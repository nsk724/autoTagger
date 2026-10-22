import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import routes
from app.main import app

from .conftest import LABELS, FakeModelClient

pytestmark = pytest.mark.integration
VERSION = "b" * 40


@pytest.fixture
def client():
    app.dependency_overrides = {
        routes.get_model_client: FakeModelClient,
        routes.get_labels: lambda: LABELS,
    }
    with TestClient(app) as c:  # lifespan opens the real pool
        yield c
    app.dependency_overrides = {}


@pytest.fixture
def conn():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c:
        yield c


def test_ticket_prediction_and_pending(client, conn):
    created = []
    try:
        body = {
            "subject": "it",
            "body": "integration test",
            "source": "manual",
            "dataset_label": None,
        }
        for _ in range(2):
            r = client.post("/tickets", json=body)
            assert r.status_code == 201
            created.append(r.json())
        tids = [c["ticket_id"] for c in created]
        assert conn.execute("SELECT count(*) FROM tickets WHERE ticket_id = ANY(%s::uuid[])",
                            (tids,)).fetchone()[0] == 2  # fmt: skip
        assert conn.execute("SELECT count(*) FROM model_versions WHERE model_version = %s",
                            (VERSION,)).fetchone()[0] == 1  # fmt: skip

        reviewed = created[0]["prediction"]["prediction_id"]
        conn.execute(
            "INSERT INTO feedback (prediction_id, is_correct, reviewer_id) VALUES (%s, true, 'it')",
            (reviewed,),
        )
        pending = {p["prediction_id"] for p in client.get("/tickets/pending?limit=100").json()}
        assert reviewed not in pending
        assert created[1]["prediction"]["prediction_id"] in pending
    finally:
        tids = [c["ticket_id"] for c in created]
        conn.execute("DELETE FROM feedback WHERE prediction_id IN (SELECT prediction_id"
                     " FROM predictions WHERE ticket_id = ANY(%s::uuid[]))", (tids,))  # fmt: skip
        conn.execute("DELETE FROM predictions WHERE ticket_id = ANY(%s::uuid[])", (tids,))
        conn.execute("DELETE FROM tickets WHERE ticket_id = ANY(%s::uuid[])", (tids,))
