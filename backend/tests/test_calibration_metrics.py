"""Reference tests for calibration statistics (values worked out by hand)."""

import pytest

from app.services.calibration_metrics import (
    Thresholds,
    agreement,
    pair_stats,
    quadratic_weighted_kappa,
    verdict,
)


def test_qwk_reference_values() -> None:
    assert quadratic_weighted_kappa([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == pytest.approx(1.0)
    # Fully reversed on 1-3: observed weighted disagreement 1/6, chance-expected 1/12.
    assert quadratic_weighted_kappa([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    # One rater constant: agreement is exactly chance level.
    assert quadratic_weighted_kappa([3, 3, 3], [1, 2, 3]) == pytest.approx(0.0)
    # Both constant: no chance-expected disagreement, so kappa is undefined.
    assert quadratic_weighted_kappa([3, 3, 3], [3, 3, 3]) is None
    assert quadratic_weighted_kappa([3], [3]) is None
    # Off by one everywhere: observed weighted disagreement 1/16, chance-expected 56/256,
    # so kappa = 1 - 0.0625 / 0.21875 = 5/7.
    assert quadratic_weighted_kappa([1, 2, 3, 4], [2, 3, 4, 5]) == pytest.approx(5 / 7)


def test_pair_stats() -> None:
    stats = pair_stats([3, 4, 5, 2], [3, 3, 3, 2])
    assert (stats.n, stats.exact, stats.within_one) == (4, 0.5, 0.75)


def test_agreement_against_several_humans() -> None:
    ai = [4, 4, 3, 2]
    humans = {"r1": [4, 3, 3, 2], "r2": [3, 3, None, 2]}
    result = agreement(ai, humans)
    assert result.rated_items == 4
    assert result.pairs == {"ai_vs_human": 2, "human_vs_human": 1}
    # AI minus human mean per item: 0.5, 1, 0, 0
    assert result.bias == pytest.approx(0.375)
    assert result.mean_absolute_error == pytest.approx(0.375)
    assert result.ai_vs_human["within_one"] == pytest.approx(1.0)


def test_verdicts() -> None:
    perfect = agreement([1, 2, 3, 4, 5] * 5, {"r1": [1, 2, 3, 4, 5] * 5, "r2": [1, 2, 3, 4, 5] * 5})
    assert verdict(perfect, {}, Thresholds()) == ("passed", [])

    generous = agreement([5, 5, 5, 4, 5] * 5, {"r1": [3, 2, 3, 2, 3] * 5})
    outcome, reasons = verdict(generous, {"Impact": generous}, Thresholds())
    assert outcome == "failed"
    assert any("rates" in r and "higher" in r for r in reasons)
    assert any("no human-human baseline" in r for r in reasons)

    small = agreement([3, 4], {"r1": [3, 4]})
    assert verdict(small, {}, Thresholds())[0] == "inconclusive"
