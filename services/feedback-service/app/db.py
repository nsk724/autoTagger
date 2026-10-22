from dataclasses import dataclass
from uuid import UUID

import psycopg
from psycopg_pool import ConnectionPool


class UnknownPrediction(Exception):
    pass


class AlreadyReviewed(Exception):
    pass


@dataclass
class PredictionInfo:
    predicted_label: str
    model_version: str
    source: str


class Database:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def ping(self) -> None:
        with self.pool.connection(timeout=1) as conn:
            conn.execute("SELECT 1")

    def get_prediction(self, prediction_id: UUID) -> PredictionInfo | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT p.predicted_label, p.model_version, t.source"
                " FROM predictions p JOIN tickets t USING (ticket_id) WHERE p.prediction_id = %s",
                (prediction_id,),
            ).fetchone()
        return PredictionInfo(*row) if row else None

    def insert_feedback(
        self, prediction_id: UUID, is_correct: bool, corrected_label: str | None, reviewer: str
    ) -> int:
        try:
            with self.pool.connection() as conn:
                return conn.execute(
                    "INSERT INTO feedback (prediction_id, is_correct, corrected_label, reviewer_id)"
                    " VALUES (%s, %s, %s, %s) RETURNING feedback_id",
                    (prediction_id, is_correct, corrected_label, reviewer),
                ).fetchone()[0]
        except psycopg.errors.UniqueViolation:
            raise AlreadyReviewed from None
        except psycopg.errors.ForeignKeyViolation:
            raise UnknownPrediction from None
