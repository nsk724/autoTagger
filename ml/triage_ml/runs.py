import argparse
import os
import sys

import psycopg

RUN, SKIP = 0, 10


def should_run(conn, cooldown_minutes: int) -> tuple[int, str]:
    recent = conn.execute(
        "SELECT model_version FROM model_versions"
        " WHERE promoted_at > now() - make_interval(mins => %s) LIMIT 1",
        (cooldown_minutes,),
    ).fetchone()
    if recent:
        return SKIP, f"{recent[0]} was promoted in the last {cooldown_minutes} minutes"
    newest = conn.execute("SELECT max(feedback_id) FROM labeled_feedback").fetchone()[0]
    cutoff = conn.execute("SELECT max(feedback_cutoff) FROM training_runs").fetchone()[0]
    if newest is None or (cutoff is not None and newest <= cutoff):
        return SKIP, "no new feedback since the last run's cutoff"
    return RUN, f"new feedback up to id {newest} (last cutoff {cutoff})"


def start(conn, trigger: str, build: str | None) -> str:
    row = conn.execute(
        "INSERT INTO training_runs (trigger, jenkins_build_id) VALUES (%s, %s) RETURNING run_id",
        (trigger, build),
    ).fetchone()
    conn.commit()
    return str(row[0])


def finish(conn, run_id: str, outcome: str) -> None:
    with conn.transaction():
        row = conn.execute(
            "UPDATE training_runs SET outcome = %s, finished_at = now()"
            " WHERE run_id = %s RETURNING candidate_version",
            (outcome, run_id),
        ).fetchone()
        if row is None:
            raise SystemExit(f"unknown run {run_id}")
        if outcome == "rejected" and row[0]:
            conn.execute(
                "UPDATE model_versions SET status = 'rejected' WHERE model_version = %s", (row[0],)
            )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="training_runs bookkeeping.")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("should-run")
    s.add_argument("--cooldown-minutes", type=int, default=60)
    s = sub.add_parser("start")
    s.add_argument("--trigger", choices=["alert", "schedule", "manual"], required=True)
    s.add_argument("--build")
    s = sub.add_parser("finish")
    s.add_argument("--run-id", required=True)
    s.add_argument(
        "--outcome", choices=["promoted", "rejected", "skipped", "failed"], required=True
    )
    for name in ("should-run", "start", "finish"):
        sub.choices[name].add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    if args.dry_run:
        print(f"would run '{args.cmd}' against DATABASE_URL", file=sys.stderr)
        return 0
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        if args.cmd == "should-run":
            code, reason = should_run(conn, args.cooldown_minutes)
            print(("run: " if code == RUN else "skip: ") + reason, file=sys.stderr)
            return code
        if args.cmd == "start":
            print(start(conn, args.trigger, args.build))
            return 0
        finish(conn, args.run_id, args.outcome)
    return 0


if __name__ == "__main__":
    sys.exit(main())
