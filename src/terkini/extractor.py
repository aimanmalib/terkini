"""Claim extractor (PRD §3 P0.2): one model call through Bifrost turns an AI answer into structured claims."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Protocol

from pydantic import ValidationError

from terkini.claims import Claim
from terkini.packs import REPO_ROOT, Pack

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class ChatClient(Protocol):
    def chat(self, model: str, messages: list[dict], *, fallbacks: list[str] | None = None,
             json_mode: bool = False, temperature: float | None = 0.0): ...


class ModelOutputError(ValueError):
    pass


def load_prompts(root: Path = REPO_ROOT) -> dict:
    with open(root / "config" / "prompts.toml", "rb") as f:
        return tomllib.load(f)


def parse_json_object(text: str) -> dict:
    """Read the JSON object a model returned, tolerating a ```json fence or text around it."""
    s = _FENCE.sub("", text.strip())
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        start, end = s.find("{"), s.rfind("}")
        if start < 0 or end <= start:
            raise ModelOutputError("model answer has no JSON object") from None
        try:
            data = json.loads(s[start : end + 1])
        except json.JSONDecodeError as e:
            raise ModelOutputError(f"model answer is not valid JSON: {e.msg}") from None
    if not isinstance(data, dict):
        raise ModelOutputError("model answer is not a JSON object")
    return data


@dataclass
class Extraction:
    claims: list[Claim]  # time-sensitive claims in a pack category, duplicates removed
    skipped: list[Claim] = field(default_factory=list)  # not time-sensitive, or outside the pack categories
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


def extract_claims(gateway: ChatClient, model: str, pack: Pack, answer: str, *, question: str = "",
                   fallbacks: list[str] | None = None, prompts: dict | None = None) -> Extraction:
    p = (prompts or load_prompts())["extractor"]
    system = Template(p["system"]).substitute(
        country=pack.name, categories=", ".join(f'"{c.id}"' for c in pack.categories)
    )
    user = Template(p["user"]).substitute(question=question, answer=answer)
    res = gateway.chat(model, [{"role": "system", "content": system.strip()}, {"role": "user", "content": user.strip()}],
                       fallbacks=fallbacks, json_mode=True)
    raw = parse_json_object(res.text).get("claims")
    if not isinstance(raw, list):
        raise ModelOutputError("extractor answer has no 'claims' list")
    out = Extraction(claims=[], model=res.model, prompt_tokens=res.prompt_tokens,
                     completion_tokens=res.completion_tokens)
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue  # a malformed item is dropped, not guessed at
        try:
            claim = Claim.model_validate(_strings(item))
        except ValidationError:
            continue
        if not claim.time_sensitive or pack.category(claim.category) is None:
            out.skipped.append(claim)
        elif claim.key not in seen:
            seen.add(claim.key)
            out.claims.append(claim)
    return out


def _strings(item: dict) -> dict:
    """Models sometimes send numbers or null for text fields; make them strings so validation is about meaning."""
    fixed = dict(item)
    for k in ("claim", "category", "entity", "value", "unit", "stated_date"):
        v = fixed.get(k)
        fixed[k] = "" if v is None else str(v)
    fixed["time_sensitive"] = fixed.get("time_sensitive") is True
    return fixed
