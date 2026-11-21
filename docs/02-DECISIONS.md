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

## D-008 · Country pack and answer key format

- **Decision.** `packs/my.toml` lists official domains with a label (`government` or `utility`), categories with a
  `volatile` flag, and one canonical official page per category. Questions are in `eval/my/questions.yaml`. The answer
  key in `eval/my/key.yaml` gives, for each question, the current value, the official page, an exact quote from that
  page's extracted text, the effective date when the quote states it, and the date the page was read. Questions we
  could not key are listed under `dropped` with the reason.
- **Why.** The key has to be checkable by anyone. `scripts/verify-key.py` re-reads every page through Tavily Extract
  and checks each quote with the same whitespace-normalised substring test the checker uses (D-004).
- **Would change if.** A pack needs a domain label other than government or utility.

## D-009 · Official pages are reachable through Tavily search

- **Decision.** Search uses `include_domains` with the pack domains and `include_domains_mode: restrict`. The canonical
  pages in the pack are a fallback, not the main path.
- **Why.** On 2026-11-20 we ran 10 restricted searches, one per sample question. All 10 returned official pages, and
  each had at least one page that answered the question. Subdomains such as `mysst.customs.gov.my` and
  `lom.agc.gov.my` are matched by their parent domain.
- **Would change if.** A later run shows search missing pages that the canonical list has. Then the checker extracts
  the canonical page directly.

## D-010 · Credits are counted from each response

- **Decision.** The checker sums the `usage.credits` field that Tavily returns with each search and extract, and also
  reads `GET /usage` before and after a run.
- **Why.** During the first key-building session the account counter at `GET /usage` stayed at 0 after 35 credits
  of calls. The per-response field was present on every call.
- **Would change if.** `GET /usage` updates promptly. Then it becomes the single source.

## D-011 · Answer-key pages are also fetched directly

- **Decision.** `scripts/verify-key.py` fetches every key URL directly from the official site before it checks the
  quote in the Tavily extract. A 4xx or 5xx status, or a URL in Tavily's `failed_results`, is a miss. Statuses that
  mean a site refuses scripts (`config/verify.toml`, now 401, 403 and 429) and refused connections are reported as
  `BLOCKED` and judged on the extract alone.
- **Why.** On 2026-11-20 the key for my-17 pointed to a HASiL PDF that returned 404, but Tavily Extract still
  returned its text. HASiL had replaced that guideline with one dated 21.09.2026. The key now cites the new PDF, which
  states the same 10% rate. On the re-run, 17 keys were ok, 6 were blocked (KWSP returns 403, the AGC law site resets
  the connection) and 0 were missed, for 4 credits.
- **Would change if.** A blocked site starts to answer scripts. Then its pages get the full check. Until then a
  blocked page could still be stale in the extract, so those 6 keys are also read by hand before each eval run.

## D-012 · Model gateway and model choice

- **Decision.** Every model call goes through Bifrost v2.5.1, the official image pinned by digest in
  `docker-compose.yml`. `scripts/bifrost-bootstrap.py` creates one OpenAI-compatible provider and one virtual key with
  a daily budget and a rate limit (`config/bifrost.toml`). Terkini sends the virtual key as `x-bf-vk`, asks for
  non-streaming answers and passes a fallback list (`src/terkini/gateway.py`). The eval models are
  `gcli/grok-4.7` (xAI), `rv/moonshotai/Kimi-K3.1-Pro` (Moonshot AI) and `rv/deepseek-ai/DeepSeek-V4.1-Flash-1017`
  (DeepSeek). Claim extraction and the verdict use `rv/GLM-5.3` (Zhipu AI). Fallbacks are
  `rv/Qwen/Qwen3.8-27B-FP8`, `cf/@cf/meta/llama-3.3-70b-instruct-fp8-fast` and `rv/zai-org/GLM-5.3-Flash`
  (`config/models.toml`).
- **Why.** On 2026-11-20 we sent a one-line request straight to the provider for 18 model ids. Nine answered. Claude, GPT and Gemini ids
  timed out or were refused by the provider at that time, so they are not in the list. Through the gateway, the first
  try failed with "failed to unmarshal response" for every model except Grok: without `"stream": false` in the body
  the provider appends an SSE `data: [DONE]` line to a JSON answer, and the gateway drops that field. An
  `Accept: application/json` header on the provider (`extra_headers` in `config/bifrost.toml`) fixes it; after that
  all seven ids answered through the gateway. The judge comes from a fourth vendor so no eval model grades its own
  answer.
- **Would change if.** A Claude, GPT or Gemini id answers reliably before the eval run. Then it replaces one eval model
  and this entry is updated with the run date.

## D-013 · How one claim is verified and scored

- **Decision.** Each claim goes through the same steps: search on the pack domains only, one `advanced` retry when no
  official page comes back, extract the top two official pages, ask the judge model, then check its quote in code.
  The verdict stands only if the quote is on the page the judge names. If the judge gives an effective date, that
  date must be written inside the quote; otherwise the claim is `unverifiable`. A date with no quoted text is dropped.
  Scores round half up, so 37.5 is always 38. A Tavily `434` answer is retried once without `max_age_hours` and the
  result is marked as a Tavily cached copy.
- **Why.** The judge can invent quotes and dates. Checking both against the extracted text means every shown value
  traces back to an official page. Half-up rounding gives the same score on every machine.
- **Credits.** A call is refused before it is sent if its worst-case cost would cross the run or daily limit in
  `config/budget.toml`. The run then stops and lists the claims it did not check. A claim verified today is reused
  from the SQLite cache at no cost. Gateway or Tavily errors are reported per claim and never cached.
- **Would change if.** The eval shows many correct claims marked `unverifiable` because pages write dates in a form
  the judge rewrites. Then the prompt is tightened first; the code check stays.

## D-014 · Snippet fallback and recorded runs

- **Decision.** Copies of one page (`http` and `https`, trailing slash) are sent to Extract once, as `https`. When
  every official page refuses extraction, the judge reads the Tavily Search snippets from those official pages
  instead. The quote check still runs on that text, and the claim is marked "search snippet". A gateway timeout
  now fails one claim, not the whole run. The client waits up to 300 s for a model answer.
- **Why.** In the first live runs on 20 Nov 2026, the minimum wage and EPF pages refused Tavily Extract. Search
  had already returned the relevant official text. Without the fallback, every claim on those sites was
  `unverifiable`. One judge call also stalled past 120 s and stopped the run.
- **Recorded runs.** `scripts/record-run.py` asks one eval model a pack question, checks the answer live and saves
  the run to `tests/fixtures/runs/`. A recording keeps search snippets, model answers and windows of at most 500
  characters around each quote the judge cited. It keeps no keys, headers or full pages. The script replays the
  run offline right away and deletes it if the report differs. `terkini check` replays these runs when no Tavily
  key is set.
- **Would change if.** Snippets turn out to cut quotes short often. Then Search with `include_raw_content` is
  measured against Extract.

## D-015 · How the eval is run and scored

- **Decision.** `terkini ask` puts each of the 23 questions to the three eval models through the gateway, with no
  fallback, and saves one answer per question and model in `eval/my/answers/`. Each answer is then labelled
  against `eval/my/key.yaml` in `eval/my/labels.yaml`: `stale: true` when it states a value or rule that differs from
  the key, `false` when it states the key value, `null` when it gives no value. Labels were committed before the
  checker ran on any answer. `terkini eval` checks every answer live and saves one run per answer in `eval/my/runs/`.
  `results.json` is computed from the runs, the labels and the key only, and a test recomputes it.
- **Scoring.** Detection is scored per answer: an answer is flagged when at least one of its claims is `outdated`.
  Precision is flagged answers that are labelled stale over all flagged answers. Recall is flagged stale answers over
  all stale answers. Claim counts, the share of claims decided with an exact quote, quoted effective dates against
  the key, Tavily credits, model tokens and time per answer are reported next to it.
- **Why.** The key holds one fact per question, not one per claim. Scoring per answer compares like with like and
  needs no judgement about which claim maps to the key. A label of "differs from the key" also counts answers that
  were never right; the label notes say which.
- **Not changed after seeing results.** The checker, prompts and search settings were not tuned on these answers.
  Failures found in the eval are listed in `docs/EVAL.md` and left for later work.
- **Would change if.** The question set grows past one fact per question. Then claims are matched to key facts
  and scored per claim.

## D-016 · The replay page

- **Decision.** The page is one static HTML file, `docs/index.html`, with `docs/app.js`. It reads JSON only:
  `docs/i18n.json` and `docs/cases/*.json`. `scripts/build-pages.py` writes those files from `config/pages.toml`,
  `i18n/en.json` and `i18n/ms.json`. GitHub Pages serves `docs/`. `terkini serve` (FastAPI) serves the same files on
  127.0.0.1 and nothing else from `docs/`.
- **Cases.** Six real runs. Three are recordings, replayed through the checker when the page data is built. The
  other three are eval runs, shown as they were checked live. A test rebuilds the data and fails if a committed file
  differs, so a code change that alters a verdict shows up.
- **Claims in the answer.** The extractor rewrites claims, so they rarely appear word for word. Each claim is
  placed on the answer sentence that shares the most words with it. A sentence that holds several claims takes the
  most serious verdict. A claim with no matching sentence keeps its card and stays unmarked in the text.
- **Paste box.** The page holds no key and makes no live calls. A pasted answer that matches a recorded run opens
  it. Any other answer gets the command to check it on your own machine.
- **Type.** Barlow and IBM Plex Mono, self-hosted under the SIL Open Font License (`docs/fonts/`), the same faces as
  the slides. No request leaves the page.
- **Would change if.** A live mode is added to `terkini serve`. Then the paste box posts to it when it runs locally.

## D-017 · `POST /api/check`, and no India pack in this window

- **Decision.** `terkini serve` answers `POST /api/check` with `{"answer", "pack", "case"}` and returns the
  CLI's report as JSON, plus `mode` and `pack`. The CLI and the API share one function (`terkini.service.run`),
  so they cannot disagree on mode or result.
- **Mode.** A named `case` always replays. Otherwise the check is live when `TAVILY_API_KEY` is set and replays
  the recording whose answer matches when it is not. Replay mode with no match returns 404 and says how to go live.
- **Limits.** The default pack and the longest answer accepted are in `config/api.toml`. A longer answer gets 413
  before any model or search call. Live runs keep the credit limits in `config/budget.toml`.
- **Exposure.** Live mode spends the key holder's credits. The server binds to 127.0.0.1 by default and has no
  login, so it is for one machine or a private network, not the open internet.
- **India pack.** Not built. The Tavily plan has 1,000 credits a month, and the build and the Malaysian eval used
  their share. A second pack needs its own answer key read from official pages and an eval run at the same size;
  doing that on the reserve would leave nothing for fixes.
- **Page.** The paste box on the replay page still opens recordings only. Posting to the API when the page is
  served locally is left for later.
- **Would change if.** The credit limit rises. Then the India pack is built the same way as `packs/my.toml`.

## D-018 · One-command demo, public CI, community files

- **Demo.** `demo/run.sh` runs the official uv image (pinned by digest) with the repository mounted read-only. It
  installs the locked dependencies inside the container and starts `terkini serve` in replay mode. There is no
  Dockerfile and no image to build or publish, so the demo cannot drift from the code in the clone.
- **Port and cleanup.** It takes the first free port from 8710 upwards. If the server does not answer within the
  wait limit, or the container stops, the script prints the last log lines and removes the container.
  `demo/run.sh stop` removes it too. The container gets one CPU and 768 MB.
- **No key in the demo.** The script clears `TAVILY_API_KEY`, so the demo can only replay. Live mode stays a step
  a user takes on purpose, with their own key.
- **CI.** GitHub Actions runs `scripts/gerbang-ujian.sh` on every push and pull request: the same offline tests,
  no secrets, no network calls from tests.
- **No Dependabot yet.** It opens pull requests as soon as it is turned on. The pinned versions are tested together
  in `uv.lock`; dependency updates can wait for a quieter time.

## D-019 · Demo video rendered from the real page, with a cloned voice

- **Method.** The video is a web page drawn frame by frame (`demo/video/work/stage.html`, a pure function of time),
  not a screen recording. Frames do not drop when the machine is busy, and one scene can be redrawn alone. The
  replay page in the video is a capture of `docs/` served on localhost (`demo/video/tangkap.py`), so it shows what a
  judge sees on Pages.
- **Numbers on screen.** The capture script reads the domain list from `packs/my.toml` and the counts from
  `eval/my/results.json`. The stage prints those values; it holds no counts of its own.
- **Voice.** The narration is an AI clone of the builder's own voice (ElevenLabs), labelled on the end card and in
  the README's AI disclosure. Captions are burned in, and the same lines are in `docs/media/terkini-demo.srt`.
- **Format.** One 16:9 1080p file, 72 seconds. Loudness -16.5 LUFS, true peak under -1.5 dBTP. Music (CC BY 4.0,
  credited on the end card) sits well under the voice.
- **Not in the repository.** The video kit, the voice files and the frames. They are build tools and media, and
  the voice files are biometric data.
- **Scene order.** Frame 0 already shows the question and the stale answer, with no fade-in. The real replay page
  starts at 7 s, straight after the hook. The eval chart comes after Bifrost, just before the precision and recall
  numbers. The narration lines did not change; only their order did.
