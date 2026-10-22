import logging

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from app.db import AlreadyReviewed, Database, UnknownPrediction
from app.observability import FEEDBACK, FEEDBACK_INCORRECT
from app.schemas import FeedbackIn, FeedbackOut

router = APIRouter()
log = logging.getLogger(__name__)
DB_ERRORS = (psycopg.OperationalError, PoolTimeout)


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_labels(request: Request) -> list[str]:
    return request.app.state.labels


def require_reviewer(x_reviewer: str | None = Header(default=None)) -> str:
    # runs before body validation, so a missing reviewer is always 401
    if not x_reviewer or not x_reviewer.strip():
        raise HTTPException(401, "missing_reviewer")
    if len(x_reviewer) > 64:
        raise HTTPException(422, "validation_error")
    return x_reviewer


@router.post("/feedback", status_code=201, response_model=FeedbackOut)
def create_feedback(
    fb: FeedbackIn,
    reviewer: str = Depends(require_reviewer),
    db: Database = Depends(get_db),
    labels: list[str] = Depends(get_labels),
):
    if fb.is_correct and fb.corrected_label is not None:
        raise HTTPException(422, "validation_error")
    if not fb.is_correct and fb.corrected_label not in labels:
        raise HTTPException(422, "validation_error")
    try:
        pred = db.get_prediction(fb.prediction_id)
        if pred is None:
            raise HTTPException(404, "unknown_prediction")
        if fb.corrected_label == pred.predicted_label:
            raise HTTPException(422, "same_as_prediction")
        feedback_id = db.insert_feedback(
            fb.prediction_id, fb.is_correct, fb.corrected_label, reviewer
        )
    except AlreadyReviewed:
        raise HTTPException(409, "already_reviewed") from None
    except UnknownPrediction:
        raise HTTPException(404, "unknown_prediction") from None
    except DB_ERRORS:
        log.error("database unavailable")
        raise HTTPException(503, "db_unavailable") from None

    if pred.source != "smoke":
        FEEDBACK.labels(pred.model_version).inc()
        if not fb.is_correct:
            FEEDBACK_INCORRECT.labels(pred.model_version).inc()
    log.info(
        "feedback stored",
        extra={"feedback_id": feedback_id, "prediction_id": str(fb.prediction_id),
               "is_correct": fb.is_correct, "model_version": pred.model_version},
    )  # fmt: skip
    return {"feedback_id": feedback_id}


@router.get("/health")
def health(db: Database = Depends(get_db)):
    try:
        db.ping()
    except DB_ERRORS:
        return JSONResponse({"status": "degraded", "db": False}, status_code=503)
    return {"status": "ok"}
