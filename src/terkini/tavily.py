"""Thin Tavily client over httpx (D-002). The key comes from the environment and is never logged."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

API = "https://api.tavily.com"


class TavilyKeyMissing(RuntimeError):
    pass


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

    def extract(self, urls: list[str]) -> ExtractResult:
        """Extract page text for up to 20 URLs (PDFs included)."""
        r = self._client.post(
            f"{API}/extract", headers=self._headers, json={"urls": urls, "include_usage": True}
        )
        r.raise_for_status()
        body = r.json()
        return ExtractResult(
            pages={p["url"]: p.get("raw_content") or "" for p in body.get("results", [])},
            failed=[f["url"] for f in body.get("failed_results", [])],
            credits=int((body.get("usage") or {}).get("credits", 0)),
        )
