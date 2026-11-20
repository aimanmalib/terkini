"""D8: the score formula and the as-of rule give exactly the values in the PRD table."""

from __future__ import annotations

from datetime import date

import pytest

from terkini.claims import Claim, ClaimResult
from terkini.score import ScoreConfig, as_of, load_score_config, round_half_up, score

TODAY = date(2026, 11, 21)
# Frozen weights from PRD D8, so this table checks the formula even if config/score.toml is retuned later.
D8 = ScoreConfig.model_validate({
    "quality": {"base": 0.6, "government": 0.2, "quote": 0.2},
    "scale": {"current": 100, "unverifiable": 50, "outdated": 30},
    "recency": [{"max_days": 30, "r": 1.0}, {"max_days": 365, "r": 0.9}],
    "recency_other": {"older": 0.75, "undated": 0.8},
})


def test_config_file_matches_the_prd_weights():
    assert load_score_config() == D8


@pytest.mark.parametrize("verdict, gov, quote, published, expected", [
    ("current", True, True, date(2026, 11, 1), 100),        # q 1.0, r 1.0 (20 days)
    ("current", True, True, date(2026, 10, 22), 100),       # exactly 30 days -> still r 1.0
    ("current", True, True, date(2026, 10, 21), 90),        # 31 days -> r 0.9
    ("current", False, True, date(2026, 6, 1), 72),         # q 0.8 x r 0.9
    ("current", True, True, date(2025, 11, 21), 90),        # 365 days -> r 0.9
    ("current", True, True, date(2025, 11, 20), 75),        # 366 days -> r 0.75
    ("current", True, True, None, 80),                      # undated -> r 0.8
    ("current", False, False, date(2024, 1, 1), 45),        # q 0.6 x r 0.75
    ("unverifiable", True, False, None, 40),                # 50 x 0.8
    ("unverifiable", False, False, date(2023, 1, 1), 38),   # 50 x 0.75 = 37.5 -> half-up 38
    ("unverifiable", True, True, date(2026, 11, 20), 50),
    ("outdated", True, True, date(2026, 11, 1), 0),         # 30 x (1 - 1.0)
    ("outdated", False, True, None, 6),                     # 30 x (1 - 0.8)
    ("outdated", False, False, None, 12),                   # 30 x (1 - 0.6)
])
def test_d8_table(verdict, gov, quote, published, expected):
    assert score(D8, verdict, government=gov, quote_ok=quote, published=published, checked_on=TODAY) == expected


def test_future_published_date_counts_as_fresh():
    assert score(D8, "current", government=True, quote_ok=True, published=date(2027, 1, 1), checked_on=TODAY) == 100


def test_round_half_up_is_stable():
    assert [round_half_up(x) for x in (0.5, 1.5, 2.5, 37.5, 72.00000000000001)] == [1, 2, 3, 38, 72]


def _result(verdict: str, effective: date | None) -> ClaimResult:
    return ClaimResult(claim=Claim(claim="x", category="wages"), verdict=verdict, effective_date=effective,
                       score=0, checked_on=TODAY)


def test_as_of_needs_a_dated_outdated_claim():
    assert as_of([_result("current", date(2025, 2, 1))]) is None
    assert as_of([_result("outdated", None)]) is None


def test_as_of_is_the_earliest_change_and_flags_mixed_answers():
    est = as_of([_result("outdated", date(2025, 2, 1)), _result("outdated", date(2024, 5, 1)),
                 _result("current", date(2023, 1, 1))])
    assert est.before == date(2024, 5, 1) and not est.mixed
    est = as_of([_result("outdated", date(2024, 5, 1)), _result("current", date(2025, 2, 1))])
    assert est.before == date(2024, 5, 1) and est.mixed
