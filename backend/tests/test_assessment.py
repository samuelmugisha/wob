"""Rubrics, criterion assessment (FR-08), quality review and provisional ranking (FR-09)."""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.services.assessment.schema import Citation, CriterionRating
from app.services.claims.llm import ExtractionLLMError
from app.services.embeddings import HashingEmbedder
from app.services.reranking import OverlapReranker
from app.services.retrieval import Retriever
from app.workers.assessment import AssessmentPipeline, ScriptedAssessor
from tests import fixture_files
from tests.conftest import drain
from tests.test_knowledge_base import make_candidate, make_category, upload

JANE = {
    "Board roles": ["Jane Doe has chaired the audit committee of Example Holdings since 2019."],
    "Mentoring": ["Jane mentors twelve women preparing for first board appointments."],
}
MARY = {
    "Board roles": ["Mary Major chairs the risk committee of Zanzibar Shipping Limited."],
    "Impact": ["Under her oversight the company cut losses by 40 percent in 2023."],
}
PASSAGE = re.compile(r'<passage id="(P\d+)" source="[^"]*">\n(.*?)\n</passage>', re.S)
CRITERION = re.compile(r"<criterion>\nName: (.+)\n")


def scripted(system: str, user: str) -> CriterionRating:
    """Cites the first passage with a real quote; mentoring gets 4, others 3."""
    passages = dict(PASSAGE.findall(user))
    criterion = CRITERION.search(user).group(1)
    if not passages:
        return CriterionRating(
            rating=1,
            rationale="No evidence.",
            supporting=[],
            contradicting=[],
            limitations=None,
            sufficiency="insufficient",
            review_required=True,
            review_reasons=["no evidence"],
        )
    pid, body = next(iter(passages.items()))
    sentence = body.split("\n\n")[-1][:60]
    rating = 4 if "Advancing women" in criterion else 3
    return CriterionRating(
        rating=rating,
        rationale=f"The evidence shows: {sentence}",
        supporting=[Citation(ref=pid, quote=sentence), Citation(ref="P99", quote="invented")],
        contradicting=[],
        limitations=None,
        sufficiency="limited",
        review_required=False,
        review_reasons=[],
    )


@pytest.fixture(autouse=True)
def _empty_queues(empty_queue: None, engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE assessment_runs SET status = 'cancelled' "
                "WHERE status IN ('queued', 'running', 'failed')"
            )
        )


@pytest.fixture
def world(coordinator: TestClient, make_pipeline) -> dict:
    category = make_category(coordinator)
    people = {}
    for name, sections in (("Jane Doe", JANE), ("Mary Major", MARY)):
        person = make_candidate(coordinator, category["id"], name)
        upload(
            coordinator,
            category["id"],
            person["id"],
            [("evidence.docx", fixture_files.docx_from(sections))],
        )
        people[name] = person
    drain(make_pipeline())
    response = coordinator.post(
        f"/api/v1/categories/{category['id']}/rubrics", json={"use_template": True}
    )
    assert response.status_code == 201, response.text
    return {"category": category, "people": people, "rubric": response.json()}


def assessment_pipeline(engine: Engine, respond=scripted):
    settings = get_settings().model_copy(update={"retrieval_top_k": 5})
    retriever = Retriever(HashingEmbedder(settings.embedding_dim), OverlapReranker(), settings)
    assessor = ScriptedAssessor(respond)
    pipeline = AssessmentPipeline(
        sessionmaker(engine, expire_on_commit=False), assessor, retriever, settings
    )
    return pipeline, assessor


def assess(coordinator: TestClient, world: dict, engine: Engine, respond=scripted):
    response = coordinator.post(
        "/api/v1/assessments", json={"category_id": world["category"]["id"]}
    )
    assert response.status_code == 202, response.text
    pipeline, assessor = assessment_pipeline(engine, respond)
    pipeline.run_once()
    return response.json(), assessor


def items_for(client: TestClient, world: dict, name: str) -> dict[str, dict]:
    person = world["people"][name]
    body = client.get(
        f"/api/v1/categories/{world['category']['id']}/finalists/{person['id']}/assessments"
    ).json()
    return {i["criterion_code"]: i for i in body["items"]}


def test_template_rubric_is_a_labelled_draft(world) -> None:
    rubric = world["rubric"]
    assert rubric["status"] == "draft" and rubric["version"] == 1
    assert rubric["notes"].startswith("DRAFT TEMPLATE")
    assert [c["code"] for c in rubric["criteria"]][:2] == [
        "governance-leadership",
        "measurable-impact",
    ]


def test_rubric_lifecycle_and_permissions(client_for, coordinator, world) -> None:
    rubric_id = world["rubric"]["id"]
    criteria = [
        {"code": "impact", "name": "Impact", "description": "Results", "weight": 2},
        {"code": "mentoring", "name": "Mentoring", "description": "Mentoring"},
    ]
    updated = coordinator.put(
        f"/api/v1/rubrics/{rubric_id}", json={"criteria": criteria, "weighting": "weighted"}
    )
    assert updated.status_code == 200 and len(updated.json()["criteria"]) == 2

    committee = client_for("committee")
    assert coordinator.post(f"/api/v1/rubrics/{rubric_id}/approve").status_code == 403
    missing_weight = committee.post(f"/api/v1/rubrics/{rubric_id}/approve")
    assert missing_weight.status_code == 422
    criteria[1]["weight"] = 1
    coordinator.put(
        f"/api/v1/rubrics/{rubric_id}", json={"criteria": criteria, "weighting": "weighted"}
    )
    assert committee.post(f"/api/v1/rubrics/{rubric_id}/freeze").status_code == 409
    assert committee.post(f"/api/v1/rubrics/{rubric_id}/approve").json()["status"] == "approved"
    # Approved: only an administrator may amend it.
    assert (
        coordinator.put(f"/api/v1/rubrics/{rubric_id}", json={"criteria": criteria}).status_code
        == 403
    )
    frozen = committee.post(f"/api/v1/rubrics/{rubric_id}/freeze").json()
    assert frozen["status"] == "frozen" and frozen["frozen_at"]

    second = coordinator.post(
        f"/api/v1/categories/{world['category']['id']}/rubrics", json={"use_template": True}
    ).json()
    assert second["version"] == 2
    # Assessments use the latest frozen rubric, not a newer draft.
    rankings = coordinator.get(f"/api/v1/categories/{world['category']['id']}/rankings").json()
    assert rankings["rubric"]["id"] == rubric_id


def _approve_and_freeze(client_for, world) -> tuple[str, TestClient]:
    rubric_id = world["rubric"]["id"]
    committee = client_for("committee")
    assert committee.post(f"/api/v1/rubrics/{rubric_id}/approve").status_code == 200
    assert committee.post(f"/api/v1/rubrics/{rubric_id}/freeze").status_code == 200
    return rubric_id, committee


def test_only_an_admin_unfreezes_and_amends_a_rubric(client_for, coordinator, world, engine):
    rubric_id, committee = _approve_and_freeze(client_for, world)
    admin = client_for("admin")
    url = f"/api/v1/rubrics/{rubric_id}"
    criteria = [
        {k: c[k] for k in ("code", "name", "description", "evidence_expectations")}
        for c in world["rubric"]["criteria"]
    ]
    criteria[0]["name"] = "Board leadership"

    assert admin.put(url, json={"criteria": criteria}).status_code == 409  # unfreeze first
    for client in (coordinator, committee):
        assert client.post(f"{url}/unfreeze", json={"reason": "typo"}).status_code == 403
    assert admin.post(f"{url}/unfreeze", json={"reason": " "}).status_code == 422
    unfrozen = admin.post(f"{url}/unfreeze", json={"reason": "Fix a criterion name."})
    assert unfrozen.status_code == 200, unfrozen.text
    assert unfrozen.json()["status"] == "approved" and unfrozen.json()["frozen_at"] is None

    # Approved: only an administrator may amend it, and it stays approved.
    assert coordinator.put(url, json={"criteria": criteria}).status_code == 403
    assert committee.put(url, json={"criteria": criteria}).status_code == 403
    amended = admin.put(url, json={"criteria": criteria})
    assert amended.status_code == 200, amended.text
    body = amended.json()
    assert body["status"] == "approved"
    assert body["criteria"][0]["name"] == "Board leadership"
    assert [c["id"] for c in body["criteria"]] == [c["id"] for c in world["rubric"]["criteria"]]

    with engine.connect() as conn:
        actions = list(
            conn.scalars(
                text("SELECT action FROM audit_events WHERE entity_id = :r ORDER BY occurred_at"),
                {"r": rubric_id},
            )
        )
    assert actions[-2:] == ["rubric.unfrozen", "rubric.amended"]
    assert committee.post(f"{url}/freeze").json()["status"] == "frozen"


def test_amending_keeps_ratings_and_refuses_to_drop_rated_criteria(
    client_for, coordinator, world, engine
) -> None:
    assess(coordinator, world, engine)
    before = items_for(coordinator, world, "Jane Doe")
    rubric_id, _ = _approve_and_freeze(client_for, world)
    admin = client_for("admin")
    url = f"/api/v1/rubrics/{rubric_id}"
    admin.post(f"{url}/unfreeze", json={"reason": "Clarify wording."})
    criteria = [
        {k: c[k] for k in ("code", "name", "description", "evidence_expectations")}
        for c in world["rubric"]["criteria"]
    ]

    dropped = admin.put(url, json={"criteria": criteria[1:]})
    assert dropped.status_code == 409 and "already rated" in dropped.json()["detail"]

    criteria.reverse()
    criteria[0]["description"] = "Reworded."
    assert admin.put(url, json={"criteria": criteria}).status_code == 200
    after = items_for(coordinator, world, "Jane Doe")
    assert {k: v["rating"] for k, v in after.items()} == {k: v["rating"] for k, v in before.items()}


def test_each_pair_is_assessed_independently_with_verified_citations(
    coordinator, world, engine
) -> None:
    run, assessor = assess(coordinator, world, engine)
    status = coordinator.get(f"/api/v1/assessments/{run['id']}").json()
    assert status["status"] == "succeeded"
    assert (status["items_done"], status["items_total"]) == (10, 10)
    assert status["embedding_model"] == "fake:hashing"
    assert status["retrieval_config"]["top_k"] == 5
    assert status["rubric_status"] == "draft"

    assert len(assessor.calls) == 10
    for _, user in assessor.calls:  # each request sees one nominee's evidence only
        assert ("Jane Doe" in user) != ("Mary Major" in user)
        if "Nominee: Jane Doe" in user:
            assert "Zanzibar" not in user

    items = items_for(coordinator, world, "Jane Doe")
    assert len(items) == 5
    mentoring = items["advancing-women"]
    assert mentoring["rating"] == 4 and mentoring["status"] == "proposed"
    assert mentoring["citations"][0]["filename"] == "evidence.docx"
    assert mentoring["discarded_citations"][0]["reason"] == "unknown reference 'P99'"
    assert "citations_discarded" in mentoring["flags"]
    assert "rubric_not_frozen" in mentoring["flags"]
    assert mentoring["review_required"] is True


def test_quality_review_rules(client_for, coordinator, world, engine) -> None:
    def uncited(system, user):
        rating = scripted(system, user)
        return rating.model_copy(update={"supporting": [Citation(ref="P1", quote="not there")]})

    assess(coordinator, world, engine, uncited)
    reviewer = client_for("reviewer")
    item = items_for(reviewer, world, "Jane Doe")["advancing-women"]
    assert "uncited_rating" in item["flags"]
    url = f"/api/v1/criterion-assessments/{item['id']}/review"

    refused = reviewer.post(url, json={"decision": "approved"})
    assert refused.status_code == 422 and "verified supporting citation" in refused.json()["detail"]
    assert reviewer.post(url, json={"decision": "rejected"}).status_code == 422  # needs notes
    assert (
        reviewer.post(url, json={"decision": "approved", "adjusted_rating": 1}).status_code == 422
    )  # needs reason
    adjusted = reviewer.post(
        url,
        json={
            "decision": "approved",
            "adjusted_rating": 1,
            "notes": "No verifiable evidence for this criterion.",
        },
    )
    assert adjusted.status_code == 200
    body = adjusted.json()
    assert (body["rating"], body["reviewer_rating"], body["effective_rating"]) == (4, 1, 1)
    assert body["status"] == "approved" and body["reviewed_by"] == "Test"
    assert client_for("judge").post(url, json={"decision": "approved"}).status_code == 403


def test_ranking_from_reviewed_assessments(client_for, coordinator, world, engine) -> None:
    run, _ = assess(coordinator, world, engine)
    category_id = world["category"]["id"]
    reviewer = client_for("reviewer")

    # Approve all of Jane's; reject one of Mary's so her score is incomplete.
    for item in items_for(reviewer, world, "Jane Doe").values():
        reviewer.post(
            f"/api/v1/criterion-assessments/{item['id']}/review", json={"decision": "approved"}
        )
    mary_items = items_for(reviewer, world, "Mary Major")
    reviewer.post(
        f"/api/v1/criterion-assessments/{mary_items['measurable-impact']['id']}/review",
        json={"decision": "rejected", "notes": "Loss figure lacks a source."},
    )

    assert (
        client_for("judge").post("/api/v1/rankings", json={"category_id": category_id}).status_code
        == 403
    )
    response = coordinator.post("/api/v1/rankings", json={"category_id": category_id})
    assert response.status_code == 201, response.text
    ranking = response.json()
    assert ranking["production"] is False and ranking["rubric_status"] == "draft"
    assert ranking["is_provisional"] and "AI rankings are advisory" in ranking["disclaimer"]

    jane, mary = ranking["entries"]
    assert jane["full_name"] == "Jane Doe"
    # Four criteria at 3 and mentoring at 4: (3×4 + 4) / 5 = 3.2
    assert (jane["score"], jane["score_display"], jane["points_display"]) == (
        "3.2",
        "3.20",
        "64.00",
    )
    assert jane["rank"] == 1 and jane["unreviewed_criteria"] == []
    assert jane["ratings"]["advancing-women"] == 4
    assert mary["score"] is None and mary["rank"] is None
    assert mary["missing_criteria"] == ["measurable-impact"]
    assert len(mary["unreviewed_criteria"]) == 4

    latest = coordinator.get(f"/api/v1/categories/{category_id}/rankings").json()
    assert latest["ranking"]["id"] == ranking["id"]
    assert latest["latest_run"]["id"] == run["id"]


def test_ties_and_close_results(coordinator, world, engine) -> None:
    assess(coordinator, world, engine)
    ranking = coordinator.post(
        "/api/v1/rankings", json={"category_id": world["category"]["id"]}
    ).json()
    jane, mary = ranking["entries"]
    assert jane["score"] == mary["score"] == "3.2"
    assert jane["rank"] == mary["rank"] == 1 and jane["is_tie"] and mary["is_tie"]
    assert ranking["close_results"] == [
        {"higher": "Jane Doe", "lower": "Mary Major", "difference": "0.00"}
    ]


def test_ranking_snapshots_are_immutable(coordinator, world, engine) -> None:
    assess(coordinator, world, engine)
    ranking = coordinator.post(
        "/api/v1/rankings", json={"category_id": world["category"]["id"]}
    ).json()
    with engine.connect() as conn, pytest.raises(DBAPIError, match="append-only"):
        conn.execute(
            text("UPDATE ranking_entries SET score = 5 WHERE snapshot_id = :s"),
            {"s": ranking["id"]},
        )


def test_failed_runs_resume_where_they_stopped(coordinator, world, engine) -> None:
    calls = {"n": 0}

    def flaky(system, user):
        calls["n"] += 1
        if calls["n"] == 3:
            error = ExtractionLLMError("Claude API unavailable: overloaded")
            error.retryable = True
            return error
        return scripted(system, user)

    run, _ = assess(coordinator, world, engine, flaky)
    status = coordinator.get(f"/api/v1/assessments/{run['id']}").json()
    assert status["status"] == "failed" and status["items_done"] == 2
    assert "overloaded" in status["error"] and status["next_attempt_at"]

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE assessment_runs SET next_attempt_at = now() WHERE id = :id"),
            {"id": run["id"]},
        )
    pipeline, assessor = assessment_pipeline(engine)
    assert pipeline.run_once()
    status = coordinator.get(f"/api/v1/assessments/{run['id']}").json()
    assert status["status"] == "succeeded" and status["items_done"] == 10
    assert len(assessor.calls) == 8  # only the pairs not already assessed


def test_assessment_is_gated(client_for, coordinator, world) -> None:
    from app.main import app

    category_id = world["category"]["id"]
    assert (
        client_for("judge")
        .post("/api/v1/assessments", json={"category_id": category_id})
        .status_code
        == 403
    )
    first = coordinator.post("/api/v1/assessments", json={"category_id": category_id})
    assert first.status_code == 202
    assert (
        coordinator.post("/api/v1/assessments", json={"category_id": category_id}).status_code
        == 409
    )

    settings = app.dependency_overrides[get_settings]().model_copy(
        update={"llm_provider": "disabled"}
    )
    app.dependency_overrides[get_settings] = lambda: settings
    disabled = coordinator.post("/api/v1/assessments", json={"category_id": category_id})
    assert disabled.status_code == 403


def test_assessment_needs_a_rubric(coordinator) -> None:
    category = make_category(coordinator)
    make_candidate(coordinator, category["id"])
    response = coordinator.post("/api/v1/assessments", json={"category_id": category["id"]})
    assert response.status_code == 409 and "rubric" in response.json()["detail"]
