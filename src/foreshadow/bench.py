"""bench: per-surface latency/cost table + the budget sweep ($2/$4/$8).

Latency figures come from FakeQwen's deterministic simulation (labeled as
such — no fake "measurements"); costs are the SPEC.md section 5 unit prices
the ledger actually charges. The sweep runs the full pipeline nine times
(3 incidents x 3 budgets) in a throwaway home and reports what the Line
Producer bought — proving the economics move when the budget does.
"""

from __future__ import annotations

import statistics
import tempfile
from pathlib import Path

from . import config
from .pipeline.engine import create_context, run_pipeline
from .qwen.fake import simulated_latency_ms
from .seeds import SWEEP_BUDGETS
from .utils import read_json

LATENCY_SAMPLE_N = 20

_SURFACES = [
    ("screenplay", config.MODEL_SCREENPLAY, "chat_screenplay", f"${config.COST_SCREENPLAY:.2f}/call"),
    ("shot plan (structured)", config.MODEL_SHOTPLAN, "chat_shotplan", f"${config.COST_SHOTPLAN:.2f}/call"),
    ("alloc rationale", config.MODEL_ALLOC, "chat_alloc", f"${config.COST_ALLOC_RATIONALE:.2f}/call"),
    ("image (character/storyboard)", config.MODEL_IMAGE, "image",
     f"${config.COST_IMAGE:.3f}/img (batch -50%)"),
    ("hero render", config.MODEL_VIDEO_HERO, "video:" + config.MODEL_VIDEO_HERO,
     f"${config.COST_HERO_PER_S:.2f}/s"),
    ("connective render", config.MODEL_VIDEO_CONNECTIVE,
     "video:" + config.MODEL_VIDEO_CONNECTIVE, f"${config.COST_CONNECTIVE_PER_S:.2f}/s"),
    ("dailies QC", config.MODEL_QC, "qc", f"${config.COST_QC_PER_REVIEW:.2f}/review"),
    ("narration", config.MODEL_TTS, "tts", f"${config.COST_TTS_PER_10K_CHARS:.2f}/10k chars"),
]


def latency_samples(kind: str, n: int = LATENCY_SAMPLE_N) -> list[int]:
    return [simulated_latency_ms(kind, i) for i in range(1, n + 1)]


def p50_p95(samples: list[int]) -> tuple[float, int]:
    ordered = sorted(samples)
    p50 = statistics.median(ordered)
    p95 = ordered[round(0.95 * (len(ordered) - 1))]
    return p50, p95


def surface_table() -> list[dict]:
    rows = []
    for label, model, kind, unit_cost in _SURFACES:
        p50, p95 = p50_p95(latency_samples(kind))
        rows.append({"surface": label, "model": model, "p50_ms": int(p50),
                     "p95_ms": int(p95), "unit_cost": unit_cost})
    return rows


def run_sweep(home: Path | None = None) -> list[dict]:
    """3 incidents x $2/$4/$8, full pipeline each, fresh deterministic home."""
    rows = []
    with tempfile.TemporaryDirectory(prefix="foreshadow-bench-") as tmp:
        base = Path(home) if home else Path(tmp)
        for incident_id in config.INCIDENT_IDS:
            for budget in SWEEP_BUDGETS:
                run_home = base / f"{incident_id}-b{budget:g}"
                ctx = create_context(incident_id, budget, transport="fake",
                                     job_id=f"bench-{incident_id}-b{budget:g}",
                                     home=run_home)
                result = run_pipeline(ctx)
                alloc = read_json(ctx.job_dir / "allocation.json")
                qc = read_json(ctx.job_dir / "qc/summary.json")
                mix = {"hero": 0, "connective": 0, "kenburns": 0}
                for decision in alloc["decisions"]:
                    mix[decision["tier"]] += 1
                rows.append({
                    "incident": incident_id,
                    "budget_usd": budget,
                    "mix": mix,
                    "render_spend_usd": alloc["render_spend_usd"],
                    "spent_usd": result.spent_usd,
                    "quality_pct": round(100 * alloc["quality_score"] / alloc["quality_max"], 1),
                    "demotions": len(alloc["regret"]),
                    "qc_reviewed": qc["reviewed"],
                    "qc_rejected": len(qc["rejected_sha256"]),
                    "qc_retries": qc["retries"],
                })
    return rows


def bench_report() -> str:
    lines = [
        "## Foreshadow bench",
        "",
        "### Per-surface latency and unit cost",
        "",
        f"Latency = FakeQwen deterministic simulation (N={LATENCY_SAMPLE_N} per "
        "surface, seeded), labeled as such — offline builds do not fake live "
        "measurements. Unit costs are the ledger's SPEC prices.",
        "",
        "| surface | model | p50 (ms) | p95 (ms) | unit cost |",
        "|---|---|---:|---:|---|",
    ]
    for row in surface_table():
        lines.append(
            f"| {row['surface']} | `{row['model']}` | {row['p50_ms']} | "
            f"{row['p95_ms']} | {row['unit_cost']} |"
        )
    lines += [
        "",
        "### Budget sweep — what the Line Producer buys at $2 / $4 / $8",
        "",
        "| incident | budget | hero | connective | ken-burns | render $ | film total $ | quality | demotions | QC (rev/rej/retry) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in run_sweep():
        mix = row["mix"]
        lines.append(
            f"| {row['incident']} | ${row['budget_usd']:g} | {mix['hero']} | "
            f"{mix['connective']} | {mix['kenburns']} | "
            f"${row['render_spend_usd']:.2f} | ${row['spent_usd']:.2f} | "
            f"{row['quality_pct']}% | {row['demotions']} | "
            f"{row['qc_reviewed']}/{row['qc_rejected']}/{row['qc_retries']} |"
        )
    lines.append("")
    return "\n".join(lines)
