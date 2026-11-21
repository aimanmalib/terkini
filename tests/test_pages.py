"""The recorded-run page (PRD §3 P0.8, P0.12, D10, D12): data files, language parity, claim marks, local server."""

from __future__ import annotations

import json
import re

from fastapi.testclient import TestClient

from terkini.packs import REPO_ROOT
from terkini.pages import build_files, claim_spans, load_pages_config, load_strings, sentences
from terkini.web import create_app

DOCS = REPO_ROOT / "docs"


def _result(claim: str, verdict: str, value: str = "") -> dict:
    return {"claim": {"claim": claim, "value": value}, "verdict": verdict}


def test_committed_page_data_matches_a_fresh_build():
    # Recorded runs are replayed through today's checker: a code change that alters a verdict shows up here.
    for rel, text in build_files().items():
        assert (REPO_ROOT / rel).read_text(encoding="utf-8") == text, f"{rel} is stale: run scripts/build-pages.py"


def test_page_has_six_recorded_runs_each_with_a_date_and_claims():
    cfg = load_pages_config()
    assert len(cfg.cases) >= 6
    for ref in cfg.cases:
        case = json.loads((DOCS / "cases" / f"{ref.id}.json").read_text(encoding="utf-8"))
        assert case["run_at"] and case["question"] and case["answer"]
        assert case["report"]["results"], ref.id
        assert case["model"]["vendor"], ref.id


def test_every_ui_string_the_page_uses_exists_in_every_language():
    cfg = load_pages_config()
    strings = load_strings(cfg.languages)  # raises when key sets differ
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    js = (DOCS / "app.js").read_text(encoding="utf-8")
    used = set(re.findall(r'data-i18n(?:-placeholder|-aria-label)?="([a-z_]+)"', html))
    used |= set(re.findall(r'\bt\("([a-z_]+)"', js))
    used |= {f"verdict_{v}" for v in ("outdated", "current", "unverifiable")}
    used |= {"source_recording", "source_eval", "label_government", "label_utility"}
    for lang, s in strings.items():
        assert used <= set(s), (lang, sorted(used - set(s)))
        assert all(isinstance(v, str) and v.strip() for v in s.values()), lang



def test_page_offers_local_commands_instead_of_a_check_button_it_cannot_run():
    # D-024: the page has no key, so it must not show a paste box with a "Check" button; it gives the local commands.
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    js = (DOCS / "app.js").read_text(encoding="utf-8")
    assert "<textarea" not in html and 'type="submit"' not in html
    assert 'data-i18n="own_command"' in html and 'id="copy"' in html
    for key in re.findall(r'say\("([a-z_]+)"\)', js):
        for lang, s in load_strings(load_pages_config().languages).items():
            assert key in s, (lang, key)
    for lang, s in load_strings(load_pages_config().languages).items():
        assert "terkini check --pack" in s["own_command"], lang


def test_phone_layout_puts_the_selected_run_before_the_list_of_runs():
    # D-024: below 60rem the rail is flattened and ordered tagline, result, runs, own check.
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    phone = html[html.index("@media (max-width: 59.99rem)"):]
    phone = phone[: phone.index("}\n  }") + 1]
    order = {name: int(n) for name, n in re.findall(r"\.(lede|result|runs|own) \{ order: (\d+); \}", phone)}
    assert ".rail { display: contents; }" in phone
    assert order["lede"] < order["result"] < order["runs"] < order["own"]

def test_sentences_skip_list_markers_and_keep_decimals_together():
    text = "- Rate is 6.5% now. Next line\n* RM1,700 since 2025!"
    parts = [text[a:b] for a, b in sentences(text)]
    assert parts == ["Rate is 6.5% now.", "Next line", "RM1,700 since 2025!"]


def test_claim_marks_the_sentence_that_shares_most_words():
    answer = "The minimum wage is RM1,500. It applies to all employers in Malaysia."
    spans = claim_spans(answer, [_result("Malaysia's minimum wage is RM1,500 per month.", "outdated", "RM1,500")])
    assert [(answer[s["start"]:s["end"]], s["verdict"], s["claims"]) for s in spans] == [
        ("The minimum wage is RM1,500.", "outdated", [0])]


def test_sentence_with_several_claims_shows_the_most_serious_verdict():
    answer = "Employees pay 11% and employers pay 12% of wages."
    spans = claim_spans(answer, [_result("Employers pay 12% of wages.", "current"),
                                 _result("Employees pay 11% of wages.", "outdated"),
                                 _result("Employees pay 11% and employers 12%.", "unverifiable")])
    assert len(spans) == 1 and spans[0]["verdict"] == "outdated" and spans[0]["claims"] == [0, 1, 2]


def test_claim_with_no_matching_sentence_is_left_unmarked():
    assert claim_spans("Paternity leave is seven days.", [_result("Service tax is 8% from March 2024.", "current")]) == []


def test_local_server_serves_the_page_and_its_data_only():
    client = TestClient(create_app())
    assert client.get("/").status_code == 200
    assert "app.js" in client.get("/").text
    assert client.get("/i18n.json").json()["languages"] == load_pages_config().languages
    index = client.get("/cases/index.json").json()
    assert client.get(f"/cases/{index['cases'][0]['id']}.json").status_code == 200
    assert client.get("/fonts/barlow-400.woff2").status_code == 200
    assert client.get("/healthz").json()["ok"] is True
    for private in ("/PRD.md", "/02-DECISIONS.md", "/../pyproject.toml"):
        assert client.get(private).status_code == 404
