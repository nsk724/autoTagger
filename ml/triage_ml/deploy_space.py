import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

from triage_ml.config import ROOT

# monorepo path -> path in the Space repo; paths are kept so the Dockerfile COPY lines work in both
FILES = {
    "services/model-service/Dockerfile": "Dockerfile",
    "services/model-service/SPACE_README.md": "README.md",
    "services/model-service/requirements.txt": "services/model-service/requirements.txt",
    "services/model-service/app": "services/model-service/app",
    "ml/triage_ml/text.py": "ml/triage_ml/text.py",
}


def stage(dest: Path) -> None:
    for src, dst in FILES.items():
        target = dest / dst
        target.parent.mkdir(parents=True, exist_ok=True)
        if (ROOT / src).is_dir():
            shutil.copytree(ROOT / src, target, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(ROOT / src, target)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Push the model-service code to the HF Space.")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    space = os.environ["HF_SPACE_REPO"]
    if args.dry_run:
        for src, dst in FILES.items():
            print(f"would copy {src} -> {dst}")
        print(f"would upload to Space {space} (docker, private)")
        return 0

    from huggingface_hub import HfApi

    api = HfApi(token=os.environ["HF_TOKEN_WRITE"])
    api.create_repo(space, repo_type="space", space_sdk="docker", private=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        stage(Path(tmp))
        commit = api.upload_folder(
            folder_path=tmp, repo_id=space, repo_type="space", commit_message="deploy model-service"
        )
    print(commit.oid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
