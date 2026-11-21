"""Command line: `terkini check --pack my "<answer>"` (PRD §3 P0.9).

Replay mode is the default: with no TAVILY_API_KEY, `check` replays a recorded run (pick one with --case, or paste
the recorded answer). With TAVILY_API_KEY and the Bifrost settings in the environment (or .env), it checks live.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import closing
from datetime import UTC, datetime

from terkini import __version__
from terkini.checker import AnswerReport
from terkini.packs import REPO_ROOT

VERDICT_MARK = {"current": "OK  ", "outdated": "OLD ", "unverifiable": "??  "}
NOT_ADVICE = "Not legal advice. Always confirm with the official source linked above."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="terkini",
        description="Check AI answers about local rules against official sources.",
    )
    parser.add_argument("--version", action="version", version=f"terkini {__version__}")
    sub = parser.add_subparsers(dest="command")
    c = sub.add_parser("check", help="check one AI answer, claim by claim")
    c.add_argument("answer", nargs="?", help="the AI answer to check (live mode, or a recorded answer in replay mode)")
    c.add_argument("--pack", default="my", help="country pack in packs/ (default: my)")
    c.add_argument("--case", help="replay this recorded run (see --list)")
    c.add_argument("--list", action="store_true", help="list recorded runs and exit")
    c.add_argument("--json", action="store_true", help="print the report as JSON")
    a = sub.add_parser("ask", help="ask the pack's eval questions to several models (writes eval/<pack>/answers/)")
    a.add_argument("--pack", default="my")
    a.add_argument("--models", help="comma-separated model ids (default: the eval models in config/models.toml)")
    a.add_argument("--only", help="comma-separated question ids")
    a.add_argument("--force", action="store_true", help="ask again even if an answer is saved")
    e = sub.add_parser("eval", help="check every saved answer live, then compute eval/<pack>/results.json")
    e.add_argument("--pack", default="my")
    e.add_argument("--score-only", action="store_true", help="recompute results.json from saved runs (no network)")
    e.add_argument("--force", action="store_true", help="check answers again even if a run is saved")
    e.add_argument("--keep-errors", action="store_true", help="save runs that had failed claims")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "check":
        return _check(args)
    if args.command in ("ask", "eval"):
        from terkini.evalcli import ask_command, eval_command
        return ask_command(args) if args.command == "ask" else eval_command(args)
    parser.print_help()
    return 0


def _check(args) -> int:
    from terkini.gateway import load_env_file
    from terkini.replay import find_by_answer, list_cassettes
    from terkini.runner import replay, runs_dir

    cassettes = list_cassettes(runs_dir(), args.pack)
    if args.list:
        for c in cassettes:
            print(f"{c.name}\t{c.answer_model or '-'}\t{c.recorded_at}\t{c.question or c.answer[:60]}")
        return 0

    if not args.case:
        load_env_file(REPO_ROOT / ".env")
    live = not args.case and bool(os.environ.get("TAVILY_API_KEY"))
    if live:
        if not args.answer:
            print("check: give the answer to check", file=sys.stderr)
            return 2
        from terkini.gateway import GatewayNotConfigured
        try:
            report = _live(args.answer, args.pack)
        except GatewayNotConfigured as e:
            print(f"check: live mode needs the Bifrost gateway: {e}", file=sys.stderr)
            return 2
        label = "live run"
    else:
        found = next((c for c in cassettes if c.name == args.case), None) if args.case else (
            find_by_answer(cassettes, args.answer) if args.answer else None)
        if found is None:
            print("check: replay mode (no TAVILY_API_KEY) needs a recorded run. Pick one with --case NAME "
                  "(see --list), or set TAVILY_API_KEY for a live check.", file=sys.stderr)
            return 2
        report = replay(found)
        label = f"recorded run, {found.recorded_at[:10]}"
        if not args.json:
            print(f"Answer ({found.answer_model or 'pasted'}):\n{found.answer}\n")

    if args.json:
        print(json.dumps({"mode": label, **report.model_dump(mode="json")}, indent=2, ensure_ascii=False))
    else:
        print(render(report, label))
    return 0


def _live(answer: str, pack_id: str) -> AnswerReport:
    from terkini.cache import Cache
    from terkini.gateway import Gateway, load_env_file
    from terkini.runner import run_check
    from terkini.tavily import Tavily
    from terkini.verify import load_verify_config

    load_env_file(REPO_ROOT / ".env.bifrost")
    today = datetime.now(UTC).date()
    with closing(Cache(REPO_ROOT / load_verify_config().cache_path)) as cache:
        return run_check(answer, pack_id=pack_id, tavily=Tavily(), gateway=Gateway(), cache=cache, today=today)


def render(r: AnswerReport, label: str) -> str:
    lines = [f"Terkini · pack {r.pack} · checked on {r.checked_on} ({label})", ""]
    for x in r.results:
        lines.append(f"{VERDICT_MARK[x.verdict]}{x.verdict:<13} score {x.score:>3}  {x.claim.claim}")
        if x.current_value:
            lines.append(f"      official now: {x.current_value}")
        if x.effective_date:
            lines.append(f"      in force from: {x.effective_date}")
        if x.source_url:
            lines.append(f"      source: {x.source_url}" + ("  (Tavily cached copy)" if x.cached_copy else "")
                         + ("  (search snippet)" if x.snippet_only else ""))
        if x.evidence_quote:
            lines.append(f"      quote: \"{x.evidence_quote}\"")
        if x.reason:
            lines.append(f"      why: {x.reason}")
    for c in r.not_checked:
        lines.append(f"--  not checked    {c.claim}")
    for e in r.errors:
        lines.append(f"!!  error          {e.claim.claim}: {e.error}")
    lines.append("")
    summary = f"{len(r.results)} claims checked, {r.outdated} outdated, {r.skipped} skipped, {r.credits} Tavily credits"
    lines.append(summary)
    if r.as_of_before:
        lines.append(f"This answer reads as if written before {r.as_of_before}" + (" (mixed dates)" if r.as_of_mixed else ""))
    if r.stopped:
        lines.append(f"Stopped early: {r.stopped}")
    lines.append(NOT_ADVICE)
    return "\n".join(lines)
