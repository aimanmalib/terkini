"""The "How this check ran" panel data (PRAHANTAR J4): built from saved runs only, no network."""

from __future__ import annotations

from terkini.evaluate import Answer, AnswerRun, eval_dir, load_eval_config
from terkini.gateway import load_gateway_config
from terkini.packs import REPO_ROOT, load_pack
from terkini.replay import SearchCall, load_cassette
from terkini.runner import replay, runs_dir
from terkini.trace import _call, trace_eval, trace_recording
from terkini.verify import build_query, load_verify_config

PACK = load_pack("my")


def _recording(name: str):
    c = load_cassette(runs_dir(REPO_ROOT) / f"{name}.json")
    return c, replay(c)


def test_fallback_is_the_answering_model_differing_from_the_one_asked_for():
    assert _call("judge", "rv/GLM-5.3", "GLM-5.3", 1, 1, 1.0)["fallback"] is False
    assert _call("answer", "rv/moonshotai/Kimi-K3.1-Pro", "moonshotai/Kimi-K3.1-Pro", 1, 1, 1.0)["fallback"] is False
    assert _call("judge", "rv/GLM-5.3", "Qwen/Qwen3.8-27B-FP8", 1, 1, 1.0)["fallback"] is True
    assert _call("judge", "rv/GLM-5.3", "", 1, 1, 1.0)["fallback"] is None  # the call failed: nothing answered


def test_recording_shows_every_gateway_call_with_its_tokens():
    c, report = _recording("my-09-grok-4-7")
    gw = trace_recording(c, report, PACK)["gateway"]
    assert [g["step"] for g in gw["calls"]] == ["answer", "extract"] + ["judge"] * (len(c.chats) - 1)
    assert gw["total_calls"] == 1 + len(c.chats)
    assert gw["tokens_in"] == c.ask.prompt_tokens + sum(ch.prompt_tokens for ch in c.chats)
    assert gw["tokens_out"] == c.ask.completion_tokens + sum(ch.completion_tokens for ch in c.chats)
    used = [g for g in gw["calls"] if g["fallback"]]
    assert used == [g for g in gw["calls"] if g["answered_by"] and g["answered_by"] != g["model"].split("/", 1)[1]]
    assert gw["fallbacks"] == load_gateway_config().models.fallbacks


def test_recording_queries_and_depths_come_from_the_saved_searches():
    c, report = _recording("my-12-kimi-k3-1-pro")
    tv = trace_recording(c, report, PACK)["tavily"]
    s = load_verify_config().search
    assert tv["log"] == "recorded" and tv["include_domains"] == PACK.domain_names
    assert tv["credits"] == report.credits
    for q, r in zip(tv["claims"], report.results, strict=True):
        assert q["query"] == build_query(r.claim, s.max_query_chars)
        assert q["credits"] == r.credits
        assert q["depths"] and set(q["depths"]) <= {s.search_depth, s.retry_depth}
        assert all(any(sc.query == q["query"] and sc.search_depth == d for sc in c.searches) for d in q["depths"])


def test_a_search_with_no_official_page_is_paired_with_its_retry():
    c, report = _recording("my-09-grok-4-7")
    s = load_verify_config().search
    first = build_query(report.results[0].claim, s.max_query_chars)
    miss = SearchCall(query=first, search_depth=s.search_depth, results=[{"url": "https://example.com/a"}])
    retry = SearchCall(query=first, search_depth=s.retry_depth, results=[{"url": "https://www.mof.gov.my/x"}])
    rest = [sc for sc in c.searches if sc.query != first]
    tv = trace_recording(c.model_copy(update={"searches": [miss, retry, *rest]}), report, PACK)["tavily"]
    assert tv["claims"][0]["depths"] == [s.search_depth, s.retry_depth]


def test_eval_case_says_what_was_not_saved_instead_of_guessing():
    cfg = load_eval_config()
    folder = eval_dir(PACK)
    a = Answer.model_validate_json((folder / cfg.answers_dir / "my-03--grok-4-7.json").read_text(encoding="utf-8"))
    run = AnswerRun.model_validate_json((folder / cfg.runs_dir / "my-03--grok-4-7.json").read_text(encoding="utf-8"))
    tr = trace_eval(a, run, PACK)
    assert tr["tavily"]["log"] == "settings"
    assert all(q["depths"] is None for q in tr["tavily"]["claims"])
    assert [q["from_cache"] for q in tr["tavily"]["claims"]] == [r.credits == 0 for r in run.report.results]
    answer, check = tr["gateway"]["calls"]
    assert answer["fallback"] is False and check["fallback"] is None
    assert check["calls"] == run.gateway_calls and tr["gateway"]["total_calls"] == 1 + run.gateway_calls
    assert tr["gateway"]["tokens_in"] == a.prompt_tokens + run.prompt_tokens
