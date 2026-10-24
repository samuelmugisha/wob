"""Estimated AI spend per step, for administrators."""

import pytest

from app.services.ai_costs import price_key
from tests import test_research
from tests.test_research import run_research

world = test_research.world
_empty_queues = test_research._empty_queues
_research_on = test_research._research_on


@pytest.mark.parametrize(
    ("recorded", "key"),
    [
        ("claude-opus-5-5", "claude-opus-5-5"),
        ("anthropic:claude-haiku-5-5", "claude-haiku-5-5"),
        ("anthropic/claude-sonnet-5.5", "claude-sonnet-5-5"),
        ("claude-opus-5-5-20261001", "claude-opus-5-5"),
        ("fake", None),
        (None, None),
    ],
)
def test_recorded_model_names_find_their_price(recorded, key) -> None:
    assert price_key(recorded) == key


def test_costs_per_step(client_for, world) -> None:
    run_research(world)  # 9,000 in / 1,200 out on Claude Opus 5.5, 4 searches, 2 pages
    admin = client_for("admin")
    url = f"/api/v1/admin/ai-costs?days=30&category_id={world['category']['id']}"
    assert world["reviewer"].get(url).status_code == 403

    body = admin.get(url).json()
    steps = {s["key"]: s for s in body["steps"]}
    assert steps["research"]["cost_usd"] == pytest.approx(9000 * 4e-6 + 1200 * 20e-6)
    assert steps["research"]["detail"] == "1 run, 2 pages read"
    assert steps["web_search"]["detail"] == "4 searches"
    assert steps["web_search"]["cost_usd"] == pytest.approx(0.04)
    assert steps["web_fetch"]["cost_usd"] == 0
    assert steps["claims"]["input_tokens"] > 0  # the test model has no price
    assert any("No price is known for fake" in n for n in body["notes"])
    assert body["total_usd"] == pytest.approx(sum(s["cost_usd"] for s in body["steps"]))
