"""bench.py: per-surface latency/cost table + the $2/$4/$8 budget sweep."""

from __future__ import annotations

from foreshadow import config
from foreshadow.bench import (
    LATENCY_SAMPLE_N,
    bench_report,
    latency_samples,
    p50_p95,
    run_sweep,
    surface_table,
)


def test_p50_p95_on_known_series():
    assert p50_p95(list(range(1, 11))) == (5.5, 10)


def test_latency_samples_are_deterministic_and_sized():
    a = latency_samples("qc")
    b = latency_samples("qc")
    assert a == b and len(a) == LATENCY_SAMPLE_N


def test_surface_table_has_eight_verified_surfaces():
    rows = surface_table()
    assert len(rows) == 8
    for row in rows:
        assert row["model"] in config.ALLOWED_MODELS
        assert row["p50_ms"] > 0 and row["p95_ms"] >= row["p50_ms"]
        assert row["unit_cost"]


def test_run_sweep_covers_three_incidents_by_three_budgets():
    rows = run_sweep()
    assert len(rows) == 9
    pairs = {(r["incident"], r["budget_usd"]) for r in rows}
    assert pairs == {
        (inc, b) for inc in config.INCIDENT_IDS for b in (2.0, 4.0, 8.0)
    }


def test_run_sweep_rows_have_economics_fields():
    row = run_sweep()[0]
    for key in ("mix", "render_spend_usd", "spent_usd", "quality_pct",
                "demotions", "qc_reviewed", "qc_rejected", "qc_retries"):
        assert key in row


def test_sweep_spend_never_exceeds_budget():
    for row in run_sweep():
        assert row["spent_usd"] <= row["budget_usd"] + 1e-9


def test_bench_report_is_markdown_with_both_tables():
    report = bench_report()
    assert "### Per-surface latency and unit cost" in report
    assert "Budget sweep" in report
    assert "| p50 (ms) |" in report or "p50 (ms)" in report
    for inc in config.INCIDENT_IDS:
        assert f"| {inc} |" in report


def test_bench_report_names_every_surface_model():
    report = bench_report()
    for model in config.ALLOWED_MODELS:
        if model in (config.MODEL_SCREENPLAY_FALLBACK, config.MODEL_VIDEO_HERO_FALLBACK):
            continue  # fallbacks are not primary rows in the surface table
        assert model in report
