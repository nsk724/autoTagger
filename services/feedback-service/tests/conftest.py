import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://triageiq:x@localhost:5432/triageiq")
os.environ.setdefault("LABELS_PATH", str(Path(__file__).parents[3] / "config" / "labels.yaml"))

from app import routes
from app.db import AlreadyReviewed, PredictionInfo
from app.main import app

LABELS = ["Technical Support", "Product Support", "Customer Service", "IT Support",
          "Billing and Payments", "Returns and Exchanges", "Sales and Pre-Sales",
          "Human Resources", "General Inquiry", "Service Outages and Maintenance"]  # fmt: skip


class FakeDB:
    def __init__(self):
        self.predictions = {}
        self.feedback = {}

    def ping(self):
        pass

    def get_prediction(self, prediction_id):
        return self.predictions.get(prediction_id)

    def insert_feedback(self, prediction_id, is_correct, corrected_label, reviewer):
        if prediction_id in self.feedback:
            raise AlreadyReviewed
        self.feedback[prediction_id] = (is_correct, corrected_label, reviewer)
        return len(self.feedback)

    def add(self, pid, source="stream", version="v1"):
        self.predictions[pid] = PredictionInfo("IT Support", version, source)


@pytest.fixture
def db():
    return FakeDB()


@pytest.fixture
def client(db):
    app.dependency_overrides = {routes.get_db: lambda: db, routes.get_labels: lambda: LABELS}
    yield TestClient(app, headers={"X-Reviewer": "alice"})
    app.dependency_overrides = {}
