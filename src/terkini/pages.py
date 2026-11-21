"""Data for the recorded-run page (PRD §3 P0.8, P0.12, D10): one JSON file per case, plus the UI strings.

The page itself (docs/index.html) is static and reads only these files, so GitHub Pages and `terkini serve` show the
same thing. Cases come from config/pages.toml. A recorded run is replayed through the checker here, so the report on
the page is what the code produces today; an eval run is shown as it was checked live.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from terkini.evaluate import Answer, AnswerRun, eval_dir, load_eval_config
from terkini.gateway import load_gateway_config
from terkini.packs import REPO_ROOT, load_pack
from terkini.replay import load_cassette
from terkini.runner import replay, runs_dir


class CaseRef(BaseModel):
    id: str
    source: Literal["recording", "eval"]
    pack: str = "my"


class ServeConfig(BaseModel):
    host: str
    port: int
    files: list[str]  # single files under out_dir served at /<name>
    folders: list[str]  # folders under out_dir served at /<name>/


class PagesConfig(BaseModel):
    out_dir: str
    languages: list[str]
    serve: ServeConfig
    cases: list[CaseRef]


def load_pages_config(root: Path = REPO_ROOT) -> PagesConfig:
    with open(root / "config" / "pages.toml", "rb") as f:
        return PagesConfig.model_validate(tomllib.load(f))


def _model_label(model: str, vendors: dict[str, str]) -> dict:
    """Show the exact model id without the gateway's provider prefix, plus the vendor."""
    return {"id": model, "name": model.rsplit("/", 1)[-1], "vendor": vendors.get(model, "")}


def build_case(ref: CaseRef, root: Path = REPO_ROOT) -> dict:
    vendors = load_gateway_config(root).models.vendors
    if ref.source == "recording":
        c = load_cassette(runs_dir(root) / f"{ref.id}.json")
        report = replay(c, root)
        question, model, answer, run_at = c.question, c.answer_model, c.answer, c.recorded_at
    else:
        folder = eval_dir(load_pack(ref.pack, root), root)
        cfg = load_eval_config(root)
        a = Answer.model_validate_json((folder / cfg.answers_dir / f"{ref.id}.json").read_text(encoding="utf-8"))
        run = AnswerRun.model_validate_json((folder / cfg.runs_dir / f"{ref.id}.json").read_text(encoding="utf-8"))
        report = run.report
        question, model, answer, run_at = a.question, a.model, a.answer, run.checked_at
    return {
        "id": ref.id,
        "source": ref.source,
        "run_at": run_at,
        "question": question,
        "model": _model_label(model, vendors),
        "answer": answer,
        "report": (rep := report.model_dump(mode="json")),
        "spans": claim_spans(answer, rep["results"]),
    }


_BREAK = re.compile(r"(?<=[.!?])[ \t]+|\n+")  # a sentence ends at . ! ? before a space, or at a line end
_WORD = re.compile(r"[a-z0-9%]+(?:[.,][0-9]+)*")
_RANK = {"outdated": 3, "unverifiable": 2, "current": 1}


def sentences(text: str) -> list[tuple[int, int]]:
    """(start, end) of each sentence or line, trimmed of surrounding spaces and list markers."""
    out, at = [], 0
    bounds = [(m.start(), m.end()) for m in _BREAK.finditer(text)] + [(len(text), len(text))]
    for end, nxt in bounds:
        a, b, at = at, end, nxt
        while a < b and (text[a].isspace() or text[a] in "-*•"):
            a += 1
        while b > a and text[b - 1].isspace():
            b -= 1
        if b > a:
            out.append((a, b))
    return out


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def claim_spans(answer: str, results: list[dict], min_overlap: float = 0.3) -> list[dict]:
    """Where each checked claim sits in the answer: the sentence that shares most words with it.

    Claims are rewritten by the extractor, so they rarely appear word for word. A sentence holding several claims takes
    the most serious verdict (outdated, then not settled, then current). Claims with no matching sentence stay
    unmarked in the text and still get their card.
    """
    spans: dict[tuple[int, int], list[int]] = {}
    parts = sentences(answer)
    for i, r in enumerate(results):
        want = _words(r["claim"]["claim"])
        value = r["claim"].get("value") or ""
        best, best_score = None, min_overlap
        for a, b in parts:
            sent = answer[a:b]
            score = len(want & _words(sent)) / max(len(want), 1) + (0.1 if value and value in sent else 0)
            if score > best_score:
                best, best_score = (a, b), score
        if best:
            spans.setdefault(best, []).append(i)
    return [{"start": a, "end": b, "claims": idx,
             "verdict": max((results[i]["verdict"] for i in idx), key=_RANK.__getitem__)}
            for (a, b), idx in sorted(spans.items())]


def case_summary(case: dict) -> dict:
    r = case["report"]
    counts = {v: sum(x["verdict"] == v for x in r["results"]) for v in ("outdated", "current", "unverifiable")}
    return {"id": case["id"], "question": case["question"], "model": case["model"]["name"],
            "run_at": case["run_at"], "counts": counts}


def load_strings(languages: list[str], root: Path = REPO_ROOT) -> dict[str, dict]:
    strings = {lang: json.loads((root / "i18n" / f"{lang}.json").read_text(encoding="utf-8")) for lang in languages}
    first = set(strings[languages[0]])
    for lang, s in strings.items():
        if set(s) != first:
            raise ValueError(f"i18n/{lang}.json keys differ from i18n/{languages[0]}.json: {sorted(set(s) ^ first)}")
    return strings


def build_files(root: Path = REPO_ROOT) -> dict[str, str]:
    """Every page data file, keyed by path relative to the repo root."""
    cfg = load_pages_config(root)
    cases = [build_case(ref, root) for ref in cfg.cases]
    files = {f"{cfg.out_dir}/cases/{c['id']}.json": _dump(c) for c in cases}
    files[f"{cfg.out_dir}/cases/index.json"] = _dump({"cases": [case_summary(c) for c in cases]})
    files[f"{cfg.out_dir}/i18n.json"] = _dump({"languages": cfg.languages, "strings": load_strings(cfg.languages, root)})
    return files


def _dump(data: dict) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"
