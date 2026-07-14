"""Seed incidents: deterministic regen, ground truth, planted QC rejection."""

from __future__ import annotations

from foreshadow import config
from foreshadow.seeds import (
    INCIDENT_TEXTS,
    SWEEP_BUDGETS,
    check_seeds,
    ground_truth,
    main,
    planted_qc_rejections,
    render_seed_files,
    write_seeds,
)


def test_committed_seeds_match_deterministic_regen():
    assert check_seeds() == []


def test_render_seed_files_covers_all_incidents():
    names = set(render_seed_files())
    for inc in config.INCIDENT_IDS:
        assert f"{inc}.txt" in names and f"{inc}.json" in names


def test_incident_texts_present_for_all():
    for inc in config.INCIDENT_IDS:
        assert inc in INCIDENT_TEXTS and "OSHA" in INCIDENT_TEXTS[inc]


def test_sweep_budgets():
    assert SWEEP_BUDGETS == (2.0, 4.0, 8.0)


def test_ground_truth_structure():
    gt = ground_truth("forklift")
    assert gt["incident_id"] == "forklift"
    assert gt["expected_shots"] > 0 and gt["expected_beats"] > 0
    assert set(gt["budgets"]) == {"2", "4", "8"}


def test_ground_truth_budget_sweep_has_quality():
    gt = ground_truth("ladder")
    for b in ("2", "4", "8"):
        assert 0 <= gt["budgets"][b]["quality_pct"] <= 100


def test_planted_qc_rejection_chemical():
    assert planted_qc_rejections("chemical", 4.0) == ["C4"]


def test_no_planted_rejection_forklift():
    assert planted_qc_rejections("forklift", 4.0) == []


def test_write_seeds_is_byte_identical(tmp_path):
    write_seeds(tmp_path)
    assert check_seeds(tmp_path) == []


def test_write_seeds_returns_paths(tmp_path):
    paths = write_seeds(tmp_path)
    assert len(paths) == 6
    assert all(p.exists() for p in paths)


def test_seed_main_check_returns_zero():
    assert main(["--check"]) == 0


def test_check_seeds_reports_every_file_stale_for_an_empty_dest(tmp_path):
    stale = check_seeds(tmp_path)
    expected = {f"{inc}.txt" for inc in config.INCIDENT_IDS} | {
        f"{inc}.json" for inc in config.INCIDENT_IDS
    }
    assert set(stale) == expected


def test_seed_main_regen_writes_files_and_returns_zero(tmp_path):
    rc = main(["--regen", "--dest", str(tmp_path)])
    assert rc == 0
    assert check_seeds(tmp_path) == []


def test_seed_main_check_reports_stale_and_returns_one(tmp_path):
    rc = main(["--check", "--dest", str(tmp_path)])  # empty dest -> everything stale
    assert rc == 1
