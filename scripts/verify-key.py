#!/usr/bin/env python3
"""Re-read every official page in a pack's answer key through Tavily Extract and check each quote is still there.

Live: spends about one Tavily credit per five pages. Needs TAVILY_API_KEY in the environment.
Usage: uv run python scripts/verify-key.py --pack my
Exit code 0 when every quote is found, 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys

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
    tv = Tavily()
    pages: dict[str, str] = {}
    credits = 0
    for i in range(0, len(urls), BATCH):
        res = tv.extract(urls[i : i + BATCH])
        pages.update(res.pages)
        credits += res.credits

    missing = 0
    for k in key.keys:
        ok = quote_in_text(k.quote, pages.get(k.url, ""))
        missing += not ok
        print(f"{'ok  ' if ok else 'MISS'} {k.id} {k.url}")
    print(f"{len(key.keys) - missing}/{len(key.keys)} quotes found in {len(urls)} pages; {credits} credits")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
