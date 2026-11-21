"""Verify one claim against official pages (PRD §3 P0.3, D5–D8).

Fixed order: Tavily Search restricted to pack domains -> one advanced retry if no official page -> Tavily Extract of the
top official pages -> judge model -> exact-quote check in code -> deterministic score.
"""

from __future__ import annotations

import tomllib
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from pydantic import BaseModel

from terkini.claims import Claim, ClaimResult, Judgement, SearchHit
from terkini.credits import CreditGuard
from terkini.extractor import ChatClient, ModelOutputError
from terkini.judge import Page, judge_claim
from terkini.packs import REPO_ROOT, Pack
from terkini.quotes import normalise, quote_in_text
from terkini.score import ScoreConfig, score
from terkini.tavily import Tavily, TavilyHTTPError

CONTEXT_CHARS = 500  # D13: recorded page text is cut to 500 characters


class SearchConfig(BaseModel):
    topic: str
    include_domains_mode: str
    search_depth: str
    retry_depth: str
    max_results: int
    include_published_date: bool
    volatile_max_age_hours: int
    max_query_chars: int
    capacity_status: int


class VerifyConfig(BaseModel):
    search: SearchConfig
    extract_max_urls: int
    judge_max_page_chars: int
    cache_path: str


def load_verify_config(root: Path = REPO_ROOT) -> VerifyConfig:
    with open(root / "config" / "verify.toml", "rb") as f:
        raw = tomllib.load(f)
    return VerifyConfig(search=raw["search"], extract_max_urls=raw["extract"]["max_urls"],
                        judge_max_page_chars=raw["judge"]["max_page_chars"], cache_path=raw["cache"]["path"])


def parse_day(value: str | None) -> date | None:
    """Read a published or effective date: ISO first, then the RFC 2822 form Tavily uses for news."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.strptime(value.strip(), "%d %B %Y").date()
    except ValueError:
        return None


def same_page(url: str) -> str:
    """Key for one page: http and https copies of a URL, or a trailing slash, are the same page."""
    rest = url.split("://", 1)[-1].rstrip("/")
    host, _, path = rest.partition("/")
    return f"{host.lower()}/{path}"


def distinct_pages(hits: list[SearchHit]) -> list[SearchHit]:
    """Drop duplicate copies of a page, keeping its first position and preferring the https copy."""
    kept: dict[str, SearchHit] = {}
    for h in hits:
        k = same_page(h.url)
        if k not in kept or h.url.startswith("https://") and not kept[k].url.startswith("https://"):
            kept[k] = h
    return list(kept.values())


def build_query(claim: Claim, max_chars: int) -> str:
    q = " ".join(claim.claim.split())
    if len(q) <= max_chars:
        return q
    cut = q[:max_chars]
    return cut[: cut.rfind(" ")] if " " in cut else cut


class Verifier:
    def __init__(self, tavily: Tavily, gateway: ChatClient, pack: Pack, guard: CreditGuard, *, cfg: VerifyConfig,
                 score_cfg: ScoreConfig, judge_model: str, today: date, fallbacks: list[str] | None = None,
                 prompts: dict | None = None):
        self.tavily, self.gateway, self.pack, self.guard = tavily, gateway, pack, guard
        self.cfg, self.score_cfg, self.judge_model = cfg, score_cfg, judge_model
        self.today, self.fallbacks, self.prompts = today, fallbacks, prompts

    # --- Tavily ---------------------------------------------------------------------------------------------------

    def _search(self, query: str, depth: str, volatile: bool) -> tuple[list[SearchHit], bool, int]:
        s = self.cfg.search
        params: dict = {
            "topic": s.topic, "search_depth": depth, "max_results": s.max_results,
            "include_domains": self.pack.domain_names, "include_domains_mode": s.include_domains_mode,
            "include_published_date": s.include_published_date,
        }
        if volatile:
            params["max_age_hours"] = s.volatile_max_age_hours
        cached = False
        self.guard.allow(self.guard.search_cost(depth))
        try:
            res = self.tavily.search(query, **params)
        except TavilyHTTPError as e:
            if e.status != s.capacity_status or "max_age_hours" not in params:
                raise
            # D6: live capacity is full. Retry once from Tavily's cache and say so in the result.
            del params["max_age_hours"]
            cached = True
            self.guard.allow(self.guard.search_cost(depth))
            res = self.tavily.search(query, **params)
        self.guard.record(res.credits)
        hits = [
            SearchHit(url=r.get("url", ""), title=r.get("title") or "", content=(r.get("content") or "")[:CONTEXT_CHARS],
                      published_date=r.get("published_date"), official=self.pack.domain_for(r.get("url", "")) is not None)
            for r in res.results if r.get("url")
        ]
        return hits, cached, res.credits

    def _extract(self, hits: list[SearchHit]) -> tuple[list[Page], int]:
        urls = [h.url for h in hits[: self.cfg.extract_max_urls]]
        self.guard.allow(self.guard.extract_cost(len(urls)))
        ext = self.tavily.extract(urls)
        self.guard.record(ext.credits)
        published = {h.url: h.published_date for h in hits}
        pages = [Page(url=u, text=ext.pages[u], published=published.get(u)) for u in urls if ext.pages.get(u)]
        return pages, ext.credits

    # --- One claim ------------------------------------------------------------------------------------------------

    def verify(self, claim: Claim) -> ClaimResult:
        category = self.pack.category(claim.category)
        volatile = bool(category and category.volatile)
        query = build_query(claim, self.cfg.search.max_query_chars)

        hits, cached, credits = self._search(query, self.cfg.search.search_depth, volatile)
        official = distinct_pages([h for h in hits if h.official])
        context = [h for h in hits if not h.official]
        if not official:
            hits, cached2, more = self._search(query, self.cfg.search.retry_depth, volatile)
            cached, credits = cached or cached2, credits + more
            official = distinct_pages([h for h in hits if h.official])
            context = [h for h in hits if not h.official]
        if not official:
            return self._unverifiable(claim, "No official page found.", context, cached, credits)

        pages, more = self._extract(official)
        credits += more
        snippets = not pages
        if snippets:
            # D-014: the official site refused the extract. Judge on the snippets Tavily Search returned from it.
            pages = [Page(url=h.url, text=h.content, published=h.published_date) for h in official if h.content]
        if not pages:
            return self._unverifiable(claim, "Official pages could not be read.", context, cached, credits)

        try:
            j = judge_claim(self.gateway, self.judge_model, claim, pages, country=self.pack.name, today=self.today,
                            max_page_chars=self.cfg.judge_max_page_chars, fallbacks=self.fallbacks, prompts=self.prompts)
        except ModelOutputError:
            return self._unverifiable(claim, "The judge model's answer could not be read.", context, cached, credits)
        return self._accept(claim, j, pages, official, context, cached, credits).model_copy(
            update={"snippet_only": snippets})

    def _accept(self, claim: Claim, j: Judgement, pages: list[Page], official: list[SearchHit],
                context: list[SearchHit], cached: bool, credits: int) -> ClaimResult:
        """D7: keep the judge's verdict only if its quote and effective date are on the page it names."""
        page = next((p for p in pages if p.url == j.source_url), None)
        quote_ok = page is not None and quote_in_text(j.evidence_quote, page.text)
        effective = parse_day(j.effective_date) if j.effective_date_text else None
        date_ok = not j.effective_date_text or (
            effective is not None and normalise(j.effective_date_text).casefold() in normalise(j.evidence_quote).casefold()
        )
        verdict, reason = j.verdict, ""
        if page is None and not j.source_url and verdict == "unverifiable":
            reason = "The official pages do not settle this claim."
        elif page is None and not j.source_url:
            verdict, reason = "unverifiable", "The judge gave no source page for its verdict."
        elif page is None:
            verdict, reason = "unverifiable", "The judge cited a page that was not extracted."
        elif not quote_ok:
            verdict, reason = "unverifiable", "The evidence quote is not on the official page."
        elif not date_ok:
            verdict, reason, effective = "unverifiable", "The effective date is not in the evidence quote.", None
        elif verdict == "unverifiable":
            reason = "The official pages do not settle this claim."

        domain = self.pack.domain_for(j.source_url) if page else None
        published = parse_day(next((h.published_date for h in official if h.url == j.source_url), None))
        government = bool(domain and domain.label == "government")
        return ClaimResult(
            claim=claim, verdict=verdict, current_value=j.current_value if quote_ok else "",
            evidence_quote=j.evidence_quote[:CONTEXT_CHARS] if quote_ok else "",
            effective_date=effective if quote_ok else None, source_url=j.source_url if page else "",
            source_published_date=published, source_label=domain.label if domain else "", quote_ok=quote_ok,
            cached_copy=cached, reason=reason, context=context, checked_on=self.today, credits=credits,
            score=score(self.score_cfg, verdict, government=government, quote_ok=quote_ok, published=published,
                        checked_on=self.today),
        )

    def _unverifiable(self, claim: Claim, reason: str, context: list[SearchHit], cached: bool,
                      credits: int) -> ClaimResult:
        return ClaimResult(
            claim=claim, verdict="unverifiable", reason=reason, context=context, cached_copy=cached,
            checked_on=self.today, credits=credits,
            score=score(self.score_cfg, "unverifiable", government=False, quote_ok=False, published=None,
                        checked_on=self.today),
        )
