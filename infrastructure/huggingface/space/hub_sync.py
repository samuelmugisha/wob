"""Move backups between this Space and its private Hugging Face dataset.

  python hub_sync.py fetch DEST [REQUESTED]   download the backup to restore into DEST
  python hub_sync.py push SRC ORIGIN          upload SRC/* as a new backup and mark it latest
  python hub_sync.py prune KEEP               delete all but the newest KEEP Space backups

The dataset is BACKUP_DATASET; HF_TOKEN must be able to read it (and write, for push and prune).
Each backup is a folder <id>/ holding wob.dump and storage.tar; the file LATEST names the newest.

A Space backup also holds ORIGIN: the backup its data started from (a server backup such as
20261111-212954). fetch restores REQUESTED (the RESTORE_BACKUP variable) only when it is not the
origin of the latest backup, so a restore that was already done is not repeated on every start,
and the Space's own later work is kept. Otherwise fetch restores LATEST.
"""

import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from huggingface_hub import CommitOperationDelete, HfApi, hf_hub_download
from huggingface_hub.errors import EntryNotFoundError

REPO = os.environ["BACKUP_DATASET"]
SPACE_PREFIX = "space-"


def read(path_in_repo: str) -> str | None:
    try:
        path = hf_hub_download(REPO, path_in_repo, repo_type="dataset")
    except EntryNotFoundError:
        return None
    return Path(path).read_text().strip()


def fetch(dest: Path, requested: str | None) -> None:
    latest = read("LATEST")
    if not latest:
        sys.exit(f"{REPO} has no LATEST file")
    latest_origin = read(f"{latest}/ORIGIN") or latest
    if requested and requested not in (latest, latest_origin):
        backup_id, origin = requested, requested
        print(f"RESTORE_BACKUP={requested} is new: restoring it instead of {latest}")
    else:
        backup_id, origin = latest, latest_origin
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("wob.dump", "storage.tar"):
        path = hf_hub_download(
            REPO, f"{backup_id}/{name}", repo_type="dataset", local_dir=dest / "download"
        )
        shutil.move(path, dest / name)
    shutil.rmtree(dest / "download", ignore_errors=True)
    (dest / "BACKUP_ID").write_text(backup_id)
    (dest / "ORIGIN").write_text(origin)
    print(f"fetched backup {backup_id} (started from {origin}) from {REPO}")


def push(src: Path, origin: str) -> None:
    backup_id = SPACE_PREFIX + datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    (src / "ORIGIN").write_text(origin)
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


def prune(keep: int) -> None:
    """Delete old Space backups. Server backups (uploaded with hub.py) are never deleted."""
    api = HfApi()
    folders = {f.split("/")[0] for f in api.list_repo_files(REPO, repo_type="dataset")}
    old = sorted(f for f in folders if f.startswith(SPACE_PREFIX))[:-keep]
    if old:
        api.create_commit(
            repo_id=REPO,
            repo_type="dataset",
            operations=[CommitOperationDelete(f"{f}/", is_folder=True) for f in old],
            commit_message=f"Remove {len(old)} old Space backups",
        )
        print(f"removed {len(old)} old Space backups from {REPO}")


if __name__ == "__main__":
    command, arg, *rest = sys.argv[1:]
    if command == "fetch":
        fetch(Path(arg), rest[0] if rest and rest[0] else None)
    elif command == "push":
        push(Path(arg), rest[0])
    elif command == "prune":
        prune(int(arg))
    else:
        sys.exit(f"unknown command {command!r}")
