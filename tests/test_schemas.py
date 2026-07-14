"""Pydantic contracts: the structured-output schemas + provenance models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from foreshadow.schemas import (
    Allocation,
    Beat,
    BudgetDecision,
    Manifest,
    ManifestLeaf,
    QCVerdict,
    RegretRow,
    Screenplay,
    Shot,
    ShotPlan,
    prompt_sha,
)
from foreshadow.utils import sha256_hex

SHA = sha256_hex(b"x")


# -- Shot -------------------------------------------------------------------
def test_shot_valid():
    s = Shot(id="S3", scene=2, duration_s=5, action="a", camera="c", narrative_weight=9)
    assert s.id == "S3" and s.narrative_weight == 9


@pytest.mark.parametrize("bad_id", ["s3", "SS1", "3", "S", "S3a", "shot1"])
def test_shot_id_pattern_rejects(bad_id):
    with pytest.raises(ValidationError):
        Shot(id=bad_id, scene=1, duration_s=5, action="a", camera="c", narrative_weight=5)


@pytest.mark.parametrize("dur", [0, 11, -1])
def test_shot_duration_bounds(dur):
    with pytest.raises(ValidationError):
        Shot(id="S1", scene=1, duration_s=dur, action="a", camera="c", narrative_weight=5)


@pytest.mark.parametrize("w", [0, 11, -3])
def test_shot_weight_bounds(w):
    with pytest.raises(ValidationError):
        Shot(id="S1", scene=1, duration_s=5, action="a", camera="c", narrative_weight=w)


def test_shot_scene_min():
    with pytest.raises(ValidationError):
        Shot(id="S1", scene=0, duration_s=5, action="a", camera="c", narrative_weight=5)


def test_shot_requires_action_and_camera():
    with pytest.raises(ValidationError):
        Shot(id="S1", scene=1, duration_s=5, action="", camera="c", narrative_weight=5)


def test_shot_extra_key_forbidden():
    with pytest.raises(ValidationError):
        Shot(id="S1", scene=1, duration_s=5, action="a", camera="c",
             narrative_weight=5, bogus=1)


def test_shot_defaults():
    s = Shot(id="S1", scene=1, duration_s=5, action="a", camera="c", narrative_weight=5)
    assert s.safety_elements == [] and s.vo_line == ""


# -- ShotPlan ---------------------------------------------------------------
def test_shotplan_rejects_duplicate_ids():
    shots = [
        Shot(id="S1", scene=1, duration_s=5, action="a", camera="c", narrative_weight=5),
        Shot(id="S1", scene=1, duration_s=5, action="b", camera="c", narrative_weight=5),
    ]
    with pytest.raises(ValidationError, match="duplicate shot ids"):
        ShotPlan(incident_id="x", shots=shots)


def test_shotplan_requires_at_least_one_shot():
    with pytest.raises(ValidationError):
        ShotPlan(incident_id="x", shots=[])


def test_shotplan_accepts_unique_ids():
    shots = [
        Shot(id="S1", scene=1, duration_s=5, action="a", camera="c", narrative_weight=5),
        Shot(id="S2", scene=1, duration_s=5, action="b", camera="c", narrative_weight=6),
    ]
    assert len(ShotPlan(incident_id="x", shots=shots).shots) == 2


# -- Screenplay -------------------------------------------------------------
def test_screenplay_valid():
    sp = Screenplay(
        incident_id="x", title="T", logline="L",
        beats=[Beat(beat=1, heading="H", description="D")], rule_card="R",
    )
    assert sp.beats[0].beat == 1


def test_screenplay_requires_beats():
    with pytest.raises(ValidationError):
        Screenplay(incident_id="x", title="T", logline="L", beats=[], rule_card="R")


def test_beat_min_index():
    with pytest.raises(ValidationError):
        Beat(beat=0, heading="H", description="D")


# -- BudgetDecision ---------------------------------------------------------
def test_budget_decision_demoted_true():
    d = BudgetDecision(shot_id="S1", tier="kenburns", desired_tier="hero", est_cost_usd=0.0)
    assert d.demoted is True


def test_budget_decision_not_demoted_when_equal():
    d = BudgetDecision(shot_id="S1", tier="hero", desired_tier="hero", est_cost_usd=0.5)
    assert d.demoted is False


def test_budget_decision_upgrade_is_not_demoted():
    d = BudgetDecision(shot_id="S1", tier="hero", desired_tier="connective", est_cost_usd=0.5)
    assert d.demoted is False


def test_budget_decision_rejects_bad_tier():
    with pytest.raises(ValidationError):
        BudgetDecision(shot_id="S1", tier="deluxe", desired_tier="hero", est_cost_usd=0.5)


def test_budget_decision_negative_cost_rejected():
    with pytest.raises(ValidationError):
        BudgetDecision(shot_id="S1", tier="hero", desired_tier="hero", est_cost_usd=-1)


# -- RegretRow / Allocation -------------------------------------------------
def test_regret_row_valid():
    r = RegretRow(shot_id="S1", from_tier="hero", to_tier="kenburns",
                  saved_usd=0.5, lost_quality_weight=6.3)
    assert r.saved_usd == 0.5


def test_allocation_requires_positive_budget():
    with pytest.raises(ValidationError):
        Allocation(incident_id="x", budget_usd=0, overhead_est_usd=0,
                   retry_reserve_usd=0, render_budget_usd=0, decisions=[],
                   render_spend_usd=0, quality_score=0, quality_max=0)


# -- QCVerdict (alias) ------------------------------------------------------
def test_qcverdict_from_pass_alias():
    v = QCVerdict.model_validate({"shot_id": "S1", "pass": False,
                                  "issues": ["x"], "action": "re-render_with_note"})
    assert v.passed is False


def test_qcverdict_populate_by_name():
    v = QCVerdict(shot_id="S1", passed=True, action="accept")
    assert v.passed is True


def test_qcverdict_dump_by_alias_uses_pass():
    v = QCVerdict(shot_id="S1", passed=True, action="accept")
    assert v.model_dump(by_alias=True)["pass"] is True


def test_qcverdict_rejects_bad_action():
    with pytest.raises(ValidationError):
        QCVerdict.model_validate({"shot_id": "S1", "pass": True, "action": "ship_it"})


def test_qcverdict_rejects_extra_key():
    with pytest.raises(ValidationError):
        QCVerdict.model_validate({"shot_id": "S1", "pass": True,
                                  "action": "accept", "extra": 1})


# -- ManifestLeaf -----------------------------------------------------------
def test_manifest_leaf_sha_pattern():
    with pytest.raises(ValidationError):
        ManifestLeaf(sha256="short", kind="k", cost_usd=0, ts=0, path="p")


def test_manifest_leaf_payload_stable_keys():
    lf = ManifestLeaf(sha256=SHA, kind="clip", cost_usd=0.5, ts=1, path="clips/a.mp4",
                      qwen_task_id="fake-task-1")
    payload = lf.leaf_payload()
    assert set(payload) == {
        "sha256", "kind", "model", "prompt_sha256", "qwen_task_id",
        "parent_ids", "cost_usd", "ts", "path",
    }


def test_manifest_leaf_requires_path():
    with pytest.raises(ValidationError):
        ManifestLeaf(sha256=SHA, kind="k", cost_usd=0, ts=0, path="")


# -- Manifest signed payload ------------------------------------------------
def test_manifest_signed_payload_uses_leaf_count_not_leaves():
    m = Manifest(
        job_id="j", incident_id="x", budget_usd=4, spent_usd=1, created_ts=0,
        leaves=[ManifestLeaf(sha256=SHA, kind="k", cost_usd=0, ts=0, path="p")],
        edit_list=[SHA], qc_rejected=[], merkle_root="a" * 64,
        signer_pubkey="b" * 64, signature="c" * 128,
    )
    payload = m.signed_payload()
    assert payload["leaf_count"] == 1 and "leaves" not in payload
    assert payload["edit_list"] == [SHA]


def test_manifest_signature_hex_length_enforced():
    with pytest.raises(ValidationError):
        Manifest(
            job_id="j", incident_id="x", budget_usd=4, spent_usd=1, created_ts=0,
            leaves=[ManifestLeaf(sha256=SHA, kind="k", cost_usd=0, ts=0, path="p")],
            edit_list=[SHA], qc_rejected=[], merkle_root="a" * 64,
            signer_pubkey="b" * 64, signature="tooshort",
        )


def test_manifest_load_roundtrip(tmp_path):
    from foreshadow.utils import write_json
    m = Manifest(
        job_id="j", incident_id="x", budget_usd=4, spent_usd=1, created_ts=0,
        leaves=[ManifestLeaf(sha256=SHA, kind="k", cost_usd=0, ts=0, path="p")],
        edit_list=[SHA], qc_rejected=[], merkle_root="a" * 64,
        signer_pubkey="b" * 64, signature="c" * 128,
    )
    p = tmp_path / "m.json"
    write_json(p, m.model_dump())
    loaded = Manifest.load(p)
    assert loaded.job_id == "j" and loaded.merkle_root == "a" * 64


def test_manifest_verify_convenience_method_matches_module_function():
    """Manifest.verify() is a thin wrapper around provenance.verify_manifest;
    exercised here against a real, fully signed committed manifest."""
    from foreshadow import config
    from foreshadow.provenance import VerifyReport

    d = config.fixtures_dir() / "cache" / "forklift"
    m = Manifest.load(d / "manifest.json")
    report = m.verify(base_dir=d, film_path=d / "film.mp4")
    assert isinstance(report, VerifyReport)
    assert report.ok


# -- prompt_sha -------------------------------------------------------------
def test_prompt_sha_deterministic():
    assert prompt_sha("hello") == prompt_sha("hello")


def test_prompt_sha_distinct():
    assert prompt_sha("a") != prompt_sha("b")


def test_prompt_sha_is_64_hex():
    assert len(prompt_sha("x")) == 64
