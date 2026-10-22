import psycopg
import pytest
from prometheus_client import REGISTRY

from .conftest import VERSION, FakeModelClient

TICKET = {
    "subject": "VPN down",
    "body": "Cannot connect",
    "source": "manual",
    "dataset_label": None,
}


def predictions_count(label="IT Support"):
    v = REGISTRY.get_sample_value(
        "triageiq_predictions_total", {"model_version": VERSION, "label": label}
    )
    return v or 0


def test_create_ticket(client, db):
    before = predictions_count()
    r = client.post("/tickets", json=TICKET)
    assert r.status_code == 201
    pred = r.json()["prediction"]
    assert pred["label"] == "IT Support" and pred["model_version"] == VERSION
    assert "prediction_id" in pred and "ticket_id" in r.json()
    assert len(db.inserted) == 1
    assert predictions_count() == before + 1


def test_smoke_ticket_not_counted(client):
    before = predictions_count()
    assert client.post("/tickets", json={**TICKET, "source": "smoke"}).status_code == 201
    assert predictions_count() == before


@pytest.mark.parametrize(
    "body",
    [
        {**TICKET, "body": ""},
        {**TICKET, "body": "x" * 5001},
        {**TICKET, "source": "stream", "dataset_label": "Not A Queue"},
        {**TICKET, "dataset_label": "IT Support"},  # dataset_label with source manual
        {**TICKET, "subject": "s" * 301},
    ],
)
def test_create_ticket_validation(client, db, body):
    r = client.post("/tickets", json=body)
    assert r.status_code == 422
    assert r.json() == {"detail": "validation_error"}
    assert db.inserted == []


def test_stream_ticket_with_dataset_label(client):
    body = {**TICKET, "source": "stream", "dataset_label": "IT Support"}
    assert client.post("/tickets", json=body).status_code == 201


@pytest.mark.parametrize("reason", ["timeout", "http_error", "bad_response"])
def test_model_down_writes_nothing(client, db, model, reason):
    model.fail = reason
    r = client.post("/tickets", json=TICKET)
    assert r.status_code == 502
    assert r.json() == {"detail": "model_unavailable"}
    assert db.inserted == []


def test_db_down(client, db):
    def boom(*a):
        raise psycopg.OperationalError("down")

    db.insert_ticket_with_prediction = boom
    db.pending = boom
    db.ping = boom
    assert client.post("/tickets", json=TICKET).json() == {"detail": "db_unavailable"}
    assert client.get("/tickets/pending").status_code == 503
    r = client.get("/health")
    assert r.status_code == 503 and r.json() == {"status": "degraded", "db": False}


def test_pending(client):
    r = client.get("/tickets/pending?limit=5")
    assert r.status_code == 200 and r.json()[0]["predicted_label"] == "IT Support"
    assert client.get("/tickets/pending?limit=0").status_code == 422
    assert client.get("/tickets/pending?limit=101").status_code == 422


def test_labels_and_health(client):
    assert len(client.get("/labels").json()["labels"]) == 10
    assert client.get("/health").json() == {"status": "ok"}


def test_request_id_forwarded(client, model):
    seen = {}

    def predict(subject, body, request_id):
        seen["rid"] = request_id
        return FakeModelClient().predict(subject, body, request_id)

    model.predict = predict
    client.post("/tickets", json=TICKET, headers={"X-Request-ID": "abc-123"})
    assert seen["rid"] == "abc-123"
