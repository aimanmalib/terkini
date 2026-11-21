"""Eval baselines (docs/EVAL.md): what the same claims give without Terkini's checks.

1. Model only: the judge model decides each claim from its own knowledge, with no official pages and no quote check.
   One gateway call per claim, no Tavily credits. Verdicts are saved to eval/<pack>/baseline-model-only.json.
2. Naive page rule: trust the official page the checker found and flag a claim when its value is not written in that
   page's quote. Computed from the saved runs: no network. Claims with no quoted official page are not flagged.

The saved runs do not keep Tavily's ranked result list, so a "top search result decides" rule cannot be replayed
without new credits; rule 2 uses the page the judge cited instead (docs/02-DECISIONS.md D-020).
Each row reports precision and recall as "x of y" with a 95% Wilson score interval.
"""

from __future__ import annotations

import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from string import Template

from terkini.extractor import ModelOutputError, load_prompts, parse_json_object
from terkini.gateway import GatewayError
from terkini.metrics import _detection


def wilson(x: int, n: int, z: float) -> list[float] | None:
    """95% Wilson score interval for x successes in n trials (z = 1.96), rounded to 3 places."""
    if not n:
        return None
    p = x / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def claim_key(answer: str, i: int) -> str:
    return f"{answer}#{i}"


def _norm(s: str) -> str:
    """Lower case, no spaces or thousands commas: 'RM 1,700' and 'rm1700' compare equal."""
    return re.sub(r"[\s,]", "", s.lower())


def naive_verdicts(runs) -> dict[str, str]:
    """Rule 2: outdated when the claim's value is not in the official quote, current when it is; no quote = absent."""
    out = {}
    for r in runs:
        for i, x in enumerate(r.report.results):
            if not (x.quote_ok and x.evidence_quote and x.claim.value):
                continue
            out[claim_key(r.answer, i)] = "current" if _norm(x.claim.value) in _norm(x.evidence_quote) else "outdated"
    return out


def judge_without_pages(gateway, model: str, claim, *, country: str, today: str, fallbacks: list[str] | None,
                        prompts: dict) -> tuple[dict, int, int]:
    p = prompts["judge_no_evidence"]
    system = Template(p["system"]).substitute(country=country, today=today).strip()
    user = Template(p["user"]).substitute(claim=claim.claim, category=claim.category, value=claim.value,
                                          unit=claim.unit, stated_date=claim.stated_date or "none").strip()
    res = gateway.chat(model, [{"role": "system", "content": system}, {"role": "user", "content": user}],
                       fallbacks=fallbacks, json_mode=True)
    data = parse_json_object(res.text)
    verdict = data.get("verdict") if data.get("verdict") in ("current", "outdated", "unverifiable") else "unverifiable"
    return ({"verdict": verdict, "current_value": str(data.get("current_value") or ""), "model": res.model},
            res.prompt_tokens, res.completion_tokens)


def run_model_only(runs, gateway, *, model: str, fallbacks: list[str], country: str, path: Path, workers: int,
                   root: Path, log=print) -> list[str]:
    """Rule 1 for every checked claim in the saved runs; resumes from the saved file. Returns failures."""
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "model": model, "prompt": "config/prompts.toml [judge_no_evidence]", "calls": 0, "prompt_tokens": 0,
        "completion_tokens": 0, "verdicts": {}}
    prompts = load_prompts(root)
    jobs = [(claim_key(r.answer, i), x.claim, r.report.checked_on.isoformat())
            for r in runs for i, x in enumerate(r.report.results) if claim_key(r.answer, i) not in saved["verdicts"]]

    def one(job):
        key, claim, today = job
        try:
            v, pt, ct = judge_without_pages(gateway, model, claim, country=country, today=today, fallbacks=fallbacks,
                                            prompts=prompts)
        except (GatewayError, ModelOutputError) as e:
            return key, None, str(e)[:200]
        return key, (v, pt, ct), None

    def write():
        saved["verdicts"] = dict(sorted(saved["verdicts"].items()))
        saved["checked_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        path.write_text(json.dumps(saved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    failed = []
    with ThreadPoolExecutor(workers) as pool:
        for key, got, err in pool.map(one, jobs):
            if err:
                failed.append(f"{key}: {err}")
                continue
            v, pt, ct = got
            saved["verdicts"][key] = v
            saved["calls"] += 1
            saved["prompt_tokens"] += pt
            saved["completion_tokens"] += ct
            if saved["calls"] % 20 == 0:
                write()  # a stopped run keeps what it has; the next run resumes
    write()
    log(f"baseline: {len(jobs) - len(failed)} claims judged without pages, {len(failed)} failed")
    return failed


def _row(name: str, flags: dict[str, bool], runs, labels: dict, z: float, note: str) -> dict:
    rows = [(flags[r.answer], labels[r.answer].stale) for r in runs if r.answer in labels]
    d = _detection(rows)
    tp, fl, st = d["true_positive"], d["flagged"], d["stale"]
    return {"name": name, "note": note, "n_answers": d["labelled"], **d,
            "precision_text": f"{tp} of {fl}", "precision_ci95": wilson(tp, fl, z),
            "recall_text": f"{tp} of {st}", "recall_ci95": wilson(tp, st, z)}


def _flags(runs, verdicts: dict[str, str]) -> dict[str, bool]:
    return {r.answer: any(verdicts.get(claim_key(r.answer, i)) == "outdated" for i in range(len(r.report.results)))
            for r in runs}


def compute_baselines(runs, labels: dict, model_only: dict | None, *, z: float, hybrid: dict | None = None) -> dict:
    """Terkini, hybrid, model-only and naive-rule detection on the same answers and the same claims."""
    terkini = {r.answer: r.report.outdated > 0 for r in runs}
    rows = [_row("terkini", terkini, runs, labels, z, "Tavily evidence, judge, exact-quote check (the main result).")]
    if model_only and hybrid:
        from terkini.hybrideval import hybrid_verdicts
        v, counts = hybrid_verdicts(runs, model_only, hybrid)
        rows.append(_row("hybrid", _flags(runs, v), runs, labels, z,
                         "Main check, then the model proposes a current value and an official sentence must state it "
                         "(D-022).") | {"claims": counts, "credits_from_responses": hybrid["credits_from_responses"]})
    if model_only:
        v = {k: x["verdict"] for k, x in model_only["verdicts"].items()}
        r = _row("model_only", _flags(runs, v), runs, labels, z,
                 "Same judge model, same claims, no official pages, no quote check. 0 Tavily credits.")
        r |= {"model": model_only["model"], "claims_judged": len(v),
              "claims_outdated": sum(x == "outdated" for x in v.values()),
              "claims_unverifiable": sum(x == "unverifiable" for x in v.values()),
              "prompt_tokens": model_only["prompt_tokens"], "completion_tokens": model_only["completion_tokens"]}
        rows.append(r)
    naive = naive_verdicts(runs)
    r = _row("naive_page_rule", _flags(runs, naive), runs, labels, z,
             "Flag a claim when its value is not in the official quote the checker found. From saved runs, 0 credits.")
    rows.append(r | {"claims_with_official_quote": len(naive),
                     "claims_outdated": sum(x == "outdated" for x in naive.values())})
    return {"ci": "95% Wilson score interval", "rows": rows}


def saved_results(pack, root: Path) -> dict:
    """results.json content: metrics from the saved runs, labels and key, plus the baselines (no network)."""
    from terkini.evaluate import eval_dir, load_eval_config, load_labels, load_runs
    from terkini.metrics import compute_results
    from terkini.packs import load_key
    cfg, d = load_eval_config(root), eval_dir(pack, root)
    usage = json.loads((d / "usage.json").read_text()) if (d / "usage.json").exists() else {"runs": []}
    runs, labels = load_runs(pack, root), load_labels(pack, root)
    mo = d / cfg.baseline_model_only
    from terkini.hybrid import load_hybrid_config
    hy = d / load_hybrid_config(root).eval.results
    results = compute_results(runs, labels, load_key(pack, root), usage=usage, window_days=cfg.date_window_days,
                              pack=pack.id)
    return results | {"baselines": compute_baselines(runs, labels, json.loads(mo.read_text()) if mo.exists() else None,
                                                     z=cfg.ci_z,
                                                     hybrid=json.loads(hy.read_text()) if hy.exists() else None)}
