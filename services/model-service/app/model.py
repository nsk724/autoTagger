import json
import logging
import threading
import time
from dataclasses import dataclass

import joblib
import numpy as np

from app.settings import Settings
from app.text import build_text, feature_frame

log = logging.getLogger(__name__)
RETRY_SECONDS = 30


@dataclass
class LoadedModel:
    classifier: object
    encoder: object
    version: str
    encoder_name: str

    def predict(self, subject: str | None, body: str) -> dict:
        text = build_text(subject, body)
        x = feature_frame([text], self.encoder.encode([text], normalize_embeddings=True))
        proba = self.classifier.predict_proba(x)[0]
        top = np.argsort(proba)[::-1][:3]
        top_k = [{"label": str(self.classifier.classes_[i]), "score": float(proba[i])} for i in top]
        return {
            "label": top_k[0]["label"],
            "confidence": top_k[0]["score"],
            "top_k": top_k,
            "model_version": self.version,
        }


class ModelHolder:
    model: LoadedModel | None = None


def load(settings: Settings) -> LoadedModel:
    from huggingface_hub import HfApi, hf_hub_download
    from sentence_transformers import SentenceTransformer

    repo, token = settings.hf_model_repo, settings.hf_token
    sha = HfApi(token=token).model_info(repo, revision=settings.model_revision).sha
    path = {
        f: hf_hub_download(repo, f, revision=sha, token=token)
        for f in ("classifier.joblib", "metadata.json")
    }
    with open(path["metadata.json"]) as fh:
        meta = json.load(fh)
    classifier = joblib.load(path["classifier.joblib"])  # our private repo at a pinned sha only
    encoder = SentenceTransformer(meta["encoder"], revision=meta["encoder_revision"], device="cpu")
    return LoadedModel(classifier, encoder, sha, meta["encoder"])


def load_in_background(holder: ModelHolder, settings: Settings) -> threading.Thread:
    def worker() -> None:
        while holder.model is None:
            try:
                holder.model = load(settings)
                log.info("model loaded", extra={"model_version": holder.model.version})
            except Exception as e:  # keep retrying: HF may be briefly unreachable
                log.warning("model load failed, retrying", extra={"error": type(e).__name__})
                time.sleep(RETRY_SECONDS)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread
