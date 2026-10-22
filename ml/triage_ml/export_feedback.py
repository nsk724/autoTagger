import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import psycopg

from triage_ml.prepare import COLUMNS
from triage_ml.text import build_text
from triage_ml.train import file_md5

MIN_ROWS = 50
TOO_FEW = 4


def snapshot(conn) -> tuple[int | None, pd.DataFrame]:
    cutoff = conn.execute("SELECT max(feedback_id) FROM labeled_feedback").fetchone()[0]
    rows = conn.execute(
        "SELECT feedback_id, subject, body, label FROM labeled_feedback"
        " WHERE feedback_id <= %s ORDER BY feedback_id",
        (cutoff,),
    ).fetchall()
    df = pd.DataFrame(rows, columns=["row_id", "subject", "body", "label"])
    df["text"] = [build_text(s, b) for s, b in zip(df.subject, df.body)]
    for col in ("priority", "type", "language", "version"):
        df[col] = None  # not known for live tickets
    return cutoff, df[COLUMNS]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Export reviewed feedback as a training snapshot.")
    p.add_argument("--run-id", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    if args.dry_run:
        print(f"would write {args.out}/feedback_<cutoff>.parquet and set the run's cutoff")
        return 0
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        cutoff, df = snapshot(conn)
        if len(df) < MIN_ROWS:
            print(f"only {len(df)} reviewed rows (< {MIN_ROWS})", file=sys.stderr)
            return TOO_FEW
        args.out.mkdir(parents=True, exist_ok=True)
        path = args.out / f"feedback_{cutoff}.parquet"
        df.to_parquet(path, index=False)
        conn.execute(
            "UPDATE training_runs SET feedback_cutoff = %s, feedback_md5 = %s WHERE run_id = %s",
            (cutoff, file_md5(path), args.run_id),
        )
        conn.commit()
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
