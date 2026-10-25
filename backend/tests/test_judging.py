"""Judges score finalists 0-3 independently; the tally, hidden from judges, picks the winner."""

import io
import json
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests import test_reports
from tests.test_judges_pack import pack_for
from tests.test_knowledge_base import make_candidate, make_category

world = test_reports.world
ranked = test_reports.ranked
_empty_queues = test_reports._empty_queues


def score_url(category: dict, person: dict) -> str:
    return f"/api/v1/categories/{category['id']}/finalists/{person['id']}/judge-score"


def score(client: TestClient, category: dict, person: dict, value: int, comment="Strong case."):
    return client.put(score_url(category, person), json={"score": value, "comment": comment})


def tally_for(client: TestClient, category: dict) -> dict:
    response = client.get("/api/v1/judge-scores")
    assert response.status_code == 200, response.text
    return next(c for c in response.json() if c["id"] == category["id"])


def test_three_judges_score_and_the_highest_average_wins(client_for, coordinator) -> None:
    category = make_category(coordinator)
    jane = make_candidate(coordinator, category["id"], "Jane Doe")
    mary = make_candidate(coordinator, category["id"], "Mary Major")
    judges = [client_for("judge") for _ in range(3)]

    for judge, (j, m) in zip(judges, [(3, 2), (2, 2), (3, 1)], strict=True):
        assert score(judge, category, jane, j).status_code == 200
        assert score(judge, category, mary, m).status_code == 200

    tally = tally_for(coordinator, category)
    assert tally["status"] == "winner" and tally["complete"] is True
    first, second = tally["candidates"]
    assert (first["full_name"], first["total"], first["average"], first["rank"]) == (
        "Jane Doe",
        8,
        "2.67",
        1,
    )
    assert (second["full_name"], second["average"], second["rank"]) == ("Mary Major", "1.67", 2)
    assert tally["leaders"] == [jane["id"]]
    assert {s["comment"] for s in first["scores"]} == {"Strong case."}

    # A judge revising a score changes the result: now a tie at the top.
    assert score(judges[0], category, mary, 3).status_code == 200
    assert score(judges[1], category, mary, 3).status_code == 200
    assert score(judges[2], category, mary, 2).status_code == 200
    tally = tally_for(coordinator, category)
    assert tally["status"] == "tie" and set(tally["leaders"]) == {jane["id"], mary["id"]}
    assert all(c["is_tie"] and c["rank"] == 1 for c in tally["candidates"])


def test_fewer_than_three_judges_is_provisional(client_for, coordinator) -> None:
    category = make_category(coordinator)
    jane = make_candidate(coordinator, category["id"], "Jane Doe")
    assert tally_for(coordinator, category)["status"] == "no_scores"
    score(client_for("judge"), category, jane, 2)
    tally = tally_for(coordinator, category)
    assert tally["status"] == "provisional" and tally["complete"] is False
    assert tally["candidates"][0]["judges_scored"] == 1


def test_judges_never_see_the_tally_or_each_other(client_for, coordinator) -> None:
    category = make_category(coordinator)
    jane = make_candidate(coordinator, category["id"], "Jane Doe")
    judge = client_for("judge")
    assert judge.get("/api/v1/judge-scores").status_code == 403
    for role in ("secretariat", "committee", "admin"):
        assert client_for(role).get("/api/v1/judge-scores").status_code == 200
    # Only those with the scoring right score (judges by default).
    assert score(client_for("reviewer"), category, jane, 2).status_code == 403
    me = judge.get("/api/v1/me").json()["permissions"]
    assert me["score_candidates"] is True and me["view_judge_scores"] is False

    # The tally right can't be given to judges, through the API or the database.
    admin = client_for("admin")
    refused = admin.put(
        "/api/v1/role-permissions/judge",
        json={"permissions": ["score_candidates", "view_judge_scores"]},
    )
    assert refused.status_code == 422


def test_scores_need_a_comment_and_a_score_from_0_to_3(client_for, coordinator) -> None:
    category = make_category(coordinator)
    jane = make_candidate(coordinator, category["id"], "Jane Doe")
    judge = client_for("judge")
    assert score(judge, category, jane, 4).status_code == 422
    assert score(judge, category, jane, -1).status_code == 422
    assert score(judge, category, jane, 2, comment="  ").status_code == 422
    assert score(judge, category, jane, 0).status_code == 200


def test_closing_scoring_locks_scores_until_an_admin_reopens(client_for, coordinator, engine):
    category = make_category(coordinator)
    jane = make_candidate(coordinator, category["id"], "Jane Doe")
    judge = client_for("judge")
    score(judge, category, jane, 2)
    base = f"/api/v1/categories/{category['id']}/judge-scores"

    closed = coordinator.post(f"{base}/close")
    assert closed.status_code == 200 and closed.json()["closed_at"]
    assert score(judge, category, jane, 3).status_code == 409
    assert coordinator.post(f"{base}/reopen", json={"reason": "late"}).status_code == 403
    reopened = client_for("admin").post(f"{base}/reopen", json={"reason": "A judge was ill."})
    assert reopened.status_code == 200 and reopened.json()["closed_at"] is None
    assert score(judge, category, jane, 3).status_code == 200

    with engine.connect() as conn:
        actions = set(
            conn.scalars(
                text("SELECT action FROM audit_events WHERE entity_id IN (:c, :fc)"),
                {"c": category["id"], "fc": jane["finalist_category_id"]},
            )
        )
    assert {"judge_score.saved", "judging.closed", "judging.reopened"} <= actions


def test_the_pack_shows_only_the_judges_own_score(client_for, ranked) -> None:
    category = ranked["category"]
    jane = ranked["people"]["Jane Doe"]
    first, second = client_for("judge"), client_for("judge")
    score(first, category, jane, 3, comment="Outstanding.")
    [mine] = pack_for(first, category["id"])["finalists"]
    assert mine["my_score"]["score"] == 3 and mine["my_score"]["comment"] == "Outstanding."
    assert pack_for(second, category["id"])["finalists"][0]["my_score"] is None


def test_scores_are_exported_and_purged(client_for, coordinator, engine: Engine) -> None:
    category = make_category(coordinator)
    jane = make_candidate(coordinator, category["id"], "Jane Doe")
    score(client_for("judge"), category, jane, 2, comment="Good.")
    base = f"/api/v1/categories/{category['id']}/finalists/{jane['id']}"
    with zipfile.ZipFile(io.BytesIO(coordinator.get(f"{base}/export").content)) as zf:
        data = json.loads(zf.read("data.json"))
    [exported] = data["judge_scores"]
    assert (exported["by_role"], exported["score"], exported["comment"]) == ("judge", 2, "Good.")

    purged = client_for("admin").post(
        f"{base}/purge", json={"reason": "erasure request", "confirm_name": "Jane Doe"}
    )
    assert purged.status_code == 200, purged.text
    with engine.connect() as conn:
        assert not conn.execute(
            text("SELECT count(*) FROM judge_scores WHERE finalist_category_id = :fc"),
            {"fc": jane["finalist_category_id"]},
        ).scalar_one()
