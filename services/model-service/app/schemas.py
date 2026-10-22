from pydantic import BaseModel, Field


class PredictIn(BaseModel):
    subject: str | None = Field(default=None, max_length=300)
    body: str = Field(min_length=1, max_length=5000)


class Score(BaseModel):
    label: str
    score: float


class PredictOut(BaseModel):
    label: str
    confidence: float
    top_k: list[Score]
    model_version: str
