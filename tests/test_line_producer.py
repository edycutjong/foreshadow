"""Line Producer knapsack allocator: tiers, caps, regret pricing, economics."""

from __future__ import annotations

import pytest
from support import make_shot

from foreshadow import config
from foreshadow.agents.line_producer import (
    LineProducer,
    allocate,
    desired_tier,
    overhead_estimate,
    quality,
    retry_reserve,
    tier_cost,
)
from foreshadow.schemas import ShotPlan
from foreshadow.utils import read_json, usd

FORKLIFT_PLAN = ShotPlan.model_validate(
    read_json(config.fixtures_dir() / "qwen" / "forklift" / "shotplan.json")
)


# -- desired_tier -----------------------------------------------------------
@pytest.mark.parametrize(
    "w,tier",
    [(1, "kenburns"), (3, "kenburns"), (4, "connective"), (6, "connective"),
     (7, "hero"), (9, "hero"), (10, "hero")],
)
def test_desired_tier_thresholds(w, tier):
    assert desired_tier(w) == tier


# -- tier_cost --------------------------------------------------------------
def test_tier_cost_hero():
    assert tier_cost("hero", 5) == usd(5 * config.COST_HERO_PER_S) == 0.5


def test_tier_cost_connective():
    assert tier_cost("connective", 4) == 0.2


def test_tier_cost_kenburns_is_free():
    assert tier_cost("kenburns", 9) == 0.0


# -- overhead / reserve / quality -------------------------------------------
def test_overhead_estimate_exact_for_eight_shots():
    assert overhead_estimate(8) == usd(0.645)


def test_overhead_increases_with_shots():
    assert overhead_estimate(10) > overhead_estimate(4)


def test_retry_reserve_uses_longest_hero_render_plus_review():
    shots = [make_shot(id="S1", duration_s=3), make_shot(id="S2", duration_s=5)]
    assert retry_reserve(shots) == usd(5 * config.COST_HERO_PER_S + config.COST_QC_PER_REVIEW)


def test_retry_reserve_empty_is_zero():
    assert retry_reserve([]) == 0.0


def test_quality_uses_factor_ladder():
    assert quality(9, "hero") == 9.0
    assert quality(10, "connective") == 6.0
    assert quality(5, "kenburns") == 1.5


# -- allocate: guards -------------------------------------------------------
@pytest.mark.parametrize("bad", [0, -1, -4.0])
def test_allocate_rejects_nonpositive_budget(bad):
    with pytest.raises(ValueError, match="budget must be positive"):
        allocate([make_shot()], bad)


def test_line_producer_rejects_nonpositive_budget():
    with pytest.raises(ValueError):
        LineProducer(0)


def test_line_producer_facade_matches_function():
    shots = FORKLIFT_PLAN.shots
    a = LineProducer(4.0).allocate(shots, incident_id="forklift")
    b = allocate(shots, 4.0, incident_id="forklift")
    assert a.model_dump() == b.model_dump()


# -- allocate: structural invariants (hold for ANY allocation) --------------
def _all_budgets_allocations():
    for budget in (1.0, 2.0, 4.0, 8.0, 16.0):
        yield budget, allocate(FORKLIFT_PLAN.shots, budget, incident_id="forklift")


def test_render_spend_equals_sum_of_decision_costs():
    for _, alloc in _all_budgets_allocations():
        total = usd(sum(d.est_cost_usd for d in alloc.decisions))
        assert total == alloc.render_spend_usd


def test_render_spend_never_exceeds_render_budget():
    for _, alloc in _all_budgets_allocations():
        assert alloc.render_spend_usd <= alloc.render_budget_usd + 1e-9


def test_hero_spend_respects_hero_cap():
    for _, alloc in _all_budgets_allocations():
        hero_cap = usd(alloc.render_budget_usd * config.HERO_SPEND_FRACTION)
        hero_spend = usd(sum(d.est_cost_usd for d in alloc.decisions if d.tier == "hero"))
        assert hero_spend <= hero_cap + 1e-9


def test_total_spend_respects_total_cap():
    for _, alloc in _all_budgets_allocations():
        total_cap = usd(alloc.render_budget_usd * config.TOTAL_SPEND_FRACTION)
        assert alloc.render_spend_usd <= total_cap + 1e-9


def test_decision_cost_matches_tier_cost():
    by_id = {s.id: s for s in FORKLIFT_PLAN.shots}
    for _, alloc in _all_budgets_allocations():
        for d in alloc.decisions:
            assert d.est_cost_usd == tier_cost(d.tier, by_id[d.shot_id].duration_s)


def test_quality_score_and_max_consistent():
    by_id = {s.id: s for s in FORKLIFT_PLAN.shots}
    for _, alloc in _all_budgets_allocations():
        q = usd(sum(quality(by_id[d.shot_id].narrative_weight, d.tier) for d in alloc.decisions))
        qmax = usd(sum(s.narrative_weight for s in FORKLIFT_PLAN.shots))
        assert alloc.quality_score == q
        assert alloc.quality_max == qmax
        assert alloc.quality_score <= alloc.quality_max + 1e-9


def test_one_decision_per_shot_preserving_plan_order():
    for _, alloc in _all_budgets_allocations():
        assert [d.shot_id for d in alloc.decisions] == [s.id for s in FORKLIFT_PLAN.shots]


# -- allocate: regret log is priced correctly -------------------------------
def _order(tier):
    return {"kenburns": 0, "connective": 1, "hero": 2}[tier]


def test_regret_rows_match_demoted_decisions():
    for _, alloc in _all_budgets_allocations():
        demoted = [d for d in alloc.decisions if d.demoted]
        assert len(alloc.regret) == len(demoted)


def test_regret_pricing_is_exact():
    # Force heavy demotion: many long hero-weight shots on a lean budget.
    shots = [make_shot(id=f"S{i}", duration_s=10, narrative_weight=10) for i in range(1, 9)]
    alloc = allocate(shots, 2.0)
    by_id = {s.id: s for s in shots}
    assert alloc.regret, "expected budget pressure to force demotions"
    for row in alloc.regret:
        dur = by_id[row.shot_id].duration_s
        w = by_id[row.shot_id].narrative_weight
        assert _order(row.to_tier) < _order(row.from_tier)
        assert row.saved_usd == usd(tier_cost(row.from_tier, dur) - tier_cost(row.to_tier, dur))
        assert row.lost_quality_weight == usd(
            quality(w, row.from_tier) - quality(w, row.to_tier)
        )


# -- economics move with the budget -----------------------------------------
def test_quality_is_monotonic_in_budget():
    scores = [alloc.quality_score for _, alloc in _all_budgets_allocations()]
    assert scores == sorted(scores)


def test_more_budget_buys_at_least_as_many_heroes():
    lo = allocate(FORKLIFT_PLAN.shots, 2.0)
    hi = allocate(FORKLIFT_PLAN.shots, 16.0)
    def heroes(a):
        return sum(1 for d in a.decisions if d.tier == "hero")

    assert heroes(hi) >= heroes(lo)


def test_upgrade_pass_promotes_connective_band_at_surplus():
    # A single weight-5 (connective-desired) shot; a fat budget should let the
    # upgrade pass promote it to hero.
    shots = [make_shot(id="S1", duration_s=4, narrative_weight=5)]
    lean = allocate(shots, 1.0)
    rich = allocate(shots, 50.0)
    assert lean.decisions[0].tier in ("kenburns", "connective")
    assert rich.decisions[0].tier == "hero"


# -- known-good regression vs committed cache -------------------------------
def test_forklift_allocation_matches_committed_cache():
    alloc = allocate(FORKLIFT_PLAN.shots, 4.0, incident_id="forklift")
    cached = read_json(config.fixtures_dir() / "cache" / "forklift" / "allocation.json")
    got = {d.shot_id: d.tier for d in alloc.decisions}
    want = {d["shot_id"]: d["tier"] for d in cached["decisions"]}
    assert got == want
    assert alloc.render_spend_usd == cached["render_spend_usd"]
    assert alloc.quality_score == cached["quality_score"]
    assert alloc.quality_max == cached["quality_max"]
