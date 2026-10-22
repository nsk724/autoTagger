import hashlib

import numpy as np
import pandas as pd
import pytest

WORDS = {
    "Technical Support": "printer",
    "Billing and Payments": "invoice",
    "Human Resources": "salary",
}


def _embed(texts):
    """Deterministic 8 floats per text; the label word shows up so a model can learn."""
    out = []
    for t in texts:
        v = np.frombuffer(hashlib.sha256(t.encode()).digest()[:8], dtype=np.uint8) / 255
        v[:4] += 5 * np.array([w in t for w in ("printer", "invoice", "salary", "outage")])
        out.append(v)
    return np.array(out)


@pytest.fixture
def fake_embed():
    return _embed


def make_split(n_per_label: int, offset: int) -> pd.DataFrame:
    rows = [
        {"row_id": offset + i * 10 + j, "text": f"{w} issue {offset + i}", "label": label}
        for i in range(n_per_label)
        for j, (label, w) in enumerate(WORDS.items())
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "processed"
    d.mkdir()
    make_split(8, 0).to_parquet(d / "train.parquet")
    make_split(3, 100).to_parquet(d / "val.parquet")
    make_split(3, 200).to_parquet(d / "golden.parquet")
    (d / "stats.json").write_text('{"dataset_revision": "abc"}')
    return d
