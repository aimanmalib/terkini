"""The Malaysia pack, its questions and its answer key stay consistent (H1, D9). No network."""

from __future__ import annotations

import re

import pytest

from terkini.budget import load_budget
from terkini.packs import load_key, load_pack, load_questions

MIN_KEYED_QUESTIONS = 20  # PRD H1


@pytest.fixture(scope="module")
def pack():
    return load_pack("my")


def test_pack_has_official_domains_and_volatile_categories(pack):
    assert pack.domain_names
    assert len(pack.domain_names) == len(set(pack.domain_names))
    assert any(c.volatile for c in pack.categories)


def test_every_question_has_exactly_one_key(pack):
    questions = load_questions(pack)
    key = load_key(pack)
    q_ids = [q.id for q in questions]
    k_ids = [k.id for k in key.keys]
    assert len(q_ids) == len(set(q_ids))
    assert sorted(q_ids) == sorted(k_ids)
    assert len(k_ids) >= MIN_KEYED_QUESTIONS


def test_questions_use_pack_categories(pack):
    for q in load_questions(pack):
        assert pack.category(q.category) is not None, q.id


def test_every_key_points_to_an_official_page(pack):
    for k in load_key(pack).keys:
        assert pack.domain_for(k.url) is not None, (k.id, k.url)


def test_effective_dates_are_iso_and_stated_in_the_quote(pack):
    for k in load_key(pack).keys:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", k.read_at), k.id
        if k.effective_date:
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", k.effective_date), k.id
            assert k.effective_date[:4] in k.quote, k.id


def test_dropped_questions_carry_a_reason(pack):
    for d in load_key(pack).dropped:
        assert d.topic and d.reason


def test_domain_match_needs_a_label_boundary(pack):
    assert pack.domain_for("https://mysst.customs.gov.my/faq") is not None
    assert pack.domain_for("https://notcustoms.gov.my/faq") is None
    assert pack.domain_for("https://customs.gov.my.example.com/") is None


def test_budget_fits_the_month():
    b = load_budget()
    assert b.limits.per_run <= b.limits.per_day
    assert b.allocation.build + b.allocation.eval_my + b.allocation.reserve <= b.monthly_credits
