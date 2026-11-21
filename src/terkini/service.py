"""One check, shared by the CLI and `POST /api/check`: replay a recorded run, or check live with your own keys.

Mode rule (same for both): a named recording always replays. Otherwise the check is live when TAVILY_API_KEY is set,
and replays the recording whose answer matches when it is not. A case name can also be a saved eval run
(eval/<pack>/runs, D-023): its report is shown as it was checked live, since eval runs keep no Tavily responses.
"""

from __future__ import annotations

import os
import tomllib
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from terkini.checker import AnswerReport
from terkini.packs import REPO_ROOT
from terkini.replay import Cassette


class NoRecording(LookupError):
    """Replay mode found no recorded run for this request."""


class UnknownPack(LookupError):
    pass


@dataclass(frozen=True)
class ApiConfig:
    default_pack: str
    max_answer_chars: int


def load_api_config(root: Path = REPO_ROOT) -> ApiConfig:
    with open(root / "config" / "api.toml", "rb") as f:
        c = tomllib.load(f)["check"]
    return ApiConfig(default_pack=c["default_pack"], max_answer_chars=int(c["max_answer_chars"]))


def pack_ids(root: Path = REPO_ROOT) -> list[str]:
    return sorted(p.stem for p in (root / "packs").glob("*.toml"))


def is_live(case: str | None) -> bool:
    return not case and bool(os.environ.get("TAVILY_API_KEY"))


@dataclass(frozen=True)
class Outcome:
    mode: str  # "live run", "recorded run, <date>" or "eval run, <date>"
    report: AnswerReport
    recording: Cassette | None = None  # the recorded run replayed, if any
    answer: str = ""  # the answer checked, when it came from a recording or an eval run
    answer_model: str = ""  # the model that wrote it


def run(answer: str | None, *, pack: str, case: str | None = None, root: Path = REPO_ROOT) -> Outcome:
    """Check one answer. Raises UnknownPack, NoRecording, or GatewayNotConfigured (live only)."""
    from terkini.replay import find_by_answer, list_cassettes
    from terkini.runner import replay, runs_dir

    if pack not in pack_ids(root):
        raise UnknownPack(pack)
    if is_live(case):
        return Outcome("live run", _live(answer or "", pack, root))
    cassettes = list_cassettes(runs_dir(root), pack)
    found = next((c for c in cassettes if c.name == case), None) if case else (
        find_by_answer(cassettes, answer) if answer else None)
    if found is not None:
        return Outcome(f"recorded run, {found.recorded_at[:10]}", replay(found, root), found, found.answer,
                       found.answer_model)
    saved = eval_run(pack, case, root) if case else None
    if saved is None:
        raise NoRecording(case or "")
    answer, checked = saved
    return Outcome(f"eval run, {checked.checked_at[:10]}", checked.report, None, answer.answer, answer.model)


def _live(answer: str, pack_id: str, root: Path) -> AnswerReport:
    from terkini.cache import Cache
    from terkini.gateway import Gateway, load_env_file
    from terkini.hybrid import load_hybrid_config
    from terkini.runner import run_check
    from terkini.tavily import Tavily
    from terkini.verify import load_verify_config

    load_env_file(root / ".env.bifrost")
    today = datetime.now(UTC).date()
    with closing(Cache(root / load_verify_config(root).cache_path)) as cache:
        return run_check(answer, pack_id=pack_id, tavily=Tavily(), gateway=Gateway(), cache=cache, today=today, root=root,
                         hybrid=load_hybrid_config(root).enabled)


def eval_runs_folder(pack: str, root: Path = REPO_ROOT) -> Path:
    from terkini.evaluate import eval_dir, load_eval_config
    from terkini.packs import load_pack

    return eval_dir(load_pack(pack, root), root) / load_eval_config(root).runs_dir


def eval_run(pack: str, case: str, root: Path = REPO_ROOT):
    """(Answer, AnswerRun) of the saved eval run named `case`, or None. Names are file stems inside the pack's folders."""
    from terkini.evaluate import Answer, AnswerRun, eval_dir, load_eval_config
    from terkini.packs import load_pack

    folder, cfg = eval_dir(load_pack(pack, root), root), load_eval_config(root)
    run_path, answer_path = folder / cfg.runs_dir / f"{case}.json", folder / cfg.answers_dir / f"{case}.json"
    if run_path.parent != folder / cfg.runs_dir or not (run_path.is_file() and answer_path.is_file()):
        return None
    return (Answer.model_validate_json(answer_path.read_text(encoding="utf-8")),
            AnswerRun.model_validate_json(run_path.read_text(encoding="utf-8")))
