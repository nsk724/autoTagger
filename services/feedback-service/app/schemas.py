from uuid import UUID

from pydantic import BaseModel, Field


class FeedbackIn(BaseModel):
    prediction_id: UUID
    is_correct: bool
    corrected_label: str | None = Field(default=None, max_length=100)


class FeedbackOut(BaseModel):
    feedback_id: int
