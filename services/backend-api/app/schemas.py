from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class Score(BaseModel):
    label: str
    score: float


class Prediction(BaseModel):
    label: str
    confidence: float
    top_k: list[Score] = Field(min_length=1, max_length=3)
    model_version: str = Field(min_length=1, max_length=64)


class TicketIn(BaseModel):
    subject: str | None = Field(default=None, max_length=300)
    body: str = Field(min_length=1, max_length=5000)
    source: Literal["stream", "manual", "smoke"]
    dataset_label: str | None = None

    @model_validator(mode="after")
    def dataset_label_only_for_stream(self):
        if self.dataset_label is not None and self.source != "stream":
            raise ValueError("dataset_label is only allowed for source=stream")
        return self


class PredictionOut(Prediction):
    prediction_id: UUID


class TicketOut(BaseModel):
    ticket_id: UUID
    prediction: PredictionOut


class PendingItem(BaseModel):
    prediction_id: UUID
    ticket_id: UUID
    subject: str | None
    body: str
    predicted_label: str
    confidence: float
    top_k: list[Score]
    model_version: str
    created_at: datetime


class LabelsOut(BaseModel):
    labels: list[str]
