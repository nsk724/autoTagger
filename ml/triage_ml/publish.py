import argparse
import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from triage_ml.train import ARTIFACT_FILES


def record_candidate(conn, sha: str, repo: str, meta: dict, run_id: str | None) -> None:
    with conn.transaction():
        conn.execute(
            "INSERT INTO model_versions"
            " (model_version, hf_repo, mlflow_run_id, dvc_data_rev, eval_metrics, status)"
            " VALUES (%s, %s, %s, %s, %s, 'candidate') ON CONFLICT (model_version) DO NOTHING",
            (sha, repo, meta.get("mlflow_run_id"), meta["data"].get("processed_md5"),
             Jsonb(meta["metrics"])),
        )  # fmt: skip
        if run_id:
            conn.execute(
                "UPDATE training_runs SET candidate_version = %s, mlflow_run_id = %s"
                " WHERE run_id = %s",
                (sha, meta.get("mlflow_run_id"), run_id),
            )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Upload model artifacts to the HF model repo.")
    p.add_argument("--artifacts", type=Path, required=True)
    p.add_argument("--run-id", help="training_runs.run_id to attach the candidate to")
    p.add_argument("--no-db", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    repo = os.environ["HF_MODEL_REPO"]
    files = [f for f in ARTIFACT_FILES if (args.artifacts / f).exists()]
    if args.dry_run:
        print(f"would upload {files} from {args.artifacts} to {repo} (private)", file=sys.stderr)
        if not args.no_db:
            print("would insert a model_versions row with status candidate", file=sys.stderr)
        return 0

    from huggingface_hub import HfApi

    api = HfApi(token=os.environ["HF_TOKEN_WRITE"])
    api.create_repo(repo, private=True, exist_ok=True)
    meta = json.loads((args.artifacts / "metadata.json").read_text())
    commit = api.upload_folder(
        folder_path=str(args.artifacts),
        repo_id=repo,
        allow_patterns=files,  # never the feedback holdout: it holds reviewer data
        commit_message=f"model trained {meta['trained_at']} (mlflow {meta.get('mlflow_run_id')})",
    )
    sha = commit.oid
    if not args.no_db:
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            record_candidate(conn, sha, repo, meta, args.run_id)
    print(sha)  # stdout carries only the new model_version: Jenkins captures it
    return 0


if __name__ == "__main__":
    sys.exit(main())
