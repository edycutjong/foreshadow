"""The eleven pipeline stages (SPEC.md section 4):

ingest -> screenplay -> shot_plan -> budget_alloc -> character_sheet ->
storyboard -> render -> qc -> narrate -> stitch -> publish

Each stage is a function of the JobContext, idempotent at the engine level
(a stage marked done is never re-run), and resumable: stages exchange data
only through artifacts on disk + rows in storage, never in-process state.
Every artifact registers a provenance leaf; every dollar registers a ledger
row; leaf costs and ledger rows reconcile to the cent (checked by I2).
"""

from __future__ import annotations

from pathlib import Path

from .. import config
from ..agents.art import ArtDept
from ..agents.line_producer import allocate, tier_cost
from ..agents.qc import QCCritic, qc_note
from ..agents.screenwriter import Screenwriter
from ..crypto.sealing import seal, seal_deterministic, unseal
from ..qwen.png import make_png
from ..render.narrate import Narrator, narration_cost, narration_script
from ..render.orchestrator import RenderOrchestrator, render_prompt
from ..render.stitch import (
    card_clip_stub,
    edit_list_text,
    ffmpeg_path,
    film_stub,
    kenburns_clip_stub,
)
from ..schemas import Allocation, Screenplay, Shot, ShotPlan, prompt_sha
from ..utils import read_json, sha256_hex, usd, write_json

CARD_DURATION_S = 3


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _artifact_sha(ctx, rel_path: str) -> str:
    for row in ctx.storage.artifacts_for_job(ctx.job_id):
        if row["path"] == rel_path:
            return row["sha256"]
    raise KeyError(f"artifact not registered: {rel_path}")


def _load_screenplay(ctx) -> Screenplay:
    return Screenplay.model_validate(read_json(ctx.job_dir / "screenplay.json"))


def _load_shotplan(ctx) -> ShotPlan:
    return ShotPlan.model_validate(read_json(ctx.job_dir / "shotplan.json"))


def _load_allocation(ctx) -> Allocation:
    return Allocation.model_validate(read_json(ctx.job_dir / "allocation.json"))


def _write_artifact(ctx, rel_path: str, data: bytes) -> str:
    from ..utils import atomic_write_bytes

    atomic_write_bytes(ctx.job_dir / rel_path, data)
    return sha256_hex(data)


def _incident_text(ctx) -> str:
    if ctx.incident_file is not None:
        path = Path(ctx.incident_file)
    else:
        path = config.seeds_dir() / f"{ctx.incident_id}.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"incident source not found: {path} "
            f"(known seed incidents: {', '.join(config.INCIDENT_IDS)})"
        )
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------------
def stage_ingest(ctx) -> dict:
    """Seal the incident report at rest. Plaintext never touches storage."""
    text = _incident_text(ctx).encode("utf-8")
    if ctx.deterministic:
        sealed = seal_deterministic(text, ctx.worker_key.public_key, context=ctx.job_id)
    else:
        sealed = seal(text, ctx.worker_key.public_key)
    sha = _write_artifact(ctx, "incident.sealed", sealed)
    ctx.ledger.record_artifact(kind="incident_sealed", rel_path="incident.sealed", sha256=sha)
    ctx.ledger.note("ingest", f"incident sealed at rest ({len(sealed)} bytes, ECIES envelope)")
    return {"sealed_bytes": len(sealed)}


def stage_screenplay(ctx) -> dict:
    text = unseal((ctx.job_dir / "incident.sealed").read_bytes(), ctx.worker_key).decode("utf-8")
    screenplay, meta = Screenwriter(ctx.transport).write(text, ctx.incident_id)
    data = write_json(ctx.job_dir / "screenplay.json", screenplay.model_dump())
    ctx.ledger.charge("screenplay", config.COST_SCREENPLAY, f"{meta.model} with thinking")
    ctx.ledger.record_artifact(
        kind="screenplay", rel_path="screenplay.json", sha256=sha256_hex(data),
        model=meta.model, prompt_sha256=prompt_sha(meta.prompt),
        qwen_task_id=meta.task_id, parent_ids=[_artifact_sha(ctx, "incident.sealed")],
        cost_usd=config.COST_SCREENPLAY,
    )
    return {"title": screenplay.title, "beats": len(screenplay.beats)}


def stage_shot_plan(ctx) -> dict:
    screenplay = _load_screenplay(ctx)
    plan, meta = Screenwriter(ctx.transport).plan_shots(screenplay, ctx.incident_id)
    data = write_json(ctx.job_dir / "shotplan.json", plan.model_dump())
    ctx.ledger.charge("shot_plan", config.COST_SHOTPLAN, "structured output (JSON schema)")
    ctx.ledger.record_artifact(
        kind="shotplan", rel_path="shotplan.json", sha256=sha256_hex(data),
        model=meta.model, prompt_sha256=prompt_sha(meta.prompt),
        qwen_task_id=meta.task_id,
        parent_ids=[_artifact_sha(ctx, "screenplay.json")], cost_usd=config.COST_SHOTPLAN,
    )
    for shot in plan.shots:
        ctx.storage.upsert_shot(ctx.job_id, shot.id, shot.model_dump())
    return {"shots": len(plan.shots)}


def stage_budget_alloc(ctx) -> dict:
    plan = _load_shotplan(ctx)
    alloc = allocate(plan.shots, ctx.budget_usd, incident_id=ctx.incident_id)
    summary = "; ".join(
        f"{d.shot_id}:{d.tier}(${d.est_cost_usd:.2f})" for d in alloc.decisions
    )
    note, meta = ctx.transport.chat_alloc_rationale(summary)
    ctx.ledger.charge("alloc_rationale", config.COST_ALLOC_RATIONALE, note)
    for decision in alloc.decisions:
        ctx.ledger.note(
            f"decision:{decision.shot_id}",
            f"{decision.rationale} (est ${decision.est_cost_usd:.2f})",
        )
        ctx.storage.upsert_shot(
            ctx.job_id, decision.shot_id,
            next(s.model_dump() for s in plan.shots if s.id == decision.shot_id),
            tier=decision.tier,
        )
    for row in alloc.regret:
        ctx.ledger.note(
            f"regret:{row.shot_id}",
            f"demoted {row.from_tier}->{row.to_tier}: saved ${row.saved_usd:.2f}, "
            f"lost {row.lost_quality_weight:.2f} quality-weight",
        )
    data = write_json(ctx.job_dir / "allocation.json", alloc.model_dump())
    ctx.ledger.record_artifact(
        kind="allocation", rel_path="allocation.json", sha256=sha256_hex(data),
        model=meta.model, prompt_sha256=prompt_sha(meta.prompt),
        qwen_task_id=meta.task_id,
        parent_ids=[_artifact_sha(ctx, "shotplan.json")],
        cost_usd=config.COST_ALLOC_RATIONALE,
    )
    mix: dict[str, int] = {"hero": 0, "connective": 0, "kenburns": 0}
    for decision in alloc.decisions:
        mix[decision.tier] += 1
    return {"mix": mix, "render_spend_usd": alloc.render_spend_usd,
            "regret_rows": len(alloc.regret)}


def stage_character_sheet(ctx) -> dict:
    screenplay = _load_screenplay(ctx)
    png, meta = ArtDept(ctx.transport).character_sheet(screenplay)
    sha = _write_artifact(ctx, "character_sheet.png", png)
    ctx.ledger.charge("character_sheet", config.COST_IMAGE, meta.model)
    ctx.ledger.record_artifact(
        kind="character_sheet", rel_path="character_sheet.png", sha256=sha,
        model=meta.model, prompt_sha256=prompt_sha(meta.prompt),
        qwen_task_id=meta.task_id,
        parent_ids=[_artifact_sha(ctx, "screenplay.json")], cost_usd=config.COST_IMAGE,
    )
    return {"bytes": len(png)}


def stage_storyboard(ctx) -> dict:
    plan = _load_shotplan(ctx)
    frames = ArtDept(ctx.transport).storyboard_frames(plan.shots)
    per_frame_cost = usd(config.COST_IMAGE * config.BATCH_DISCOUNT)
    sheet_sha = _artifact_sha(ctx, "character_sheet.png")
    plan_sha = _artifact_sha(ctx, "shotplan.json")
    for shot_id, png, meta in frames:
        sha = _write_artifact(ctx, f"frames/{shot_id}.png", png)
        ctx.ledger.charge(
            f"storyboard:{shot_id}", per_frame_cost, "Batch API fan-out (-50%)"
        )
        ctx.ledger.record_artifact(
            kind="storyboard_frame", rel_path=f"frames/{shot_id}.png", sha256=sha,
            model=meta.model, prompt_sha256=prompt_sha(meta.prompt),
            qwen_task_id=meta.task_id, parent_ids=[sheet_sha, plan_sha],
            cost_usd=per_frame_cost,
        )
    return {"frames": len(frames), "batch_discount": config.BATCH_DISCOUNT}


def stage_render(ctx) -> dict:
    plan = _load_shotplan(ctx)
    alloc = _load_allocation(ctx)
    tiers = {d.shot_id: d.tier for d in alloc.decisions}
    orchestrator = RenderOrchestrator(ctx.transport)
    rendered = kenburns = 0
    for shot in plan.shots:
        tier = tiers[shot.id]
        frame_rel = f"frames/{shot.id}.png"
        frame_sha = _artifact_sha(ctx, frame_rel)
        if tier == "kenburns":
            blob = kenburns_clip_stub(shot.id, frame_sha, shot.duration_s)
            rel = f"clips/{shot.id}.mp4"
            sha = _write_artifact(ctx, rel, blob)
            ctx.ledger.record_artifact(
                kind="clip_kenburns", rel_path=rel, sha256=sha,
                parent_ids=[frame_sha], cost_usd=0.0,
            )
            ctx.storage.upsert_shot(ctx.job_id, shot.id, shot.model_dump(),
                                    artifact_path=rel, cost_usd=0.0)
            kenburns += 1
            continue
        cost = tier_cost(tier, shot.duration_s)
        frame_png = (ctx.job_dir / frame_rel).read_bytes()
        blob, meta, prompt = orchestrator.render_clip(
            shot, tier, frame_png,
            on_submit=lambda task_id, sid=shot.id, s=shot: ctx.storage.upsert_shot(
                ctx.job_id, sid, s.model_dump(), task_id=task_id
            ),
        )
        rel = f"clips/{shot.id}_attempt1.mp4"
        sha = _write_artifact(ctx, rel, blob)
        ctx.ledger.charge(f"render:{shot.id}", cost, f"{tier} tier on {meta.model}")
        ctx.ledger.record_artifact(
            kind="clip", rel_path=rel, sha256=sha, model=meta.model,
            prompt_sha256=prompt_sha(prompt), qwen_task_id=meta.task_id,
            parent_ids=[frame_sha], cost_usd=cost,
        )
        ctx.storage.upsert_shot(ctx.job_id, shot.id, shot.model_dump(),
                                artifact_path=rel, cost_usd=cost)
        rendered += 1
    return {"rendered": rendered, "kenburns": kenburns}


def stage_qc(ctx) -> dict:
    """Dailies review. Fail path: reject -> (budget permitting) one corrective
    re-render -> re-review -> else demote to a Ken-Burns still. Rejected clip
    hashes are recorded so I3 can prove they never reach the cut."""
    plan = _load_shotplan(ctx)
    alloc = _load_allocation(ctx)
    tiers = {d.shot_id: d.tier for d in alloc.decisions}
    critic = QCCritic(ctx.transport)
    orchestrator = RenderOrchestrator(ctx.transport)
    rejected_shas: list[str] = []
    reviewed = retries = demoted = 0

    def _review(shot: Shot, clip_rel: str, prompt: str, attempt: int):
        nonlocal reviewed
        frame_png = (ctx.job_dir / f"frames/{shot.id}.png").read_bytes()
        verdict, meta = critic.review(shot, prompt, frame_png)
        verdict_rel = f"qc/{shot.id}_attempt{attempt}.json"
        data = write_json(ctx.job_dir / verdict_rel, verdict.model_dump(by_alias=True))
        item = f"qc:{shot.id}" if attempt == 1 else f"qc_retry_review:{shot.id}"
        ctx.ledger.charge(item, config.COST_QC_PER_REVIEW, f"{meta.model} dailies review")
        ctx.ledger.record_artifact(
            kind="qc_verdict", rel_path=verdict_rel, sha256=sha256_hex(data),
            model=meta.model, prompt_sha256=prompt_sha(meta.prompt),
            qwen_task_id=meta.task_id, parent_ids=[_artifact_sha(ctx, clip_rel)],
            cost_usd=config.COST_QC_PER_REVIEW,
        )
        reviewed += 1
        return verdict

    def _reject(clip_rel: str) -> None:
        """Flip the clip leaf to kind=clip_rejected, preserving its model,
        task id and cost — the rejected render stays in the signed manifest
        (money trail + I3 proof) but can never enter the cut."""
        row = next(
            r for r in ctx.storage.artifacts_for_job(ctx.job_id)
            if r["path"] == clip_rel
        )
        meta = row["meta"]
        ctx.ledger.record_artifact(
            kind="clip_rejected", rel_path=clip_rel, sha256=row["sha256"],
            model=meta.get("model", ""),
            prompt_sha256=meta.get("prompt_sha256", ""),
            qwen_task_id=meta.get("qwen_task_id", ""),
            parent_ids=meta.get("parent_ids", []),
            cost_usd=meta.get("cost_usd", 0.0),
        )
        rejected_shas.append(row["sha256"])

    for shot in plan.shots:
        tier = tiers[shot.id]
        if tier == "kenburns":
            continue  # deterministic local effect; no VL review needed
        frame_sha = _artifact_sha(ctx, f"frames/{shot.id}.png")
        clip_rel = f"clips/{shot.id}_attempt1.mp4"
        prompt1 = render_prompt(shot)
        verdict = _review(shot, clip_rel, prompt1, attempt=1)
        if verdict.passed:
            ctx.storage.upsert_shot(ctx.job_id, shot.id, shot.model_dump(),
                                    qc=verdict.model_dump(by_alias=True),
                                    artifact_path=clip_rel)
            continue

        # -- attempt 1 rejected ------------------------------------------------
        render_cost = tier_cost(tier, shot.duration_s)
        _reject(clip_rel)

        # leaf meta changed for the rejected clip -> its ledger row stands, but
        # re-registration flips kind to clip_rejected (cost preserved). The
        # original 'clip' charge remains the money trail.
        note = qc_note(verdict)
        retry_cost = usd(render_cost + config.COST_QC_PER_REVIEW)
        final_rel: str
        final_verdict = verdict
        if config.MAX_QC_RETRIES >= 1 and ctx.ledger.remaining_usd() + 1e-9 >= retry_cost:
            retries += 1
            frame_png = (ctx.job_dir / f"frames/{shot.id}.png").read_bytes()
            blob2, meta2, prompt2 = orchestrator.render_clip(shot, tier, frame_png, note=note)
            retry_rel = f"clips/{shot.id}_attempt2.mp4"
            sha2 = _write_artifact(ctx, retry_rel, blob2)
            ctx.ledger.charge(f"qc_retry_render:{shot.id}", render_cost,
                              f"re-render with corrective note on {meta2.model}")
            ctx.ledger.record_artifact(
                kind="clip", rel_path=retry_rel, sha256=sha2, model=meta2.model,
                prompt_sha256=prompt_sha(prompt2), qwen_task_id=meta2.task_id,
                parent_ids=[frame_sha], cost_usd=render_cost,
            )
            verdict2 = _review(shot, retry_rel, prompt2, attempt=2)
            if verdict2.passed:
                final_rel, final_verdict = retry_rel, verdict2
            else:
                _reject(retry_rel)
                final_rel = _demote(ctx, shot, frame_sha)
                final_verdict = verdict2
                demoted += 1
        else:
            ctx.ledger.note(
                f"qc_demote:{shot.id}",
                f"retry budget-blocked (needs ${retry_cost:.2f}, "
                f"remaining ${ctx.ledger.remaining_usd():.2f}); demoted to kenburns",
            )
            final_rel = _demote(ctx, shot, frame_sha)
            demoted += 1
        ctx.storage.upsert_shot(ctx.job_id, shot.id, shot.model_dump(),
                                tier="kenburns" if final_rel.endswith("_kenburns.mp4") else tier,
                                qc=final_verdict.model_dump(by_alias=True),
                                artifact_path=final_rel)

    summary = {"rejected_sha256": sorted(rejected_shas), "reviewed": reviewed,
               "retries": retries, "demoted": demoted}
    data = write_json(ctx.job_dir / "qc/summary.json", summary)
    ctx.ledger.record_artifact(kind="qc_summary", rel_path="qc/summary.json",
                               sha256=sha256_hex(data))
    return {"reviewed": reviewed, "rejected": len(rejected_shas),
            "retries": retries, "demoted": demoted}


def _demote(ctx, shot: Shot, frame_sha: str) -> str:
    blob = kenburns_clip_stub(shot.id, frame_sha, shot.duration_s)
    rel = f"clips/{shot.id}_kenburns.mp4"
    sha = _write_artifact(ctx, rel, blob)
    ctx.ledger.record_artifact(kind="clip_kenburns", rel_path=rel, sha256=sha,
                               parent_ids=[frame_sha], cost_usd=0.0)
    ctx.ledger.note(f"regret_qc:{shot.id}",
                    "QC demotion to kenburns after failed retry or blocked budget")
    return rel


def stage_narrate(ctx) -> dict:
    screenplay = _load_screenplay(ctx)
    plan = _load_shotplan(ctx)
    script = narration_script(screenplay, plan)
    audio, meta = Narrator(ctx.transport).narrate(script)
    cost = narration_cost(script)
    sha = _write_artifact(ctx, "narration.wav", audio)
    ctx.ledger.charge("narration", cost, f"{meta.model}, {len(script)} chars")
    ctx.ledger.record_artifact(
        kind="narration", rel_path="narration.wav", sha256=sha, model=meta.model,
        prompt_sha256=prompt_sha(meta.prompt), qwen_task_id=meta.task_id,
        parent_ids=[
            _artifact_sha(ctx, "screenplay.json"),
            _artifact_sha(ctx, "shotplan.json"),
        ],
        cost_usd=cost,
    )
    return {"chars": len(script), "cost_usd": cost}


def stage_stitch(ctx) -> dict:
    screenplay = _load_screenplay(ctx)
    plan = _load_shotplan(ctx)
    screenplay_sha = _artifact_sha(ctx, "screenplay.json")

    # cards (local deterministic renders; cost $0, traceable to the screenplay)
    cards: dict[str, str] = {}
    for name, text in (
        ("title", f"{screenplay.title} - a Foreshadow safety film"),
        ("rule", screenplay.rule_card),
    ):
        png = make_png(f"card:{name}:{text}")
        rel = f"cards/{name}.png"
        sha = _write_artifact(ctx, rel, png)
        ctx.ledger.record_artifact(kind="card", rel_path=rel, sha256=sha,
                                   parent_ids=[screenplay_sha])
        clip = card_clip_stub(name, sha, CARD_DURATION_S)
        clip_rel = f"clips/cards/{name}.mp4"
        clip_sha = _write_artifact(ctx, clip_rel, clip)
        ctx.ledger.record_artifact(kind="clip_card", rel_path=clip_rel,
                                   sha256=clip_sha, parent_ids=[sha])
        cards[name] = clip_rel

    # final cut order: title card, shots in plan order, rule card
    shot_rows = {row["shot_id"]: row for row in ctx.storage.shots_for_job(ctx.job_id)}
    edit_entries = [{"path": cards["title"], "sha256": _artifact_sha(ctx, cards["title"])}]
    for shot in plan.shots:
        rel = shot_rows[shot.id]["artifact_path"]
        edit_entries.append({"path": rel, "sha256": _artifact_sha(ctx, rel)})
    edit_entries.append({"path": cards["rule"], "sha256": _artifact_sha(ctx, cards["rule"])})
    narration = {"path": "narration.wav", "sha256": _artifact_sha(ctx, "narration.wav")}

    text = edit_list_text(ctx.job_id, edit_entries, narration)
    edit_sha = _write_artifact(ctx, "film.edit_list.txt", text.encode("utf-8"))
    ctx.ledger.record_artifact(
        kind="edit_list", rel_path="film.edit_list.txt", sha256=edit_sha,
        parent_ids=[e["sha256"] for e in edit_entries],
    )

    if ctx.transport.name == "fake":
        # stub media: never shell out; deterministic on every machine
        film = film_stub(ctx.job_id, edit_entries, narration["sha256"])
        film_sha = _write_artifact(ctx, "film.mp4", film)
        ffmpeg_note = "stub media (deterministic replay); ffmpeg intentionally not used"
    elif ffmpeg_path() is not None:  # pragma: no cover - live media path
        from ..render.stitch import stitch_with_ffmpeg

        stitch_with_ffmpeg(ctx.job_dir, edit_entries,
                           ctx.job_dir / narration["path"], ctx.job_dir / "film.mp4")
        film_sha = sha256_hex((ctx.job_dir / "film.mp4").read_bytes())
        ffmpeg_note = f"ffmpeg concat + audio mix ({ffmpeg_path()})"
    else:
        ctx.ledger.note("stitch", "skipped (ffmpeg not installed); edit list emitted")
        return {"ffmpeg": "skipped (ffmpeg not installed)",
                "edit_entries": len(edit_entries), "film": None}

    ctx.ledger.record_artifact(
        kind="film", rel_path="film.mp4", sha256=film_sha,
        parent_ids=[e["sha256"] for e in edit_entries] + [narration["sha256"]],
    )
    return {"ffmpeg": ffmpeg_note, "edit_entries": len(edit_entries), "film": "film.mp4"}


def stage_publish(ctx) -> dict:
    from ..provenance import build_manifest, verify_manifest

    spent = ctx.storage.ledger_total(ctx.job_id)
    if spent > ctx.budget_usd + 1e-9:
        raise RuntimeError(
            f"I2 violation caught at publish: spent ${spent:.2f} > budget "
            f"${ctx.budget_usd:.2f}"
        )

    ledger_data = write_json(ctx.job_dir / "ledger.json",
                             {"job_id": ctx.job_id, "rows": ctx.ledger.rows(),
                              "total_usd": spent})
    ctx.ledger.record_artifact(kind="ledger", rel_path="ledger.json",
                               sha256=sha256_hex(ledger_data))

    edit_list = _parse_edit_list(ctx.job_dir / "film.edit_list.txt")
    qc_summary = read_json(ctx.job_dir / "qc/summary.json")

    manifest = build_manifest(
        storage=ctx.storage, job_id=ctx.job_id, incident_id=ctx.incident_id,
        budget_usd=ctx.budget_usd, edit_list=edit_list,
        qc_rejected=qc_summary["rejected_sha256"],
        signing_key=ctx.signing_key, created_ts=ctx.clock.now(),
    )
    write_json(ctx.job_dir / "manifest.json", manifest.model_dump())
    film = ctx.job_dir / "film.mp4"
    report = verify_manifest(manifest, base_dir=ctx.job_dir,
                             film_path=film if film.exists() else None)
    if not report.ok:
        failed = [c.name for c in report.checks if not c.passed]
        raise RuntimeError(f"manifest self-check failed: {failed}")
    ctx.storage.save_manifest(ctx.job_id, manifest.merkle_root, manifest.signature,
                              len(manifest.leaves), verified_at=ctx.clock.now())
    ctx.ledger.note("publish", f"manifest root {manifest.merkle_root[:16]}... signed + self-verified")
    return {"merkle_root": manifest.merkle_root, "leaves": len(manifest.leaves),
            "spent_usd": spent, "invariants": "I1-I4 PASS"}


def _parse_edit_list(path: Path) -> list[str]:
    shas = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        shas.append(line.split("\t")[2])
    return shas


STAGES: list[tuple[str, object]] = [
    ("ingest", stage_ingest),
    ("screenplay", stage_screenplay),
    ("shot_plan", stage_shot_plan),
    ("budget_alloc", stage_budget_alloc),
    ("character_sheet", stage_character_sheet),
    ("storyboard", stage_storyboard),
    ("render", stage_render),
    ("qc", stage_qc),
    ("narrate", stage_narrate),
    ("stitch", stage_stitch),
    ("publish", stage_publish),
]

STAGE_ORDER = [name for name, _ in STAGES]
