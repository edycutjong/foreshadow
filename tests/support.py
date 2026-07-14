"""Shared test builders. No network, no keys — pure fixture construction.

These helpers let the invariant tests forge *validly signed* manifests with
hand-controlled leaves / edit lists / costs, so each of I1-I4 can be failed in
isolation while the other checks still pass.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from foreshadow import config
from foreshadow.crypto.signing import demo_signing_key
from foreshadow.provenance import build_manifest
from foreshadow.schemas import Manifest, Shot
from foreshadow.storage import SQLiteStorage
from foreshadow.utils import sha256_hex

CACHE_DIR = config.fixtures_dir() / "cache"


def make_shot(
    id: str = "S1",
    scene: int = 1,
    duration_s: int = 5,
    narrative_weight: int = 8,
    action: str = "action text",
    camera: str = "slow push",
    safety_elements: list[str] | None = None,
    vo_line: str = "",
) -> Shot:
    return Shot(
        id=id,
        scene=scene,
        duration_s=duration_s,
        action=action,
        camera=camera,
        narrative_weight=narrative_weight,
        safety_elements=safety_elements or [],
        vo_line=vo_line,
    )


def leaf(
    kind: str,
    path: str,
    *,
    sha: str | None = None,
    task: str = "",
    parents: tuple[str, ...] = (),
    cost: float = 0.0,
    model: str = "",
    prompt: str = "",
    ts: int = 0,
    charge: bool = True,
) -> dict:
    """One artifact/leaf spec. `charge` mirrors a matching ledger row so leaf
    costs reconcile with spent_usd (set False to force an I2 reconcile break)."""
    return {
        "kind": kind,
        "path": path,
        "sha256": sha or sha256_hex(path.encode("utf-8")),
        "qwen_task_id": task,
        "parent_ids": list(parents),
        "cost_usd": cost,
        "model": model,
        "prompt_sha256": prompt,
        "ts": ts,
        "charge": charge,
    }


def build_signed_manifest(
    leaf_specs: list[dict],
    edit_list: list[str],
    qc_rejected: list[str] | None = None,
    *,
    budget_usd: float = 4.0,
    job_id: str = "job-test",
    incident_id: str = "forklift",
    created_ts: int = 0,
) -> tuple[Manifest, SQLiteStorage]:
    """A real, Ed25519-signed manifest built through the production
    `build_manifest` path over an in-memory store."""
    key = demo_signing_key()
    storage = SQLiteStorage(":memory:")
    storage.create_job(job_id, incident_id, budget_usd, "fake", 0)
    for spec in leaf_specs:
        meta = {
            "kind": spec["kind"],
            "model": spec["model"],
            "prompt_sha256": spec["prompt_sha256"],
            "qwen_task_id": spec["qwen_task_id"],
            "parent_ids": list(spec["parent_ids"]),
            "cost_usd": spec["cost_usd"],
            "ts": spec["ts"],
        }
        storage.add_artifact(job_id, spec["kind"], spec["path"], spec["sha256"], meta)
        if spec["cost_usd"] > 0 and spec["charge"]:
            storage.append_ledger(job_id, spec["ts"], spec["kind"], spec["cost_usd"], "")
            storage.add_spend(job_id, spec["cost_usd"])
    manifest = build_manifest(
        storage=storage,
        job_id=job_id,
        incident_id=incident_id,
        budget_usd=budget_usd,
        edit_list=edit_list,
        qc_rejected=qc_rejected or [],
        signing_key=key,
        created_ts=created_ts,
    )
    return manifest, storage


def passing_leaf_set() -> tuple[list[dict], list[str], list[str]]:
    """A minimal internally consistent leaf set that satisfies I1-I3.

    Returns (leaf_specs, edit_list, qc_rejected). The card leaf carries no task
    id of its own but its parent (screenplay) does — exercising the ancestry
    traversal that I1 relies on.
    """
    sp = leaf("screenplay", "screenplay.json", task="fake-task-0001", cost=0.10)
    clip = leaf(
        "clip", "clips/S1_attempt1.mp4",
        task="fake-task-0002", parents=(sp["sha256"],), cost=0.50,
        model=config.MODEL_VIDEO_HERO,
    )
    card = leaf("clip_card", "clips/cards/title.mp4", parents=(sp["sha256"],))
    specs = [sp, clip, card]
    edit_list = [card["sha256"], clip["sha256"]]
    return specs, edit_list, []


def copy_cache(incident: str, dest: Path) -> Path:
    """Copy a committed cache dir to a writable location (for tamper tests)."""
    src = CACHE_DIR / incident
    out = Path(dest) / incident
    shutil.copytree(src, out)
    return out
