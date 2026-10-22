import random

import httpx
import pandas as pd
import pytest

from app.generator import DriftConfig, load_state, pick_next, save_state, tick

LENGTHS = {"stream": 10, "heldout": 5}


def cfg(enabled=True, start_after=100, ratio=0.4):
    return DriftConfig(enabled, start_after, ratio, LENGTHS)


def state(sent=0, stream_pos=0, heldout_pos=0):
    return {"sent": sent, "stream_pos": stream_pos, "heldout_pos": heldout_pos}


def test_drift_off_always_stream():
    rng = random.Random(1)
    assert {pick_next(state(500), cfg(enabled=False), rng)[0] for _ in range(200)} == {"stream"}


def test_drift_on_before_start_is_stream():
    rng = random.Random(1)
    assert {pick_next(state(99), cfg(), rng)[0] for _ in range(200)} == {"stream"}


def test_drift_ratio_after_start():
    rng = random.Random(42)
    picks = [pick_next(state(100), cfg(), rng)[0] for _ in range(1000)]
    assert abs(picks.count("heldout") / 1000 - 0.4) <= 0.05


@pytest.mark.parametrize(("pos", "expected"), [(9, 9), (10, 0), (23, 3)])
def test_wrap_around(pos, expected):
    assert pick_next(state(stream_pos=pos), cfg(enabled=False), random.Random(0)) == (
        "stream", expected)  # fmt: skip


STREAM = {"subject": [None, "s"] * 5, "body": ["b"] * 10, "label": ["IT Support"] * 10}
HELDOUT = {
    "subject": ["h"] * 5,
    "body": ["x"] * 5,
    "label": ["Service Outages and Maintenance"] * 5,
}
DATA = {"stream": pd.DataFrame(STREAM), "heldout": pd.DataFrame(HELDOUT)}


def client(status):
    sent = []

    def handler(req):
        sent.append(req)
        if status == "down":
            raise httpx.ConnectError("down")
        return httpx.Response(status, json={})

    return httpx.Client(base_url="http://b", transport=httpx.MockTransport(handler)), sent


def test_cursor_advances_only_on_201():
    http, sent = client(201)
    new = tick(state(), cfg(enabled=False), DATA, http, 42)
    assert new == state(sent=1, stream_pos=1)
    assert len(sent) == 1

    for status in (502, "down"):
        http, sent = client(status)
        assert tick(new, cfg(enabled=False), DATA, http, 42) == new


def test_restart_resumes_from_saved_state(tmp_path):
    path = tmp_path / "cursor.json"
    assert load_state(path) == state()
    save_state(path, state(7, 5, 2))
    assert load_state(path) == state(7, 5, 2)
    assert not path.with_suffix(".tmp").exists()
