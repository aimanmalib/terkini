"""Country packs: official domains, categories and eval files, read from packs/<id>.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field, model_validator

REPO_ROOT = Path(__file__).resolve().parents[2]


class Domain(BaseModel):
    domain: str
    label: Literal["government", "utility"]
    agency: str = ""


class Category(BaseModel):
    id: str
    name_en: str
    name_ms: str
    volatile: bool


class CanonicalSource(BaseModel):
    category: str
    url: str


class Pack(BaseModel):
    id: str
    name: str
    query_languages: list[str]
    questions: str
    key: str
    domains: list[Domain] = Field(min_length=1)
    categories: list[Category] = Field(min_length=1)
    canonical_sources: list[CanonicalSource] = []

    @model_validator(mode="after")
    def _consistent(self) -> "Pack":
        ids = [c.id for c in self.categories]
        if len(ids) != len(set(ids)):
            raise ValueError("category ids must be unique")
        for src in self.canonical_sources:
            if src.category not in ids:
                raise ValueError(f"canonical source for unknown category {src.category!r}")
            if self.domain_for(src.url) is None:
                raise ValueError(f"canonical source is not on a pack domain: {src.url}")
        return self

    @property
    def domain_names(self) -> list[str]:
        return [d.domain for d in self.domains]

    def domain_for(self, url: str) -> Domain | None:
        """The pack domain that serves this URL (exact host or a subdomain), else None."""
        host = (urlparse(url).hostname or "").lower()
        for d in self.domains:
            name = d.domain.lower()
            if host == name or host.endswith("." + name):
                return d
        return None

    def category(self, category_id: str) -> Category | None:
        return next((c for c in self.categories if c.id == category_id), None)


class Question(BaseModel):
    id: str
    category: str
    question: str


class KeyEntry(BaseModel):
    id: str
    value: str
    url: str
    quote: str = Field(min_length=1, max_length=500)
    effective_date: str | None = None
    read_at: str


class DroppedQuestion(BaseModel):
    topic: str
    reason: str


class AnswerKey(BaseModel):
    pack: str
    keys: list[KeyEntry]
    dropped: list[DroppedQuestion] = []


def load_pack(pack_id: str, root: Path = REPO_ROOT) -> Pack:
    with open(root / "packs" / f"{pack_id}.toml", "rb") as f:
        return Pack.model_validate(tomllib.load(f))


def load_questions(pack: Pack, root: Path = REPO_ROOT) -> list[Question]:
    data = yaml.safe_load((root / pack.questions).read_text(encoding="utf-8"))
    return [Question.model_validate(q) for q in data["questions"]]


def load_key(pack: Pack, root: Path = REPO_ROOT) -> AnswerKey:
    data = yaml.safe_load((root / pack.key).read_text(encoding="utf-8"))
    return AnswerKey.model_validate(data)
