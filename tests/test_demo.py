"""The one-command demo script: valid bash, pinned image, replay only."""

import re
import subprocess
from pathlib import Path

RUN = Path(__file__).resolve().parents[1] / "demo" / "run.sh"


def test_demo_script_parses():
    subprocess.run(["bash", "-n", str(RUN)], check=True)


def test_demo_image_is_pinned_by_digest():
    image = re.search(r'^IMAGE="([^"]+)"', RUN.read_text(), re.M).group(1)
    assert re.fullmatch(r"[\w./-]+@sha256:[0-9a-f]{64}", image)


def test_demo_never_passes_a_tavily_key():
    text = RUN.read_text()
    assert "-e TAVILY_API_KEY= " in text
    assert "$TAVILY_API_KEY" not in text


def test_demo_binds_to_localhost_and_cleans_up():
    text = RUN.read_text()
    assert '-p "127.0.0.1:$PORT:' in text
    assert "trap " in text and "remove" in text


def test_demo_case_opens_without_a_key(monkeypatch):
    from terkini.service import run

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    case = re.search(r'^CASE="([^"]+)"', RUN.read_text(), re.M).group(1)
    assert run(None, pack="my", case=case).report.results
