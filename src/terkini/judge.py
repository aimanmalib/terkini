"""Judge (PRD §3 P0.3): one model call through Bifrost compares a claim with extracted official pages.

The judge only proposes. verify.py accepts the verdict only after the exact-quote check (D7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from string import Template

from pydantic import ValidationError

from terkini.claims import Claim, Judgement
from terkini.extractor import ChatClient, ModelOutputError, load_prompts, parse_json_object


@dataclass(frozen=True)
class Page:
    url: str
    text: str
    published: str | None = None


def judge_claim(gateway: ChatClient, model: str, claim: Claim, pages: list[Page], *, country: str, today: date,
                max_page_chars: int, fallbacks: list[str] | None = None, prompts: dict | None = None) -> Judgement:
    p = (prompts or load_prompts())["judge"]
    page_block = "".join(
        Template(p["page"]).substitute(n=i + 1, url=pg.url, published=pg.published or "unknown",
                                       text=pg.text[:max_page_chars])
        for i, pg in enumerate(pages)
    )
    system = Template(p["system"]).substitute(country=country, today=today.isoformat())
    user = Template(p["user"]).substitute(
        claim=claim.claim, category=claim.category, value=claim.value, unit=claim.unit,
        stated_date=claim.stated_date or "none", pages=page_block,
    )
    res = gateway.chat(model, [{"role": "system", "content": system.strip()}, {"role": "user", "content": user.strip()}],
                       fallbacks=fallbacks, json_mode=True)
    data = parse_json_object(res.text)
    try:
        return Judgement.model_validate({k: ("" if v is None else v) for k, v in data.items()})
    except ValidationError as e:
        raise ModelOutputError(f"judge answer does not match the schema: {e.error_count()} errors") from None
