"""Calibration studies (FR-15): blind benchmark ratings compared with AI ratings."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models import CalibrationStudy, User
from app.services import calibration
from app.services.calibration_metrics import Thresholds
from tests import test_assessment
from tests.test_assessment import assess, items_for
from tests.test_reports import download, generate, pdf_text

world = test_assessment.world
_empty_queues = test_assessment._empty_queues


def user_id(client: TestClient) -> str:
    return client.get("/api/v1/me").json()["id"]


@pytest.fixture
def study(client_for, coordinator: TestClient, world, engine: Engine) -> dict:
    """An assessed category and an open study with two committee raters."""
    assess(coordinator, world, engine)
    coordinator.post("/api/v1/rankings", json={"category_id": world["category"]["id"]})
    coordinator.post(
        "/api/v1/reports", json={"kind": "category", "category_id": world["category"]["id"]}
    )
    raters = [client_for("committee"), client_for("judge")]
    response = coordinator.post(
        "/api/v1/calibration-studies",
        json={
            "category_id": world["category"]["id"],
            "name": "Pilot calibration",
            "rater_ids": [user_id(r) for r in raters],
        },
    )
    assert response.status_code == 201, response.text
    return {**world, "study": response.json(), "raters": raters, "engine": engine}


def worksheet(rater: TestClient, study: dict) -> list[dict]:
    response = rater.get(f"/api/v1/calibration-studies/{study['study']['id']}/items")
    assert response.status_code == 200, response.text
    return response.json()["items"]


def rate_all(rater: TestClient, study: dict, rating_for) -> None:  # noqa: ANN001
    for item in worksheet(rater, study):
        response = rater.put(
            f"/api/v1/calibration-studies/{study['study']['id']}/ratings",
            json={"item_id": item["id"], "rating": rating_for(item)},
        )
        assert response.status_code == 200, response.text


def submit(rater: TestClient, study: dict, attest: bool = True):
    return rater.post(
        f"/api/v1/calibration-studies/{study['study']['id']}/submit", json={"attest_blind": attest}
    )


def test_study_covers_every_ai_rating(study) -> None:
    assert study["study"]["items"] == 10  # 2 finalists x 5 criteria
    assert study["study"]["status"] == "open"
    assert [r["submitted"] for r in study["study"]["raters"]] == [False, False]


def test_raters_are_blind_to_ai_output_until_they_submit(coordinator, study) -> None:
    rater = study["raters"][0]
    category_id = study["category"]["id"]
    jane = study["people"]["Jane Doe"]["id"]

    assessments = rater.get(f"/api/v1/categories/{category_id}/finalists/{jane}/assessments")
    assert assessments.json()["hidden_for_calibration"] is True
    assert assessments.json()["items"] == []
    rankings = rater.get(f"/api/v1/categories/{category_id}/rankings").json()
    assert rankings["hidden_for_calibration"] is True and rankings["ranking"] is None
    report = coordinator.get(f"/api/v1/categories/{category_id}/reports").json()[0]
    assert rater.get(f"/api/v1/reports/{report['id']}/download").status_code == 403
    item = items_for(coordinator, study, "Jane Doe")["advancing-women"]
    assert (
        rater.post(
            f"/api/v1/criterion-assessments/{item['id']}/review", json={"decision": "approved"}
        ).status_code
        == 403
    )
    assert (
        rater.get(f"/api/v1/calibration-studies/{study['study']['id']}/results").status_code == 403
    )

    sheet = worksheet(rater, study)
    assert len(sheet) == 10 and all(i["rating"] is None for i in sheet)
    assert "ai" not in str(sheet[0].keys()).lower()  # the worksheet never carries AI output
    assert sheet[0]["criterion"]["description"]

    # Coordinators who are not raters see everything as usual.
    assert (
        coordinator.get(f"/api/v1/categories/{category_id}/rankings").json()["ranking"] is not None
    )

    rate_all(rater, study, lambda item: 3)
    assert submit(rater, study).status_code == 200
    unblinded = rater.get(f"/api/v1/categories/{category_id}/finalists/{jane}/assessments")
    assert unblinded.json()["hidden_for_calibration"] is False


def test_submission_rules(client_for, study) -> None:
    rater = study["raters"][0]
    sid = study["study"]["id"]
    first = worksheet(rater, study)[0]
    rater.put(
        f"/api/v1/calibration-studies/{sid}/ratings", json={"item_id": first["id"], "rating": 4}
    )
    incomplete = submit(rater, study)
    assert incomplete.status_code == 422 and "9 left" in incomplete.json()["detail"]
    rate_all(rater, study, lambda item: 3)
    assert submit(rater, study, attest=False).status_code == 422
    assert submit(rater, study).status_code == 200
    locked = rater.put(
        f"/api/v1/calibration-studies/{sid}/ratings", json={"item_id": first["id"], "rating": 5}
    )
    assert locked.status_code == 409

    outsider = client_for("committee")
    assert outsider.get(f"/api/v1/calibration-studies/{sid}/items").status_code == 403
    assert (
        outsider.put(
            f"/api/v1/calibration-studies/{sid}/ratings", json={"item_id": first["id"], "rating": 3}
        ).status_code
        == 422
    )
    assert (
        client_for("judge")
        .post(
            "/api/v1/calibration-studies",
            json={
                "category_id": study["category"]["id"],
                "name": "x",
                "rater_ids": [user_id(rater)],
            },
        )
        .status_code
        == 403
    )


def test_closing_records_an_immutable_result(coordinator, study) -> None:
    sid = study["study"]["id"]
    assert coordinator.post(f"/api/v1/calibration-studies/{sid}/close").status_code == 409

    # AI rated mentoring 4 and the rest 3; the humans agree exactly.
    agree = lambda item: 4 if "Advancing women" in item["criterion"]["name"] else 3  # noqa: E731
    for rater in study["raters"]:
        rate_all(rater, study, agree)
        submit(rater, study)

    interim = coordinator.get(f"/api/v1/calibration-studies/{sid}/results").json()
    assert interim["final"] is False
    closed = coordinator.post(f"/api/v1/calibration-studies/{sid}/close").json()
    results = closed["results"]
    assert closed["final"] is True and closed["study"]["status"] == "closed"
    assert results["outcome"] == "inconclusive"  # 10 items, fewer than the 20 required
    assert results["overall"]["ai_vs_human"]["exact"] == 1.0
    assert results["overall"]["ai_vs_human"]["qwk"] == pytest.approx(1.0)
    assert results["overall"]["human_vs_human"]["qwk"] == pytest.approx(1.0)
    assert results["overall"]["bias"] == 0
    assert set(results["by_criterion"]) >= {"Advancing women in leadership"}

    with study["engine"].begin() as conn, pytest.raises(DBAPIError, match="cannot change"):
        conn.execute(
            text(
                "UPDATE calibration_ratings SET rating = 1 WHERE item_id IN "
                "(SELECT id FROM calibration_items WHERE study_id = :s)"
            ),
            {"s": sid},
        )
    with study["engine"].begin() as conn, pytest.raises(DBAPIError, match="is closed"):
        conn.execute(
            text("UPDATE calibration_studies SET outcome = 'passed' WHERE id = :s"), {"s": sid}
        )

    rankings = coordinator.get(f"/api/v1/categories/{study['category']['id']}/rankings").json()
    assert rankings["calibration"]["outcome"] == "inconclusive"
    report = generate(coordinator, study, "category").json()
    assert "AI calibration (FR-15) inconclusive (Pilot calibration" in pdf_text(
        download(coordinator, report)
    )


@pytest.mark.parametrize(
    ("human", "outcome", "reason"),
    [
        (lambda ai: ai, "passed", None),
        (lambda ai: max(1, ai - 2), "failed", "points higher than humans"),
    ],
)
def test_outcomes_against_thresholds(
    client_for, coordinator, world, engine, human, outcome, reason
) -> None:
    """With a lower item minimum, agreement passes and a generous AI fails."""
    assess(coordinator, world, engine)
    raters = [client_for("committee"), client_for("committee")]
    with Session(engine) as session:
        creator = session.get(User, user_id(coordinator))
        created = calibration.create_study(
            session,
            category_id=world["category"]["id"],
            name="Threshold test",
            rater_ids=[user_id(r) for r in raters],
            creator=creator,
            thresholds=Thresholds(min_items=5),
        )
        session.commit()
        sid = str(created.id)
    ai = {"Advancing women in leadership": 4}
    data = {**world, "study": {"id": sid}}
    for rater in raters:
        rate_all(rater, data, lambda item: human(ai.get(item["criterion"]["name"], 3)))
        submit(rater, data)
    with Session(engine) as session:
        study_row = session.get(CalibrationStudy, sid)
        results = calibration.close(session, study_row, session.get(User, user_id(coordinator)))
        session.commit()
    assert results["outcome"] == outcome
    if reason:
        assert any(reason in r for r in results["reasons"])


def test_study_needs_a_completed_run(coordinator, client_for) -> None:
    from tests.test_knowledge_base import make_candidate, make_category

    category = make_category(coordinator)
    make_candidate(coordinator, category["id"])
    response = coordinator.post(
        "/api/v1/calibration-studies",
        json={
            "category_id": category["id"],
            "name": "x",
            "rater_ids": [user_id(client_for("committee"))],
        },
    )
    assert response.status_code == 409
