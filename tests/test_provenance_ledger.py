"""ProvenanceLedger: cost ledger, artifact registration, 2.5xB kill switch."""

from __future__ import annotations

import pytest

from foreshadow import config
from foreshadow.provenance import KillSwitchTripped, ProvenanceLedger
from foreshadow.storage import SQLiteStorage
from foreshadow.utils import FixedClock


def _ledger(budget=4.0, job="job-1"):
    storage = SQLiteStorage(":memory:")
    storage.create_job(job, "forklift", budget, "fake", 0)
    return ProvenanceLedger(storage, job, budget, FixedClock()), storage, job


def test_charge_records_and_accumulates_spend():
    ledger, storage, job = _ledger()
    ledger.charge("screenplay", 0.10, "qwen3.7-max")
    ledger.charge("render:S1", 0.50, "hero")
    assert ledger.spent_usd == 0.60
    assert storage.ledger_total(job) == 0.60


def test_charge_appends_ledger_rows():
    ledger, storage, job = _ledger()
    ledger.charge("a", 0.10)
    ledger.charge("b", 0.20)
    rows = storage.ledger_for_job(job)
    assert [r["item"] for r in rows] == ["a", "b"]
    assert [r["cost_usd"] for r in rows] == [0.10, 0.20]


def test_remaining_usd():
    ledger, _, _ = _ledger(budget=4.0)
    ledger.charge("x", 1.5)
    assert ledger.remaining_usd() == 2.5


def test_note_is_zero_cost_row():
    ledger, storage, job = _ledger()
    ledger.note("decision:S1", "demoted hero->connective")
    rows = storage.ledger_for_job(job)
    assert rows[0]["cost_usd"] == 0.0
    assert ledger.spent_usd == 0.0


def test_negative_charge_rejected():
    ledger, _, _ = _ledger()
    with pytest.raises(ValueError, match="negative charge"):
        ledger.charge("x", -0.01)


def test_rows_includes_notes_and_charges_in_order():
    ledger, _, _ = _ledger()
    ledger.charge("a", 0.1)
    ledger.note("n", "note")
    ledger.charge("b", 0.2)
    items = [r["item"] for r in ledger.rows()]
    assert items == ["a", "n", "b"]


# -- kill switch (hard stop at 2.5 x budget) --------------------------------
def test_kill_switch_allows_spend_up_to_the_cap():
    ledger, _, _ = _ledger(budget=1.0)
    ledger.charge("big", 2.5)  # exactly 2.5x -> allowed
    assert ledger.spent_usd == 2.5


def test_kill_switch_trips_just_past_cap():
    ledger, storage, job = _ledger(budget=1.0)
    ledger.charge("big", 2.5)
    with pytest.raises(KillSwitchTripped):
        ledger.charge("tip", 0.01)
    assert storage.get_job(job)["status"] == "killed"


def test_kill_switch_trips_on_single_oversized_charge():
    ledger, _, _ = _ledger(budget=1.0)
    with pytest.raises(KillSwitchTripped, match="kill switch"):
        ledger.charge("huge", 3.0)


def test_kill_switch_blocks_all_further_spend_once_tripped():
    ledger, _, _ = _ledger(budget=1.0)
    with pytest.raises(KillSwitchTripped):
        ledger.charge("huge", 3.0)
    with pytest.raises(KillSwitchTripped, match="already tripped"):
        ledger.charge("anything", 0.01)


def test_kill_switch_cap_is_2_5x_budget():
    ledger, _, _ = _ledger(budget=2.0)
    ledger.charge("ok", 5.0)  # 2.5 x 2.0
    with pytest.raises(KillSwitchTripped):
        ledger.charge("over", 0.01)


def test_tripped_charge_does_not_record_ledger_row():
    ledger, storage, job = _ledger(budget=1.0)
    with pytest.raises(KillSwitchTripped):
        ledger.charge("huge", 3.0)
    assert storage.ledger_total(job) == 0.0


# -- artifact registration --------------------------------------------------
def test_record_artifact_persists_meta():
    ledger, storage, job = _ledger()
    ledger.record_artifact(
        kind="clip", rel_path="clips/S1.mp4", sha256="a" * 64,
        model=config.MODEL_VIDEO_HERO, qwen_task_id="fake-task-9", cost_usd=0.5,
    )
    rows = storage.artifacts_for_job(job)
    assert len(rows) == 1
    row = rows[0]
    assert row["path"] == "clips/S1.mp4"
    assert row["meta"]["model"] == config.MODEL_VIDEO_HERO
    assert row["meta"]["qwen_task_id"] == "fake-task-9"
    assert row["meta"]["cost_usd"] == 0.5


def test_record_artifact_returns_sha():
    ledger, _, _ = _ledger()
    sha = ledger.record_artifact(kind="k", rel_path="p", sha256="b" * 64)
    assert sha == "b" * 64


def test_record_artifact_defaults_parent_ids_to_empty():
    ledger, storage, job = _ledger()
    ledger.record_artifact(kind="k", rel_path="p", sha256="c" * 64)
    assert storage.artifacts_for_job(job)[0]["meta"]["parent_ids"] == []
