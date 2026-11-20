"""Check a whole AI answer (PRD §3 P0.1–P0.5): extract claims, verify each once, summarise the answer.

Claims are de-duplicated and looked up in the cache before any Tavily call (D11). When the credit guard refuses a call,
the run stops cleanly: claims already checked keep their result, the rest are listed as not checked.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from terkini.cache import Cache
from terkini.claims import Claim, ClaimResult
from terkini.credits import CreditLimitReached
from terkini.extractor import ChatClient, extract_claims
from terkini.gateway import GatewayError
from terkini.score import as_of
from terkini.tavily import TavilyHTTPError
from terkini.verify import Verifier


class ClaimError(BaseModel):
    claim: Claim
    error: str


class AnswerReport(BaseModel):
    pack: str
    checked_on: date
    results: list[ClaimResult]
    not_checked: list[Claim] = []
    errors: list[ClaimError] = []  # a gateway or Tavily failure for one claim; not cached, safe to retry
    stopped: str = ""  # why the run stopped early (credit limit), empty when it finished
    skipped: int = 0  # claims that were not time-sensitive or outside the pack categories
    credits: int = 0
    outdated: int = 0
    as_of_before: date | None = None
    as_of_mixed: bool = False


def check_claims(claims: list[Claim], verifier: Verifier, cache: Cache, *, skipped: int = 0) -> AnswerReport:
    pack, today = verifier.pack.id, verifier.today
    report = AnswerReport(pack=pack, checked_on=today, results=[], skipped=skipped)
    seen: dict[str, ClaimResult] = {}
    for claim in claims:
        if report.stopped:
            report.not_checked.append(claim)
            continue
        hit = seen.get(claim.key) or cache.get(claim.key, pack, today)
        if hit is not None:
            # Same claim already verified today: reuse it at no credit cost.
            result = hit.model_copy(update={"claim": claim, "credits": 0})
        else:
            try:
                result = verifier.verify(claim)
            except CreditLimitReached as e:
                report.stopped = str(e)
                report.not_checked.append(claim)
                continue
            except (GatewayError, TavilyHTTPError) as e:
                report.errors.append(ClaimError(claim=claim, error=str(e)))
                continue
            cache.put(claim.key, pack, today, result)
        seen[claim.key] = result
        report.results.append(result)
        report.credits += result.credits

    report.outdated = sum(r.verdict == "outdated" for r in report.results)
    est = as_of(report.results)
    if est is not None:
        report.as_of_before, report.as_of_mixed = est.before, est.mixed
    return report


def check_answer(answer: str, *, gateway: ChatClient, extractor_model: str, verifier: Verifier, cache: Cache,
                 question: str = "", fallbacks: list[str] | None = None, prompts: dict | None = None) -> AnswerReport:
    ex = extract_claims(gateway, extractor_model, verifier.pack, answer, question=question, fallbacks=fallbacks,
                        prompts=prompts)
    return check_claims(ex.claims, verifier, cache, skipped=len(ex.skipped))
