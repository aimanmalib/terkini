"""`terkini ask` and `terkini eval` (PRD §2 H2-H6). Live calls need TAVILY_API_KEY and the Bifrost settings in the
environment (or .env / .env.bifrost); `eval --score-only` needs neither."""

from __future__ import annotations

import os
import sys
from contextlib import closing
from datetime import UTC, datetime

import httpx

from terkini.packs import REPO_ROOT, load_key, load_pack


def _env() -> None:
    from terkini.gateway import load_env_file
    load_env_file(REPO_ROOT / ".env")
    load_env_file(REPO_ROOT / ".env.bifrost")


def ask_command(args) -> int:
    from terkini.evaluate import ask_all
    from terkini.gateway import Gateway, load_gateway_config
    _env()
    pack = load_pack(args.pack)
    models = args.models.split(",") if args.models else load_gateway_config().models.models
    failed = ask_all(Gateway(), pack, models, only=args.only.split(",") if args.only else None, force=args.force)
    for f in failed:
        print(f"ask: failed {f}", file=sys.stderr)
    return 1 if failed else 0


def usage_numbers(u: dict) -> dict:
    """Keep only the credit totals from Tavily GET /usage, never names or ids."""
    return {k: {kk: vv for kk, vv in v.items() if isinstance(vv, (int, float))} for k, v in u.items()
            if isinstance(v, dict)}


def gateway_usage() -> dict:
    """Spend and token counters of the virtual key, from the Bifrost governance API (needs the setup token)."""
    from terkini.gateway import load_gateway_config
    base, token = os.environ.get("BIFROST_URL", ""), os.environ.get("BIFROST_SETUP_TOKEN", "")
    if not base or not token:
        return {}
    try:
        r = httpx.get(f"{base.rstrip('/')}/api/governance/virtual-keys", headers={"x-bifrost-setup-token": token},
                      timeout=30)
    except httpx.HTTPError:
        return {}
    name = load_gateway_config().virtual_key["name"]
    vk = next((k for k in (r.json().get("virtual_keys") or []) if k.get("name") == name), None) if r.is_success else None
    if not vk:
        return {}
    rl = vk.get("rate_limit") or {}
    return {"budget_usd": sum(b.get("current_usage", 0) for b in vk.get("budgets") or []),
            "tokens_this_window": rl.get("token_current_usage"), "requests_this_window": rl.get("request_current_usage"),
            "window": rl.get("token_reset_duration")}


def eval_command(args) -> int:
    from terkini.evaluate import (
        check_all,
        eval_dir,
        load_answers,
        load_eval_config,
        load_labels,
        load_runs,
        write_json,
    )
    from terkini.metrics import compute_results
    pack = load_pack(args.pack)
    cfg = load_eval_config()
    side = eval_dir(pack) / "usage.json"
    if not args.score_only:
        from terkini.cache import Cache
        from terkini.gateway import Gateway
        from terkini.tavily import Tavily
        from terkini.verify import load_verify_config
        _env()
        if not os.environ.get("TAVILY_API_KEY"):
            print("eval: live checks need TAVILY_API_KEY (use --score-only to recompute results)", file=sys.stderr)
            return 2
        tavily, today = Tavily(), datetime.now(UTC).date()
        before, gw_before = usage_numbers(tavily.usage()), gateway_usage()
        with closing(Cache(REPO_ROOT / load_verify_config().cache_path)) as cache:
            guard = check_all(load_answers(pack), pack, tavily=tavily, gateway=Gateway(), cache=cache, today=today,
                              force=args.force, keep_errors=args.keep_errors)
        import json
        log = json.loads(side.read_text()) if side.exists() else {"runs": []}
        log["runs"].append({"at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "credits_from_responses":
                            guard.spent_this_run, "tavily_usage_before": before,
                            "tavily_usage_after": usage_numbers(tavily.usage()), "gateway_before": gw_before,
                            "gateway_after": gateway_usage()})
        write_json(side, log)
    import json
    usage = json.loads(side.read_text()) if side.exists() else {"runs": []}
    results = compute_results(load_runs(pack), load_labels(pack), load_key(pack), usage=usage,
                              window_days=cfg.date_window_days, pack=pack.id)
    write_json(eval_dir(pack) / cfg.results, results)
    d = results["detection"]
    print(f"eval: {results['answers']} answers · {results['claims']['checked']} claims · precision {d['precision']} · "
          f"recall {d['recall']} · results in {(eval_dir(pack) / cfg.results).relative_to(REPO_ROOT)}")
    return 0
