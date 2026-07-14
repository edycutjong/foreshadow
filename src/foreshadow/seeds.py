"""Deterministic seed incidents (SEED_DATA.md) + ground truth.

Three OSHA-300-style synthetic narratives, each engineered to exercise a
different allocator/QC path:
  forklift — hero-heavy demo (weights 9/8/7 buy hero shots at $4)
  ladder   — budget-pressure case (flat weights; $2 forces still demotions)
  chemical — QC case (C4's action omits its PPE elements -> planted rejection)

`python seed.py --regen` rewrites seeds/ byte-identically; ground-truth JSON
is computed with the SAME allocator + QC rule the pipeline runs, so tests
assert pipeline behavior against it as a regression net.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config
from .agents.line_producer import allocate, desired_tier
from .qwen.fake import missing_safety_elements
from .render.orchestrator import render_prompt
from .schemas import Screenplay, ShotPlan
from .utils import read_json

SWEEP_BUDGETS = (2.0, 4.0, 8.0)

INCIDENT_TEXTS: dict[str, str] = {
    "forklift": """OSHA FORM 300 SUPPLEMENTARY NARRATIVE — NEAR-MISS REPORT
Establishment: Hollis Ridge Distribution Center, Building 2 (synthetic site)
Case number: NM-2026-0117 | Date of incident: Tuesday, 06:41 | Shift: first
Employee (pseudonym): D. Okafor, order picker, 14 months on site
Equipment involved: counterbalance forklift #FLT-09, operator R. Sandoval

Description of incident: Order picker exited the break room at the head of
aisle seven wearing personal earbuds in both ears, in violation of posted
floor policy. At the same time forklift #FLT-09 was reversing a 900 kg pallet
from the end-cap racking toward the blind corner at bay 7-C. The convex
mirror mounted above bay 7-C was fogged from the overnight temperature swing
and had not been wiped during the pre-shift walk. The picker stepped off the
marked pedestrian lane to cut the corner. The operator braked at
approximately 3 km/h of remaining speed; the load shifted against the
backrest. Forks came to rest approximately 10 cm from the picker's hip. No
contact, no injury, no property damage.

Contributing factors identified: (1) hearing occluded by earbuds; (2) fogged
convex mirror not inspected; (3) pedestrian left the marked lane at a known
blind corner. Prior similar events this quarter: two.

Corrective actions proposed: earbud prohibition enforcement at floor entry;
mirror wipe added to pre-shift checklist; repaint pedestrian lane through the
7-C corner with corner guard rail quote requested.
""",
    "ladder": """OSHA FORM 300 SUPPLEMENTARY NARRATIVE — INJURY REPORT
Establishment: Merrow & Sons Fabrication, Plant 1 loading dock (synthetic site)
Case number: LD-2026-0033 | Date of incident: Thursday, 14:05 | Shift: second
Employee (pseudonym): T. Brandt, maintenance electrician, 6 years on site
Equipment involved: 24 ft aluminum extension ladder, asset L-24-03

Description of incident: Electrician retrieved the extension ladder from the
yard truck to service a junction box above the loading door. The floor inside
the loading door had been mopped approximately four minutes earlier and was
still wet; no footing mat was placed and the wet-floor sign was behind the
door leaf. The ladder was set at an angle visibly steeper than the four-to-one
rule to clear a pallet staged below the box. Twelve feet up, the employee
leaned laterally past the right rail (overreach) to reach the junction box
rather than descending to reposition. The ladder feet lost traction on the
wet concrete and slid outward; the employee rode the ladder down and landed
on the staged pallet. Injury: contusion to left forearm and hip, one day of
restricted duty. Property damage: bent ladder rail, asset L-24-03 tagged out.

Contributing factors identified: (1) wet floor, no mat, sign not visible;
(2) set-up angle far steeper than four to one; (3) overreach past the rail;
(4) no tie off point used despite anchor eye present above the door.

Corrective actions proposed: ladder set-up checklist on the asset tag
(angle, footing, tie off, three points of contact); mop schedule moved off
shift; staged pallets excluded from the door zone.
""",
    "chemical": """OSHA FORM 300 SUPPLEMENTARY NARRATIVE — INJURY REPORT
Establishment: Corvid Analytical Services, receiving area (synthetic site)
Case number: CH-2026-0059 | Date of incident: Monday, 08:24 | Shift: first
Employee (pseudonym): P. Nair, laboratory technician, 2 years on site
Substance involved: solvent degreaser (petroleum distillate blend)

Description of incident: During intake in the receiving area, a technician
began transferring an unlabeled secondary container of degreaser that had
been decanted by the previous shift and never marked. The technician handled
the container without chemical-resistant gloves and without a face shield,
with sleeves rolled up. The container cap had been reseated but not torqued;
as the container was lifted to the bench scale the cap released and an
estimated 150 ml of solvent splashed across the technician's right forearm
and cheek. The employee was walked to the eyewash station and flushed for a
full fifteen minutes while a coworker retrieved the safety data sheet. The
spill kit mounted by the receiving door was used to absorb residue. Injury:
minor chemical irritation, no lost time. Property damage: none.

Contributing factors identified: (1) secondary container not labeled as
required; (2) PPE (gloves, face shield) not worn for an open-container
transfer; (3) cap not verified before lifting.

Corrective actions proposed: label-at-decant rule with pre-printed blanks at
every bench; glove and face-shield station moved to the receiving door;
cap-torque check added to the transfer procedure.
""",
}


def _fixture(incident_id: str, name: str) -> dict:
    return read_json(config.fixtures_dir() / "qwen" / incident_id / f"{name}.json")


def planted_qc_rejections(incident_id: str, budget_usd: float = 4.0) -> list[str]:
    """Shots whose attempt-1 render prompt misses a safety element AND which
    receive a video tier at the given budget — exactly the clips the FakeQwen
    critic (and, live, qwen3-vl-plus) rejects on first review."""
    plan = ShotPlan.model_validate(_fixture(incident_id, "shotplan"))
    alloc = allocate(plan.shots, budget_usd, incident_id=incident_id)
    tiers = {d.shot_id: d.tier for d in alloc.decisions}
    rejected = []
    for shot in plan.shots:
        if tiers[shot.id] == "kenburns":
            continue
        if missing_safety_elements(shot.model_dump(), render_prompt(shot)):
            rejected.append(shot.id)
    return rejected


def ground_truth(incident_id: str) -> dict:
    screenplay = Screenplay.model_validate(_fixture(incident_id, "screenplay"))
    plan = ShotPlan.model_validate(_fixture(incident_id, "shotplan"))
    sweep = {}
    for budget in SWEEP_BUDGETS:
        alloc = allocate(plan.shots, budget, incident_id=incident_id)
        mix = {"hero": 0, "connective": 0, "kenburns": 0}
        for decision in alloc.decisions:
            mix[decision.tier] += 1
        sweep[f"{budget:g}"] = {
            "tier_mix": mix,
            "render_spend_usd": alloc.render_spend_usd,
            "demotions": len(alloc.regret),
            "quality_pct": round(100 * alloc.quality_score / alloc.quality_max, 1),
        }
    return {
        "incident_id": incident_id,
        "expected_beats": len(screenplay.beats),
        "expected_shots": len(plan.shots),
        "desired_tiers": {s.id: desired_tier(s.narrative_weight) for s in plan.shots},
        "budgets": sweep,
        "planted_qc_rejections_at_4": planted_qc_rejections(incident_id, 4.0),
    }


def render_seed_files() -> dict[str, bytes]:
    """All seed files as bytes — the single source of byte-identical --regen."""
    files: dict[str, bytes] = {}
    for incident_id in config.INCIDENT_IDS:
        files[f"{incident_id}.txt"] = INCIDENT_TEXTS[incident_id].encode("utf-8")
        files[f"{incident_id}.json"] = (
            json.dumps(ground_truth(incident_id), indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
    return files


def write_seeds(dest: Path | None = None) -> list[Path]:
    dest = Path(dest) if dest else config.seeds_dir()
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    for name, data in render_seed_files().items():
        path = dest / name
        path.write_bytes(data)
        written.append(path)
    return written


def check_seeds(dest: Path | None = None) -> list[str]:
    """Names of seed files that differ from a deterministic regen (empty = ok)."""
    dest = Path(dest) if dest else config.seeds_dir()
    stale = []
    for name, data in render_seed_files().items():
        path = dest / name
        if not path.exists() or path.read_bytes() != data:
            stale.append(name)
    return stale


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Foreshadow seed generator")
    parser.add_argument("--regen", action="store_true",
                        help="rewrite seeds/ (byte-identical for identical code)")
    parser.add_argument("--check", action="store_true",
                        help="verify committed seeds match a regen")
    parser.add_argument("--dest", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.regen:
        for path in write_seeds(args.dest):
            print(f"wrote {path}")
        return 0
    stale = check_seeds(args.dest)
    if stale:
        print(f"STALE seeds (regen with --regen): {', '.join(stale)}")
        return 1
    print("seeds match deterministic regen (byte-identical)")
    return 0
