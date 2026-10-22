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
