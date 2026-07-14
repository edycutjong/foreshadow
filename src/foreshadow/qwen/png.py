"""Minimal valid PNG generator (pure stdlib) for FakeQwen "renders".

Produces a real, openable grayscale PNG whose pixel bytes are derived from a
seed string, with the seed (e.g. "storyboard:S4") embedded in a tEXt chunk —
so the placeholder is inspectable AND byte-deterministic.
"""

from __future__ import annotations

import hashlib
import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def make_png(label: str, size: int = 8) -> bytes:
    """Tiny grayscale PNG; pixels seeded by `label`, label stored in tEXt."""
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0)  # 8-bit grayscale
    seed = hashlib.sha256(label.encode("utf-8")).digest()
    raw = b""
    for y in range(size):
        row = bytes((seed[(x + y * size) % len(seed)]) for x in range(size))
        raw += b"\x00" + row  # filter type 0 per scanline
    text = b"foreshadow\x00" + label.encode("utf-8")
    return (
        PNG_SIGNATURE
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"tEXt", text)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def png_label(data: bytes) -> str | None:
    """Read back the embedded label (used by tests)."""
    offset = len(PNG_SIGNATURE)
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        if kind == b"tEXt" and payload.startswith(b"foreshadow\x00"):
            return payload.split(b"\x00", 1)[1].decode("utf-8")
        offset += 12 + length
    return None
