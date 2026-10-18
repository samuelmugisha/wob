"""Reference tests for the deterministic ranking arithmetic (spec §7.2, §13: 100% agreement)."""

import uuid
from decimal import Decimal

import pytest

from app.services.ranking import (
    CandidateRatings,
    CriterionSpec,
    calculate_score,
    display,
    display_points,
    rank,
)

C = [CriterionSpec(uuid.UUID(int=i), f"c{i}") for i in range(1, 4)]


def ratings(*values):
    return dict(zip([c.id for c in C], values, strict=True))


def candidate(n: int, *values) -> CandidateRatings:
    return CandidateRatings(uuid.UUID(int=100 + n), ratings(*values))


def test_equal_weighting_is_the_mean() -> None:
    assert calculate_score(ratings(4, 3, 5), C, weighted=False) == Decimal(4)
    assert calculate_score(ratings(4, 4, 3), C, weighted=False) == Decimal(11) / Decimal(3)


def test_weighted_scoring() -> None:
    weighted = [
        CriterionSpec(c.id, c.code, Decimal(w)) for c, w in zip(C, ("2", "1", "1"), strict=True)
    ]
    # (2×5 + 1×3 + 1×1) / 4 = 3.5
    assert calculate_score(ratings(5, 3, 1), weighted, weighted=True) == Decimal("3.5")
    with pytest.raises(ValueError, match="positive weight"):
        calculate_score(ratings(5, 3, 1), C, weighted=True)


def test_incomplete_criteria_give_no_score() -> None:
    assert calculate_score(ratings(5, None, 5), C, weighted=False) is None


def test_ratings_outside_the_scale_are_refused() -> None:
    with pytest.raises(ValueError):
        calculate_score(ratings(0, 3, 3), C, weighted=False)
    with pytest.raises(ValueError):
        calculate_score(ratings(6, 3, 3), C, weighted=False)


def test_ranks_ties_and_unscored() -> None:
    entries = rank(
        [
            candidate(1, 3, 3, 3),  # 3.00
            candidate(2, 5, 4, 4),  # 4.33
            candidate(3, 4, 5, 4),  # 4.33 tie
            candidate(4, 5, None, 5),  # incomplete
            candidate(5, 2, 2, 3),  # 2.33
        ],
        C,
        weighted=False,
    )
    summary = [
        (e.finalist_category_id.int - 100, e.rank, e.is_tie, display(e.score)) for e in entries
    ]
    assert summary == [
        (2, 1, True, "4.33"),
        (3, 1, True, "4.33"),
        (1, 3, False, "3.00"),
        (5, 4, False, "2.33"),
        (4, None, False, None),
    ]
    incomplete = entries[-1]
    assert incomplete.missing == ["c2"]
    assert (incomplete.criteria_assessed, incomplete.criteria_total) == (2, 3)


def test_full_precision_decides_rank_not_the_rounded_display() -> None:
    # 11/3 = 3.6667 and 3.67 exactly both display as "3.67" but are not tied.
    hundred = [CriterionSpec(uuid.UUID(int=1000 + i), f"d{i}") for i in range(100)]
    a = candidate(1, 4, 4, 3)
    b = CandidateRatings(
        uuid.UUID(int=2), {c.id: 4 if i < 67 else 3 for i, c in enumerate(hundred)}
    )
    score_a = calculate_score(a.ratings, C, weighted=False)
    score_b = calculate_score(b.ratings, hundred, weighted=False)
    assert display(score_a) == display(score_b) == "3.67"
    assert score_b > score_a


def test_display_rounding_and_points() -> None:
    assert display(Decimal("3.125")) == "3.13"  # half-up, not banker's rounding
    assert display(Decimal(11) / Decimal(3)) == "3.67"
    assert display_points(Decimal(11) / Decimal(3)) == "73.33"
    assert display_points(Decimal(5)) == "100.00"
    assert display(None) is None


def test_ranking_is_reproducible_regardless_of_input_order() -> None:
    pool = [candidate(i, (i % 5) + 1, ((i * 2) % 5) + 1, ((i * 3) % 5) + 1) for i in range(12)]
    first = rank(pool, C, weighted=False)
    second = rank(list(reversed(pool)), C, weighted=False)
    assert [(e.finalist_category_id, e.rank, e.score) for e in first] == [
        (e.finalist_category_id, e.rank, e.score) for e in second
    ]
