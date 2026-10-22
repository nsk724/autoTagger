import logging
import time

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from app.clients import ModelClient, ModelUnavailable
from app.db import Database
from app.observability import PREDICTIONS, request_id_var
from app.schemas import LabelsOut, PendingItem, TicketIn, TicketOut
from app.settings import Settings

router = APIRouter()
log = logging.getLogger(__name__)
DB_ERRORS = (psycopg.OperationalError, PoolTimeout)


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_model_client(request: Request) -> ModelClient:
    return request.app.state.model_client


def get_labels(request: Request) -> list[str]:
    return request.app.state.labels


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


@router.post("/tickets", status_code=201, response_model=TicketOut)
def create_ticket(
    ticket: TicketIn,
    db: Database = Depends(get_db),
    model: ModelClient = Depends(get_model_client),
    labels: list[str] = Depends(get_labels),
    settings: Settings = Depends(get_settings),
):
    if ticket.dataset_label is not None and ticket.dataset_label not in labels:
        raise HTTPException(422, "validation_error")
    start = time.perf_counter()
    try:
        prediction = model.predict(ticket.subject, ticket.body, request_id_var.get())
    except ModelUnavailable as e:
        log.warning("model call failed", extra={"reason": e.reason})
        raise HTTPException(502, "model_unavailable") from None
    latency_ms = round((time.perf_counter() - start) * 1000)
    try:
        ticket_id, prediction_id = db.insert_ticket_with_prediction(
            ticket, prediction, settings.hf_model_repo, latency_ms
        )
    except DB_ERRORS:
        log.error("database unavailable")
        raise HTTPException(503, "db_unavailable") from None
    if ticket.source != "smoke":
        PREDICTIONS.labels(prediction.model_version, prediction.label).inc()
    log.info(
        "ticket stored",
        extra={"ticket_id": str(ticket_id), "prediction_id": str(prediction_id),
               "source": ticket.source, "model_version": prediction.model_version},
    )  # fmt: skip
    return {
        "ticket_id": ticket_id,
        "prediction": {"prediction_id": prediction_id, **prediction.model_dump()},
    }


@router.get("/tickets/pending", response_model=list[PendingItem])
def pending(limit: int = Query(20, ge=1, le=100), db: Database = Depends(get_db)):
    try:
        return db.pending(limit)
    except DB_ERRORS:
        log.error("database unavailable")
        raise HTTPException(503, "db_unavailable") from None


@router.get("/labels", response_model=LabelsOut)
def get_label_list(labels: list[str] = Depends(get_labels)):
    return {"labels": labels}


@router.get("/health")
def health(db: Database = Depends(get_db)):
    try:
        db.ping()
    except DB_ERRORS:
        return JSONResponse({"status": "degraded", "db": False}, status_code=503)
    return {"status": "ok"}
