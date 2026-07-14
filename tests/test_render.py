"""RenderOrchestrator failure paths + the real-ffmpeg concat path in
render/stitch.py. FakeQwen-backed pipeline tests never exercise the async
poll FAILED/timeout branches or the live ffmpeg concat (clip stubs aren't
decodable video) -- these are direct, transport-free unit tests instead."""

from __future__ import annotations

import shutil
import subprocess

import pytest
from support import make_shot

from foreshadow.render.orchestrator import RenderFailed, RenderOrchestrator
from foreshadow.render.stitch import ffmpeg_path, stitch_with_ffmpeg


class _SubmitOnlyTransport:
    """A transport whose submit/poll behavior is fully test-controlled."""

    name = "test"

    def __init__(self, poll_result: tuple[str, bytes | None, object]) -> None:
        self._poll_result = poll_result
        self.submitted: list[str] = []

    def submit_video(self, prompt, image_png, duration_s, model):
        task_id = f"task-{len(self.submitted)}"
        self.submitted.append(task_id)
        return task_id

    def poll_video(self, task_id):
        return self._poll_result


def test_model_for_tier_rejects_kenburns():
    orch = RenderOrchestrator(_SubmitOnlyTransport(("RUNNING", None, None)))
    with pytest.raises(ValueError, match="no video model for tier 'kenburns'"):
        orch.model_for_tier("kenburns")


def test_render_clip_raises_render_failed_on_failed_status():
    transport = _SubmitOnlyTransport(("FAILED", None, None))
    orch = RenderOrchestrator(transport)
    shot = make_shot(id="S1", duration_s=3)
    with pytest.raises(RenderFailed, match="video task task-0 failed for shot S1"):
        orch.render_clip(shot, "hero", b"\x89PNG")


def test_render_clip_raises_render_failed_when_poll_limit_exceeded():
    transport = _SubmitOnlyTransport(("RUNNING", None, None))
    orch = RenderOrchestrator(transport)
    orch.MAX_POLLS = 3  # keep the test fast; real default is 120
    shot = make_shot(id="S2", duration_s=3)
    with pytest.raises(RenderFailed, match="did not finish within poll limit"):
        orch.render_clip(shot, "connective", b"\x89PNG")


def test_ffmpeg_path_matches_shutil_which():
    assert ffmpeg_path() == shutil.which("ffmpeg")


FFMPEG = shutil.which("ffmpeg")


@pytest.mark.skipif(
    FFMPEG is None,
    reason="requires the ffmpeg binary; the offline FakeQwen pipeline never needs it",
)
def test_stitch_with_ffmpeg_concats_real_clips_and_mixes_audio(tmp_path):
    """Exercises the real live-mode concat path with genuine decodable media
    (never used by the FakeQwen stub pipeline, which always writes byte
    stubs and skips ffmpeg entirely)."""
    clip_a = tmp_path / "a.mp4"
    clip_b = tmp_path / "b.mp4"
    narration = tmp_path / "narration.wav"
    out = tmp_path / "film.mp4"

    for clip, color in ((clip_a, "red"), (clip_b, "blue")):
        subprocess.run(
            [FFMPEG, "-y", "-f", "lavfi", "-i", f"color=c={color}:s=64x64:d=1",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
            check=True, capture_output=True,
        )
    subprocess.run(
        [FFMPEG, "-y", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", "1",
         "-c:a", "pcm_s16le", str(narration)],
        check=True, capture_output=True,
    )

    edit_entries = [{"path": "a.mp4", "sha256": "x"}, {"path": "b.mp4", "sha256": "y"}]
    stitch_with_ffmpeg(tmp_path, edit_entries, narration, out)

    assert out.exists() and out.stat().st_size > 0
    assert (tmp_path / "concat.txt").exists()
