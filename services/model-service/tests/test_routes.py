import numpy as np

from app.model import LoadedModel

from .conftest import FakeModel


def test_predict_happy_path(client, holder):
    holder.model = FakeModel()
    r = client.post("/predict", json={"subject": "VPN", "body": "cannot connect"})
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "IT Support"
    assert len(body["top_k"]) == 3
    assert [s["score"] for s in body["top_k"]] == sorted(
        (s["score"] for s in body["top_k"]), reverse=True
    )


def test_predict_validation(client, holder):
    holder.model = FakeModel()
    assert client.post("/predict", json={"body": ""}).status_code == 422
    r = client.post("/predict", json={"body": "x" * 5001})
    assert r.status_code == 422
    assert r.json() == {"detail": "validation_error"}


def test_loading_then_ready(client, holder):
    assert client.post("/predict", json={"body": "hi"}).json() == {"detail": "model_loading"}
    assert client.get("/health").status_code == 503
    holder.model = FakeModel()
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["model_version"] == "a" * 40


def test_loaded_model_ranks_top3():
    class Clf:
        classes_ = np.array(["a", "b", "c", "d"])

        def predict_proba(self, x):
            return np.array([[0.1, 0.5, 0.15, 0.25]])

    class Enc:
        def encode(self, texts, normalize_embeddings):
            return np.zeros((1, 2))

    out = LoadedModel(Clf(), Enc(), "sha", "enc").predict(None, "body")
    assert [s["label"] for s in out["top_k"]] == ["b", "d", "c"]
    assert out["confidence"] == 0.5


def test_metrics(client):
    assert client.get("/metrics").status_code == 200
