"""Pydantic schemas — the structured-output contracts (SPEC.md section 6)
plus the provenance manifest (COMPLEXITY.md section 2).

Every JSON produced by a Qwen structured-output call is validated against one
of these models; a failed parse is rejected and retried once (see agents).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .utils import canonical_json, sha256_hex

Tier = Literal["hero", "connective", "kenburns"]
QCAction = Literal["re-render_with_note", "accept", "demote_to_kenburns"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Screenplay (Screenwriter output)
# ---------------------------------------------------------------------------
class Beat(StrictModel):
    beat: int = Field(ge=1)
    heading: str = Field(min_length=1)
    description: str = Field(min_length=1)
    vo: str = ""


class Screenplay(StrictModel):
    incident_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    logline: str = Field(min_length=1)
    beats: list[Beat] = Field(min_length=1)
    rule_card: str = Field(min_length=1, description="closing safety rule text")


# ---------------------------------------------------------------------------
# ShotPlan (structured output; the allocator's input)
# ---------------------------------------------------------------------------
class Shot(StrictModel):
    id: str = Field(pattern=r"^[A-Z]\d+$")
    scene: int = Field(ge=1)
    duration_s: int = Field(ge=1, le=10)
    action: str = Field(min_length=1)
    camera: str = Field(min_length=1)
    narrative_weight: int = Field(ge=1, le=10)
    safety_elements: list[str] = Field(default_factory=list)
    vo_line: str = ""


class ShotPlan(StrictModel):
    incident_id: str = Field(min_length=1)
    shots: list[Shot] = Field(min_length=1)

    @field_validator("shots")
    @classmethod
    def _unique_ids(cls, shots: list[Shot]) -> list[Shot]:
        ids = [s.id for s in shots]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate shot ids")
        return shots


# ---------------------------------------------------------------------------
# BudgetDecision (Line Producer output, one per shot)
# ---------------------------------------------------------------------------
class BudgetDecision(StrictModel):
    shot_id: str
    tier: Tier
    desired_tier: Tier
    est_cost_usd: float = Field(ge=0)
    rationale: str = ""

    @property
    def demoted(self) -> bool:
        order = {"kenburns": 0, "connective": 1, "hero": 2}
        return order[self.tier] < order[self.desired_tier]


class RegretRow(StrictModel):
    """Every budget-forced demotion, priced: what we saved, what it cost us."""

    shot_id: str
    from_tier: Tier
    to_tier: Tier
    saved_usd: float = Field(ge=0)
    lost_quality_weight: float = Field(ge=0, description="w_i * (q(from)-q(to))")


class Allocation(StrictModel):
    incident_id: str
    budget_usd: float = Field(gt=0)
    overhead_est_usd: float = Field(ge=0)
    retry_reserve_usd: float = Field(ge=0)
    render_budget_usd: float = Field(ge=0)
    decisions: list[BudgetDecision]
    regret: list[RegretRow] = Field(default_factory=list)
    render_spend_usd: float = Field(ge=0)
    quality_score: float = Field(ge=0, description="sum(w_i * q(tier_i))")
    quality_max: float = Field(ge=0, description="sum(w_i * 1.0)")


# ---------------------------------------------------------------------------
# QCVerdict (VL critic output)
# ---------------------------------------------------------------------------
class QCVerdict(StrictModel):
    shot_id: str
    passed: bool = Field(alias="pass")
    issues: list[str] = Field(default_factory=list)
    action: QCAction

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
class LedgerRow(StrictModel):
    ts: int
    item: str
    cost_usd: float = Field(ge=0)
    rationale: str = ""


# ---------------------------------------------------------------------------
# Provenance manifest (COMPLEXITY.md section 2)
# ---------------------------------------------------------------------------
class ManifestLeaf(StrictModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: str = Field(min_length=1)
    model: str = ""
    prompt_sha256: str = ""
    qwen_task_id: str = ""
    parent_ids: list[str] = Field(default_factory=list, description="parent leaf sha256s")
    cost_usd: float = Field(ge=0)
    ts: int = Field(ge=0)
    path: str = Field(min_length=1, description="artifact path relative to job dir")

    def leaf_payload(self) -> dict:
        """The exact dict that gets canonical-JSON'd and hashed into the tree."""
        return {
            "sha256": self.sha256,
            "kind": self.kind,
            "model": self.model,
            "prompt_sha256": self.prompt_sha256,
            "qwen_task_id": self.qwen_task_id,
            "parent_ids": list(self.parent_ids),
            "cost_usd": self.cost_usd,
            "ts": self.ts,
            "path": self.path,
        }


class Manifest(StrictModel):
    version: int = 1
    job_id: str
    incident_id: str
    budget_usd: float
    spent_usd: float
    created_ts: int
    leaves: list[ManifestLeaf]
    edit_list: list[str] = Field(description="ordered clip sha256s of the final cut")
    qc_rejected: list[str] = Field(default_factory=list)
    merkle_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    signer_pubkey: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")

    def signed_payload(self) -> dict:
        """Everything the Ed25519 signature covers."""
        return {
            "version": self.version,
            "job_id": self.job_id,
            "incident_id": self.incident_id,
            "budget_usd": self.budget_usd,
            "spent_usd": self.spent_usd,
            "created_ts": self.created_ts,
            "leaf_count": len(self.leaves),
            "merkle_root": self.merkle_root,
            "edit_list": list(self.edit_list),
            "qc_rejected": list(self.qc_rejected),
        }

    @classmethod
    def load(cls, path) -> Manifest:
        import json
        from pathlib import Path

        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))

    def verify(self, base_dir=None, film_path=None):
        """Full invariant verification (I1-I4). Returns a VerifyReport."""
        from .provenance import verify_manifest

        return verify_manifest(self, base_dir=base_dir, film_path=film_path)


def prompt_sha(prompt: str) -> str:
    return sha256_hex(canonical_json({"prompt": prompt}))
