"""Eval runs (PRD §2 H2-H6): ask pack questions to several models, then check every answer live.

`terkini ask` writes one file per (question, model) to eval/<pack>/answers/. `terkini eval` checks each answer with
the real checker (Tavily + Bifrost), keeps one report per answer in eval/<pack>/runs/, and computes
eval/<pack>/results.json from the runs, the labels (labels.yaml) and the answer key (metrics.py).
"""

from __future__ import annotations

import json
import re
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from string import Template

import yaml
from pydantic import BaseModel

from terkini.budget import load_budget
from terkini.cache import Cache
from terkini.checker import AnswerReport
from terkini.credits import CreditGuard
from terkini.extractor import load_prompts
from terkini.gateway import ChatResult, GatewayError
from terkini.packs import REPO_ROOT, Pack, Question, load_questions
from terkini.runner import run_check


class EvalConfig(BaseModel):
    workers: int
    answers_dir: str
    runs_dir: str
    labels: str
    results: str
    date_window_days: int
    baseline_model_only: str
    ci_z: float


def load_eval_config(root: Path = REPO_ROOT) -> EvalConfig:
    with open(root / "config" / "verify.toml", "rb") as f:
        return EvalConfig.model_validate(tomllib.load(f)["eval"])


def eval_dir(pack: Pack, root: Path = REPO_ROOT) -> Path:
    return (root / pack.questions).parent


def answer_name(question_id: str, model: str) -> str:
    return f"{question_id}--" + re.sub(r"[^a-z0-9]+", "-", model.lower().split("/")[-1]).strip("-")


class Answer(BaseModel):
    name: str
    question_id: str
    question: str
    model: str
    answered_by: str
    asked_at: str
    answer: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float


class Label(BaseModel):
    """Label for one answer, written against the answer key before the checker ran (docs/EVAL.md)."""

    answer: str
    stale: bool | None  # True: states an older value than the key; False: states the key value; None: no value
    note: str = ""


class AnswerRun(BaseModel):
    answer: str
    question_id: str
    model: str
    checked_at: str
    seconds: float
    prompt_tokens: int
    completion_tokens: int
    gateway_calls: int
    report: AnswerReport


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ask_question(gateway, pack: Pack, q: Question, model: str, prompts: dict | None = None) -> Answer:
    p = (prompts or load_prompts())["ask"]
    messages = [{"role": "system", "content": Template(p["system"]).substitute(country=pack.name).strip()},
                {"role": "user", "content": Template(p["user"]).substitute(question=q.question).strip()}]
    res: ChatResult = gateway.chat(model, messages, temperature=0.0)  # no fallbacks: the answer must be this model's
    return Answer(name=answer_name(q.id, model), question_id=q.id, question=q.question, model=model,
                  answered_by=res.model, asked_at=_now(), answer=res.text.strip(), prompt_tokens=res.prompt_tokens,
                  completion_tokens=res.completion_tokens, seconds=round(res.seconds, 2))


def write_json(path: Path, data: BaseModel | dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ask_all(gateway, pack: Pack, models: list[str], *, only: list[str] | None = None, force: bool = False,
            root: Path = REPO_ROOT, log=print) -> list[str]:
    """Ask every pack question to every model; skip answers already on disk. Returns failures."""
    cfg = load_eval_config(root)
    out = eval_dir(pack, root) / cfg.answers_dir
    prompts = load_prompts(root)
    jobs = [(q, m) for q in load_questions(pack, root) if not only or q.id in only for m in models
            if force or not (out / f"{answer_name(q.id, m)}.json").exists()]

    def one(job):
        q, m = job
        try:
            a = ask_question(gateway, pack, q, m, prompts)
        except GatewayError as e:
            return f"{answer_name(q.id, m)}: {e}"
        if not a.answer:
            return f"{a.name}: empty answer"
        write_json(out / f"{a.name}.json", a)
        log(f"ask: {a.name} ({a.seconds:.0f} s)")
        return None

    with ThreadPoolExecutor(cfg.workers) as pool:
        return [f for f in pool.map(one, jobs) if f]


def load_answers(pack: Pack, root: Path = REPO_ROOT) -> list[Answer]:
    d = eval_dir(pack, root) / load_eval_config(root).answers_dir
    return [Answer.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))]


def load_labels(pack: Pack, root: Path = REPO_ROOT) -> dict[str, Label]:
    p = eval_dir(pack, root) / load_eval_config(root).labels
    data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {"labels": []}
    return {x.answer: x for x in (Label.model_validate(v) for v in data["labels"])}


def load_runs(pack: Pack, root: Path = REPO_ROOT) -> list[AnswerRun]:
    d = eval_dir(pack, root) / load_eval_config(root).runs_dir
    return [AnswerRun.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))]


class CountingGateway:
    """Pass-through that adds up the tokens of every model call made while checking one answer."""

    def __init__(self, inner):
        self.inner, self.prompt_tokens, self.completion_tokens, self.calls = inner, 0, 0, 0

    def chat(self, model, messages, **kw) -> ChatResult:
        res = self.inner.chat(model, messages, **kw)
        self.calls += 1
        self.prompt_tokens += res.prompt_tokens
        self.completion_tokens += res.completion_tokens
        return res


def check_all(answers: list[Answer], pack: Pack, *, tavily, gateway, cache: Cache, today: date, force: bool = False,
              keep_errors: bool = False, root: Path = REPO_ROOT, log=print) -> CreditGuard:
    """Check each answer live and write its run. One credit guard for the whole eval, capped at the eval allocation."""
    cfg = load_eval_config(root)
    out = eval_dir(pack, root) / cfg.runs_dir
    budget = load_budget(root)
    eval_budget = budget.model_copy(update={"limits": budget.limits.model_copy(
        update={"per_run": budget.allocation.eval_my})})
    guard = CreditGuard(eval_budget, cache, today)
    todo = [a for a in answers if force or not (out / f"{a.name}.json").exists()]

    def one(a: Answer):
        gw = CountingGateway(gateway)
        t0 = time.monotonic()
        report = run_check(a.answer, pack_id=pack.id, tavily=tavily, gateway=gw, cache=cache, today=today,
                           question=a.question, root=root, guard=guard)
        took = round(time.monotonic() - t0, 2)
        if report.stopped:
            log(f"eval: {a.name} stopped: {report.stopped}; not saved")
            return
        if report.errors and not keep_errors:
            # A gateway or Tavily failure is not cached; the next run retries it and reuses the claims that passed.
            log(f"eval: {a.name} had {len(report.errors)} failed claims ({report.errors[0].error}); not saved")
            return
        write_json(out / f"{a.name}.json", AnswerRun(
            answer=a.name, question_id=a.question_id, model=a.model, checked_at=_now(), seconds=took,
            prompt_tokens=gw.prompt_tokens, completion_tokens=gw.completion_tokens, gateway_calls=gw.calls,
            report=report))
        log(f"eval: {a.name} · {len(report.results)} claims · {report.outdated} outdated · "
            f"{len(report.errors)} errors · {report.credits} credits · {took:.0f} s")

    with ThreadPoolExecutor(cfg.workers) as pool:
        list(pool.map(one, todo))
    return guard
