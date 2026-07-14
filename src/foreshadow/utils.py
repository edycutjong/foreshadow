"""Deterministic primitives shared across the pipeline.

Canonical JSON here is THE canonical form for everything that gets hashed or
signed (manifest leaves, signed payloads). Rules (see docs/SPEC-PROVENANCE.md):
UTF-8, sorted keys, compact separators, non-ASCII preserved.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def canonical_json(obj: Any) -> bytes:
    """Stable byte serialization used for hashing and signing."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def usd(x: float) -> float:
    """Normalize a USD amount to 6 decimal places (float discipline)."""
    return round(float(x), 6)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write via tmp+rename so a crashed stage never leaves a torn artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def write_json(path: Path, obj: Any) -> bytes:
    """Write canonical JSON (pretty variant would break byte determinism)."""
    data = canonical_json(obj)
    atomic_write_bytes(path, data)
    return data


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def iso_ts(epoch_s: int) -> str:
    return datetime.fromtimestamp(epoch_s, tz=UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


class Clock:
    """Monotonic per-job clock. SystemClock in live mode; FixedClock for
    deterministic replay (every timestamp is a pure function of tick order)."""

    def now(self) -> int:  # pragma: no cover - interface
        raise NotImplementedError


class SystemClock(Clock):
    def now(self) -> int:
        import time

        return int(time.time())


class FixedClock(Clock):
    """Starts at a fixed epoch and advances 1s per call — replayable time."""

    #: 2026-01-01T00:00:00Z
    DEFAULT_START = 1767225600

    def __init__(self, start: int = DEFAULT_START, step: int = 1) -> None:
        self._next = start
        self._step = step

    def now(self) -> int:
        value = self._next
        self._next += self._step
        return value


def stable_ints(seed: str) -> Iterator[int]:
    """Infinite deterministic integer stream derived from a seed string."""
    counter = 0
    while True:
        digest = hashlib.sha256(f"{seed}:{counter}".encode()).digest()
        yield int.from_bytes(digest[:4], "big")
        counter += 1
