"""Direct liveness check for answer-key pages (D-011). Tavily Extract can return a cached copy of a page that the
site has since removed, so each URL is also fetched directly from the official site."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import httpx

from terkini.packs import REPO_ROOT


class Live(str, Enum):
    OK = "ok"  # 2xx/3xx from the official site
    DEAD = "dead"  # any other 4xx/5xx: the page is gone or broken
    BLOCKED = "blocked"  # the site refused a script (status in blocked_status, or connection refused/reset)


@dataclass(frozen=True)
class VerifyConfig:
    timeout_seconds: float
    user_agent: str
    blocked_status: frozenset[int]


def load_verify_config(root: Path = REPO_ROOT) -> VerifyConfig:
    with open(root / "config" / "verify.toml", "rb") as f:
        d = tomllib.load(f)["direct"]
    return VerifyConfig(float(d["timeout_seconds"]), str(d["user_agent"]), frozenset(int(s) for s in d["blocked_status"]))


def classify(status: int, cfg: VerifyConfig) -> Live:
    if status < 400:
        return Live.OK
    return Live.BLOCKED if status in cfg.blocked_status else Live.DEAD


def probe(url: str, cfg: VerifyConfig, client: httpx.Client) -> tuple[Live, str]:
    """GET the URL (body not read) and return its liveness and a short detail for the report."""
    try:
        with client.stream("GET", url, headers={"User-Agent": cfg.user_agent}, follow_redirects=True) as r:
            return classify(r.status_code, cfg), str(r.status_code)
    except httpx.TransportError as e:
        return Live.BLOCKED, type(e).__name__


def verdict(live: Live, extract_failed: bool, quote_found: bool) -> str:
    """One word per key: ok, BLOCKED (quote found but the site refuses scripts), or MISS."""
    if live is Live.DEAD or extract_failed or not quote_found:
        return "MISS"
    return "BLOCKED" if live is Live.BLOCKED else "ok"
