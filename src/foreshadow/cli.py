"""`foreshadow` CLI — plan / render / verify / bench / replay / seed."""

from __future__ import annotations

import re
from pathlib import Path

import typer

from . import config
from .pipeline.engine import create_context, run_pipeline
from .pipeline.engine import replay as engine_replay
from .provenance import verify_manifest
from .schemas import Manifest
from .utils import read_json

app = typer.Typer(
    name="foreshadow",
    help="Agent film studio: near-miss incident report -> provenance-signed safety film.",
    add_completion=False,
    pretty_exceptions_enable=False,
)


def _echo_stage(name: str, status: str, detail: dict | None) -> None:
    if status == "running":
        return
    suffix = ""
    if detail:
        parts = [f"{k}={v}" for k, v in sorted(detail.items())]
        suffix = "  (" + ", ".join(parts) + ")"
    typer.echo(f"  [{status:>6}] {name}{suffix}")


def _print_ledger(ctx) -> None:
    rows = ctx.ledger.rows()
    typer.echo("\n  cost ledger")
    typer.echo("  " + "-" * 74)
    for row in rows:
        if row["cost_usd"] > 0:
            typer.echo(f"  {row['item']:<26} ${row['cost_usd']:>7.4f}  {row['rationale'][:38]}")
    for row in rows:
        if row["item"].startswith("regret"):
            typer.echo(f"  {row['item']:<26} {'':>8}  {row['rationale'][:46]}")
    typer.echo("  " + "-" * 74)
    typer.echo(f"  {'TOTAL':<26} ${ctx.ledger.spent_usd:>7.4f}  (budget ${ctx.budget_usd:.2f})")


@app.command()
def plan(
    incident: str = typer.Option(..., help=f"one of {', '.join(config.INCIDENT_IDS)} (or use --file)"),
    budget: float = typer.Option(config.DEFAULT_BUDGET_USD, help="hard film budget in USD"),
    transport: str = typer.Option("fake", help="fake (offline) or live (DASHSCOPE_API_KEY)"),
    file: Path | None = typer.Option(None, help="custom incident report (text); needs --transport live (offline replays only the seeds)"),
    home: Path | None = typer.Option(None, help="runtime dir (default ./var)"),
) -> None:
    """Screenplay + shot plan + Line Producer allocation only (no renders)."""
    try:
        ctx = create_context(incident, budget, transport, home=home, incident_file=file)
    except Exception as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"planning job {ctx.job_id} (budget ${budget:.2f}, transport {transport})")
    try:
        run_pipeline(ctx, until="budget_alloc", on_stage=_echo_stage)
    except Exception as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    alloc = read_json(ctx.job_dir / "allocation.json")
    typer.echo("\n  shot plan + tiers")
    typer.echo("  " + "-" * 74)
    plan_data = read_json(ctx.job_dir / "shotplan.json")
    tiers = {d["shot_id"]: d for d in alloc["decisions"]}
    for shot in plan_data["shots"]:
        decision = tiers[shot["id"]]
        typer.echo(
            f"  {shot['id']:<4} w{shot['narrative_weight']:>2}/10 {shot['duration_s']}s "
            f"{decision['tier']:<10} ${decision['est_cost_usd']:.2f}  {shot['action'][:44]}"
        )
    typer.echo("  " + "-" * 74)
    typer.echo(
        f"  render budget ${alloc['render_budget_usd']:.2f} "
        f"(overhead est ${alloc['overhead_est_usd']:.2f}, "
        f"retry reserve ${alloc['retry_reserve_usd']:.2f}); "
        f"render spend ${alloc['render_spend_usd']:.2f}; "
        f"quality {100 * alloc['quality_score'] / alloc['quality_max']:.1f}%"
    )
    _print_ledger(ctx)


@app.command()
def render(
    incident: str = typer.Option(..., help=f"one of {', '.join(config.INCIDENT_IDS)} (or use --file)"),
    budget: float = typer.Option(config.DEFAULT_BUDGET_USD, help="hard film budget in USD"),
    transport: str = typer.Option("fake", help="fake (offline) or live (DASHSCOPE_API_KEY)"),
    job_id: str | None = typer.Option(None, help="resume/derive a specific job id"),
    file: Path | None = typer.Option(None, help="custom incident report (text); needs --transport live (offline replays only the seeds)"),
    home: Path | None = typer.Option(None, help="runtime dir (default ./var)"),
) -> None:
    """Full pipeline: ingest -> ... -> publish (signed manifest)."""
    try:
        ctx = create_context(incident, budget, transport, job_id=job_id,
                             home=home, incident_file=file)
    except Exception as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"rendering job {ctx.job_id} (budget ${budget:.2f}, transport {transport})")
    try:
        result = run_pipeline(ctx, on_stage=_echo_stage)
    except Exception as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    _print_ledger(ctx)
    typer.echo(f"\n  film      : {result.job_dir / 'film.mp4'}")
    typer.echo(f"  edit list : {result.job_dir / 'film.edit_list.txt'}")
    typer.echo(f"  manifest  : {result.manifest_path}")
    typer.echo(f"  merkle root {result.merkle_root}")
    typer.echo(f"  status: {result.status}  |  spent ${result.spent_usd:.4f} of ${budget:.2f}")


@app.command()
def verify(
    film: Path = typer.Argument(..., help="path to film.mp4 (or stub)"),
    manifest: Path = typer.Argument(..., help="path to manifest.json"),
    trusted_key: str | None = typer.Option(
        None, help="hex Ed25519 pubkey that MUST match the manifest signer"
    ),
) -> None:
    """Recompute every hash, rebuild the Merkle root, check the signature,
    and evaluate invariants I1-I4. Exit 0 = PASS, 1 = FAIL."""
    if not manifest.exists():
        typer.echo(f"error: manifest not found: {manifest}", err=True)
        raise typer.Exit(2)
    if not film.exists():
        typer.echo(f"error: film not found: {film}", err=True)
        raise typer.Exit(2)
    m = Manifest.load(manifest)
    report = verify_manifest(m, base_dir=manifest.parent, film_path=film,
                             trusted_pubkey_hex=trusted_key)
    typer.echo(f"manifest {manifest}")
    typer.echo(f"  job {m.job_id} | incident {m.incident_id} | "
               f"spent ${m.spent_usd:.4f} of ${m.budget_usd:.2f} | leaves {len(m.leaves)}")
    for check in report.checks:
        mark = "PASS" if check.passed else "FAIL"
        typer.echo(f"  [{mark}] {check.name:<24} {check.detail}")
    typer.echo("VERIFICATION " + ("PASS" if report.ok else "FAIL"))
    raise typer.Exit(0 if report.ok else 1)


@app.command()
def bench() -> None:
    """Latency/cost table + $2/$4/$8 budget sweep (markdown)."""
    from .bench import bench_report

    typer.echo(bench_report())


@app.command()
def replay(
    job_id: str | None = typer.Argument(
        None, help="replay job id, e.g. replay-forklift-b4 (or use --incident)"
    ),
    incident: str | None = typer.Option(None, help=f"one of {', '.join(config.INCIDENT_IDS)}"),
    budget: float = typer.Option(config.DEFAULT_BUDGET_USD, help="budget in USD"),
    home: Path | None = typer.Option(None, help="runtime dir (default ./var)"),
) -> None:
    """Zero-network deterministic rebuild of a demo film (FakeQwen, no keys),
    verified against its signed manifest and the committed fixture cache."""
    if job_id:
        match = re.fullmatch(r"replay-([a-z]+)-b([0-9.]+)", job_id)
        if not match:
            typer.echo(f"error: cannot parse job id {job_id!r} "
                       "(expected replay-<incident>-b<budget>)", err=True)
            raise typer.Exit(2)
        incident, budget = match.group(1), float(match.group(2))
    if not incident:
        typer.echo("error: pass a job id or --incident", err=True)
        raise typer.Exit(2)
    typer.echo(f"replaying {incident} at ${budget:g} (offline, FakeQwen, demo keys)")
    try:
        result, matches_cache = engine_replay(incident, budget, home=home,
                                              on_stage=_echo_stage)
    except Exception as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    manifest = Manifest.load(result.manifest_path)
    report = verify_manifest(manifest, base_dir=result.job_dir,
                             film_path=result.job_dir / "film.mp4")
    typer.echo(f"\n  spent ${result.spent_usd:.4f} of ${budget:.2f}")
    typer.echo(f"  merkle root {result.merkle_root}")
    typer.echo("  invariants I1-I4 " + ("PASS" if report.ok else "FAIL"))
    if matches_cache is None:
        typer.echo("  committed cache: no cache for this (incident, budget) pair")
    else:
        typer.echo(
            "  committed cache: "
            + ("byte-identical manifest (root + signature match)" if matches_cache
               else "MISMATCH vs fixtures/cache — determinism broken")
        )
    if not report.ok or matches_cache is False:
        raise typer.Exit(1)


@app.command()
def preview(
    incident: str = typer.Option(
        "forklift", help=f"one of {', '.join(config.INCIDENT_IDS)}"
    ),
    out: Path | None = typer.Option(
        None, help="output .mp4 path (default ./<incident>_animatic.mp4)"
    ),
) -> None:
    """Render a REAL, playable MP4 storyboard animatic from the committed cache.

    Not AI-generated footage — an offline animatic (title cards + narration +
    Ken-Burns) drawn from the deterministic shot plan, so a judge has something
    watchable. Needs the optional deps: pip install '.[preview]'."""
    from .render.animatic import PreviewDepsMissing, render_animatic

    if incident not in config.INCIDENT_IDS:
        typer.echo(f"error: unknown incident {incident!r} "
                   f"(one of {', '.join(config.INCIDENT_IDS)})", err=True)
        raise typer.Exit(2)
    cache_dir = config.fixtures_dir() / "cache" / incident
    if not (cache_dir / "shotplan.json").exists():
        typer.echo(f"error: no committed cache at {cache_dir} — run "
                   f"`foreshadow replay --incident {incident}` first", err=True)
        raise typer.Exit(2)
    out_path = out or Path.cwd() / f"{incident}_animatic.mp4"
    typer.echo(f"rendering animatic for {incident} -> {out_path} "
               "(offline storyboard, not wan-generated)")
    try:
        summary = render_animatic(cache_dir, out_path)
    except PreviewDepsMissing as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(3) from exc
    typer.echo(
        f"  done: {summary['seconds']}s · {summary['frames']} frames · "
        f"{summary['shots']} shots · ledger ${summary['spent_usd']:.4f}"
    )
    typer.echo(f"  open it: {out_path}")


@app.command()
def seed(
    regen: bool = typer.Option(False, help="rewrite seeds/ deterministically"),
    check: bool = typer.Option(False, help="verify seeds match a regen"),
) -> None:
    """Regenerate or check the committed seed incidents (byte-identical)."""
    from .seeds import main as seeds_main

    args = ["--regen"] if regen else ([] if check else ["--check"])
    raise typer.Exit(seeds_main(args or ["--check"]))


def main() -> None:  # console_scripts entry point  # pragma: no cover - boilerplate
    app()


if __name__ == "__main__":  # pragma: no cover - boilerplate
    main()
