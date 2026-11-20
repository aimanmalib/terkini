"""Exact-quote check (D-004): a quote counts only if it appears in the source text."""

from __future__ import annotations

import re

_SPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Collapse every run of whitespace to one space and trim the ends."""
    return _SPACE.sub(" ", text).strip()


def quote_in_text(quote: str, text: str) -> bool:
    """True when the quote is a substring of the text after whitespace is normalised.

    An empty quote never counts as evidence.
    """
    q = normalise(quote)
    return bool(q) and q in normalise(text)
