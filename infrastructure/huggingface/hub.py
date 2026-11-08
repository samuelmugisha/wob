"""Publish backups and the app to Hugging Face. See docs/operations/huggingface.md.

  uv run --no-project --with huggingface_hub python infrastructure/huggingface/hub.py \
      upload-backup ~/wob-backups/20261108-120000 --dataset you/wob-backups
  uv run --no-project --with huggingface_hub python infrastructure/huggingface/hub.py \
      push-space --space you/wob-awards --dataset you/wob-backups \
      --env ~/wob-backups/keys/env-20261108-120000

Uses your Hugging Face login (`hf auth login`) or HF_TOKEN. For push-space, set
SPACE_HF_TOKEN to a fine-grained token the Space uses to read the dataset (and write to it, if
BACKUP_UPLOAD is on); it is stored as the Space secret HF_TOKEN.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

# Settings copied from the server's env file into Space secrets. Database, site address and
# memory caps are not: the Space has its own.
FORWARDED = [
    "SECRET_KEY",
    "FILE_ENCRYPTION_KEYS",
    "FILE_ENCRYPTION_ACTIVE_KEY",
    "MFA_REQUIRED_ROLES",
    "LLM_PROVIDER",
    "EXTERNAL_AI_PROCESSING_APPROVED",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL",
    "RESEARCH_ENABLED",
    "RESEARCH_PROVIDER",
    "RESEARCH_MODEL",
    "RESEARCH_EFFORT",
    "UPLOAD_REQUIRES_CONSENT",
    "JURY_VERIFIES_SUPPORTING_DOCUMENTS",
    "LANGSMITH_TRACING",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
    "LANGSMITH_ENDPOINT",
    "EMAIL_BACKEND",
    "EMAIL_FROM",
    "EMAIL_FROM_NAME",
    "EMAIL_REPLY_TO",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_SECURITY",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
]
REQUIRED = ["SECRET_KEY", "FILE_ENCRYPTION_KEYS"]


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def upload_backup(args: argparse.Namespace) -> None:
    backup = Path(args.backup).expanduser().resolve()
    dump, storage = backup / "wob.dump", backup / "storage"
    if not dump.is_file() or not storage.is_dir():
        sys.exit(f"{backup} has no wob.dump and storage/: run backup.sh first")
    backup_id = backup.name
    api = HfApi()
    api.create_repo(args.dataset, repo_type="dataset", private=True, exist_ok=True)
    if not api.repo_info(args.dataset, repo_type="dataset").private:
        sys.exit(f"{args.dataset} is public: make it private before uploading personal data")

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / backup_id
        stage.mkdir()
        shutil.copy2(dump, stage / "wob.dump")
        with tarfile.open(stage / "storage.tar", "w") as tar:
            tar.add(storage, arcname=".")
        if (backup / "counts.txt").is_file():
            shutil.copy2(backup / "counts.txt", stage / "counts.txt")
        print(f"Uploading {backup_id} to the private dataset {args.dataset}…")
        api.upload_folder(
            repo_id=args.dataset,
            repo_type="dataset",
            folder_path=stage,
            path_in_repo=backup_id,
            commit_message=f"Backup {backup_id}",
        )
    api.upload_file(
        repo_id=args.dataset,
        repo_type="dataset",
        path_or_fileobj=backup_id.encode(),
        path_in_repo="LATEST",
        commit_message=f"Mark {backup_id} as the latest backup",
    )
    print(f"Done: {args.dataset} now serves {backup_id} as the latest backup.")


def stage_space(stage: Path) -> None:
    """The Space repository: tracked backend/ and frontend/ files plus the Space's own files."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "backend", "frontend"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode()
    for rel in filter(None, listed.split("\0")):
        src = ROOT / rel
        if src.is_file():
            (stage / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, stage / rel)
    shutil.copy2(HERE / "Dockerfile", stage / "Dockerfile")
    shutil.copy2(HERE / "README.md", stage / "README.md")
    shutil.copytree(HERE / "space", stage / "space")


def push_space(args: argparse.Namespace) -> None:
    api = HfApi()
    env = read_env(Path(args.env).expanduser()) if args.env else {}
    missing = [key for key in REQUIRED if not env.get(key)]
    if args.env and missing:
        sys.exit(f"{args.env} lacks {', '.join(missing)}")

    api.create_repo(
        args.space, repo_type="space", space_sdk="docker", private=args.private, exist_ok=True
    )
    # Secrets and variables first, so the first build already starts with them.
    for key in FORWARDED:
        if env.get(key):
            api.add_space_secret(args.space, key, env[key])
    if token := os.environ.get("SPACE_HF_TOKEN"):
        api.add_space_secret(args.space, "HF_TOKEN", token)
    if args.dataset:
        api.add_space_variable(args.space, "BACKUP_DATASET", args.dataset)
    if args.env:
        print(f"Set {sum(1 for k in FORWARDED if env.get(k))} secrets from {args.env}")

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        stage_space(stage)
        print(f"Uploading the app to the Space {args.space}…")
        api.upload_folder(
            repo_id=args.space,
            repo_type="space",
            folder_path=stage,
            delete_patterns="*",  # mirror: remove files no longer in the app
            commit_message=args.message,
        )
    print(f"Done. Build log: https://huggingface.co/spaces/{args.space}?logs=build")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("upload-backup", help="upload a backup.sh folder to a private dataset")
    p.add_argument("backup", help="folder written by backup.sh, e.g. ~/wob-backups/2026…")
    p.add_argument("--dataset", required=True, help="dataset repo id, e.g. you/wob-backups")
    p.set_defaults(func=upload_backup)

    p = sub.add_parser("push-space", help="create or update the Space")
    p.add_argument("--space", required=True, help="Space repo id, e.g. you/wob-awards")
    p.add_argument("--dataset", help="dataset the Space restores from (BACKUP_DATASET)")
    p.add_argument("--env", help="server env file saved by backup.sh, copied into secrets")
    p.add_argument("--private", action="store_true", help="create the Space as private")
    p.add_argument("--message", default="Deploy the app", help="commit message")
    p.set_defaults(func=push_space)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
