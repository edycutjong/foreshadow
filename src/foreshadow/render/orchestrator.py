"""Director of Photography — Qwen surfaces #4 and #5 (wan i2v async tasks).

Hero shots render on wan2.7-i2v (fallback wan2.6-i2v via FORESHADOW_HERO_MODEL
or the constructor); connective tissue on wan2.6-i2v-flash. Renders are
image-conditioned on the shot's storyboard frame (which is itself conditioned
on the character sheet) — consistency by conditioning, not luck.

Async-task shape: submit -> task_id (persisted before the first poll, so a
crash never orphans an unbilled render) -> poll until SUCCEEDED.
"""

from __future__ import annotations

import os

from .. import config
from ..qwen.base import CallMeta, QwenTransport, ensure_allowed
from ..schemas import Shot, Tier


class RenderFailed(RuntimeError):
    pass


def render_prompt(shot: Shot, note: str | None = None) -> str:
    prompt = (
        f"Shot {shot.id}: {shot.action} Camera: {shot.camera}. "
        "Continuity: match the character sheet."
    )
    if note:
        prompt += f" {note}"
    return prompt


class RenderOrchestrator:
    MAX_POLLS = 120

    def __init__(self, transport: QwenTransport, hero_model: str | None = None) -> None:
        self.transport = transport
        self.hero_model = ensure_allowed(
            hero_model
            or os.environ.get("FORESHADOW_HERO_MODEL", config.MODEL_VIDEO_HERO)
        )

    def model_for_tier(self, tier: Tier) -> str:
        if tier == "hero":
            return self.hero_model
        if tier == "connective":
            return config.MODEL_VIDEO_CONNECTIVE
        raise ValueError(f"no video model for tier {tier!r} (kenburns is local)")

    def render_clip(
        self, shot: Shot, tier: Tier, frame_png: bytes, note: str | None = None,
        on_submit=None,
    ) -> tuple[bytes, CallMeta, str]:
        """Returns (clip_bytes, call_meta, prompt). `on_submit(task_id)` fires
        as soon as the async task id exists (persisted to the shot row)."""
        prompt = render_prompt(shot, note)
        model = self.model_for_tier(tier)
        task_id = self.transport.submit_video(prompt, frame_png, shot.duration_s, model)
        if on_submit is not None:
            on_submit(task_id)
        for _ in range(self.MAX_POLLS):
            status, blob, meta = self.transport.poll_video(task_id)
            if status == "SUCCEEDED":
                assert blob is not None and meta is not None
                return blob, meta, prompt
            if status == "FAILED":
                raise RenderFailed(f"video task {task_id} failed for shot {shot.id}")
        raise RenderFailed(f"video task {task_id} did not finish within poll limit")
