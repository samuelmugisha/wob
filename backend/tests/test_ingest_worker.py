"""End-to-end ingestion: upload via the API, process with the worker, read the knowledge base."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.services.scanning import ScannerError, ScanResult
from tests import fixture_files
from tests.conftest import drain
from tests.test_knowledge_base import make_candidate, make_category, upload


class InfectedScanner:
    def scan(self, data: bytes) -> ScanResult:
        return ScanResult(clean=False, scanner="clamav", signature="Eicar-Test-Signature")


class BrokenScanner:
    def scan(self, data: bytes) -> ScanResult:
        raise ScannerError("virus scanner unavailable at clamav:3310: refused")


@pytest.fixture(autouse=True)
def _empty_queue(empty_queue: None) -> None:
    pass


def candidate_with_files(coordinator: TestClient, files: list[tuple[str, bytes]]):
    category = make_category(coordinator)
    candidate = make_candidate(coordinator, category["id"])
    body = upload(coordinator, category["id"], candidate["id"], files).json()
    assert len(body["accepted"]) == len(files), body
    return category, candidate, {d["filename"]: d["id"] for d in body["accepted"]}


def document(coordinator: TestClient, category, candidate, document_id: str) -> dict:
    url = f"/api/v1/categories/{category['id']}/finalists/{candidate['id']}/documents"
    docs = coordinator.get(url, params={"include_withdrawn": True}).json()
    return next(d for d in docs if d["id"] == document_id)


def test_documents_are_indexed_into_the_knowledge_base(
    coordinator: TestClient, make_pipeline, engine: Engine
) -> None:
    category, candidate, ids = candidate_with_files(
        coordinator,
        [
            ("nomination.pdf", fixture_files.pdf_with_structure()),
            ("letter.docx", fixture_files.docx_document()),
            ("attendance.xlsx", fixture_files.xlsx_workbook()),
        ],
    )
    assert drain(make_pipeline()) == 3

    for name, document_id in ids.items():
        doc = document(coordinator, category, candidate, document_id)
        assert doc["processing_status"] == "indexed", (name, doc["processing_error"])
        quality = doc["extraction_quality"]
        assert quality["chunks"] >= 1
        assert quality["embedding_model"] == "fake:hashing"
        assert "not scanned for malware (scanning disabled)" in quality["warnings"]

    pdf_quality = document(coordinator, category, candidate, ids["nomination.pdf"])
    assert pdf_quality["extraction_quality"]["pages"] == 2

    chunks = coordinator.get(f"/api/v1/documents/{ids['nomination.pdf']}/chunks").json()
    assert all(c["embedded"] for c in chunks)
    joined = "\n".join(c["content"] for c in chunks)
    assert "Section: Nomination statement" in joined
    assert "| 2021 | Example Holdings | Audit Chair |" in joined
    assert chunks[0]["page_number"] == 1

    # Keyword search over the knowledge base, scoped to this candidate.
    with engine.connect() as conn:
        hits = conn.execute(
            text(
                "SELECT filename FROM knowledge_base_chunks WHERE finalist_category_id = :fc "
                "AND content_tsv @@ plainto_tsquery('english', 'audit chair')"
            ),
            {"fc": candidate["finalist_category_id"]},
        ).scalars()
        assert set(hits) >= {"nomination.pdf", "letter.docx"}


def test_withdrawn_documents_leave_the_knowledge_base(
    coordinator: TestClient, make_pipeline, engine: Engine
) -> None:
    _, candidate, ids = candidate_with_files(
        coordinator, [("letter.docx", fixture_files.docx_document())]
    )
    drain(make_pipeline())

    def visible_chunks() -> int:
        with engine.connect() as conn:
            return conn.execute(
                text("SELECT count(*) FROM knowledge_base_chunks WHERE finalist_category_id = :fc"),
                {"fc": candidate["finalist_category_id"]},
            ).scalar_one()

    assert visible_chunks() > 0
    coordinator.post(f"/api/v1/documents/{ids['letter.docx']}/withdraw", json={"reason": "Wrong"})
    assert visible_chunks() == 0


def test_withdrawn_before_processing_is_skipped(coordinator: TestClient, make_pipeline) -> None:
    _, _, ids = candidate_with_files(coordinator, [("letter.docx", fixture_files.docx_document())])
    coordinator.post(f"/api/v1/documents/{ids['letter.docx']}/withdraw", json={"reason": "Wrong"})
    assert drain(make_pipeline()) == 0


def test_malware_is_rejected_and_never_parsed(coordinator: TestClient, make_pipeline) -> None:
    category, candidate, ids = candidate_with_files(
        coordinator, [("letter.docx", fixture_files.docx_document())]
    )
    drain(make_pipeline(scanner=InfectedScanner()))

    doc = document(coordinator, category, candidate, ids["letter.docx"])
    assert doc["processing_status"] == "rejected"
    assert doc["processing_error"] == "malware detected (Eicar-Test-Signature)"
    assert doc["extraction_quality"]["malware_scan"]["result"] == "infected"
    assert coordinator.get(f"/api/v1/documents/{ids['letter.docx']}/chunks").json() == []

    # A coordinator can queue it again (e.g. after a false positive is resolved).
    response = coordinator.post(f"/api/v1/documents/{ids['letter.docx']}/reprocess")
    assert response.status_code == 200
    assert response.json()["processing_status"] == "pending"
    drain(make_pipeline())
    assert (
        document(coordinator, category, candidate, ids["letter.docx"])["processing_status"]
        == "indexed"
    )


def test_transient_failures_retry_with_backoff(
    coordinator: TestClient, make_pipeline, engine: Engine
) -> None:
    category, candidate, ids = candidate_with_files(
        coordinator, [("letter.docx", fixture_files.docx_document())]
    )
    broken = make_pipeline(scanner=BrokenScanner(), max_processing_attempts=2)
    assert drain(broken) == 1

    doc = document(coordinator, category, candidate, ids["letter.docx"])
    assert doc["processing_status"] == "failed"
    assert doc["processing_attempts"] == 1
    assert "virus scanner unavailable" in doc["processing_error"]
    assert drain(broken) == 0  # not due yet

    def make_due() -> None:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE documents SET next_attempt_at = now() - interval '1 second' "
                    "WHERE id = :id AND next_attempt_at IS NOT NULL"
                ),
                {"id": ids["letter.docx"]},
            )

    make_due()
    assert drain(broken) == 1
    doc = document(coordinator, category, candidate, ids["letter.docx"])
    assert doc["processing_attempts"] == 2
    assert "gave up after 2 attempts" in doc["processing_error"]
    make_due()
    assert drain(broken) == 0  # out of attempts

    # Once the scanner is back, a coordinator can requeue it.
    coordinator.post(f"/api/v1/documents/{ids['letter.docx']}/reprocess")
    drain(make_pipeline())
    assert (
        document(coordinator, category, candidate, ids["letter.docx"])["processing_status"]
        == "indexed"
    )


def test_tampered_original_is_rejected(
    coordinator: TestClient, make_pipeline, tmp_path: Path, engine: Engine
) -> None:
    category, candidate, ids = candidate_with_files(
        coordinator, [("letter.docx", fixture_files.docx_document())]
    )
    with engine.connect() as conn:
        key = conn.execute(
            text("SELECT storage_key FROM documents WHERE id = :id"), {"id": ids["letter.docx"]}
        ).scalar_one()
    stored = tmp_path / "storage" / key
    stored.chmod(0o644)
    stored.write_bytes(stored.read_bytes() + b"tampered")

    drain(make_pipeline())
    doc = document(coordinator, category, candidate, ids["letter.docx"])
    assert doc["processing_status"] == "rejected"
    assert "failed its integrity check" in doc["processing_error"]


def test_unreadable_documents_are_rejected(coordinator: TestClient, make_pipeline) -> None:
    category, candidate, ids = candidate_with_files(
        coordinator, [("locked.pdf", fixture_files.pdf_with_structure(encrypt="secret"))]
    )
    drain(make_pipeline())
    doc = document(coordinator, category, candidate, ids["locked.pdf"])
    assert doc["processing_status"] == "rejected"
    assert doc["processing_error"] == "the PDF is password-protected"


def test_only_failed_documents_can_be_reprocessed(coordinator: TestClient, make_pipeline) -> None:
    _, _, ids = candidate_with_files(coordinator, [("letter.docx", fixture_files.docx_document())])
    drain(make_pipeline())
    response = coordinator.post(f"/api/v1/documents/{ids['letter.docx']}/reprocess")
    assert response.status_code == 409
