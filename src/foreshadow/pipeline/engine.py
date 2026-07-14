"""Pipeline engine: job context, resumable stage runner, deterministic replay.

Idempotency contract: a stage marked `done` is never re-executed for the same
job_id — re-running a job resumes at the first non-done stage. Determinism
contract (fake transport): FixedClock + demo keys + fixture-backed FakeQwen
make a fresh run of the same (incident, budget) byte-identical, manifest
signature included.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nacl.public import PrivateKey
from nacl.signing import SigningKey

from .. import config
from ..crypto.sealing import demo_worker_key, load_or_create_worker_key
from ..crypto.signing import demo_signing_key, load_or_create_signing_key
from ..provenance import KillSwitchTripped, ProvenanceLedger
from ..qwen import QwenTransport, make_transport
from ..storage import SQLiteStorage
from ..utils import Clock, FixedClock, SystemClock, read_json, usd
from .stages import STAGE_ORDER, STAGES

MIN_BUDGET_USD = 1.0


@dataclass
class JobContext:
    job_id: str
    incident_id: str
    budget_usd: float
    storage: SQLiteStorage
    transport: QwenTransport
    clock: Clock
    ledger: ProvenanceLedger
    home: Path
    job_dir: Path
    worker_key: PrivateKey
    signing_key: SigningKey
    deterministic: bool
    incident_file: Path | None = None


@dataclass
class JobResult:
    job_id: str
    status: str
    job_dir: Path
    spent_usd: float
    merkle_root: str | None
    manifest_path: Path | None
    stages: list[dict]


def default_home() -> Path:
    return config.home_dir()


def create_context(
    incident_id: str,
    budget_usd: float = config.DEFAULT_BUDGET_USD,
    transport: str | QwenTransport = "fake",
    job_id: str | None = None,
    home: Path | None = None,
    incident_file: Path | None = None,
) -> JobContext:
    if budget_usd < MIN_BUDGET_USD:
        raise ValueError(
            f"budget ${budget_usd:.2f} is below the ${MIN_BUDGET_USD:.2f} minimum "
            "(a film needs film stock: fixed pipeline overhead alone approaches $1)"
        )
    home = Path(home) if home else default_home()
    storage = SQLiteStorage(home / "foreshadow.db")
    if isinstance(transport, str):
        transport_obj = make_transport(transport)
    else:
        transport_obj = transport
    deterministic = transport_obj.name == "fake"
    clock: Clock = FixedClock() if deterministic else SystemClock()
    if deterministic:
        worker_key, signing_key = demo_worker_key(), demo_signing_key()
    else:
        worker_key = load_or_create_worker_key(home / "keys" / "worker_x25519.key")
        signing_key = load_or_create_signing_key(home / "keys" / "project_signing.key")
    if job_id is None:
        import uuid

        job_id = f"job-{incident_id}-b{budget_usd:g}-{uuid.uuid4().hex[:8]}"
    storage.create_job(job_id, incident_id, budget_usd, transport_obj.name, clock.now())
    job_dir = home / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    ledger = ProvenanceLedger(storage, job_id, budget_usd, clock)
    return JobContext(
        job_id=job_id,
        incident_id=incident_id,
        budget_usd=usd(budget_usd),
        storage=storage,
        transport=transport_obj,
        clock=clock,
        ledger=ledger,
        home=home,
        job_dir=job_dir,
        worker_key=worker_key,
        signing_key=signing_key,
        deterministic=deterministic,
        incident_file=Path(incident_file) if incident_file else None,
    )


def run_pipeline(
    ctx: JobContext,
    until: str | None = None,
    on_stage: Callable[[str, str, dict | None], None] | None = None,
) -> JobResult:
    """Run stages in order, skipping any already done (resume semantics).
    `until` stops after the named stage (used by `foreshadow plan`)."""
    if until is not None and until not in STAGE_ORDER:
        raise ValueError(f"unknown stage {until!r}; expected one of {STAGE_ORDER}")
    ctx.storage.set_job_status(ctx.job_id, "running")
    import json as _json

    for name, fn in STAGES:
        if ctx.storage.stage_status(ctx.job_id, name) in ("done", "skipped"):
            if on_stage:
                on_stage(name, "cached", None)
        else:
            ctx.storage.mark_stage(ctx.job_id, name, "running", ts=ctx.clock.now())
            if on_stage:
                on_stage(name, "running", None)
            try:
                detail: dict[str, Any] = fn(ctx) or {}
            except KillSwitchTripped as exc:
                ctx.storage.mark_stage(ctx.job_id, name, "failed",
                                       ts=ctx.clock.now(), error=str(exc))
                ctx.storage.set_job_status(ctx.job_id, "killed")
                raise
            except Exception as exc:
                ctx.storage.mark_stage(ctx.job_id, name, "failed",
                                       ts=ctx.clock.now(), error=str(exc))
                ctx.storage.set_job_status(ctx.job_id, "failed")
                raise
            ctx.storage.mark_stage(ctx.job_id, name, "done", ts=ctx.clock.now(),
                                   detail=_json.dumps(detail, sort_keys=True))
            if on_stage:
                on_stage(name, "done", detail)
        if name == until:
            break

    finished_all = until is None and all(
        ctx.storage.stage_status(ctx.job_id, n) in ("done", "skipped")
        for n in STAGE_ORDER
    )
    if finished_all:
        ctx.storage.set_job_status(ctx.job_id, "published")
    manifest_row = ctx.storage.get_manifest(ctx.job_id)
    job = ctx.storage.get_job(ctx.job_id)
    assert job is not None
    manifest_path = ctx.job_dir / "manifest.json"
    return JobResult(
        job_id=ctx.job_id,
        status=job["status"],
        job_dir=ctx.job_dir,
        spent_usd=ctx.storage.ledger_total(ctx.job_id),
        merkle_root=manifest_row["merkle_root"] if manifest_row else None,
        manifest_path=manifest_path if manifest_path.exists() else None,
        stages=ctx.storage.stages_for_job(ctx.job_id),
    )


# -----------------------------------------------------------------------------
# Replay: the judge path. Zero network, zero keys, byte-identical output.
# -----------------------------------------------------------------------------
def replay_job_id(incident_id: str, budget_usd: float) -> str:
    return f"replay-{incident_id}-b{budget_usd:g}"


def replay(
    incident_id: str,
    budget_usd: float = config.DEFAULT_BUDGET_USD,
    home: Path | None = None,
    on_stage: Callable[[str, str, dict | None], None] | None = None,
) -> tuple[JobResult, bool | None]:
    """Fresh deterministic run under a stable job id. Returns (result,
    matches_committed_cache) — the bool is None when no cache exists for the
    (incident, budget) pair."""
    home = Path(home) if home else default_home()
    job_id = replay_job_id(incident_id, budget_usd)
    storage = SQLiteStorage(home / "foreshadow.db")
    storage.delete_job(job_id)
    storage.close()
    job_dir = home / "jobs" / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir)
    ctx = create_context(incident_id, budget_usd, transport="fake",
                         job_id=job_id, home=home)
    result = run_pipeline(ctx, on_stage=on_stage)

    matches: bool | None = None
    cache_manifest = config.fixtures_dir() / "cache" / incident_id / "manifest.json"
    if cache_manifest.exists():
        cached = read_json(cache_manifest)
        if usd(cached.get("budget_usd", -1.0)) == usd(budget_usd):
            fresh = read_json(ctx.job_dir / "manifest.json")
            matches = (
                cached["merkle_root"] == fresh["merkle_root"]
                and cached["signature"] == fresh["signature"]
            )
    return result, matches
