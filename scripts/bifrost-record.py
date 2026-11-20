"""Record one real model answer through the Bifrost gateway into tests/fixtures/bifrost/ (D4, D13).

The fixture keeps only what the tests need: the request body (no headers, so no key), the answer, token usage
and the measured seconds. Values from .env / .env.bifrost are read into the process and never written out.

Usage: uv run scripts/bifrost-record.py <upstream model id> "<prompt>" [--name NAME]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path

from terkini.gateway import Gateway, load_env_file

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "tests" / "fixtures" / "bifrost"
KEEP = ("id", "object", "created", "model", "choices", "usage")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model")
    ap.add_argument("prompt")
    ap.add_argument("--name")
    args = ap.parse_args()

    load_env_file(REPO / ".env")
    load_env_file(REPO / ".env.bifrost")
    g = Gateway()
    cfg = g.cfg.models
    messages = [{"role": "user", "content": args.prompt}]
    fallbacks = [f for f in cfg.fallbacks if f != args.model]
    r = g.chat(args.model, messages, fallbacks=fallbacks)

    response = {k: r.raw[k] for k in KEEP if k in r.raw}
    for c in response.get("choices", []):
        c.get("message", {}).pop("reasoning_content", None)
    record = {
        "recorded_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gateway": "Bifrost v2.5.1 (official image, pinned digest)",
        "upstream_model": args.model,
        "seconds": round(r.seconds, 2),
        "request": {"model": g.cfg.ref(args.model), "messages": messages, "stream": False,
                    "temperature": 0.0, "fallbacks": [g.cfg.ref(f) for f in fallbacks]},
        "response": response,
    }
    text = json.dumps(record, indent=2, ensure_ascii=False) + "\n"
    for secret in (os.environ.get("BIFROST_VIRTUAL_KEY"), os.environ.get("PROVIDER_API_KEY"),
                   os.environ.get("BIFROST_SETUP_TOKEN")):
        if secret and secret in text:
            raise SystemExit("record: a secret value appeared in the answer; not writing the fixture")
    name = args.name or re.sub(r"[^a-z0-9]+", "-", args.model.lower()).strip("-")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.json"
    path.write_text(text, encoding="utf-8")
    print(f"record: {path.relative_to(REPO)} · answered by {r.model} in {r.seconds:.1f} s · "
          f"{r.prompt_tokens}+{r.completion_tokens} tokens")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
