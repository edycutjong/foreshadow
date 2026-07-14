"""Formal invariants I1-I4 (COMPLEXITY.md section 2), each failed in isolation.

  I1  every final-cut entry traces to a signed leaf with a real qwen_task_id
  I2  spent_usd <= budget AND leaf costs reconcile with the ledger
  I3  no QC-rejected clip hash appears in the final edit list
  I4  a 1-byte artifact tamper fails manifest re-hash verification
"""

from __future__ import annotations

import pytest
from support import build_signed_manifest, leaf, passing_leaf_set

from foreshadow.crypto.signing import demo_signing_key, pubkey_hex
from foreshadow.provenance import (
    _ancestor_has_task_id,
    build_manifest,
    verify_manifest,
)
from foreshadow.schemas import Manifest, ManifestLeaf
from foreshadow.storage import SQLiteStorage
from foreshadow.utils import sha256_hex


def _leaf(sha, task="", parents=()):
    return ManifestLeaf(sha256=sha, kind="clip", cost_usd=0.0, ts=0, path="p",
                        qwen_task_id=task, parent_ids=list(parents))


# ===========================================================================
# Happy path: a well-formed manifest passes every invariant
# ===========================================================================
def test_passing_manifest_satisfies_all_invariants():
    manifest, _ = build_signed_manifest(*passing_leaf_set())
    report = verify_manifest(manifest)
    assert report.ok, [c.name for c in report.checks if not c.passed]
    for name in ("signature", "merkle_root", "I1_traceable_edit_list",
                 "I2_budget", "I3_rejected_excluded"):
        assert report.get(name).passed


def test_build_manifest_rejects_zero_leaves():
    storage = SQLiteStorage(":memory:")
    storage.create_job("j", "forklift", 4.0, "fake", 0)
    with pytest.raises(ValueError, match="zero leaves"):
        build_manifest(storage=storage, job_id="j", incident_id="forklift",
                       budget_usd=4.0, edit_list=[], qc_rejected=[],
                       signing_key=demo_signing_key(), created_ts=0)


# ===========================================================================
# I1 — traceability to a real qwen_task_id
# ===========================================================================
def test_ancestor_has_task_id_direct_self():
    s = sha256_hex(b"1")
    assert _ancestor_has_task_id(s, {s: _leaf(s, task="fake-task-1")})


def test_ancestor_has_task_id_through_parent():
    child, parent = sha256_hex(b"c"), sha256_hex(b"p")
    by_sha = {child: _leaf(child, parents=(parent,)),
              parent: _leaf(parent, task="fake-task-1")}
    assert _ancestor_has_task_id(child, by_sha)


def test_ancestor_has_task_id_two_levels_up():
    a, b, c = sha256_hex(b"a"), sha256_hex(b"b"), sha256_hex(b"c")
    by_sha = {a: _leaf(a, parents=(b,)), b: _leaf(b, parents=(c,)),
              c: _leaf(c, task="fake-task-1")}
    assert _ancestor_has_task_id(a, by_sha)


def test_ancestor_no_task_anywhere_is_false():
    a, b = sha256_hex(b"a"), sha256_hex(b"b")
    by_sha = {a: _leaf(a, parents=(b,)), b: _leaf(b)}
    assert not _ancestor_has_task_id(a, by_sha)


def test_ancestor_missing_parent_is_false():
    a = sha256_hex(b"a")
    assert not _ancestor_has_task_id(a, {a: _leaf(a, parents=(sha256_hex(b"gone"),))})


def test_ancestor_cycle_terminates_false():
    a, b = sha256_hex(b"a"), sha256_hex(b"b")
    by_sha = {a: _leaf(a, parents=(b,)), b: _leaf(b, parents=(a,))}  # cycle, no task
    assert not _ancestor_has_task_id(a, by_sha)


def test_I1_fails_when_edit_entry_is_untraceable():
    sp = leaf("screenplay", "screenplay.json", task="fake-task-1", cost=0.10)
    dangle = leaf("card", "cards/orphan.png")  # no task, no parents
    manifest, _ = build_signed_manifest([sp, dangle], [dangle["sha256"]], [])
    report = verify_manifest(manifest)
    assert report.get("signature").passed  # signature still valid
    assert not report.get("I1_traceable_edit_list").passed
    assert not report.ok


# ===========================================================================
# I2 — budget cap and ledger reconciliation
# ===========================================================================
def test_I2_fails_when_spent_exceeds_budget():
    sp = leaf("screenplay", "screenplay.json", task="fake-task-1", cost=0.10)
    clip = leaf("clip", "clips/S1.mp4", task="fake-task-2",
                parents=(sp["sha256"],), cost=0.50)
    manifest, _ = build_signed_manifest([sp, clip], [clip["sha256"]], [], budget_usd=0.1)
    report = verify_manifest(manifest)
    assert report.get("signature").passed
    assert not report.get("I2_budget").passed


def test_I2_fails_when_leaf_costs_do_not_reconcile():
    sp = leaf("screenplay", "screenplay.json", task="fake-task-1", cost=0.10)
    # clip cost is present on the leaf but NOT mirrored into the ledger:
    clip = leaf("clip", "clips/S1.mp4", task="fake-task-2",
                parents=(sp["sha256"],), cost=0.50, charge=False)
    manifest, _ = build_signed_manifest([sp, clip], [clip["sha256"]], [], budget_usd=4.0)
    report = verify_manifest(manifest)
    assert report.get("signature").passed
    assert not report.get("I2_budget").passed


def test_I2_passes_when_within_budget_and_reconciled():
    manifest, _ = build_signed_manifest(*passing_leaf_set())
    assert verify_manifest(manifest).get("I2_budget").passed


# ===========================================================================
# I3 — QC-rejected clips excluded from the cut
# ===========================================================================
def test_I3_fails_when_rejected_sha_is_in_edit_list():
    sp = leaf("screenplay", "screenplay.json", task="fake-task-1", cost=0.10)
    clip = leaf("clip", "clips/S1.mp4", task="fake-task-2",
                parents=(sp["sha256"],), cost=0.50)
    manifest, _ = build_signed_manifest(
        [sp, clip], edit_list=[clip["sha256"]], qc_rejected=[clip["sha256"]]
    )
    report = verify_manifest(manifest)
    assert report.get("signature").passed
    assert not report.get("I3_rejected_excluded").passed


def test_I3_fails_when_rejected_kind_leaf_is_in_edit_list():
    sp = leaf("screenplay", "screenplay.json", task="fake-task-1", cost=0.10)
    rej = leaf("clip_rejected", "clips/S1_attempt1.mp4", task="fake-task-2",
               parents=(sp["sha256"],), cost=0.50)
    manifest, _ = build_signed_manifest([sp, rej], edit_list=[rej["sha256"]], qc_rejected=[])
    report = verify_manifest(manifest)
    assert not report.get("I3_rejected_excluded").passed


def test_I3_passes_when_rejected_clip_is_outside_the_cut():
    sp = leaf("screenplay", "screenplay.json", task="fake-task-1", cost=0.10)
    good = leaf("clip", "clips/S1_attempt2.mp4", task="fake-task-3",
                parents=(sp["sha256"],), cost=0.50)
    rejected_sha = sha256_hex(b"rejected-attempt-1")
    manifest, _ = build_signed_manifest(
        [sp, good], edit_list=[good["sha256"]], qc_rejected=[rejected_sha]
    )
    assert verify_manifest(manifest).get("I3_rejected_excluded").passed


# ===========================================================================
# signature / merkle tamper (backs I4's chain-of-custody)
# ===========================================================================
def test_signature_tamper_detected():
    manifest, _ = build_signed_manifest(*passing_leaf_set())
    tampered = manifest.model_copy(update={"signature": "1" * 128})
    assert not verify_manifest(tampered).get("signature").passed


def test_merkle_root_tamper_detected():
    manifest, _ = build_signed_manifest(*passing_leaf_set())
    tampered = manifest.model_copy(update={"merkle_root": "0" * 64})
    assert not verify_manifest(tampered).get("merkle_root").passed


def test_trusted_pubkey_match():
    manifest, _ = build_signed_manifest(*passing_leaf_set())
    report = verify_manifest(manifest, trusted_pubkey_hex=pubkey_hex(demo_signing_key()))
    assert report.get("signature").passed
    assert report.get("trusted_signer").passed


def test_trusted_pubkey_mismatch_fails_both_checks():
    manifest, _ = build_signed_manifest(*passing_leaf_set())
    report = verify_manifest(manifest, trusted_pubkey_hex="0" * 64)
    assert not report.get("signature").passed
    assert not report.get("trusted_signer").passed


# ===========================================================================
# I4 — 1-byte artifact tamper fails re-hash (against the committed caches)
# ===========================================================================
INCIDENTS = ["forklift", "ladder", "chemical"]


@pytest.mark.parametrize("incident", INCIDENTS)
def test_cached_manifest_verifies_untampered(incident, tmp_path):
    from support import copy_cache
    d = copy_cache(incident, tmp_path)
    manifest = Manifest.load(d / "manifest.json")
    report = verify_manifest(manifest, base_dir=d, film_path=d / "film.mp4")
    assert report.ok, [c.name for c in report.checks if not c.passed]


@pytest.mark.parametrize("incident", INCIDENTS)
def test_I4_one_byte_artifact_tamper_fails(incident, tmp_path):
    from support import copy_cache
    d = copy_cache(incident, tmp_path)
    target = d / "character_sheet.png"
    raw = bytearray(target.read_bytes())
    raw[-1] ^= 0x01  # flip one byte
    target.write_bytes(bytes(raw))
    manifest = Manifest.load(d / "manifest.json")
    report = verify_manifest(manifest, base_dir=d, film_path=d / "film.mp4")
    assert not report.get("I4_artifact_hashes").passed
    assert not report.ok


def test_I4_film_tamper_fails(tmp_path):
    from support import copy_cache
    d = copy_cache("forklift", tmp_path)
    film = d / "film.mp4"
    film.write_bytes(film.read_bytes() + b"\x00")  # append a byte
    manifest = Manifest.load(d / "manifest.json")
    report = verify_manifest(manifest, base_dir=d, film_path=film)
    assert not report.get("I4_film_hash").passed


def test_I4_missing_artifact_fails(tmp_path):
    from support import copy_cache
    d = copy_cache("forklift", tmp_path)
    (d / "character_sheet.png").unlink()
    manifest = Manifest.load(d / "manifest.json")
    report = verify_manifest(manifest, base_dir=d)
    check = report.get("I4_artifact_hashes")
    assert not check.passed and "missing" in check.detail


# ===========================================================================
# VerifyReport helper surface
# ===========================================================================
def test_verify_report_get_unknown_raises():
    manifest, _ = build_signed_manifest(*passing_leaf_set())
    report = verify_manifest(manifest)
    with pytest.raises(KeyError):
        report.get("nonexistent_check")
