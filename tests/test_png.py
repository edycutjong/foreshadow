"""FakeQwen PNG stubs: real, openable, byte-deterministic, self-describing."""

from __future__ import annotations

from foreshadow.qwen.png import PNG_SIGNATURE, make_png, png_label


def test_make_png_has_signature():
    assert make_png("storyboard:S1").startswith(PNG_SIGNATURE)


def test_make_png_has_ihdr_and_iend():
    data = make_png("x")
    assert b"IHDR" in data and b"IEND" in data and b"IDAT" in data


def test_png_label_roundtrip():
    assert png_label(make_png("storyboard:S4")) == "storyboard:S4"


def test_png_deterministic_for_same_label():
    assert make_png("character_sheet") == make_png("character_sheet")


def test_png_differs_by_label():
    assert make_png("a") != make_png("b")


def test_png_label_absent_returns_none():
    # A PNG with no foreshadow tEXt chunk yields None.
    raw = PNG_SIGNATURE + b"\x00\x00\x00\x00IEND\xaeB`\x82"
    assert png_label(raw) is None


def test_make_png_size_param_changes_bytes():
    assert make_png("x", size=8) != make_png("x", size=16)


def test_png_label_survives_unicode():
    assert png_label(make_png("card:café")) == "card:café"
