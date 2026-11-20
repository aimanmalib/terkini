# Decisions

Short records of why Terkini is built the way it is. Newest last. Each entry says what was decided, why, and what would
change it.

## D-001 · Python 3.12, FastAPI, httpx, Pydantic, uv

- **Decision.** The checker is a Python 3.12 package under `src/terkini/`, managed with `uv` and a committed `uv.lock`.
  FastAPI serves the local page, httpx makes the HTTP calls, Pydantic defines claims and verdicts. Tests use pytest.
- **Why.** The work is HTTP calls and JSON validation. These libraries do that with little code, and `uv sync --frozen`
  gives the same environment on every machine.
- **Would change if.** A dependency blocks a needed feature. Then we record the replacement here.

## D-002 · Call Tavily with httpx, not the SDK

- **Decision.** Tavily Search and Extract are called directly over HTTP.
- **Why.** The checker needs exact control of a few request fields (domain filters, maximum content age, usage reporting)
  and of specific error codes. A thin client of our own keeps every request field visible in one file.
- **Would change if.** The SDK exposes the same controls and we need a feature only it has.

## D-003 · Official domains decide the verdict

- **Decision.** Only pages on official domains listed in a country pack (`packs/*.toml`) can make a claim current or
  outdated. Other pages can be shown as context and never change the verdict.
- **Why.** The question Terkini answers is "what do the official sources say today". A blog that repeats an old rate is
  not evidence.
- **Would change if.** An agency publishes its rules only on a domain outside the pack. Then the domain is added to the pack,
  not to the code.

## D-004 · Evidence quotes are checked in code

- **Decision.** A model may propose an evidence quote, but the claim is accepted only if that quote appears in the
  extracted page text after whitespace is normalised. Otherwise the claim is `unverifiable`.
- **Why.** Models can invent plausible quotes. A substring check is cheap and cannot be talked out of.
- **Would change if.** Official pages are mostly scanned PDFs with no text layer. Then the claim stays `unverifiable`
  rather than being trusted.

## D-005 · Values live in files, not code

- **Decision.** Domains, categories and questions are in `packs/` and `eval/`. Score weights are in `config/score.toml`,
  credit limits in `config/budget.toml`, model IDs in `config/models.toml`. Interface text is in `i18n/en.json` and
  `i18n/ms.json` with the same keys.
- **Why.** Rules, rates and models change. Updating a file is safer than editing code, and a second country is a new pack.
- **Would change if.** Nothing planned.

## D-006 · No public live server

- **Decision.** The public demo is a static replay page on GitHub Pages built from recorded runs. Live mode runs only on
  your own machine with your own Tavily key.
- **Why.** A public server would have to hold a paid key and could be abused to spend it.
- **Would change if.** There is a way to let visitors use their own key without it passing through our server.

## D-007 · Licence

- **Decision.** Apache-2.0.
- **Why.** The same licence as Bifrost, and it carries an explicit patent grant.
- **Would change if.** Nothing planned.
