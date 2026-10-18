"""Deliberation reports (FR-11, spec §11): PDFs generated from ranking snapshots."""

import hashlib
import io

import pdfplumber
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests import test_assessment
from tests.test_assessment import assess, items_for
from tests.test_knowledge_base import make_candidate

# Shared fixtures from the assessment tests.
world = test_assessment.world
_empty_queues = test_assessment._empty_queues


def pdf_text(content: bytes) -> str:
    """Page text with whitespace normalised, since PDF line wrapping splits phrases."""
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return " ".join(" ".join(page.extract_text() or "" for page in pdf.pages).split())


@pytest.fixture
def ranked(client_for, coordinator: TestClient, world, engine: Engine) -> dict:
    """Jane fully approved; Mary with one adjusted and one rejected rating; then ranked."""
    assess(coordinator, world, engine)
    reviewer = client_for("reviewer")
    for item in items_for(reviewer, world, "Jane Doe").values():
        reviewer.post(
            f"/api/v1/criterion-assessments/{item['id']}/review", json={"decision": "approved"}
        )
    mary = items_for(reviewer, world, "Mary Major")
    reviewer.post(
        f"/api/v1/criterion-assessments/{mary['governance-leadership']['id']}/review",
        json={
            "decision": "approved",
            "adjusted_rating": 2,
            "notes": "Committee role is described but not evidenced.",
        },
    )
    reviewer.post(
        f"/api/v1/criterion-assessments/{mary['measurable-impact']['id']}/review",
        json={"decision": "rejected", "notes": "Loss figure lacks a source."},
    )
    ranking = coordinator.post(
        "/api/v1/rankings", json={"category_id": world["category"]["id"]}
    ).json()
    return {**world, "ranking": ranking, "reviewer": reviewer, "mary_items": mary}


def generate(client: TestClient, world: dict, kind: str, name: str | None = None):
    body = {"kind": kind, "category_id": world["category"]["id"]}
    if name:
        body["finalist_id"] = world["people"][name]["id"]
    return client.post("/api/v1/reports", json=body)


def download(client: TestClient, report: dict) -> bytes:
    response = client.get(f"/api/v1/reports/{report['id']}/download")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    return response.content


def test_category_report(coordinator, ranked) -> None:
    response = generate(coordinator, ranked, "category")
    assert response.status_code == 201, response.text
    report = response.json()
    assert report["status"] == "succeeded" and report["snapshot_id"] == ranked["ranking"]["id"]
    assert report["generator_version"] == "report-v1"

    content = download(coordinator, report)
    assert content.startswith(b"%PDF")
    assert hashlib.sha256(content).hexdigest() == report["sha256_hash"]
    assert len(content) == report["size_bytes"]

    text_ = pdf_text(content)
    for expected in (
        "Category comparison report",
        "PRACTICE ONLY",
        "AI rankings are advisory. The awards committee retains responsibility",
        "Jane Doe",
        "Mary Major",
        "Board leadership and governance",
        "Criteria driving the differences",
        "Unresolved verification",
        "Questions for judges",
        "could not be scored",  # Mary has a rejected rating
        "The rubric is not frozen",
        "Provenance",
        "fake:scripted",
        "Confidential: judging committee use only",
    ):
        assert expected in text_, expected


def test_individual_report(coordinator, ranked) -> None:
    jane = generate(coordinator, ranked, "individual", "Jane Doe").json()
    assert jane["finalist_name"] == "Jane Doe"
    text_ = pdf_text(download(coordinator, jane))
    for expected in (
        "Individual deliberation report",
        "1 of 2",
        "3.20",
        "64.00",
        "Key strengths",
        "Advancing women in leadership (4/5)",
        "mentors twelve women",  # a verified citation quote
        "Assessment detail",
        "Evidence documents",
        "evidence.docx",
        "none extracted",
    ):
        assert expected in text_, expected

    mary = pdf_text(
        download(coordinator, generate(coordinator, ranked, "individual", "Mary Major").json())
    )
    assert "not ranked (incomplete)" in mary
    assert "A reviewer adjusted Board leadership and governance from 3 to 2" in mary
    assert "Should the nominee be re-assessed" in mary
    assert "rating(s) have not had human quality review" in mary


def test_reviews_after_the_snapshot_are_pointed_out(coordinator, ranked) -> None:
    item = ranked["mary_items"]["integrity-stewardship"]
    ranked["reviewer"].post(
        f"/api/v1/criterion-assessments/{item['id']}/review",
        json={
            "decision": "approved",
            "adjusted_rating": 1,
            "notes": "Nothing on ethics in the evidence.",
        },
    )
    mary = pdf_text(
        download(coordinator, generate(coordinator, ranked, "individual", "Mary Major").json())
    )
    assert "Reviewed after this ranking was calculated: current rating 1" in mary
    assert "Should the ranking be recalculated?" in mary


def test_production_reports_have_no_practice_marking(client_for, coordinator, ranked) -> None:
    committee = client_for("committee")
    rubric_id = ranked["rubric"]["id"]
    committee.post(f"/api/v1/rubrics/{rubric_id}/approve")
    committee.post(f"/api/v1/rubrics/{rubric_id}/freeze")
    coordinator.post("/api/v1/rankings", json={"category_id": ranked["category"]["id"]})
    text_ = pdf_text(download(committee, generate(committee, ranked, "category").json()))
    assert "Provisional ranking on the committee's frozen rubric" in text_
    assert "PRACTICE" not in text_


def test_permissions_and_audit(client_for, coordinator, ranked, engine: Engine) -> None:
    judge = client_for("judge")
    assert generate(judge, ranked, "category").status_code == 403
    assert generate(client_for("reviewer"), ranked, "category").status_code == 403
    report = generate(coordinator, ranked, "category").json()
    download(judge, report)  # judges can read reports
    listed = judge.get(f"/api/v1/categories/{ranked['category']['id']}/reports").json()
    assert report["id"] in {r["id"] for r in listed}
    with engine.connect() as conn:
        actions = (
            conn.execute(
                text("SELECT action FROM audit_events WHERE entity_id = :id ORDER BY id"),
                {"id": report["id"]},
            )
            .scalars()
            .all()
        )
    assert actions == ["report.generated", "report.downloaded"]


def test_report_preconditions(coordinator, world, ranked) -> None:
    other = coordinator.post(
        "/api/v1/categories", json={"code": "no-ranking-yet", "name": "No ranking"}
    ).json()
    response = coordinator.post(
        "/api/v1/reports", json={"kind": "category", "category_id": other["id"]}
    )
    assert response.status_code == 409
    no_finalist = coordinator.post(
        "/api/v1/reports", json={"kind": "individual", "category_id": ranked["category"]["id"]}
    )
    assert no_finalist.status_code == 422
    late = make_candidate(coordinator, ranked["category"]["id"], "Late Entrant")
    response = coordinator.post(
        "/api/v1/reports",
        json={
            "kind": "individual",
            "category_id": ranked["category"]["id"],
            "finalist_id": late["id"],
        },
    )
    assert response.status_code == 404
