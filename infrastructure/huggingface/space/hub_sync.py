"""Move backups between this Space and its private Hugging Face dataset.

  python hub_sync.py fetch DEST [BACKUP_ID]   download wob.dump and storage.tar to DEST
  python hub_sync.py push SRC                 upload SRC/* as a new backup and mark it latest

The dataset is BACKUP_DATASET; HF_TOKEN must be able to read it (and write, for push). Each
backup is a folder <id>/ holding wob.dump and storage.tar; the file LATEST names the newest.
"""

import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

REPO = os.environ["BACKUP_DATASET"]


def latest() -> str:
    path = hf_hub_download(REPO, "LATEST", repo_type="dataset")
    return Path(path).read_text().strip()


def fetch(dest: Path, backup_id: str | None) -> None:
    backup_id = backup_id or latest()
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("wob.dump", "storage.tar"):
        path = hf_hub_download(
            REPO, f"{backup_id}/{name}", repo_type="dataset", local_dir=dest / "download"
        )
        shutil.move(path, dest / name)
    shutil.rmtree(dest / "download", ignore_errors=True)
    (dest / "BACKUP_ID").write_text(backup_id)
    print(f"fetched backup {backup_id} from {REPO}")


def push(src: Path) -> None:
    backup_id = "space-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    api = HfApi()
    api.upload_folder(
        repo_id=REPO,
        repo_type="dataset",
        folder_path=src,
        path_in_repo=backup_id,
        commit_message=f"Backup {backup_id} from the Space",
    )
    api.upload_file(
        repo_id=REPO,
        repo_type="dataset",
        path_or_fileobj=backup_id.encode(),
        path_in_repo="LATEST",
        commit_message=f"Mark {backup_id} as the latest backup",
    )
    print(f"pushed backup {backup_id} to {REPO}")


if __name__ == "__main__":
    command, path, *rest = sys.argv[1:]
    if command == "fetch":
        fetch(Path(path), rest[0] if rest else None)
    elif command == "push":
        push(Path(path))
    else:
        sys.exit(f"unknown command {command!r}")
