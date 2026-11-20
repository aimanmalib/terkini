# Terkini

**Is this AI answer still true where you live?**

Terkini takes an AI answer about a Malaysian rule, such as the minimum wage, an EPF contribution rate, an electricity
tariff or the turnover limit for e-invoicing. It pulls out each factual claim, checks it against official government pages through
Tavily Search and Extract, and gives every claim a freshness score with the exact quote from the official source. All model
calls go through a Bifrost gateway.

> **Not legal advice.** Terkini compares an answer with what official pages say on the day it runs. It can miss a page,
> misread one, or check a page that is itself out of date. Confirm anything important with the agency.

## Status

Work in progress. This repository was started on 21 November 2026. Nothing in it works end to end yet, and there are no
evaluation results. This file will say so until there are.

Built during the Global AI Hackathon (extended window, 21 Nov 2026), Tavily track, problem statement PS06.

## Plan

1. Extract claims from an AI answer with a model called through Bifrost.
2. Search official Malaysian government domains with Tavily, then extract the page text.
3. Accept a claim only when the evidence quote appears word for word in the extracted page.
4. Score freshness with fixed rules from `config/score.toml`, and say which date the answer is consistent with.

Design decisions are in [`docs/02-DECISIONS.md`](docs/02-DECISIONS.md).

## How AI is used

### AI disclosure

- The code and the documentation in this repository were written with Claude Code (Claude Opus).
- The product calls language models through a Bifrost gateway to extract claims and to judge evidence. The exact model IDs
  will be listed here once they are chosen and measured.

## Licence

Apache-2.0. See [`LICENSE`](LICENSE).
