"""Direct liveness check (D-011): a dead official page is a MISS even when an extract still has its text. No network."""

from __future__ import annotations

import httpx

from terkini.liveness import Live, VerifyConfig, classify, load_verify_config, probe, verdict

CFG = VerifyConfig(timeout_seconds=5, user_agent="test", blocked_status=frozenset({403, 429}))


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_config_loads_with_blocked_statuses():
    cfg = load_verify_config()
    assert cfg.timeout_seconds > 0 and cfg.user_agent
    assert all(400 <= s < 600 for s in cfg.blocked_status)


def test_classify():
    assert classify(200, CFG) is Live.OK
    assert classify(301, CFG) is Live.OK
    assert classify(404, CFG) is Live.DEAD
    assert classify(500, CFG) is Live.DEAD
    assert classify(403, CFG) is Live.BLOCKED


def test_probe_reports_404_as_dead():
    live, detail = probe("https://example.gov.my/gone.pdf", CFG, _client(lambda req: httpx.Response(404)))
    assert (live, detail) == (Live.DEAD, "404")


def test_probe_sends_configured_user_agent():
    seen = {}

    def handler(req):
        seen["ua"] = req.headers["user-agent"]
        return httpx.Response(200)

    assert probe("https://example.gov.my/a", CFG, _client(handler))[0] is Live.OK
    assert seen["ua"] == "test"


def test_probe_connection_reset_is_blocked():
    def handler(req):
        raise httpx.ConnectError("reset", request=req)

    assert probe("https://example.gov.my/a", CFG, _client(handler)) == (Live.BLOCKED, "ConnectError")


def test_dead_page_is_miss_even_when_cached_extract_has_the_quote():
    assert verdict(Live.DEAD, extract_failed=False, quote_found=True) == "MISS"


def test_failed_extract_is_miss():
    assert verdict(Live.OK, extract_failed=True, quote_found=True) == "MISS"


def test_blocked_site_with_quote_is_reported_not_missed():
    assert verdict(Live.BLOCKED, extract_failed=False, quote_found=True) == "BLOCKED"
    assert verdict(Live.OK, extract_failed=False, quote_found=True) == "ok"
