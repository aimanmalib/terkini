"""Hybrid eval (D-022): replay the hybrid step over the saved eval runs.

The model's proposals are the saved model-only baseline (eval/<pack>/baseline-model-only.json): the same judge model
and the same prompt the live hybrid step uses, on the same claims. Only claims the main check did not flag, with a
proposed "outdated" value, cost Tavily credits: one search and one extract per distinct (claim, proposed value).
The evidence is saved to eval/<pack>/hybrid.json (quotes cut to 500 characters, D13); verdicts are recomputed from
that file with no network.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from terkini.baseline import claim_key
from terkini.claims import HybridEvidence
from terkini.credits import CreditLimitReached
from terkini.hybrid import HybridConfig, decide, prove
from terkini.tavily import TavilyHTTPError

QUOTE_CHARS = 500


def evidence_key(claim_text_key: str, proposal: str) -> str:
    return f"{claim_text_key} => {proposal}"


def candidates(runs, model_only: dict) -> list[tuple[str, object, object, str]]:
    """(claim key, run, claim result, proposal) for claims not flagged by the main check that the model calls outdated."""
    out = []
    for r in runs:
        for i, x in enumerate(r.report.results):
            v = model_only["verdicts"].get(claim_key(r.answer, i))
            if x.verdict != "outdated" and v and v["verdict"] == "outdated" and v["current_value"]:
                out.append((claim_key(r.answer, i), r, x, v["current_value"]))
    return out


def run_hybrid(runs, model_only: dict, verifier, cfg: HybridConfig, path: Path, *, usage_before: dict | None = None,
               usage=None, log=print) -> list[str]:
    """Prove every distinct proposal once; resumes from the saved file. Returns failures."""
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "proposals": "eval baseline-model-only.json (config/prompts.toml [judge_no_evidence])",
        "config": "config/hybrid.toml", "credits_from_responses": 0, "evidence": {}}
    jobs = {}
    for _, _, x, proposal in candidates(runs, model_only):
        k = evidence_key(x.claim.key, proposal)
        if k not in saved["evidence"]:
            jobs.setdefault(k, (x.claim, proposal))

    def one(item):
        k, (claim, proposal) = item
        try:
            return k, prove(verifier, claim, proposal, cfg), None
        except (TavilyHTTPError, CreditLimitReached) as e:
            return k, None, f"{type(e).__name__}: {str(e)[:200]}"

    failed = []
    with ThreadPoolExecutor(cfg.eval.workers) as pool:
        for k, ev, err in pool.map(one, jobs.items()):
            if err:
                failed.append(f"{k}: {err}")
                continue
            saved["evidence"][k] = ev.model_copy(update={"quote": ev.quote[:QUOTE_CHARS]}).model_dump(mode="json")
            saved["credits_from_responses"] += ev.credits
    saved["evidence"] = dict(sorted(saved["evidence"].items()))
    saved["checked_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if usage_before is not None:
        saved.setdefault("tavily_usage", []).append({"before": usage_before, "after": usage() if usage else None})
    path.write_text(json.dumps(saved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"hybrid: {len(jobs) - len(failed)} proposals searched, {len(failed)} failed, "
        f"{saved['credits_from_responses']} credits in total")
    return failed


def hybrid_verdicts(runs, model_only: dict, saved: dict) -> tuple[dict[str, str], dict]:
    """Verdict of every claim after the hybrid step (main verdict where it did not run), plus counts."""
    verdicts = {claim_key(r.answer, i): x.verdict for r in runs for i, x in enumerate(r.report.results)}
    counts = {"proposals": 0, "searched": 0, "quoted": 0, "changed_to_outdated": 0, "kept_by_date": 0}
    for key, _, x, proposal in candidates(runs, model_only):
        counts["proposals"] += 1
        raw = saved["evidence"].get(evidence_key(x.claim.key, proposal))
        if raw is None:
            continue
        ev = HybridEvidence.model_validate(raw)
        counts["searched"] += bool(ev.query)
        counts["quoted"] += bool(ev.quote)
        verdict, _ = decide(x, ev)
        counts["changed_to_outdated"] += verdict == "outdated"
        counts["kept_by_date"] += bool(ev.quote) and verdict != "outdated"
        verdicts[key] = verdict
    return verdicts, counts
