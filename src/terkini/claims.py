"""Data shapes shared by the extractor, the verifier and the answer report."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

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
    score: int
    reason: str = ""  # why a claim ended up unverifiable, in plain words
    context: list[SearchHit] = []  # non-official pages: shown, never decide (D5)
    checked_on: date
    credits: int = 0
