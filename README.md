# TriageIQ

Predicts the support queue of incoming tickets; reviewers confirm or correct; the model retrains itself.
Contracts and phases: `Team-A-Application-ML-Guide.md` (Part 0 + Team A), `Team-B-Platform-Delivery-Guide.md`.

```bash
cp .env.example .env          # fill in real values, incl. GATEWAY_HTPASSWD
docker compose up -d --build                      # app (model on the HF Space)
docker compose --profile local-model up -d        # + local model copy (set MODEL_SERVICE_URL=http://model-service:8000)
docker compose --profile ops up -d jenkins        # Jenkins as code on http://127.0.0.1:8090
GATEWAY_URL=http://127.0.0.1:$GATEWAY_PORT SMOKE_PASSWORD=... python scripts/smoke_test.py
```

## Resource limits (A8)

Measured with `docker stats` while the generator ran every 5s and a reviewer worked through tickets.
Limit = 2 x peak, rounded up to 64 MB.

| Service | Observed peak | Limit | Peak CPU (limit) |
|---|---|---|---|
| gateway | 16 MiB | 64M | 0% (0.5) |
| backend-api | 57 MiB | 128M | 1% (0.5) |
| feedback-service | 67 MiB | 192M | 29% (0.5) |
| ticket-generator | 140 MiB | 320M | 1% (0.5) |
| postgres | 46 MiB | 256M ¹ | 5% (1.0) |
| model-service (local copy) | 452 MiB | 960M | 51% (1.0) |
| jenkins (idle, no build) | 558 MiB | 2G | 7% |

15 min, 213 reviews (82 corrections). Kubernetes uses the peak as `requests.memory` and the limit as
`limits.memory`. ¹ 2 × peak would be 128M, but Postgres' default `shared_buffers` alone is 128 MB once
the database grows, so it gets 256M.
