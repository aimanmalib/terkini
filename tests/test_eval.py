"""Eval: answer files, live-check orchestration over fakes, and the metrics (PRD §2 H2-H6). No network."""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
from conftest import TODAY, FakeGateway, FakeTavily, extract_body, search_body

from terkini.cache import Cache
from terkini.checker import AnswerReport
from terkini.claims import Claim, ClaimResult
from terkini.evaluate import (
    Answer,
    AnswerRun,
    Label,
    answer_name,
    ask_all,
    check_all,
    eval_dir,
    load_answers,
    load_eval_config,
    load_labels,
    load_runs,
)
from terkini.metrics import compute_results
from terkini.packs import REPO_ROOT, AnswerKey, KeyEntry, load_key, load_pack


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A copy of the repo's config, packs and eval questions, with no saved answers or runs."""
    for d in ("config", "packs"):
        shutil.copytree(REPO_ROOT / d, tmp_path / d)
    (tmp_path / "eval" / "my").mkdir(parents=True)
    for f in ("questions.yaml", "key.yaml"):
        shutil.copy(REPO_ROOT / "eval" / "my" / f, tmp_path / "eval" / "my" / f)
    return tmp_path


def test_answer_name_is_question_and_model_slug():
    assert answer_name("my-01", "rv/moonshotai/Kimi-K3.1-Pro") == "my-01--kimi-k3-1-pro"


def test_ask_writes_one_file_per_question_and_model_and_skips_saved(root):
    pack = load_pack("my", root)
    gw = FakeGateway("RM1,500 a month.", "RM1,700 a month.")
    assert ask_all(gw, pack, ["a/m1", "b/m2"], only=["my-01"], root=root, log=lambda _: None) == []
    answers = load_answers(pack, root)
    assert [a.name for a in answers] == ["my-01--m1", "my-01--m2"]
    assert gw.calls[0]["fallbacks"] is None  # an eval answer must come from the model asked
    assert ask_all(FakeGateway(), pack, ["a/m1", "b/m2"], only=["my-01"], root=root, log=lambda _: None) == []


def test_check_all_saves_a_run_with_tokens_and_credits(root):
    pack = load_pack("my", root)
    cat = next(c for c in pack.categories if c.volatile)
    gov = next(d for d in pack.domains if d.label == "government")
    url = f"https://www.{gov.domain}/wage"
    page = "The minimum wage is RM1,700 per month with effect from 1 February 2025."
    claims = {"claims": [{"claim": "The minimum wage is RM1,500 per month.", "category": cat.id, "value": "RM1,500",
                          "time_sensitive": True}]}
    judge = {"verdict": "outdated", "current_value": "RM1,700", "evidence_quote": page.rstrip("."),
             "effective_date_text": "1 February 2025", "effective_date": "2025-02-01", "source_url": url}
    tv = FakeTavily()
    tv.searches.append(search_body((url, "2025-01-20")))
    tv.extracts.append(extract_body({url: page}))
    a = Answer(name="my-01--m1", question_id="my-01", question="q", model="a/m1", answered_by="m1", asked_at="t",
               answer="RM1,500 a month.", prompt_tokens=1, completion_tokens=1, seconds=1.0)
    with _cache() as cache:
        guard = check_all([a], pack, tavily=tv.client(), gateway=FakeGateway(claims, judge), cache=cache, today=TODAY,
                          root=root, log=lambda _: None)
    run = load_runs(pack, root)[0]
    assert run.report.outdated == 1 and run.report.credits == 2 and guard.spent_this_run == 2
    assert run.gateway_calls == 2 and run.prompt_tokens == 20
    assert guard.budget.limits.per_run == guard.budget.allocation.eval_my


class _cache:
    def __enter__(self):
        self.c = Cache(":memory:")
        return self.c

    def __exit__(self, *_):
        self.c.close()


def _run(name: str, qid: str, verdicts: list[str], eff: date | None = None, credits: int = 3) -> AnswerRun:
    results = [ClaimResult(claim=Claim(claim=f"{name} {i}", category="wages"), verdict=v, quote_ok=v != "unverifiable",
                           effective_date=eff if v == "outdated" else None, score=50, checked_on=TODAY,
                           credits=credits if i == 0 else 0, reason="" if v != "unverifiable" else "none")
               for i, v in enumerate(verdicts)]
    rep = AnswerReport(pack="my", checked_on=TODAY, results=results, outdated=verdicts.count("outdated"),
                       credits=credits)
    return AnswerRun(answer=name, question_id=qid, model="m/" + name[-1], checked_at="2026-11-21T01:00:00Z",
                     seconds=10.0, prompt_tokens=100, completion_tokens=10, gateway_calls=2, report=rep)


def test_metrics_precision_recall_dates_and_cost():
    key = AnswerKey(pack="my", keys=[KeyEntry(id="q1", value="v", url="u", quote="x", effective_date="2025-02-01",
                                              read_at="2026-11-20"),
                                     KeyEntry(id="q2", value="v", url="u", quote="x", read_at="2026-11-20")])
    runs = [_run("q1-a", "q1", ["outdated", "current"], date(2025, 2, 1)),   # stale, flagged, exact date
            _run("q1-b", "q1", ["outdated"], date(2025, 2, 20)),             # stale, flagged, date within 31 days
            _run("q2-a", "q2", ["current"]),                                 # stale, missed
            _run("q2-b", "q2", ["outdated", "unverifiable"]),                # current, flagged: false positive
            _run("q2-c", "q2", ["unverifiable"])]                            # no value, not flagged
    labels = {x.answer: x for x in [Label(answer="q1-a", stale=True), Label(answer="q1-b", stale=True),
                                    Label(answer="q2-a", stale=True), Label(answer="q2-b", stale=False),
                                    Label(answer="q2-c", stale=None)]}
    r = compute_results(runs, labels, key, usage={"runs": []}, window_days=31, pack="my")
    d = r["detection"]
    assert (d["true_positive"], d["false_positive"], d["false_negative"], d["true_negative"]) == (2, 1, 1, 1)
    assert d["precision"] == 0.667 and d["recall"] == 0.667
    assert r["claims"]["checked"] == 7 and r["claims"]["unverifiable"] == 2
    assert r["evidence"]["decided_with_exact_quote"] == 5
    e = r["effective_dates"]
    assert (e["flagged_stale"], e["date_quoted"], e["exact"], e["within_window"]) == (2, 2, 1, 1)
    assert r["cost"]["tavily_credits_from_responses"] == 15 and r["cost"]["claims_needing_tavily"] == 5
    assert r["cost"]["p50_seconds_per_answer"] == 10.0


def test_saved_results_are_computed_from_the_saved_runs():
    """eval/my/results.json must be what the saved runs, labels and key give (no hand-edited numbers)."""
    pack = load_pack("my")
    cfg = load_eval_config()
    path = eval_dir(pack) / cfg.results
    if not path.exists():
        pytest.skip("no eval results saved yet")
    usage_path = eval_dir(pack) / "usage.json"
    usage = json.loads(usage_path.read_text()) if usage_path.exists() else {"runs": []}
    again = compute_results(load_runs(pack), load_labels(pack), load_key(pack), usage=usage,
                            window_days=cfg.date_window_days, pack=pack.id)
    assert json.loads(path.read_text()) == json.loads(json.dumps(again))
