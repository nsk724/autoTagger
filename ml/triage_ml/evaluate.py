import argparse
import json
import os
import sys
from pathlib import Path

import joblib
import pandas as pd
import psycopg

from triage_ml.config import PROCESSED
from triage_ml.train import features, score, sentence_embedder

GOLDEN_TOLERANCE = 0.02  # challenger may lose at most this much golden macro-F1
MIN_HOLDOUT_ROWS = 20
WIN, LOSE, TINY_HOLDOUT = 0, 3, 4


def decide(champion: dict, challenger: dict, holdout_rows: int) -> tuple[int, str]:
    if holdout_rows < MIN_HOLDOUT_ROWS:
        return TINY_HOLDOUT, f"feedback holdout has {holdout_rows} rows (< {MIN_HOLDOUT_ROWS})"
    floor = champion["golden_macro_f1"] - GOLDEN_TOLERANCE
    if challenger["golden_macro_f1"] < floor:
        return LOSE, (
            f"golden regression: {challenger['golden_macro_f1']:.4f} < {floor:.4f} "
            f"(champion {champion['golden_macro_f1']:.4f} - {GOLDEN_TOLERANCE})"
        )
    if challenger["feedback_macro_f1"] <= champion["feedback_macro_f1"]:
        return LOSE, (
            f"no feedback gain: {challenger['feedback_macro_f1']:.4f} <= "
            f"{champion['feedback_macro_f1']:.4f}"
        )
    return WIN, "challenger wins"


def production_version(conn) -> str:
    row = conn.execute(
        "SELECT model_version FROM model_versions WHERE status = 'production' "
        "ORDER BY promoted_at DESC NULLS LAST, created_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise SystemExit("no production model in model_versions")
    return row[0]


def download_champion(repo: str, sha: str, token: str | None) -> Path:
    from huggingface_hub import snapshot_download

    return Path(
        snapshot_download(
            repo,
            revision=sha,
            token=token,
            allow_patterns=["classifier.joblib", "metadata.json"],
        )
    )


def score_models(dirs: dict[str, Path], golden: pd.DataFrame, holdout: pd.DataFrame, embed_fn):
    X_golden, X_holdout = features(golden, embed_fn), features(holdout, embed_fn)
    scores = {}
    for name, d in dirs.items():
        clf = joblib.load(d / "classifier.joblib")  # our own private repo at a pinned sha only
        g, f = score(clf, X_golden, golden.label), score(clf, X_holdout, holdout.label)
        scores[name] = {
            "golden_macro_f1": g["macro_f1"],
            "golden_accuracy": g["accuracy"],
            "feedback_macro_f1": f["macro_f1"],
            "feedback_accuracy": f["accuracy"],
        }
    return scores


def main(argv: list[str] | None = None, embed_fn=None) -> int:
    p = argparse.ArgumentParser(description="Champion vs challenger.")
    p.add_argument("--challenger", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--no-mlflow", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    repo = os.environ.get("HF_MODEL_REPO")
    if args.dry_run:
        print(f"would load the production version from DATABASE_URL, download it from {repo},")
        print(f"score it and {args.challenger} on golden + feedback_holdout, write {args.out}")
        return 0

    holdout = pd.read_parquet(args.challenger / "feedback_holdout.parquet")
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        champion_version = production_version(conn)
    champion_dir = download_champion(repo, champion_version, os.environ.get("HF_TOKEN_READ"))

    if len(holdout) < MIN_HOLDOUT_ROWS:
        code, reason, scores = TINY_HOLDOUT, f"feedback holdout has {len(holdout)} rows", {}
    else:
        meta = json.loads((args.challenger / "metadata.json").read_text())
        embed_fn = embed_fn or sentence_embedder(meta["encoder"], meta["encoder_revision"])
        golden = pd.read_parquet(PROCESSED / "golden.parquet")
        scores = score_models(
            {"champion": champion_dir, "challenger": args.challenger}, golden, holdout, embed_fn
        )
        code, reason = decide(scores["champion"], scores["challenger"], len(holdout))

    result = {
        "decision": {0: "win", 3: "lose", 4: "tiny_holdout"}[code],
        "reason": reason,
        "exit_code": code,
        "champion_version": champion_version,
        "holdout_rows": len(holdout),
        **scores,
    }
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))

    run_id = json.loads((args.challenger / "metadata.json").read_text()).get("mlflow_run_id")
    if run_id and scores and not args.no_mlflow:
        import mlflow

        with mlflow.start_run(run_id=run_id):
            for who, s in scores.items():
                mlflow.log_metrics({f"eval_{who}_{k}": v for k, v in s.items()})
            mlflow.set_tag("eval_decision", result["decision"])
            mlflow.set_tag("champion_version", champion_version)
            mlflow.log_artifact(str(args.out))
    return code


if __name__ == "__main__":
    sys.exit(main())
