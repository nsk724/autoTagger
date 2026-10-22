from uuid import UUID

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.schemas import Prediction, TicketIn

PENDING_SQL = """
SELECT p.prediction_id, t.ticket_id, t.subject, t.body, p.predicted_label,
       p.confidence, p.top_k, p.model_version, t.created_at
FROM predictions p
JOIN tickets t USING (ticket_id)
LEFT JOIN feedback f USING (prediction_id)
WHERE f.feedback_id IS NULL
ORDER BY t.created_at
LIMIT %s
"""


class Database:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def ping(self) -> None:
        with self.pool.connection(timeout=1) as conn:
            conn.execute("SELECT 1")

    def insert_ticket_with_prediction(
        self, ticket: TicketIn, prediction: Prediction, hf_repo: str, latency_ms: int
    ) -> tuple[UUID, UUID]:
        with self.pool.connection() as conn, conn.transaction():
            conn.execute(
                "INSERT INTO model_versions (model_version, hf_repo, status)"
                " VALUES (%s, %s, 'production') ON CONFLICT DO NOTHING",
                (prediction.model_version, hf_repo),
            )
            ticket_id = conn.execute(
                "INSERT INTO tickets (subject, body, source, dataset_label)"
                " VALUES (%s, %s, %s, %s) RETURNING ticket_id",
                (ticket.subject, ticket.body, ticket.source, ticket.dataset_label),
            ).fetchone()[0]
            prediction_id = conn.execute(
                "INSERT INTO predictions"
                " (ticket_id, model_version, predicted_label, confidence, top_k, latency_ms)"
                " VALUES (%s, %s, %s, %s, %s, %s) RETURNING prediction_id",
                (
                    ticket_id,
                    prediction.model_version,
                    prediction.label,
                    prediction.confidence,
                    Jsonb([s.model_dump() for s in prediction.top_k]),
                    latency_ms,
                ),
            ).fetchone()[0]
        return ticket_id, prediction_id

    def pending(self, limit: int) -> list[dict]:
        cols = ["prediction_id", "ticket_id", "subject", "body", "predicted_label",
                "confidence", "top_k", "model_version", "created_at"]  # fmt: skip
        with self.pool.connection() as conn:
            return [dict(zip(cols, row)) for row in conn.execute(PENDING_SQL, (limit,))]
