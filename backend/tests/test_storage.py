"""Envelope encryption of stored files (spec §3, §12)."""

import hashlib
import os

import pytest

from app.config import get_settings
from app.services.storage import (
    MAGIC,
    KeyRing,
    LocalStorage,
    StorageError,
    StorageIntegrityError,
    build_storage,
    generate_key,
)

SECRET_TEXT = b"%PDF-1.7 Jane Doe chaired the audit committee of Example Holdings."


def ring(*ids: str, active: str | None = None) -> KeyRing:
    return KeyRing.parse(",".join(f"{i}:{generate_key()}" for i in ids), active)


@pytest.fixture
def store(tmp_path) -> LocalStorage:  # noqa: ANN001
    return LocalStorage(tmp_path, ring("k1"))


def test_round_trip_and_nothing_readable_on_disk(store, tmp_path) -> None:  # noqa: ANN001
    store.put("originals/fc-a/doc.pdf", SECRET_TEXT)
    raw = (tmp_path / "originals/fc-a/doc.pdf").read_bytes()
    assert raw.startswith(MAGIC)
    assert b"Jane Doe" not in raw and b"%PDF" not in raw
    assert store.read("originals/fc-a/doc.pdf") == SECRET_TEXT


def test_each_file_gets_its_own_key_and_nonce(store, tmp_path) -> None:  # noqa: ANN001
    store.put("a.pdf", SECRET_TEXT)
    store.put("b.pdf", SECRET_TEXT)
    assert (tmp_path / "a.pdf").read_bytes() != (tmp_path / "b.pdf").read_bytes()


def test_tampering_is_detected(store, tmp_path) -> None:  # noqa: ANN001
    store.put("doc.pdf", SECRET_TEXT)
    path = tmp_path / "doc.pdf"
    blob = bytearray(path.read_bytes())
    blob[-5] ^= 0x01
    path.write_bytes(bytes(blob))
    with pytest.raises(StorageIntegrityError, match="failed authentication"):
        store.read("doc.pdf")


def test_a_file_moved_to_another_candidate_does_not_decrypt(store, tmp_path) -> None:  # noqa: ANN001
    store.put("originals/fc-a/doc.pdf", SECRET_TEXT)
    (tmp_path / "originals/fc-b").mkdir(parents=True)
    os.link(tmp_path / "originals/fc-a/doc.pdf", tmp_path / "originals/fc-b/doc.pdf")
    with pytest.raises(StorageIntegrityError):
        store.read("originals/fc-b/doc.pdf")


def test_wrong_or_missing_key(store, tmp_path) -> None:  # noqa: ANN001
    store.put("doc.pdf", SECRET_TEXT)
    with pytest.raises(StorageIntegrityError, match="not available"):
        LocalStorage(tmp_path, ring("k2")).read("doc.pdf")
    impostor = KeyRing({"k1": os.urandom(32)}, "k1")
    with pytest.raises(StorageIntegrityError):
        LocalStorage(tmp_path, impostor).read("doc.pdf")


def test_files_are_write_once(store) -> None:
    store.put("doc.pdf", SECRET_TEXT)
    with pytest.raises(FileExistsError):
        store.put("doc.pdf", b"replacement")
    assert store.read("doc.pdf") == SECRET_TEXT


def test_key_rotation_rewraps_without_reencrypting(tmp_path) -> None:  # noqa: ANN001
    old = ring("k1")
    LocalStorage(tmp_path, old).put("doc.pdf", SECRET_TEXT)
    before = (tmp_path / "doc.pdf").read_bytes()
    both = KeyRing({**old.keys, "k2": os.urandom(32)}, "k2")
    rotated = LocalStorage(tmp_path, both)
    assert rotated.rewrap("doc.pdf") is True
    assert rotated.rewrap("doc.pdf") is False  # already on the active key
    after = (tmp_path / "doc.pdf").read_bytes()
    assert after[-len(SECRET_TEXT) - 16 :] == before[-len(SECRET_TEXT) - 16 :]  # same ciphertext
    only_new = LocalStorage(tmp_path, KeyRing({"k2": both.keys["k2"]}, "k2"))
    assert only_new.read("doc.pdf") == SECRET_TEXT  # the old key is no longer needed


def test_legacy_plaintext_is_refused_until_migrated(store, tmp_path) -> None:  # noqa: ANN001
    (tmp_path / "old.pdf").write_bytes(SECRET_TEXT)
    with pytest.raises(StorageIntegrityError, match="without encryption"):
        store.read("old.pdf")
    assert store.encrypt_in_place("old.pdf") is True
    assert store.encrypt_in_place("old.pdf") is False
    assert b"Jane Doe" not in (tmp_path / "old.pdf").read_bytes()
    assert store.read("old.pdf") == SECRET_TEXT


def test_storage_refuses_to_run_without_a_key(tmp_path) -> None:  # noqa: ANN001
    settings = get_settings().model_copy(
        update={
            "storage_dir": tmp_path,
            "file_encryption_keys": None,
            "allow_unencrypted_storage": False,
        }
    )
    with pytest.raises(StorageError, match="never stored unencrypted"):
        build_storage(settings)
    with pytest.raises(StorageError, match="refusing to store plaintext"):
        LocalStorage(tmp_path, None).put("doc.pdf", SECRET_TEXT)


@pytest.mark.parametrize(
    ("spec", "message"),
    [("", "empty"), ("k1:c2hvcnQ", "32 bytes"), ("k1:!!!", "base64|32 bytes")],
)
def test_key_configuration_is_validated(spec, message) -> None:  # noqa: ANN001
    with pytest.raises(StorageError, match=message):
        KeyRing.parse(spec, None)
    with pytest.raises(StorageError, match="not in FILE_ENCRYPTION_KEYS"):
        KeyRing.parse(f"k1:{generate_key()}", "k9")


def test_uploads_and_downloads_are_encrypted_end_to_end(coordinator, tmp_path) -> None:  # noqa: ANN001
    from tests.test_knowledge_base import make_candidate, make_category, upload

    category = make_category(coordinator)
    candidate = make_candidate(coordinator, category["id"])
    doc = upload(coordinator, category["id"], candidate["id"], [("n.pdf", SECRET_TEXT)]).json()
    stored = list((tmp_path / "storage").rglob("*.pdf"))
    assert len(stored) == 1 and b"Jane Doe" not in stored[0].read_bytes()
    download = coordinator.get(f"/api/v1/documents/{doc['accepted'][0]['id']}/content")
    assert download.content == SECRET_TEXT
    assert hashlib.sha256(download.content).hexdigest() == doc["accepted"][0]["sha256_hash"]
