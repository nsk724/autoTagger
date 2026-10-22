# TriageIQ — Team A Guide: Application & ML

> This file contains **Part 0 (Shared Foundation)**, the contract **both teams** build against, and **Part A**, Team A's phase-by-phase build guide.
> Team B's guide is `Team-B-Platform-Delivery-Guide.md`. It does not repeat Part 0, so there is one source of truth that can't drift apart between teams.
> This guide replaces `TriageIQ-Project-Detailing.md` and `DevOps-POC-Lifecycle.md`.

**How to read this**
- Everyone reads Part 0 fully before writing any code.
- Team A then follows Part A **in order**. Never start a phase before the previous phase's **gate** passes.
- Nobody changes Part 0 alone. Open a PR that edits Part 0, and get one approval from each team. Contracts change on paper first, then in code.

---

# PART 0 — SHARED FOUNDATION (both teams)

## 0.1 What we are building

**TriageIQ** reads incoming support tickets and **predicts which support queue each ticket belongs to**. A human reviewer confirms or corrects each prediction in a web page, and those corrections are stored. When the model's error rate on reviewed tickets rises too high, the system **retrains itself automatically**, checks the new model is actually better, and switches to it. No one clicks anything.

Everything runs on **one local machine with Docker**. Two exceptions:
- The model runs as a **Hugging Face Space**.
- Experiment tracking and data versioning live on **DagsHub** (shared by the whole team).

The system is built so it can move to **AWS and/or a public Cloudflare URL without code changes** (rules in 0.5).

```
                      (public access: Cloudflare Tunnel, later)
                                     │
 Reviewer's browser ───────────► gateway  (nginx: serves frontend, basic auth, routing)
                                   │   /api/*           ──► backend-api ──► model-service
                                   │                          │              (HF Space; optional local copy)
                                   │   /feedback-api/*  ──► feedback-service
                                   │                          │
 ticket-generator ─────────────► backend-api            postgres  ◄── backend-api, feedback-service
 (drips dataset tickets)

 Prometheus ── scrapes /metrics of backend-api, feedback-service
     └─► Alertmanager ── webhook ──► Jenkins "retrain" job
                                        └─► train → evaluate → publish to HF model repo → repoint HF Space
 Jenkins "CI" job: secrets scan → lint → tests → security scans → build → deploy → smoke test
 Grafana: dashboards over Prometheus (metrics) and Loki (logs)
```

## 0.2 Team split, phases and gates

Each team has two developers. Each team runs **two tracks in parallel**. Inside a track, phases are **strictly sequential**.

| | Track | Phases (in order) | Ends with |
|---|---|---|---|
| **Both** | Joint | **Phase 0**: repo skeleton, stubs, accounts | Gate 0 |
| **Team A** | A-ML | A1 Dataset → A2 Baseline model → A3 Model service on HF | A3 gate |
| **Team A** | A-App | A4 Backend + DB → A5 Feedback → A6 Gateway + frontend → A7 Ticket generator | A7 gate |
| **Team A** | Joint | A8 Integration + smoke test | **A8 gate (App POC)** |
| **Team B** | B-Delivery | B1 Jenkins as code → B2 CI pipeline → B3 DevSecOps | B3 gate |
| **Team B** | B-Infra | B4 Public access → B5 IaC (AWS + Cloudflare) → B6 Kubernetes (kind) | B6 gate |
| | | ════ **DevOps POC gate** (0.2.2) ════ | |
| **Team A** | MLOps | A9 Retrain/evaluate/promote tooling | A9 gate |
| **Team B** | MLOps | B7 Monitoring + logging → B8 Retrain automation → B9 Drift demo | **MLOps gate** |

Team A's app track can start right after Phase 0, even though the real model only arrives in A3. The app track codes against the **contracts in 0.7** and uses **fakes** in tests. Team B's pipeline builds the Phase 0 **stubs** until real services land.

### 0.2.1 Sync points (put them in the calendar)
| When | Who | What |
|---|---|---|
| After Phase 0 | All 4 | Contracts frozen. Everyone can run `docker compose up` |
| After A2 | A → B | Team A posts the baseline accuracy in `data/README.md`. Team B uses it to set the alert threshold (B7) |
| After A3 + B2 | A + B | Team B adds the "deploy model-service to HF" stage using Team A's script |
| After A8 + B3 | All 4 | Jenkins deploys the full app on every merge to `main` |
| DevOps POC gate | All 4 | Demo rehearsal against the checklist below |

### 0.2.2 DevOps POC gate (rubric checklist)
| Requirement | Evidence to show |
|---|---|
| Microservices | 5 app services + Postgres running as separate containers (`docker compose ps`) |
| Docker | Every service has its own Dockerfile and image; every app image runs as non-root (UID 1000; gateway UID 101) |
| CI/CD | A Jenkins run on `main`: scans → tests → build → deploy → smoke test, all green, no manual steps |
| DevSecOps | Gitleaks, Bandit, pip-audit and Trivy stages, and one deliberately bad branch failing at the right stage |
| Kubernetes | The same images running on a local **kind** cluster; smoke test passes against it |
| IaC | `terraform validate` + `plan` in CI for AWS and Cloudflare. Optional: one real apply → smoke → destroy |
| Public access | The app opens from a phone on **mobile data** through a Cloudflare Tunnel URL, behind a login |

### 0.2.3 MLOps gate
A recorded run of the **drift demo** (B9): the held-out queue starts arriving → reviewers correct it → error rate rises in Grafana → alert fires → Jenkins retrains → the new model is promoted → error rate for the new version falls. DVC and MLflow show where every model came from.

## 0.3 How we work: sequential phases with dry tests

**Dry test**: a check with **no real side effects**. It must not:
- call paid or shared external services
- change deployed state
- need credentials beyond read-only

Every phase ships its dry tests **in the same PR** as its code.

| Kind | Examples in this project |
|---|---|
| Unit test with fakes | pytest; external calls (model, DB, HF) replaced by fake objects through dependency injection |
| Integration test (throwaway) | pytest marked `integration`, against a temporary Postgres container that is deleted afterwards |
| Config validators | `docker compose config -q`, `promtool check`, `amtool check-config`, `terraform validate`, `kubeconform`, `alloy fmt`, the Jenkinsfile linter |
| Dry-run flags | `--dry-run` on every script that would push, promote or delete. It prints what it *would* do and changes nothing |
| Plan | `terraform plan` (reads cloud state, changes nothing) |

**Phase rules**
1. A phase is **done** when (a) its dry tests pass locally, (b) Jenkins is green (once B2 exists), (c) its **Gate** checklist is ticked by the *other* developer on the team, and (d) the PR is merged.
2. The next phase starts only after that.
3. If a gate fails, fix it inside the same phase. Never "fix it in the next phase."

## 0.4 Repository layout

```
triageiq/
├── .gitattributes                 # * text=auto eol=lf   (critical on Windows)
├── .gitignore                     # .env, .env.*, !.env.example, .venv/, __pycache__/, artifacts/, mlruns/, .dvc/config.local, deploy/k8s/.env.k8s, *.tfstate*, .terraform/
│                                  # do NOT ignore data/ dirs: DVC writes its own data/**/.gitignore, and the .dvc pointer files must be committed
├── .dockerignore                  # whitelist style, see 0.6.9
├── .env.example                   # every variable from 0.8, with placeholder values
├── .pre-commit-config.yaml        # ruff + gitleaks (Team B adds in B3)
├── pyproject.toml                 # tool config only: ruff, pytest
├── docker-compose.yml             # ONE file, profiles: (default) app, local-model, ops, monitoring, public, public-quick
├── Jenkinsfile                    # CI/CD (Team B)
├── Jenkinsfile.retrain            # retraining (Team B)
├── README.md                      # how to run, in 10 lines
├── config/
│   └── labels.yaml                # the 10 queue labels: single source of truth
├── data/                          # DVC-tracked, never committed to git directly
│   ├── README.md                  # dataset facts, counts, license, BASELINE numbers
│   ├── raw/tickets.parquet(.dvc)
│   └── processed.dvc              # train/val/golden/stream/heldout parquet + stats.json
├── ml/                            # Team A: python package `triage_ml`
│   ├── Dockerfile                 # image "triageiq-ml": used by Jenkins retrain job
│   ├── requirements.txt / requirements-dev.txt
│   ├── triage_ml/{text,prepare,train,evaluate,publish,promote,export_feedback,runs,deploy_space}.py
│   └── tests/
├── services/                      # Team A
│   ├── model-service/   {app/, tests/, Dockerfile, requirements*.txt, SPACE_README.md}
│   ├── backend-api/     {app/, tests/, Dockerfile, requirements*.txt}
│   ├── feedback-service/{app/, tests/, Dockerfile, requirements*.txt}
│   ├── ticket-generator/{app/, tests/, Dockerfile, requirements*.txt}
│   ├── gateway/         {nginx.conf.template, entrypoint.sh, frontend/{index.html,app.js,styles.css}, Dockerfile}
│   └── postgres/        {migrations/001_init.sql, Dockerfile}
├── ops/                           # Team B
│   ├── jenkins/     {Dockerfile, plugins.txt, casc.yaml}
│   ├── prometheus/  {Dockerfile, prometheus.yml, alerts.yml, alerts_test.yml}
│   ├── alertmanager/{Dockerfile, alertmanager.yml, entrypoint.sh}
│   ├── grafana/     {Dockerfile, provisioning/, dashboards/}
│   └── alloy/       {Dockerfile, config.alloy}
├── deploy/                        # Team B
│   ├── kind/cluster.yaml
│   └── k8s/*.yaml                 # plain manifests, no kustomize
├── infra/                         # Team B
│   ├── aws/        {versions.tf, variables.tf, main.tf, outputs.tf, cloud-init.yaml.tftpl}
│   └── cloudflare/ {versions.tf, variables.tf, main.tf, outputs.tf}
└── scripts/
    └── smoke_test.py              # stdlib only; used by Jenkins and humans
```

## 0.5 Cloud-ready rules (how we move to AWS/Cloudflare with zero code change)

These rules exist so that "local today, AWS or Cloudflare tomorrow" only changes **where** things run, never **what** the code does. Reviewers reject PRs that break them.

1. **All configuration comes from environment variables** (list in 0.8). Code never contains `localhost`, IP addresses, ports of *other* services, or secrets.
2. **Services find each other by Docker service name** (`http://backend-api:8000`). The names are identical in Compose, kind and AWS.
3. **No host bind mounts in `docker-compose.yml`.** Config files are **baked into images** (`COPY`); state lives in **named volumes**. Why: Jenkins runs `docker compose` from inside a container, and bind-mount paths would point at the wrong filesystem. The same images also run unchanged on AWS. *Only allowed exception:* `/var/run/docker.sock` for Jenkins and Alloy.
4. **Containers are stateless.** Only Postgres, Jenkins, Prometheus, Grafana, Loki and the generator cursor have state, each in a named volume.
5. **Logs go to stdout as JSON**, one line per event. Never write log files.
6. **Every service exposes `GET /health`**, and Python services also expose `GET /metrics`.
7. **Exactly one public entry point: `gateway`.** Admin UIs (Jenkins, Grafana, Prometheus, Alertmanager) are published only on `127.0.0.1`. Postgres is never published.
8. **Image names are `${REGISTRY:-}triageiq-<service>:${IMAGE_TAG:-dev}`.** Locally, `REGISTRY` is empty. On AWS you set `REGISTRY=ghcr.io/<org>/`, and nothing else changes.
9. **Secrets are never in git or in images.** They live in `.env` locally (gitignored), the Jenkins credential store, Space secrets on HF, and SSM Parameter Store on AWS.
10. **Time is UTC everywhere**, and DB columns are `TIMESTAMPTZ`.

## 0.6 Coding practices

### 0.6.1 Language and libraries (do not add others without a Part 0 PR)
| Purpose | Use |
|---|---|
| Language | Python **3.11** everywhere |
| Web | FastAPI + uvicorn; pydantic v2; `pydantic-settings` for config |
| HTTP client | `httpx` (always with an explicit timeout) |
| DB | `psycopg` 3 + `psycopg_pool`, **plain SQL**, no ORM |
| Metrics | `prometheus-client` + `prometheus-fastapi-instrumentator` |
| Logging | stdlib `logging` + `python-json-logger` |
| ML | pandas, pyarrow, scikit-learn, sentence-transformers (**CPU torch**, see 0.6.9), `datasets`, `huggingface_hub`, mlflow, dvc |
| Tests | pytest, FastAPI `TestClient` |
| Lint and format | ruff (`ruff check` + `ruff format`), line length 100 |
| Frontend | plain HTML + vanilla JS + CSS. **No framework, no build step** |

**Pin every dependency exactly** (`package==x.y.z`) in `requirements.txt`. Use the latest stable version on the day you create the file. Dev-only packages (pytest, ruff) go in `requirements-dev.txt`.

### 0.6.2 Layout of a Python service (same for all four)
```
services/<name>/
├── app/
│   ├── main.py        # create_app() -> FastAPI; lifespan opens/closes DB pool / loads model
│   ├── settings.py    # class Settings(BaseSettings): every env var this service reads
│   ├── routes.py      # endpoints only: validate → call function → map errors to HTTP
│   ├── schemas.py     # pydantic request/response models (match 0.7 exactly)
│   ├── db.py          # SQL functions, if the service uses the DB
│   ├── clients.py     # outbound HTTP clients, if any
│   └── observability.py  # JSON logging setup, request-id middleware, custom metrics
├── tests/
│   ├── conftest.py    # fixtures + fakes
│   ├── test_routes.py
│   └── test_integration.py   # @pytest.mark.integration
├── Dockerfile
├── requirements.txt
└── requirements-dev.txt
```

### 0.6.3 Rules every service follows
1. **Settings**: one `Settings` class. Required variables have no default, so the app **fails at startup** if one is missing, not at the first request.
2. **Dependency injection**: routes get the DB, model client and settings through `Depends(...)`. Tests swap them with `app.dependency_overrides`. Tests never make a network call to HF or DagsHub.
3. **Validate at the boundary**: every request body is a pydantic model with length limits (see 0.7). Never trust a header or field you didn't validate.
4. **SQL**: always parameterized (`cur.execute("... WHERE id = %s", (id,))`). **Never** f-strings or `+` in SQL. Bandit fails the build on this.
5. **Errors**: map known failures to the status codes in 0.7. Unknown exceptions → 500 with `{"detail": "internal_error"}`. Never return stack traces or exception text to clients.
6. **Timeouts on every outbound call.** Retry only idempotent calls, and only where 0.7 says so.
7. **Logging**: JSON to stdout with fields `ts, level, service, logger, msg, request_id`. Log **events and IDs, never ticket text, tokens or passwords**. INFO for normal events, WARNING for retries and degraded state, ERROR for failed requests.
8. **Request ID**: read `X-Request-ID` (the gateway sets it). If missing, generate a UUID. Store it in a `contextvars.ContextVar`, add it to every log line through a logging filter, and **forward it** on outbound calls.
9. **Health**: `GET /health` returns 200 only if the service can do its job, e.g. the DB answers `SELECT 1` within 1s and the model is loaded. Otherwise 503 with the reason.
10. **No dead code, no commented-out code, no "for later" options.** If you take a known shortcut, mark it on one line:
    `# shortcut: <the limit>, <when to upgrade>`

### 0.6.4 Tests
- Every endpoint gets at least: one happy path, one validation failure (422), and one dependency failure (model down / DB error).
- Unit tests must run **without network and without Docker**: `pytest -m "not integration"`.
- Integration tests use a real Postgres (Jenkins starts a throwaway one; locally `docker compose up -d postgres`). Read the address from `DATABASE_URL`, and delete only the rows you created.
- Put test data in fixtures in `tests/conftest.py`. Never read `data/processed/` in a unit test.

### 0.6.5 Git workflow
- `main` is always deployable. Work on short-lived branches: `a/<phase>-<topic>` (Team A), `b/<phase>-<topic>` (Team B).
- Commits use Conventional Commits: `feat(backend): add pending endpoint`, `fix(feedback): reject same label`, `test(...)`, `chore(...)`, `docs(...)`.
- Every PR needs **one approval from the other developer** plus a green Jenkins build. Paste the build link in the PR description.
- PR description template: *What / Why / Dry tests run / Gate checklist ticked by*.

### 0.6.6 Docker rules
- Base image `python:3.11-slim` (Python services), `nginxinc/nginx-unprivileged:1.27-alpine` (gateway, listens on 8080), `postgres:16-alpine` (DB). Always pin the tag, never `latest`.
- **Build context is the repo root** for every image (`build: {context: ., dockerfile: services/<name>/Dockerfile}`), so images can `COPY config/labels.yaml` and shared files.
- Run as **UID 1000** (`useradd --uid 1000 appuser`, `USER 1000`). Hugging Face Spaces also require UID 1000.
- Copy `requirements.txt` and install **before** copying code, so Docker's layer cache survives code edits.
- `HEALTHCHECK` uses Python, because `curl` isn't in slim images:
  `CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"`
- All Python services listen on **port 8000** inside the container.
- No secrets in `ARG`/`ENV`/files in the image. Secrets arrive only at runtime as env vars.

**Python service Dockerfile template**
```dockerfile
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --uid 1000 --create-home appuser
WORKDIR /app
COPY services/backend-api/requirements.txt .
RUN pip install -r requirements.txt
COPY config/labels.yaml /app/config/labels.yaml
COPY services/backend-api/app ./app
USER 1000
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
```

### 0.6.7 Windows machines (all four of us)
- Install **Docker Desktop with the WSL2 backend**. Run commands in **Git Bash or WSL**, not cmd.
- Run `git config --global core.autocrlf false` once. `.gitattributes` forces LF line endings. A CRLF shell script fails inside Linux containers with `/bin/sh^M: not found`.
- We don't use `make`. Commands are written out in each phase.

### 0.6.8 Shared code
There is **one** piece of logic that must be identical in training and serving: `build_text()` in `ml/triage_ml/text.py`. The model-service image **copies that exact file** (`COPY ml/triage_ml/text.py ./app/text.py`). Never re-implement it, or the model will see different text in production than in training (training/serving skew).

```python
# ml/triage_ml/text.py
import re


def build_text(subject: str | None, body: str) -> str:
    text = f"{(subject or '').strip()}\n\n{body.strip()}".strip()
    return re.sub(r"[ \t]+", " ", text)
```

### 0.6.9 Two gotchas worth knowing in advance
- **CPU-only torch.** `pip install sentence-transformers` pulls the CUDA build of torch (gigabytes) by default. In `ml/requirements.txt` and `services/model-service/requirements.txt`, put `--extra-index-url https://download.pytorch.org/whl/cpu` on the first line and pin `torch==<version>+cpu`.
- **`.dockerignore` is a whitelist:**
  ```
  *
  !config/
  !ml/
  !services/
  !scripts/
  !data/processed/
  **/tests/
  **/__pycache__/
  **/.pytest_cache/
  ```

## 0.7 Service contracts

All JSON, UTF-8. Python services listen on port **8000** in the container. Errors always use `{"detail": "<code>"}` with these codes.

### 0.7.1 model-service (runs on HF Space; optional local copy with profile `local-model`)
| Method & path | Request | Success | Errors |
|---|---|---|---|
| `POST /predict` | `{"subject": str\|null (≤300), "body": str (1..5000)}` | 200 `{"label": str, "confidence": float, "top_k": [{"label": str, "score": float}] (3 items, highest first), "model_version": str}` | 422 validation; 503 `model_loading` |
| `GET /health` | – | 200 `{"status": "ok", "model_version": "<40-char sha>", "encoder": str}` | 503 `{"status": "loading"}` |
| `GET /metrics` | – | Prometheus text | – |

- `model_version` is the **HF model repo commit SHA** the service loaded, resolved at startup even if configured as `main`.
- On HF the Space is **private**. Callers send `Authorization: Bearer <HF_TOKEN_READ>`, and HF checks it before our code runs. The service itself has no auth code.

### 0.7.2 backend-api (internal; public only through the gateway as `/api/*`)
| Method & path | Request | Success | Errors |
|---|---|---|---|
| `POST /tickets` | `{"subject": str\|null (≤300), "body": str (1..5000), "source": "stream"\|"manual"\|"smoke", "dataset_label": str\|null}` | 201 `{"ticket_id": uuid, "prediction": {"prediction_id": uuid, "label", "confidence", "top_k", "model_version"}}` | 422 validation (incl. `dataset_label` given when source≠`stream`, or not in labels.yaml); 502 `model_unavailable` (**nothing is written**); 503 `db_unavailable` |
| `GET /tickets/pending?limit=20` | `limit` 1..100 | 200 `[{"prediction_id","ticket_id","subject","body","predicted_label","confidence","top_k","model_version","created_at"}]`, oldest first, only predictions with **no feedback yet** | 422 |
| `GET /labels` | – | 200 `{"labels": [10 strings from config/labels.yaml]}` | – |
| `GET /health` | – | 200 `{"status":"ok"}` | 503 `{"status":"degraded","db":false}` |
| `GET /metrics` | – | Prometheus text | – |

`POST /tickets` steps:
1. Validate.
2. Call model-service `/predict` (timeout `MODEL_CALL_TIMEOUT_SECONDS`, **no retry**: the caller retries).
3. In **one transaction**:
   - upsert `model_versions` (`ON CONFLICT DO NOTHING`, status `production`)
   - insert `tickets`
   - insert `predictions`
4. Return 201.

### 0.7.3 feedback-service (internal; public only through the gateway as `/feedback-api/*`)
| Method & path | Request | Success | Errors |
|---|---|---|---|
| `POST /feedback` | Header `X-Reviewer` (1..64 chars, **set by the gateway, never by the browser**). Body `{"prediction_id": uuid, "is_correct": bool, "corrected_label": str\|null}` | 201 `{"feedback_id": int}` | 401 `missing_reviewer`; 422 validation (`corrected_label` must be null when correct; required, in labels.yaml, and ≠ predicted label when incorrect: code `same_as_prediction`); 404 `unknown_prediction`; 409 `already_reviewed`; 503 `db_unavailable` |
| `GET /health`, `GET /metrics` | – | as above | – |

Use the database constraints as the final check: a UNIQUE violation means 409, and a foreign-key violation means 404. After a successful insert, increment the metrics in 0.10, **unless the ticket's `source` is `smoke`**.

### 0.7.4 gateway (the only public service)
| Path | Goes to | Auth |
|---|---|---|
| `/healthz` | answered by nginx itself: `200 ok` | none |
| `/` | static frontend files | basic auth |
| `/api/` | `http://backend-api:8000/` (prefix stripped) | basic auth |
| `/feedback-api/` | `http://feedback-service:8000/` (prefix stripped), with `X-Reviewer: $remote_user` | basic auth |

On every proxied request the gateway sets `X-Request-ID: $request_id`, and it **overwrites** any client-supplied `X-Reviewer`.

### 0.7.5 ticket-generator (internal; no HTTP server)
It reads `/app/data/stream.parquet` and `/app/data/heldout.parquet` (baked into its image) and calls `POST http://backend-api:8000/tickets` every `TICKET_INTERVAL_SECONDS`. Its health is a heartbeat: it touches `/state/heartbeat` every tick, and the Dockerfile HEALTHCHECK fails if the file is older than 3× the interval.

## 0.8 Configuration contract (`.env.example`)

Copy it to `.env` and fill in real values. **`.env` is never committed.**

```dotenv
# ---------- images ----------
REGISTRY=                       # empty locally; e.g. ghcr.io/<org>/ on AWS (note trailing slash)
IMAGE_TAG=dev                   # Jenkins sets the git short SHA

# ---------- gateway ----------
GATEWAY_PORT=8080               # host port, bound to 127.0.0.1
GATEWAY_HTPASSWD='reviewer1:$2y$05$...\nsmoke:$2y$05$...'
                                # htpasswd lines joined with \n. MUST be in single quotes: the hashes contain "$",
                                # which Compose would otherwise try to expand.
                                # generate one line: docker run --rm httpd:2.4-alpine htpasswd -nbB <user> <pass>
                                # users: one per reviewer + "smoke"

# ---------- database ----------
POSTGRES_PASSWORD=change-me     # letters and digits only (it is embedded in a URL)
                                # DATABASE_URL is NOT set here: docker-compose.yml builds it from POSTGRES_PASSWORD
                                # (nested ${} inside .env does not expand reliably everywhere this file is read)

# ---------- model ----------
HF_MODEL_REPO=<hf-org>/triageiq-classifier
HF_SPACE_REPO=<hf-org>/triageiq-model-service
MODEL_SERVICE_URL=https://<hf-org>-triageiq-model-service.hf.space   # local copy: http://model-service:8000
MODEL_SERVICE_TOKEN=            # = HF_TOKEN_READ for the private Space; empty for the local copy
MODEL_CALL_TIMEOUT_SECONDS=30
HF_TOKEN_READ=                  # fine-grained, read-only: model repo + Space
HF_TOKEN_WRITE=                 # fine-grained, write: model repo + Space. Jenkins + ML devs ONLY
MODEL_REVISION=main             # used only by the local model-service copy

# ---------- generator ----------
TICKET_INTERVAL_SECONDS=15
DRIFT_ENABLED=false
DRIFT_START_AFTER=100           # tickets sent before drift begins
DRIFT_RATIO=0.4                 # share of held-out tickets once drift is on
DRIFT_SEED=42

# ---------- experiment tracking & data (DagsHub) ----------
MLFLOW_TRACKING_URI=https://dagshub.com/<user>/triageiq.mlflow
MLFLOW_TRACKING_USERNAME=<dagshub-user>
MLFLOW_TRACKING_PASSWORD=<dagshub-token>
DAGSHUB_USER=<dagshub-user>
DAGSHUB_TOKEN=<dagshub-token>

# ---------- ops (Team B) ----------
JENKINS_ADMIN_PASSWORD=change-me
GITHUB_REPO_URL=https://github.com/<org>/triageiq.git
GITHUB_TOKEN=                   # fine-grained, read-only contents
DOCKER_SOCK_GID=0               # see Team B guide B1
RETRAIN_WEBHOOK_TOKEN=          # long random string
GRAFANA_ADMIN_PASSWORD=change-me
TUNNEL_TOKEN=                   # named Cloudflare tunnel only (B5)

# ---------- common ----------
LOG_LEVEL=INFO
SMOKE_PASSWORD=                 # plain password of the "smoke" user in GATEWAY_HTPASSWD (smoke test + Jenkins)
```

## 0.9 Database schema (`services/postgres/migrations/001_init.sql`)

Postgres runs files in `/docker-entrypoint-initdb.d/` **only on an empty volume**.

```sql
CREATE TABLE tickets (
  ticket_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subject       TEXT,
  body          TEXT NOT NULL,
  source        TEXT NOT NULL CHECK (source IN ('stream','manual','smoke')),
  dataset_label TEXT,                 -- original dataset label (stream only), never shown in UI
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE model_versions (
  model_version TEXT PRIMARY KEY,     -- HF model repo commit SHA
  hf_repo       TEXT NOT NULL,
  mlflow_run_id TEXT,
  dvc_data_rev  TEXT,                 -- md5 of the data used (from .dvc files)
  eval_metrics  JSONB,
  status        TEXT NOT NULL CHECK (status IN ('candidate','production','rejected','retired')),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  promoted_at   TIMESTAMPTZ
);

CREATE TABLE predictions (
  prediction_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ticket_id       UUID NOT NULL REFERENCES tickets(ticket_id),
  model_version   TEXT NOT NULL REFERENCES model_versions(model_version),
  predicted_label TEXT NOT NULL,
  confidence      REAL NOT NULL,
  top_k           JSONB NOT NULL,
  latency_ms      INTEGER,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX predictions_ticket_idx  ON predictions(ticket_id);
CREATE INDEX predictions_version_idx ON predictions(model_version);

CREATE TABLE training_runs (
  run_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  trigger           TEXT NOT NULL CHECK (trigger IN ('alert','schedule','manual')),
  jenkins_build_id  TEXT,
  mlflow_run_id     TEXT,
  feedback_cutoff   BIGINT,           -- max feedback_id included
  feedback_md5      TEXT,             -- DVC md5 of the exported feedback snapshot
  candidate_version TEXT REFERENCES model_versions(model_version),
  outcome           TEXT NOT NULL DEFAULT 'running'
                    CHECK (outcome IN ('running','promoted','rejected','skipped','failed')),
  started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at       TIMESTAMPTZ
);

CREATE TABLE feedback (
  feedback_id     BIGSERIAL PRIMARY KEY,
  prediction_id   UUID NOT NULL UNIQUE REFERENCES predictions(prediction_id),
  is_correct      BOOLEAN NOT NULL,
  corrected_label TEXT,
  reviewer_id     TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK ((is_correct AND corrected_label IS NULL) OR (NOT is_correct AND corrected_label IS NOT NULL))
);
CREATE INDEX feedback_created_idx ON feedback(created_at);

-- Retraining set: every human-reviewed, non-smoke ticket with its confirmed label.
CREATE VIEW labeled_feedback AS
SELECT f.feedback_id, t.ticket_id, t.subject, t.body,
       COALESCE(f.corrected_label, p.predicted_label) AS label,
       p.model_version, f.reviewer_id, f.created_at
FROM feedback f
JOIN predictions p USING (prediction_id)
JOIN tickets t     USING (ticket_id)
WHERE t.source <> 'smoke';
```

`DEFAULT gen_random_uuid()` is built into Postgres 13+, so no extension is needed.

## 0.10 Metrics contract (names are fixed: Team B's alerts and dashboards depend on them)

| Service | Metric (as seen by Prometheus) | Type | Labels | Incremented when |
|---|---|---|---|---|
| backend-api | `triageiq_predictions_total` | Counter | `model_version`, `label` | a non-smoke prediction is stored |
| backend-api | `triageiq_model_call_seconds` | Histogram, buckets `0.05,0.1,0.25,0.5,1,2.5,5,10,30` | – | every call to model-service |
| backend-api | `triageiq_model_call_errors_total` | Counter | `reason` ∈ `timeout`,`http_error`,`bad_response` | a model call fails |
| feedback-service | `triageiq_feedback_total` | Counter | `model_version` | non-smoke feedback stored |
| feedback-service | `triageiq_feedback_incorrect_total` | Counter | `model_version` | …and `is_correct = false` |
| all Python services | default HTTP metrics from `prometheus-fastapi-instrumentator` | – | – | automatic |

In code you create `Counter("triageiq_feedback", "...", ["model_version"])`. The client library adds the `_total` suffix itself, so **don't** name it `..._total` in code.

## 0.11 Dataset: source, traits, decisions

### 0.11.1 Source
- **`Tobi-Bueck/customer-support-tickets`** on Hugging Face (DOI `10.57967/hf/6184`). One split, `train`.
- **License: CC BY-NC 4.0** (non-commercial). This is fine for coursework. Put the attribution in `data/README.md` and in the HF model card. Never redistribute it commercially.
- **Pin the dataset revision.** `prepare.py` records `HfApi().dataset_info(...).sha` and loads with `revision=<sha>`, so everyone gets byte-identical data.

### 0.11.2 Measured traits (from the HF statistics API; `prepare.py` asserts them)
| Column | Type | Nulls | Facts |
|---|---|---|---|
| `subject` | text | 5,299 (8.6%) | length 3–675 chars, median 45 |
| `body` | text | **2** | length 4–2,259 chars, median 415 |
| `answer` | text | 13,189 (21.4%) | agent reply. **Not used** (it would leak the answer) |
| `queue` | label | 0 | **52 values**: our target |
| `type` | label | 13,178 | Incident 19,444 · Request 13,950 · Problem 10,196 · Change 4,997 |
| `priority` | label | 0 | medium 23,378 · high 21,925 · low 12,765 · critical 1,914 · very_low 1,783 |
| `language` | label | 0 | **de 33,504 · en 28,261** |
| `version` | int | 33,178 | values cluster at 51 (9,988 rows) and 400 (18,599 rows). Looks like generation batches |
| `tag_1..tag_6` | label | 21–79% | 211–956 distinct values each. **Not used** |

**Total rows: 61,765.**

**The 52 queues are two different datasets merged.**
- **10 helpdesk queues: 48,587 rows.** We use these:

| Queue | Rows (all languages) |
|---|---|
| Technical Support | 14,186 |
| Product Support | 8,960 |
| Customer Service | 7,420 |
| IT Support | 5,725 |
| Billing and Payments | 4,874 |
| Returns and Exchanges | 2,438 |
| Service Outages and Maintenance | 1,912 |
| Sales and Pre-Sales | 1,490 |
| Human Resources | 914 |
| General Inquiry | 668 |

- **42 "Topic/Subtopic" queues: 13,178 rows** (230–386 each, e.g. `Games`, `Finance/Investments`). These are web-topic categories, not support queues. **We drop them.**
  - Their row count equals the null count of `type` and `tag_1` exactly (13,178). They are very likely the rows without type/tags. `prepare.py` asserts this.

**Other traits to design for**
- **Imbalance**: the largest class is about 21× the smallest. Use `class_weight="balanced"` and judge models by **macro-F1**, not accuracy.
- **Overlapping classes**: *Technical Support*, *IT Support* and *Product Support* mean similar things. Expect most confusion between them. That's a property of the data, not a bug.
- **Probably synthetic.** The `version` batches suggest generated data. It's fine for this project, but expect duplicates and near-duplicates (hence the dedup step), and mention it in the report.
- **Text length**: a median ticket is ~100 tokens. The encoder truncates at 256 tokens, so only the longest tickets lose their tail.

### 0.11.3 Decisions (already made, don't re-decide)
| Decision | Value | Why |
|---|---|---|
| Rows used | the 10 helpdesk queues only | the other 42 are a different task |
| Language | **English only** for this project | human reviewers must be able to read the tickets |
| Model input | `build_text(subject, body)` (0.6.8) | identical in training and serving |
| Label | `queue` | – |
| **Held-out queue (drift demo)** | **Service Outages and Maintenance** | never in train/val/golden. Released only by the generator when drift is on. The baseline model has 9 classes, the UI always offers all 10 labels, and retraining from corrections adds the 10th |
| Deduplication | exact duplicates of normalized text (lowercase, whitespace collapsed) are dropped, keeping the first. Count conflicting-label duplicates | prevents train/test leakage |
| Splits (of the 9-class English pool) | stratified, seed 42: **train 60% · val 10% · golden 10% · stream 20%** | stream = "production" tickets the model never saw. Golden = frozen regression test set, never trained on, ever |
| Model | `sentence-transformers/all-MiniLM-L6-v2` embeddings (pinned revision, normalized) + scikit-learn `LogisticRegression(class_weight="balanced", max_iter=2000)`, `C` picked from {0.1, 1, 10} on val macro-F1 | trains in minutes on CPU; ~90 MB encoder |
| Primary metric | macro-F1 (golden) | imbalance |
| Alert metric | error ratio of reviewed predictions (≈ 1 − accuracy) | what the feedback measures |

### 0.11.4 Processed data files (`data/processed/`, DVC-tracked)
| File | Contents |
|---|---|
| `train.parquet`, `val.parquet`, `golden.parquet`, `stream.parquet` | columns: `row_id` (int, index in the raw file), `text`, `subject`, `body`, `label`, `priority`, `type`, `language`, `version` |
| `heldout.parquet` | same columns; all English, deduplicated *Service Outages and Maintenance* rows |
| `stats.json` | dataset revision, counts after every filter step, per-split per-label counts, held-out count |

## 0.12 Accounts, tokens, least privilege

| Account | Owner | What | Tokens |
|---|---|---|---|
| GitHub | Team lead | private repo `triageiq`, branch protection on `main` (1 approval) | Jenkins: fine-grained, **read-only contents** |
| Hugging Face | Team A | org `<hf-org>`; private model repo `triageiq-classifier`; private Space `triageiq-model-service` | `HF_TOKEN_READ` (backend + Space), `HF_TOKEN_WRITE` (Jenkins + ML devs only) |
| DagsHub | Team A | repo `triageiq` (gives a DVC remote + hosted MLflow) | one token per developer + one for Jenkins |
| Cloudflare | Team B | only needed for a named tunnel with your own domain (B5). Quick tunnels need no account | tunnel token |

Never share personal tokens. Each person uses their own, and Jenkins has its own.

## 0.13 Using an AI coding agent with this guide
Give the agent: **Part 0 + exactly one phase section**, plus the files that phase touches. Tell it:
1. "Follow Part 0 exactly. Don't add libraries, endpoints, options or files that aren't listed."
2. "Write the phase's dry tests first, then the code, then run the tests."
3. "Don't change any contract in 0.7–0.10. If one seems wrong, stop and tell me."

Then **you** run the gate checklist. The agent doesn't tick it.

---

# PART A — TEAM A PHASES

Owners:
- **A-ML developer**: Phase 0 accounts, A1, A2, A3, A9.
- **A-App developer**: Phase 0 stubs, A4, A5, A6, A7.
- **Both**: A8.

## Phase 0 — Skeleton (joint, all four people, one session)

**Goal**: everyone can clone, run `docker compose up`, and see stub services. Team B has something to build in CI.

**Steps**
1. Team lead creates the GitHub repo and adds the files from 0.4 that exist on day one: `.gitattributes`, `.gitignore`, `.dockerignore`, `.env.example`, `pyproject.toml`, `config/labels.yaml`, `README.md`, the directory tree.
2. `config/labels.yaml`:
   ```yaml
   labels:
     - Technical Support
     - Product Support
     - Customer Service
     - IT Support
     - Billing and Payments
     - Returns and Exchanges
     - Sales and Pre-Sales
     - Human Resources
     - General Inquiry
     - Service Outages and Maintenance
   heldout_labels:
     - Service Outages and Maintenance
   ```
3. **A-App** creates **stubs** for backend-api, feedback-service and ticket-generator: the real Dockerfile (0.6.6), `app/main.py` with only `GET /health` returning 200, and an empty `/metrics` via the instrumentator. The ticket-generator stub just sleeps and writes its heartbeat. Also:
   - the gateway with the real nginx config (A6 spec below, frontend = one "coming soon" page)
   - postgres with the real `001_init.sql` (0.9)
4. **A-App** writes the first `docker-compose.yml`: top-level `name: triageiq`, the default-profile services (gateway, backend-api, feedback-service, ticket-generator, postgres), named volume `pgdata`, and `generator_state`. Template for one service:
   ```yaml
   name: triageiq
   services:
     backend-api:
       build: {context: ., dockerfile: services/backend-api/Dockerfile}
       image: ${REGISTRY:-}triageiq-backend-api:${IMAGE_TAG:-dev}
       environment:
         DATABASE_URL: postgresql://triageiq:${POSTGRES_PASSWORD}@postgres:5432/triageiq
         MODEL_SERVICE_URL: ${MODEL_SERVICE_URL}
         MODEL_SERVICE_TOKEN: ${MODEL_SERVICE_TOKEN:-}
         MODEL_CALL_TIMEOUT_SECONDS: ${MODEL_CALL_TIMEOUT_SECONDS:-30}
         HF_MODEL_REPO: ${HF_MODEL_REPO}
         LOG_LEVEL: ${LOG_LEVEL:-INFO}
       depends_on:
         postgres: {condition: service_healthy}
       read_only: true
       tmpfs: [/tmp]
       cap_drop: [ALL]
       security_opt: ["no-new-privileges:true"]
       deploy: {resources: {limits: {memory: 256M, cpus: "0.50"}}}   # starting guess; A8 replaces with measured values
       restart: unless-stopped
   ```
   - Only `gateway` gets `ports: ["127.0.0.1:${GATEWAY_PORT:-8080}:8080"]`.
   - `postgres` gets `healthcheck: {test: ["CMD-SHELL","pg_isready -U triageiq"], interval: 5s, retries: 10}`, `POSTGRES_USER=triageiq`, `POSTGRES_DB=triageiq`, `POSTGRES_PASSWORD=${POSTGRES_PASSWORD}`, volume `pgdata:/var/lib/postgresql/data`.
5. **A-ML** creates the HF org and the DagsHub repo, generates the tokens (0.12), and shares them with each developer privately (password manager, never chat).
6. Team B does its part of Phase 0 at the same time (see the Team B guide).

**Dry tests**: `docker compose --env-file .env.example config -q`

**Gate 0** (ticked by Team B)
- [ ] Fresh clone + `cp .env.example .env` (+ a real `GATEWAY_HTPASSWD`) + `docker compose up -d --build` → all containers `healthy` within 2 minutes
- [ ] `curl -u <user>:<pass> http://127.0.0.1:8080/` shows the placeholder page; `curl http://127.0.0.1:8080/healthz` returns `ok` without a password
- [ ] `docker compose exec postgres psql -U triageiq -c '\dt'` lists 5 tables
- [ ] Nothing except the gateway is reachable from the host (`docker compose ps` shows no other published ports)

---

## A1 — Dataset preparation + DVC (A-ML)

**Goal**: reproducible, versioned train/val/golden/stream/heldout files whose traits are checked in code.

**Files**: `ml/triage_ml/text.py`, `ml/triage_ml/prepare.py`, `ml/tests/test_prepare.py`, `ml/tests/test_text.py`, `ml/requirements*.txt`, `data/README.md`, `.dvc/config`, `data/raw/tickets.parquet.dvc`, `data/processed.dvc`.

**Setup (once per machine)**
```bash
python -m venv .venv && source .venv/Scripts/activate      # Git Bash on Windows
pip install -r ml/requirements.txt -r ml/requirements-dev.txt
dvc init                                                    # first person only; commit .dvc/
dvc remote add -d origin https://dagshub.com/<user>/triageiq.dvc     # first person only
dvc remote modify origin --local auth basic
dvc remote modify origin --local user $DAGSHUB_USER
dvc remote modify origin --local password $DAGSHUB_TOKEN    # --local => .dvc/config.local, gitignored
```

**`prepare.py` steps** (run as `python -m triage_ml.prepare`)
1. Resolve the dataset revision: `HfApi().dataset_info("Tobi-Bueck/customer-support-tickets").sha`. Allow `--revision` to override.
2. Load: `datasets.load_dataset(..., split="train", revision=sha).to_pandas()`. Add `row_id = df.index`. Save `data/raw/tickets.parquet`.
3. **Assert raw traits** (fail loudly with a clear message):
   - `len(df) == 61765`
   - `df.queue.nunique() == 52`
   - the 10 core queues exist with the exact counts in 0.11.2
   - `df.body.isna().sum() == 2`
   - `set(df.language) == {"de","en"}`
   - every row with null `type` is a non-core queue: `df[df.type.isna()].queue.isin(CORE).sum() == 0`. If this one fails, **stop and tell the team**. Don't silently continue.
4. Keep the 10 core queues → drop null `body` → keep `language == "en"`. Record every count.
5. `text = build_text(subject, body)`. `norm = text.lower()` with all whitespace collapsed to one space.
6. Deduplicate on `norm`, keeping the first. Record `duplicates_removed`, plus `conflicting_label_duplicates` (same `norm`, different `queue`).
7. `label = queue`. Split off **held-out**: all rows with label *Service Outages and Maintenance* → `heldout.parquet`.
8. Split the remaining 9-class pool with `train_test_split(..., stratify=label, random_state=42)`:
   - first take 20% as **stream**
   - split the rest 75/12.5/12.5 into **train / val / golden** (= 60/10/10 of the pool)
9. **Assert** no `norm` value appears in two files (leakage check), and every class has ≥ 20 rows in each of val/golden/stream. If a class doesn't, print the counts and fail.
10. Write the parquet files (0.11.4 columns) and `stats.json`.
11. Print a summary table.

**Then**
```bash
dvc add data/raw/tickets.parquet data/processed
git add data/raw/tickets.parquet.dvc data/processed.dvc data/.gitignore data/raw/.gitignore
dvc push
```
Record the English count, dedup counts and per-split counts from `stats.json` in `data/README.md`, together with the license attribution.

**Dry tests**
- `test_text.py`: `build_text(None, " a  b ")` → `"a b"`, a subject is joined with a blank line, and tabs are collapsed.
- `test_prepare.py`: refactor steps 4–9 into a pure function `make_splits(df) -> dict[str, DataFrame]`, and test it on a **hand-made 60-row fixture DataFrame** (no download):
  - non-core and German rows are removed
  - duplicates are removed
  - held-out rows land only in `heldout`
  - no text appears in two splits
  - the proportions are roughly right
- Network-dependent asserts (step 3) run only in the real run, not in pytest.

**Gate A1** (ticked by the A-App developer)
- [ ] On a second machine, `dvc pull` gives the same files, and `md5sum data/processed/*.parquet` matches
- [ ] `stats.json` exists and the counts are copied into `data/README.md`
- [ ] All step-3 assertions passed on the real data (paste the console output in the PR)
- [ ] `pytest ml/tests` green without network

---

## A2 — Baseline model + MLflow (A-ML)

**Goal**: a trained baseline, tracked in MLflow, with artifacts ready to publish.

**Files**: `ml/triage_ml/train.py`, `ml/tests/test_train.py`.

**`train.py`** (`python -m triage_ml.train --out artifacts/ [--feedback-snapshot PATH] [--sample N] [--no-mlflow] [--run-id UUID]`)
1. Load `train/val/golden.parquet`. With `--sample N`, take N stratified rows per split, for quick runs.
2. The encoder is `SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", revision=<pinned sha>)`.
   - Pin the sha in a constant: get it once with `HfApi().model_info(...).sha`.
   - Encode with `encode(texts, batch_size=64, normalize_embeddings=True)`.
   - The encoder is passed in as a parameter (`embed_fn`) so tests can inject a fake.
3. For each `C` in `[0.1, 1.0, 10.0]`: fit `LogisticRegression(C=C, class_weight="balanced", max_iter=2000)` on train, and score macro-F1 on val. Keep the best.
4. Evaluate the chosen model on **golden**: accuracy, macro-F1, per-class F1, confusion matrix.
5. Write `--out`:
   - `classifier.joblib`: the fitted LogisticRegression
   - `metadata.json`: `{"encoder", "encoder_revision", "classes", "C", "trained_at", "mlflow_run_id", "data": {"dataset_revision", "processed_md5", "feedback_md5"}, "metrics": {...}}`
   - `README.md`: model card, with license CC BY-NC 4.0 and the dataset attribution
   - `classification_report.txt`, `confusion_matrix.csv`
   - Get `processed_md5` from `data/processed.dvc` (field `outs[0].md5`).
6. MLflow (skip with `--no-mlflow`):
   - experiment `triageiq-classifier`
   - log params (encoder, encoder_revision, C, class_weight, rows per split, dataset_revision, processed_md5, feedback_md5)
   - log metrics (`val_macro_f1`, `golden_accuracy`, `golden_macro_f1`, `golden_f1_<label>`)
   - log every file in `--out` as artifacts, plus the `.dvc` files used
   - tags: `git_sha` and `trigger`
7. `--feedback-snapshot` is used in A9. Accept the flag now but just reject it with "not implemented in A2".

**Security note**: `joblib` files are pickles, and loading one runs code. Only ever load `classifier.joblib` from **our own private repo at a pinned revision**.

**Dry tests**: `test_train.py` runs the full pipeline on a 40-row fixture with a **fake `embed_fn`** (e.g. a hash of the text → 8 floats). Assert that it runs, writes all artifact files, and that `metadata.json` has every key. No network, no MLflow (`--no-mlflow`).

**Run it**: `python -m triage_ml.train --out artifacts/baseline`, then check the run on DagsHub's MLflow UI.

**Gate A2** (ticked by A-App)
- [ ] The MLflow run is visible on DagsHub with params, metrics and artifacts
- [ ] Golden macro-F1 ≥ **0.40**. This is a sanity floor (9-class random ≈ 0.11), not a target. Below it means a bug
- [ ] `data/README.md` has a **Baseline** section: golden accuracy, macro-F1, per-class F1, the top-3 confusions. **Tell Team B the golden accuracy** (they set the alert threshold from it)
- [ ] `pytest ml/tests` green offline

---

## A3 — model-service + Hugging Face model repo and Space (A-ML)

**Goal**: the baseline served from a private HF Space, and the same code runnable locally.

**Files**: `services/model-service/app/*`, `services/model-service/tests/*`, `services/model-service/Dockerfile`, `services/model-service/SPACE_README.md`, `services/model-service/requirements*.txt`, `ml/triage_ml/publish.py`, `ml/triage_ml/deploy_space.py`, `ml/triage_ml/promote.py`.

**model-service behaviour**
- Settings: `HF_MODEL_REPO`, `MODEL_REVISION` (default `main`), `HF_TOKEN` (optional; read token for the private repo), `LOG_LEVEL`. Set `HF_HOME=/tmp/hf` in the Dockerfile, a writable cache.
- In `lifespan`, **in a background thread** so `/health` responds right away:
  1. resolve `sha = HfApi().model_info(HF_MODEL_REPO, revision=MODEL_REVISION, token=...).sha`
  2. `hf_hub_download` `classifier.joblib` and `metadata.json` **at that sha**
  3. load the encoder named in metadata at its pinned revision
  4. mark ready
- `/predict`: `build_text` (copied file, 0.6.8) → encode → `predict_proba` → top 3. `label` = top-1 and `confidence` = its probability. Returns 503 `model_loading` until ready.
- The model loader is behind `Depends` so tests inject a fake model.

**Dockerfile** (root context): template from 0.6.6 plus
```dockerfile
ENV HF_HOME=/tmp/hf
COPY services/model-service/requirements.txt .
RUN pip install -r requirements.txt
COPY ml/triage_ml/text.py ./app/text.py
COPY services/model-service/app ./app
```

**`SPACE_README.md`** (it becomes the Space's `README.md`):
```markdown
---
title: TriageIQ Model Service
sdk: docker
app_port: 8000
pinned: false
---
Private inference service for TriageIQ.
```

**`publish.py`** (`python -m triage_ml.publish --artifacts DIR [--dry-run]`)
1. `create_repo(HF_MODEL_REPO, private=True, exist_ok=True)`
2. `commit = upload_folder(folder_path=DIR, repo_id=HF_MODEL_REPO, commit_message=...)` and print `commit.oid` (the new `model_version`)
3. Insert a `model_versions` row with status `candidate` (needs `DATABASE_URL`; skipped with `--no-db`)

`--dry-run` only lists the files and the target repo.

**`deploy_space.py`** (`python -m triage_ml.deploy_space [--dry-run]`)
- Copy into a temp dir, **keeping monorepo paths**:
  - `services/model-service/Dockerfile` → `Dockerfile`
  - `SPACE_README.md` → `README.md`
  - `services/model-service/requirements.txt` → same path
  - `services/model-service/app/` → same path
  - `ml/triage_ml/text.py` → same path
- On the Space, the build context is the Space repo root. Because the paths are preserved, the same Dockerfile `COPY` lines work there **and** locally.
- `create_repo(HF_SPACE_REPO, repo_type="space", space_sdk="docker", private=True, exist_ok=True)`, then `upload_folder(..., repo_type="space")`.

**`promote.py`** (`python -m triage_ml.promote --revision SHA [--dry-run]`)
1. `add_space_secret(HF_SPACE_REPO, "HF_TOKEN", HF_TOKEN_READ)` (idempotent)
2. `add_space_variable(HF_SPACE_REPO, "HF_MODEL_REPO", ...)` and `add_space_variable(HF_SPACE_REPO, "MODEL_REVISION", SHA)`
3. `restart_space(HF_SPACE_REPO)`
4. Poll `GET {MODEL_SERVICE_URL}/health` with the bearer token every 15s, up to 15 min, until `model_version == SHA`. Otherwise exit 1.
5. In one DB transaction:
   - the old `production` row(s) → `retired`
   - SHA → `production`, `promoted_at = now()` (upsert if missing)
   - skipped with `--no-db`

`--dry-run` prints steps 1–5 without calling anything. A9 adds `--rollback`.

**Do it (baseline)**
```bash
python -m triage_ml.publish --artifacts artifacts/baseline --no-db   # prints SHA. --no-db: Postgres isn't reachable from your
                                                                     # host shell; backend-api records the version on first prediction
python -m triage_ml.deploy_space
python -m triage_ml.promote --revision <SHA> --no-db
curl -H "Authorization: Bearer $HF_TOKEN_READ" "$MODEL_SERVICE_URL/health"
```
- Copy the exact Space URL from the Space page ("Embed this Space" → direct URL) into `.env`.
- Free Spaces **sleep when idle**. The first request after a sleep can take a minute or more. That's expected, and the backend handles it with 502 + the caller retrying.

**Local copy**: add the `model-service` service to `docker-compose.yml` with `profiles: [local-model]`, `HF_TOKEN: ${HF_TOKEN_READ}`, `MODEL_REVISION: ${MODEL_REVISION:-main}`, a 2G memory limit, and no published port. To use it, set `MODEL_SERVICE_URL=http://model-service:8000` and an empty `MODEL_SERVICE_TOKEN`.

**Dry tests**
- Route tests with a fake model: `/predict` happy path (3 top_k items, sorted), 422 for an empty body and for a body over 5000 chars, 503 while loading, `/health` 503 then 200.
- `publish/deploy_space/promote --dry-run` exit 0 and print the expected targets (pytest calls `main([...,"--dry-run"])` with network calls mocked).

**Gate A3** (ticked by A-App)
- [ ] `curl` with the read token → `/health` shows the baseline SHA. `/predict` on a real ticket text returns a sensible label
- [ ] Without the token, the Space URL returns 401/404 (it is private)
- [ ] `docker compose --profile local-model up -d model-service` → the same `/health` from inside the network (`docker compose exec backend-api python -c "..."`)
- [ ] The model repo has `classifier.joblib`, `metadata.json` and `README.md`, and the model card shows the license

---

## A4 — backend-api (A-App)

**Goal**: the ticket intake and prediction-storage API from 0.7.2, with real SQL.

**Files**: `services/backend-api/app/*`, tests, requirements.

**Key implementation points**
- `clients.py`: `ModelClient.predict(subject, body, request_id) -> Prediction`, using `httpx.Client(timeout=MODEL_CALL_TIMEOUT_SECONDS)`.
  - Add `Authorization: Bearer` only if a token is set. Forward `X-Request-ID`.
  - Map timeout, non-2xx and an invalid response schema to `ModelUnavailable(reason)`. Increment `triageiq_model_call_errors_total{reason}` and observe `triageiq_model_call_seconds` around every call.
- `db.py`: one function per SQL statement:
  - `insert_ticket_with_prediction(conn, ticket, prediction, hf_repo)`: runs the upsert of `model_versions` + the two inserts in **one** transaction
  - `pending(conn, limit)`:
    ```sql
    SELECT p.prediction_id, t.ticket_id, t.subject, t.body, p.predicted_label,
           p.confidence, p.top_k, p.model_version, t.created_at
    FROM predictions p
    JOIN tickets t USING (ticket_id)
    LEFT JOIN feedback f USING (prediction_id)
    WHERE f.feedback_id IS NULL
    ORDER BY t.created_at
    LIMIT %s;
    ```
- `latency_ms`: measured around the model call.
- Labels: load `/app/config/labels.yaml` once at startup. `dataset_label`, if given, must be in it.
- Increment `triageiq_predictions_total{model_version,label}` after the commit, unless source = `smoke`.

**Dry tests**
- Unit (fake `ModelClient`, fake DB functions):
  - 201 happy path
  - 422 cases (empty body, body > 5000, unknown `dataset_label`, `dataset_label` with source `manual`)
  - 502 when the client raises (**and the DB insert function is never called**)
  - `/labels` returns 10
- Integration (real Postgres):
  - a POST creates exactly one ticket, prediction and model_versions row
  - a second POST with the same model_version doesn't duplicate model_versions
  - `pending` excludes predictions that have feedback (insert a feedback row directly in SQL)

**Gate A4** (ticked by A-ML)
- [ ] With the local-model profile running: `curl -u u:p -X POST localhost:8080/api/tickets -H 'content-type: application/json' -d '{"subject":"VPN down","body":"Cannot connect to VPN since morning","source":"manual","dataset_label":null}'` → 201 with a prediction
- [ ] `GET /api/tickets/pending` lists it. `/metrics` shows `triageiq_predictions_total` with the right labels
- [ ] Stopping model-service → POST returns 502, and no new rows appear in `tickets`
- [ ] Logs are JSON lines with `request_id`, and contain no ticket text

---

## A5 — feedback-service (A-App)

**Goal**: record reviewer verdicts, linked to predictions, and expose the counters the alert uses.

**Implementation points**
- A missing or empty `X-Reviewer` → 401.
- Validation order:
  1. pydantic shape
  2. if `is_correct`, `corrected_label` must be null
  3. else it's required and in labels.yaml
  4. load the prediction (`SELECT p.predicted_label, p.model_version, t.source FROM predictions p JOIN tickets t USING (ticket_id) WHERE p.prediction_id = %s`). If missing → 404
  5. if `corrected_label == predicted_label` → 422 `same_as_prediction`
  6. INSERT. A UNIQUE violation (`psycopg.errors.UniqueViolation`) → 409
- After the commit: `feedback.labels(model_version).inc()`, plus `feedback_incorrect.labels(model_version).inc()` if incorrect. Skip both when source = `smoke`.

**Dry tests**
- Unit (fake DB): every error code in 0.7.3, and the counters increment by the right amount (read them with `prometheus_client.REGISTRY.get_sample_value`).
- Integration: insert a ticket + prediction with SQL, POST feedback → 201, POST again → 409, `labeled_feedback` returns the corrected label. A smoke ticket's feedback is excluded from the view.

**Gate A5** (ticked by A-ML)
- [ ] Through the gateway: feedback on the A4 prediction → 201, repeat → 409, the reviewer stored = the basic-auth username
- [ ] Sending your own `X-Reviewer: someone-else` header through the gateway is ignored (the stored value is still your username)
- [ ] `/metrics` counters are correct after 3 correct + 2 incorrect submissions

---

## A6 — gateway + frontend (A-App)

**Goal**: the only public entry point, plus the reviewer UI.

**`services/gateway/nginx.conf.template`** (the nginx image renders `/etc/nginx/templates/*.template` into `/etc/nginx/conf.d/` with envsubst at start)
```nginx
limit_req_zone $binary_remote_addr zone=perip:10m rate=10r/s;

# Behind Cloudflare Tunnel every request arrives from the cloudflared container. Trust its
# CF-Connecting-IP header only from Docker-network addresses, so rate limits are per real user.
set_real_ip_from 172.16.0.0/12;
set_real_ip_from 192.168.0.0/16;
set_real_ip_from 10.0.0.0/8;
real_ip_header CF-Connecting-IP;

server {
  listen 8080;                       # unprivileged image: non-root, so no port 80
  client_max_body_size 64k;
  server_tokens off;
  add_header X-Content-Type-Options nosniff always;
  add_header X-Frame-Options DENY always;
  add_header Referrer-Policy no-referrer always;

  location = /healthz { auth_basic off; access_log off; return 200 'ok'; }   # server-level auth is inherited; switch it off here

  auth_basic "TriageIQ";
  auth_basic_user_file /tmp/htpasswd;
  limit_req zone=perip burst=20 nodelay;

  location / { root /usr/share/nginx/html; try_files $uri /index.html; }

  location /api/ {
    proxy_pass http://backend-api:8000/;
    proxy_set_header X-Request-ID $request_id;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 60s;
  }

  location /feedback-api/ {
    proxy_pass http://feedback-service:8000/;
    proxy_set_header X-Request-ID $request_id;
    proxy_set_header X-Reviewer $remote_user;        # overwrites anything the client sent
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  }

  location ~ ^/(api|feedback-api)/metrics { return 404; }   # metrics are internal only
}
```
- **`entrypoint.sh`**: write the htpasswd file from env, then hand over to nginx's normal entrypoint:
  ```sh
  #!/bin/sh
  set -eu
  printf '%b\n' "$GATEWAY_HTPASSWD" > /tmp/htpasswd
  exec /docker-entrypoint.sh nginx -g 'daemon off;'
  ```
- **Dockerfile**:
  - `FROM nginxinc/nginx-unprivileged:1.27-alpine` (runs as UID 101, listens on 8080)
  - `COPY` the template to `/etc/nginx/templates/default.conf.template`, the frontend to `/usr/share/nginx/html`, and `entrypoint.sh` (`chmod +x`)
  - `ENTRYPOINT ["/entrypoint.sh"]`
  - `HEALTHCHECK CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1`
- **Compose**:
  - `ports: ["127.0.0.1:${GATEWAY_PORT:-8080}:8080"]`
  - `read_only: true`, `tmpfs: [/tmp, /etc/nginx/conf.d]` (the template is rendered into conf.d at start)
  - `depends_on` backend-api and feedback-service with `condition: service_healthy`. nginx refuses to start if an upstream hostname doesn't resolve yet.
  - Inside the Docker network, the gateway is `http://gateway:8080`.

**Frontend** (`index.html`, `app.js`, `styles.css`, no build step)
- **Header**: app name and the logged-in reviewer. **Pending count** badge.
- **Review list**: polls `GET /api/tickets/pending?limit=20` every 5s. Each card shows:
  - subject (bold), body (first 600 chars, with "show more")
  - predicted label, confidence as %, top-3 with scores
  - model version (first 7 chars of the SHA)
  - **"✓ Correct"** button
  - **label dropdown** (all 10 from `GET /api/labels`, the predicted one disabled) + **"Fix"** button
  - **After submitting**, the card disappears. On 409, show "already reviewed by someone else" and remove the card.
- **Manual ticket form**: subject (optional), body (required, maxlength 5000) → `POST /api/tickets` with source `manual`. Show the returned prediction. On 502, show "Model is waking up, try again in a minute."
- **Accessibility**: real `<button>` and `<label for>` elements, visible focus outlines, everything usable by keyboard, `aria-live="polite"` on the status message, colour is never the only signal.
- **Security**: render ticket text with `textContent`, **never `innerHTML`**. Ticket bodies are untrusted input (XSS).

**Dry tests**
- nginx config test. It needs fake upstream hosts, because outside compose `backend-api` doesn't resolve:
  ```bash
  docker run --rm --add-host backend-api:127.0.0.1 --add-host feedback-service:127.0.0.1 \
    -e GATEWAY_HTPASSWD='ci:x' --entrypoint sh triageiq-gateway:dev \
    -c 'printf "%b\n" "$GATEWAY_HTPASSWD" > /tmp/htpasswd && /docker-entrypoint.sh nginx -t'
  ```
- `node --check app.js` if Node is available. Otherwise review the JS manually.

**Gate A6** (ticked by A-ML)
- [ ] Browser: login prompt → review list → Correct/Fix work → the card disappears → the DB shows the feedback with your username
- [ ] Manual ticket submit shows a prediction
- [ ] Pasting `<img src=x onerror=alert(1)>` as a ticket body shows the literal text, with no alert
- [ ] The whole flow works using only the keyboard
- [ ] `curl -u u:p localhost:8080/api/metrics` → 404

---

## A7 — ticket-generator (A-App)

**Goal**: a steady stream of realistic tickets, with drift you can switch on.

**Behaviour**
- Settings: `BACKEND_URL` (default `http://backend-api:8000`), `TICKET_INTERVAL_SECONDS`, `DRIFT_ENABLED`, `DRIFT_START_AFTER`, `DRIFT_RATIO`, `DRIFT_SEED`.
- State file `/state/cursor.json`: `{"sent": int, "stream_pos": int, "heldout_pos": int}` (named volume `generator_state`).
- Each tick:
  1. Pick the next row with a **pure function** `pick_next(state, cfg, rng) -> ("stream"|"heldout", pos)`:
     - if drift is enabled, `sent >= DRIFT_START_AFTER`, and `rng.random() < DRIFT_RATIO` → held-out
     - otherwise stream
     - positions wrap to 0 at the end of a file, with a WARNING log
  2. POST `{"subject", "body", "source": "stream", "dataset_label": label}`.
  3. **Only on 201**: advance the cursor and save it (write to a temp file, then `os.replace`). On any error, log a WARNING and retry the same row next tick.
  4. Touch `/state/heartbeat`.
- The `rng` is `random.Random(DRIFT_SEED + state["sent"])`, so a run is reproducible across restarts.
- **Dockerfile**: `COPY data/processed/stream.parquet data/processed/heldout.parquet /app/data/`. The data must be pulled with DVC before building, and Jenkins does this in a stage.

**Dry tests**
- `pick_next` table tests:
  - drift off → always stream
  - drift on, before `DRIFT_START_AFTER` → stream
  - drift on, after it → about `DRIFT_RATIO` held-out over 1,000 picks (±5%)
  - wrap-around works
- Cursor tests: it doesn't advance on failure, and a restart resumes from the saved state.

**Gate A7** (ticked by A-ML)
- [ ] With `TICKET_INTERVAL_SECONDS=5`, tickets appear in the UI every ~5s
- [ ] `docker compose restart ticket-generator` doesn't resend old tickets (row IDs keep increasing)
- [ ] With `DRIFT_ENABLED=true DRIFT_START_AFTER=5`, held-out tickets start appearing after 5, and the model mislabels them (it has never seen the class)
- [ ] With model-service down, the generator logs warnings and resumes cleanly when it comes back

---

## A8 — Integration, smoke test, resource limits (both Team A developers)

**Goal**: the full app runs from a clean state, a script proves it, and memory limits are measured, not guessed.

**`scripts/smoke_test.py`** (stdlib only; env `GATEWAY_URL` = `http://127.0.0.1:8080` from your host, or `http://gateway:8080` from Jenkins; `SMOKE_USER`, `SMOKE_PASSWORD`; exits non-zero on the first failure, printing which step failed)
1. `GET /healthz` → 200
2. `GET /api/labels` → 10 labels
3. `POST /api/tickets` with source `smoke` → 201. On 502, retry every 10s for up to 180s (the Space may be asleep)
4. `GET /api/tickets/pending?limit=100` contains the new `prediction_id`
5. `POST /feedback-api/feedback` `is_correct=true` → 201
6. Repeat → 409
7. Print `SMOKE OK <model_version>`

**Resource measurement** (this replaces the starting guesses in Phase 0)
1. Run the full stack with the generator at 5s for 15 minutes while one person reviews tickets.
2. `docker stats --no-stream` every few minutes, and note each container's **peak** memory.
3. Set `deploy.resources.limits.memory` = **2 × peak**, rounded up to a 64 MB multiple. CPU limit `0.5` for the app services unless `docker stats` shows them pinned at the limit.
4. Write the table (service, observed peak, limit) in `README.md`. Team B reuses it for Kubernetes requests/limits in B6.

**Gate A8: App POC** (ticked by Team B)
- [ ] `docker compose down -v && docker compose up -d --build` → everything healthy → `python scripts/smoke_test.py` prints `SMOKE OK`, twice in a row
- [ ] The full reviewer flow works with the real HF Space
- [ ] The resource table is in README and the limits are applied
- [ ] Every Team A service has a passing `pytest -m "not integration"` without network

---

## A9 — Retrain, evaluate, promote tooling (A-ML, MLOps phase)

**Goal**: the command-line tools that Team B's retrain pipeline (B8) calls. Every tool works from a terminal and has `--dry-run`. **Exit codes are a contract.**

| Command | Does | Exit codes |
|---|---|---|
| `python -m triage_ml.runs should-run --cooldown-minutes 60` | exit 10 if a model was promoted in the last N minutes, or there is no new feedback since the last run's cutoff | 0 run · 10 skip |
| `python -m triage_ml.runs start --trigger alert --build <id>` | inserts a `training_runs` row, prints `run_id` | 0 |
| `python -m triage_ml.export_feedback --run-id ID --out data/feedback/` | `cutoff = max(feedback_id)`; writes `data/feedback/feedback_<cutoff>.parquet` from `labeled_feedback` (feedback_id ≤ cutoff) with the 0.11.4 columns (`text` via `build_text`); stores the cutoff on the run; prints the file path | 0 · 4 if fewer than 50 rows |
| `python -m triage_ml.train --feedback-snapshot FILE --run-id ID --out artifacts/` | as A2, but: split the snapshot 80/20 (seed 42, stratified where every class has ≥2 rows, else random) → **train = base train + 80% feedback**; the 20% is saved as `artifacts/feedback_holdout.parquet`; log `feedback_md5` | 0 |
| `python -m triage_ml.evaluate --challenger artifacts/ --out eval.json` | gets the **champion** = the `production` row in `model_versions`, downloads its artifacts at that SHA; scores **both** models on (a) golden and (b) `feedback_holdout.parquet` | 0 challenger wins · 3 loses · 4 holdout < 20 rows |
| `python -m triage_ml.publish --artifacts artifacts/ --run-id ID` | as A3, also sets `training_runs.candidate_version` | 0 |
| `python -m triage_ml.promote --revision SHA` / `--rollback` | as A3. `--rollback` = promote the most recently `retired` version | 0 · 1 timeout |
| `python -m triage_ml.runs finish --run-id ID --outcome promoted\|rejected\|skipped\|failed` | sets the outcome + `finished_at`; marks the candidate `rejected` if the outcome is rejected | 0 |

**Champion-vs-challenger rule** (in `evaluate.py`; the numbers are constants at the top of the file):
- challenger `golden_macro_f1 ≥ champion_golden_macro_f1 − 0.02` (no real regression on the frozen set), **and**
- challenger `feedback_macro_f1 > champion_feedback_macro_f1` (actually better on what reviewers now see)

Write both models' scores to `eval.json` and log them to the challenger's MLflow run.

**Container**: `ml/Dockerfile` builds image `triageiq-ml` with the `triage_ml` package, `dvc`, git, and the CPU torch stack. Jenkins runs the retrain stages inside it.

**Dry tests**
- `evaluate` decision logic as a pure function `decide(champion, challenger) -> (code, reason)`, with table tests: win / golden regression / no feedback gain / tiny holdout.
- `export_feedback` against a throwaway Postgres (integration): smoke rows excluded, cutoff respected.
- `train --feedback-snapshot` on fixtures with the fake `embed_fn`: the feedback rows actually change the training set, and a class that exists only in the feedback appears in `metadata.classes`.
- Every command's `--dry-run` exits 0 with network mocked.

**Gate A9** (ticked by Team B)
- [ ] By hand from a terminal on the running stack: enable drift → review ~60 tickets (correcting the held-out ones) → `export_feedback` → `train --feedback-snapshot` → `evaluate` exits 0 → `publish` → `promote` → the UI shows the new model version, and the held-out queue is now predicted correctly most of the time
- [ ] `promote --rollback` returns to the previous version
- [ ] MLflow shows both runs, linked by `feedback_md5`, with the champion/challenger scores
