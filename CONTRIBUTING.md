# Contributing

Thanks for helping. Terkini reads official pages and tells people whether an answer about a rule is out of date, so
a change that can turn a wrong page into a confident verdict gets extra scrutiny.

## Set up

Python 3.12 and [uv](https://docs.astral.sh/uv/). Docker is needed only for the Bifrost gateway and the demo.

```sh
uv sync
bash scripts/gerbang-ujian.sh   # all tests, offline, on recorded fixtures; no keys
demo/run.sh                     # the replay page and the API in Docker; demo/run.sh stop removes it
```

Live mode needs a Tavily key and a Bifrost gateway; see the README section "Live mode".

## Before you open a pull request

- Run `bash scripts/gerbang-ujian.sh`. CI runs the same script. Tests must not touch the network.
- Values that can change (domains, weights, limits, model ids, prompts, page text) live in `config/`, `packs/` and
  `i18n/`, not in code. User-facing text goes in `i18n/en.json` and `i18n/ms.json` with the same keys.
- A change to the quote check, the score or the verdict rules needs a test that fails without your change.
- Recorded fixtures keep only the fields the code reads, quotes of 500 characters or less, and never a key.
- Do not edit `eval/*/key.yaml` after you have seen model answers for those questions. Add new questions instead.
- A new country pack needs official domains only, and an answer key read from those domains.
- One topic per pull request; describe how you tested it.

## Reporting security issues

Please don't open a public issue. See [`SECURITY.md`](SECURITY.md).

By contributing you agree that your contribution is licensed under the [Apache License 2.0](LICENSE) and that you follow
the [Code of Conduct](CODE_OF_CONDUCT.md).
