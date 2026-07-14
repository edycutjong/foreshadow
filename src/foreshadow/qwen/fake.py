"""FakeQwen — deterministic, fixture-backed transport. Zero network, zero keys.

Behavior contract:
- screenplay / shotplan come from committed fixtures (fixtures/qwen/<incident>/)
- "renders" are tiny valid PNGs / documented MP4-stub byte blobs with the
  shot id (via the prompt) embedded — inspectable, hashable, byte-identical
  across machines
- task ids are sequential: fake-task-0001, fake-task-0002, ...
- video tasks follow the real async lifecycle: submit -> RUNNING -> SUCCEEDED
- latency figures are a deterministic simulation (bench labels them as such)
- the QC critic is mechanistic: a clip passes iff every safety element of its
  shot appears (underscores -> spaces, case-insensitive) in the render prompt.
  The chemical seed plants a shot whose first prompt is missing PPE wording,
  so attempt 1 fails and the corrective re-render (note appended) passes —
  the same failure mode qwen3-vl-plus catches live, made reproducible.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import config
from ..utils import canonical_json, sha256_hex
from .base import CallMeta, QwenTransport, ensure_allowed
from .png import make_png

MP4_STUB_MAGIC = b"FAKEMP4\x00"
WAV_STUB_MAGIC = b"FAKEWAV\x00"

_LATENCY_BASE_MS = {
    "chat_screenplay": 6200,
    "chat_shotplan": 2600,
    "chat_alloc": 700,
    "qc": 4600,
    "image": 8400,
    "video:" + config.MODEL_VIDEO_HERO: 96000,
    "video:" + config.MODEL_VIDEO_HERO_FALLBACK: 88000,
    "video:" + config.MODEL_VIDEO_CONNECTIVE: 41000,
    "tts": 3800,
}


def simulated_latency_ms(kind: str, counter: int) -> int:
    """Deterministic latency: base per surface + hash-derived jitter (<=25%)."""
    base = _LATENCY_BASE_MS[kind]
    jitter_span = base // 4
    digest = sha256_hex(f"foreshadow-latency:{kind}:{counter}".encode())
    return base + int(digest[:8], 16) % max(jitter_span, 1)


def normalize_element(element: str) -> str:
    return element.replace("_", " ").strip().lower()


def missing_safety_elements(shot: dict, clip_prompt: str) -> list[str]:
    prompt_norm = clip_prompt.replace("_", " ").lower()
    return [
        e for e in shot.get("safety_elements", [])
        if normalize_element(e) not in prompt_norm
    ]


class FakeQwen(QwenTransport):
    name = "fake"

    def __init__(self, fixtures_dir: Path | None = None) -> None:
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir else config.fixtures_dir() / "qwen"
        self._task_counter = 0
        self._call_counter = 0
        self._video_tasks: dict[str, dict] = {}

    # -- plumbing -------------------------------------------------------------
    def _next_task_id(self) -> str:
        self._task_counter += 1
        return f"fake-task-{self._task_counter:04d}"

    def _meta(self, model: str, kind: str, prompt: str, task_id: str | None = None) -> CallMeta:
        ensure_allowed(model)
        self._call_counter += 1
        return CallMeta(
            model=model,
            task_id=task_id or self._next_task_id(),
            latency_ms=simulated_latency_ms(kind, self._call_counter),
            prompt=prompt,
        )

    def _fixture(self, incident_id: str, name: str) -> dict:
        path = self.fixtures_dir / incident_id / f"{name}.json"
        if not path.exists():
            known = ", ".join(config.INCIDENT_IDS)
            raise FileNotFoundError(
                f"FakeQwen has no committed fixture for incident {incident_id!r} "
                f"({name}.json). The offline transport deterministically replays the "
                f"committed seed incidents ({known}); to script your OWN incident "
                "report, run the live models with --transport live and a "
                f"{config.DASHSCOPE_API_KEY_ENV}."
            )
        return json.loads(path.read_text(encoding="utf-8"))

    # -- chat surfaces ----------------------------------------------------------
    def chat_screenplay(self, incident_text: str, incident_id: str) -> tuple[dict, CallMeta]:
        prompt = screenplay_prompt(incident_text)
        return (
            self._fixture(incident_id, "screenplay"),
            self._meta(config.MODEL_SCREENPLAY, "chat_screenplay", prompt),
        )

    def chat_shotplan(self, screenplay: dict, incident_id: str) -> tuple[dict, CallMeta]:
        prompt = shotplan_prompt(screenplay)
        return (
            self._fixture(incident_id, "shotplan"),
            self._meta(config.MODEL_SHOTPLAN, "chat_shotplan", prompt),
        )

    def chat_alloc_rationale(self, summary: str) -> tuple[str, CallMeta]:
        prompt = alloc_prompt(summary)
        digest = sha256_hex(summary.encode("utf-8"))[:8]
        text = (
            "Line Producer note: allocation follows narrative weight under the "
            f"hard cap; decision digest {digest}."
        )
        return text, self._meta(config.MODEL_ALLOC, "chat_alloc", prompt)

    def qc_review(self, shot: dict, clip_prompt: str, frame_png: bytes) -> tuple[dict, CallMeta]:
        prompt = qc_prompt(shot, clip_prompt)
        missing = missing_safety_elements(shot, clip_prompt)
        if missing:
            verdict = {
                "shot_id": shot["id"],
                "pass": False,
                "issues": [
                    f"safety element not visible in frame: {normalize_element(e)}"
                    for e in missing
                ],
                "action": "re-render_with_note",
            }
        else:
            verdict = {"shot_id": shot["id"], "pass": True, "issues": [], "action": "accept"}
        return verdict, self._meta(config.MODEL_QC, "qc", prompt)

    # -- image ---------------------------------------------------------------
    def generate_image(self, prompt: str, kind: str, batch: bool = False) -> tuple[bytes, CallMeta]:
        meta = self._meta(config.MODEL_IMAGE, "image", prompt)
        return make_png(f"{kind}:{meta.task_id}:{sha256_hex(prompt.encode())[:12]}"), meta

    # -- video async tasks -------------------------------------------------------
    def submit_video(self, prompt: str, image_png: bytes, duration_s: int, model: str) -> str:
        ensure_allowed(model)
        task_id = self._next_task_id()
        self._video_tasks[task_id] = {
            "prompt": prompt,
            "image_sha256": sha256_hex(image_png),
            "duration_s": duration_s,
            "model": model,
            "polls": 0,
        }
        return task_id

    def poll_video(self, task_id: str) -> tuple[str, bytes | None, CallMeta | None]:
        task = self._video_tasks.get(task_id)
        if task is None:
            raise KeyError(f"unknown video task: {task_id}")
        task["polls"] += 1
        if task["polls"] < 2:  # first poll: still rendering (real async shape)
            return "RUNNING", None, None
        payload = {
            "model": task["model"],
            "prompt": task["prompt"],
            "duration_s": task["duration_s"],
            "source_image_sha256": task["image_sha256"],
            "task_id": task_id,
        }
        blob = MP4_STUB_MAGIC + canonical_json(payload)
        self._call_counter += 1
        meta = CallMeta(
            model=task["model"],
            task_id=task_id,
            latency_ms=simulated_latency_ms("video:" + task["model"], self._call_counter),
            prompt=task["prompt"],
        )
        return "SUCCEEDED", blob, meta

    # -- tts --------------------------------------------------------------------
    def tts(self, text: str) -> tuple[bytes, CallMeta]:
        meta = self._meta(config.MODEL_TTS, "tts", text)
        payload = {
            "model": config.MODEL_TTS,
            "text_sha256": sha256_hex(text.encode("utf-8")),
            "chars": len(text),
            "task_id": meta.task_id,
        }
        return WAV_STUB_MAGIC + canonical_json(payload), meta


# -----------------------------------------------------------------------------
# Prompt builders (shared verbatim by LiveQwen so prompt hashes are transport-
# independent for the text surfaces).
# -----------------------------------------------------------------------------
def screenplay_prompt(incident_text: str) -> str:
    return (
        "You are the Screenwriter of a safety-film studio. Turn this OSHA-300-"
        "style incident narrative into a three-beat, 60-90 second screenplay "
        "(setup, incident, corrective) with a closing rule card. Respond as "
        "JSON matching the Screenplay schema.\n\nINCIDENT:\n" + incident_text
    )


def shotplan_prompt(screenplay: dict) -> str:
    return (
        "You are the First AD. Break this screenplay into 6-10 shots. For each "
        "shot give id, scene, duration_s, action, camera, narrative_weight "
        "(1-10), safety_elements, vo_line. Respond as JSON matching the "
        "ShotPlan schema.\n\nSCREENPLAY:\n" + json.dumps(screenplay, sort_keys=True)
    )


def alloc_prompt(summary: str) -> str:
    return (
        "You are the Line Producer. Given this deterministic tier allocation, "
        "write a one-line producer's note.\n\nALLOCATION:\n" + summary
    )


def qc_prompt(shot: dict, clip_prompt: str) -> str:
    return (
        "You are the QC Critic reviewing dailies. Does the rendered clip match "
        "the shot intent, keep the character consistent with the sheet, and "
        "show every listed safety element? Respond as JSON matching the "
        "QCVerdict schema.\n\nSHOT:\n"
        + json.dumps(shot, sort_keys=True)
        + "\n\nRENDER PROMPT:\n"
        + clip_prompt
    )
