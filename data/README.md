# Data

Tracked with DVC: `dvc pull` fetches `raw/tickets.parquet` and `processed/`. Rebuild with
`python -m triage_ml.prepare --revision ddf1c81a5475992c4fa6752bf1e8b4e31f07bbeb`.

## Source and license

[Tobi-Bueck/customer-support-tickets](https://huggingface.co/datasets/Tobi-Bueck/customer-support-tickets)
by Tobias Bueck, DOI `10.57967/hf/6184`, revision `ddf1c81a5475992c4fa6752bf1e8b4e31f07bbeb`.
Licensed under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/): non-commercial use
only, attribution required. Used here for coursework; do not redistribute commercially.

## Counts (from `processed/stats.json`)

| Step | Rows |
|---|---|
| Raw | 61,765 |
| 10 core queues | 48,587 |
| Body not null | 48,585 |
| English | 28,260 |
| Exact duplicates removed | 4,514 |
| Conflicting-label duplicates | 0 |
| After dedup | 23,746 |

| Label | train | val | golden | stream | heldout |
|---|---|---|---|---|---|
| Technical Support | 4,114 | 686 | 686 | 1,372 | – |
| Product Support | 2,656 | 443 | 443 | 886 | – |
| Customer Service | 2,142 | 357 | 357 | 714 | – |
| IT Support | 1,700 | 283 | 283 | 567 | – |
| Billing and Payments | 1,452 | 242 | 242 | 484 | – |
| Returns and Exchanges | 704 | 117 | 118 | 234 | – |
| Sales and Pre-Sales | 434 | 73 | 72 | 145 | – |
| Human Resources | 277 | 46 | 46 | 92 | – |
| General Inquiry | 206 | 34 | 34 | 68 | – |
| Service Outages and Maintenance | – | – | – | – | 937 |
| **Total** | **13,685** | **2,281** | **2,281** | **4,562** | **937** |

Notes: 19% of English rows were exact duplicates (the data is probably synthetic), but no duplicate
carried a different label.

## Baseline

Model: word 1-2-gram TF-IDF + `all-MiniLM-L6-v2` embeddings, concatenated into
`LogisticRegression(C=100, class_weight="balanced")` (C picked on val from {1, 10, 100}).
The guide's embeddings-only model scored golden macro-F1 0.27 (below the 0.40 floor; larger C did not
help), TF-IDF alone 0.60; the team chose the combination.

| Golden set | Value |
|---|---|
| **Accuracy** | **0.615** |
| Macro-F1 | 0.602 |
| Val macro-F1 | 0.605 |

| Class | F1 |
|---|---|
| Billing and Payments | 0.838 |
| Technical Support | 0.658 |
| General Inquiry | 0.618 |
| Human Resources | 0.591 |
| Returns and Exchanges | 0.577 |
| Product Support | 0.570 |
| IT Support | 0.553 |
| Customer Service | 0.507 |
| Sales and Pre-Sales | 0.504 |

Top-3 confusions (true → predicted): Product Support → Technical Support (91),
Customer Service → Technical Support (75), IT Support → Technical Support (73).

**For Team B (B7)**: alert threshold = round((1 − 0.615) + 0.15, 2) = **0.54**. Drift crosses it when
`DRIFT_RATIO > 0.15 / 0.615 ≈ 0.24`, so the default 0.4 is safe.
