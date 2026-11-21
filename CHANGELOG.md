# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

First public version, built on 20 and 21 November 2026.

### Added

- `terkini check`: pulls the factual claims out of an AI answer about a Malaysian rule, checks each one against official
  domains through Tavily Search and Extract, keeps a verdict only when its quote appears in the official page text, and
  gives each claim a freshness score from `config/score.toml`. Replay mode needs no key; live mode needs a Tavily key
  and a Bifrost gateway.
- Every model call goes through a Bifrost v2.5.1 gateway (official image, pinned by digest) with a virtual key, a budget
  and a fallback list (`config/models.toml`).
- The Malaysian pack (`packs/my.toml`): official domains, categories, and 23 questions with an answer key read from
  official pages before any model answer was seen.
- `terkini ask` and `terkini eval`: 68 answers from three models, one saved run per answer, and `eval/my/results.json`
  (precision 0.588, recall 0.357). Method and failures in `docs/EVAL.md`.
- The replay page on GitHub Pages: six recorded runs, each claim marked in the answer, English and Bahasa Melayu.
- `POST /api/check` on `terkini serve`, sharing one code path with the command line.
- `demo/run.sh`: the replay page and the API from a clean clone with Docker only.
- Offline tests on recorded fixtures, run in CI on every push.

### Not included

- The India pack, dropped to stay within the Tavily credit budget (decision D-017).
