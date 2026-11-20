"""Thin Tavily client over httpx (D-002). The key comes from the environment and is never logged."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

API = "https://api.tavily.com"


class TavilyKeyMissing(RuntimeError):
    pass


class TavilyHTTPError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"Tavily HTTP {status}: {message}")
        self.status = status


@dataclass(frozen=True)
class SearchResult:
    results: list[dict]  # url, title, content, score, published_date
    credits: int


@dataclass(frozen=True)
class ExtractResult:
    pages: dict[str, str]  # url -> raw page text
    failed: list[str]
    credits: int


class Tavily:
    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None, timeout: float = 120.0):
        key = api_key if api_key is not None else os.environ.get("TAVILY_API_KEY", "")
        if not key:
            raise TavilyKeyMissing("TAVILY_API_KEY is not set; live mode needs your own key")
        self._client = client or httpx.Client(timeout=timeout)
        self._headers = {"Authorization": f"Bearer {key}"}

    def usage(self) -> dict:
        """Credits used by this key and its account (GET /usage)."""
        r = self._client.get(f"{API}/usage", headers=self._headers)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict) -> dict:
        r = self._client.post(f"{API}/{path}", headers=self._headers, json=body)
        if r.status_code != 200:
            raise TavilyHTTPError(r.status_code, _error_detail(r))
        return r.json()

    def search(self, query: str, **params) -> SearchResult:
        """POST /search. params are sent as given (verify.py builds them from config/verify.toml)."""
        body = self._post("search", {"query": query, **params, "include_usage": True})
        return SearchResult(
            results=list(body.get("results") or []),
            credits=int((body.get("usage") or {}).get("credits", 0)),
        )

    def extract(self, urls: list[str]) -> ExtractResult:
        """Extract page text for up to 20 URLs (PDFs included)."""
        body = self._post("extract", {"urls": urls, "include_usage": True})
        return ExtractResult(
            pages={p["url"]: p.get("raw_content") or "" for p in body.get("results", [])},
            failed=[f["url"] for f in body.get("failed_results", [])],
            credits=int((body.get("usage") or {}).get("credits", 0)),
        )


def _error_detail(r: httpx.Response) -> str:
    # Tavily errors look like {"detail": {"error": "..."}}; never echo request headers.
    try:
        detail = r.json().get("detail")
    except ValueError:
        return r.text[:200]
    if isinstance(detail, dict):
        return str(detail.get("error", ""))[:200]
    return str(detail)[:200]
