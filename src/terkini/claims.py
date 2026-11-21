"""Data shapes shared by the extractor, the verifier and the answer report."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_serializer

Verdict = Literal["current", "outdated", "unverifiable"]

_NON_WORD = re.compile(r"[^\w%.]+")


class Claim(BaseModel):
    """One factual claim pulled out of an AI answer (PRD §3 P0.2)."""

    claim: str = Field(min_length=1)
    category: str
    entity: str = ""
    value: str = ""
    unit: str = ""
    stated_date: str = ""
    time_sensitive: bool = False

    @property
    def key(self) -> str:
        """Normalised claim text, used to drop duplicates and as the cache key."""
        return normalise_claim(self.claim)


def normalise_claim(text: str) -> str:
    """Lower-case, keep words, numbers, '%' and '.', collapse the rest to single spaces."""
    return _NON_WORD.sub(" ", text.casefold()).strip(" .")


class SearchHit(BaseModel):
    url: str
    title: str = ""
    content: str = ""
    published_date: str | None = None
    official: bool = False  # on a pack domain (D5); only official hits can decide a verdict


class Judgement(BaseModel):
    """What the judge model proposes. Nothing here is trusted until the quote check passes (D7)."""

    verdict: Verdict = "unverifiable"
    current_value: str = ""
    evidence_quote: str = ""
    effective_date_text: str = ""
    effective_date: str = ""
    source_url: str = ""


class HybridEvidence(BaseModel):
    """Second look at a claim (D-022): the value the model proposed and what the official pages showed for it."""

    proposed_value: str
    query: str = ""
    urls: list[str] = []
    quote: str = ""  # exact sentence from an official page that states the proposed value; empty when none
    source_url: str = ""
    page_date: date | None = None
    date_estimated: bool = False  # True: no date in the page text, Tavily's published date was used
    credits: int = 0
    previous_verdict: Verdict = "unverifiable"
    previous_quote: str = ""
    previous_url: str = ""
    previous_date: date | None = None
    decision: str = ""  # why the verdict changed or stayed, in plain words


class ClaimResult(BaseModel):
    claim: Claim
    verdict: Verdict
    current_value: str = ""
    evidence_quote: str = ""
    effective_date: date | None = None
    source_url: str = ""
    source_published_date: date | None = None
    source_label: str = ""  # pack label of the source domain: "government" or "utility"
    quote_ok: bool = False
    cached_copy: bool = False  # Tavily answered from its cache after a capacity error (D6)
    snippet_only: bool = False  # judged on Tavily Search snippets because the official page refused extraction (D-014)
    score: int
    reason: str = ""  # why a claim ended up unverifiable, in plain words
    context: list[SearchHit] = []  # non-official pages: shown, never decide (D5)
    checked_on: date
    credits: int = 0
    hybrid: HybridEvidence | None = None  # set when the hybrid step ran for this claim (D-022)

    @model_serializer(mode="wrap")
    def _omit_empty_hybrid(self, handler):
        """Results without a hybrid step serialise exactly as before D-022 (saved runs, recordings, Pages data)."""
        data = handler(self)
        if data.get("hybrid") is None:
            data.pop("hybrid", None)
        return data
