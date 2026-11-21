# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- `terkini check --case` and `POST /api/check` also open the 68 saved eval runs by name, shown as saved (D-023).
- The first example in the README, `demo/run.sh`, slide 8 and the replay page is the service tax answer (6% claimed,
  8% official since 1 March 2024), a stale answer by the answer key. The EPF false alarm stays listed in `docs/EVAL.md`.

## [0.1.0] - 2026-11-21

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
- Demo video (`docs/media/terkini-demo.mp4`, 72 s, captions in `docs/media/terkini-demo.srt`), rendered from the
  replay page and the eval numbers; source in `demo/video/` (D-019).
- `terkini baseline`: two baselines on the same answers and claims, the judge model alone with no official pages and a
  naive page rule, with 95% Wilson intervals in `docs/EVAL.md` (D-020). The Terkini numbers did not change.
- "How this check ran" on the replay page and in `terkini serve`: for each recorded run, the Tavily queries with their
  domains and credits, and each Bifrost call with the model asked for, the model that answered and the tokens (D-021).

### Not included

- The India pack, dropped to stay within the Tavily credit budget (decision D-017).

[Unreleased]: https://github.com/aimanmalib/terkini/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/aimanmalib/terkini/releases/tag/v0.1.0
