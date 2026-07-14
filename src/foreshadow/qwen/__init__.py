from .base import CallMeta, ModelNotAllowedError, QwenTransport, ensure_allowed
from .fake import FakeQwen
from .live import LiveQwen, LiveSurfaceNotVerified, MissingAPIKeyError

__all__ = [
    "CallMeta",
    "QwenTransport",
    "ModelNotAllowedError",
    "ensure_allowed",
    "FakeQwen",
    "LiveQwen",
    "LiveSurfaceNotVerified",
    "MissingAPIKeyError",
]


def make_transport(name: str, **kwargs):
    if name == "fake":
        return FakeQwen(**kwargs)
    if name == "live":
        return LiveQwen(**kwargs)
    raise ValueError(f"unknown transport {name!r} (expected 'fake' or 'live')")
