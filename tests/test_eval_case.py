"""`check --case` and `POST /api/check` also show a saved eval run (D-023): no key, no network, report as saved."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from terkini.cli import main
from terkini.evaluate import AnswerRun
from terkini.service import NoRecording, eval_runs_folder, run
from terkini.web import create_app

RUN_PATH = sorted(eval_runs_folder("my").glob("*.json"))[0]
SAVED = AnswerRun.model_validate_json(RUN_PATH.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)


def test_service_shows_a_saved_eval_run_as_checked():
    out = run(None, pack="my", case=RUN_PATH.stem)
    assert out.mode == f"eval run, {SAVED.checked_at[:10]}"
    assert out.report == SAVED.report
    assert out.answer.strip() and out.answer != RUN_PATH.stem  # the answer text, not the file name
    assert out.answer_model == SAVED.model and out.recording is None


@pytest.mark.parametrize("name", ["../answers/" + RUN_PATH.stem, "no-such-run", ""])
def test_names_outside_the_runs_folder_are_not_found(name):
    with pytest.raises(NoRecording):
        run("an answer nobody recorded", pack="my", case=name or None)


def test_cli_prints_the_eval_run(capsys):
    assert main(["check", "--case", RUN_PATH.stem]) == 0
    out = capsys.readouterr().out
    assert "(eval run, " in out and "Not legal advice" in out


def test_cli_list_names_eval_runs(capsys):
    assert main(["check", "--list"]) == 0
    rows = [line.split("\t") for line in capsys.readouterr().out.splitlines()]
    assert [RUN_PATH.stem, "eval"] in [r[:2] for r in rows]
    assert {r[1] for r in rows} == {"recorded", "eval"}


def test_api_shows_the_eval_run():
    r = TestClient(create_app()).post("/api/check", json={"case": RUN_PATH.stem})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"].startswith("eval run") and body["results"] == json.loads(SAVED.report.model_dump_json())["results"]
