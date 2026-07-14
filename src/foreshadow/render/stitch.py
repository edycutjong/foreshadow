"""Stitch: assemble the final cut.

Media-honesty rule:
- FakeQwen clips are documented byte stubs, not decodable video, so the fake
  path NEVER shells out to ffmpeg — it writes a deterministic stub film plus
  a documented edit-list artifact (film.edit_list.txt). Byte-identical on
  every machine, with or without ffmpeg.
- The live path uses ffmpeg (concat demuxer + audio mix) when the binary is
  present; when it is absent the stage still succeeds, produces the edit
  list, and is marked "skipped (ffmpeg not installed)". Tests never require
  ffmpeg.

Ken-Burns clips (weight <= 3 shots and QC demotions) derive from the shot's
storyboard frame: ffmpeg zoompan live, deterministic stub offline.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..utils import canonical_json

KENBURNS_STUB_MAGIC = b"FAKEKBRN\x00"
FILM_STUB_MAGIC = b"FSTUBFILM1\x00"


def ffmpeg_path() -> str | None:
    """Detect the ffmpeg binary (None when not installed)."""
    return shutil.which("ffmpeg")


def kenburns_clip_stub(shot_id: str, frame_sha256: str, duration_s: int) -> bytes:
    return KENBURNS_STUB_MAGIC + canonical_json(
        {
            "effect": "kenburns_zoompan",
            "shot_id": shot_id,
            "source_frame_sha256": frame_sha256,
            "duration_s": duration_s,
        }
    )


def card_clip_stub(card_name: str, card_sha256: str, duration_s: int) -> bytes:
    return KENBURNS_STUB_MAGIC + canonical_json(
        {
            "effect": "card_hold",
            "card": card_name,
            "source_card_sha256": card_sha256,
            "duration_s": duration_s,
        }
    )


def film_stub(job_id: str, edit_entries: list[dict], narration_sha256: str) -> bytes:
    return FILM_STUB_MAGIC + canonical_json(
        {
            "job_id": job_id,
            "edit_list": [e["sha256"] for e in edit_entries],
            "narration_sha256": narration_sha256,
        }
    )


def edit_list_text(job_id: str, edit_entries: list[dict], narration: dict) -> str:
    """Documented .txt edit-list artifact: the exact cut, one clip per line."""
    lines = [
        f"# Foreshadow edit list - job {job_id}",
        "# columns: index<TAB>path<TAB>sha256",
        "# audio track: " + f"{narration['path']}\t{narration['sha256']}",
    ]
    for index, entry in enumerate(edit_entries, start=1):
        lines.append(f"{index}\t{entry['path']}\t{entry['sha256']}")
    return "\n".join(lines) + "\n"


def stitch_with_ffmpeg(job_dir: Path, edit_entries: list[dict],
                       narration_path: Path, out_path: Path) -> None:
    """Real concat for live-mode media. Only called when ffmpeg exists AND the
    clips are decodable video (never on FakeQwen stubs)."""
    binary = ffmpeg_path()
    if binary is None:  # pragma: no cover - guarded by caller
        raise RuntimeError("ffmpeg not installed")
    concat_file = job_dir / "concat.txt"
    concat_file.write_text(
        "".join(f"file '{(job_dir / e['path']).resolve()}'\n" for e in edit_entries),
        encoding="utf-8",
    )
    subprocess.run(
        [
            binary, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-i", str(narration_path), "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(out_path),
        ],
        check=True,
        capture_output=True,
    )
