"""Art Department — Qwen surface #3 (qwen-image-2.0-pro).

One character sheet anchors identity across every storyboard frame and every
image-conditioned render; storyboards fan out through the Batch API helper
(surface #8, -50%).
"""

from __future__ import annotations

from ..batch import batch_generate_images
from ..qwen.base import CallMeta, QwenTransport
from ..schemas import Screenplay, Shot


def character_sheet_prompt(screenplay: Screenplay) -> str:
    return (
        "Character reference sheet, front/profile/three-quarter, consistent "
        "wardrobe with hi-vis PPE where the story requires it. Film: "
        f"{screenplay.title}. Logline: {screenplay.logline} "
        "Grounded industrial-cinema look, neutral background."
    )


def storyboard_prompt(shot: Shot) -> str:
    return (
        f"Storyboard frame for shot {shot.id}: {shot.action} "
        f"Camera: {shot.camera}. Match the character sheet exactly. "
        "Cinematic key art, 16:9."
    )


class ArtDept:
    def __init__(self, transport: QwenTransport) -> None:
        self.transport = transport

    def character_sheet(self, screenplay: Screenplay) -> tuple[bytes, CallMeta]:
        return self.transport.generate_image(
            character_sheet_prompt(screenplay), kind="character_sheet", batch=False
        )

    def storyboard_frames(self, shots: list[Shot]) -> list[tuple[str, bytes, CallMeta]]:
        requests = [(shot.id, storyboard_prompt(shot), "storyboard") for shot in shots]
        return batch_generate_images(self.transport, requests)
