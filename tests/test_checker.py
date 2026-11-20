"""Extractor, de-duplication, cache and the credit guard (D11). No network."""

from __future__ import annotations

import pytest

from conftest import TODAY, FakeGateway, FakeTavily, extract_body, search_body
from terkini.budget import load_budget
from terkini.cache import Cache
from terkini.checker import check_answer, check_claims
from terkini.claims import Claim
from terkini.credits import CreditGuard, CreditLimitReached
from terkini.extractor import ModelOutputError, extract_claims, parse_json_object

PAGE = "The minimum wage is RM1,700 per month."


@pytest.fixture
def official(pack):
    return f"https://{pack.domains[0].domain}/a"


@pytest.fixture
def cat(pack):
    return next(c for c in pack.categories if c.volatile).id


def _budget(per_run: int, per_day: int):
    b = load_budget()
    return b.model_copy(update={"limits": b.limits.model_copy(update={"per_run": per_run, "per_day": per_day})})


def _queue_one_claim(tv: FakeTavily, official: str) -> dict:
    tv.searches.append(search_body((official, None)))
    tv.extracts.append(extract_body({official: PAGE}))
    return {"verdict": "current", "evidence_quote": PAGE, "source_url": official}


def test_parse_json_object_tolerates_fences_and_text():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Here you go: {"a": [1]} done') == {"a": [1]}
    with pytest.raises(ModelOutputError):
        parse_json_object("no json here")
    with pytest.raises(ModelOutputError):
        parse_json_object("[1, 2]")


def test_extractor_keeps_time_sensitive_pack_claims_once(pack, cat):
    gw = FakeGateway({"claims": [
        {"claim": "The minimum wage is RM1,500.", "category": cat, "value": 1500, "time_sensitive": True},
        {"claim": "the minimum wage is  RM1,500", "category": cat, "time_sensitive": True},  # duplicate
        {"claim": "Malaysia has 13 states.", "category": "other", "time_sensitive": False},
        {"claim": "Some tax", "category": "not-a-pack-category", "time_sensitive": True},
        {"claim": "", "category": cat, "time_sensitive": True},  # malformed, dropped
        "not an object",
    ]})
    ex = extract_claims(gw, "ex/model", pack, "answer text", question="What is the minimum wage?")
    assert [c.claim for c in ex.claims] == ["The minimum wage is RM1,500."]
    assert ex.claims[0].value == "1500"
    assert len(ex.skipped) == 2
    system = gw.calls[0]["messages"][0]["content"]
    assert all(f'"{c.id}"' in system for c in pack.categories) and pack.name in system


def test_extractor_rejects_answer_without_claims_list(pack):
    with pytest.raises(ModelOutputError):
        extract_claims(FakeGateway({"facts": []}), "ex/model", pack, "x")


def test_guard_refuses_before_crossing_run_or_day_limit(cache):
    g = CreditGuard(_budget(per_run=3, per_day=5), cache, TODAY)
    g.allow(g.search_cost("advanced"))
    g.record(2)
    with pytest.raises(CreditLimitReached, match="run limit"):
        g.allow(g.search_cost("advanced"))
    cache.add_spent(TODAY, 3)  # another run earlier today
    g2 = CreditGuard(_budget(per_run=3, per_day=5), cache, TODAY)
    with pytest.raises(CreditLimitReached, match="daily limit"):
        g2.allow(1)
    assert g.extract_cost(1) == 1 and g.extract_cost(6) == 2


def test_run_stops_cleanly_at_the_credit_limit(make_verifier, official, cat):
    tv, gw = FakeTavily(), FakeGateway()
    gw.answers.append(_queue_one_claim(tv, official))
    claims = [Claim(claim=f"Rule {i} is RM{i}.", category=cat, time_sensitive=True) for i in range(3)]
    report = check_claims(claims, make_verifier(tv, gw, budget=_budget(per_run=2, per_day=10)), Cache(":memory:"))
    assert len(report.results) == 1 and report.credits == 2
    assert [c.claim for c in report.not_checked] == ["Rule 1 is RM1.", "Rule 2 is RM2."]
    assert "run limit" in report.stopped
    assert len(tv.calls) == 2  # the refused search was never sent


def test_same_claim_is_searched_once_and_cached(make_verifier, official, cat, cache):
    tv, gw = FakeTavily(), FakeGateway()
    gw.answers.append(_queue_one_claim(tv, official))
    a = Claim(claim="The minimum wage is RM1,700.", category=cat, time_sensitive=True)
    b = Claim(claim="the minimum wage is RM1,700", category=cat, time_sensitive=True)
    report = check_claims([a, b], make_verifier(tv, gw), cache)
    assert [r.credits for r in report.results] == [2, 0] and len(tv.calls) == 2
    again = check_claims([b], make_verifier(tv, gw), cache)  # a later run on the same day: no Tavily call
    assert again.results[0].verdict == "current" and len(tv.calls) == 2 and again.credits == 0
    assert cache.spent_on(TODAY) == 2


def test_tavily_error_is_reported_and_not_cached(make_verifier, official, cat, cache):
    tv = FakeTavily()
    tv.searches.append(500)
    claim = Claim(claim="X is RM1.", category=cat, time_sensitive=True)
    report = check_claims([claim], make_verifier(tv, FakeGateway()), cache)
    assert report.results == [] and "HTTP 500" in report.errors[0].error
    assert cache.get(claim.key, "my", TODAY) is None


def test_check_answer_end_to_end_with_as_of(make_verifier, official, cat, cache):
    tv = FakeTavily()
    tv.searches.append(search_body((official, "2025-01-20")))
    tv.extracts.append(extract_body({official: "From 1 February 2025 the minimum wage is RM1,700 per month."}))
    gw = FakeGateway(
        {"claims": [{"claim": "The minimum wage is RM1,500 per month.", "category": cat, "time_sensitive": True},
                    {"claim": "Malaysia uses the ringgit.", "category": cat, "time_sensitive": False}]},
        {"verdict": "outdated", "current_value": "RM1,700", "source_url": official,
         "evidence_quote": "From 1 February 2025 the minimum wage is RM1,700 per month.",
         "effective_date_text": "1 February 2025", "effective_date": "2025-02-01"},
    )
    report = check_answer("The minimum wage is RM1,500.", gateway=gw, extractor_model="ex/model",
                          verifier=make_verifier(tv, gw), cache=cache)
    assert report.outdated == 1 and report.skipped == 1
    assert report.as_of_before.isoformat() == "2025-02-01" and not report.as_of_mixed
