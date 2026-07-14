"""Public developer-toolkit surface (COMPLEXITY.md section 4)."""

from __future__ import annotations

import foreshadow
from foreshadow import (
    Allocation,
    BudgetDecision,
    FakeQwen,
    KillSwitchTripped,
    LineProducer,
    LiveQwen,
    Manifest,
    ManifestLeaf,
    ProvenanceLedger,
    QCCritic,
    QCVerdict,
    QwenTransport,
    RegretRow,
    RenderOrchestrator,
    Screenplay,
    Screenwriter,
    Shot,
    ShotPlan,
    VerifyReport,
    config,
    verify_manifest,
)


def test_version_is_declared():
    assert foreshadow.__version__ == "0.1.0"


def test_all_exports_are_importable():
    for name in foreshadow.__all__:
        assert hasattr(foreshadow, name), name


def test_toolkit_core_classes_present():
    for cls in (Screenwriter, LineProducer, RenderOrchestrator, QCCritic,
                ProvenanceLedger, Manifest, FakeQwen, LiveQwen, QwenTransport):
        assert isinstance(cls, type)


def test_schema_classes_exported():
    for cls in (Screenplay, ShotPlan, Shot, Allocation, BudgetDecision,
                RegretRow, QCVerdict, ManifestLeaf):
        assert isinstance(cls, type)


def test_line_producer_allocate_smoke():
    shot = Shot(id="S1", scene=1, duration_s=5, action="a", camera="c", narrative_weight=9)
    alloc = LineProducer(4.0).allocate([shot])
    assert isinstance(alloc, Allocation)
    assert alloc.decisions[0].tier == "hero"


def test_fake_qwen_is_a_transport():
    assert isinstance(FakeQwen(), QwenTransport)
    assert FakeQwen().name == "fake"


def test_manifest_load_and_verify_from_toolkit():
    d = config.fixtures_dir() / "cache" / "forklift"
    manifest = Manifest.load(d / "manifest.json")
    report = verify_manifest(manifest, base_dir=d, film_path=d / "film.mp4")
    assert isinstance(report, VerifyReport)
    assert report.ok


def test_kill_switch_exported():
    assert issubclass(KillSwitchTripped, RuntimeError)
