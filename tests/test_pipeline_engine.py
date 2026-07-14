"""pipeline/engine.py branches not reached by the happy-path fixtures in
test_pipeline_stages.py / test_replay_determinism.py: the default (env-var)
home dir, passing a transport instance directly (the non-deterministic
"live-shaped" branch), run_pipeline's failure bookkeeping, and replay's
stale-job-dir cleanup."""

from __future__ import annotations

import pytest

from foreshadow.pipeline.engine import (
    JobResult,
    create_context,
    default_home,
    replay,
    run_pipeline,
)
from foreshadow.pipeline.stages import STAGES
from foreshadow.provenance import KillSwitchTripped
from foreshadow.qwen.fake import FakeQwen


def test_default_home_honors_foreshadow_home_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FORESHADOW_HOME", str(tmp_path / "custom-home"))
    assert default_home() == tmp_path / "custom-home"


class _CustomNamedTransport(FakeQwen):
    """FakeQwen's fixture-backed behavior under a non-'fake' name, to drive
    create_context's non-deterministic ("live-shaped") branch -- real key
    generation + the random ECIES envelope -- without any network or a
    DASHSCOPE_API_KEY."""

    name = "custom"


def test_object_transport_takes_non_deterministic_path(tmp_path, monkeypatch):
    # Force stage_stitch's ffmpeg-not-installed branch regardless of whether
    # the host actually has ffmpeg: the FakeQwen clip stubs aren't decodable
    # video, so real ffmpeg must never be invoked on them here.
    monkeypatch.setattr("foreshadow.pipeline.stages.ffmpeg_path", lambda: None)

    transport = _CustomNamedTransport()
    ctx = create_context("forklift", 4.0, transport, job_id="custom-transport", home=tmp_path)
    assert ctx.transport is transport  # non-str transport passed through as-is
    assert ctx.deterministic is False

    result = run_pipeline(ctx)
    assert result.status == "published"

    # live-mode key material was generated + persisted on disk
    assert (tmp_path / "keys" / "worker_x25519.key").exists()
    assert (tmp_path / "keys" / "project_signing.key").exists()

    # the incident was sealed with the random SealedBox envelope ("S"), not
    # the deterministic demo envelope ("D") used for replay/fake runs
    sealed = (ctx.job_dir / "incident.sealed").read_bytes()
    assert sealed[:1] == b"S"

    # stitch skipped the ffmpeg concat (no film for a non-fake transport
    # without ffmpeg) but the rest of the pipeline still published cleanly
    assert not (ctx.job_dir / "film.mp4").exists()


def test_run_pipeline_marks_killswitch_and_reraises(tmp_path, monkeypatch):
    ctx = create_context("forklift", 4.0, "fake", job_id="ks-stage", home=tmp_path)

    def _boom(_ctx):
        raise KillSwitchTripped("forced kill switch for test")

    monkeypatch.setattr("foreshadow.pipeline.engine.STAGES", [("boom", _boom)])
    with pytest.raises(KillSwitchTripped, match="forced kill switch"):
        run_pipeline(ctx)
    assert ctx.storage.get_job(ctx.job_id)["status"] == "killed"
    assert ctx.storage.stage_status(ctx.job_id, "boom") == "failed"


def test_run_pipeline_marks_failed_and_reraises_generic_exception(tmp_path, monkeypatch):
    ctx = create_context("forklift", 4.0, "fake", job_id="fail-stage", home=tmp_path)

    def _boom(_ctx):
        raise ValueError("forced generic failure for test")

    monkeypatch.setattr("foreshadow.pipeline.engine.STAGES", [("boom", _boom)])
    with pytest.raises(ValueError, match="forced generic failure"):
        run_pipeline(ctx)
    assert ctx.storage.get_job(ctx.job_id)["status"] == "failed"
    assert ctx.storage.stage_status(ctx.job_id, "boom") == "failed"


def test_run_pipeline_still_uses_real_stages_after_monkeypatch_test(tmp_path):
    """Sanity check that STAGES imported fresh in a new test is unaffected by
    monkeypatch.setattr in the tests above (monkeypatch auto-reverts)."""
    assert len(STAGES) == 11


def test_replay_twice_same_home_clears_stale_job_dir(tmp_path):
    first, matches1 = replay("forklift", 4.0, home=tmp_path)
    assert matches1 is True
    stale_marker = first.job_dir / "leftover_from_previous_attempt.txt"
    stale_marker.write_text("stale", encoding="utf-8")
    assert stale_marker.exists()

    second, matches2 = replay("forklift", 4.0, home=tmp_path)
    assert isinstance(second, JobResult)
    assert second.job_dir == first.job_dir
    assert not stale_marker.exists()  # rmtree cleared the pre-existing dir
    assert matches2 is True
