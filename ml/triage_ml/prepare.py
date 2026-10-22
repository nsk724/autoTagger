import argparse
import json

import datasets
import pandas as pd
from huggingface_hub import HfApi
from sklearn.model_selection import train_test_split

from triage_ml.config import HELDOUT, LABELS, PROCESSED, ROOT
from triage_ml.text import build_text

DATASET = "Tobi-Bueck/customer-support-tickets"
SEED = 42
COLUMNS = ["row_id", "text", "subject", "body", "label", "priority", "type", "language", "version"]
# Guide 0.11.2: rows per core queue, all languages.
CORE_COUNTS = {
    "Technical Support": 14186,
    "Product Support": 8960,
    "Customer Service": 7420,
    "IT Support": 5725,
    "Billing and Payments": 4874,
    "Returns and Exchanges": 2438,
    "Service Outages and Maintenance": 1912,
    "Sales and Pre-Sales": 1490,
    "Human Resources": 914,
    "General Inquiry": 668,
}

CORE = LABELS


def check_raw(df: pd.DataFrame) -> None:
    def require(ok: bool, msg: str) -> None:
        if not ok:
            raise SystemExit(f"raw data check failed: {msg}")

    require(len(df) == 61765, f"expected 61765 rows, got {len(df)}")
    require(df.queue.nunique() == 52, f"expected 52 queues, got {df.queue.nunique()}")
    require(set(CORE) == set(CORE_COUNTS), "config/labels.yaml differs from CORE_COUNTS")
    counts = df.queue.value_counts()
    for queue, n in CORE_COUNTS.items():
        require(counts.get(queue) == n, f"{queue}: expected {n} rows, got {counts.get(queue)}")
    require(df.body.isna().sum() == 2, f"expected 2 null bodies, got {df.body.isna().sum()}")
    require(set(df.language) == {"de", "en"}, f"unexpected languages {set(df.language)}")
    require(
        df[df.type.isna()].queue.isin(CORE).sum() == 0,
        "some core-queue rows have a null type. STOP and tell the team",
    )


def make_splits(df: pd.DataFrame, min_per_class: int = 20) -> tuple[dict[str, pd.DataFrame], dict]:
    counts = {"raw": len(df)}
    df = df[df.queue.isin(CORE)]
    counts["core_queues"] = len(df)
    df = df[df.body.notna()]
    counts["body_not_null"] = len(df)
    df = df[df.language == "en"].copy()
    counts["english"] = len(df)

    df["text"] = [build_text(s, b) for s, b in zip(df.subject, df.body)]
    df["norm"] = [" ".join(t.lower().split()) for t in df.text]
    counts["conflicting_label_duplicates"] = int((df.groupby("norm").queue.nunique() > 1).sum())
    before = len(df)
    df = df.drop_duplicates("norm", keep="first")
    counts["duplicates_removed"] = before - len(df)
    counts["deduplicated"] = len(df)

    df["label"] = df.queue
    is_heldout = df.label.isin(HELDOUT)
    splits = {"heldout": df[is_heldout]}
    pool = df[~is_heldout]
    rest, splits["stream"] = train_test_split(
        pool, test_size=0.2, stratify=pool.label, random_state=SEED
    )
    splits["train"], tmp = train_test_split(
        rest, train_size=0.75, stratify=rest.label, random_state=SEED
    )
    splits["val"], splits["golden"] = train_test_split(
        tmp, test_size=0.5, stratify=tmp.label, random_state=SEED
    )

    seen: set[str] = set()
    for name, part in splits.items():
        overlap = seen & set(part.norm)
        if overlap:
            raise SystemExit(f"leakage: {len(overlap)} texts of {name} appear in another split")
        seen |= set(part.norm)
    per_label = {name: part.label.value_counts().to_dict() for name, part in splits.items()}
    for name in ("val", "golden", "stream"):
        small = {k: v for k, v in per_label[name].items() if v < min_per_class}
        if small:
            raise SystemExit(f"{name}: classes below {min_per_class} rows: {small}")

    stats = {"counts": counts, "split_sizes": {n: len(p) for n, p in splits.items()}}
    stats["per_split_label"] = per_label
    stats["heldout_count"] = len(splits["heldout"])
    return {n: p[COLUMNS].reset_index(drop=True) for n, p in splits.items()}, stats


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download and split the ticket dataset.")
    parser.add_argument("--revision", help="dataset commit sha (default: current main)")
    args = parser.parse_args(argv)

    sha = args.revision or HfApi().dataset_info(DATASET).sha
    df = datasets.load_dataset(DATASET, split="train", revision=sha).to_pandas()
    df["row_id"] = df.index
    raw = ROOT / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    df.to_parquet(raw / "tickets.parquet", index=False)

    check_raw(df)
    splits, stats = make_splits(df)
    stats = {"dataset": DATASET, "dataset_revision": sha, **stats}

    out = PROCESSED
    out.mkdir(parents=True, exist_ok=True)
    for name, part in splits.items():
        part.to_parquet(out / f"{name}.parquet", index=False)
    (out / "stats.json").write_text(json.dumps(stats, indent=2) + "\n")

    print(json.dumps(stats["counts"], indent=2))
    table = pd.DataFrame(stats["per_split_label"]).fillna(0).astype(int)
    table.loc["TOTAL"] = table.sum()
    print(table.to_string())


if __name__ == "__main__":
    main()
