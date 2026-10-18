"""Dashboard overview and the cross-finalist document library."""

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests import test_assessment
from tests.test_assessment import assess, world  # noqa: F401 (fixture)
from tests.test_knowledge_base import make_candidate, make_category, pdf, upload

_empty_queues = test_assessment._empty_queues


def test_dashboard_counts_and_top_ranked(coordinator: TestClient, world, engine: Engine) -> None:  # noqa: F811
    assess(coordinator, world, engine)
    response = coordinator.post("/api/v1/rankings", json={"category_id": world["category"]["id"]})
    assert response.status_code == 201, response.text

    data = coordinator.get("/api/v1/dashboard").json()
    mine = next(c for c in data["by_category"] if c["id"] == world["category"]["id"])
    assert mine == {
        "id": world["category"]["id"],
        "name": world["category"]["name"],
        "finalists": 2,
        "documents": 2,
        "ranked": True,
    }
    progress = data["progress"]
    assert progress["nominations"] >= 2
    assert progress["assessed"] >= 2 and progress["documents_indexed"] >= 2
    assert data["documents"] >= 2 and data["categories_ranked"] >= 1

    scores = [float(t["score_display"]) for t in data["top_ranked"]]
    assert scores == sorted(scores, reverse=True) and len(scores) <= 5
    for entry in data["top_ranked"]:
        if entry["category_id"] == world["category"]["id"]:
            assert entry["full_name"] in world["people"]
            assert entry["production"] is False  # template rubric is a draft


def test_dashboard_hides_rankings_from_blinded_raters(
    coordinator: TestClient,
    client_for,
    world,  # noqa: F811
    engine: Engine,
) -> None:
    assess(coordinator, world, engine)
    coordinator.post("/api/v1/rankings", json={"category_id": world["category"]["id"]})
    committee = client_for("committee")
    me = committee.get("/api/v1/me").json()
    study = coordinator.post(
        "/api/v1/calibration-studies",
        json={"category_id": world["category"]["id"], "name": "Blind", "rater_ids": [me["id"]]},
    )
    assert study.status_code == 201, study.text

    data = committee.get("/api/v1/dashboard").json()
    assert data["rankings_hidden"] >= 1
    assert all(t["category_id"] != world["category"]["id"] for t in data["top_ranked"])


def test_document_library_filters(coordinator: TestClient) -> None:
    category = make_category(coordinator)
    jane = make_candidate(coordinator, category["id"], "Jane Library")
    ann = make_candidate(coordinator, category["id"], "Ann Library")
    upload(coordinator, category["id"], jane["id"], [("jane-cv.pdf", pdf())])
    upload(
        coordinator,
        category["id"],
        ann["id"],
        [("ann-form.pdf", pdf())],
        source_type="nomination_form",
    )

    def names(**params) -> list[str]:
        response = coordinator.get(
            "/api/v1/documents", params={"category_id": category["id"], **params}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == len(body["items"])
        return sorted(i["filename"] for i in body["items"])

    assert names() == ["ann-form.pdf", "jane-cv.pdf"]
    assert names(finalist_id=jane["id"]) == ["jane-cv.pdf"]
    assert names(source_type="nomination_form") == ["ann-form.pdf"]
    assert names(q="Jane Lib") == ["jane-cv.pdf"]
    assert names(q="ann-form") == ["ann-form.pdf"]
    assert names(kind="pdf") == ["ann-form.pdf", "jane-cv.pdf"]
    assert names(kind="word") == []

    item = coordinator.get("/api/v1/documents", params={"finalist_id": jane["id"]}).json()["items"][
        0
    ]
    assert item["finalist_name"] == "Jane Library"
    assert item["category_name"] == category["name"]
    assert coordinator.get("/api/v1/documents", params={"kind": "exe"}).status_code == 422
