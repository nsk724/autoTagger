import os
import sys

import pytest
from fastapi.testclient import TestClient

import triage_ml.text

# the image copies ml/triage_ml/text.py to app/text.py; tests import the original instead
sys.modules["app.text"] = triage_ml.text
os.environ.setdefault("HF_MODEL_REPO", "org/triageiq-classifier")

from app.main import app
from app.model import ModelHolder


class FakeModel:
    version = "a" * 40
    encoder_name = "fake-encoder"

    def predict(self, subject, body):
        top_k = [{"label": "IT Support", "score": 0.7}, {"label": "Product Support", "score": 0.2},
                 {"label": "General Inquiry", "score": 0.1}]  # fmt: skip
        return {"label": "IT Support", "confidence": 0.7, "top_k": top_k,
                "model_version": self.version}  # fmt: skip


@pytest.fixture
def holder():
    h = ModelHolder()
    app.state.holder = h
    return h


@pytest.fixture
def client(holder):
    return TestClient(app)  # no `with`: lifespan (the HF download) never runs
