"""QC Critic — Qwen surface #6 (qwen3-vl-plus dailies review).

Every rendered clip is judged against its shot's intent: does the frame show
the listed safety elements, is the character consistent with the sheet?
Verdicts are structured output (QCVerdict), validated with one reject-retry.
"""

from __future__ import annotations

from pydantic import ValidationError

from ..qwen.base import CallMeta, QwenTransport
from ..schemas import QCVerdict, Shot
from .screenwriter import StructuredOutputError


def qc_note(verdict: QCVerdict) -> str:
    """The corrective note appended to a re-render prompt."""
    fixes = "; ".join(verdict.issues) if verdict.issues else "match shot intent"
    return f"QC NOTE - must clearly show: {fixes}"


class QCCritic:
    def __init__(self, transport: QwenTransport) -> None:
        self.transport = transport

    def review(self, shot: Shot, clip_prompt: str, frame_png: bytes) -> tuple[QCVerdict, CallMeta]:
        last_error: ValidationError | None = None
        for _ in range(2):
            raw, meta = self.transport.qc_review(shot.model_dump(), clip_prompt, frame_png)
            try:
                return QCVerdict.model_validate(raw), meta
            except ValidationError as exc:
                last_error = exc
        raise StructuredOutputError(f"QCVerdict failed validation twice: {last_error}")
