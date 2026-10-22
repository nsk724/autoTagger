import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import routes
from app.main import app

from .conftest import LABELS

pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    app.dependency_overrides = {routes.get_labels: lambda: LABELS}
    with TestClient(app, headers={"X-Reviewer": "it-reviewer"}) as c:
        yield c
    app.dependency_overrides = {}


@pytest.fixture
def conn():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c:
        yield c


def add_prediction(conn, source):
    conn.execute(
        "INSERT INTO model_versions (model_version, hf_repo, status)"
        " VALUES ('it-fb', 'x', 'production') ON CONFLICT DO NOTHING"
    )
    tid = conn.execute(
        "INSERT INTO tickets (body, source) VALUES ('fb it', %s) RETURNING ticket_id", (source,)
    ).fetchone()[0]
    pid = conn.execute(
        "INSERT INTO predictions (ticket_id, model_version, predicted_label, confidence, top_k)"
        " VALUES (%s, 'it-fb', 'IT Support', 0.5, '[]') RETURNING prediction_id",
        (tid,),
    ).fetchone()[0]
    return tid, pid


def test_feedback_flow(client, conn):
    created = [add_prediction(conn, "stream"), add_prediction(conn, "smoke")]
    try:
        (_, pid), (_, smoke_pid) = created
        body = {
            "prediction_id": str(pid),
            "is_correct": False,
            "corrected_label": "Product Support",
        }
        assert client.post("/feedback", json=body).status_code == 201
        assert client.post("/feedback", json=body).status_code == 409
        smoke = {"prediction_id": str(smoke_pid), "is_correct": True, "corrected_label": None}
        assert client.post("/feedback", json=smoke).status_code == 201

        rows = conn.execute(
            "SELECT ticket_id, label, reviewer_id FROM labeled_feedback WHERE ticket_id = ANY(%s)",
            ([t for t, _ in created],),
        ).fetchall()
        assert [(r[1], r[2]) for r in rows] == [("Product Support", "it-reviewer")]
    finally:
        pids = [p for _, p in created]
        conn.execute("DELETE FROM feedback WHERE prediction_id = ANY(%s)", (pids,))
        conn.execute("DELETE FROM predictions WHERE prediction_id = ANY(%s)", (pids,))
        conn.execute("DELETE FROM tickets WHERE ticket_id = ANY(%s)", ([t for t, _ in created],))
