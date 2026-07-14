"""Deterministic replay: a fresh offline run is byte-identical to the cache."""

from __future__ import annotations

import pytest

from foreshadow import config
from foreshadow.pipeline.engine import replay, replay_job_id
from foreshadow.provenance import verify_manifest
from foreshadow.schemas import Manifest

CASES = [("forklift", 4.0), ("ladder", 2.0), ("chemical", 4.0)]


def _cache(incident):
    return config.fixtures_dir() / "cache" / incident


@pytest.mark.parametrize("incident,budget", CASES)
def test_replay_matches_committed_cache(incident, budget, tmp_path):
    result, matches = replay(incident, budget, home=tmp_path)
    assert result.status == "published"
    assert matches is True


@pytest.mark.parametrize("incident,budget", CASES)
def test_replay_manifest_is_byte_identical_to_cache(incident, budget, tmp_path):
    result, _ = replay(incident, budget, home=tmp_path)
    fresh = (result.job_dir / "manifest.json").read_bytes()
    cached = (_cache(incident) / "manifest.json").read_bytes()
    assert fresh == cached


@pytest.mark.parametrize("incident,budget", CASES)
def test_replay_root_and_signature_match_cache(incident, budget, tmp_path):
    result, _ = replay(incident, budget, home=tmp_path)
    fresh = Manifest.load(result.job_dir / "manifest.json")
    cached = Manifest.load(_cache(incident) / "manifest.json")
    assert fresh.merkle_root == cached.merkle_root
    assert fresh.signature == cached.signature


@pytest.mark.parametrize("incident,budget", CASES)
def test_replay_output_verifies(incident, budget, tmp_path):
    result, _ = replay(incident, budget, home=tmp_path)
    manifest = Manifest.load(result.job_dir / "manifest.json")
    report = verify_manifest(manifest, base_dir=result.job_dir,
                             film_path=result.job_dir / "film.mp4")
    assert report.ok, [c.name for c in report.checks if not c.passed]


def test_two_replays_are_identical(tmp_path):
    a, _ = replay("forklift", 4.0, home=tmp_path / "a")
    b, _ = replay("forklift", 4.0, home=tmp_path / "b")
    assert (a.job_dir / "manifest.json").read_bytes() == (b.job_dir / "manifest.json").read_bytes()


def test_replay_spent_matches_cache(tmp_path):
    result, _ = replay("forklift", 4.0, home=tmp_path)
    cached = Manifest.load(_cache("forklift") / "manifest.json")
    assert result.spent_usd == cached.spent_usd


def test_replay_job_id_format():
    assert replay_job_id("forklift", 4.0) == "replay-forklift-b4"
    assert replay_job_id("ladder", 2.0) == "replay-ladder-b2"


def test_replay_uses_stable_job_id(tmp_path):
    result, _ = replay("chemical", 4.0, home=tmp_path)
    assert result.job_id == "replay-chemical-b4"
