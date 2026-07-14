"""Screenwriter agent — Qwen surfaces #1 (chat.completions on qwen3.7-max with
thinking) and #2 (structured-output ShotPlan). Structured outputs are
validated with Pydantic; an invalid payload is rejected and re-requested once
(SPEC.md section 6) before failing the stage.
"""

from __future__ import annotations

from pydantic import ValidationError

from ..qwen.base import CallMeta, QwenTransport
from ..schemas import Screenplay, ShotPlan


class StructuredOutputError(RuntimeError):
    """Structured output failed validation twice (initial + one retry)."""


def _validated(model_cls, fetch, attempts: int = 2):
    last_error: ValidationError | None = None
    for _ in range(attempts):
        raw, meta = fetch()
        try:
            return model_cls.model_validate(raw), meta
        except ValidationError as exc:
            last_error = exc
    raise StructuredOutputError(
        f"{model_cls.__name__} failed validation after {attempts} attempts: {last_error}"
    )


class Screenwriter:
    def __init__(self, transport: QwenTransport) -> None:
        self.transport = transport

    def write(self, incident_text: str, incident_id: str) -> tuple[Screenplay, CallMeta]:
        return _validated(
            Screenplay,
            lambda: self.transport.chat_screenplay(incident_text, incident_id),
        )

    def plan_shots(self, screenplay: Screenplay, incident_id: str) -> tuple[ShotPlan, CallMeta]:
        return _validated(
            ShotPlan,
            lambda: self.transport.chat_shotplan(
                screenplay.model_dump(), incident_id
            ),
        )
