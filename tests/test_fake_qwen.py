"""FakeQwen: deterministic, fixture-backed, zero-network transport."""

from __future__ import annotations

import pytest

from foreshadow import config
from foreshadow.qwen.base import ModelNotAllowedError, ensure_allowed
from foreshadow.qwen.fake import (
    MP4_STUB_MAGIC,
    WAV_STUB_MAGIC,
    FakeQwen,
    missing_safety_elements,
    normalize_element,
    simulated_latency_ms,
)
from foreshadow.qwen.png import png_label


def test_name_is_fake():
    assert FakeQwen().name == "fake"


def test_ensure_allowed_accepts_verified_models():
    for m in config.ALLOWED_MODELS:
        assert ensure_allowed(m) == m


def test_ensure_allowed_rejects_unknown():
    with pytest.raises(ModelNotAllowedError):
        ensure_allowed("gpt-4o")


# -- chat surfaces ----------------------------------------------------------
def test_screenplay_returns_fixture_and_max_model():
    fq = FakeQwen()
    data, meta = fq.chat_screenplay("incident text", "forklift")
    assert data["incident_id"] == "forklift"
    assert meta.model == config.MODEL_SCREENPLAY
    assert meta.task_id == "fake-task-0001"


def test_task_ids_are_sequential():
    fq = FakeQwen()
    _, m1 = fq.chat_screenplay("t", "forklift")
    _, m2 = fq.chat_shotplan({"x": 1}, "forklift")
    assert (m1.task_id, m2.task_id) == ("fake-task-0001", "fake-task-0002")


def test_shotplan_returns_fixture():
    data, meta = FakeQwen().chat_shotplan({"title": "T"}, "ladder")
    assert data["incident_id"] == "ladder"
    assert meta.model == config.MODEL_SHOTPLAN


def test_missing_fixture_raises():
    fq = FakeQwen()
    with pytest.raises(FileNotFoundError):
        fq.chat_screenplay("t", "does-not-exist")


def test_alloc_rationale_uses_flash_model():
    text, meta = FakeQwen().chat_alloc_rationale("S1:hero($0.50)")
    assert meta.model == config.MODEL_ALLOC
    assert "Line Producer" in text


def test_alloc_rationale_is_deterministic():
    a, _ = FakeQwen().chat_alloc_rationale("summary")
    b, _ = FakeQwen().chat_alloc_rationale("summary")
    assert a == b


# -- QC critic (mechanistic) ------------------------------------------------
def test_qc_passes_when_all_elements_present():
    shot = {"id": "S1", "safety_elements": ["hard hat", "guard rail"]}
    prompt = "worker in hard hat beside the guard rail"
    verdict, meta = FakeQwen().qc_review(shot, prompt, b"png")
    assert verdict["pass"] is True and verdict["action"] == "accept"
    assert meta.model == config.MODEL_QC


def test_qc_fails_when_element_missing():
    shot = {"id": "S1", "safety_elements": ["hi_vis_vest"]}
    verdict, _ = FakeQwen().qc_review(shot, "a plain worker", b"png")
    assert verdict["pass"] is False
    assert verdict["action"] == "re-render_with_note"
    assert verdict["issues"]


def test_qc_matches_underscore_elements_via_normalization():
    shot = {"id": "S1", "safety_elements": ["blind_corner"]}
    verdict, _ = FakeQwen().qc_review(shot, "forklift at the blind corner", b"png")
    assert verdict["pass"] is True


def test_normalize_element():
    assert normalize_element("Blind_Corner ") == "blind corner"


def test_missing_safety_elements_helper():
    shot = {"safety_elements": ["earbuds", "pedestrian_lane"]}
    missing = missing_safety_elements(shot, "worker with earbuds")
    assert missing == ["pedestrian_lane"]


# -- image ------------------------------------------------------------------
def test_generate_image_returns_labeled_png():
    png, meta = FakeQwen().generate_image("a prompt", kind="storyboard")
    assert meta.model == config.MODEL_IMAGE
    assert png_label(png).startswith("storyboard:")


def test_generate_image_is_deterministic():
    a, _ = FakeQwen().generate_image("p", kind="character_sheet")
    b, _ = FakeQwen().generate_image("p", kind="character_sheet")
    assert a == b


# -- video async lifecycle --------------------------------------------------
def test_video_task_lifecycle_running_then_succeeded():
    fq = FakeQwen()
    task_id = fq.submit_video("prompt", b"frame-png", 5, config.MODEL_VIDEO_HERO)
    status1, blob1, meta1 = fq.poll_video(task_id)
    assert status1 == "RUNNING" and blob1 is None and meta1 is None
    status2, blob2, meta2 = fq.poll_video(task_id)
    assert status2 == "SUCCEEDED"
    assert blob2.startswith(MP4_STUB_MAGIC)
    assert task_id.encode() in blob2
    assert meta2.model == config.MODEL_VIDEO_HERO


def test_submit_video_rejects_unknown_model():
    with pytest.raises(ModelNotAllowedError):
        FakeQwen().submit_video("p", b"png", 5, "sora")


def test_poll_unknown_task_raises():
    with pytest.raises(KeyError):
        FakeQwen().poll_video("fake-task-9999")


def test_connective_model_allowed():
    fq = FakeQwen()
    task_id = fq.submit_video("p", b"png", 4, config.MODEL_VIDEO_CONNECTIVE)
    fq.poll_video(task_id)
    _, _, meta = fq.poll_video(task_id)
    assert meta.model == config.MODEL_VIDEO_CONNECTIVE


# -- tts --------------------------------------------------------------------
def test_tts_returns_wav_stub():
    blob, meta = FakeQwen().tts("narration script")
    assert blob.startswith(WAV_STUB_MAGIC)
    assert meta.model == config.MODEL_TTS


# -- latency simulation -----------------------------------------------------
def test_simulated_latency_deterministic():
    assert simulated_latency_ms("qc", 3) == simulated_latency_ms("qc", 3)


def test_simulated_latency_within_jitter_band():
    base = 4600  # qc base
    for i in range(1, 30):
        ms = simulated_latency_ms("qc", i)
        assert base <= ms < base + base // 4 + 1


def test_simulated_latency_varies_by_counter():
    vals = {simulated_latency_ms("image", i) for i in range(1, 20)}
    assert len(vals) > 1  # jitter actually varies
