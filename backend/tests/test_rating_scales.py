"""The board's 0-3 scale (0 None, 1 Poor, 2 Good, 3 Excellent) on new rubric versions, beside
the original 1-5 scale on earlier ones."""

import pytest
from fastapi.testclient import TestClient

from app.services.assessment.schema import (
    Citation,
    CriterionRating,
    OneToFiveRating,
    ZeroToThreeRating,
    rating_output,
)
from app.services.scales import SCALES, RatingScale
from tests import test_assessment
from tests.test_assessment import PASSAGE, assess, items_for

_empty_queues = test_assessment._empty_queues


@pytest.fixture
def world(coordinator: TestClient, make_pipeline) -> dict:
    """The assessment world, with a rubric on the default (0-3) scale."""
    world = test_assessment.world.__wrapped__(coordinator, make_pipeline)
    response = coordinator.post(
        f"/api/v1/categories/{world['category']['id']}/rubrics", json={"use_template": True}
    )
    assert response.status_code == 201, response.text
    world["rubric"] = response.json()
    return world


def zero_to_three(system: str, user: str) -> CriterionRating:
    """Rates 2 (Good) with a real citation; mentoring 0 (None) without one."""
    pid, body = next(iter(dict(PASSAGE.findall(user)).items()))
    sentence = body.split("\n\n")[-1][:60]
    if "Advancing women" in user:
        return CriterionRating(
            rating=0,
            rationale="No evidence.",
            supporting=[],
            contradicting=[],
            limitations=None,
            sufficiency="insufficient",
            review_required=False,
            review_reasons=[],
        )
    return CriterionRating(
        rating=2,
        rationale=f"The evidence shows: {sentence}",
        supporting=[Citation(ref=pid, quote=sentence)],
        contradicting=[],
        limitations=None,
        sufficiency="sufficient",
        review_required=False,
        review_reasons=[],
    )


def test_new_rubric_versions_use_the_zero_to_three_scale(world) -> None:
    rubric = world["rubric"]
    assert rubric["scale"] == "zero_to_three"
    assert [(level["rating"], level["label"]) for level in rubric["scale_levels"]] == [
        (0, "None"),
        (1, "Poor"),
        (2, "Good"),
        (3, "Excellent"),
    ]
    assert rating_output(SCALES[RatingScale.ZERO_TO_THREE]) is ZeroToThreeRating
    assert rating_output(SCALES[RatingScale.ONE_TO_FIVE]) is OneToFiveRating


def test_assessment_review_and_ranking_on_zero_to_three(client_for, coordinator, world, engine):
    _, assessor = assess(coordinator, world, engine, zero_to_three)
    system, _ = assessor.calls[0]
    assert "0 = None: no evidence that the criterion is met" in system
    assert "3 = Excellent" in system and "rate 0 and mark sufficiency insufficient" in system
    assert "a rating of 1 or more without a verified supporting citation" in system

    reviewer = client_for("reviewer")
    jane = items_for(reviewer, world, "Jane Doe")
    assert jane["advancing-women"]["rating"] == 0
    assert "uncited_rating" not in jane["advancing-women"]["flags"]  # 0 needs no citation

    url = f"/api/v1/criterion-assessments/{jane['governance-leadership']['id']}/review"
    beyond = reviewer.post(url, json={"decision": "approved", "adjusted_rating": 4, "notes": "x"})
    assert beyond.status_code == 422 and "0 to 3" in beyond.json()["detail"]
    # Adjusting to 0 sticks: 0 is a rating, not "no adjustment".
    lowered = reviewer.post(
        url, json={"decision": "approved", "adjusted_rating": 0, "notes": "Role ended in 2022."}
    )
    assert lowered.status_code == 200, lowered.text
    assert lowered.json()["effective_rating"] == 0
    for code, item in jane.items():
        if code != "governance-leadership":
            reviewer.post(
                f"/api/v1/criterion-assessments/{item['id']}/review", json={"decision": "approved"}
            )

    ranking = coordinator.post(
        "/api/v1/rankings", json={"category_id": world["category"]["id"]}
    ).json()
    assert ranking["scale"] == "zero_to_three"
    entry = next(e for e in ranking["entries"] if e["full_name"] == "Jane Doe")
    # Five criteria: 0 (adjusted), 0 (mentoring) and three at 2 -> 6 / 5 = 1.2, i.e. 40 of 100.
    assert (entry["score_display"], entry["points_display"]) == ("1.20", "40.00")


def test_the_scale_changes_only_on_an_unrated_draft(client_for, coordinator, world, engine):
    rubric = world["rubric"]
    body = {"criteria": rubric["criteria"], "weighting": "equal", "scale": "one_to_five"}
    changed = coordinator.put(f"/api/v1/rubrics/{rubric['id']}", json=body)
    assert changed.status_code == 200 and changed.json()["scale"] == "one_to_five"
    body["scale"] = "zero_to_three"
    assert coordinator.put(f"/api/v1/rubrics/{rubric['id']}", json=body).status_code == 200

    assess(coordinator, world, engine, zero_to_three)
    body["scale"] = "one_to_five"
    refused = coordinator.put(f"/api/v1/rubrics/{rubric['id']}", json=body)
    assert refused.status_code == 409 and "nobody has rated" in refused.json()["detail"]
