from pathlib import Path

import yaml


def _find_root() -> Path:
    # commands run from the repo root, ml/ (CI unit tests) or the Jenkins workspace
    for p in (Path.cwd(), *Path.cwd().parents):
        if (p / "config" / "labels.yaml").exists():
            return p
    raise SystemExit("config/labels.yaml not found: run from inside the repository")


ROOT = _find_root()
PROCESSED = ROOT / "data" / "processed"
_labels = yaml.safe_load((ROOT / "config" / "labels.yaml").read_text())
LABELS: list[str] = _labels["labels"]
HELDOUT: list[str] = _labels["heldout_labels"]
