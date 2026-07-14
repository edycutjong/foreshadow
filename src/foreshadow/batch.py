"""Batch API fan-out — Qwen surface #8.

Storyboard frames all ship in one batch, which prices each image at
BATCH_DISCOUNT (-50%) of the on-demand rate. The transport receives
batch=True per request; the cost accounting lives with the caller (the
storyboard stage charges COST_IMAGE * BATCH_DISCOUNT per frame).
"""

from __future__ import annotations

from .qwen.base import CallMeta, QwenTransport


def batch_generate_images(
    transport: QwenTransport, requests: list[tuple[str, str, str]]
) -> list[tuple[str, bytes, CallMeta]]:
    """requests: [(key, prompt, kind)] -> [(key, png_bytes, meta)] in order."""
    results: list[tuple[str, bytes, CallMeta]] = []
    for key, prompt, kind in requests:
        png, meta = transport.generate_image(prompt, kind=kind, batch=True)
        results.append((key, png, meta))
    return results
