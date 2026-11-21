"""Budget guard (D-025): Bifrost Meter's `guard` before a run that spends. No network, no Node: the process is faked."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from terkini import cli, guard
from terkini.guard import (
    GuardConfig,
    GuardResult,
    guard_env,
    load_guard_config,
    preflight,
    run_guard,
)
from terkini.packs import REPO_ROOT


def cfg(tmp_path: Path, **over) -> GuardConfig:
    (tmp_path / "meter").mkdir(exist_ok=True)
    (tmp_path / "meter" / "cli.js").write_text("// fake\n")
    base = {"enabled": True, "node": "node", "cli": "meter/cli.js", "min_remaining": 20, "on_error": "continue",
            "timeout_seconds": 5, "commands": ["check", "ask", "eval", "baseline", "hybrid"]}
    return GuardConfig(**{**base, **over})


def fake(code: int, out: str = "", err: str = ""):
    calls = []

    def runner(argv, **kw):
        calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, code, out, err)
    runner.calls = calls
    return runner


def test_shipped_config_is_off_and_valid():
    c = load_guard_config(REPO_ROOT)
    assert c.enabled is False
    assert c.on_error in ("continue", "stop")


def test_go_passes_the_min_remaining_and_maps_the_gateway_url(tmp_path):
    r = fake(0, "Bifrost guard: go. Closest limit: 0% · $5.00 left; at least 20% left is required.\n")
    res = run_guard(cfg(tmp_path), tmp_path, {"BIFROST_URL": "http://127.0.0.1:1", "BIFROST_VIRTUAL_KEY": "vk"}, r)
    assert res == GuardResult(0, "Bifrost guard: go. Closest limit: 0% · $5.00 left; at least 20% left is required.")
    argv, kw = r.calls[0]
    assert argv[0] == "node" and argv[1] == str(tmp_path / "meter" / "cli.js")
    assert argv[2:] == ["guard", "--min-remaining", "20"]
    assert kw["env"]["BIFROST_BASE_URL"] == "http://127.0.0.1:1"
    assert kw["env"]["BIFROST_VIRTUAL_KEY"] == "vk"
    assert kw["timeout"] == 5


def test_existing_base_url_wins():
    assert guard_env({"BIFROST_URL": "a", "BIFROST_BASE_URL": "b"})["BIFROST_BASE_URL"] == "b"


def test_stop_and_unknown_codes(tmp_path):
    assert run_guard(cfg(tmp_path), tmp_path, {}, fake(2, "Bifrost guard: stop. Requests used up.\n")).code == 2
    res = run_guard(cfg(tmp_path), tmp_path, {}, fake(1, "", "Bifrost Key rejected\n"))
    assert res == GuardResult(1, "Bifrost Key rejected")
    assert run_guard(cfg(tmp_path), tmp_path, {}, fake(7)).code == 1


def test_missing_cli_node_and_timeout_are_errors(tmp_path):
    assert run_guard(cfg(tmp_path, cli="nowhere.js"), tmp_path, {}, fake(0)).code == 1

    def no_node(argv, **kw):
        raise FileNotFoundError(argv[0])

    def slow(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])
    assert run_guard(cfg(tmp_path), tmp_path, {}, no_node).code == 1
    assert "within 5 s" in run_guard(cfg(tmp_path), tmp_path, {}, slow).sentence


def write_cfg(root: Path, **over) -> None:
    (root / "config").mkdir()
    shutil.copy(REPO_ROOT / "config" / "guard.toml", root / "config" / "guard.toml")
    text = (root / "config" / "guard.toml").read_text()
    for k, v in over.items():
        text = "\n".join(f"{k} = {v}" if line.startswith(f"{k} =") else line for line in text.splitlines())
    (root / "config" / "guard.toml").write_text(text + "\n")


def test_preflight_off_or_other_command_never_runs(tmp_path):
    write_cfg(tmp_path)

    def boom(*a):
        raise AssertionError("guard ran while off")
    assert preflight("eval", tmp_path, boom) is None
    (tmp_path / "config").rename(tmp_path / "old")
    write_cfg(tmp_path, enabled="true", commands='["eval"]')
    assert preflight("ask", tmp_path, boom) is None


@pytest.mark.parametrize(("code", "on_error", "expected"), [
    (0, "continue", None), (2, "continue", 2), (1, "continue", None), (1, "stop", 2), (0, "stop", None)])
def test_preflight_decision(tmp_path, capsys, code, on_error, expected):
    write_cfg(tmp_path, enabled="true", on_error=f'"{on_error}"')
    assert preflight("eval", tmp_path, lambda c, r: GuardResult(code, "Bifrost guard: sentence.")) == expected
    err = capsys.readouterr().err
    assert "Bifrost guard: sentence." in err
    if code == 2:
        assert "stopped before any call" in err


def test_eval_stops_before_tavily_when_the_guard_says_stop(monkeypatch, capsys):
    on = load_guard_config(REPO_ROOT).model_copy(update={"enabled": True})
    monkeypatch.setattr(guard, "load_guard_config", lambda root: on)
    monkeypatch.setattr(guard, "run_guard", lambda c, r: GuardResult(2, "Bifrost guard: stop. Budget used up."))
    monkeypatch.setattr("terkini.evalcli._env", lambda: None)  # no .env from the working folder
    monkeypatch.setenv("TAVILY_API_KEY", "not-used")

    def no_tavily(*a, **k):
        raise AssertionError("Tavily was called after a stop")
    monkeypatch.setattr("terkini.tavily.Tavily.__init__", no_tavily)
    assert cli.main(["eval", "--pack", "my"]) == 2
    assert "eval: stopped before any call" in capsys.readouterr().err


def test_guard_command_reports_the_code(monkeypatch, capsys):
    seen = {}

    def fake_run(c, r):
        seen["min"] = c.min_remaining
        return GuardResult(2, "Bifrost guard: stop. Closest limit: Requests used up.")
    monkeypatch.setattr(guard, "run_guard", fake_run)
    monkeypatch.setattr("terkini.evalcli._env", lambda: None)
    assert cli.main(["guard", "--min-remaining", "0"]) == 2
    assert seen["min"] == 0
    assert "Requests used up" in capsys.readouterr().out
