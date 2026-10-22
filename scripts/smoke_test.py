"""End-to-end smoke test through the gateway. Standard library only.

Env: GATEWAY_URL (http://127.0.0.1:8080 from the host, http://gateway:8080 from Jenkins),
SMOKE_USER (default "smoke"), SMOKE_PASSWORD.
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8080").rstrip("/")
USER = os.environ.get("SMOKE_USER", "smoke")
AUTH = base64.b64encode(f"{USER}:{os.environ.get('SMOKE_PASSWORD', '')}".encode()).decode()
MODEL_WAIT_SECONDS = 180


def call(method: str, path: str, body: dict | None = None, auth: bool = True):
    req = urllib.request.Request(BASE + path, method=method)
    if auth:
        req.add_header("Authorization", f"Basic {AUTH}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data, timeout=60) as r:  # nosec B310: fixed http(s) base
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw.decode(errors="replace")


def step(n: int, name: str, ok: bool, detail="") -> None:
    print(f"[{n}] {name}: {'ok' if ok else 'FAILED'} {detail}".rstrip())
    if not ok:
        print(f"SMOKE FAILED at step {n} ({name})")
        sys.exit(1)


def main() -> None:
    status, body = call("GET", "/healthz", auth=False)
    step(1, "GET /healthz", status == 200, f"{status}")

    status, body = call("GET", "/api/labels")
    step(2, "GET /api/labels", status == 200 and len(body.get("labels", [])) == 10, f"{status}")

    ticket = {"subject": "Smoke test", "body": "Smoke test: VPN cannot connect.", "source": "smoke",
              "dataset_label": None}  # fmt: skip
    deadline = time.monotonic() + MODEL_WAIT_SECONDS
    while True:
        status, body = call("POST", "/api/tickets", ticket)
        if status != 502 or time.monotonic() > deadline:
            break
        print("    model unavailable (Space may be waking up), retrying in 10s")
        time.sleep(10)
    step(3, "POST /api/tickets", status == 201, f"{status}")
    prediction = body["prediction"]

    status, body = call("GET", "/api/tickets/pending?limit=100")
    ids = {p["prediction_id"] for p in body} if status == 200 else set()
    step(4, "GET /api/tickets/pending", prediction["prediction_id"] in ids, f"{status}")

    fb = {"prediction_id": prediction["prediction_id"], "is_correct": True, "corrected_label": None}
    status, body = call("POST", "/feedback-api/feedback", fb)
    step(5, "POST /feedback-api/feedback", status == 201, f"{status}")

    status, body = call("POST", "/feedback-api/feedback", fb)
    step(6, "repeat feedback -> 409", status == 409, f"{status}")

    print(f"SMOKE OK {prediction['model_version']}")


if __name__ == "__main__":
    main()
