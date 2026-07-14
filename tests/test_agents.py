"""Screenwriter + QCCritic: the reject-retry-once-then-fail contract that
both structured-output agents share (SPEC.md section 6). Each agent gets one
retry after a validation failure; a second consecutive failure raises
StructuredOutputError with both attempts' context preserved."""

from __future__ import annotations

import pytest
from support import make_shot

from foreshadow.agents.qc import QCCritic, qc_note
from foreshadow.agents.screenwriter import Screenwriter, StructuredOutputError
from foreshadow.qwen.base import CallMeta


class _AlwaysInvalidScreenplayTransport:
    """Every chat_screenplay call returns a payload missing required fields."""

    name = "test"

    def __init__(self) -> None:
        self.calls = 0

    def chat_screenplay(self, incident_text: str, incident_id: str):
        self.calls += 1
        meta = CallMeta(model="m", task_id=f"t{self.calls}", latency_ms=0, prompt="p")
        return {"incident_id": incident_id}, meta  # missing title/logline/beats/rule_card


class _AlwaysInvalidShotplanTransport:
    name = "test"

    def __init__(self) -> None:
        self.calls = 0

    def chat_shotplan(self, screenplay: dict, incident_id: str):
        self.calls += 1
        meta = CallMeta(model="m", task_id=f"t{self.calls}", latency_ms=0, prompt="p")
        return {"incident_id": incident_id, "shots": "not-a-list"}, meta


def test_screenwriter_write_raises_after_two_invalid_payloads():
    transport = _AlwaysInvalidScreenplayTransport()
    sw = Screenwriter(transport)
    with pytest.raises(StructuredOutputError, match="Screenplay failed validation after 2"):
        sw.write("an incident narrative", "forklift")
    assert transport.calls == 2  # initial attempt + exactly one retry


def test_screenwriter_plan_shots_raises_after_two_invalid_payloads():
    from foreshadow.schemas import Screenplay

    transport = _AlwaysInvalidShotplanTransport()
    sw = Screenwriter(transport)
    screenplay = Screenplay(
        incident_id="forklift", title="T", logline="L",
        beats=[{"beat": 1, "heading": "h", "description": "d"}], rule_card="R",
    )
    with pytest.raises(StructuredOutputError, match="ShotPlan failed validation after 2"):
        sw.plan_shots(screenplay, "forklift")
    assert transport.calls == 2


class _AlwaysInvalidQCTransport:
    name = "test"

    def __init__(self) -> None:
        self.calls = 0

    def qc_review(self, shot: dict, clip_prompt: str, frame_png: bytes):
        self.calls += 1
        meta = CallMeta(model="m", task_id=f"t{self.calls}", latency_ms=0, prompt=clip_prompt)
        # 'pass' and 'action' are required by QCVerdict; omit both.
        return {"shot_id": shot["id"]}, meta


def test_qc_critic_raises_after_two_invalid_verdicts():
    transport = _AlwaysInvalidQCTransport()
    critic = QCCritic(transport)
    shot = make_shot(id="S1")
    with pytest.raises(Exception) as exc:
        critic.review(shot, "a render prompt", b"\x89PNG")
    assert "QCVerdict failed validation twice" in str(exc.value)
    assert transport.calls == 2


def test_qc_note_falls_back_when_no_issues():
    from foreshadow.schemas import QCVerdict

    verdict = QCVerdict(shot_id="S1", **{"pass": True}, issues=[], action="accept")
    assert qc_note(verdict) == "QC NOTE - must clearly show: match shot intent"


def test_qc_note_joins_issues():
    from foreshadow.schemas import QCVerdict

    verdict = QCVerdict(
        shot_id="S1", **{"pass": False}, issues=["a", "b"], action="re-render_with_note"
    )
    assert qc_note(verdict) == "QC NOTE - must clearly show: a; b"
