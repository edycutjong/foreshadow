"""Animatic: render a *real, playable* MP4 from the deterministic pipeline output.

Honesty rule (read this before touching it):
- This is NOT AI-generated video. FakeQwen never calls `wan`, so there is no
  generated footage. This module builds an **offline storyboard animatic** —
  title cards per shot, driven entirely by the committed, deterministic
  `shotplan.json` / `screenplay.json` (the same data the signed manifest
  covers). Every frame is drawn from that text with Pillow and encoded to
  H.264 with imageio-ffmpeg. It exists so a judge has *something watchable*;
  it is clearly stamped as an animatic, not as a rendered film.
- It is deliberately separate from `stitch.py` and the byte-identical replay
  path. Encoding output is not byte-stable across ffmpeg builds, so it is
  never hashed into the manifest and never asserted in the determinism tests.

Deps (`foreshadow-pipeline[preview]`): pillow, imageio, imageio-ffmpeg. They are
imported lazily so the offline core stays dependency-light and keyless.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..utils import read_json

W, H = 1280, 720
FPS = 24
BG = (11, 13, 18)          # matte war-room black
FG = (233, 236, 241)
DIM = (150, 158, 170)
ACCENT = (245, 158, 11)    # foreshadow amber
VIOLET = (139, 92, 246)


class PreviewDepsMissing(RuntimeError):
    pass


def _load_font(size: int, bold: bool = False) -> Any:
    from PIL import ImageFont

    # Prefer a real TrueType face; fall back to Pillow's bitmap default.
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _wrap(draw: Any, text: str, font: Any, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _gradient_base() -> Any:
    from PIL import Image

    img = Image.new("RGB", (W, H), BG)
    px = img.load()
    assert px is not None
    for y in range(H):
        # subtle top-lit vignette
        t = 1.0 - (y / H) * 0.35
        r = int(BG[0] * t + 6)
        g = int(BG[1] * t + 7)
        b = int(BG[2] * t + 10)
        for x in range(0, W, 2):
            px[x, y] = (r, g, b)
            px[x + 1, y] = (r, g, b)
    return img


def _title_card(title: str, logline: str) -> Any:
    from PIL import ImageDraw

    img = _gradient_base()
    d = ImageDraw.Draw(img)
    d.text((90, 150), "FORESHADOW", font=_load_font(34, bold=True), fill=ACCENT)
    d.text((90, 210), title, font=_load_font(88, bold=True), fill=FG)
    for i, line in enumerate(_wrap(d, logline, _load_font(30), W - 180)):
        d.text((90, 340 + i * 42), line, font=_load_font(30), fill=DIM)
    d.text((90, H - 90),
           "offline storyboard animatic  ·  FakeQwen  ·  no wan video generated",
           font=_load_font(22), fill=(90, 96, 108))
    return img


def _shot_frame(shot: dict, idx: int, total: int, zoom: float) -> Any:
    from PIL import Image, ImageDraw

    base = _gradient_base()
    d = ImageDraw.Draw(base)

    # top strip: scene / shot id / progress
    sid = shot.get("id", f"S{idx + 1}")
    d.text((90, 70),
           f"SCENE {shot.get('scene', 1)}   ·   SHOT {sid}   ·   {idx + 1}/{total}",
           font=_load_font(24, bold=True), fill=ACCENT)
    d.text((W - 260, 70), f"weight {shot.get('narrative_weight', '-')}",
           font=_load_font(22), fill=DIM)

    # the money: the VO line, big and centered
    vo = shot.get("vo_line") or ""
    vo_font = _load_font(52, bold=True)
    vo_lines = _wrap(d, f"“{vo}”", vo_font, W - 220)
    y = 250
    for line in vo_lines:
        w = d.textlength(line, font=vo_font)
        d.text(((W - w) / 2, y), line, font=vo_font, fill=FG)
        y += 66

    # the action description
    y += 20
    act_font = _load_font(28)
    for line in _wrap(d, shot.get("action", ""), act_font, W - 260):
        w = d.textlength(line, font=act_font)
        d.text(((W - w) / 2, y), line, font=act_font, fill=DIM)
        y += 38

    # bottom: camera + safety-element chips
    d.text((90, H - 120), f"CAMERA  ·  {shot.get('camera', '')}",
           font=_load_font(24), fill=(120, 200, 255))
    chip_x = 90
    for el in shot.get("safety_elements", []):
        label = el.replace("_", " ")
        cf = _load_font(20)
        tw = d.textlength(label, font=cf)
        d.rounded_rectangle((chip_x, H - 70, chip_x + tw + 28, H - 36),
                            radius=16, outline=VIOLET, width=2)
        d.text((chip_x + 14, H - 64), label, font=cf, fill=(200, 190, 255))
        chip_x += int(tw) + 44

    # gentle Ken-Burns: crop-zoom the composed frame
    if zoom > 1.0:
        cw, ch = int(W / zoom), int(H / zoom)
        left, top = (W - cw) // 2, (H - ch) // 2
        base = base.crop((left, top, left + cw, top + ch)).resize(
            (W, H), Image.Resampling.LANCZOS)
    return base


def _end_card(spent: float, merkle_root: str) -> Any:
    from PIL import ImageDraw

    img = _gradient_base()
    d = ImageDraw.Draw(img)
    big = _load_font(96, bold=True)
    line = f"${spent:,.2f}"
    w = d.textlength(line, font=big)
    d.text(((W - w) / 2, 190), line, font=big, fill=ACCENT)
    sub = "this safety film  ·  vs $5,000–$15,000 and 6–8 weeks the old way"
    sf = _load_font(28)
    w = d.textlength(sub, font=sf)
    d.text(((W - w) / 2, 320), sub, font=sf, fill=FG)
    prov = f"Ed25519-signed  ·  merkle {merkle_root[:16]}…  ·  verify offline, zero keys"
    pf = _load_font(22)
    w = d.textlength(prov, font=pf)
    d.text(((W - w) / 2, 400), prov, font=pf, fill=DIM)
    return img


def render_animatic(cache_dir: Path, out_path: Path) -> dict:
    """Render a real, playable MP4 animatic from a committed incident cache.

    Returns a small summary dict (frames, seconds, out path). Raises
    PreviewDepsMissing with an actionable message if optional deps are absent.
    """
    try:
        import imageio.v2 as imageio  # noqa: F401
        import numpy as np
        from PIL import Image  # noqa: F401
    except ImportError as exc:  # pragma: no cover - dep guard
        raise PreviewDepsMissing(
            "The animatic preview needs optional deps: "
            "pip install 'foreshadow-pipeline[preview]'  "
            f"(missing: {exc.name})"
        ) from exc

    shotplan = read_json(cache_dir / "shotplan.json")
    screenplay = read_json(cache_dir / "screenplay.json")
    ledger_path = cache_dir / "ledger.json"
    manifest_path = cache_dir / "manifest.json"
    spent = 0.0
    if ledger_path.exists():
        spent = round(sum(r.get("cost_usd", 0.0) for r in read_json(ledger_path)["rows"]), 4)
    merkle_root = ""
    if manifest_path.exists():
        merkle_root = str(read_json(manifest_path).get("merkle_root", ""))

    shots = shotplan["shots"]
    title = screenplay.get("title", shotplan.get("incident_id", "Untitled"))
    logline = screenplay.get("logline", "")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio.get_writer(
        str(out_path), fps=FPS, codec="libx264",
        format="FFMPEG", pixelformat="yuv420p", macro_block_size=None,  # type: ignore[arg-type]
        output_params=["-crf", "20", "-preset", "medium"],
    )
    frames_written = 0
    try:
        # 2.5s title card
        title_img = np.asarray(_title_card(title, logline))
        for _ in range(int(FPS * 2.5)):
            writer.append_data(title_img)
            frames_written += 1
        # each shot held for its duration, with a slow Ken-Burns push
        for idx, shot in enumerate(shots):
            dur = max(2, int(shot.get("duration_s", 3)))
            n = FPS * dur
            for f in range(n):
                zoom = 1.0 + 0.06 * (f / max(1, n - 1))  # 1.00 -> 1.06
                writer.append_data(np.asarray(_shot_frame(shot, idx, len(shots), zoom)))
                frames_written += 1
        # 3s end card
        end_img = np.asarray(_end_card(spent, merkle_root))
        for _ in range(int(FPS * 3)):
            writer.append_data(end_img)
            frames_written += 1
    finally:
        writer.close()

    return {
        "out": str(out_path),
        "frames": frames_written,
        "seconds": round(frames_written / FPS, 1),
        "shots": len(shots),
        "spent_usd": spent,
    }
