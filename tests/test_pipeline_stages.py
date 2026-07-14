"""End-to-end pipeline: all stages, provenance, QC loop, resume/idempotency."""

from __future__ import annotations

import pytest

from foreshadow import config
from foreshadow.crypto.sealing import unseal
from foreshadow.pipeline.engine import MIN_BUDGET_USD, create_context, run_pipeline
from foreshadow.pipeline.stages import STAGE_ORDER
from foreshadow.provenance import verify_manifest
from foreshadow.schemas import Allocation, Manifest
from foreshadow.utils import read_json


def _manifest(ctx):
    return Manifest.load(ctx.job_dir / "manifest.json")


def _sha_to_path(manifest):
    return {leaf.sha256: leaf.path for leaf in manifest.leaves}


# ===========================================================================
# forklift — the flagship happy path at $4
# ===========================================================================
def test_forklift_reaches_published(forklift_run):
    _, result = forklift_run
    assert result.status == "published"
    assert result.merkle_root and len(result.merkle_root) == 64


def test_forklift_all_stages_done(forklift_run):
    ctx, _ = forklift_run
    statuses = {s["name"]: s["status"] for s in ctx.storage.stages_for_job(ctx.job_id)}
    assert set(statuses) == set(STAGE_ORDER)
    assert all(v in ("done", "skipped") for v in statuses.values())


def test_forklift_manifest_verifies_all_invariants(forklift_run):
    ctx, _ = forklift_run
    manifest = _manifest(ctx)
    report = verify_manifest(manifest, base_dir=ctx.job_dir, film_path=ctx.job_dir / "film.mp4")
    assert report.ok, [c.name for c in report.checks if not c.passed]


def test_forklift_spend_within_budget(forklift_run):
    ctx, result = forklift_run
    assert result.spent_usd <= ctx.budget_usd + 1e-9


def test_forklift_leaf_costs_reconcile_with_ledger(forklift_run):
    ctx, result = forklift_run
    manifest = _manifest(ctx)
    from foreshadow.utils import usd
    leaf_total = usd(sum(leaf.cost_usd for leaf in manifest.leaves))
    assert leaf_total == result.spent_usd


def test_forklift_edit_list_nonempty_and_traceable(forklift_run):
    ctx, _ = forklift_run
    manifest = _manifest(ctx)
    assert len(manifest.edit_list) >= 3  # title card + shots + rule card
    assert verify_manifest(manifest).get("I1_traceable_edit_list").passed


def test_forklift_no_rejected_clips_in_cut(forklift_run):
    ctx, _ = forklift_run
    manifest = _manifest(ctx)
    assert set(manifest.edit_list).isdisjoint(set(manifest.qc_rejected))


def test_ingest_seals_incident_and_unseals_to_seed_text(forklift_run):
    ctx, _ = forklift_run
    sealed = (ctx.job_dir / "incident.sealed").read_bytes()
    assert sealed[:1] == b"D"  # deterministic envelope header
    plaintext = unseal(sealed, ctx.worker_key).decode("utf-8")
    seed = (config.seeds_dir() / "forklift.txt").read_text(encoding="utf-8")
    assert plaintext == seed


# ===========================================================================
# chemical — the planted QC rejection + bounded retry
# ===========================================================================
def test_chemical_has_one_rejected_clip(chemical_run):
    ctx, _ = chemical_run
    manifest = _manifest(ctx)
    assert len(manifest.qc_rejected) == 1


def test_chemical_rejected_clip_is_attempt1_of_c4(chemical_run):
    ctx, _ = chemical_run
    manifest = _manifest(ctx)
    sha_to_path = _sha_to_path(manifest)
    rejected_paths = [sha_to_path[s] for s in manifest.qc_rejected]
    assert rejected_paths == ["clips/C4_attempt1.mp4"]


def test_chemical_final_c4_is_the_passing_retry(chemical_run):
    ctx, _ = chemical_run
    manifest = _manifest(ctx)
    sha_to_path = _sha_to_path(manifest)
    edit_paths = [sha_to_path[s] for s in manifest.edit_list]
    assert "clips/C4_attempt2.mp4" in edit_paths
    assert "clips/C4_attempt1.mp4" not in edit_paths


def test_chemical_qc_summary_records_retry(chemical_run):
    ctx, _ = chemical_run
    summary = read_json(ctx.job_dir / "qc" / "summary.json")
    assert summary["retries"] >= 1
    assert len(summary["rejected_sha256"]) == 1


def test_chemical_manifest_verifies(chemical_run):
    ctx, _ = chemical_run
    report = verify_manifest(_manifest(ctx), base_dir=ctx.job_dir,
                             film_path=ctx.job_dir / "film.mp4")
    assert report.ok


# ===========================================================================
# ladder — budget pressure at $2 forces demotions
# ===========================================================================
def test_ladder_has_kenburns_demotions(ladder_run):
    ctx, _ = ladder_run
    manifest = _manifest(ctx)
    kb = [leaf for leaf in manifest.leaves if leaf.kind == "clip_kenburns"]
    assert len(kb) >= 1


def test_ladder_regret_matches_demoted_decisions(ladder_run):
    ctx, _ = ladder_run
    alloc = Allocation.model_validate(read_json(ctx.job_dir / "allocation.json"))
    demoted = [d for d in alloc.decisions if d.demoted]
    assert len(alloc.regret) == len(demoted)


def test_ladder_spend_within_two_dollars(ladder_run):
    ctx, result = ladder_run
    assert result.spent_usd <= 2.0 + 1e-9
    assert verify_manifest(_manifest(ctx), base_dir=ctx.job_dir).get("I2_budget").passed


# ===========================================================================
# resume / idempotency / guards
# ===========================================================================
def test_rerun_is_idempotent_and_does_not_double_charge(tmp_path):
    ctx = create_context("forklift", 4.0, "fake", job_id="idem", home=tmp_path)
    first = run_pipeline(ctx)
    seen: list[str] = []
    second = run_pipeline(ctx, on_stage=lambda n, s, d: seen.append(s))
    assert second.spent_usd == first.spent_usd
    assert set(seen) == {"cached"}  # every stage already done


def test_plan_stops_after_budget_alloc(tmp_path):
    ctx = create_context("forklift", 4.0, "fake", job_id="planonly", home=tmp_path)
    run_pipeline(ctx, until="budget_alloc")
    assert (ctx.job_dir / "allocation.json").exists()
    assert not (ctx.job_dir / "film.mp4").exists()
    assert ctx.storage.stage_status(ctx.job_id, "render") == "pending"


def test_unknown_until_stage_raises(tmp_path):
    ctx = create_context("forklift", 4.0, "fake", job_id="bad-until", home=tmp_path)
    with pytest.raises(ValueError, match="unknown stage"):
        run_pipeline(ctx, until="nonexistent")


def test_budget_below_minimum_rejected(tmp_path):
    with pytest.raises(ValueError, match="minimum"):
        create_context("forklift", MIN_BUDGET_USD - 0.5, "fake", home=tmp_path)


def test_publish_records_manifest_row(forklift_run):
    ctx, _ = forklift_run
    row = ctx.storage.get_manifest(ctx.job_id)
    assert row is not None and row["leaf_count"] == len(_manifest(ctx).leaves)


# ===========================================================================
# stage-level branches not reached by the three seed happy paths
# ===========================================================================
def test_artifact_sha_raises_keyerror_for_unregistered_artifact(tmp_path):
    from foreshadow.pipeline.stages import _artifact_sha

    ctx = create_context("forklift", 4.0, "fake", job_id="artifact-sha-miss", home=tmp_path)
    with pytest.raises(KeyError, match="artifact not registered"):
        _artifact_sha(ctx, "not/a/real/path.png")


def test_ingest_reads_from_custom_incident_file(tmp_path):
    from foreshadow.crypto.sealing import unseal

    custom = tmp_path / "custom_incident.txt"
    custom.write_text("A hand-written near-miss narrative for testing.", encoding="utf-8")
    ctx = create_context(
        "forklift", 4.0, "fake", job_id="custom-file",
        home=tmp_path / "home", incident_file=custom,
    )
    run_pipeline(ctx, until="ingest")
    sealed = (ctx.job_dir / "incident.sealed").read_bytes()
    plaintext = unseal(sealed, ctx.worker_key).decode("utf-8")
    assert plaintext == "A hand-written near-miss narrative for testing."


def test_incident_source_not_found_raises(tmp_path):
    ctx = create_context("not-a-real-incident", 4.0, "fake", job_id="no-source", home=tmp_path)
    with pytest.raises(FileNotFoundError, match="incident source not found"):
        run_pipeline(ctx, until="ingest")


def _forced_qc(ctx, target_shot_id: str, *, always_fail: bool):
    """Wraps ctx.transport.qc_review so `target_shot_id` gets a forced
    rejection (once, or every time), while every other shot goes through the
    real fixture-backed FakeQwen logic untouched. Returns the call counter
    for the forced shot."""
    from foreshadow import config
    from foreshadow.qwen.base import CallMeta
    from foreshadow.qwen.fake import qc_prompt

    orig = ctx.transport.qc_review
    counter = {"n": 0}

    def _wrapped(shot, clip_prompt, frame_png):
        if shot["id"] == target_shot_id and (always_fail or counter["n"] == 0):
            counter["n"] += 1
            verdict = {
                "shot_id": target_shot_id, "pass": False,
                "issues": ["forced test rejection"], "action": "re-render_with_note",
            }
            meta = CallMeta(
                model=config.MODEL_QC, task_id=f"forced-{counter['n']}",
                latency_ms=1, prompt=qc_prompt(shot, clip_prompt),
            )
            return verdict, meta
        return orig(shot, clip_prompt, frame_png)

    ctx.transport.qc_review = _wrapped
    return counter


def test_qc_double_reject_demotes_after_failed_retry(tmp_path):
    """A shot that fails QC twice in a row (attempt 1 + the corrective
    re-render) is rejected both times and demoted to a Ken Burns still."""
    from foreshadow.pipeline.stages import stage_qc
    from foreshadow.utils import read_json

    ctx = create_context("forklift", 4.0, "fake", job_id="qc-double-reject", home=tmp_path)
    run_pipeline(ctx, until="render")
    target = "S2"  # connective tier, cheap enough that the retry is affordable
    counter = _forced_qc(ctx, target, always_fail=True)

    detail = stage_qc(ctx)
    assert counter["n"] == 2  # attempt1 + attempt2, both forced to fail
    assert detail["retries"] >= 1
    assert detail["demoted"] >= 1
    assert (ctx.job_dir / f"clips/{target}_kenburns.mp4").exists()
    summary = read_json(ctx.job_dir / "qc/summary.json")
    assert len(summary["rejected_sha256"]) >= 2


def test_qc_budget_blocked_retry_skips_render_and_demotes(tmp_path):
    """When the remaining budget can't cover a corrective re-render + its
    re-review, the retry is skipped entirely and the shot demotes straight
    to Ken Burns (no attempt2 clip is ever rendered)."""
    from foreshadow import config
    from foreshadow.agents.line_producer import tier_cost
    from foreshadow.pipeline.stages import stage_qc
    from foreshadow.schemas import Allocation
    from foreshadow.utils import read_json

    ctx = create_context("forklift", 4.0, "fake", job_id="qc-budget-blocked", home=tmp_path)
    run_pipeline(ctx, until="render")
    target = "S8"

    alloc = Allocation.model_validate(read_json(ctx.job_dir / "allocation.json"))
    tiers = {d.shot_id: d.tier for d in alloc.decisions}
    render_cost = tier_cost(tiers[target], 4)
    retry_cost = render_cost + config.COST_QC_PER_REVIEW
    # drain the ledger so remaining budget can't cover one more retry
    drain = ctx.ledger.remaining_usd() - (retry_cost - 0.01)
    ctx.ledger.charge("test_drain", drain, "test: force budget-blocked QC retry")
    assert ctx.ledger.remaining_usd() < retry_cost

    _forced_qc(ctx, target, always_fail=False)
    detail = stage_qc(ctx)

    assert detail["demoted"] >= 1
    assert not (ctx.job_dir / f"clips/{target}_attempt2.mp4").exists()
    assert (ctx.job_dir / f"clips/{target}_kenburns.mp4").exists()
    items = [row["item"] for row in ctx.ledger.rows()]
    assert f"qc_demote:{target}" in items


def test_stage_publish_raises_on_ledger_overspend(tmp_path):
    """The I2 safety-net check at publish time: if the ledger somehow ends
    up over budget (should never happen through the normal allocator path),
    publish refuses to sign a manifest rather than silently lying about
    spend."""
    from foreshadow.pipeline.stages import stage_publish

    ctx = create_context("forklift", 4.0, "fake", job_id="overspend", home=tmp_path)
    ctx.ledger.charge("test_overspend", 4.5, "test: force spend past budget "
                                              "(under the 2.5x kill switch cap)")
    with pytest.raises(RuntimeError, match="I2 violation caught at publish"):
        stage_publish(ctx)


def test_stage_publish_raises_when_self_check_fails(tmp_path, monkeypatch):
    """publish's final self-verification: if verify_manifest ever reports a
    failing check on the manifest it just built, publish must raise instead
    of persisting an unverified manifest."""
    from foreshadow.pipeline.stages import stage_publish
    from foreshadow.provenance import VerifyReport

    ctx = create_context("forklift", 4.0, "fake", job_id="selfcheck-fail", home=tmp_path)
    run_pipeline(ctx, until="stitch")

    def _fake_verify_manifest(manifest, base_dir=None, film_path=None, trusted_pubkey_hex=None):
        report = VerifyReport()
        report.add("forced_failure", False, "test: forced self-check failure")
        return report

    monkeypatch.setattr("foreshadow.provenance.verify_manifest", _fake_verify_manifest)
    with pytest.raises(RuntimeError, match=r"manifest self-check failed: \['forced_failure'\]"):
        stage_publish(ctx)
