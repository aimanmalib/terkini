"""Tavily credit limits from config/budget.toml (D11)."""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, PositiveInt, model_validator

from terkini.packs import REPO_ROOT


class Allocation(BaseModel):
    build: int
    eval_my: int
    reserve: int


class Limits(BaseModel):
    per_run: PositiveInt
    per_day: PositiveInt


class TavilyBudget(BaseModel):
    monthly_credits: PositiveInt
    allocation: Allocation
    limits: Limits

    @model_validator(mode="after")
    def _fits(self) -> "TavilyBudget":
        a = self.allocation
        if a.build + a.eval_my + a.reserve > self.monthly_credits:
            raise ValueError("allocation is larger than monthly_credits")
        if self.limits.per_run > self.limits.per_day:
            raise ValueError("per_run limit is larger than per_day limit")
        return self


def load_budget(root: Path = REPO_ROOT) -> TavilyBudget:
    with open(root / "config" / "budget.toml", "rb") as f:
        return TavilyBudget.model_validate(tomllib.load(f)["tavily"])
