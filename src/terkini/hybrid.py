"""Hybrid check (D-022): the model proposes a current value, an official page has to prove it.

For a claim the main check did not flag, the judge model guesses, without pages, whether a newer value applies
(config/prompts.toml [judge_no_evidence]). When it proposes one, Terkini runs one Tavily Search on the pack's official
domains for that value and extracts the top official pages. Code, not the model, then looks for a sentence on those
pages that states the proposed value and shares words with the claim. The verdict changes to "outdated" only then:

- main check unverifiable + proposed value quoted on an official page -> outdated;
- main check current (with its own quote) -> outdated only when the new page carries a later date than the old one;
- anything else -> the main check's verdict stays. A model guess alone never decides a verdict.
"""

from __future__ import annotations

import re
import tomllib
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import BaseModel

from terkini.claims import Claim, ClaimResult, HybridEvidence
from terkini.judge import Page
from terkini.packs import REPO_ROOT
from terkini.quotes import quote_in_text
from terkini.score import score
from terkini.verify import build_query, distinct_pages, parse_day


class HybridEvalConfig(BaseModel):
    max_credits: int
    workers: int
    results: str


class HybridConfig(BaseModel):
    enabled: bool
    search_depth: str
    max_urls: int
    min_shared_words: int
    min_word_chars: int
    date_window_chars: int
    max_quote_chars: int
    eval: HybridEvalConfig
    stop_words: frozenset[str]
    months: dict[str, int]


def load_hybrid_config(root: Path = REPO_ROOT) -> HybridConfig:
    with open(root / "config" / "hybrid.toml", "rb") as f:
        raw = tomllib.load(f)
    return HybridConfig(**{k: v for k, v in raw.items() if k not in ("words", "months")},
                        stop_words=frozenset(raw["words"]["stop"]), months=raw["months"])


# --- Values: money, percent, date ---------------------------------------------------------------------------------

_SCALE = {"million": 10**6, "juta": 10**6, "mil": 10**6, "billion": 10**9, "bilion": 10**9}
_MONEY = re.compile(r"(?:RM|MYR)\s?(\d[\d,]*(?:\.\d+)?)(?:\s?(million|billion|juta|bilion|mil)\b)?", re.IGNORECASE)
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s?(?:%|per\s?cent\b|peratus\b)", re.IGNORECASE)
_DMY_NAME = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\.?,?\s+(\d{4})\b")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY_NUM = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")

Value = tuple[str, object]  # ("money", Decimal) | ("pct", Decimal) | ("date", date)


def _dec(s: str) -> Decimal | None:
    try:
        return Decimal(s.replace(",", "")).normalize()
    except InvalidOperation:
        return None


def dates_in(text: str, months: dict[str, int]) -> list[tuple[int, date]]:
    """Every date written in the text, with its position: '1 June 2026', '1 Jun 2026', '2026-06-01', '01.06.2026'."""
    out = []
    for m in _DMY_NAME.finditer(text):
        mon = months.get(m.group(2).casefold())
        if mon:
            try:
                out.append((m.start(), date(int(m.group(3)), mon, int(m.group(1)))))
            except ValueError:
                pass
    for m in _ISO.finditer(text):
        d = parse_day(m.group(0))
        if d:
            out.append((m.start(), d))
    for m in _DMY_NUM.finditer(text):
        try:
            out.append((m.start(), date(int(m.group(3)), int(m.group(2)), int(m.group(1)))))
        except ValueError:
            pass
    return out


def values_in(text: str, months: dict[str, int]) -> list[tuple[int, Value, str]]:
    """Money amounts, percentages and dates in the text, in order: (position, comparable value, text as written)."""
    out: list[tuple[int, Value, str]] = []
    for m in _MONEY.finditer(text):
        n = _dec(m.group(1))
        if n is not None:
            out.append((m.start(), ("money", (n * _SCALE.get((m.group(2) or "").casefold(), 1)).normalize()), m.group(0)))
    for m in _PCT.finditer(text):
        n = _dec(m.group(1))
        if n is not None:
            out.append((m.start(), ("pct", n), m.group(0)))
    out += [(pos, ("date", d), text[pos:pos + 20]) for pos, d in dates_in(text, months)]
    return sorted(out, key=lambda x: x[0])


def first_value(text: str, months: dict[str, int]) -> tuple[Value, str] | None:
    """The first money amount, percentage or date in the model's proposal, or None when it has none."""
    found = values_in(text, months)
    return (found[0][1], found[0][2].strip()) if found else None


# --- Finding the quote ----------------------------------------------------------------------------------------------

_WORD = re.compile(r"[A-Za-z]+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])|\n+")


def words(text: str, cfg: HybridConfig) -> set[str]:
    return {w for w in (x.casefold() for x in _WORD.findall(text))
            if len(w) >= cfg.min_word_chars and w not in cfg.stop_words}


def _sentences(text: str):
    start = 0
    for m in _SENTENCE.finditer(text):
        yield start, text[start:m.start()]
        start = m.end()
    yield start, text[start:]


def find_quote(pages: list[Page], target: Value, claim_words: set[str], cfg: HybridConfig
               ) -> tuple[Page, str, int] | None:
    """Best sentence on the pages that states the target value and shares the most words with the claim."""
    best = None
    for page in pages:
        for pos, sent in _sentences(page.text):
            hit = next((p for p, v, _ in values_in(sent, cfg.months) if v == target), None)
            if hit is None:
                continue
            shared = len(words(sent, cfg) & claim_words)
            if shared < cfg.min_shared_words or (best and shared <= best[0]):
                continue
            quote = sent.strip()
            if len(quote) > cfg.max_quote_chars:
                half = cfg.max_quote_chars // 2
                lo = max(0, hit - half)
                quote = sent[lo:lo + cfg.max_quote_chars].strip()
            best = (shared, page, quote, pos)
    return best[1:] if best else None


def page_date(page: Page, quote: str, pos: int, cfg: HybridConfig, today: date) -> tuple[date | None, bool]:
    """Latest date (not after today) in the quote, else near it; else Tavily's published date, marked estimated."""
    near = page.text[max(0, pos - cfg.date_window_chars): pos + len(quote) + cfg.date_window_chars]
    for span in (quote, near):
        found = [d for _, d in dates_in(span, cfg.months) if d <= today]
        if found:
            return max(found), False
    published = parse_day(page.published)
    return published, published is not None


# --- The search for one proposed value ------------------------------------------------------------------------------

def hybrid_query(claim: Claim, proposed_text: str, max_chars: int) -> str:
    """The claim sentence with its value replaced by the proposed one (or the proposed value appended)."""
    text = claim.claim.replace(claim.value, proposed_text) if claim.value and claim.value in claim.claim \
        else f"{claim.claim} {proposed_text}"
    return build_query(claim.model_copy(update={"claim": text}), max_chars)


def prove(verifier, claim: Claim, proposal: str, cfg: HybridConfig) -> HybridEvidence:
    """One Tavily Search + one Extract for the proposed value; the quote is found by code. Spends no credit when the
    proposal has no value or repeats the claim's value."""
    ev = HybridEvidence(proposed_value=proposal)
    got = first_value(proposal, cfg.months)
    if got is None:
        return ev.model_copy(update={"decision": "The model's proposal has no amount, rate or date to look for."})
    target, text = got
    if target in {v for _, v, _ in values_in(f"{claim.value} {claim.claim}", cfg.months)}:
        return ev.model_copy(update={"proposed_value": text, "decision": "The model proposed the claim's own value."})
    category = verifier.pack.category(claim.category)
    query = hybrid_query(claim, text, verifier.cfg.search.max_query_chars)
    hits, _cached, credits = verifier._search(query, cfg.search_depth, bool(category and category.volatile))
    official = distinct_pages([h for h in hits if h.official])[: cfg.max_urls]
    ev = ev.model_copy(update={"proposed_value": text, "query": query, "urls": [h.url for h in official]})
    if not official:
        return ev.model_copy(update={"credits": credits, "decision": "No official page found for the proposed value."})
    pages, more = verifier._extract(official, cfg.max_urls)
    credits += more
    if not pages:  # D-014: the site refused the extract; look in the Search snippets instead
        pages = [Page(url=h.url, text=h.content, published=h.published_date) for h in official if h.content]
    published = {h.url: h.published_date for h in official}
    pages = [Page(url=p.url, text=p.text, published=p.published or published.get(p.url)) for p in pages]
    found = find_quote(pages, target, words(f"{claim.claim} {claim.entity}", cfg), cfg)
    if found is None or not quote_in_text(found[1], found[0].text):
        return ev.model_copy(update={"credits": credits,
                                     "decision": "No official sentence states the proposed value for this rule."})
    page, quote, pos = found
    day, estimated = page_date(page, quote, pos, cfg, verifier.today)
    return ev.model_copy(update={"credits": credits, "quote": quote, "source_url": page.url, "page_date": day,
                                 "date_estimated": estimated})


# --- The decision (deterministic) -------------------------------------------------------------------------------------

def decide(result: ClaimResult, ev: HybridEvidence | None) -> tuple[str, str]:
    """(verdict, reason). Only a quoted official sentence can turn a claim outdated; for a claim the main check found
    current with its own quote, the page with the later date wins and an undated side keeps the main verdict."""
    if ev is None or not ev.quote or result.verdict == "outdated":
        return result.verdict, ev.decision if ev else ""
    if result.verdict == "current" and result.quote_ok:
        old = result.effective_date or result.source_published_date
        if old is None or ev.page_date is None:
            return "current", "An official page states the proposed value, but one of the two pages has no date."
        if ev.page_date <= old:
            return "current", f"The page with the claim's value ({old}) is not older than the other ({ev.page_date})."
        return "outdated", f"A later official page ({ev.page_date}) states {ev.proposed_value}; the claim's page is {old}."
    return "outdated", f"An official page states {ev.proposed_value}, not {result.claim.value or 'the claimed value'}."


def combine(result: ClaimResult, ev: HybridEvidence, verifier) -> ClaimResult:
    """The claim result after the hybrid step: the main fields show the evidence that decided the verdict."""
    verdict, reason = decide(result, ev)
    ev = ev.model_copy(update={"decision": reason, "previous_verdict": result.verdict,
                               "previous_quote": result.evidence_quote, "previous_url": result.source_url,
                               "previous_date": result.effective_date or result.source_published_date})
    credits = result.credits + ev.credits
    if verdict == result.verdict:
        return result.model_copy(update={"hybrid": ev, "credits": credits})
    domain = verifier.pack.domain_for(ev.source_url)
    return result.model_copy(update={
        "verdict": verdict, "current_value": ev.proposed_value, "evidence_quote": ev.quote,
        "effective_date": None if ev.date_estimated else ev.page_date, "source_url": ev.source_url,
        "source_published_date": ev.page_date, "source_label": domain.label if domain else "", "quote_ok": True,
        "snippet_only": False, "reason": "", "hybrid": ev, "credits": credits,
        "score": score(verifier.score_cfg, verdict, government=bool(domain and domain.label == "government"),
                       quote_ok=True, published=ev.page_date, checked_on=verifier.today)})


class Hybrid:
    """Live hybrid step for `terkini check`: one model guess, then `prove` and `combine` when it proposes a value."""

    def __init__(self, verifier, cfg: HybridConfig):
        self.verifier, self.cfg = verifier, cfg

    def apply(self, result: ClaimResult) -> ClaimResult:
        from terkini.baseline import judge_without_pages
        from terkini.credits import CreditLimitReached
        from terkini.extractor import ModelOutputError, load_prompts
        from terkini.gateway import GatewayError
        from terkini.tavily import TavilyHTTPError
        v = self.verifier
        if result.verdict == "outdated":
            return result
        try:
            guess, _, _ = judge_without_pages(v.gateway, v.judge_model, result.claim, country=v.pack.name,
                                              today=v.today.isoformat(), fallbacks=v.fallbacks,
                                              prompts=v.prompts or load_prompts())
            if guess["verdict"] != "outdated" or not guess["current_value"]:
                return result
            return combine(result, prove(v, result.claim, guess["current_value"], self.cfg), v)
        except (GatewayError, ModelOutputError, TavilyHTTPError, CreditLimitReached):
            return result  # the hybrid step is a second look; its failure leaves the main verdict as it was
