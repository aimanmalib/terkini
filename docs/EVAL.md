# Evaluation: Malaysia pack

Run on 21 Nov 2026. Every number below comes from [`eval/my/results.json`](../eval/my/results.json), printed by
`uv run scripts/eval-tables.py`. A test recomputes `results.json` from the saved runs, labels and key.

## What was run

1. **Questions and key.** 23 questions about Malaysian rules in [`eval/my/questions.yaml`](../eval/my/questions.yaml).
   Each has one answer-key entry in [`eval/my/key.yaml`](../eval/my/key.yaml): the current value, the official page,
   an exact quote from it and the date it was read. Six more topics were dropped because no official page gave a
   quotable sentence; the reasons are in the key file. The key was written on 20 Nov 2026, before any model answer
   was seen, and has not changed since. Six key pages block automated fetching (D-011). D-011 asks for them to be
   read again before each eval run; that was not done for this run, so those six were last read on 20 Nov 2026.
2. **Answers.** `terkini ask` put each question to three models from three vendors through the Bifrost gateway,
   with no fallback, so each answer is that model's own. 68 of 69 answers were saved in
   [`eval/my/answers/`](../eval/my/answers/). The Kimi K3.1 Pro answer to `my-10` timed out at the gateway three times
   and is not in the eval.
3. **Labels.** Each answer was read against the key and labelled in
   [`eval/my/labels.yaml`](../eval/my/labels.yaml): stale when it states a value or rule that differs from the key,
   current when it states the key value. The labelling was done with Claude Code and not checked by a second reader.
   The labels were committed before the checker ran on any answer.
4. **Checks.** `terkini eval` ran the full checker on every answer: claim extraction and judging through Bifrost,
   Tavily Search restricted to the pack's official domains, Tavily Extract, the exact-quote check and the score. One
   run per answer is saved in [`eval/my/runs/`](../eval/my/runs/).

The checker, prompts and search settings were not changed after the answers were seen (D-015).

## Detection

An answer counts as flagged when Terkini marks at least one of its claims `outdated`.

| Measure | Value |
|---|---|
| Answers checked | 68 |
| Answers labelled stale (differ from the key) | 28 |
| Answers labelled current | 40 |
| Answers flagged by Terkini | 17 |
| True positives | 10 |
| False positives | 7 |
| False negatives | 18 |
| Precision | 59% |
| Recall | 36% |

| Model | Vendor | Answers | Labelled stale | Flagged | Stale and flagged |
|---|---|---|---|---|---|
| `gcli/grok-4.7` | xAI | 23 | 20 | 9 | 9 |
| `rv/deepseek-ai/DeepSeek-V4.1-Flash-1017` | DeepSeek | 23 | 6 | 4 | 1 |
| `rv/moonshotai/Kimi-K3.1-Pro` | Moonshot AI | 22 | 2 | 4 | 0 |

## Claims

| Claims | Count |
|---|---|
| Checked | 214 |
| current | 59 |
| outdated | 20 |
| unverifiable | 135 |
| Not checked (credit limit) | 0 |
| Failed (gateway or Tavily error) | 0 |
| Skipped (not time-sensitive or outside the pack) | 112 |
| Decided with an exact official quote | 79 (37% of checked) |

| Why a claim was `unverifiable` | Claims |
|---|---|
| The official pages do not settle this claim. | 121 |
| The evidence quote is not on the official page. | 13 |
| The effective date is not in the evidence quote. | 1 |

## Effective dates

For stale answers that Terkini flagged: did it quote the date the rule changed, and does that date match the key?

| Effective dates (flagged stale answers) | Count |
|---|---|
| Flagged stale answers | 10 |
| With a quoted effective date | 5 |
| Date equals the key | 1 |
| Within 31 days of the key | 0 |
| Different date | 1 |
| Key gives no date | 3 |

## Cost

| Cost | Value |
|---|---|
| Tavily credits (sum of response usage) | 276 |
| Claims that needed Tavily calls (not cache hits) | 205 |
| Credits per claim that needed Tavily | 1.346 |
| Tavily plan usage before (GET /usage) | 65 |
| Tavily plan usage after (GET /usage) | 65 |
| Model calls through Bifrost | 273 |
| Prompt tokens | 974445 |
| Completion tokens | 750730 |
| Tokens per checked claim | 8061.565 |
| Bifrost virtual-key spend after (USD) | 0 |
| Median seconds to check one answer | 151.8 |

Notes on these numbers:

- **Tavily credits.** The responses of all calls in the eval add up to 300 credits on 21 Nov 2026. 276 of them belong
  to the saved runs. The other 24 went to claims that were in flight when the first eval run was stopped to raise the
  worker count from 4 to 8. `GET /usage` did not move during the run (65 before and after), the same lag recorded in
  D-010, so the per-response sum is the count we trust.
- **Tokens.** Summed from each model response. The virtual key's own token counter rose by 1,631,767 during the
  second run. The 64 runs saved in that run sum to 1,635,733 tokens, within 0.3%. Completion tokens are high
  because the judge model returns its reasoning tokens as completion tokens.
- **Spend.** The gateway reports US$0 because it has no price list for these upstream model ids.
- **Time.** Most of the time per answer is spent waiting for the judge. Calls that hit the gateway timeout (90 s)
  took about 110 s before a fallback model answered.

## Cases

Every answer that was labelled stale or flagged by Terkini.

| Answer | Label | Flagged | Outdated claims |
|---|---|---|---|
| `my-01--grok-4-7` | stale | no | - |
| `my-01--kimi-k3-1-pro` | current | yes | The RM1,700 minimum wage took effect on 1 August 2025 for other employers with fewer than five employees. |
| `my-02--grok-4-7` | stale | no | - |
| `my-03--deepseek-v4-1-flash-1017` | current | yes | The standard service tax rate in Malaysia is 8% effective from 1 March 2024. |
| `my-03--grok-4-7` | stale | yes | The standard service tax rate in Malaysia is 6%. |
| `my-05--grok-4-7` | stale | yes | Malaysia introduced the standard service tax (SST) rate of 6% on 1 April 2018.; Malaysia's standard service tax rate has remained at 6% since 1 April 2018, with no further changes. |
| `my-06--deepseek-v4-1-flash-1017` | current | yes | The 5% sales tax rate generally applies to food, beverages, building materials, and certain other goods. |
| `my-06--grok-4-7` | stale | no | - |
| `my-06--kimi-k3-1-pro` | current | yes | The main sales tax rates in Malaysia are 5% and 10% depending on the product's tariff classification. |
| `my-08--deepseek-v4-1-flash-1017` | stale | no | - |
| `my-08--grok-4-7` | stale | no | - |
| `my-09--deepseek-v4-1-flash-1017` | stale | no | - |
| `my-09--grok-4-7` | stale | no | - |
| `my-09--kimi-k3-1-pro` | stale | no | - |
| `my-10--deepseek-v4-1-flash-1017` | stale | no | - |
| `my-10--grok-4-7` | stale | yes | Businesses that already exceeded RM3 million in annual revenue in YA2023 must start e-Invoicing on 1 January 2024. |
| `my-11--grok-4-7` | stale | no | - |
| `my-12--grok-4-7` | stale | yes | The total EPF contribution rate is 12%.; The employee EPF contribution rate is 8%. |
| `my-12--kimi-k3-1-pro` | current | yes | Foreign employees who had already opted into EPF before the October 2025 change generally continue under their previous contribution rates. |
| `my-13--grok-4-7` | stale | yes | The EIS contribution applies to wages up to RM5,000 per month. |
| `my-13--kimi-k3-1-pro` | current | yes | The EIS employee contribution rate is 0.2% of monthly wages. |
| `my-14--grok-4-7` | stale | no | - |
| `my-15--deepseek-v4-1-flash-1017` | stale | no | - |
| `my-15--grok-4-7` | stale | no | - |
| `my-15--kimi-k3-1-pro` | stale | no | - |
| `my-16--grok-4-7` | stale | yes | Dividends received by individuals from Malaysian companies are fully exempt from income tax under Section 4A of the Income Tax Act 1967.; Non-resident individuals may face 10% withholding tax on dividends instead. |
| `my-17--deepseek-v4-1-flash-1017` | stale | yes | From 1 March 2024, gains on the disposal of unlisted shares by companies, limited liability partnerships, trust bodies and co-operative societies are subject to tax under the Capital Gains Tax regime. |
| `my-17--grok-4-7` | stale | no | - |
| `my-18--grok-4-7` | stale | no | - |
| `my-20--grok-4-7` | stale | yes | A married male employee is entitled to 2 days of paid paternity leave for the birth of his child under Malaysia's Employment Act 1955. |
| `my-21--deepseek-v4-1-flash-1017` | stale | no | - |
| `my-21--grok-4-7` | stale | yes | Under Section 30A of Malaysia's Employment Act 1955, the maximum normal working hours per week is 48 hours for most employees, covering standard shifts without overtime. |
| `my-22--deepseek-v4-1-flash-1017` | current | yes | The Employment (Amendment) Act 2022 raised the Employment Act coverage ceiling to RM4,000 from RM2,000 effective 1 May 2023. |
| `my-22--grok-4-7` | stale | no | - |
| `my-23--grok-4-7` | stale | yes | EPF contributions stop at age 55. |

## Where it fails

- **Misses (18 stale answers not flagged).** These answers had 45 checked claims. 39 ended `unverifiable`: the
  official pages that Search returned did not settle the claim. 23 of those 39 were judged on search snippets,
  because the official site refused Tavily Extract (D-014). For the minimum wage, the restricted search returned a PDF from the
  social security agency and a TNB news clipping instead of the Ministry of Human Resources FAQ that the key uses. Six claims were
  judged `current` when the label says the answer is stale. One stale answer had no claim that the extractor marked
  time-sensitive.
- **False alarms (7 answers).** In five the evidence quote is real but does not state a different value: a table
  row naming a 2026 amendment order, the heading of a 2025 sales-tax FAQ (two answers), a contribution-table row,
  and an amendment date. The quote check confirms the sentence is on the page; it cannot confirm that the sentence
  contradicts the claim. In two the claim and the quote are about different groups or dates: the RM1,700 start date
  for small employers against the date for larger ones, and foreign workers who opted into EPF before October 2025
  against those who opted in before 1 August 1998.
- **Grok 4.7 drives the stale count.** 20 of its 23 answers differ from the key, against 6 for DeepSeek and 2 for Kimi.
  Recall on Grok answers is 9 of 20.
- **Small sample.** 68 answers to 23 questions, labelled once. Treat the rates as a first measurement.
- **Right verdict, old evidence.** The recorded e-invoicing run (`my-09-grok-4-7`, on the replay page) is marked
  outdated with a 2023 Ministry of Finance statement. The verdict is right, but the current rule in the key is newer:
  turnover under RM3,000,000 is exempt (hasil.gov.my). The eval run of the same answer was a miss. Terkini does not yet
  prefer the newest official page when two disagree.

## Reproduce

```bash
uv run terkini eval --pack my --score-only   # recompute results.json from the saved runs; no keys, no network
uv run scripts/eval-tables.py                # print the tables above
```

A live re-run needs `TAVILY_API_KEY` and the gateway (see the README). It will give different numbers on a different
day: official pages, search results and model answers change.
