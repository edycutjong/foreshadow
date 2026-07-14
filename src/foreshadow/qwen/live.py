"""LiveQwen — real transport against Qwen Cloud (dashscope-intl).

Chat surfaces (screenplay / shot plan / alloc rationale / VL QC) are fully
implemented on the OpenAI SDK compatible-mode endpoint. Image, video and TTS
are async-task-style builders: they construct the documented DashScope task
payloads but raise LiveSurfaceNotVerified instead of firing — live media
generation is intentionally out of scope for the offline-first build (see
README "Status / Pending"). Tests exercise payload construction and the
model allow-list without any network.
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any

from .. import config
from .base import CallMeta, QwenTransport, ensure_allowed
from .fake import alloc_prompt, qc_prompt, screenplay_prompt, shotplan_prompt


class MissingAPIKeyError(RuntimeError):
    pass


class LiveSurfaceNotVerified(NotImplementedError):
    """Raised by media surfaces pending live verification; carries the exact
    request payload that would be sent, for inspection and tests."""

    def __init__(self, surface: str, payload: dict[str, Any]) -> None:
        super().__init__(
            f"LiveQwen.{surface} is pending live verification (offline-first "
            "build). See README 'Status / Pending'."
        )
        self.surface = surface
        self.payload = payload


class LiveQwen(QwenTransport):
    name = "live"

    def __init__(self, api_key: str | None = None, client: Any = None) -> None:
        self.api_key = api_key or os.environ.get(config.DASHSCOPE_API_KEY_ENV, "")
        if not self.api_key:
            raise MissingAPIKeyError(
                f"LiveQwen requires the {config.DASHSCOPE_API_KEY_ENV} environment "
                "variable (or api_key=). Use --transport fake for the offline demo."
            )
        self._client = client  # injectable for tests
        self._task_counter = 0

    # -- plumbing ------------------------------------------------------------
    def client(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI  # lazy: only the live path needs it
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "LiveQwen needs the openai SDK: pip install 'foreshadow-pipeline[live]'"
                ) from exc
            self._client = OpenAI(api_key=self.api_key, base_url=config.DASHSCOPE_BASE_URL)
        return self._client

    def _chat(self, model: str, prompt: str, *, kind: str,
              json_schema: dict | None = None, thinking: bool = False,
              image_png: bytes | None = None) -> tuple[str, CallMeta]:
        ensure_allowed(model)
        content: Any = prompt
        if image_png is not None:
            data_url = "data:image/png;base64," + base64.b64encode(image_png).decode()
            content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
        }
        if json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": kind, "schema": json_schema, "strict": True},
            }
        if thinking:
            kwargs["extra_body"] = {"enable_thinking": True}
        start = time.monotonic()
        response = self.client().chat.completions.create(**kwargs)
        latency_ms = int((time.monotonic() - start) * 1000)
        text = response.choices[0].message.content or ""
        meta = CallMeta(
            model=model,
            task_id=getattr(response, "id", "") or "",
            latency_ms=latency_ms,
            prompt=prompt,
        )
        return text, meta

    @staticmethod
    def _parse_json(text: str) -> dict:
        return json.loads(text)

    # -- chat surfaces ------------------------------------------------------------
    def chat_screenplay(self, incident_text: str, incident_id: str) -> tuple[dict, CallMeta]:
        from ..schemas import Screenplay

        text, meta = self._chat(
            config.MODEL_SCREENPLAY,
            screenplay_prompt(incident_text),
            kind="screenplay",
            json_schema=Screenplay.model_json_schema(),
            thinking=True,
        )
        return self._parse_json(text), meta

    def chat_shotplan(self, screenplay: dict, incident_id: str) -> tuple[dict, CallMeta]:
        from ..schemas import ShotPlan

        text, meta = self._chat(
            config.MODEL_SHOTPLAN,
            shotplan_prompt(screenplay),
            kind="shotplan",
            json_schema=ShotPlan.model_json_schema(),
        )
        return self._parse_json(text), meta

    def chat_alloc_rationale(self, summary: str) -> tuple[str, CallMeta]:
        text, meta = self._chat(config.MODEL_ALLOC, alloc_prompt(summary), kind="alloc")
        return text.strip(), meta

    def qc_review(self, shot: dict, clip_prompt: str, frame_png: bytes) -> tuple[dict, CallMeta]:
        from ..schemas import QCVerdict

        text, meta = self._chat(
            config.MODEL_QC,
            qc_prompt(shot, clip_prompt),
            kind="qc",
            json_schema=QCVerdict.model_json_schema(),
            image_png=frame_png,
        )
        return self._parse_json(text), meta

    # -- async-task-style media surfaces (payload builders; pending live) ---------
    def generate_image(self, prompt: str, kind: str, batch: bool = False) -> tuple[bytes, CallMeta]:
        ensure_allowed(config.MODEL_IMAGE)
        payload = {
            "model": config.MODEL_IMAGE,
            "input": {"prompt": prompt},
            "parameters": {"size": "1280*720", "n": 1},
            "batch": batch,
        }
        raise LiveSurfaceNotVerified("generate_image", payload)

    def submit_video(self, prompt: str, image_png: bytes, duration_s: int, model: str) -> str:
        ensure_allowed(model)
        payload = {
            "model": model,
            "input": {
                "prompt": prompt,
                "img_base64": base64.b64encode(image_png).decode(),
            },
            "parameters": {"duration": duration_s, "resolution": "720P"},
            "headers": {"X-DashScope-Async": "enable"},
        }
        raise LiveSurfaceNotVerified("submit_video", payload)

    def poll_video(self, task_id: str) -> tuple[str, bytes | None, CallMeta | None]:
        payload = {"task_id": task_id, "endpoint": "GET /api/v1/tasks/{task_id}"}
        raise LiveSurfaceNotVerified("poll_video", payload)

    def tts(self, text: str) -> tuple[bytes, CallMeta]:
        ensure_allowed(config.MODEL_TTS)
        payload = {
            "model": config.MODEL_TTS,
            "input": {"text": text},
            "parameters": {"voice": "longhua_v2", "format": "wav"},
        }
        raise LiveSurfaceNotVerified("tts", payload)
