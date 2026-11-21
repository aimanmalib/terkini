"""Print the Markdown tables for docs/EVAL.md from eval/<pack>/results.json and the saved runs, so no number in the
document is typed by hand.

Usage: uv run scripts/eval-tables.py [--pack my]
"""

from __future__ import annotations

import argparse
import json

from terkini.evaluate import eval_dir, load_eval_config, load_labels, load_runs
from terkini.gateway import load_gateway_config
from terkini.packs import load_pack


def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pack", default="my")
    args = ap.parse_args()
    pack = load_pack(args.pack)
    r = json.loads((eval_dir(pack) / load_eval_config().results).read_text())
    vendors = load_gateway_config().models.vendors
    d, c, e, k = r["detection"], r["claims"], r["effective_dates"], r["cost"]

    print("| Measure | Value |\n|---|---|")
    for name, v in [("Answers checked", r["answers"]), ("Answers labelled stale (differ from the key)", d["stale"]),
                    ("Answers labelled current", d["current"]), ("Answers flagged by Terkini", d["flagged"]),
                    ("True positives", d["true_positive"]), ("False positives", d["false_positive"]),
                    ("False negatives", d["false_negative"]), ("Precision", pct(d["precision"])),
                    ("Recall", pct(d["recall"]))]:
        print(f"| {name} | {v} |")

    print("\n| Model | Vendor | Answers | Labelled stale | Flagged | Stale and flagged |\n|---|---|---|---|---|---|")
    for m, x in sorted(r["per_model"].items()):
        print(f"| `{m}` | {vendors.get(m, '')} | {x['answers']} | {x['stale_label']} | {x['flagged']} | "
              f"{x['true_positive']} |")

    print("\n| Claims | Count |\n|---|---|")
    for name, v in [("Checked", c["checked"]), ("current", c["current"]), ("outdated", c["outdated"]),
                    ("unverifiable", c["unverifiable"]), ("Not checked (credit limit)", c["not_checked"]),
                    ("Failed (gateway or Tavily error)", c["errors"]),
                    ("Skipped (not time-sensitive or outside the pack)", c["skipped_not_time_sensitive"]),
                    ("Decided with an exact official quote", (f"{r['evidence']['decided_with_exact_quote']} "
                                                              f"({pct(r['evidence']['share_of_checked'])} of checked)"))]:
        print(f"| {name} | {v} |")
    print("\n| Why a claim was `unverifiable` | Claims |\n|---|---|")
    for why, n in c["unverifiable_reasons"].items():
        print(f"| {why} | {n} |")

    print("\n| Effective dates (flagged stale answers) | Count |\n|---|---|")
    for name, key in [("Flagged stale answers", "flagged_stale"), ("With a quoted effective date", "date_quoted"),
                      ("Date equals the key", "exact"), (f"Within {e['window_days']} days of the key", "within_window"),
                      ("Different date", "different"), ("Key gives no date", "key_has_no_date")]:
        print(f"| {name} | {e[key]} |")

    print("\n| Cost | Value |\n|---|---|")
    for name, key in [("Tavily credits (sum of response usage)", "tavily_credits_from_responses"),
                      ("Claims that needed Tavily calls (not cache hits)", "claims_needing_tavily"),
                      ("Credits per claim that needed Tavily", "credits_per_claim_needing_tavily"),
                      ("Tavily plan usage before (GET /usage)", "tavily_plan_usage_before"),
                      ("Tavily plan usage after (GET /usage)", "tavily_plan_usage_after"),
                      ("Model calls through Bifrost", "gateway_calls"), ("Prompt tokens", "prompt_tokens"),
                      ("Completion tokens", "completion_tokens"), ("Tokens per checked claim", "tokens_per_checked_claim"),
                      ("Bifrost virtual-key spend after (USD)", "gateway_budget_usd_after"),
                      ("Median seconds to check one answer", "p50_seconds_per_answer")]:
        print(f"| {name} | {k[key]} |")

    labels = load_labels(pack)
    print("\n| Answer | Label | Flagged | Outdated claims |\n|---|---|---|---|")
    for run in load_runs(pack):
        lab = labels.get(run.answer)
        flag = run.report.outdated > 0
        mark = {True: "stale", False: "current", None: "no value"}[lab.stale] if lab else "unlabelled"
        if flag or (lab and lab.stale):
            olds = "; ".join(x.claim.claim for x in run.report.results if x.verdict == "outdated")
            print(f"| `{run.answer}` | {mark} | {'yes' if flag else 'no'} | {olds or '-'} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
