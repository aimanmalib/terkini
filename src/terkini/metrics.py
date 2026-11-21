"""Eval metrics (PRD §2 H3-H6) from saved runs, hand labels and the answer key. Pure: no network, no clock.

Detection is scored per answer. An answer is "flagged" when the checker marks at least one of its claims outdated.
A flagged answer is a true positive when its hand label says it states an older value than the key.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from statistics import median

from terkini.packs import AnswerKey


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def _detection(rows: list[tuple[bool, bool | None]]) -> dict:
    """rows: (flagged, label) for each labelled answer."""
    tp = sum(f and lab is True for f, lab in rows)
    fp = sum(f and lab is not True for f, lab in rows)
    fn = sum(not f and lab is True for f, lab in rows)
    tn = sum(not f and lab is not True for f, lab in rows)
    return {"labelled": len(rows), "stale": sum(lab is True for _, lab in rows),
            "current": sum(lab is False for _, lab in rows), "no_value": sum(lab is None for _, lab in rows),
            "flagged": tp + fp, "true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn,
            "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn)}


def _dates(runs, labels, key: AnswerKey, window_days: int) -> dict:
    """H5: for stale answers the checker flagged, is the change date quoted, and does it match the key?"""
    key_dates = {k.id: date.fromisoformat(k.effective_date) for k in key.keys if k.effective_date}
    out = Counter()
    for r in runs:
        lab = labels.get(r.answer)
        olds = [x for x in r.report.results if x.verdict == "outdated"]
        if not (lab and lab.stale is True and olds):
            continue
        out["flagged_stale"] += 1
        quoted = [x.effective_date for x in olds if x.effective_date]
        if not quoted:
            continue
        out["date_quoted"] += 1
        want = key_dates.get(r.question_id)
        if want is None:
            out["key_has_no_date"] += 1
        elif want in quoted:
            out["exact"] += 1
        elif any(abs((d - want).days) <= window_days for d in quoted):
            out["within_window"] += 1
        else:
            out["different"] += 1
    return {k: out[k] for k in ("flagged_stale", "date_quoted", "exact", "within_window", "different",
                                "key_has_no_date")} | {"window_days": window_days}


def compute_results(runs, labels: dict, key: AnswerKey, *, usage: dict, window_days: int, pack: str) -> dict:
    results = [x for r in runs for x in r.report.results]
    verdicts = Counter(x.verdict for x in results)
    reasons = Counter(x.reason for x in results if x.verdict == "unverifiable")
    decided = sum(x.verdict != "unverifiable" and x.quote_ok for x in results)
    credits = sum(r.report.credits for r in runs)
    fresh = sum(1 for x in results if x.credits > 0)  # claims that needed Tavily calls (not cache hits)

    rows, per_model = [], {}
    for r in runs:
        flagged = r.report.outdated > 0
        lab = labels.get(r.answer)
        m = per_model.setdefault(r.model, {"answers": 0, "flagged": 0, "stale_label": 0, "true_positive": 0})
        m["answers"] += 1
        m["flagged"] += flagged
        if lab is not None:
            rows.append((flagged, lab.stale))
            m["stale_label"] += lab.stale is True
            m["true_positive"] += flagged and lab.stale is True

    tokens_in = sum(r.prompt_tokens for r in runs)
    tokens_out = sum(r.completion_tokens for r in runs)
    log = usage.get("runs", [])
    first, last = (log[0], log[-1]) if log else ({}, {})
    used = lambda u: (u.get("account") or {}).get("plan_usage")
    return {
        "pack": pack,
        "answers": len(runs),
        "unlabelled": sorted(r.answer for r in runs if r.answer not in labels),
        "models": sorted({r.model for r in runs}),
        "checked_from": min((r.checked_at for r in runs), default=None),
        "checked_to": max((r.checked_at for r in runs), default=None),
        "detection": _detection(rows),
        "per_model": per_model,
        "claims": {"checked": len(results), "current": verdicts["current"], "outdated": verdicts["outdated"],
                   "unverifiable": verdicts["unverifiable"], "unverifiable_reasons": dict(reasons.most_common()),
                   "not_checked": sum(len(r.report.not_checked) for r in runs),
                   "errors": sum(len(r.report.errors) for r in runs),
                   "skipped_not_time_sensitive": sum(r.report.skipped for r in runs)},
        "evidence": {"decided_with_exact_quote": decided, "share_of_checked": _ratio(decided, len(results))},
        "effective_dates": _dates(runs, labels, key, window_days),
        "cost": {
            "tavily_credits_from_responses": credits,
            "claims_needing_tavily": fresh,
            "credits_per_claim_needing_tavily": _ratio(credits, fresh),
            "credits_per_checked_claim": _ratio(credits, len(results)),
            "tavily_plan_usage_before": used(first.get("tavily_usage_before") or {}),
            "tavily_plan_usage_after": used(last.get("tavily_usage_after") or {}),
            "gateway_calls": sum(r.gateway_calls for r in runs),
            "prompt_tokens": tokens_in, "completion_tokens": tokens_out,
            "tokens_per_checked_claim": _ratio(tokens_in + tokens_out, len(results)),
            "gateway_budget_usd_after": (last.get("gateway_after") or {}).get("budget_usd"),
            "p50_seconds_per_answer": round(median(r.seconds for r in runs), 1) if runs else None,
        },
    }
