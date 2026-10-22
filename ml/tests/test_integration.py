import os
import uuid

import psycopg
import pytest

from triage_ml import export_feedback, runs

pytestmark = pytest.mark.integration


@pytest.fixture
def conn():
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        yield c


def add_reviewed(conn, n: int, source: str = "stream") -> list:
    conn.execute(
        "INSERT INTO model_versions (model_version, hf_repo, status)"
        " VALUES ('it-model', 'x', 'production') ON CONFLICT DO NOTHING"
    )
    tickets = []
    for _ in range(n):
        tid = conn.execute(
            "INSERT INTO tickets (body, source) VALUES (%s, %s) RETURNING ticket_id",
            (f"{source} ticket {uuid.uuid4()}", source),
        ).fetchone()[0]
        pid = conn.execute(
            "INSERT INTO predictions (ticket_id, model_version, predicted_label, confidence, top_k)"
            " VALUES (%s, 'it-model', 'IT Support', 0.5, '[]') RETURNING prediction_id",
            (tid,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO feedback (prediction_id, is_correct, reviewer_id) VALUES (%s, true, 'it')",
            (pid,),
        )
        tickets.append(tid)
    conn.commit()
    return tickets


def cleanup(conn, tickets: list, run_ids: list) -> None:
    conn.execute("DELETE FROM training_runs WHERE run_id = ANY(%s)", (run_ids,))
    conn.execute(
        "DELETE FROM feedback WHERE prediction_id IN"
        " (SELECT prediction_id FROM predictions WHERE ticket_id = ANY(%s))",
        (tickets,),
    )
    conn.execute("DELETE FROM predictions WHERE ticket_id = ANY(%s)", (tickets,))
    conn.execute("DELETE FROM tickets WHERE ticket_id = ANY(%s)", (tickets,))
    conn.commit()


def test_export_excludes_smoke_and_respects_cutoff(conn):
    tickets = add_reviewed(conn, 3) + add_reviewed(conn, 2, source="smoke")
    run_id = runs.start(conn, "manual", "it")
    try:
        cutoff, df = export_feedback.snapshot(conn)
        assert not df.text.str.startswith("smoke ticket").any()
        assert df.row_id.max() <= cutoff

        conn.execute(
            "UPDATE training_runs SET feedback_cutoff = %s WHERE run_id = %s", (cutoff, run_id)
        )
        conn.commit()
        assert runs.should_run(conn, 0)[0] == runs.SKIP  # nothing newer than the cutoff
        tickets += add_reviewed(conn, 1)
        assert runs.should_run(conn, 0)[0] == runs.RUN
    finally:
        cleanup(conn, tickets, [run_id])
