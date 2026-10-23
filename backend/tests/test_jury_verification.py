"""Jury decision (23 Oct 2026): supporting documents are a credible source of truth, so claims
they support are verified automatically."""

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app import cli
from tests import fixture_files, test_verification
from tests.conftest import drain
from tests.test_claims import claims_pipeline
from tests.test_knowledge_base import make_candidate, make_category, upload
from tests.test_verification import (
    AUDIT,
    CV,
    JOINED,
    LETTER,
    MENTOR,
    claims_by_statement,
    respond,
    review,
)

_empty_queues = test_verification._empty_queues


def candidate(coordinator: TestClient, make_pipeline, engine: Engine, cv_type: str) -> dict:
    """Jane with her CV (as cv_type) and a nomination letter."""
    category = make_category(coordinator)
    jane = make_candidate(coordinator, category["id"], "Jane Doe")
    upload(
        coordinator,
        category["id"],
        jane["id"],
        [("cv.docx", fixture_files.docx_from(CV))],
        source_type=cv_type,
    )
    upload(
        coordinator,
        category["id"],
        jane["id"],
        [("letter.docx", fixture_files.docx_from(LETTER))],
        source_type="nomination_form",
    )
    drain(make_pipeline())
    base = f"/api/v1/categories/{category['id']}/finalists/{jane['id']}/claims"
    return {"base": base, "engine": engine}


def extract(coordinator: TestClient, world: dict, jury: bool) -> None:
    assert coordinator.post(f"{world['base']}/extract").status_code == 202
    pipeline, _ = claims_pipeline(world["engine"], respond, jury_verifies_supporting_documents=jury)
    pipeline.run_once()


def test_claims_a_supporting_document_backs_are_verified(
    client_for, coordinator, make_pipeline, engine
) -> None:
    world = candidate(coordinator, make_pipeline, engine, "supporting_document")
    extract(coordinator, world, jury=True)
    claims = claims_by_statement(coordinator, world)

    for statement in (AUDIT, MENTOR):
        assert claims[statement]["status"] == "verified"
        latest = claims[statement]["latest_review"]
        assert (latest["reviewer"], latest["reviewer_role"]) == ("Jury decision", "automatic")
        assert "jury decided" in latest["notes"]
    # Contradicted by the letter: disputed at extraction, left for a reviewer.
    assert claims[JOINED]["status"] == "disputed" and claims[JOINED]["latest_review"] is None

    # A reviewer can still change an automatic decision.
    reviewer = client_for("reviewer")
    changed = review(reviewer, claims[MENTOR], "disputed", notes="Mentoring ended in 2024.")
    assert changed.status_code == 201, changed.text

    # Re-extraction keeps the decisions on identical claims.
    extract(coordinator, world, jury=True)
    claims = claims_by_statement(coordinator, world)
    assert claims[AUDIT]["status"] == "verified"
    assert claims[AUDIT]["latest_review"]["carried_forward"] is True
    assert claims[MENTOR]["status"] == "disputed"


def test_nomination_forms_alone_dont_verify(coordinator, make_pipeline, engine) -> None:
    world = candidate(coordinator, make_pipeline, engine, "nomination_form")
    extract(coordinator, world, jury=True)
    claims = claims_by_statement(coordinator, world)
    assert {claims[s]["status"] for s in (AUDIT, MENTOR)} == {"unverified"}


def test_earlier_claims_are_verified_by_the_command(
    coordinator, make_pipeline, engine, monkeypatch, capsys
) -> None:
    world = candidate(coordinator, make_pipeline, engine, "supporting_document")
    extract(coordinator, world, jury=False)
    assert claims_by_statement(coordinator, world)[AUDIT]["status"] == "unverified"

    monkeypatch.setattr("app.cli.get_engine", lambda: engine)
    cli.verify_supporting_claims()
    assert "Verified" in capsys.readouterr().out
    claims = claims_by_statement(coordinator, world)
    assert claims[AUDIT]["status"] == claims[MENTOR]["status"] == "verified"
    cli.verify_supporting_claims()  # nothing left: already decided
    assert claims_by_statement(coordinator, world)[AUDIT]["review_count"] == 1
