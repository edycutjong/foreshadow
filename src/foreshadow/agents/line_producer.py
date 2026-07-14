"""Line Producer — the scarcity allocator (SPEC.md section 6, COMPLEXITY.md section 3).

Deterministic core; the LLM only writes the producer's note. Algorithm:

1. Effective render budget  R = B - overhead_estimate - retry_reserve
   (overhead = every non-render call the film will make, priced conservatively;
   the reserve guarantees one QC re-render can never break invariant I2).
2. Desired tier per shot by narrative weight: >=7 hero, 4-6 connective,
   <=3 ken-burns still (never pay video rates for a weight-2 shot).
3. Greedy affordability pass in (weight desc, id) order with two caps:
   hero spend <= 0.6*R, hero+connective spend <= 0.9*R. A shot that cannot
   afford its desired tier demotes stepwise; every demotion is priced into
   the regret log ("saved $X, lost w*(q_from - q_to) quality-weight").
4. Upgrade pass: leftover budget promotes connective-band shots to hero
   (weight desc), same caps — extra dollars buy visible quality.

Everything is a pure function of (shots, budget) — replayable to the cent.
"""

from __future__ import annotations

from .. import config
from ..schemas import Allocation, BudgetDecision, RegretRow, Shot, Tier
from ..utils import usd

_TIER_ORDER: dict[str, int] = {"kenburns": 0, "connective": 1, "hero": 2}


def desired_tier(weight: int) -> Tier:
    if weight >= config.HERO_MIN_WEIGHT:
        return "hero"
    if weight >= config.CONNECTIVE_MIN_WEIGHT:
        return "connective"
    return "kenburns"


def tier_cost(tier: Tier, duration_s: int) -> float:
    if tier == "hero":
        return usd(duration_s * config.COST_HERO_PER_S)
    if tier == "connective":
        return usd(duration_s * config.COST_CONNECTIVE_PER_S)
    return usd(config.COST_KENBURNS)


def overhead_estimate(n_shots: int) -> float:
    """Conservative estimate of every non-render dollar the film will spend."""
    return usd(
        config.COST_SCREENPLAY
        + config.COST_SHOTPLAN
        + config.COST_ALLOC_RATIONALE
        + config.COST_IMAGE  # character sheet (full price)
        + n_shots * config.COST_IMAGE * config.BATCH_DISCOUNT  # storyboards (batch)
        + n_shots * config.COST_QC_PER_REVIEW
        + config.COST_NARRATION_ESTIMATE
    )


def retry_reserve(shots: list[Shot]) -> float:
    """Held back so one QC re-render (worst case: hero rate at the longest
    duration) plus its re-review can never push spend past the budget."""
    if not shots:
        return 0.0
    max_duration = max(s.duration_s for s in shots)
    return usd(max_duration * config.COST_HERO_PER_S + config.COST_QC_PER_REVIEW)


def quality(weight: int, tier: Tier) -> float:
    return weight * config.QUALITY_FACTOR[tier]


def allocate(shots: list[Shot], budget_usd: float, incident_id: str = "") -> Allocation:
    if budget_usd <= 0:
        raise ValueError("budget must be positive")
    overhead = overhead_estimate(len(shots))
    reserve = retry_reserve(shots)
    render_budget = usd(max(0.0, budget_usd - overhead - reserve))
    hero_cap = usd(render_budget * config.HERO_SPEND_FRACTION)
    total_cap = usd(render_budget * config.TOTAL_SPEND_FRACTION)

    order = sorted(shots, key=lambda s: (-s.narrative_weight, s.id))
    assigned: dict[str, Tier] = {}
    regret: list[RegretRow] = []
    spend = 0.0
    hero_spend = 0.0
    eps = 1e-9

    # -- pass 1: desired tier, demote when unaffordable -----------------------
    for shot in order:
        want = desired_tier(shot.narrative_weight)
        got: Tier = "kenburns"
        if want == "hero":
            cost = tier_cost("hero", shot.duration_s)
            if hero_spend + cost <= hero_cap + eps and spend + cost <= total_cap + eps:
                got = "hero"
            else:
                conn = tier_cost("connective", shot.duration_s)
                got = "connective" if spend + conn <= total_cap + eps else "kenburns"
        elif want == "connective":
            conn = tier_cost("connective", shot.duration_s)
            got = "connective" if spend + conn <= total_cap + eps else "kenburns"
        cost = tier_cost(got, shot.duration_s)
        spend = usd(spend + cost)
        if got == "hero":
            hero_spend = usd(hero_spend + cost)
        assigned[shot.id] = got
        if _TIER_ORDER[got] < _TIER_ORDER[want]:
            regret.append(
                RegretRow(
                    shot_id=shot.id,
                    from_tier=want,
                    to_tier=got,
                    saved_usd=usd(tier_cost(want, shot.duration_s) - cost),
                    lost_quality_weight=usd(quality(shot.narrative_weight, want) - quality(shot.narrative_weight, got)),
                )
            )

    # -- pass 2: leftover budget upgrades connective-band shots to hero -------
    for shot in order:
        if assigned[shot.id] != "connective":
            continue
        if desired_tier(shot.narrative_weight) != "connective":
            continue  # demoted heroes stay demoted: the caps already spoke
        hero_c = tier_cost("hero", shot.duration_s)
        conn_c = tier_cost("connective", shot.duration_s)
        new_spend = usd(spend - conn_c + hero_c)
        new_hero = usd(hero_spend + hero_c)
        if new_hero <= hero_cap + eps and new_spend <= total_cap + eps:
            assigned[shot.id] = "hero"
            spend, hero_spend = new_spend, new_hero

    decisions = []
    q_score = 0.0
    q_max = 0.0
    for shot in shots:  # plan order for readability
        want = desired_tier(shot.narrative_weight)
        got = assigned[shot.id]
        cost = tier_cost(got, shot.duration_s)
        q_score += quality(shot.narrative_weight, got)
        q_max += quality(shot.narrative_weight, "hero")
        if _TIER_ORDER[got] < _TIER_ORDER[want]:
            note = f"demoted {want}->{got}: budget cap"
        elif _TIER_ORDER[got] > _TIER_ORDER[want]:
            note = f"upgraded {want}->{got}: surplus budget buys quality"
        elif got == "kenburns":
            note = f"weight {shot.narrative_weight}/10 -> still (Ken Burns), saves ${tier_cost('connective', shot.duration_s):.2f} vs connective"
        else:
            note = f"weight {shot.narrative_weight}/10 earns the {got} tier"
        decisions.append(
            BudgetDecision(
                shot_id=shot.id,
                tier=got,
                desired_tier=want,
                est_cost_usd=cost,
                rationale=note,
            )
        )

    return Allocation(
        incident_id=incident_id,
        budget_usd=usd(budget_usd),
        overhead_est_usd=overhead,
        retry_reserve_usd=reserve,
        render_budget_usd=render_budget,
        decisions=decisions,
        regret=regret,
        render_spend_usd=usd(spend),
        quality_score=usd(q_score),
        quality_max=usd(q_max),
    )


class LineProducer:
    """Public toolkit facade: LineProducer(budget).allocate(shot_plan)."""

    def __init__(self, budget_usd: float) -> None:
        if budget_usd <= 0:
            raise ValueError("budget must be positive")
        self.budget_usd = float(budget_usd)

    def allocate(self, shots: list[Shot], incident_id: str = "") -> Allocation:
        return allocate(shots, self.budget_usd, incident_id=incident_id)
