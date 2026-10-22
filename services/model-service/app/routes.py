from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.model import LoadedModel, ModelHolder
from app.schemas import PredictIn, PredictOut

router = APIRouter()


def get_holder(request: Request) -> ModelHolder:
    return request.app.state.holder


def get_model(holder: ModelHolder = Depends(get_holder)) -> LoadedModel:
    if holder.model is None:
        raise HTTPException(503, "model_loading")
    return holder.model


@router.post("/predict", response_model=PredictOut)
def predict(req: PredictIn, model: LoadedModel = Depends(get_model)) -> dict:
    return model.predict(req.subject, req.body)


@router.get("/health")
def health(holder: ModelHolder = Depends(get_holder)):
    if holder.model is None:
        return JSONResponse({"status": "loading"}, status_code=503)
    return {
        "status": "ok",
        "model_version": holder.model.version,
        "encoder": holder.model.encoder_name,
    }
