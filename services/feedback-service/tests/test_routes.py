import uuid

import psycopg
import pytest
from prometheus_client import REGISTRY


def counter(name, version):
    return REGISTRY.get_sample_value(f"{name}_total", {"model_version": version}) or 0


def post(client, pid, is_correct=True, label=None, **kw):
    body = {"prediction_id": str(pid), "is_correct": is_correct, "corrected_label": label}
    return client.post("/feedback", json=body, **kw)


def test_correct_and_incorrect_counted(client, db):
    version = f"v-{uuid.uuid4()}"
    pids = [uuid.uuid4() for _ in range(5)]
    for p in pids:
        db.add(p, version=version)
    for p in pids[:3]:
        assert post(client, p).status_code == 201
    for p in pids[3:]:
        assert post(client, p, False, "Product Support").status_code == 201
    assert counter("triageiq_feedback", version) == 5
    assert counter("triageiq_feedback_incorrect", version) == 2
    assert db.feedback[pids[0]] == (True, None, "alice")


def test_smoke_not_counted(client, db):
    version, pid = f"v-{uuid.uuid4()}", uuid.uuid4()
    db.add(pid, source="smoke", version=version)
    assert post(client, pid, False, "Product Support").status_code == 201
    assert counter("triageiq_feedback", version) == 0
    assert counter("triageiq_feedback_incorrect", version) == 0


@pytest.mark.parametrize("headers", [{"X-Reviewer": ""}, {"X-Reviewer": "  "}])
def test_missing_reviewer(client, db, headers):
    r = post(client, uuid.uuid4(), headers=headers)
    assert (r.status_code, r.json()) == (401, {"detail": "missing_reviewer"})


def test_missing_reviewer_beats_body_validation(client):
    r = client.post("/feedback", json={"bad": 1}, headers={"X-Reviewer": ""})
    assert r.status_code == 401


@pytest.mark.parametrize(
    ("is_correct", "label", "detail"),
    [
        (True, "Product Support", "validation_error"),  # label given although correct
        (False, None, "validation_error"),  # label missing
        (False, "Not A Queue", "validation_error"),
        (False, "IT Support", "same_as_prediction"),
    ],
)
def test_validation(client, db, is_correct, label, detail):
    pid = uuid.uuid4()
    db.add(pid)
    r = post(client, pid, is_correct, label)
    assert (r.status_code, r.json()) == (422, {"detail": detail})


def test_unknown_prediction(client):
    r = post(client, uuid.uuid4())
    assert (r.status_code, r.json()) == (404, {"detail": "unknown_prediction"})


def test_already_reviewed(client, db):
    pid = uuid.uuid4()
    db.add(pid)
    assert post(client, pid).status_code == 201
    r = post(client, pid)
    assert (r.status_code, r.json()) == (409, {"detail": "already_reviewed"})


def test_db_down(client, db):
    def boom(*a):
        raise psycopg.OperationalError("down")

    db.get_prediction = boom
    db.ping = boom
    assert post(client, uuid.uuid4()).json() == {"detail": "db_unavailable"}
    assert client.get("/health").status_code == 503
