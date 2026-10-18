"""Hybrid retrieval and citation checks (spec §5.3, §13 candidate isolation)."""

import random
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.services.reranking import VoyageReranker
from tests import fixture_files
from tests.conftest import drain
from tests.test_knowledge_base import make_candidate, make_category, upload

JANE = {
    "Board leadership": [
        "Jane Doe has chaired the audit committee of Example Holdings since 2019.",
        "She led the board's response to a cyber incident and commissioned an external review.",
    ],
    "Governance reform": [
        "Jane introduced a director skills matrix and annual board evaluations.",
        "She championed term limits for non-executive directors.",
    ],
    "Mentoring": [
        "Jane mentors twelve women preparing for first board appointments in Kampala.",
    ],
}
MARY = {
    "Board leadership": [
        "Mary Major chairs the risk committee of Zanzibar Shipping Limited.",
        "She oversaw the merger with Dar Logistics in 2023.",
    ],
    "Sustainability": [
        "Mary led adoption of climate disclosure aligned with ISSB standards.",
    ],
}


@pytest.fixture(autouse=True)
def _empty_queue(empty_queue: None) -> None:
    pass


@pytest.fixture
def world(coordinator: TestClient, make_pipeline) -> dict:
    """One category with two candidates whose evidence is indexed."""
    category = make_category(coordinator)
    jane = make_candidate(coordinator, category["id"], "Jane Doe")
    mary = make_candidate(coordinator, category["id"], "Mary Major")
    for candidate, sections in ((jane, JANE), (mary, MARY)):
        body = upload(
            coordinator,
            category["id"],
            candidate["id"],
            [("evidence.docx", fixture_files.docx_from(sections))],
        ).json()
        candidate["document_ids"] = [d["id"] for d in body["accepted"]]
    drain(make_pipeline())
    return {"category": category, "jane": jane, "mary": mary}


def search(client: TestClient, category: dict, candidate: dict, **params) -> dict:
    response = client.get(
        f"/api/v1/categories/{category['id']}/finalists/{candidate['id']}/search", params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_search_returns_ranked_cited_passages(coordinator: TestClient, world) -> None:
    result = search(coordinator, world["category"], world["jane"], q="audit committee chair")
    assert result["passages"], result
    top = result["passages"][0]
    assert top["rank"] == 1
    assert "audit committee" in top["content"]
    assert top["filename"] == "evidence.docx"
    assert top["section"] == "Board leadership"
    assert top["lexical_rank"] is not None and top["vector_rank"] is not None
    assert top["rerank_score"] is not None
    assert result["config"]["embedding_model"] == "fake:hashing"
    assert result["config"]["reranker_model"] == "fake:overlap"
    assert result["candidates"]["vector"] == result["candidates"]["indexed_chunks"]


def test_retrieval_never_crosses_candidates(coordinator: TestClient, world, engine: Engine) -> None:
    jane = world["jane"]
    # A term that only appears in Mary's evidence finds nothing for Jane.
    result = search(coordinator, world["category"], jane, q="Zanzibar Shipping merger")
    assert all("Zanzibar" not in p["content"] for p in result["passages"])
    assert "no_keyword_matches" in result["flags"]

    with engine.connect() as conn:
        jane_chunks = set(
            conn.execute(
                text("SELECT id::text FROM document_chunks WHERE finalist_category_id = :fc"),
                {"fc": jane["finalist_category_id"]},
            ).scalars()
        )
    vocabulary = " ".join(" ".join(p) for p in (*JANE.values(), *MARY.values())).split()
    rng = random.Random(7)
    for _ in range(25):
        query = " ".join(rng.sample(vocabulary, 4))
        for passage in search(coordinator, world["category"], jane, q=query)["passages"]:
            assert passage["chunk_id"] in jane_chunks, query
            assert passage["document_id"] in jane["document_ids"]


def test_same_person_is_isolated_across_categories(coordinator: TestClient, world) -> None:
    other_category = make_category(coordinator)
    jane_elsewhere = make_candidate(coordinator, other_category["id"], "Jane Doe")
    result = search(coordinator, other_category, jane_elsewhere, q="audit committee")
    assert result["passages"] == []
    assert result["flags"] == ["no_indexed_evidence"]


def test_results_are_reproducible_and_respect_top_k(coordinator: TestClient, world) -> None:
    first = search(coordinator, world["category"], world["jane"], q="board evaluation", top_k=2)
    second = search(coordinator, world["category"], world["jane"], q="board evaluation", top_k=2)
    assert [p["chunk_id"] for p in first["passages"]] == [p["chunk_id"] for p in second["passages"]]
    assert len(first["passages"]) <= 2


def test_withdrawn_evidence_is_not_retrieved(coordinator: TestClient, world) -> None:
    mary = world["mary"]
    assert search(coordinator, world["category"], mary, q="Zanzibar")["passages"]
    coordinator.post(
        f"/api/v1/documents/{mary['document_ids'][0]}/withdraw", json={"reason": "Superseded"}
    )
    result = search(coordinator, world["category"], mary, q="Zanzibar")
    assert result["passages"] == []
    assert "no_indexed_evidence" in result["flags"]


def test_search_by_rubric_criterion(coordinator: TestClient, world, engine: Engine) -> None:
    with engine.begin() as conn:
        rubric = conn.execute(
            text("INSERT INTO rubric_versions (category_id, version) VALUES (:c, 1) RETURNING id"),
            {"c": world["category"]["id"]},
        ).scalar_one()
        criterion = conn.execute(
            text(
                "INSERT INTO rubric_criteria (rubric_version_id, code, name, description, "
                "evidence_expectations, position) VALUES (:r, 'mentoring', 'Mentoring', "
                "'Develops and mentors women for board roles', "
                "'Named mentoring programmes and outcomes', 1) RETURNING id"
            ),
            {"r": rubric},
        ).scalar_one()

    result = search(coordinator, world["category"], world["jane"], criterion_id=str(criterion))
    assert result["criterion_id"] == str(criterion)
    assert result["query"].startswith("Mentoring. Develops and mentors women")
    assert "mentors twelve women" in result["passages"][0]["content"]

    other = make_category(coordinator)
    candidate = make_candidate(coordinator, other["id"])
    response = coordinator.get(
        f"/api/v1/categories/{other['id']}/finalists/{candidate['id']}/search",
        params={"criterion_id": str(criterion)},
    )
    assert response.status_code == 404


def test_search_requires_exactly_one_query(coordinator: TestClient, world) -> None:
    url = f"/api/v1/categories/{world['category']['id']}/finalists/{world['jane']['id']}/search"
    assert coordinator.get(url).status_code == 422
    both = coordinator.get(url, params={"q": "audit", "criterion_id": str(uuid.uuid4())})
    assert both.status_code == 422


def test_searches_are_audited(coordinator: TestClient, world, engine: Engine) -> None:
    result = search(coordinator, world["category"], world["jane"], q="skills matrix")
    with engine.connect() as conn:
        details = conn.execute(
            text(
                "SELECT details FROM audit_events WHERE action = 'evidence.searched' "
                "AND entity_id = :fc ORDER BY id DESC LIMIT 1"
            ),
            {"fc": world["jane"]["finalist_category_id"]},
        ).scalar_one()
    assert details["query"] == "skills matrix"
    assert details["returned"] == [p["chunk_id"] for p in result["passages"]]


def test_citation_verification(coordinator: TestClient, world) -> None:
    category, jane, mary = world["category"], world["jane"], world["mary"]
    jane_passage = search(coordinator, category, jane, q="audit committee")["passages"][0]
    mary_passage = search(coordinator, category, mary, q="Zanzibar")["passages"][0]

    response = coordinator.post(
        f"/api/v1/categories/{category['id']}/finalists/{jane['id']}/citations/verify",
        json={
            "citations": [
                # Case, whitespace and typographic quotes don't matter.
                {
                    "chunk_id": jane_passage["chunk_id"],
                    "quote": "chaired   the AUDIT committee of Example Holdings",
                },
                {
                    "chunk_id": jane_passage["chunk_id"],
                    "quote": "chaired the remuneration committee",
                },
                {"chunk_id": mary_passage["chunk_id"], "quote": "Zanzibar Shipping"},
                {"chunk_id": str(uuid.uuid4()), "quote": "anything"},
                {"chunk_id": jane_passage["chunk_id"], "quote": "   "},
            ]
        },
    )
    checks = response.json()
    assert [c["valid"] for c in checks] == [True, False, False, False, False]
    assert checks[0]["filename"] == "evidence.docx"
    assert checks[1]["reason"] == "quoted text does not appear in the passage"
    assert checks[2]["reason"] == "passage is not in this finalist's knowledge base"
    assert checks[3]["reason"] == "passage is not in this finalist's knowledge base"
    assert checks[4]["reason"] == "empty quote"


def test_vector_pool_is_exact_with_many_chunks(
    coordinator: TestClient, make_pipeline, engine: Engine
) -> None:
    """Pre-filtering must still return a full candidate pool (no approximate-index shortfall)."""
    category = make_category(coordinator)
    candidate = make_candidate(coordinator, category["id"])
    sections = {f"Section {i}": [f"Paragraph about topic {i}. " * 120] for i in range(30)}
    upload(
        coordinator,
        category["id"],
        candidate["id"],
        [("long.docx", fixture_files.docx_from(sections))],
    )
    drain(make_pipeline())
    result = search(coordinator, category, candidate, q="topic 7")
    assert result["candidates"]["indexed_chunks"] >= 25
    assert result["candidates"]["vector"] == 20
    assert len(result["passages"]) == 10


def test_voyage_reranker_maps_scores_to_input_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.2}]
            },
        )

    reranker = VoyageReranker(
        "rerank-2.5", "key", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert reranker.rerank("q", ["a", "b"]) == [0.2, 0.9]


def test_recall_benchmark(coordinator: TestClient, world, engine: Engine) -> None:
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.evaluation.retrieval import BenchmarkError, run_benchmark
    from app.services.embeddings import HashingEmbedder
    from app.services.reranking import OverlapReranker
    from app.services.retrieval import Retriever

    settings = get_settings()
    retriever = Retriever(HashingEmbedder(settings.embedding_dim), OverlapReranker(), settings)
    code = world["category"]["code"]
    benchmark = {
        "name": "test",
        "target_recall": 0.75,
        "cases": [
            {
                "id": "audit",
                "category": code,
                "candidate": "Jane Doe",
                "query": "Who chairs the audit committee?",
                "relevant": [{"document": "evidence.docx", "quote": "chaired the audit committee"}],
            },
            {
                "id": "mentoring",
                "category": code,
                "candidate": "jane doe",
                "query": "mentoring women for boards",
                "relevant": [
                    {"quote": "mentors twelve women"},
                    {"quote": "this text is not in the evidence"},
                ],
            },
        ],
    }
    with Session(engine) as session:
        report = run_benchmark(session, retriever, benchmark, top_k=5)
        assert [c.found for c in report.cases] == [1, 1]
        assert report.cases[0].ranks == [1]
        assert report.recall == pytest.approx(2 / 3)
        assert not report.passed
        assert "FAIL" in report.summary()

        benchmark["cases"][0]["candidate"] = "Nobody"
        with pytest.raises(BenchmarkError, match="no candidates named"):
            run_benchmark(session, retriever, benchmark)
