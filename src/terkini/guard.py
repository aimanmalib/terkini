"""Budget guard before a run that spends (D-025): Bifrost Meter's `guard` command, off by default (config/guard.toml).

Terkini passes BIFROST_URL as BIFROST_BASE_URL and its own BIFROST_VIRTUAL_KEY to the guard process. The key is never
printed; Bifrost Meter never prints it either. Exit codes from the guard: 0 go, 2 stop, 1 quota not readable.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from terkini.packs import REPO_ROOT

GO, ERROR, STOP = 0, 1, 2


class GuardConfig(BaseModel):
    enabled: bool
    node: str
    cli: str
    min_remaining: int = Field(ge=0, le=100)
    on_error: Literal["continue", "stop"]
    timeout_seconds: int = Field(gt=0)
    commands: list[str]


def load_guard_config(root: Path = REPO_ROOT) -> GuardConfig:
    with open(root / "config" / "guard.toml", "rb") as f:
        return GuardConfig(**tomllib.load(f))


@dataclass(frozen=True)
class GuardResult:
    code: int  # 0 go, 1 quota not readable, 2 stop
    sentence: str


def guard_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if environ is None else environ)
    if env.get("BIFROST_URL") and not env.get("BIFROST_BASE_URL"):
        env["BIFROST_BASE_URL"] = env["BIFROST_URL"]
    return env


def run_guard(cfg: GuardConfig, root: Path = REPO_ROOT, environ: dict[str, str] | None = None,
              runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> GuardResult:
    cli = Path(cfg.cli) if Path(cfg.cli).is_absolute() else root / cfg.cli
    if not cli.is_file():
        return GuardResult(ERROR, f"Bifrost Meter not found at {cfg.cli} (config/guard.toml cli).")
    try:
        p = runner([cfg.node, str(cli), "guard", "--min-remaining", str(cfg.min_remaining)], env=guard_env(environ),
                   capture_output=True, text=True, timeout=cfg.timeout_seconds)
    except FileNotFoundError:
        return GuardResult(ERROR, f"{cfg.node} not found (config/guard.toml node).")
    except subprocess.TimeoutExpired:
        return GuardResult(ERROR, f"Bifrost guard did not answer within {cfg.timeout_seconds} s.")
    lines = (p.stdout or p.stderr or "").strip().splitlines()
    sentence = lines[-1] if lines else f"Bifrost guard exited {p.returncode} with no output."
    return GuardResult(p.returncode if p.returncode in (GO, STOP) else ERROR, sentence)


def preflight(command: str, root: Path = REPO_ROOT, run: Callable[..., GuardResult] | None = None) -> int | None:
    """Run the guard if config/guard.toml turns it on for this command. None = go on; an int = exit with that code."""
    cfg = load_guard_config(root)
    if not cfg.enabled or command not in cfg.commands:
        return None
    r = (run or run_guard)(cfg, root)
    print(r.sentence, file=sys.stderr)
    if r.code == STOP:
        print(f"{command}: stopped before any call (budget guard, config/guard.toml).", file=sys.stderr)
        return STOP
    if r.code == ERROR:
        if cfg.on_error == "stop":
            print(f"{command}: stopped: the budget guard could not read the quota (on_error = \"stop\").",
                  file=sys.stderr)
            return STOP
        print(f"{command}: going on without a budget reading (on_error = \"continue\").", file=sys.stderr)
    return None
