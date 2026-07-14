"""Qwen transport abstraction.

Two implementations:
- LiveQwen  — OpenAI-SDK client against dashscope-intl compatible-mode
              (chat surfaces) + async-task-style builders for image/video/TTS.
- FakeQwen  — deterministic, fixture-backed, zero-network. Every test and
              the judge-facing replay path runs on FakeQwen.

Each call returns (result, CallMeta). CallMeta carries the model id, the
task/request id (persisted into the provenance manifest), the exact prompt
used (hashed into the manifest leaf) and a latency figure for bench.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .. import config


class ModelNotAllowedError(ValueError):
    """Raised when a model id outside config.ALLOWED_MODELS is requested."""


def ensure_allowed(model: str) -> str:
    if model not in config.ALLOWED_MODELS:
        raise ModelNotAllowedError(
            f"model {model!r} is not in the verified allow-list: "
            f"{sorted(config.ALLOWED_MODELS)}"
        )
    return model


@dataclass(frozen=True)
class CallMeta:
    model: str
    task_id: str
    latency_ms: int
    prompt: str


class QwenTransport(ABC):
    """The eight Qwen surfaces the pipeline consumes (SPONSOR_DEFENSE map)."""

    name: str = "abstract"

    # 1+2: chat.completions on qwen3.7-max (+thinking) / structured output
    @abstractmethod
    def chat_screenplay(self, incident_text: str, incident_id: str) -> tuple[dict, CallMeta]: ...

    @abstractmethod
    def chat_shotplan(self, screenplay: dict, incident_id: str) -> tuple[dict, CallMeta]: ...

    # Line Producer rationale (qwen3.6-flash)
    @abstractmethod
    def chat_alloc_rationale(self, summary: str) -> tuple[str, CallMeta]: ...

    # 6: qwen3-vl-plus dailies QC
    @abstractmethod
    def qc_review(self, shot: dict, clip_prompt: str, frame_png: bytes) -> tuple[dict, CallMeta]: ...

    # 3 (+8 batch): qwen-image-2.0-pro
    @abstractmethod
    def generate_image(self, prompt: str, kind: str, batch: bool = False) -> tuple[bytes, CallMeta]: ...

    # 4+5: wan i2v async tasks (submit / poll)
    @abstractmethod
    def submit_video(self, prompt: str, image_png: bytes, duration_s: int, model: str) -> str: ...

    @abstractmethod
    def poll_video(self, task_id: str) -> tuple[str, bytes | None, CallMeta | None]: ...

    # 7: cosyvoice-v3-plus narration
    @abstractmethod
    def tts(self, text: str) -> tuple[bytes, CallMeta]: ...
