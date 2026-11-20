"""Record and replay (PRD §3 P0.7, D13): recordings keep excerpts only, and replay reproduces the live report. No network."""

from __future__ import annotations

import json
from contextlib import closing

import pytest
from conftest import TODAY, FakeGateway, FakeTavily, extract_body, search_body

from terkini.cache import Cache
from terkini.cli import main
from terkini.replay import (
    EXCERPT_CHARS,
    Cassette,
    RecordingGateway,
    RecordingTavily,
    ReplayMismatch,
    excerpts,
    list_cassettes,
    write_cassette,
)
from terkini.runner import replay, run_check, runs_dir

QUOTE = "The minimum wage is RM1,700 per month effective 1 August 2025."
PAGE = ("Intro text. " * 200) + QUOTE + (" Footer text." * 200)


def test_excerpt_keeps_quote_within_limit():
    out = excerpts(PAGE, [QUOTE])
    assert len(out) == 1 and QUOTE in out[0] and len(out[0]) <= EXCERPT_CHARS


def test_quote_not_on_page_is_not_invented():
    out = excerpts(PAGE, ["RM1,500 per month"])
    assert out == [PAGE[:200]] and "RM1,500" not in out[0]


def _live_run(pack):
    official = f"https://{pack.domains[0].domain}/wages"
    cat = next(c for c in pack.categories if c.volatile).id
    tv = FakeTavily()
    tv.searches.append(search_body((official, "2025-08-01"), ("https://news.example/a", None)))
    tv.extracts.append(extract_body({official: PAGE}))
    gw = FakeGateway(
        {"claims": [{"claim": "Malaysia's minimum wage is RM1,500 a month.", "category": cat, "value": "RM1,500",
                     "time_sensitive": True}]},
        {"verdict": "outdated", "current_value": "RM1,700", "evidence_quote": QUOTE, "source_url": official,
         "effective_date_text": "1 August 2025", "effective_date": "2025-08-01"},
    )
    rec_t, rec_g = RecordingTavily(tv.client()), RecordingGateway(gw)
    with closing(Cache(":memory:")) as cache:
        report = run_check("The minimum wage is RM1,500.", pack_id=pack.id, tavily=rec_t, gateway=rec_g, cache=cache,
                           today=TODAY)
    rec_t.cut(rec_g.chats)
    return Cassette(name="t", pack=pack.id, recorded_at="2026-11-21T00:00:00Z", checked_on=TODAY,
                    answer="The minimum wage is RM1,500.", chats=rec_g.chats, searches=rec_t.searches,
                    extracts=rec_t.extracts, report=report.model_dump(mode="json"))


def test_replay_reproduces_live_report(pack):
    c = _live_run(pack)
    assert c.report["results"][0]["verdict"] == "outdated"
    assert all(len(x) <= EXCERPT_CHARS for e in c.extracts for xs in e.excerpts.values() for x in xs)
    assert replay(c).model_dump(mode="json") == c.report


def test_replay_refuses_a_different_run(pack):
    c = _live_run(pack)
    c.searches[0].query = "something else"
    with pytest.raises(ReplayMismatch):
        replay(c)


def test_gateway_failure_is_recorded_and_replayed(pack):
    from terkini.gateway import GatewayError

    class Failing(FakeGateway):
        def chat(self, model, messages, **kw):
            if len(self.calls) == 1:
                self.calls.append({})
                raise GatewayError("gateway request failed: ReadTimeout")
            return super().chat(model, messages, **kw)

    official = f"https://{pack.domains[0].domain}/wages"
    cat = next(c for c in pack.categories if c.volatile).id
    tv = FakeTavily()
    tv.searches.append(search_body((official, None)))
    tv.extracts.append(extract_body({official: PAGE}))
    gw = Failing({"claims": [{"claim": "Minimum wage is RM1,500.", "category": cat, "time_sensitive": True}]})
    rec_t, rec_g = RecordingTavily(tv.client()), RecordingGateway(gw)
    with closing(Cache(":memory:")) as cache:
        report = run_check("x", pack_id=pack.id, tavily=rec_t, gateway=rec_g, cache=cache, today=TODAY)
    rec_t.cut(rec_g.chats)
    assert report.errors and rec_g.chats[1].error
    c = Cassette(name="t", pack=pack.id, recorded_at="2026-11-21T00:00:00Z", checked_on=TODAY, answer="x",
                 chats=rec_g.chats, searches=rec_t.searches, extracts=rec_t.extracts,
                 report=report.model_dump(mode="json"))
    assert replay(c).model_dump(mode="json") == c.report


def test_recording_refuses_secrets(tmp_path, pack):
    c = _live_run(pack)
    with pytest.raises(RuntimeError):
        write_cassette(c, tmp_path, ["RM1,500"])
    assert not list(tmp_path.iterdir())


RECORDED = list_cassettes(runs_dir())


def test_at_least_three_recorded_runs():
    assert len(RECORDED) >= 3


@pytest.mark.parametrize("c", RECORDED, ids=lambda c: c.name)
def test_recorded_run_replays_offline(c):
    assert replay(c).model_dump(mode="json") == c.report


@pytest.mark.parametrize("c", RECORDED, ids=lambda c: c.name)
def test_recorded_run_keeps_no_full_page(c):
    for e in c.extracts:
        assert all(len(x) <= EXCERPT_CHARS for xs in e.excerpts.values() for x in xs)
    for s in c.searches:
        assert all(len(r.get("content") or "") <= EXCERPT_CHARS for r in s.results)
    text = c.model_dump_json()
    assert "Authorization" not in text and "x-bf-vk" not in text and "tvly-" not in text


def test_cli_replays_a_case_without_key(monkeypatch, capsys):
    monkeypatch.setenv("TAVILY_API_KEY", "")
    c = RECORDED[0]
    assert main(["check", "--case", c.name, "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"].startswith("recorded run") and out["results"] == c.report["results"]


def test_cli_matches_pasted_recorded_answer(monkeypatch, capsys):
    monkeypatch.setenv("TAVILY_API_KEY", "")
    c = RECORDED[0]
    assert main(["check", "--pack", c.pack, "  " + c.answer + "\n"]) == 0
    assert "Not legal advice" in capsys.readouterr().out


def test_cli_unknown_answer_without_key_explains(monkeypatch, capsys):
    monkeypatch.setenv("TAVILY_API_KEY", "")
    assert main(["check", "an answer nobody recorded"]) == 2
    assert "--case" in capsys.readouterr().err
