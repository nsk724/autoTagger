import pandas as pd
import pytest

from triage_ml.prepare import COLUMNS, make_splits


@pytest.fixture
def raw_df() -> pd.DataFrame:
    rows = []

    def add(queue, body, language="en", subject="s"):
        rows.append(
            {
                "subject": subject,
                "body": body,
                "queue": queue,
                "language": language,
                "priority": "low",
                "type": "Request",
                "version": 51,
            }
        )

    for i in range(20):
        add("Technical Support", f"printer broken {i}")
        add("Billing and Payments", f"invoice wrong {i}", subject="s" if i else float("nan"))
    for i in range(5):
        # duplicates of the rows above once lowercased and whitespace-collapsed
        add("Technical Support", f"PRINTER  broken {i}", subject="S")
        add("Technical Support", f"Drucker kaputt {i}", language="de")
        add("Games", f"game topic {i}")
        add("Service Outages and Maintenance", f"site down {i}")
    df = pd.DataFrame(rows)
    df["row_id"] = df.index
    assert len(df) == 60
    return df


def test_make_splits(raw_df):
    splits, stats = make_splits(raw_df, min_per_class=1)
    all_rows = pd.concat(splits.values())

    assert set(splits) == {"train", "val", "golden", "stream", "heldout"}
    assert all(list(p.columns) == COLUMNS for p in splits.values())
    assert set(all_rows.language) == {"en"}
    assert "Games" not in set(all_rows.label)
    assert stats["counts"]["duplicates_removed"] == 5
    assert set(splits["heldout"].label) == {"Service Outages and Maintenance"}
    assert len(splits["heldout"]) == 5
    assert "Service Outages and Maintenance" not in set(
        pd.concat([splits[n] for n in ("train", "val", "golden", "stream")]).label
    )
    assert all_rows.text.str.lower().is_unique
    sizes = {n: len(p) for n, p in splits.items()}
    assert sizes == {"heldout": 5, "stream": 8, "train": 24, "val": 4, "golden": 4}


def test_min_per_class_enforced(raw_df):
    with pytest.raises(SystemExit, match="below 20"):
        make_splits(raw_df)
