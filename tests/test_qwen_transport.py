"""qwen/__init__.make_transport branches + LiveQwen's lazy OpenAI client
construction. No network, no real `openai` install (it's an optional `live`
extra not present in the dev venv) -- the lazy import is exercised by
injecting a fake module into sys.modules, which drives the exact same
`from openai import OpenAI` / `OpenAI(...)` statements the real dependency
would."""

from __future__ import annotations

import sys
import types

import pytest

from foreshadow import config
from foreshadow.qwen import FakeQwen, LiveQwen, make_transport


def test_make_transport_fake_returns_fake_qwen():
    t = make_transport("fake")
    assert isinstance(t, FakeQwen)


def test_make_transport_live_returns_live_qwen():
    t = make_transport("live", api_key="test-key-not-real")
    assert isinstance(t, LiveQwen)
    assert t.api_key == "test-key-not-real"


def test_make_transport_unknown_name_raises():
    with pytest.raises(ValueError, match="unknown transport 'bogus'"):
        make_transport("bogus")


def test_live_qwen_client_lazily_imports_and_constructs_openai(monkeypatch):
    """No injected client -> .client() must exercise the lazy `from openai
    import OpenAI` + construction path itself. We stand in for the optional
    `openai` dependency via sys.modules so this runs with zero network and
    without requiring the `[live]` extra to be installed."""
    created: dict[str, str] = {}

    class _FakeOpenAI:
        def __init__(self, api_key: str, base_url: str) -> None:
            created["api_key"] = api_key
            created["base_url"] = base_url

    fake_module = types.ModuleType("openai")
    fake_module.OpenAI = _FakeOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_module)

    q = LiveQwen(api_key="k-live")
    client = q.client()

    assert isinstance(client, _FakeOpenAI)
    assert created == {"api_key": "k-live", "base_url": config.DASHSCOPE_BASE_URL}
    # cached: a second call must not reconstruct the client
    assert q.client() is client
