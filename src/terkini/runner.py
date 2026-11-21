"""Wire the checker to its clients: live (your own keys, through Bifrost and Tavily) or replay (a recorded run)."""

from __future__ import annotations

import tomllib
from contextlib import closing
from datetime import date
from pathlib import Path

from terkini.budget import load_budget
from terkini.cache import Cache
from terkini.checker import AnswerReport, check_answer
from terkini.credits import CreditGuard
from terkini.extractor import load_prompts
from terkini.gateway import load_gateway_config
from terkini.packs import REPO_ROOT, load_pack
from terkini.replay import Cassette, ReplayGateway, ReplayTavily
from terkini.score import load_score_config
from terkini.verify import Verifier, load_verify_config


def runs_dir(root: Path = REPO_ROOT) -> Path:
    """Folder of recorded runs, from config/verify.toml [replay] runs_dir."""
    with open(root / "config" / "verify.toml", "rb") as f:
        return root / tomllib.load(f)["replay"]["runs_dir"]


def run_check(answer: str, *, pack_id: str, tavily, gateway, cache: Cache, today: date, question: str = "",
              root: Path = REPO_ROOT, guard: CreditGuard | None = None) -> AnswerReport:
    pack = load_pack(pack_id, root)
    models = load_gateway_config(root).models
    prompts = load_prompts(root)
    verifier = Verifier(tavily, gateway, pack, guard or CreditGuard(load_budget(root), cache, today), cfg=load_verify_config(root),
                        score_cfg=load_score_config(root), judge_model=models.judge, today=today,
                        fallbacks=models.fallbacks, prompts=prompts)
    return check_answer(answer, gateway=gateway, extractor_model=models.extractor, verifier=verifier, cache=cache,
                        question=question, fallbacks=models.fallbacks, prompts=prompts)


def replay(c: Cassette, root: Path = REPO_ROOT) -> AnswerReport:
    """Run the real checker against a recording: no key, no network, a fresh in-memory cache."""
    with closing(Cache(":memory:")) as cache:
        return run_check(c.answer, pack_id=c.pack, tavily=ReplayTavily(c), gateway=ReplayGateway(c.chats),
                         cache=cache, today=c.checked_on, question=c.question, root=root)
