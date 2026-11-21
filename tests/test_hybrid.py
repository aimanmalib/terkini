"""Hybrid step (D-022): the model proposes, an official sentence found by code decides. No network."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from conftest import TODAY, FakeGateway, FakeTavily, extract_body, search_body

from terkini.checker import check_claims
from terkini.claims import Claim, ClaimResult, HybridEvidence
from terkini.hybrid import (
    Hybrid,
    combine,
    decide,
    first_value,
    hybrid_query,
    load_hybrid_config,
    prove,
    values_in,
)
from terkini.hybrideval import hybrid_verdicts

NEW_PAGE = ("Minimum Wages Order 2025.\nThe minimum wage for employers with five or more employees is RM1,700 per "
            "month with effect from 1 February 2025.\nOther text.")
OLD_PAGE = "Minimum Wages Order 2022. The minimum wage for employers is RM1,500 per month from 1 May 2022."


@pytest.fixture
def cfg():
    return load_hybrid_config()


@pytest.fixture
def official(pack):
    gov = next(d for d in pack.domains if d.label == "government")
    return f"https://www.{gov.domain}/rules/minimum-wage-2025"


@pytest.fixture
def claim(pack):
    cat = next(c for c in pack.categories if not c.volatile)
    return Claim(claim="The minimum wage for employers in Malaysia is RM1,500 per month.", category=cat.id,
                 entity="employers", value="RM1,500", unit="MYR per month", time_sensitive=True)


def _result(claim, verdict="unverifiable", **over) -> ClaimResult:
    return ClaimResult(claim=claim, verdict=verdict, score=0, checked_on=TODAY, **over)


def _tavily(official, page=NEW_PAGE, published="2025-01-20") -> FakeTavily:
    tv = FakeTavily()
    tv.searches.append(search_body((official, published), ("https://blog.example.com/wage", None)))
    tv.extracts.append(extract_body({official: page}))
    return tv


def test_values_compare_written_forms(cfg):
    got = {v for _, v, _ in values_in("RM1 million, RM 1,000,000.00, 8 per cent, 1 Jun 2026, 01.06.2026", cfg.months)}
    assert got == {("money", Decimal(10**6)), ("pct", Decimal(8)), ("date", date(2026, 6, 1))}
    assert first_value("RM1,700 per month since 2025", cfg.months)[1] == "RM1,700"
    assert first_value("No such scheme exists.", cfg.months) is None


def test_query_puts_the_proposed_value_in_the_claim(claim):
    assert hybrid_query(claim, "RM1,700", 380) == "The minimum wage for employers in Malaysia is RM1,700 per month."


def test_proposal_quoted_on_official_page_turns_unverifiable_into_outdated(make_verifier, official, claim, cfg):
    tv = _tavily(official)
    v = make_verifier(tv, FakeGateway())
    ev = prove(v, claim, "RM1,700 MYR per month", cfg)
    assert ev.quote.startswith("The minimum wage for employers with five or more employees is RM1,700")
    assert ev.source_url == official and ev.page_date == date(2025, 2, 1) and not ev.date_estimated
    search = tv.calls[0][1]
    assert search["include_domains_mode"] == "restrict" and "RM1,700" in search["query"]
    assert len(tv.calls[1][1]["urls"]) == 1  # only official pages are extracted
    out = combine(_result(claim), ev, v)
    assert out.verdict == "outdated" and out.quote_ok and out.current_value == "RM1,700"
    assert out.evidence_quote == ev.quote and out.hybrid.previous_verdict == "unverifiable"
    assert out.credits == ev.credits == 2


def test_proposal_without_a_quote_keeps_the_main_verdict(make_verifier, official, claim, cfg):
    tv = _tavily(official, page="Wages are reviewed every two years. See the order for RM1,700 details.")
    v = make_verifier(tv, FakeGateway())
    ev = prove(v, claim, "RM1,700", cfg)
    assert ev.quote == "" and ev.urls == [official]
    out = combine(_result(claim), ev, v)
    assert out.verdict == "unverifiable" and out.hybrid.decision.startswith("No official sentence")


def test_proposal_equal_to_the_claim_spends_nothing(make_verifier, claim, cfg):
    tv = FakeTavily()
    ev = prove(make_verifier(tv, FakeGateway()), claim, "RM 1,500 per month", cfg)
    assert tv.calls == [] and ev.quote == "" and "own value" in ev.decision


def test_newer_page_wins_over_older_page(claim):
    old = _result(claim, "current", quote_ok=True, evidence_quote="RM1,500 per month from 1 May 2022",
                  effective_date=date(2022, 5, 1))
    newer = HybridEvidence(proposed_value="RM1,700", quote="… RM1,700 …", page_date=date(2025, 2, 1))
    assert decide(old, newer)[0] == "outdated"
    older = newer.model_copy(update={"page_date": date(2020, 1, 1)})
    assert decide(old, older)[0] == "current"
    undated = newer.model_copy(update={"page_date": None})
    assert decide(old, undated)[0] == "current"


def test_outdated_result_keeps_both_quotes_and_dates(make_verifier, official, claim, cfg):
    v = make_verifier(_tavily(official), FakeGateway())
    old = _result(claim, "current", quote_ok=True, evidence_quote="RM1,500 per month from 1 May 2022",
                  source_url="https://www.mohr.gov.my/old", effective_date=date(2022, 5, 1))
    out = combine(old, prove(v, claim, "RM1,700", cfg), v)
    assert out.verdict == "outdated"
    assert (out.effective_date, out.hybrid.previous_date) == (date(2025, 2, 1), date(2022, 5, 1))
    assert out.hybrid.previous_quote == "RM1,500 per month from 1 May 2022" and out.evidence_quote != ""


def test_model_guess_current_changes_nothing(make_verifier, claim):
    tv = FakeTavily()
    v = make_verifier(tv, FakeGateway({"verdict": "current", "current_value": "RM1,500"}))
    r = _result(claim)
    assert Hybrid(v, load_hybrid_config()).apply(r) is r and tv.calls == []


def test_checker_runs_the_hybrid_step_after_the_main_check(make_verifier, official, claim, cache):
    tv = FakeTavily()
    tv.searches.append(search_body((official, "2025-01-20")))  # main check
    tv.extracts.append(extract_body({official: OLD_PAGE}))
    tv.searches.append(search_body((official, "2025-01-20")))  # hybrid search
    tv.extracts.append(extract_body({official: NEW_PAGE}))
    unsettled = {"verdict": "unverifiable", "current_value": "", "evidence_quote": "", "effective_date_text": "",
                 "effective_date": "", "source_url": ""}
    gw = FakeGateway(unsettled, {"verdict": "outdated", "current_value": "RM1,700 per month"})
    v = make_verifier(tv, gw)
    report = check_claims([claim], v, cache, hybrid=Hybrid(v, load_hybrid_config()))
    (r,) = report.results
    assert r.verdict == "outdated" and report.outdated == 1 and report.credits == 4
    assert "no documents" in gw.calls[1]["messages"][0]["content"].lower()


def test_eval_verdicts_from_saved_evidence(claim):
    class Run:
        answer = "my-01--m"

        class report:
            results = (_result(claim),)
    mo = {"verdicts": {"my-01--m#0": {"verdict": "outdated", "current_value": "RM1,700"}}}
    ev = HybridEvidence(proposed_value="RM1,700", query="q", quote="x RM1,700", page_date=date(2025, 2, 1))
    saved = {"evidence": {f"{claim.key} => RM1,700": json.loads(ev.model_dump_json())}, "credits_from_responses": 2}
    verdicts, counts = hybrid_verdicts([Run], mo, saved)
    assert verdicts == {"my-01--m#0": "outdated"} and counts["changed_to_outdated"] == 1
    assert hybrid_verdicts([Run], mo, {"evidence": {}})[0] == {"my-01--m#0": "unverifiable"}


def test_old_side_of_a_change_is_not_proof(cfg):
    from terkini.hybrid import states_value
    target = ("money", Decimal(1700))
    assert states_value("The minimum wage rose from RM1,700 to RM2,000 per month.", target, cfg) is None
    assert states_value("Gaji minimum dinaikkan daripada RM1,700 kepada RM2,000.", target, cfg) is None
    assert states_value("The minimum wage rose from RM1,500 to RM1,700 per month.", target, cfg) is not None


def test_proposal_must_be_of_the_claims_kind(make_verifier, claim, cfg):
    tv = FakeTavily()
    ev = prove(make_verifier(tv, FakeGateway()), claim, "Since 1 October 2025 the rule applies to all", cfg)
    assert tv.calls == [] and ev.quote == "" and "kind" in ev.decision
