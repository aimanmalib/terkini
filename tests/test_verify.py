"""Verifier: search parameters (D5, D6), 434 retry, exact-quote check (D7) and scoring. No network."""

from __future__ import annotations

from datetime import date

import pytest

from conftest import FakeGateway, FakeTavily, extract_body, search_body
from terkini.claims import Claim
from terkini.verify import build_query, parse_day

PAGE = ("Minimum Wages Order 2025.\n  The minimum wage   is RM1,700 per month with effect from 1 February 2025 "
        "for employers with five or more employees.")
QUOTE = "The minimum wage is RM1,700 per month with effect from 1 February 2025"


@pytest.fixture
def official(pack):
    gov = next(d for d in pack.domains if d.label == "government")
    return f"https://www.{gov.domain}/rules/minimum-wage"


@pytest.fixture
def volatile_claim(pack):
    cat = next(c for c in pack.categories if c.volatile)
    return Claim(claim="The minimum wage in Malaysia is RM1,500 per month.", category=cat.id, value="RM1,500",
                 time_sensitive=True)


def _judgement(url: str, **over) -> dict:
    j = {"verdict": "outdated", "current_value": "RM1,700", "evidence_quote": QUOTE,
         "effective_date_text": "1 February 2025", "effective_date": "2025-02-01", "source_url": url}
    return {**j, **over}


def _run(make_verifier, official, claim, judgement, published="2025-01-20"):
    tv = FakeTavily()
    tv.searches.append(search_body((official, published), ("https://blog.example.com/wage", None)))
    tv.extracts.append(extract_body({official: PAGE}))
    gw = FakeGateway(judgement)
    return make_verifier(tv, gw).verify(claim), tv, gw


def test_search_uses_pack_domains_restrict_and_live_results(make_verifier, official, volatile_claim, pack):
    res, tv, gw = _run(make_verifier, official, volatile_claim, _judgement(official))
    path, body = tv.calls[0]
    assert path == "search"
    assert body["include_domains"] == pack.domain_names
    assert body["include_domains_mode"] == "restrict"
    assert body["search_depth"] == "basic" and body["max_results"] == 5 and body["topic"] == "general"
    assert body["max_age_hours"] == 0 and body["include_published_date"] is True and body["include_usage"] is True
    assert tv.calls[1] == ("extract", {"urls": [official], "include_usage": True})
    assert gw.calls[0]["json_mode"] is True and gw.calls[0]["model"] == "judge/model"


def test_outdated_claim_with_real_quote(make_verifier, official, volatile_claim):
    res, _, _ = _run(make_verifier, official, volatile_claim, _judgement(official))
    assert res.verdict == "outdated" and res.quote_ok
    assert res.effective_date == date(2025, 2, 1)
    assert res.source_label == "government" and res.current_value == "RM1,700"
    assert res.score == 0  # 30 x (1 - 1.0)
    assert res.credits == 2  # one search, one extract, as reported by Tavily
    assert [h.url for h in res.context] == ["https://blog.example.com/wage"]  # shown, never decides (D5)


def test_invented_quote_is_unverifiable(make_verifier, official, volatile_claim):
    res, _, _ = _run(make_verifier, official, volatile_claim,
                     _judgement(official, evidence_quote="The minimum wage is RM1,800 per month"))
    assert res.verdict == "unverifiable" and not res.quote_ok
    assert res.evidence_quote == "" and res.current_value == "" and res.effective_date is None
    assert "not on the official page" in res.reason


def test_quote_from_a_page_that_was_not_extracted_is_unverifiable(make_verifier, official, volatile_claim):
    res, _, _ = _run(make_verifier, official, volatile_claim, _judgement("https://blog.example.com/wage"))
    assert res.verdict == "unverifiable" and res.source_url == ""


def test_judge_without_a_source_is_unsettled_not_a_wrong_page(make_verifier, official, volatile_claim):
    # Regression: an "unverifiable" judgement with no source URL was reported as citing an unextracted page.
    res, _, _ = _run(make_verifier, official, volatile_claim,
                     _judgement("", verdict="unverifiable", evidence_quote="", effective_date_text="", effective_date=""))
    assert res.verdict == "unverifiable" and res.reason == "The official pages do not settle this claim."
    res, _, _ = _run(make_verifier, official, volatile_claim, _judgement(""))
    assert res.verdict == "unverifiable" and res.reason == "The judge gave no source page for its verdict."


def test_effective_date_must_appear_in_the_quote(make_verifier, official, volatile_claim):
    res, _, _ = _run(make_verifier, official, volatile_claim,
                     _judgement(official, effective_date_text="1 March 2025", effective_date="2025-03-01"))
    assert res.verdict == "unverifiable" and res.effective_date is None
    assert "effective date" in res.reason


def test_current_claim_score_uses_source_age(make_verifier, official, volatile_claim):
    res, _, _ = _run(make_verifier, official, volatile_claim,
                     _judgement(official, verdict="current", effective_date_text="", effective_date=""),
                     published="2026-11-10")
    assert res.verdict == "current" and res.effective_date is None
    assert res.source_published_date == date(2026, 11, 10) and res.score == 100


def test_capacity_error_retries_once_from_cache(make_verifier, official, volatile_claim):
    tv = FakeTavily()
    tv.searches += [434, search_body((official, None))]
    tv.extracts.append(extract_body({official: PAGE}))
    res = make_verifier(tv, FakeGateway(_judgement(official))).verify(volatile_claim)
    assert [c[0] for c in tv.calls] == ["search", "search", "extract"]
    assert "max_age_hours" in tv.calls[0][1] and "max_age_hours" not in tv.calls[1][1]
    assert res.cached_copy and res.verdict == "outdated"


def test_non_volatile_category_does_not_ask_for_live_results(make_verifier, official, pack):
    cat = next(c for c in pack.categories if not c.volatile)
    claim = Claim(claim="Annual leave is 8 days.", category=cat.id, time_sensitive=True)
    _, tv, _ = _run(make_verifier, official, claim, _judgement(official, verdict="current"))
    assert "max_age_hours" not in tv.calls[0][1]


def test_no_official_page_retries_advanced_then_gives_up(make_verifier, volatile_claim):
    tv = FakeTavily()
    tv.searches += [search_body(credits=1), search_body(("https://blog.example.com/x", None), credits=2)]
    gw = FakeGateway()
    res = make_verifier(tv, gw).verify(volatile_claim)
    assert [c[1]["search_depth"] for c in tv.calls] == ["basic", "advanced"]
    assert res.verdict == "unverifiable" and res.score == 40 and res.credits == 3
    assert gw.calls == []  # no judge call without an official page


def test_unreadable_judge_answer_is_unverifiable(make_verifier, official, volatile_claim):
    res, _, _ = _run(make_verifier, official, volatile_claim, "sorry, I cannot help")
    assert res.verdict == "unverifiable" and "could not be read" in res.reason


def test_build_query_cuts_at_a_word():
    c = Claim(claim="word " * 200, category="x")
    q = build_query(c, 380)
    assert len(q) <= 380 and not q.endswith(" ") and q.endswith("word")


@pytest.mark.parametrize("raw, expected", [
    ("2025-02-01", date(2025, 2, 1)),
    ("2025-02-01T00:00:00Z", date(2025, 2, 1)),
    ("Sat, 01 Feb 2025 08:00:00 GMT", date(2025, 2, 1)),
    ("1 February 2025", date(2025, 2, 1)),
    ("soon", None),
    (None, None),
])
def test_parse_day(raw, expected):
    assert parse_day(raw) == expected


def test_http_and_https_copies_are_extracted_once(make_verifier, official, volatile_claim):
    tv = FakeTavily()
    http = official.replace("https://", "http://")
    tv.searches.append(search_body((http, None), (official + "/", None)))
    tv.extracts.append(extract_body({official + "/": PAGE}))
    make_verifier(tv, FakeGateway(_judgement(official + "/"))).verify(volatile_claim)
    assert tv.calls[1] == ("extract", {"urls": [official + "/"], "include_usage": True})


def _refused_extract(official: str) -> tuple[FakeTavily, dict]:
    tv = FakeTavily()
    body = search_body((official, None))
    body["results"][0]["content"] = f"News. {QUOTE} More."
    tv.searches.append(body)
    tv.extracts.append({"results": [], "failed_results": [{"url": official}], "usage": {"credits": 0}})
    return tv, body


def test_refused_extract_is_judged_on_the_official_snippet(make_verifier, official, volatile_claim):
    tv, _ = _refused_extract(official)
    gw = FakeGateway(_judgement(official))
    res = make_verifier(tv, gw).verify(volatile_claim)
    assert res.verdict == "outdated" and res.quote_ok and res.snippet_only
    assert QUOTE in gw.calls[0]["messages"][1]["content"]


def test_snippet_quote_still_has_to_match(make_verifier, official, volatile_claim):
    tv, _ = _refused_extract(official)
    res = make_verifier(tv, FakeGateway(_judgement(official, evidence_quote="RM1,800 per month"))).verify(volatile_claim)
    assert res.verdict == "unverifiable" and not res.quote_ok
