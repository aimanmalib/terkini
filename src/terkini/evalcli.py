"""`terkini ask` and `terkini eval` (PRD §2 H2-H6). Live calls need TAVILY_API_KEY and the Bifrost settings in the
environment (or .env / .env.bifrost); `eval --score-only` needs neither."""

from __future__ import annotations

import os
import sys
from contextlib import closing
from datetime import UTC, datetime

import httpx

from terkini.packs import REPO_ROOT, load_pack


def _env() -> None:
    from terkini.gateway import load_env_file
    load_env_file(REPO_ROOT / ".env")
    load_env_file(REPO_ROOT / ".env.bifrost")


def _env_and_guard(command: str) -> int | None:
    """Load the environment, then run the budget guard if config/guard.toml turns it on (D-025)."""
    from terkini.guard import preflight
    _env()
    return preflight(command, REPO_ROOT)


def guard_command(args) -> int:
    """Run the Bifrost Meter guard once with Terkini's key, whether or not config/guard.toml turns it on."""
    from terkini.guard import load_guard_config, run_guard
    _env()
    cfg = load_guard_config(REPO_ROOT)
    if args.min_remaining is not None:
        cfg = cfg.model_copy(update={"min_remaining": args.min_remaining})
    r = run_guard(cfg, REPO_ROOT)
    print(r.sentence, file=sys.stderr if r.code == 1 else sys.stdout)
    return r.code


def ask_command(args) -> int:
    from terkini.evaluate import ask_all
    from terkini.gateway import Gateway, load_gateway_config
    if (stop := _env_and_guard("ask")) is not None:
        return stop
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
        write_json,
    )
    pack = load_pack(args.pack)
    cfg = load_eval_config()
    side = eval_dir(pack) / "usage.json"
    if not args.score_only:
        from terkini.cache import Cache
        from terkini.gateway import Gateway
        from terkini.tavily import Tavily
        from terkini.verify import load_verify_config
        if (stop := _env_and_guard("eval")) is not None:
            return stop
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
    from terkini.baseline import saved_results
    results = saved_results(pack, REPO_ROOT)
    write_json(eval_dir(pack) / cfg.results, results)
    d = results["detection"]
    print(f"eval: {results['answers']} answers · {results['claims']['checked']} claims · precision {d['precision']} · "
          f"recall {d['recall']} · results in {(eval_dir(pack) / cfg.results).relative_to(REPO_ROOT)}")
    return 0


def baseline_command(args) -> int:
    """Judge every saved claim without official pages (one gateway call per claim, no Tavily), then rewrite results."""
    from terkini.baseline import run_model_only, saved_results
    from terkini.evaluate import eval_dir, load_eval_config, load_runs, write_json
    from terkini.gateway import Gateway, load_gateway_config
    pack = load_pack(args.pack)
    cfg = load_eval_config()
    failed = []
    if not args.score_only:
        if (stop := _env_and_guard("baseline")) is not None:
            return stop
        models = load_gateway_config().models
        failed = run_model_only(load_runs(pack), Gateway(), model=models.judge, fallbacks=models.fallbacks,
                                country=pack.name, path=eval_dir(pack) / cfg.baseline_model_only,
                                workers=cfg.workers, root=REPO_ROOT)
        for f in failed:
            print(f"baseline: failed {f}", file=sys.stderr)
    results = saved_results(pack, REPO_ROOT)
    write_json(eval_dir(pack) / cfg.results, results)
    for r in results["baselines"]["rows"]:
        print(f"baseline: {r['name']}: precision {r['precision_text']} {r['precision_ci95']} · "
              f"recall {r['recall_text']} {r['recall_ci95']}")
    return 1 if failed else 0


def hybrid_command(args) -> int:
    """Run the hybrid step (D-022) over the saved runs: Tavily only, proposals from the model-only baseline."""
    import json

    from terkini.baseline import saved_results
    from terkini.evaluate import eval_dir, load_eval_config, load_runs, write_json
    from terkini.hybrid import load_hybrid_config
    pack = load_pack(args.pack)
    cfg, hcfg = load_eval_config(), load_hybrid_config()
    failed = []
    if not args.score_only:
        from terkini.budget import load_budget
        from terkini.cache import Cache
        from terkini.credits import CreditGuard
        from terkini.hybrideval import run_hybrid
        from terkini.score import load_score_config
        from terkini.tavily import Tavily
        from terkini.verify import Verifier, load_verify_config
        if (stop := _env_and_guard("hybrid")) is not None:
            return stop
        if not os.environ.get("TAVILY_API_KEY"):
            print("hybrid: needs TAVILY_API_KEY (use --score-only to recompute results)", file=sys.stderr)
            return 2
        mo = eval_dir(pack) / cfg.baseline_model_only
        if not mo.exists():
            print("hybrid: run `terkini baseline` first (the proposals come from it)", file=sys.stderr)
            return 2
        tavily, today = Tavily(), datetime.now(UTC).date()
        budget = load_budget()
        # The hybrid eval spends from the reserve under its own cap (config/hybrid.toml [eval] max_credits).
        cap = hcfg.eval.max_credits
        budget = budget.model_copy(update={"limits": budget.limits.model_copy(
            update={"per_run": cap, "per_day": budget.limits.per_day + cap})})
        before = usage_numbers(tavily.usage())
        with closing(Cache(REPO_ROOT / load_verify_config().cache_path)) as cache:
            verifier = Verifier(tavily, None, pack, CreditGuard(budget, cache, today), cfg=load_verify_config(),
                                score_cfg=load_score_config(), judge_model="", today=today)
            failed = run_hybrid(load_runs(pack), json.loads(mo.read_text()), verifier, hcfg,
                                eval_dir(pack) / hcfg.eval.results, usage_before=before,
                                usage=lambda: usage_numbers(tavily.usage()))
        for f in failed:
            print(f"hybrid: failed {f}", file=sys.stderr)
    results = saved_results(pack, REPO_ROOT)
    write_json(eval_dir(pack) / cfg.results, results)
    for r in results["baselines"]["rows"]:
        print(f"hybrid: {r['name']}: precision {r['precision_text']} {r['precision_ci95']} · "
              f"recall {r['recall_text']} {r['recall_ci95']}")
    return 1 if failed else 0
