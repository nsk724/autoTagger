import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://triageiq:x@localhost:5432/triageiq")
os.environ.setdefault("MODEL_SERVICE_URL", "http://model-service:8000")
os.environ.setdefault("HF_MODEL_REPO", "org/triageiq-classifier")
os.environ.setdefault("LABELS_PATH", str(Path(__file__).parents[3] / "config" / "labels.yaml"))

from app import routes
from app.clients import ModelUnavailable
from app.main import app
from app.schemas import Prediction

LABELS = ["Technical Support", "Product Support", "Customer Service", "IT Support",
          "Billing and Payments", "Returns and Exchanges", "Sales and Pre-Sales",
          "Human Resources", "General Inquiry", "Service Outages and Maintenance"]  # fmt: skip
VERSION = "b" * 40


class FakeModelClient:
    def __init__(self, fail: str | None = None):
        self.fail = fail

    def predict(self, subject, body, request_id):
        if self.fail:
            raise ModelUnavailable(self.fail)
        top_k = [
            {"label": "IT Support", "score": 0.8},
            {"label": "Product Support", "score": 0.1},
            {"label": "General Inquiry", "score": 0.05},
        ]
        return Prediction(label="IT Support", confidence=0.8, top_k=top_k, model_version=VERSION)


class FakeDB:
    def __init__(self):
        self.inserted = []

    def ping(self):
        pass

    def insert_ticket_with_prediction(self, ticket, prediction, hf_repo, latency_ms):
        self.inserted.append((ticket, prediction))
        return uuid.uuid4(), uuid.uuid4()

    def pending(self, limit):
        return [{"prediction_id": uuid.uuid4(), "ticket_id": uuid.uuid4(), "subject": None,
                 "body": "b", "predicted_label": "IT Support", "confidence": 0.8,
                 "top_k": [{"label": "IT Support", "score": 0.8}], "model_version": VERSION,
                 "created_at": datetime.now(UTC)}][:limit]  # fmt: skip


@pytest.fixture
def db():
    return FakeDB()


@pytest.fixture
def model():
    return FakeModelClient()


@pytest.fixture
def client(db, model):
    app.dependency_overrides = {
        routes.get_db: lambda: db,
        routes.get_model_client: lambda: model,
        routes.get_labels: lambda: LABELS,
        routes.get_settings: lambda: app.state.settings,
    }
    yield TestClient(app)
    app.dependency_overrides = {}
