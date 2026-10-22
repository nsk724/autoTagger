import pytest

from triage_ml import deploy_space, evaluate, export_feedback, promote, publish, runs


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("HF_MODEL_REPO", "org/triageiq-classifier")
    monkeypatch.setenv("HF_SPACE_REPO", "org/triageiq-model-service")
    monkeypatch.setenv("MODEL_SERVICE_URL", "https://org-triageiq-model-service.hf.space")

    def no_network(*a, **k):
        raise AssertionError("network call in a dry run")

    monkeypatch.setattr("huggingface_hub.HfApi.__init__", no_network)
    monkeypatch.setattr("psycopg.connect", no_network)
    monkeypatch.setattr("httpx.get", no_network)


def test_publish(tmp_path, capsys):
    (tmp_path / "classifier.joblib").write_text("x")
    assert publish.main(["--artifacts", str(tmp_path), "--dry-run"]) == 0
    assert "org/triageiq-classifier" in capsys.readouterr().err


def test_deploy_space(capsys):
    assert deploy_space.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "services/model-service/Dockerfile -> Dockerfile" in out
    assert "org/triageiq-model-service" in out


@pytest.mark.parametrize("args", [["--revision", "abc"], ["--rollback"]])
def test_promote(args, capsys):
    assert promote.main([*args, "--dry-run"]) == 0
    assert "restart Space org/triageiq-model-service" in capsys.readouterr().out


@pytest.mark.parametrize(
    "args",
    [
        ["should-run", "--cooldown-minutes", "60", "--dry-run"],
        ["start", "--trigger", "alert", "--build", "1", "--dry-run"],
        ["finish", "--run-id", "x", "--outcome", "rejected", "--dry-run"],
    ],
)
def test_runs(args):
    assert runs.main(args) == 0


def test_export_and_evaluate(tmp_path):
    assert export_feedback.main(["--run-id", "x", "--out", str(tmp_path), "--dry-run"]) == 0
    args = ["--challenger", str(tmp_path), "--out", str(tmp_path / "e.json"), "--dry-run"]
    assert evaluate.main(args) == 0
