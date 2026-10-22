import argparse
import os
import sys
import time

import httpx
import psycopg

POLL_SECONDS = 15
POLL_TIMEOUT_SECONDS = 15 * 60


def rollback_target(conn) -> str:
    row = conn.execute(
        "SELECT model_version FROM model_versions WHERE status = 'retired'"
        " ORDER BY promoted_at DESC NULLS LAST, created_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise SystemExit("no retired version to roll back to")
    return row[0]


def mark_production(conn, sha: str, repo: str) -> None:
    with conn.transaction():
        conn.execute(
            "UPDATE model_versions SET status = 'retired'"
            " WHERE status = 'production' AND model_version <> %s",
            (sha,),
        )
        conn.execute(
            "INSERT INTO model_versions (model_version, hf_repo, status, promoted_at)"
            " VALUES (%s, %s, 'production', now())"
            " ON CONFLICT (model_version) DO UPDATE SET status = 'production', promoted_at = now()",
            (sha, repo),
        )


def wait_for_version(url: str, token: str | None, sha: str) -> bool:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{url}/health", headers=headers, timeout=10)
            if r.status_code == 200 and r.json().get("model_version") == sha:
                return True
            print(f"waiting: {r.status_code} {r.text[:120]}", file=sys.stderr)
        except (httpx.HTTPError, ValueError) as e:
            print(f"waiting: {type(e).__name__}", file=sys.stderr)
        time.sleep(POLL_SECONDS)
    return False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Point the HF Space at a model revision.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--revision")
    g.add_argument("--rollback", action="store_true", help="promote the latest retired version")
    p.add_argument("--no-db", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    space, repo = os.environ["HF_SPACE_REPO"], os.environ["HF_MODEL_REPO"]
    url = os.environ["MODEL_SERVICE_URL"]
    if args.dry_run:
        target = args.revision or "<latest retired version from model_versions>"
        print(f"1. would set Space secret HF_TOKEN on {space}")
        print(f"2. would set Space variables HF_MODEL_REPO={repo} MODEL_REVISION={target}")
        print(f"3. would restart Space {space}")
        print(f"4. would poll {url}/health until model_version == {target}")
        print(
            "5. would mark it production in model_versions" + (" (skipped)" if args.no_db else "")
        )
        return 0

    sha = args.revision
    if args.rollback:
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            sha = rollback_target(conn)
        print(f"rolling back to {sha}", file=sys.stderr)

    from huggingface_hub import HfApi

    api = HfApi(token=os.environ["HF_TOKEN_WRITE"])
    api.add_space_secret(space, "HF_TOKEN", os.environ["HF_TOKEN_READ"])
    api.add_space_variable(space, "HF_MODEL_REPO", repo)
    api.add_space_variable(space, "MODEL_REVISION", sha)
    api.restart_space(space)
    if not wait_for_version(url, os.environ.get("HF_TOKEN_READ"), sha):
        print(f"timeout: Space did not serve {sha} within {POLL_TIMEOUT_SECONDS}s", file=sys.stderr)
        return 1
    if not args.no_db:
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            mark_production(conn, sha, repo)
    print(sha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
