""""How this check ran" for one case on the recorded-run page (PRAHANTAR J4): what Terkini sent to Tavily and Bifrost.

Built only from what was saved during the run plus the settings that produced the requests. No new calls.

- Tavily: the search settings come from config/verify.toml and the pack (the code sends them unchanged). Each claim's
  query is `build_query(claim)`, the exact string the checker sends. A recording also saved every search it made, so
  its search depths come from that log; an eval run saved only the credits per claim, so depths are `None` there.
- Bifrost: a recording saved every gateway call (model asked for, model that answered, tokens, seconds), so a
  fallback is visible per call. An eval run saved the answer call and the totals for the check, so `fallback` is
  `None` (not recorded) for the check.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from terkini.checker import AnswerReport
from terkini.evaluate import Answer, AnswerRun, eval_dir, load_eval_config
from terkini.gateway import load_gateway_config
from terkini.packs import REPO_ROOT, Pack
from terkini.replay import Cassette
from terkini.verify import build_query, load_verify_config


def _short(model: str) -> str:
    """Model id without the gateway's provider prefix ("rv/GLM-5.3" -> "GLM-5.3"), as the gateway reports it back."""
    return model.split("/", 1)[1] if "/" in model else model


def _call(step: str, model: str, answered_by: str, tokens_in: int, tokens_out: int, seconds: float | None,
          calls: int = 1) -> dict:
    return {"step": step, "model": model, "answered_by": answered_by or None,
            "fallback": (_short(model) != answered_by) if answered_by else None,
            "calls": calls, "tokens_in": tokens_in, "tokens_out": tokens_out, "seconds": seconds}


def _tavily(report: AnswerReport, pack: Pack, root: Path, searches: list | None) -> dict:
    s = load_verify_config(root).search
    by_query: dict[str, list] = defaultdict(list)
    for call in searches or []:
        by_query[call.query].append(call)
    claims = []
    for i, r in enumerate(report.results):
        query = build_query(r.claim, s.max_query_chars)
        category = pack.category(r.claim.category)
        volatile = bool(category and category.volatile)
        # The checker searches once, and once more at the retry depth when no official page came back (verify.py).
        mine = []
        queue = by_query[query]
        if searches is not None and r.credits and queue:
            mine.append(queue.pop(0))
            if not _found_official(mine[0], pack) and queue:
                mine.append(queue.pop(0))
        claims.append({
            "n": i + 1,
            "query": query,
            "max_age_hours": s.volatile_max_age_hours if volatile and not r.cached_copy else None,
            "cached_copy": r.cached_copy,
            "depths": [c.search_depth for c in mine] if searches is not None else None,
            "from_cache": r.credits == 0,
            "credits": r.credits,
        })
    return {"topic": s.topic, "include_domains": pack.domain_names, "include_domains_mode": s.include_domains_mode,
            "max_results": s.max_results, "search_depth": s.search_depth, "retry_depth": s.retry_depth,
            "log": "recorded" if searches is not None else "settings", "claims": claims, "credits": report.credits}


def _found_official(call, pack: Pack) -> bool:
    return any(pack.domain_for(r.get("url", "")) is not None for r in call.results)


def _spend(pack: Pack, root: Path) -> float | None:
    """Virtual-key spend Bifrost reported after the eval run (docs/EVAL.md: it has no price list for these ids)."""
    path = eval_dir(pack, root) / load_eval_config(root).results
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("cost", {}).get("gateway_budget_usd_after")


def trace_recording(c: Cassette, report: AnswerReport, pack: Pack, root: Path = REPO_ROOT) -> dict:
    a = c.ask
    calls = [_call("answer", a.model, a.answered_by, a.prompt_tokens, a.completion_tokens, a.seconds)]
    for i, ch in enumerate(c.chats):
        # The checker asks the extractor once, then the judge once per claim it sends to official pages.
        calls.append(_call("extract" if i == 0 else "judge", ch.model, ch.answered_by, ch.prompt_tokens,
                           ch.completion_tokens, ch.seconds))
    return {"tavily": _tavily(report, pack, root, c.searches), "gateway": _gateway(calls, pack, root, "recorded")}


def trace_eval(a: Answer, run: AnswerRun, pack: Pack, root: Path = REPO_ROOT) -> dict:
    models = load_gateway_config(root).models
    calls = [_call("answer", a.model, a.answered_by, a.prompt_tokens, a.completion_tokens, a.seconds),
             _call("check", models.judge, "", run.prompt_tokens, run.completion_tokens, run.seconds,
                   calls=run.gateway_calls)]
    return {"tavily": _tavily(run.report, pack, root, None), "gateway": _gateway(calls, pack, root, "totals")}


def _gateway(calls: list[dict], pack: Pack, root: Path, log: str) -> dict:
    return {"log": log, "calls": calls, "fallbacks": load_gateway_config(root).models.fallbacks,
            "total_calls": sum(c["calls"] for c in calls),
            "tokens_in": sum(c["tokens_in"] for c in calls), "tokens_out": sum(c["tokens_out"] for c in calls),
            "spend_usd": _spend(pack, root)}
