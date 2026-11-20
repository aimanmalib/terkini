"""Recorded runs (PRD §3 P0.7, D10, D13): record a live check, replay it later with no key and no network.

A recorded run ("cassette") keeps only what the pipeline reads back: Tavily search results (snippets cut to 500
characters), short excerpts of each extracted page around the quotes the judge cited, and the model answers. It never
keeps request headers, keys or full pages. Replay feeds the same answers back in the same order, so the checker runs
its real code path (quote check, score) and must produce the same report.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel

from terkini.extractor import ModelOutputError, parse_json_object
from terkini.gateway import ChatResult, GatewayError
from terkini.quotes import normalise
from terkini.tavily import ExtractResult, SearchResult, Tavily, TavilyHTTPError

EXCERPT_CHARS = 500  # D13: no recorded page text longer than this
UNCITED_CHARS = 200  # a page the judge did not quote keeps only its opening, so it still counts as read
_SEP = "\n…\n"
_HIT_FIELDS = ("url", "title", "content", "score", "published_date")


class ReplayMismatch(RuntimeError):
    """The pipeline asked for something the recording does not have (code or config changed since recording)."""


class Chat(BaseModel):
    model: str  # model requested
    answered_by: str = ""  # model the gateway reports
    text: str = ""
    error: str = ""  # gateway failure, replayed as GatewayError
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0


class SearchCall(BaseModel):
    query: str
    search_depth: str = ""
    results: list[dict] = []
    credits: int = 0
    error_status: int = 0  # Tavily HTTP error replayed as TavilyHTTPError
    error: str = ""


class ExtractCall(BaseModel):
    urls: list[str]
    excerpts: dict[str, list[str]] = {}  # url -> excerpts, each <= EXCERPT_CHARS
    failed: list[str] = []
    credits: int = 0


class Cassette(BaseModel):
    name: str
    pack: str
    recorded_at: str  # UTC timestamp of the live run
    checked_on: date
    question_id: str = ""
    question: str = ""
    answer_model: str = ""  # eval model that wrote the answer
    answer: str
    ask: Chat | None = None  # the recorded model answer, when the answer came from a model
    chats: list[Chat] = []  # extractor first, then one judge call per verified claim
    searches: list[SearchCall] = []
    extracts: list[ExtractCall] = []
    usage_before: dict = {}  # GET /usage before and after the live run (plan and key totals only)
    usage_after: dict = {}
    report: dict  # the AnswerReport produced live; replay must reproduce it


# --- Recording ----------------------------------------------------------------------------------------------------

def chat_record(model: str, res: ChatResult) -> Chat:
    return Chat(model=model, answered_by=res.model, text=res.text, prompt_tokens=res.prompt_tokens,
                completion_tokens=res.completion_tokens, seconds=round(res.seconds, 2))


class RecordingGateway:
    def __init__(self, inner):
        self.inner, self.chats = inner, []

    def chat(self, model, messages, *, fallbacks=None, json_mode=False, temperature=0.0):
        try:
            res = self.inner.chat(model, messages, fallbacks=fallbacks, json_mode=json_mode, temperature=temperature)
        except GatewayError as e:
            self.chats.append(Chat(model=model, error=str(e)))
            raise
        self.chats.append(chat_record(model, res))
        return res


class RecordingTavily:
    """Wraps a live Tavily client. Full page text is held in memory only until `excerpts()` cuts it down."""

    def __init__(self, inner: Tavily):
        self.inner, self.searches, self.extracts = inner, [], []
        self._full: list[dict[str, str]] = []

    def search(self, query: str, **params) -> SearchResult:
        call = SearchCall(query=query, search_depth=str(params.get("search_depth", "")))
        self.searches.append(call)
        try:
            res = self.inner.search(query, **params)
        except TavilyHTTPError as e:
            call.error_status, call.error = e.status, str(e).split(": ", 1)[-1]
            raise
        call.results = [{k: (r.get(k) or "")[:EXCERPT_CHARS] if k in ("title", "content") else r.get(k)
                         for k in _HIT_FIELDS} for r in res.results]
        call.credits = res.credits
        return res

    def extract(self, urls: list[str]) -> ExtractResult:
        res = self.inner.extract(urls)
        self.extracts.append(ExtractCall(urls=list(urls), failed=list(res.failed), credits=res.credits))
        self._full.append(dict(res.pages))
        return res

    def cut(self, chats: list[Chat]) -> None:
        """Keep only excerpts of each page: a window around every quote the judge cited from it (D13)."""
        cited: dict[str, list[str]] = {}
        for c in chats:
            try:
                data = parse_json_object(c.text)
            except ModelOutputError:
                continue
            if data.get("source_url") and data.get("evidence_quote"):
                cited.setdefault(str(data["source_url"]), []).append(str(data["evidence_quote"]))
        for call, pages in zip(self.extracts, self._full):
            call.excerpts = {u: excerpts(t, cited.get(u, [])) for u, t in pages.items()}
        self._full = []


def excerpts(text: str, quotes: list[str]) -> list[str]:
    """Whitespace-normalised windows of the page that contain each quote found on it."""
    page = normalise(text)
    if not page:
        return []
    out: list[str] = []
    for q in quotes:
        nq = normalise(q)
        i = page.find(nq) if nq else -1
        if i < 0 or len(nq) > EXCERPT_CHARS:
            continue  # a quote not on the page stays absent; replay reaches the same verdict
        pad = (EXCERPT_CHARS - len(nq)) // 2
        start = max(0, min(i - pad, len(page) - EXCERPT_CHARS))
        window = page[start : start + EXCERPT_CHARS]
        if window not in out:
            out.append(window)
    return out or [page[:UNCITED_CHARS]]


# --- Replay -------------------------------------------------------------------------------------------------------

class ReplayGateway:
    def __init__(self, chats: list[Chat]):
        self._chats = list(chats)

    def chat(self, model, messages, *, fallbacks=None, json_mode=False, temperature=0.0) -> ChatResult:
        if not self._chats:
            raise ReplayMismatch(f"no recorded model answer left for {model}")
        c = self._chats.pop(0)
        if c.model != model:
            raise ReplayMismatch(f"recorded answer is from {c.model}, run asked {model}")
        if c.error:
            raise GatewayError(c.error)
        return ChatResult(text=c.text, model=c.answered_by or c.model, prompt_tokens=c.prompt_tokens,
                          completion_tokens=c.completion_tokens, seconds=c.seconds, raw={})


class ReplayTavily:
    def __init__(self, cassette: Cassette):
        self._searches, self._extracts = list(cassette.searches), list(cassette.extracts)

    def search(self, query: str, **params) -> SearchResult:
        if not self._searches:
            raise ReplayMismatch(f"no recorded search left for {query!r}")
        s = self._searches.pop(0)
        if s.query != query or s.search_depth != str(params.get("search_depth", "")):
            raise ReplayMismatch(f"recorded search was {s.query!r} ({s.search_depth}), run asked {query!r}")
        if s.error_status:
            raise TavilyHTTPError(s.error_status, s.error)
        return SearchResult(results=[dict(r) for r in s.results], credits=s.credits)

    def extract(self, urls: list[str]) -> ExtractResult:
        if not self._extracts:
            raise ReplayMismatch(f"no recorded extract left for {urls}")
        e = self._extracts.pop(0)
        if e.urls != list(urls):
            raise ReplayMismatch(f"recorded extract was {e.urls}, run asked {urls}")
        return ExtractResult(pages={u: _SEP.join(x) for u, x in e.excerpts.items()}, failed=list(e.failed),
                             credits=e.credits)


def load_cassette(path: Path) -> Cassette:
    return Cassette.model_validate_json(path.read_text(encoding="utf-8"))


def list_cassettes(folder: Path, pack: str | None = None) -> list[Cassette]:
    found = [load_cassette(p) for p in sorted(folder.glob("*.json"))]
    return [c for c in found if pack is None or c.pack == pack]


def find_by_answer(cassettes: list[Cassette], answer: str) -> Cassette | None:
    want = normalise(answer)
    return next((c for c in cassettes if normalise(c.answer) == want), None)


def write_cassette(c: Cassette, folder: Path, secrets: list[str]) -> Path:
    text = json.dumps(c.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    if any(s and s in text for s in secrets):
        raise RuntimeError("a secret value appeared in the recording; not writing it")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{c.name}.json"
    path.write_text(text, encoding="utf-8")
    return path
