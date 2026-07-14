"""LiveQwen: offline unit coverage — key policy, payload builders, allow-list.

No network and no DASHSCOPE_API_KEY are ever used: chat surfaces run against an
injected fake client; media surfaces are asserted to raise before any I/O.
"""

from __future__ import annotations

import pytest

from foreshadow import config
from foreshadow.qwen.base import ModelNotAllowedError
from foreshadow.qwen.live import (
    LiveQwen,
    LiveSurfaceNotVerified,
    MissingAPIKeyError,
)


class _FakeChatClient:
    """Records the last create() kwargs; returns a canned completion."""

    def __init__(self, content: str, resp_id: str = "resp-abc"):
        self._content = content
        self._id = resp_id
        self.last_kwargs: dict | None = None
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        message = type("M", (), {"content": self._content})()
        choice = type("C", (), {"message": message})()
        return type("R", (), {"id": self._id, "choices": [choice]})()


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv(config.DASHSCOPE_API_KEY_ENV, raising=False)
    with pytest.raises(MissingAPIKeyError):
        LiveQwen()


def test_api_key_from_argument(monkeypatch):
    monkeypatch.delenv(config.DASHSCOPE_API_KEY_ENV, raising=False)
    q = LiveQwen(api_key="secret", client=_FakeChatClient("{}"))
    assert q.name == "live" and q.api_key == "secret"


def test_api_key_from_env(monkeypatch):
    monkeypatch.setenv(config.DASHSCOPE_API_KEY_ENV, "env-key")
    q = LiveQwen(client=_FakeChatClient("{}"))
    assert q.api_key == "env-key"


def test_chat_screenplay_parses_and_sets_task_id():
    client = _FakeChatClient('{"title": "Blind Corner"}', resp_id="chatcmpl-1")
    q = LiveQwen(api_key="k", client=client)
    data, meta = q.chat_screenplay("incident", "forklift")
    assert data == {"title": "Blind Corner"}
    assert meta.task_id == "chatcmpl-1"
    assert meta.model == config.MODEL_SCREENPLAY


def test_chat_screenplay_enables_thinking():
    client = _FakeChatClient("{}")
    LiveQwen(api_key="k", client=client).chat_screenplay("t", "forklift")
    assert client.last_kwargs["extra_body"] == {"enable_thinking": True}


def test_chat_shotplan_requests_json_schema():
    client = _FakeChatClient('{"shots": []}')
    LiveQwen(api_key="k", client=client).chat_shotplan({"title": "T"}, "forklift")
    rf = client.last_kwargs["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True


def test_chat_alloc_rationale_strips_text():
    client = _FakeChatClient("  producer note  ")
    text, meta = LiveQwen(api_key="k", client=client).chat_alloc_rationale("S1:hero")
    assert text == "producer note"
    assert meta.model == config.MODEL_ALLOC


def test_qc_review_sends_image_content():
    client = _FakeChatClient('{"shot_id": "S1", "pass": true, "action": "accept"}')
    q = LiveQwen(api_key="k", client=client)
    q.qc_review({"id": "S1"}, "clip prompt", b"\x89PNG-bytes")
    content = client.last_kwargs["messages"][0]["content"]
    assert any(part.get("type") == "image_url" for part in content)


# -- media surfaces are payload builders that stop short of firing ----------
def test_generate_image_pending_with_payload():
    q = LiveQwen(api_key="k", client=_FakeChatClient("{}"))
    with pytest.raises(LiveSurfaceNotVerified) as exc:
        q.generate_image("a prompt", kind="storyboard")
    assert exc.value.surface == "generate_image"
    assert exc.value.payload["model"] == config.MODEL_IMAGE


def test_submit_video_pending_with_payload():
    q = LiveQwen(api_key="k", client=_FakeChatClient("{}"))
    with pytest.raises(LiveSurfaceNotVerified) as exc:
        q.submit_video("p", b"png", 5, config.MODEL_VIDEO_HERO)
    assert exc.value.payload["model"] == config.MODEL_VIDEO_HERO
    assert exc.value.payload["headers"]["X-DashScope-Async"] == "enable"


def test_submit_video_rejects_unknown_model():
    q = LiveQwen(api_key="k", client=_FakeChatClient("{}"))
    with pytest.raises(ModelNotAllowedError):
        q.submit_video("p", b"png", 5, "sora")


def test_poll_video_pending():
    q = LiveQwen(api_key="k", client=_FakeChatClient("{}"))
    with pytest.raises(LiveSurfaceNotVerified):
        q.poll_video("task-1")


def test_tts_pending_with_payload():
    q = LiveQwen(api_key="k", client=_FakeChatClient("{}"))
    with pytest.raises(LiveSurfaceNotVerified) as exc:
        q.tts("narration")
    assert exc.value.payload["model"] == config.MODEL_TTS
