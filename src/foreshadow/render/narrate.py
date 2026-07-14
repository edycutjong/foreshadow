"""Narrator — Qwen surface #7 (cosyvoice-v3-plus).

Narration script = the shot VO lines in cut order + the closing rule card.
Cost = chars / 10k * $0.26, charged at actual length.
"""

from __future__ import annotations

from .. import config
from ..qwen.base import CallMeta, QwenTransport
from ..schemas import Screenplay, ShotPlan
from ..utils import usd


def narration_script(screenplay: Screenplay, shotplan: ShotPlan) -> str:
    lines = [shot.vo_line for shot in shotplan.shots if shot.vo_line]
    lines.append(f"Rule card: {screenplay.rule_card}")
    return " ".join(lines)


def narration_cost(script: str) -> float:
    return usd(len(script) / 10_000 * config.COST_TTS_PER_10K_CHARS)


class Narrator:
    def __init__(self, transport: QwenTransport) -> None:
        self.transport = transport

    def narrate(self, script: str) -> tuple[bytes, CallMeta]:
        return self.transport.tts(script)
