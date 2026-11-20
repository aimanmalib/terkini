"""Shared fakes for the verifier tests. No network: Tavily runs over an httpx MockTransport, the gateway is scripted."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from terkini.budget import load_budget
from terkini.cache import Cache
from terkini.credits import CreditGuard
from terkini.gateway import ChatResult
from terkini.packs import load_pack
from terkini.score import load_score_config
from terkini.tavily import Tavily
from terkini.verify import Verifier, load_verify_config

TODAY = date(2026, 11, 21)


class FakeTavily:
    """Answers /search and /extract from queues; records every request body."""

    def __init__(self):
        self.searches: list[dict] = []  # responses: dict body, or int status for an error
        self.extracts: list[dict] = []
        self.calls: list[tuple[str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.strip("/")
        body = json.loads(request.content)
        self.calls.append((path, body))
        queue = self.searches if path == "search" else self.extracts
        item = queue.pop(0)
        if isinstance(item, int):
            return httpx.Response(item, json={"detail": {"error": "Flex tier capacity exceeded"}})
        return httpx.Response(200, json=item)

    def client(self) -> Tavily:
        return Tavily(api_key="test-only", client=httpx.Client(transport=httpx.MockTransport(self.handler)))


class FakeGateway:
    def __init__(self, *answers: dict | str):
        self.answers = list(answers)
        self.calls: list[dict] = []

    def chat(self, model, messages, *, fallbacks=None, json_mode=False, temperature=0.0):
        self.calls.append({"model": model, "messages": messages, "fallbacks": fallbacks, "json_mode": json_mode})
        a = self.answers.pop(0)
        text = a if isinstance(a, str) else json.dumps(a)
        return ChatResult(text=text, model=model, prompt_tokens=10, completion_tokens=5, seconds=0.1, raw={})


def search_body(*hits: tuple[str, str | None], credits: int = 1) -> dict:
    return {"results": [{"url": u, "title": "t", "content": "snippet", "score": 0.9, "published_date": p}
                        for u, p in hits], "usage": {"credits": credits}}


def extract_body(pages: dict[str, str], credits: int = 1) -> dict:
    return {"results": [{"url": u, "raw_content": t} for u, t in pages.items()], "failed_results": [],
            "usage": {"credits": credits}}


@pytest.fixture
def pack():
    return load_pack("my")


@pytest.fixture
def cache():
    c = Cache(":memory:")
    yield c
    c.close()


@pytest.fixture
def make_verifier(pack, cache):
    def make(tavily: FakeTavily, gateway: FakeGateway, budget=None) -> Verifier:
        guard = CreditGuard(budget or load_budget(), cache, TODAY)
        return Verifier(tavily.client(), gateway, pack, guard, cfg=load_verify_config(), score_cfg=load_score_config(),
                        judge_model="judge/model", today=TODAY)
    return make
