"""Deterministic primitives: canonical JSON, hashing, USD discipline, clocks."""

from __future__ import annotations

import pytest

from foreshadow.utils import (
    Clock,
    FixedClock,
    SystemClock,
    atomic_write_bytes,
    atomic_write_text,
    canonical_json,
    iso_ts,
    read_json,
    sha256_file,
    sha256_hex,
    stable_ints,
    usd,
    write_json,
)


def test_canonical_json_sorts_keys():
    assert canonical_json({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_canonical_json_compact_separators():
    assert b", " not in canonical_json({"a": 1, "b": 2})
    assert b": " not in canonical_json({"a": 1})


def test_canonical_json_is_bytes():
    assert isinstance(canonical_json({"x": 1}), bytes)


def test_canonical_json_preserves_non_ascii():
    out = canonical_json({"k": "café—π"})
    assert "café—π".encode() in out


def test_canonical_json_order_independent():
    a = canonical_json({"a": 1, "b": {"d": 4, "c": 3}})
    b = canonical_json({"b": {"c": 3, "d": 4}, "a": 1})
    assert a == b


def test_canonical_json_list_order_significant():
    assert canonical_json([1, 2, 3]) != canonical_json([3, 2, 1])


def test_sha256_hex_known_vector():
    assert sha256_hex(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_sha256_hex_len():
    assert len(sha256_hex(b"anything")) == 64


def test_sha256_file_matches_hex(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello world")
    assert sha256_file(p) == sha256_hex(b"hello world")


def test_sha256_file_large(tmp_path):
    data = b"x" * (65536 * 3 + 7)  # spans multiple read chunks
    p = tmp_path / "big.bin"
    p.write_bytes(data)
    assert sha256_file(p) == sha256_hex(data)


@pytest.mark.parametrize(
    "raw,expected",
    [(0.1 + 0.2, 0.3), (1 / 3, 0.333333), (2.0, 2.0), (0.0000004, 0.0)],
)
def test_usd_rounds_to_six_places(raw, expected):
    assert usd(raw) == expected


def test_usd_returns_float():
    assert isinstance(usd(3), float)


def test_atomic_write_bytes_roundtrip(tmp_path):
    p = tmp_path / "sub" / "a.bin"
    atomic_write_bytes(p, b"data")
    assert p.read_bytes() == b"data"


def test_atomic_write_leaves_no_tmp(tmp_path):
    p = tmp_path / "a.bin"
    atomic_write_bytes(p, b"data")
    assert not (tmp_path / "a.bin.tmp").exists()


def test_atomic_write_text_roundtrip(tmp_path):
    p = tmp_path / "a.txt"
    atomic_write_text(p, "héllo")
    assert p.read_text(encoding="utf-8") == "héllo"


def test_write_json_returns_canonical_bytes(tmp_path):
    p = tmp_path / "a.json"
    data = write_json(p, {"b": 1, "a": 2})
    assert data == b'{"a":2,"b":1}'
    assert p.read_bytes() == data


def test_read_json_roundtrip(tmp_path):
    p = tmp_path / "a.json"
    write_json(p, {"a": [1, 2, 3]})
    assert read_json(p) == {"a": [1, 2, 3]}


def test_fixed_clock_advances_one_per_call():
    c = FixedClock(start=100, step=1)
    assert [c.now(), c.now(), c.now()] == [100, 101, 102]


def test_fixed_clock_custom_step():
    c = FixedClock(start=0, step=5)
    assert [c.now(), c.now()] == [0, 5]


def test_fixed_clock_default_start_is_2026():
    assert FixedClock.DEFAULT_START == 1767225600


def test_fixed_clock_deterministic_across_instances():
    a = FixedClock()
    b = FixedClock()
    assert [a.now(), a.now(), a.now()] == [b.now(), b.now(), b.now()]


def test_system_clock_is_monotonic_ish():
    now = SystemClock().now()
    assert isinstance(now, int) and now > 1_600_000_000


def test_clock_base_class_not_implemented():
    with pytest.raises(NotImplementedError):
        Clock().now()


def test_stable_ints_deterministic():
    a = [x for _, x in zip(range(5), stable_ints("seed"), strict=False)]
    b = [x for _, x in zip(range(5), stable_ints("seed"), strict=False)]
    assert a == b


def test_stable_ints_seed_sensitive():
    a = next(iter(stable_ints("seed-a")))
    b = next(iter(stable_ints("seed-b")))
    assert a != b


def test_stable_ints_are_uint32():
    for _, val in zip(range(10), stable_ints("s"), strict=False):
        assert 0 <= val < 2**32


def test_iso_ts_formats_utc():
    assert iso_ts(1767225600) == "2026-01-01T00:00:00Z"
