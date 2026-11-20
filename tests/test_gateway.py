"""Bifrost gateway client (D4). No network: requests go to an httpx MockTransport or a recorded gateway answer."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from terkini.gateway import Gateway, GatewayError, GatewayNotConfigured, ModelsConfig, load_gateway_config, parse_chat

FIXTURES = Path(__file__).parent / "fixtures" / "bifrost"


def _gateway(handler) -> Gateway:
    return Gateway(client=httpx.Client(transport=httpx.MockTransport(handler)), url="http://gw.test", virtual_key="vk-test")


def test_config_has_three_vendors_and_two_fallbacks():
    cfg = load_gateway_config()
    m = cfg.models
    assert len(m.models) >= 3 and len(m.fallbacks) >= 2
    assert len({m.vendors[x] for x in m.models}) >= 3, "eval models should come from different vendors"
    assert not set(m.models) & set(m.fallbacks)
    assert cfg.ref("x/y") == f"{cfg.provider_name}/x/y"
    assert cfg.virtual_key["name"] and cfg.virtual_key["budgets"] and cfg.virtual_key["rate_limit"]


def test_models_config_rejects_alias_and_short_lists():
    ok = dict(models=["a", "b", "c"], fallbacks=["d", "e"], extractor="a", judge="a", vendors={"a": "A", "b": "B", "c": "C"})
    ModelsConfig(**ok)
    with pytest.raises(ValueError):
        ModelsConfig(**{**ok, "models": ["a", "b"]})
    with pytest.raises(ValueError):
        ModelsConfig(**{**ok, "fallbacks": ["d"]})
    with pytest.raises(ValueError):
        ModelsConfig(**{**ok, "judge": "Fallback"})


def test_chat_sends_virtual_key_fallbacks_and_no_stream():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["vk"] = req.headers.get("x-bf-vk")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"model": "m", "choices": [{"message": {"content": "hi"}}],
                                         "usage": {"prompt_tokens": 3, "completion_tokens": 1}})

    g = _gateway(handler)
    r = g.chat("kr/a", [{"role": "user", "content": "q"}], fallbacks=["kr/a", "kr/b"], json_mode=True)
    p = g.cfg.provider_name
    assert seen["url"] == "http://gw.test/v1/chat/completions"
    assert seen["vk"] == "vk-test"
    assert seen["body"]["model"] == f"{p}/kr/a"
    assert seen["body"]["stream"] is False
    assert seen["body"]["fallbacks"] == [f"{p}/kr/b"]  # the primary model is not repeated
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert (r.text, r.prompt_tokens, r.completion_tokens) == ("hi", 3, 1)


def test_chat_error_carries_gateway_message_not_key():
    g = _gateway(lambda req: httpx.Response(429, json={"error": {"message": "budget exceeded"}}))
    with pytest.raises(GatewayError) as e:
        g.chat("kr/a", [{"role": "user", "content": "q"}])
    assert "429" in str(e.value) and "budget exceeded" in str(e.value)
    assert "vk-test" not in str(e.value)


def test_missing_env_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("BIFROST_URL", raising=False)
    monkeypatch.delenv("BIFROST_VIRTUAL_KEY", raising=False)
    with pytest.raises(GatewayNotConfigured):
        Gateway()


def test_recorded_gateway_answer_parses():
    files = sorted(FIXTURES.glob("*.json"))
    assert files, "record at least one real gateway answer (scripts/bifrost-record.py)"
    for f in files:
        rec = json.loads(f.read_text(encoding="utf-8"))
        assert rec["request"]["stream"] is False
        r = parse_chat(rec["response"])
        assert r.text.strip()
        assert r.prompt_tokens > 0 and r.completion_tokens > 0
        assert rec["request"]["model"].endswith(rec["upstream_model"])
