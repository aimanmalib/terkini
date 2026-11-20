"""Record one live check for replay (PRD §3 P0.7, D13): ask an eval model a pack question, check its answer, save it.

Needs TAVILY_API_KEY and the Bifrost settings in the environment (or .env / .env.bifrost). Keys are read into the
process only; the recording keeps no headers, no key and no full page. After writing, the run is replayed offline and
must give the same report, or the recording is removed.

Usage: uv run scripts/record-run.py <question id> <model id> [--name NAME] [--pack my]
"""

from __future__ import annotations

import argparse
import os
import re
from contextlib import closing
from datetime import UTC, datetime
from string import Template

from terkini.cache import Cache
from terkini.extractor import load_prompts
from terkini.gateway import Gateway, load_env_file
from terkini.packs import REPO_ROOT, load_pack, load_questions
from terkini.replay import (
    Cassette,
    RecordingGateway,
    RecordingTavily,
    chat_record,
    write_cassette,
)
from terkini.runner import replay, run_check, runs_dir
from terkini.tavily import Tavily


def usage_numbers(u: dict) -> dict:
    """Keep only the numbers from GET /usage (credit totals), never names or ids."""
    return {k: {kk: vv for kk, vv in v.items() if isinstance(vv, (int, float))} for k, v in u.items()
            if isinstance(v, dict)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("question_id")
    ap.add_argument("model")
    ap.add_argument("--name")
    ap.add_argument("--pack", default="my")
    args = ap.parse_args()

    load_env_file(REPO_ROOT / ".env")
    load_env_file(REPO_ROOT / ".env.bifrost")
    pack = load_pack(args.pack)
    q = next(x for x in load_questions(pack) if x.id == args.question_id)
    p = load_prompts()["ask"]
    messages = [{"role": "system", "content": Template(p["system"]).substitute(country=pack.name).strip()},
                {"role": "user", "content": Template(p["user"]).substitute(question=q.question).strip()}]

    tavily, gateway = Tavily(), Gateway()
    asked = gateway.chat(args.model, messages, temperature=0.0)  # no fallbacks: the answer must be this model's
    answer = asked.text.strip()

    before = usage_numbers(tavily.usage())
    rec_t, rec_g = RecordingTavily(tavily), RecordingGateway(gateway)
    today = datetime.now(UTC).date()
    recorded_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with closing(Cache(":memory:")) as cache:  # fresh cache: every call is made live and recorded
        report = run_check(answer, pack_id=pack.id, tavily=rec_t, gateway=rec_g, cache=cache, today=today,
                           question=q.question)
    after = usage_numbers(tavily.usage())
    rec_t.cut(rec_g.chats)

    name = args.name or f"{q.id}-" + re.sub(r"[^a-z0-9]+", "-", args.model.lower().split("/")[-1]).strip("-")
    c = Cassette(name=name, pack=pack.id, recorded_at=recorded_at, checked_on=today, question_id=q.id,
                 question=q.question, answer_model=args.model, answer=answer, ask=chat_record(args.model, asked),
                 chats=rec_g.chats, searches=rec_t.searches, extracts=rec_t.extracts, usage_before=before,
                 usage_after=after, report=report.model_dump(mode="json"))
    secrets = [os.environ.get(k, "") for k in ("TAVILY_API_KEY", "BIFROST_VIRTUAL_KEY", "PROVIDER_API_KEY",
                                                 "BIFROST_SETUP_TOKEN")]
    path = write_cassette(c, runs_dir(), secrets)
    again = replay(c).model_dump(mode="json")
    verdicts = ", ".join(f"{r.verdict}" for r in report.results) or "none"
    print(f"record: {path.relative_to(REPO_ROOT)} · {len(report.results)} claims ({verdicts}) · "
          f"{report.credits} credits from responses · /usage before {before} after {after}")
    if again != c.report:
        path.unlink()
        print("record: replay gave a different report; recording removed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
