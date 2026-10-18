"""Reviewer verification of claims (FR-07, spec §6)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.services.claims.schema import ClaimExtractionOutput, Contradiction, EvidenceQuote
from tests import fixture_files
from tests.conftest import drain
from tests.test_claims import claim, claims_pipeline, passages_in
from tests.test_knowledge_base import make_candidate, make_category, upload

CV = {
    "Board roles": ["Jane Doe has chaired the audit committee of Example Holdings since 2019."],
    "Mentoring": ["Jane mentors twelve women preparing for first board appointments."],
    "History": ["She joined the Example Holdings board in March 2018."],
}
LETTER = {
    "Reference": [
        "As chair of the audit committee since 2019, Jane Doe led reforms.",
        "She was appointed to the board in March 2019.",
    ]
}

AUDIT = "Jane Doe has chaired the audit committee of Example Holdings since 2019."
MENTOR = "Jane Doe mentors twelve women preparing for board appointments."
JOINED = "Jane Doe joined the Example Holdings board in March 2018."


def respond(system: str, user: str) -> ClaimExtractionOutput:
    p = passages_in(user)
    cv = next(pid for pid, body in p.items() if "mentors twelve" in body)
    letter = next(pid for pid, body in p.items() if "As chair" in body)
    return ClaimExtractionOutput(
        claims=[
            claim(
                AUDIT,
                [
                    (cv, "chaired the audit committee of Example Holdings since 2019"),
                    (letter, "chair of the audit committee since 2019"),
                ],
            ),
            claim(MENTOR, [(cv, "mentors twelve women")], claim_type="advocacy"),
            claim(
                JOINED,
                [(cv, "joined the Example Holdings board in March 2018")],
                contradicting=[(letter, "appointed to the board in March 2019")],
            ),
        ],
        contradictions=[
            Contradiction(
                description="Board appointment: March 2018 (CV) vs March 2019 (letter).",
                evidence=[
                    EvidenceQuote(passage_id=cv, quote="March 2018"),
                    EvidenceQuote(passage_id=letter, quote="March 2019"),
                ],
            )
        ],
        missing_information=[],
    )


@pytest.fixture(autouse=True)
def _empty_queues(empty_queue: None, engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE claim_extraction_runs SET status = 'cancelled' "
                "WHERE status IN ('queued', 'running', 'failed')"
            )
        )


@pytest.fixture
def world(coordinator: TestClient, make_pipeline, engine: Engine) -> dict:
    category = make_category(coordinator)
    jane = make_candidate(coordinator, category["id"], "Jane Doe")
    body = upload(
        coordinator,
        category["id"],
        jane["id"],
        [
            ("cv.docx", fixture_files.docx_from(CV)),
            ("letter.docx", fixture_files.docx_from(LETTER)),
        ],
    ).json()
    drain(make_pipeline())
    base = f"/api/v1/categories/{category['id']}/finalists/{jane['id']}/claims"
    world = {
        "category": category,
        "jane": jane,
        "base": base,
        "engine": engine,
        "documents": {d["filename"]: d["id"] for d in body["accepted"]},
    }
    extract(coordinator, world)
    return world


def extract(client: TestClient, world: dict) -> dict:
    assert client.post(f"{world['base']}/extract").status_code == 202
    claims_pipeline(world["engine"], respond)[0].run_once()
    return client.get(world["base"]).json()


def claims_by_statement(client: TestClient, world: dict) -> dict:
    return {c["statement"]: c for c in client.get(world["base"]).json()["claims"]}


def review(client: TestClient, claim: dict, decision: str, **extra):
    return client.post(
        f"/api/v1/claims/{claim['id']}/reviews",
        json={"decision": decision, "expected_status": claim["status"], **extra},
    )


def test_reviewer_verifies_a_claim(client_for, world, engine: Engine) -> None:
    reviewer = client_for("reviewer")
    mentor = claims_by_statement(reviewer, world)[MENTOR]
    response = review(reviewer, mentor, "verified", sufficiency="sufficient", credibility="high")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "verified"
    assert body["latest_review"]["decision"] == "verified"
    assert body["latest_review"]["previous_status"] == "unverified"
    assert body["latest_review"]["sufficiency"] == "sufficient"
    assert body["latest_review"]["reviewer_role"] == "reviewer"
    assert body["review_count"] == 1

    summary = reviewer.get(world["base"]).json()["verification"]
    assert summary["total"] == 3 and summary["reviewed"] == 1
    assert summary["by_status"]["verified"] == 1
    assert summary["by_status"]["disputed"] == 1  # the contradicted claim
    with engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM audit_events WHERE action = 'claim.reviewed' "
                    "AND entity_id = :id"
                ),
                {"id": mentor["id"]},
            ).scalar_one()
            == 1
        )


@pytest.mark.parametrize("decision", ["disputed", "missing", "unverified", "corroborated"])
def test_notes_are_required_except_for_verified(client_for, world, decision) -> None:
    reviewer = client_for("reviewer")
    audit = claims_by_statement(reviewer, world)[AUDIT]
    response = review(reviewer, audit, decision, notes="   ")
    assert response.status_code == 422
    assert "notes are required" in response.json()["detail"]


def test_corroboration_needs_two_documents(client_for, world) -> None:
    reviewer = client_for("reviewer")
    claims = claims_by_statement(reviewer, world)
    assert claims[AUDIT]["supporting_documents"] == 2
    ok = review(
        reviewer, claims[AUDIT], "corroborated", notes="CV and the board secretary's letter agree."
    )
    assert ok.status_code == 201
    single = review(reviewer, claims[MENTOR], "corroborated", notes="Looks right.")
    assert single.status_code == 422
    assert "at least two independent sources" in single.json()["detail"]


def test_stale_status_is_rejected(client_for, world) -> None:
    first, second = client_for("reviewer"), client_for("reviewer")
    mentor = claims_by_statement(first, world)[MENTOR]
    assert review(first, mentor, "verified").status_code == 201
    # The second reviewer still sees "unverified".
    late = review(second, mentor, "disputed", notes="Can't find it.")
    assert late.status_code == 409
    assert "now verified" in late.json()["detail"]


def test_disputed_claim_can_be_resolved_and_history_kept(client_for, world) -> None:
    reviewer = client_for("reviewer")
    joined = claims_by_statement(reviewer, world)[JOINED]
    assert joined["status"] == "disputed"
    review(reviewer, joined, "verified", notes="Companies registry shows March 2018.")
    history = reviewer.get(f"/api/v1/claims/{joined['id']}/reviews").json()
    assert [h["decision"] for h in history] == ["verified"]
    assert history[0]["previous_status"] == "disputed"


def test_withdrawn_evidence_cannot_be_verified(client_for, coordinator, world) -> None:
    reviewer = client_for("reviewer")
    for doc in world["documents"].values():
        coordinator.post(f"/api/v1/documents/{doc}/withdraw", json={"reason": "Wrong person"})
    mentor = claims_by_statement(reviewer, world)[MENTOR]
    response = review(reviewer, mentor, "verified")
    assert response.status_code == 409
    assert mentor["evidence"][0]["document_withdrawn"] is True


def test_only_reviewers_and_coordinators_can_review(client_for, coordinator, world) -> None:
    judge = client_for("judge")
    mentor = claims_by_statement(judge, world)[MENTOR]
    assert review(judge, mentor, "verified").status_code == 403
    assert review(client_for("committee"), mentor, "verified").status_code == 403
    assert review(coordinator, mentor, "verified").status_code == 201

    me = judge.get("/api/v1/me").json()
    assert me["role"] == "judge"
    assert me["permissions"] == {
        "manage_evidence": False,
        "review_claims": False,
        "approve_rubrics": False,
        "generate_reports": False,
        "manage_users": False,
    }
    assert coordinator.get("/api/v1/me").json()["permissions"]["review_claims"] is True


def test_superseded_claims_cannot_be_reviewed(client_for, coordinator, world) -> None:
    reviewer = client_for("reviewer")
    old = claims_by_statement(reviewer, world)[MENTOR]
    extract(coordinator, world)
    response = review(reviewer, old, "verified")
    assert response.status_code == 409
    assert "replaced by a later extraction" in response.json()["detail"]


def test_reviews_carry_forward_to_identical_claims(client_for, coordinator, world) -> None:
    reviewer = client_for("reviewer")
    claims = claims_by_statement(reviewer, world)
    review(reviewer, claims[MENTOR], "verified", notes="Matches the programme list.")
    review(reviewer, claims[AUDIT], "corroborated", notes="Two independent sources.")
    review(reviewer, claims[JOINED], "verified", notes="Registry confirms 2018.")

    body = extract(coordinator, world)
    assert body["latest_run"]["claims_carried_forward"] == 2
    after = {c["statement"]: c for c in body["claims"]}
    assert after[MENTOR]["id"] != claims[MENTOR]["id"]
    assert after[MENTOR]["status"] == "verified"
    assert after[MENTOR]["latest_review"]["carried_forward"] is True
    assert "Matches the programme list." in after[MENTOR]["latest_review"]["notes"]
    assert after[AUDIT]["status"] == "corroborated"
    # Still contradicted in the new extraction, so a reviewer must look again.
    assert after[JOINED]["status"] == "disputed"
    assert after[JOINED]["latest_review"] is None


def test_contradictions_are_resolved_manually(client_for, world) -> None:
    reviewer = client_for("reviewer")
    body = reviewer.get(world["base"]).json()
    run = body["latest_run"]
    assert body["verification"]["unresolved_contradictions"] == 1
    url = f"/api/v1/claim-extraction-runs/{run['id']}/contradictions"
    assert reviewer.post(f"{url}/5/resolutions", json={"resolution": "n/a"}).status_code == 404
    response = reviewer.post(
        f"{url}/0/resolutions", json={"resolution": "Registry shows March 2018; letter is wrong."}
    )
    assert response.status_code == 201
    assert response.json()["contradiction_resolutions"]["0"]["resolution"].startswith("Registry")
    assert reviewer.get(world["base"]).json()["verification"]["unresolved_contradictions"] == 0
    assert (
        client_for("judge").post(f"{url}/0/resolutions", json={"resolution": "nope"}).status_code
        == 403
    )


def test_finalist_list_shows_review_progress(client_for, world) -> None:
    reviewer = client_for("reviewer")
    review(reviewer, claims_by_statement(reviewer, world)[MENTOR], "verified")
    finalists = reviewer.get(f"/api/v1/categories/{world['category']['id']}/finalists").json()
    assert (finalists[0]["claims_total"], finalists[0]["claims_reviewed"]) == (3, 1)


def test_review_history_is_append_only(client_for, world, engine: Engine) -> None:
    reviewer = client_for("reviewer")
    review(reviewer, claims_by_statement(reviewer, world)[MENTOR], "verified")
    with engine.connect() as conn, pytest.raises(DBAPIError, match="append-only"):
        conn.execute(text("UPDATE verification_reviews SET notes = 'edited'"))
