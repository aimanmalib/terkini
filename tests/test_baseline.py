"""Eval baselines (src/terkini/baseline.py): Wilson interval, naive page rule, model-only judge, results rows."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import TODAY, FakeGateway

from terkini.baseline import (
    claim_key,
    compute_baselines,
    judge_without_pages,
    naive_verdicts,
    run_model_only,
    wilson,
)
from terkini.checker import AnswerReport
from terkini.claims import Claim, ClaimResult
from terkini.evaluate import AnswerRun, Label, eval_dir, load_runs
from terkini.extractor import load_prompts
from terkini.packs import REPO_ROOT, load_pack


def test_wilson_matches_the_textbook_interval():
    assert wilson(5, 10, 1.96) == [0.237, 0.763]
    assert wilson(0, 10, 1.96)[0] == 0.0
    assert wilson(10, 10, 1.96)[1] == 1.0
    assert wilson(0, 0, 1.96) is None


def _res(value: str, quote: str, verdict: str = "current") -> ClaimResult:
    return ClaimResult(claim=Claim(claim=f"rate is {value}", category="wages", value=value), verdict=verdict,
                       evidence_quote=quote, quote_ok=bool(quote), score=50, checked_on=TODAY)


def _run(name: str, results: list[ClaimResult]) -> AnswerRun:
    rep = AnswerReport(pack="my", checked_on=TODAY, results=results,
                       outdated=sum(x.verdict == "outdated" for x in results))
    return AnswerRun(answer=name, question_id=name.split("--")[0], model="m/x", checked_at="2026-11-21T01:00:00Z",
                     seconds=1.0, prompt_tokens=1, completion_tokens=1, gateway_calls=1, report=rep)


def test_naive_rule_flags_a_value_missing_from_the_quote_and_ignores_unquoted_claims():
    runs = [_run("a", [_res("RM 1,500", "The minimum wage is RM1500 a month."),     # same value after normalising
                       _res("6%", "The rate is 8% from 1 March 2024."),             # value missing -> outdated
                       _res("RM1,700", "")])]                                       # no quote -> no verdict
    assert naive_verdicts(runs) == {"a#0": "current", "a#1": "outdated"}


def test_baseline_rows_score_the_same_answers_with_x_of_y_and_intervals():
    runs = [_run("q1--a", [_res("6%", "now 8%", "outdated")]),   # Terkini flags; stale
            _run("q1--b", [_res("8%", "now 8%")]),               # current
            _run("q2--a", [_res("RM1", "RM2")])]                 # stale; naive flags, Terkini misses
    labels = {x.answer: x for x in [Label(answer="q1--a", stale=True), Label(answer="q1--b", stale=False),
                                    Label(answer="q2--a", stale=True)]}
    model_only = {"model": "j", "prompt_tokens": 3, "completion_tokens": 2,
                  "verdicts": {claim_key("q1--a", 0): {"verdict": "current"},
                               claim_key("q1--b", 0): {"verdict": "outdated"},
                               claim_key("q2--a", 0): {"verdict": "outdated"}}}
    rows = {r["name"]: r for r in compute_baselines(runs, labels, model_only, z=1.96)["rows"]}
    assert rows["terkini"]["precision_text"] == "1 of 1" and rows["terkini"]["recall_text"] == "1 of 2"
    assert rows["model_only"]["precision_text"] == "1 of 2" and rows["model_only"]["recall_text"] == "1 of 2"
    assert rows["naive_page_rule"]["precision_text"] == "2 of 2" and rows["naive_page_rule"]["recall_text"] == "2 of 2"
    assert rows["model_only"]["precision_ci95"] == wilson(1, 2, 1.96)
    assert "model_only" not in {r["name"] for r in compute_baselines(runs, labels, None, z=1.96)["rows"]}


def test_model_only_judge_gets_no_pages_and_unknown_verdicts_become_unverifiable():
    claim = Claim(claim="The rate is 6%.", category="indirect-tax", value="6%", unit="percent")
    gw = FakeGateway({"verdict": "outdated", "current_value": "8%"}, {"verdict": "maybe"})
    p = load_prompts()
    v, _, _ = judge_without_pages(gw, "j", claim, country="Malaysia", today="2026-11-21", fallbacks=["f"], prompts=p)
    assert v["verdict"] == "outdated" and v["current_value"] == "8%"
    text = json.dumps(gw.calls[0]["messages"])
    assert "PAGE" not in text and "URL:" not in text and gw.calls[0]["json_mode"]
    v, _, _ = judge_without_pages(gw, "j", claim, country="Malaysia", today="2026-11-21", fallbacks=None, prompts=p)
    assert v["verdict"] == "unverifiable"


def test_model_only_run_resumes_from_the_saved_file(tmp_path: Path):
    runs = [_run("a", [_res("6%", ""), _res("7%", "")])]
    path = tmp_path / "mo.json"
    path.write_text(json.dumps({"model": "j", "calls": 1, "prompt_tokens": 10, "completion_tokens": 5,
                                "verdicts": {"a#0": {"verdict": "current"}}}))
    gw = FakeGateway({"verdict": "outdated"})
    assert run_model_only(runs, gw, model="j", fallbacks=[], country="Malaysia", path=path, workers=2,
                          root=REPO_ROOT, log=lambda *_: None) == []
    saved = json.loads(path.read_text())
    assert len(gw.calls) == 1 and saved["calls"] == 2 and saved["verdicts"]["a#1"]["verdict"] == "outdated"


def test_saved_model_only_verdicts_cover_every_checked_claim():
    pack = load_pack("my")
    path = eval_dir(pack) / "baseline-model-only.json"
    keys = {claim_key(r.answer, i) for r in load_runs(pack) for i in range(len(r.report.results))}
    assert set(json.loads(path.read_text())["verdicts"]) == keys
