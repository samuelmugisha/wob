"""Claim extraction end to end: API → worker (scripted LLM) → verified claims (FR-06)."""

import re
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.services.claims.extraction import Passage, make_batches, parse_period
from app.services.claims.llm import (
    ExtractionLLMError,
    ExtractionRefused,
    OutputTruncated,
    ScriptedClaimLLM,
)
from app.services.claims.schema import (
    ClaimExtractionOutput,
    Contradiction,
    EvidenceQuote,
    ExtractedClaim,
    QuantitativeOutcome,
)
from app.workers.claims import ClaimPipeline
from tests import fixture_files
from tests.conftest import drain
from tests.test_knowledge_base import make_candidate, make_category, upload

JANE = {
    "Board leadership": [
        "Jane Doe has chaired the audit committee of Example Holdings since 2019.",
        "Her CV states she joined the Example Holdings board in March 2018.",
    ],
    "Mentoring": ["Jane mentors twelve women preparing for first board appointments."],
    "Appointment letter": ["The letter confirms her appointment to the board in March 2019."],
}
PASSAGE = re.compile(r'<passage id="(P\d+)" source="[^"]*">\n(.*?)\n</passage>', re.S)


def passages_in(prompt: str) -> dict[str, str]:
    return dict(PASSAGE.findall(prompt))


def find(passages: dict[str, str], phrase: str) -> str:
    return next(pid for pid, body in passages.items() if phrase in body)


def claim(statement, evidence, *, claim_type="position", contradicting=(), start=None, **extra):
    return ExtractedClaim(
        statement=statement,
        claim_type=claim_type,
        entity=extra.get("entity"),
        role=extra.get("role"),
        period_start=start,
        period_end=None,
        period_text=extra.get("period_text"),
        quantitative_outcomes=extra.get("outcomes", []),
        supporting_evidence=[EvidenceQuote(passage_id=p, quote=q) for p, q in evidence],
        contradicting_evidence=[EvidenceQuote(passage_id=p, quote=q) for p, q in contradicting],
        limitations=extra.get("limitations"),
    )


def realistic(system: str, user: str) -> ClaimExtractionOutput:
    """What a careful model returns, plus two bad claims the verifier must drop."""
    p = passages_in(user)
    audit, joined, mentor, letter = (
        find(p, "audit committee"),
        find(p, "March 2018"),
        find(p, "mentors"),
        find(p, "letter"),
    )
    return ClaimExtractionOutput(
        claims=[
            claim(
                "Jane Doe has chaired the audit committee of Example Holdings since 2019.",
                [(audit, "chaired the audit committee of Example Holdings since 2019")],
                start="2019",
                entity="Example Holdings",
                role="Audit committee chair",
                period_text="since 2019",
            ),
            claim(
                "Jane Doe joined the Example Holdings board in March 2018.",
                [(joined, "joined the Example Holdings board in March 2018")],
                contradicting=[(letter, "appointment to the board in March 2019")],
                start="2018-03",
                limitations="Stated only in her CV.",
            ),
            claim(
                "Jane Doe mentors twelve women preparing for board appointments.",
                [(mentor, "mentors twelve women preparing for first board appointments")],
                claim_type="advocacy",
                outcomes=[QuantitativeOutcome(metric="women mentored", value="12", unit=None)],
            ),
            # Fabricated: the quote is not in the passage.
            claim(
                "Jane Doe won the 2022 Governance Excellence Award.",
                [(audit, "won the Governance Excellence Award")],
                claim_type="award",
            ),
            # Cites a passage id that does not exist.
            claim("Jane Doe chairs the remuneration committee.", [("P999", "chairs")]),
        ],
        contradictions=[
            Contradiction(
                description="Board appointment date differs between CV (2018) and letter (2019).",
                evidence=[
                    EvidenceQuote(passage_id=joined, quote="March 2018"),
                    EvidenceQuote(passage_id=letter, quote="March 2019"),
                ],
            )
        ],
        missing_information=["No end date or outcomes are given for the audit committee role."],
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
def world(coordinator: TestClient, make_pipeline) -> dict:
    category = make_category(coordinator)
    jane = make_candidate(coordinator, category["id"], "Jane Doe")
    upload(
        coordinator, category["id"], jane["id"], [("evidence.docx", fixture_files.docx_from(JANE))]
    )
    drain(make_pipeline())
    return {"category": category, "jane": jane}


def claims_pipeline(engine: Engine, respond, **overrides) -> tuple[ClaimPipeline, ScriptedClaimLLM]:
    llm = ScriptedClaimLLM(respond)
    settings = get_settings().model_copy(update=overrides)
    return ClaimPipeline(sessionmaker(engine, expire_on_commit=False), llm, settings), llm


def urls(world) -> tuple[str, str]:
    base = f"/api/v1/categories/{world['category']['id']}/finalists/{world['jane']['id']}/claims"
    return base, f"{base}/extract"


def test_extraction_produces_verified_claims(coordinator: TestClient, world, engine) -> None:
    list_url, extract_url = urls(world)
    response = coordinator.post(extract_url)
    assert response.status_code == 202, response.text
    assert response.json()["run"]["status"] == "queued"

    pipeline, llm = claims_pipeline(engine, realistic)
    assert pipeline.run_once()

    body = coordinator.get(list_url).json()
    run = body["latest_run"]
    assert run["status"] == "succeeded"
    assert run["claims_created"] == 3
    assert run["prompt_version"] == "claim-extraction-v1"
    reasons = {(d["kind"], d["reason"]) for d in run["discarded"]}
    assert ("claim", "no supporting quote could be verified against the evidence") in reasons
    assert ("quote", "quote not found in the cited passage") in reasons
    assert any(r.startswith("unknown passage id") for _, r in reasons)
    assert len(run["contradictions"]) == 1
    assert {e["quote"] for e in run["contradictions"][0]["evidence"]} == {
        "March 2018",
        "March 2019",
    }
    assert run["missing_information"]

    claims = {c["statement"]: c for c in body["claims"]}
    assert len(claims) == 3
    audit = claims["Jane Doe has chaired the audit committee of Example Holdings since 2019."]
    assert audit["status"] == "unverified"
    assert audit["period_start"] == "2019-01-01" and audit["period_start_precision"] == "year"
    assert audit["evidence"][0]["filename"] == "evidence.docx"
    assert audit["evidence"][0]["relation"] == "supports"
    joined = claims["Jane Doe joined the Example Holdings board in March 2018."]
    assert joined["status"] == "disputed"
    assert {e["relation"] for e in joined["evidence"]} == {"supports", "contradicts"}
    assert joined["period_start_precision"] == "month"
    mentor = claims["Jane Doe mentors twelve women preparing for board appointments."]
    assert mentor["quantitative_outcomes"] == [
        {"metric": "women mentored", "value": "12", "unit": None}
    ]

    # The prompt carries the nominee, the injection guard, and only this candidate's evidence.
    system, user = llm.calls[0]
    assert "untrusted data" in system
    assert "Nominee: Jane Doe" in user


def test_rerun_supersedes_previous_claims(coordinator: TestClient, world, engine) -> None:
    list_url, extract_url = urls(world)
    coordinator.post(extract_url)
    claims_pipeline(engine, realistic)[0].run_once()
    first = {c["id"] for c in coordinator.get(list_url).json()["claims"]}

    coordinator.post(extract_url)
    claims_pipeline(engine, realistic)[0].run_once()
    second = {c["id"] for c in coordinator.get(list_url).json()["claims"]}
    assert len(second) == 3 and not first & second
    with engine.connect() as conn:
        superseded = conn.execute(
            text("SELECT count(*) FROM claims WHERE id = ANY(:ids) AND superseded_at IS NOT NULL"),
            {"ids": list(first)},
        ).scalar_one()
    assert superseded == 3


def test_large_evidence_is_batched_and_truncation_splits(
    coordinator: TestClient, make_pipeline, engine
) -> None:
    category = make_category(coordinator)
    candidate = make_candidate(coordinator, category["id"], "Long Evidence")
    sections = {
        f"Role {i}": [f"She held role number {i} at Organisation {i}. " * 60] for i in range(6)
    }
    upload(
        coordinator,
        category["id"],
        candidate["id"],
        [("long.docx", fixture_files.docx_from(sections))],
    )
    drain(make_pipeline())
    coordinator.post(
        f"/api/v1/categories/{category['id']}/finalists/{candidate['id']}/claims/extract"
    )

    def respond(system: str, user: str):
        p = passages_in(user)
        if len(p) > 1:
            return OutputTruncated("too long")  # forces the extractor to split batches
        pid, body = next(iter(p.items()))
        sentence = re.search(r"She held role number \d+ at Organisation \d+\.", body).group(0)
        return ClaimExtractionOutput(
            claims=[claim(sentence, [(pid, sentence)])], contradictions=[], missing_information=[]
        )

    pipeline, llm = claims_pipeline(engine, respond, claim_batch_tokens=2500)
    pipeline.run_once()
    with engine.connect() as conn:
        run = conn.execute(
            text(
                "SELECT status, batches, claims_created, input_chunk_ids "
                "FROM claim_extraction_runs WHERE finalist_category_id = :fc"
            ),
            {"fc": candidate["finalist_category_id"]},
        ).one()
    assert run.status == "succeeded"
    assert len(run.input_chunk_ids) >= 4
    # Every passage ended up in its own request after splitting, and each yielded a claim.
    assert run.batches == len(run.input_chunk_ids)
    assert run.claims_created == len(run.input_chunk_ids)
    assert len(llm.calls) > run.batches  # the truncated attempts were retried as halves


def test_refusal_fails_without_retry(coordinator: TestClient, world, engine) -> None:
    list_url, extract_url = urls(world)
    coordinator.post(extract_url)
    claims_pipeline(engine, lambda s, u: ExtractionRefused("declined (category: cyber)"))[
        0
    ].run_once()
    run = coordinator.get(list_url).json()["latest_run"]
    assert run["status"] == "failed"
    assert run["next_attempt_at"] is None
    assert "declined" in run["error"]


def test_transient_errors_retry_later(coordinator: TestClient, world, engine) -> None:
    list_url, extract_url = urls(world)
    coordinator.post(extract_url)

    def unavailable(system, user):
        error = ExtractionLLMError("Claude API unavailable: overloaded")
        error.retryable = True
        return error

    pipeline, _ = claims_pipeline(engine, unavailable)
    pipeline.run_once()
    run = coordinator.get(list_url).json()["latest_run"]
    assert run["status"] == "failed" and run["next_attempt_at"] is not None
    assert not pipeline.run_once()  # backing off

    # A new request cancels the waiting retry instead of conflicting with it.
    assert coordinator.post(extract_url).status_code == 202
    with engine.connect() as conn:
        statuses = (
            conn.execute(
                text(
                    "SELECT status FROM claim_extraction_runs WHERE finalist_category_id = :fc "
                    "ORDER BY created_at"
                ),
                {"fc": world["jane"]["finalist_category_id"]},
            )
            .scalars()
            .all()
        )
    assert statuses[-2:] == ["cancelled", "queued"]


def test_only_one_active_run(coordinator: TestClient, world) -> None:
    _, extract_url = urls(world)
    assert coordinator.post(extract_url).status_code == 202
    assert coordinator.post(extract_url).status_code == 409


def test_extraction_requires_indexed_evidence(coordinator: TestClient) -> None:
    category = make_category(coordinator)
    candidate = make_candidate(coordinator, category["id"])
    response = coordinator.post(
        f"/api/v1/categories/{category['id']}/finalists/{candidate['id']}/claims/extract"
    )
    assert response.status_code == 409


def test_extraction_is_gated_on_approval(client_for, world) -> None:
    from app.main import app

    client = client_for("secretariat")
    _, extract_url = urls(world)
    for provider, approved, message in [
        ("disabled", False, "LLM_PROVIDER=disabled"),
        ("anthropic", False, "has not been approved"),
    ]:
        settings = app.dependency_overrides[get_settings]().model_copy(
            update={"llm_provider": provider, "external_ai_processing_approved": approved}
        )
        app.dependency_overrides[get_settings] = lambda s=settings: s
        response = client.post(extract_url)
        assert response.status_code == 403
        assert message in response.json()["detail"]
        listing = client.get(extract_url.removesuffix("/extract")).json()
        assert listing["extraction"]["enabled"] is False


def test_judges_cannot_start_extraction(client_for, world) -> None:
    judge = client_for("judge")
    assert judge.post(urls(world)[1]).status_code == 403


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2019", (date(2019, 1, 1), "year")),
        ("2019-03", (date(2019, 3, 1), "month")),
        ("2019-03-14", (date(2019, 3, 14), "day")),
        ("2019-13", (None, None)),
        ("March 2019", (None, None)),
        (None, (None, None)),
    ],
)
def test_parse_period(value, expected) -> None:
    assert parse_period(value) == expected


def test_batches_respect_token_budget() -> None:
    def p(i, tokens):
        return Passage(f"P{i}", None, None, "f", None, None, None, "x", tokens)  # type: ignore[arg-type]

    batches = make_batches([p(1, 500), p(2, 500), p(3, 500), p(4, 3000)], budget_tokens=1500)
    assert [[x.pid for x in b] for b in batches] == [["P1", "P2"], ["P3"], ["P4"]]
