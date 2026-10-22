"""Judges' pack: top finalists of each category's latest ranking with reports and documents."""

from fastapi.testclient import TestClient

from tests import test_reports
from tests.test_knowledge_base import make_category
from tests.test_reports import generate

# Shared fixtures from the report tests.
world = test_reports.world
ranked = test_reports.ranked
_empty_queues = test_reports._empty_queues


def pack_for(client: TestClient, category_id: str) -> dict:
    response = client.get("/api/v1/judges-pack")
    assert response.status_code == 200, response.text
    return next(c for c in response.json() if c["id"] == category_id)


def test_pack_lists_ranked_finalists_with_reports_and_documents(
    client_for, coordinator, ranked
) -> None:
    judge = client_for("judge")
    category_id = ranked["category"]["id"]
    pack = pack_for(judge, category_id)
    assert pack["ranking_id"] == ranked["ranking"]["id"]
    assert pack["production"] is False and pack["category_report"] is None

    # Mary has a rejected rating, so no score and no rank: she isn't in the pack.
    [jane] = pack["finalists"]
    assert (jane["full_name"], jane["rank"]) == ("Jane Doe", 1)
    assert jane["score_display"] and jane["report"] is None
    [document] = jane["documents"]
    assert document["filename"] == "evidence.docx"
    assert judge.get(f"/api/v1/documents/{document['id']}/content").status_code == 200

    individual = generate(coordinator, ranked, "individual", "Jane Doe").json()
    category = generate(coordinator, ranked, "category").json()
    pack = pack_for(judge, category_id)
    assert pack["finalists"][0]["report"]["id"] == individual["id"]
    assert pack["category_report"]["id"] == category["id"]

    # Withdrawn documents leave the pack.
    coordinator.post(
        f"/api/v1/documents/{document['id']}/withdraw", json={"reason": "Wrong nominee"}
    )
    assert pack_for(judge, category_id)["finalists"][0]["documents"] == []


def test_unranked_category_is_listed_empty(client_for, coordinator) -> None:
    category = make_category(coordinator)
    pack = pack_for(client_for("judge"), category["id"])
    assert pack["ranking_id"] is None and pack["finalists"] == []
