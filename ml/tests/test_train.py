import json

import pandas as pd

from triage_ml import train
from triage_ml.prepare import COLUMNS

META_KEYS = {"encoder", "encoder_revision", "classes", "C", "trained_at", "mlflow_run_id"}


def test_baseline_writes_all_artifacts(data_dir, tmp_path, fake_embed):
    out = tmp_path / "artifacts"
    train.main(["--out", str(out), "--no-mlflow", "--data-dir", str(data_dir)], embed_fn=fake_embed)

    for f in train.ARTIFACT_FILES:
        assert (out / f).exists(), f
    meta = json.loads((out / "metadata.json").read_text())
    assert META_KEYS | {"data", "metrics"} <= set(meta)
    assert set(meta["data"]) == {"dataset_revision", "processed_md5", "feedback_md5"}
    assert meta["data"]["dataset_revision"] == "abc"
    assert meta["C"] in train.C_GRID
    assert "CC BY-NC 4.0" in (out / "README.md").read_text()


def test_feedback_snapshot_adds_new_class(data_dir, tmp_path, fake_embed):
    fb = pd.DataFrame(
        {"row_id": range(40), "text": [f"outage number {i}" for i in range(40)],
         "subject": None, "body": "x", "label": "Service Outages and Maintenance",
         "priority": None, "type": None, "language": None, "version": None}
    )[COLUMNS]  # fmt: skip
    snap = tmp_path / "feedback_40.parquet"
    fb.to_parquet(snap)
    out = tmp_path / "artifacts"

    args = ["--out", str(out), "--no-mlflow", "--data-dir", str(data_dir)]
    train.main([*args, "--feedback-snapshot", str(snap)], embed_fn=fake_embed)

    meta = json.loads((out / "metadata.json").read_text())
    assert "Service Outages and Maintenance" in meta["classes"]
    assert meta["rows"]["train"] == 24 + 32  # base train + 80% of the feedback
    assert len(pd.read_parquet(out / "feedback_holdout.parquet")) == 8
    assert meta["data"]["feedback_md5"] == train.file_md5(snap)
