import json
import logging
import os
import random
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
import pandas as pd

log = logging.getLogger(__name__)
EMPTY_STATE = {"sent": 0, "stream_pos": 0, "heldout_pos": 0}


@dataclass
class DriftConfig:
    enabled: bool
    start_after: int
    ratio: float
    lengths: dict[str, int]  # rows per source file


def pick_next(state: dict, cfg: DriftConfig, rng: random.Random) -> tuple[str, int]:
    source = "stream"
    if cfg.enabled and state["sent"] >= cfg.start_after and rng.random() < cfg.ratio:
        source = "heldout"
    return source, state[f"{source}_pos"] % cfg.lengths[source]


def load_state(path: Path) -> dict:
    try:
        return {**EMPTY_STATE, **json.loads(path.read_text())}
    except FileNotFoundError:
        return dict(EMPTY_STATE)


def save_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, path)  # atomic: a crash never leaves a half-written cursor


def payload(row: pd.Series) -> dict:
    subject = row.subject if isinstance(row.subject, str) else None
    return {"subject": subject, "body": row.body, "source": "stream", "dataset_label": row.label}


def tick(
    state: dict, cfg: DriftConfig, data: dict[str, pd.DataFrame], http: httpx.Client, seed: int
) -> dict:
    """Send one ticket. Returns the new state; unchanged if the send failed."""
    rng = random.Random(seed + state["sent"])  # reproducible across restarts
    source, pos = pick_next(state, cfg, rng)
    if pos != state[f"{source}_pos"]:
        log.warning("reached end of file, wrapping to start", extra={"file": source})
    rid = str(uuid.uuid4())
    try:
        r = http.post(
            "/tickets", json=payload(data[source].iloc[pos]), headers={"X-Request-ID": rid}
        )
    except httpx.HTTPError as e:
        log.warning("send failed", extra={"error": type(e).__name__, "request_id": rid})
        return state
    if r.status_code != 201:
        log.warning("send rejected", extra={"status": r.status_code, "request_id": rid})
        return state
    log.info("ticket sent", extra={"source": source, "pos": pos, "request_id": rid})
    return {**state, "sent": state["sent"] + 1, f"{source}_pos": pos + 1}
