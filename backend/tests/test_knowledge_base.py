import io
import uuid
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.conftest import ClientFactory


def pdf(marker: str = "") -> bytes:
    return b"%PDF-1.7\n% " + (marker or uuid.uuid4().hex).encode() + b"\n%%EOF\n"


def ooxml(part: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr(part, f"<doc>{uuid.uuid4().hex}</doc>")
    return buffer.getvalue()


def png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + uuid.uuid4().bytes


def archive(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buffer.getvalue()


def make_category(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/categories",
        json={"code": f"cat-{uuid.uuid4().hex[:8]}", "name": "Board Leadership Award"},
    )
    assert response.status_code == 201, response.text
    return response.json()


FULL_CONSENT = {"assessment": True, "ai_processing": True, "web_research": True}


def record_consent(client: TestClient, category_id: str, finalist_id: str, **parts) -> dict:
    response = client.post(
        f"/api/v1/categories/{category_id}/finalists/{finalist_id}/consent",
        json={
            "notice_version": "v1",
            "method": "signed_form",
            "reference": "file 12",
            **FULL_CONSENT,
            **parts,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def make_candidate(
    client: TestClient, category_id: str, name: str = "Jane Doe", consent: dict | None = None
) -> dict:
    """A shortlisted candidate; full consent is recorded unless `consent` says otherwise
    ({} records nothing)."""
    response = client.post(
        f"/api/v1/categories/{category_id}/finalists",
        json={"full_name": name, "organisation": "Example Holdings"},
    )
    assert response.status_code == 201, response.text
    candidate = response.json()
    parts = FULL_CONSENT if consent is None else consent
    if parts:
        record_consent(client, category_id, candidate["id"], **parts)
    return candidate


def upload(
    client: TestClient,
    category_id: str,
    finalist_id: str,
    files: list[tuple[str, bytes]],
    key: str | None = None,
    source_type: str = "supporting_document",
):
    return client.post(
        f"/api/v1/categories/{category_id}/finalists/{finalist_id}/documents",
        files=[("files", (name, data, "application/octet-stream")) for name, data in files],
        data={"source_type": source_type},
        headers={"Idempotency-Key": key or uuid.uuid4().hex},
    )


def documents_url(category_id: str, finalist_id: str) -> str:
    return f"/api/v1/categories/{category_id}/finalists/{finalist_id}/documents"


def test_upload_and_download(coordinator: TestClient) -> None:
    category = make_category(coordinator)
    candidate = make_candidate(coordinator, category["id"])
    nomination = pdf()

    response = upload(
        coordinator,
        category["id"],
        candidate["id"],
        [
            ("nomination.pdf", nomination),
            ("cv.docx", ooxml("word/document.xml")),
            ("board-attendance.xlsx", ooxml("xl/workbook.xml")),
            ("photo.png", png()),
        ],
        source_type="nomination_form",
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["skipped"] == []
    accepted = {d["filename"]: d for d in body["accepted"]}
    assert set(accepted) == {"nomination.pdf", "cv.docx", "board-attendance.xlsx", "photo.png"}
    assert accepted["cv.docx"]["mime_type"].endswith("wordprocessingml.document")
    assert all(d["processing_status"] == "pending" for d in accepted.values())
    assert all(d["source_type"] == "nomination_form" for d in accepted.values())

    listed = coordinator.get(documents_url(category["id"], candidate["id"])).json()
    assert len(listed) == 4

    categories = {c["id"]: c for c in coordinator.get("/api/v1/categories").json()}
    assert categories[category["id"]]["finalist_count"] == 1
    assert categories[category["id"]]["document_count"] == 4

    download = coordinator.get(f"/api/v1/documents/{accepted['nomination.pdf']['id']}/content")
    assert download.status_code == 200
    assert download.content == nomination
    assert "nomination.pdf" in download.headers["content-disposition"]
    assert download.headers["x-content-type-options"] == "nosniff"


def test_file_type_is_checked_by_content(coordinator: TestClient) -> None:
    category = make_category(coordinator)
    candidate = make_candidate(coordinator, category["id"])
    response = upload(
        coordinator,
        category["id"],
        candidate["id"],
        [
            ("renamed.pdf", b"just some text pretending to be a PDF"),
            ("slides.pptx", ooxml("ppt/presentation.xml")),
            ("../../etc/real.pdf", pdf()),
        ],
    )
    body = response.json()
    assert [d["filename"] for d in body["accepted"]] == ["real.pdf"]
    assert {s["filename"] for s in body["skipped"]} == {"renamed.pdf", "slides.pptx"}
    assert all("unsupported" in s["reason"] for s in body["skipped"])


def test_zip_archives_are_expanded_safely(coordinator: TestClient) -> None:
    category = make_category(coordinator)
    candidate = make_candidate(coordinator, category["id"])
    bundle = archive(
        {
            "evidence/annual-report.pdf": pdf(),
            "evidence/letter.docx": ooxml("word/document.xml"),
            "nested.zip": archive({"inner.pdf": pdf()}),
            "../escape.pdf": pdf(),
            "notes.txt": b"plain text",
            "__MACOSX/evidence/._annual-report.pdf": b"resource fork",
        }
    )
    body = upload(coordinator, category["id"], candidate["id"], [("bundle.zip", bundle)]).json()

    accepted = {d["filename"]: d for d in body["accepted"]}
    assert set(accepted) == {"annual-report.pdf", "letter.docx"}
    assert accepted["annual-report.pdf"]["archive_name"] == "bundle.zip"
    assert accepted["annual-report.pdf"]["archive_member"] == "evidence/annual-report.pdf"
    reasons = {s["filename"]: s["reason"] for s in body["skipped"]}
    assert reasons == {
        "bundle.zip › nested.zip": "archives inside archives are not supported",
        "bundle.zip › ../escape.pdf": "unsafe path inside archive",
        "bundle.zip › notes.txt": reasons["bundle.zip › notes.txt"],
    }
    assert "unsupported" in reasons["bundle.zip › notes.txt"]


def test_oversized_files_are_skipped(coordinator: TestClient) -> None:
    category = make_category(coordinator)
    candidate = make_candidate(coordinator, category["id"])
    big = b"%PDF-1.7\n" + b"0" * (300 * 1024)
    body = upload(coordinator, category["id"], candidate["id"], [("big.pdf", big)]).json()
    assert body["accepted"] == []
    assert body["skipped"] == [
        {"filename": "big.pdf", "reason": "file is larger than the size limit"}
    ]


def test_duplicates_are_per_candidate(coordinator: TestClient) -> None:
    category = make_category(coordinator)
    jane = make_candidate(coordinator, category["id"], "Jane Doe")
    mary = make_candidate(coordinator, category["id"], "Mary Major")
    shared = pdf("shared reference letter")

    first = upload(coordinator, category["id"], jane["id"], [("a.pdf", shared), ("b.pdf", shared)])
    assert [d["filename"] for d in first.json()["accepted"]] == ["a.pdf"]
    assert first.json()["skipped"][0]["reason"] == "already uploaded for this candidate"

    again = upload(coordinator, category["id"], jane["id"], [("a-copy.pdf", shared)]).json()
    assert again["accepted"] == []

    other = upload(coordinator, category["id"], mary["id"], [("a.pdf", shared)]).json()
    assert len(other["accepted"]) == 1


def test_idempotent_retry_does_not_duplicate(coordinator: TestClient) -> None:
    category = make_category(coordinator)
    candidate = make_candidate(coordinator, category["id"])
    key = uuid.uuid4().hex
    first = upload(coordinator, category["id"], candidate["id"], [("n.pdf", pdf())], key=key)
    retry = upload(coordinator, category["id"], candidate["id"], [("n.pdf", pdf())], key=key)

    assert first.status_code == 202
    assert retry.status_code == 200
    assert retry.json()["replayed"] is True
    assert retry.json()["import_id"] == first.json()["import_id"]
    assert len(coordinator.get(documents_url(category["id"], candidate["id"])).json()) == 1


def test_withdrawn_documents_leave_the_knowledge_base(coordinator: TestClient) -> None:
    category = make_category(coordinator)
    candidate = make_candidate(coordinator, category["id"])
    data = pdf()
    doc = upload(coordinator, category["id"], candidate["id"], [("wrong.pdf", data)]).json()
    doc_id = doc["accepted"][0]["id"]

    response = coordinator.post(
        f"/api/v1/documents/{doc_id}/withdraw", json={"reason": "Belongs to another nominee"}
    )
    assert response.status_code == 200
    assert response.json()["withdrawn_at"]

    url = documents_url(category["id"], candidate["id"])
    assert coordinator.get(url).json() == []
    assert len(coordinator.get(url, params={"include_withdrawn": True}).json()) == 1
    again = coordinator.post(f"/api/v1/documents/{doc_id}/withdraw", json={"reason": "again"})
    assert again.status_code == 409

    # The same file may be uploaded again once the earlier copy is withdrawn.
    reupload = upload(coordinator, category["id"], candidate["id"], [("right.pdf", data)])
    assert len(reupload.json()["accepted"]) == 1


def test_candidate_must_belong_to_category(coordinator: TestClient) -> None:
    category_a = make_category(coordinator)
    category_b = make_category(coordinator)
    candidate = make_candidate(coordinator, category_b["id"])
    response = upload(coordinator, category_a["id"], candidate["id"], [("n.pdf", pdf())])
    assert response.status_code == 404


def test_only_coordinators_can_change_the_knowledge_base(
    coordinator: TestClient, client_for: ClientFactory
) -> None:
    category = make_category(coordinator)
    candidate = make_candidate(coordinator, category["id"])
    judge = client_for("judge")

    assert judge.get(f"/api/v1/categories/{category['id']}/finalists").status_code == 200
    assert upload(judge, category["id"], candidate["id"], [("n.pdf", pdf())]).status_code == 403
    assert judge.post("/api/v1/categories", json={"code": "x", "name": "X"}).status_code == 403


def test_uploads_are_audited(coordinator: TestClient, engine: Engine) -> None:
    category = make_category(coordinator)
    candidate = make_candidate(coordinator, category["id"])
    body = upload(coordinator, category["id"], candidate["id"], [("n.pdf", pdf())]).json()
    with engine.connect() as conn:
        details = conn.execute(
            text(
                "SELECT details FROM audit_events WHERE action = 'documents.uploaded' "
                "AND entity_id = :fc"
            ),
            {"fc": candidate["finalist_category_id"]},
        ).scalar_one()
    assert details["import_id"] == body["import_id"]
    assert details["accepted"] == [body["accepted"][0]["id"]]
