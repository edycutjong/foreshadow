"""Preview animatic — renders a real, playable MP4 from the committed cache.

Skipped automatically if the optional `[preview]` deps are absent; otherwise it
renders a low-fps clip (fast) and asserts the bytes are a genuine MP4 (ISO
`ftyp` box), i.e. something a judge can actually open.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from foreshadow import config
from foreshadow.cli import app

pytest.importorskip("PIL")
pytest.importorskip("imageio")
pytest.importorskip("numpy")

from foreshadow.render import animatic  # noqa: E402

runner = CliRunner()


def _is_mp4(data: bytes) -> bool:
    # ISO base media: bytes 4..8 are the 'ftyp' box type.
    return len(data) > 32 and data[4:8] == b"ftyp"


def test_render_animatic_produces_real_mp4(tmp_path, monkeypatch):
    monkeypatch.setattr(animatic, "FPS", 2)  # keep the render fast
    out = tmp_path / "forklift.mp4"
    cache = config.fixtures_dir() / "cache" / "forklift"
    summary = animatic.render_animatic(cache, out)
    assert out.exists()
    assert summary["shots"] == 8
    assert summary["frames"] > 0
    assert summary["spent_usd"] > 0
    assert _is_mp4(out.read_bytes()), "output is not a decodable MP4 container"


def test_preview_cli_forklift(tmp_path, monkeypatch):
    monkeypatch.setattr(animatic, "FPS", 2)
    out = tmp_path / "cli.mp4"
    result = runner.invoke(app, ["preview", "--incident", "forklift", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "done" in result.output
    assert _is_mp4(out.read_bytes())


def test_preview_cli_unknown_incident_exits_two():
    result = runner.invoke(app, ["preview", "--incident", "nope"])
    assert result.exit_code == 2
    assert "unknown incident" in result.output


def test_preview_cli_missing_cache_exits_two(tmp_path, monkeypatch):
    # Point fixtures at an empty dir -> no committed cache -> actionable exit 2.
    monkeypatch.setattr(config, "fixtures_dir", lambda: tmp_path)
    result = runner.invoke(app, ["preview", "--incident", "forklift"])
    assert result.exit_code == 2
    assert "no committed cache" in result.output


def test_preview_cli_deps_missing_exits_three(monkeypatch):
    from foreshadow.render import animatic as amod

    def _raise(*_a, **_k):
        raise amod.PreviewDepsMissing("pip install '.[preview]'")

    monkeypatch.setattr(amod, "render_animatic", _raise)
    result = runner.invoke(app, ["preview", "--incident", "forklift"])
    assert result.exit_code == 3
    assert "preview" in result.output.lower()


def test_frame_helpers_render_expected_size():
    # the pure drawing helpers produce full-frame 1280x720 images
    assert _size(animatic._title_card("T", "logline here")) == (animatic.W, animatic.H)
    shot = {"id": "S1", "scene": 1, "narrative_weight": 9, "vo_line": "line",
            "action": "does a thing", "camera": "wide", "safety_elements": ["a_b"]}
    assert _size(animatic._shot_frame(shot, 0, 1, zoom=1.05)) == (animatic.W, animatic.H)
    assert _size(animatic._shot_frame(shot, 0, 1, zoom=1.0)) == (animatic.W, animatic.H)
    assert _size(animatic._end_card(2.71, "a" * 64)) == (animatic.W, animatic.H)


def _size(img) -> tuple[int, int]:
    return (img.width, img.height)


def test_font_fallback_when_no_truetype(monkeypatch):
    # No TrueType candidate exists -> load_default() fallback still yields a font.
    monkeypatch.setattr(animatic.Path, "exists", lambda self: False)
    assert animatic._load_font(20) is not None


def test_font_skips_unreadable_truetype(monkeypatch):
    # A candidate that exists but fails to load is skipped, not fatal. Only the
    # file-path candidates raise; load_default()'s internal calls still work.
    from PIL import ImageFont

    orig = ImageFont.truetype
    monkeypatch.setattr(animatic.Path, "exists", lambda self: True)

    def maybe_boom(font=None, size=10, *a, **k):
        if isinstance(font, str):
            raise OSError("corrupt font")
        return orig(font, size, *a, **k)

    monkeypatch.setattr(ImageFont, "truetype", maybe_boom)
    assert animatic._load_font(20) is not None
