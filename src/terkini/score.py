"""Deterministic freshness score and answer "as-of" estimate (PRD D8). Weights come from config/score.toml."""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from terkini.claims import ClaimResult, Verdict
from terkini.packs import REPO_ROOT


class Quality(BaseModel):
    base: float
    government: float
    quote: float


class Scale(BaseModel):
    current: float
    unverifiable: float
    outdated: float


class Band(BaseModel):
    max_days: int = Field(ge=0)
    r: float


class Other(BaseModel):
    older: float
    undated: float


class ScoreConfig(BaseModel):
    quality: Quality
    scale: Scale
    recency: list[Band] = Field(min_length=1)
    recency_other: Other


def load_score_config(root: Path = REPO_ROOT) -> ScoreConfig:
    with open(root / "config" / "score.toml", "rb") as f:
        return ScoreConfig.model_validate(tomllib.load(f))


def round_half_up(x: float) -> int:
    # The epsilon absorbs float noise such as 100 * 0.8 * 0.9 = 72.00000000000001 or 37.49999999.
    return int(math.floor(x + 0.5 + 1e-9))


def quality(cfg: ScoreConfig, government: bool, quote_ok: bool) -> float:
    q = cfg.quality
    return q.base + q.government * government + q.quote * quote_ok


def recency(cfg: ScoreConfig, published: date | None, checked_on: date) -> float:
    if published is None:
        return cfg.recency_other.undated
    age = max(0, (checked_on - published).days)
    for band in cfg.recency:
        if age <= band.max_days:
            return band.r
    return cfg.recency_other.older


def score(cfg: ScoreConfig, verdict: Verdict, *, government: bool, quote_ok: bool,
          published: date | None, checked_on: date) -> int:
    q = quality(cfg, government, quote_ok)
    r = recency(cfg, published, checked_on)
    if verdict == "current":
        return round_half_up(cfg.scale.current * q * r)
    if verdict == "outdated":
        return round_half_up(cfg.scale.outdated * (1 - q))
    return round_half_up(cfg.scale.unverifiable * r)


@dataclass(frozen=True)
class AsOf:
    """Answer-level estimate. Present only when at least one outdated claim has an effective date."""

    before: date  # the answer matches the rules in force before this date
    mixed: bool  # some dated rules in the answer are newer than that date


def as_of(results: list[ClaimResult]) -> AsOf | None:
    stale = [r.effective_date for r in results if r.verdict == "outdated" and r.effective_date]
    if not stale:
        return None
    first_change = min(stale)
    fresh = [r.effective_date for r in results if r.verdict == "current" and r.effective_date]
    return AsOf(before=first_change, mixed=bool(fresh) and max(fresh) > first_change)
