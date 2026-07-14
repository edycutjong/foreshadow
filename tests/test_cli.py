"""`foreshadow` CLI — the judge-facing commands, via Typer's CliRunner."""

from __future__ import annotations

from support import copy_cache
from typer.testing import CliRunner

from foreshadow import config
from foreshadow.cli import app
from foreshadow.schemas import Manifest

runner = CliRunner()


def test_replay_forklift_exits_zero_and_matches_cache(tmp_path):
    result = runner.invoke(app, ["replay", "--incident", "forklift",
                                 "--budget", "4", "--home", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "PASS" in result.output
    assert "byte-identical" in result.output


def test_replay_by_job_id(tmp_path):
    result = runner.invoke(app, ["replay", "replay-ladder-b2", "--home", str(tmp_path)])
    assert result.exit_code == 0, result.output


def test_replay_bad_job_id_exits_two():
    result = runner.invoke(app, ["replay", "not-a-valid-id"])
    assert result.exit_code == 2


def test_verify_cached_film_passes():
    d = config.fixtures_dir() / "cache" / "forklift"
    result = runner.invoke(app, ["verify", str(d / "film.mp4"), str(d / "manifest.json")])
    assert result.exit_code == 0, result.output
    assert "VERIFICATION PASS" in result.output


def test_verify_tampered_film_fails(tmp_path):
    d = copy_cache("forklift", tmp_path)
    sheet = d / "character_sheet.png"
    raw = bytearray(sheet.read_bytes())
    raw[-1] ^= 0x01
    sheet.write_bytes(bytes(raw))
    result = runner.invoke(app, ["verify", str(d / "film.mp4"), str(d / "manifest.json")])
    assert result.exit_code == 1
    assert "VERIFICATION FAIL" in result.output


def test_verify_with_matching_trusted_key(tmp_path):
    d = config.fixtures_dir() / "cache" / "forklift"
    signer = Manifest.load(d / "manifest.json").signer_pubkey
    result = runner.invoke(app, ["verify", str(d / "film.mp4"), str(d / "manifest.json"),
                                 "--trusted-key", signer])
    assert result.exit_code == 0, result.output


def test_verify_with_wrong_trusted_key_fails(tmp_path):
    d = config.fixtures_dir() / "cache" / "forklift"
    result = runner.invoke(app, ["verify", str(d / "film.mp4"), str(d / "manifest.json"),
                                 "--trusted-key", "0" * 64])
    assert result.exit_code == 1


def test_verify_missing_manifest_exits_two(tmp_path):
    result = runner.invoke(app, ["verify", str(tmp_path / "film.mp4"),
                                 str(tmp_path / "missing.json")])
    assert result.exit_code == 2


def test_plan_prints_tiers_and_budget(tmp_path):
    result = runner.invoke(app, ["plan", "--incident", "forklift",
                                 "--budget", "4", "--home", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "shot plan + tiers" in result.output
    assert "render budget" in result.output
    assert "TOTAL" in result.output


def test_render_full_pipeline(tmp_path):
    result = runner.invoke(app, ["render", "--incident", "forklift",
                                 "--budget", "4", "--home", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "merkle root" in result.output
    assert "published" in result.output


def test_plan_below_min_budget_exits_two(tmp_path):
    result = runner.invoke(app, ["plan", "--incident", "forklift",
                                 "--budget", "0.5", "--home", str(tmp_path)])
    assert result.exit_code == 2


def test_render_custom_incident_offline_fails_cleanly(tmp_path):
    """A judge who supplies their own report on the offline transport must get a
    clean, actionable error (exit 2) — not a stack trace. The message points at
    --transport live rather than crashing on a missing FakeQwen fixture."""
    report = tmp_path / "my_incident.txt"
    report.write_text("A worker reached over an unguarded mezzanine edge.", encoding="utf-8")
    result = runner.invoke(app, ["render", "--incident", "custom", "--file",
                                 str(report), "--budget", "4", "--home", str(tmp_path)])
    assert result.exit_code == 2, result.output
    assert "Traceback" not in result.output
    assert "--transport live" in result.output


def test_plan_custom_incident_offline_fails_cleanly(tmp_path):
    """Same clean-failure contract for `plan` (covers its pipeline error guard)."""
    report = tmp_path / "my_incident.txt"
    report.write_text("A worker reached over an unguarded mezzanine edge.", encoding="utf-8")
    result = runner.invoke(app, ["plan", "--incident", "custom", "--file",
                                 str(report), "--budget", "4", "--home", str(tmp_path)])
    assert result.exit_code == 2, result.output
    assert "Traceback" not in result.output
    assert "--transport live" in result.output


def test_seed_check_exits_zero():
    result = runner.invoke(app, ["seed", "--check"])
    assert result.exit_code == 0
    assert "byte-identical" in result.output


def test_bench_emits_markdown_tables():
    result = runner.invoke(app, ["bench"])
    assert result.exit_code == 0
    assert "Budget sweep" in result.output


def test_help_lists_all_commands():
    result = runner.invoke(app, ["--help"])
    for cmd in ("plan", "render", "verify", "bench", "replay", "seed"):
        assert cmd in result.output


def test_plan_ladder_prints_regret_rows(tmp_path):
    """At $2 the ladder incident forces demotions -> the ledger carries
    regret:<shot_id> rows, which _print_ledger renders in its own loop."""
    result = runner.invoke(app, ["plan", "--incident", "ladder",
                                 "--budget", "2", "--home", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "regret:" in result.output


def test_render_below_min_budget_exits_two(tmp_path):
    result = runner.invoke(app, ["render", "--incident", "forklift",
                                 "--budget", "0.5", "--home", str(tmp_path)])
    assert result.exit_code == 2
    assert "error:" in result.output


def test_verify_missing_film_exits_two(tmp_path):
    d = config.fixtures_dir() / "cache" / "forklift"
    result = runner.invoke(app, ["verify", str(tmp_path / "missing_film.mp4"),
                                 str(d / "manifest.json")])
    assert result.exit_code == 2
    assert "film not found" in result.output


def test_replay_no_job_id_or_incident_exits_two():
    result = runner.invoke(app, ["replay"])
    assert result.exit_code == 2
    assert "pass a job id or --incident" in result.output


def test_replay_unknown_incident_exits_two(tmp_path):
    result = runner.invoke(app, ["replay", "--incident", "not-a-real-incident",
                                 "--home", str(tmp_path)])
    assert result.exit_code == 2
    assert "error:" in result.output


def test_replay_different_budget_reports_no_cache(tmp_path):
    """The committed cache is keyed by incident only for a single (incident,
    budget) pair; a budget that doesn't match it can't be compared."""
    result = runner.invoke(app, ["replay", "--incident", "forklift",
                                 "--budget", "7", "--home", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "no cache for this (incident, budget) pair" in result.output


def test_replay_reports_cache_mismatch_and_exits_one(tmp_path, monkeypatch):
    """Drives the CLI's mismatch-handling branch (matches_cache is False)
    without fabricating pipeline internals: run a real replay, then hand the
    CLI that same real result back with the cache-comparison flag flipped,
    exactly like a genuine drift would look from the CLI's point of view."""
    from foreshadow.pipeline import engine as engine_mod

    real_replay = engine_mod.replay

    def _flip_to_mismatch(incident_id, budget_usd, home=None, on_stage=None):
        result, _ = real_replay(incident_id, budget_usd, home=home, on_stage=on_stage)
        return result, False

    monkeypatch.setattr("foreshadow.cli.engine_replay", _flip_to_mismatch)
    result = runner.invoke(app, ["replay", "--incident", "forklift",
                                 "--budget", "4", "--home", str(tmp_path)])
    assert result.exit_code == 1
    assert "MISMATCH vs fixtures/cache" in result.output
