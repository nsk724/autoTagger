import argparse
import hashlib
import json
import os
import subprocess  # nosec B404: fixed git command, no user input
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import yaml
from sklearn.compose import ColumnTransformer, make_column_selector
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from triage_ml.config import PROCESSED, ROOT
from triage_ml.text import EMB_PREFIX, feature_frame

ENCODER = "sentence-transformers/all-MiniLM-L6-v2"
ENCODER_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
# widened from the guide's {0.1, 1, 10}: the TF-IDF features need weaker regularisation
C_GRID = [1.0, 10.0, 100.0]
SEED = 42
EXPERIMENT = "triageiq-classifier"
ARTIFACT_FILES = [
    "classifier.joblib",
    "metadata.json",
    "README.md",
    "classification_report.txt",
    "confusion_matrix.csv",
]

EmbedFn = Callable[[Iterable[str]], np.ndarray]


def sentence_embedder(name: str = ENCODER, revision: str = ENCODER_REVISION) -> EmbedFn:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(name, revision=revision, device="cpu")
    return lambda texts: model.encode(list(texts), batch_size=64, normalize_embeddings=True)


def score(clf, X: pd.DataFrame, y: pd.Series) -> dict:
    # macro over the classes present in y, so a class only the challenger knows can't skew it
    labels = sorted(set(y))
    pred = clf.predict(X)
    per_class = f1_score(y, pred, labels=labels, average=None, zero_division=0)
    return {
        "accuracy": float(accuracy_score(y, pred)),
        "macro_f1": float(f1_score(y, pred, labels=labels, average="macro", zero_division=0)),
        "per_class_f1": {k: float(v) for k, v in zip(labels, per_class)},
    }


def file_md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


def split_feedback(fb: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    stratify = fb.label if fb.label.value_counts().min() >= 2 else None
    return train_test_split(fb, test_size=0.2, stratify=stratify, random_state=SEED)


def features(df: pd.DataFrame, embed_fn: EmbedFn) -> pd.DataFrame:
    return feature_frame(df.text, embed_fn(df.text))


def make_classifier(C: float) -> Pipeline:
    """TF-IDF of the text + the sentence embedding, side by side, into one linear model."""
    return Pipeline([
        ("features", ColumnTransformer([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True), "text"),
            ("emb", "passthrough", make_column_selector(pattern=f"^{EMB_PREFIX}")),
        ])),
        ("clf", LogisticRegression(C=C, class_weight="balanced", max_iter=3000)),
    ])  # fmt: skip


def fit(train_df: pd.DataFrame, val_df: pd.DataFrame, embed_fn: EmbedFn):
    X_train, X_val = features(train_df, embed_fn), features(val_df, embed_fn)
    best = None
    for C in C_GRID:
        clf = make_classifier(C).fit(X_train, train_df.label)
        val_f1 = score(clf, X_val, val_df.label)["macro_f1"]
        if best is None or val_f1 > best[1]:
            best = (clf, val_f1, C)
    return best


def model_card(meta: dict) -> str:
    m = meta["metrics"]
    return f"""---
license: cc-by-nc-4.0
tags: [text-classification, sentence-transformers, scikit-learn, tf-idf]
datasets: [Tobi-Bueck/customer-support-tickets]
---
# TriageIQ ticket queue classifier

Predicts the support queue of a ticket. A scikit-learn Pipeline: word 1-2-gram TF-IDF of the
text, concatenated with normalized `{meta["encoder"]}` embeddings (revision
`{meta["encoder_revision"]}`), into `LogisticRegression(C={meta["C"]}, class_weight="balanced")`.
Input: `feature_frame(texts, embeddings)` from `triage_ml/text.py`.

Classes: {", ".join(meta["classes"])}

Golden set: accuracy {m["golden_accuracy"]:.3f}, macro-F1 {m["golden_macro_f1"]:.3f}.

## Data and license
Trained on [Tobi-Bueck/customer-support-tickets](https://huggingface.co/datasets/Tobi-Bueck/customer-support-tickets)
(DOI 10.57967/hf/6184, revision `{meta["data"]["dataset_revision"]}`), English rows of the 10
helpdesk queues, plus reviewer corrections when retrained. The dataset is licensed
**CC BY-NC 4.0**, so this model is for non-commercial use only.

`classifier.joblib` is a pickle: load it only from this repository at a pinned revision.
"""


def run(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    golden_df: pd.DataFrame,
    embed_fn: EmbedFn,
    out: Path,
    data_meta: dict,
    mlflow_run_id: str | None = None,
) -> dict:
    clf, val_f1, C = fit(train_df, val_df, embed_fn)
    X_golden = features(golden_df, embed_fn)
    golden = score(clf, X_golden, golden_df.label)
    pred = clf.predict(X_golden)

    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(clf, out / "classifier.joblib")
    labels = sorted(set(golden_df.label) | set(pred))
    cm = pd.DataFrame(
        confusion_matrix(golden_df.label, pred, labels=labels), index=labels, columns=labels
    )
    cm.to_csv(out / "confusion_matrix.csv")
    (out / "classification_report.txt").write_text(
        classification_report(golden_df.label, pred, zero_division=0)
    )
    metrics = {
        "val_macro_f1": val_f1,
        "golden_accuracy": golden["accuracy"],
        "golden_macro_f1": golden["macro_f1"],
        "golden_per_class_f1": golden["per_class_f1"],
    }
    meta = {
        "features": "tfidf_1-2gram + sentence_embedding",
        "encoder": ENCODER,
        "encoder_revision": ENCODER_REVISION,
        "classes": [str(c) for c in clf.classes_],
        "C": C,
        "trained_at": datetime.now(UTC).isoformat(),
        "mlflow_run_id": mlflow_run_id,
        "data": data_meta,
        "metrics": metrics,
        "rows": {"train": len(train_df), "val": len(val_df), "golden": len(golden_df)},
    }
    (out / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
    (out / "README.md").write_text(model_card(meta))
    return meta


def git_sha() -> str:
    if os.environ.get("GIT_COMMIT"):
        return os.environ["GIT_COMMIT"]
    try:
        return subprocess.run(  # nosec B603 B607: fixed command
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def log_to_mlflow(meta: dict, out: Path, dvc_files: list[Path]) -> None:
    import mlflow

    params = {
        "encoder": meta["encoder"],
        "encoder_revision": meta["encoder_revision"],
        "C": meta["C"],
        "class_weight": "balanced",
        **{f"rows_{k}": v for k, v in meta["rows"].items()},
        **meta["data"],
    }
    mlflow.log_params(params)
    m = meta["metrics"]
    metrics = {k: m[k] for k in ("val_macro_f1", "golden_accuracy", "golden_macro_f1")}
    for label, f1 in m["golden_per_class_f1"].items():
        metrics[f"golden_f1_{label.replace(' ', '_')}"] = f1
    mlflow.log_metrics(metrics)
    mlflow.log_artifacts(str(out))
    for f in dvc_files:
        if f.exists():
            mlflow.log_artifact(str(f), artifact_path="dvc")


def stratified_sample(df: pd.DataFrame, n: int) -> pd.DataFrame:
    if n >= len(df):
        return df
    return train_test_split(df, train_size=n, stratify=df.label, random_state=SEED)[0]


def main(argv: list[str] | None = None, embed_fn: EmbedFn | None = None) -> None:
    p = argparse.ArgumentParser(description="Train the queue classifier.")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--feedback-snapshot", type=Path)
    p.add_argument("--sample", type=int, help="stratified rows per split, for quick runs")
    p.add_argument("--no-mlflow", action="store_true")
    p.add_argument("--run-id", help="training_runs.run_id, recorded as an MLflow tag")
    p.add_argument("--data-dir", type=Path, default=PROCESSED)
    args = p.parse_args(argv)

    train_df, val_df, golden_df = (
        pd.read_parquet(args.data_dir / f"{n}.parquet") for n in ("train", "val", "golden")
    )
    if args.sample:
        train_df, val_df, golden_df = (
            stratified_sample(d, args.sample) for d in (train_df, val_df, golden_df)
        )

    stats_path = args.data_dir / "stats.json"
    processed_dvc = ROOT / "data" / "processed.dvc"
    data_meta = {
        "dataset_revision": json.loads(stats_path.read_text())["dataset_revision"]
        if stats_path.exists()
        else None,
        "processed_md5": yaml.safe_load(processed_dvc.read_text())["outs"][0]["md5"]
        if processed_dvc.exists()
        else None,
        "feedback_md5": None,
    }
    dvc_files = [processed_dvc]
    if args.feedback_snapshot:
        fb = pd.read_parquet(args.feedback_snapshot)
        data_meta["feedback_md5"] = file_md5(args.feedback_snapshot)
        fb_train, fb_holdout = split_feedback(fb)
        train_df = pd.concat([train_df[["text", "label"]], fb_train[["text", "label"]]])
        args.out.mkdir(parents=True, exist_ok=True)
        fb_holdout.to_parquet(args.out / "feedback_holdout.parquet", index=False)
        dvc_files.append(args.feedback_snapshot.with_name(args.feedback_snapshot.name + ".dvc"))

    embed_fn = embed_fn or sentence_embedder()
    if args.no_mlflow:
        meta = run(train_df, val_df, golden_df, embed_fn, args.out, data_meta)
        print(json.dumps(meta["metrics"], indent=2))
        return

    import mlflow

    mlflow.set_experiment(EXPERIMENT)
    tags = {"git_sha": git_sha(), "trigger": os.environ.get("TRIGGER", "manual")}
    if args.run_id:
        tags["training_run_id"] = args.run_id
    with mlflow.start_run(tags=tags) as active:
        meta = run(train_df, val_df, golden_df, embed_fn, args.out, data_meta, active.info.run_id)
        log_to_mlflow(meta, args.out, dvc_files)
    print(json.dumps(meta["metrics"], indent=2))


if __name__ == "__main__":
    main()
