"""Storage layer (SQLite default): jobs, stages, shots, ledger, artifacts."""

from __future__ import annotations

from foreshadow.storage import SQLiteStorage


def _storage():
    s = SQLiteStorage(":memory:")
    s.create_job("j1", "forklift", 4.0, "fake", 1000)
    return s


# -- jobs -------------------------------------------------------------------
def test_create_and_get_job():
    s = _storage()
    job = s.get_job("j1")
    assert job["incident_id"] == "forklift"
    assert job["status"] == "created"
    assert job["budget_usd"] == 4.0
    assert job["transport"] == "fake"


def test_get_unknown_job_is_none():
    assert SQLiteStorage(":memory:").get_job("nope") is None


def test_create_job_is_idempotent():
    s = _storage()
    s.create_job("j1", "ladder", 9.0, "live", 2000)  # INSERT OR IGNORE
    assert s.get_job("j1")["incident_id"] == "forklift"  # unchanged


def test_set_job_status():
    s = _storage()
    s.set_job_status("j1", "running")
    assert s.get_job("j1")["status"] == "running"


def test_add_spend_accumulates_and_rounds():
    s = _storage()
    assert s.add_spend("j1", 0.1) == 0.1
    assert s.add_spend("j1", 0.2) == 0.3
    assert s.get_job("j1")["spent_usd"] == 0.3


# -- ledger -----------------------------------------------------------------
def test_ledger_append_and_total():
    s = _storage()
    s.append_ledger("j1", 1, "a", 0.10, "note-a")
    s.append_ledger("j1", 2, "b", 0.25, "note-b")
    assert s.ledger_total("j1") == 0.35


def test_ledger_for_job_preserves_insertion_order():
    s = _storage()
    for i, item in enumerate(["z", "a", "m"]):
        s.append_ledger("j1", i, item, 0.0, "")
    assert [r["item"] for r in s.ledger_for_job("j1")] == ["z", "a", "m"]


def test_ledger_total_empty_is_zero():
    assert _storage().ledger_total("j1") == 0.0


# -- artifacts --------------------------------------------------------------
def test_add_and_list_artifact_with_meta():
    s = _storage()
    s.add_artifact("j1", "clip", "clips/S1.mp4", "a" * 64, {"model": "wan2.7-i2v"})
    rows = s.artifacts_for_job("j1")
    assert rows[0]["sha256"] == "a" * 64
    assert rows[0]["meta"] == {"model": "wan2.7-i2v"}


def test_add_artifact_conflict_updates_in_place():
    s = _storage()
    s.add_artifact("j1", "clip", "clips/S1.mp4", "a" * 64, {"v": 1})
    s.add_artifact("j1", "clip_rejected", "clips/S1.mp4", "a" * 64, {"v": 2})
    rows = s.artifacts_for_job("j1")
    assert len(rows) == 1
    assert rows[0]["kind"] == "clip_rejected"
    assert rows[0]["meta"] == {"v": 2}


def test_artifacts_empty_default_meta():
    s = _storage()
    s.add_artifact("j1", "k", "p", "b" * 64)
    assert s.artifacts_for_job("j1")[0]["meta"] == {}


# -- shots ------------------------------------------------------------------
def test_upsert_shot_and_read_back():
    s = _storage()
    plan = {"id": "S1", "narrative_weight": 9}
    s.upsert_shot("j1", "S1", plan, tier="hero", task_id="fake-task-1", cost_usd=0.5)
    rows = s.shots_for_job("j1")
    assert rows[0]["plan"] == plan
    assert rows[0]["tier"] == "hero"
    assert rows[0]["task_id"] == "fake-task-1"
    assert rows[0]["cost_usd"] == 0.5
    assert rows[0]["qc"] is None


def test_upsert_shot_partial_update_preserves_plan():
    s = _storage()
    s.upsert_shot("j1", "S1", {"id": "S1", "w": 9})
    s.upsert_shot("j1", "S1", {"id": "S1", "w": 9}, tier="connective")
    row = s.shots_for_job("j1")[0]
    assert row["plan"] == {"id": "S1", "w": 9}
    assert row["tier"] == "connective"


def test_upsert_shot_qc_json_roundtrip():
    s = _storage()
    s.upsert_shot("j1", "S1", {"id": "S1"}, qc={"pass": True, "issues": []})
    assert s.shots_for_job("j1")[0]["qc"] == {"pass": True, "issues": []}


def test_shots_sorted_by_id():
    s = _storage()
    for sid in ["S3", "S1", "S2"]:
        s.upsert_shot("j1", sid, {"id": sid})
    assert [r["shot_id"] for r in s.shots_for_job("j1")] == ["S1", "S2", "S3"]


# -- stages -----------------------------------------------------------------
def test_stage_status_defaults_to_pending():
    assert _storage().stage_status("j1", "ingest") == "pending"


def test_mark_stage_running_sets_started():
    s = _storage()
    s.mark_stage("j1", "ingest", "running", ts=1234)
    stage = s.get_stage("j1", "ingest")
    assert stage["status"] == "running" and stage["started"] == 1234


def test_mark_stage_done_sets_finished_and_detail():
    s = _storage()
    s.mark_stage("j1", "ingest", "running", ts=1)
    s.mark_stage("j1", "ingest", "done", ts=9, detail='{"ok": true}')
    stage = s.get_stage("j1", "ingest")
    assert stage["status"] == "done" and stage["finished"] == 9
    assert stage["detail"] == '{"ok": true}'


def test_mark_stage_failed_records_error():
    s = _storage()
    s.mark_stage("j1", "render", "failed", ts=3, error="boom")
    assert s.get_stage("j1", "render")["error"] == "boom"


def test_stages_for_job_in_creation_order():
    s = _storage()
    for name in ["ingest", "screenplay", "shot_plan"]:
        s.mark_stage("j1", name, "done", ts=1)
    assert [r["name"] for r in s.stages_for_job("j1")] == ["ingest", "screenplay", "shot_plan"]


# -- manifests --------------------------------------------------------------
def test_save_and_get_manifest():
    s = _storage()
    s.save_manifest("j1", "root", "sig", 12, verified_at=42)
    m = s.get_manifest("j1")
    assert m["merkle_root"] == "root" and m["leaf_count"] == 12 and m["verified_at"] == 42


def test_get_manifest_absent_is_none():
    assert _storage().get_manifest("j1") is None


# -- deletion ---------------------------------------------------------------
def test_delete_job_wipes_all_tables():
    s = _storage()
    s.append_ledger("j1", 1, "a", 0.1)
    s.add_artifact("j1", "k", "p", "a" * 64)
    s.upsert_shot("j1", "S1", {"id": "S1"})
    s.mark_stage("j1", "ingest", "done", ts=1)
    s.save_manifest("j1", "r", "s", 1)
    s.delete_job("j1")
    assert s.get_job("j1") is None
    assert s.ledger_for_job("j1") == []
    assert s.artifacts_for_job("j1") == []
    assert s.shots_for_job("j1") == []
    assert s.stages_for_job("j1") == []
    assert s.get_manifest("j1") is None


# -- file-backed variant creates its parent dir -----------------------------
def test_file_backed_storage_creates_parent(tmp_path):
    db = tmp_path / "nested" / "foreshadow.db"
    s = SQLiteStorage(db)
    s.create_job("j", "forklift", 4.0, "fake", 0)
    assert db.exists()
    s.close()
