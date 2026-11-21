"""`POST /api/check` (PRD §1 users 1, §3 P1): the CLI's check over HTTP. No network: replay mode, live mode stubbed."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from terkini import service
from terkini.checker import AnswerReport
from terkini.gateway import GatewayNotConfigured
from terkini.replay import list_cassettes
from terkini.runner import replay, runs_dir
from terkini.service import load_api_config
from terkini.web import create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    return TestClient(create_app())


@pytest.fixture(scope="module")
def recording():
    return list_cassettes(runs_dir(), "my")[0]


def test_replays_a_named_recording_like_the_cli(client, recording):
    r = client.post("/api/check", json={"case": recording.name})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == f"recorded run, {recording.recorded_at[:10]}"
    assert body["pack"] == load_api_config().default_pack
    want = replay(recording).model_dump(mode="json")
    assert {k: body[k] for k in want} == want


def test_pasted_recorded_answer_is_matched_despite_spacing(client, recording):
    r = client.post("/api/check", json={"answer": "  " + recording.answer.replace(" ", "  ") + "\n", "pack": "my"})
    assert r.status_code == 200
    assert [x["verdict"] for x in r.json()["results"]] == [x.verdict for x in replay(recording).results]


def test_unknown_answer_in_replay_mode_is_404_with_a_hint(client):
    r = client.post("/api/check", json={"answer": "The minimum wage is RM1 an hour."})
    assert r.status_code == 404
    assert "TAVILY_API_KEY" in r.json()["detail"]


@pytest.mark.parametrize("body", [{}, {"answer": "   "}])
def test_empty_request_is_422(client, body):
    assert client.post("/api/check", json=body).status_code == 422


def test_answer_over_the_configured_limit_is_413(client):
    limit = load_api_config().max_answer_chars
    assert client.post("/api/check", json={"answer": "x" * (limit + 1)}).status_code == 413


def test_unknown_pack_is_400(client, recording):
    assert client.post("/api/check", json={"case": recording.name, "pack": "zz"}).status_code == 400


def test_live_mode_with_a_key_calls_the_live_checker(monkeypatch, client):
    seen = {}

    def fake_live(answer, pack, root):
        seen.update(answer=answer, pack=pack)
        return AnswerReport(pack=pack, checked_on=date(2026, 11, 21), results=[])

    monkeypatch.setenv("TAVILY_API_KEY", "test-not-a-key")
    monkeypatch.setattr(service, "_live", fake_live)
    r = client.post("/api/check", json={"answer": "Some answer."})
    assert r.status_code == 200 and r.json()["mode"] == "live run"
    assert seen == {"answer": "Some answer.", "pack": "my"}


def test_live_mode_without_gateway_is_503(monkeypatch, client):
    def no_gateway(answer, pack, root):
        raise GatewayNotConfigured("BIFROST_URL is not set")

    monkeypatch.setenv("TAVILY_API_KEY", "test-not-a-key")
    monkeypatch.setattr(service, "_live", no_gateway)
    r = client.post("/api/check", json={"answer": "Some answer."})
    assert r.status_code == 503 and "Bifrost" in r.json()["detail"]
