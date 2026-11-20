#!/usr/bin/env python3
"""Re-read every official page in a pack's answer key and check each quote is still there.

Each URL is first fetched directly from the official site (D-011): a 404 or other dead status is a MISS even when
Tavily Extract still returns a cached copy. Sites that refuse scripts (config/verify.toml) are reported as BLOCKED
and judged on the extract alone. Then every page is read through Tavily Extract and the quote is checked.

Live: spends about one Tavily credit per five pages. Needs TAVILY_API_KEY in the environment.
Usage: uv run python scripts/verify-key.py --pack my
Exit code 0 when no key is a MISS, 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys

import httpx

from terkini.liveness import load_verify_config, probe, verdict
from terkini.packs import load_key, load_pack
from terkini.quotes import quote_in_text
from terkini.tavily import Tavily

BATCH = 5  # Tavily bills extract per five successful URLs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="my")
    args = ap.parse_args()

    pack = load_pack(args.pack)
    key = load_key(pack)
    urls = sorted({k.url for k in key.keys})
    cfg = load_verify_config()
    with httpx.Client(timeout=cfg.timeout_seconds) as direct:
        live = {u: probe(u, cfg, direct) for u in urls}

    tv = Tavily()
    pages: dict[str, str] = {}
    failed: set[str] = set()
    credits = 0
    for i in range(0, len(urls), BATCH):
        res = tv.extract(urls[i : i + BATCH])
        pages.update(res.pages)
        failed.update(res.failed)
        credits += res.credits

    counts = {"ok": 0, "BLOCKED": 0, "MISS": 0}
    for k in key.keys:
        state, detail = live[k.url]
        v = verdict(state, k.url in failed, quote_in_text(k.quote, pages.get(k.url, "")))
        counts[v] += 1
        print(f"{v:<7} {k.id} direct={detail} {k.url}")
    print(
        f"{counts['ok']} ok, {counts['BLOCKED']} blocked by site (quote found in extract), {counts['MISS']} miss"
        f" of {len(key.keys)} keys in {len(urls)} pages; {credits} credits"
    )
    return 1 if counts["MISS"] else 0


if __name__ == "__main__":
    sys.exit(main())
