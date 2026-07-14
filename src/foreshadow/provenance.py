"""Provenance: cost ledger (with kill switch), manifest build, invariant verify.

Invariants (COMPLEXITY.md section 2, all tested):
  I1  every entry in the final cut's edit list resolves to a manifest leaf
      whose ancestry (parent_ids) reaches a leaf with a real qwen_task_id
  I2  spent_usd <= budget_usd, and the leaf costs reconcile with the ledger
  I3  no QC-rejected clip hash appears in the edit list
  I4  re-hashing every artifact file, rebuilding the Merkle root and checking
      the Ed25519 signature fails on ANY 1-byte tamper
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from nacl.signing import SigningKey

from . import config
from .crypto.merkle import hash_leaf, merkle_root
from .crypto.signing import pubkey_hex, sign_payload, verify_signature
from .schemas import Manifest, ManifestLeaf
from .utils import Clock, canonical_json, sha256_file, usd


class KillSwitchTripped(RuntimeError):
    """Ledger refused a spend that would cross 2.5 x budget (hard stop)."""


class ProvenanceLedger:
    """Single writing surface for money and artifacts on a job.

    - charge(): appends a priced ledger row; trips the kill switch if the
      running total would cross KILL_SWITCH_MULTIPLIER x budget.
    - note(): zero-cost ledger row (decisions, regret, stage notes).
    - record_artifact(): registers an artifact + its manifest-leaf metadata.
    """

    def __init__(self, storage, job_id: str, budget_usd: float, clock: Clock) -> None:
        self.storage = storage
        self.job_id = job_id
        self.budget_usd = float(budget_usd)
        self.clock = clock
        self._tripped = False

    # -- money -----------------------------------------------------------------
    @property
    def spent_usd(self) -> float:
        return self.storage.ledger_total(self.job_id)

    def remaining_usd(self) -> float:
        return usd(self.budget_usd - self.spent_usd)

    def charge(self, item: str, cost_usd: float, rationale: str = "") -> float:
        if cost_usd < 0:
            raise ValueError("negative charge")
        if self._tripped:
            raise KillSwitchTripped(
                f"job {self.job_id}: kill switch already tripped; no further spend"
            )
        cap = config.KILL_SWITCH_MULTIPLIER * self.budget_usd
        prospective = usd(self.spent_usd + cost_usd)
        if prospective > cap + 1e-9:
            self._tripped = True
            self.storage.set_job_status(self.job_id, "killed")
            raise KillSwitchTripped(
                f"job {self.job_id}: spend ${prospective:.2f} would cross the "
                f"{config.KILL_SWITCH_MULTIPLIER}x budget kill switch (${cap:.2f})"
            )
        self.storage.append_ledger(self.job_id, self.clock.now(), item, cost_usd, rationale)
        self.storage.add_spend(self.job_id, cost_usd)
        return prospective

    def note(self, item: str, rationale: str) -> None:
        self.storage.append_ledger(self.job_id, self.clock.now(), item, 0.0, rationale)

    def rows(self) -> list[dict]:
        return self.storage.ledger_for_job(self.job_id)

    # -- artifacts ---------------------------------------------------------------
    def record_artifact(self, *, kind: str, rel_path: str, sha256: str,
                        model: str = "", prompt_sha256: str = "",
                        qwen_task_id: str = "", parent_ids: list[str] | None = None,
                        cost_usd: float = 0.0) -> str:
        meta = {
            "kind": kind,
            "model": model,
            "prompt_sha256": prompt_sha256,
            "qwen_task_id": qwen_task_id,
            "parent_ids": list(parent_ids or []),
            "cost_usd": usd(cost_usd),
            "ts": self.clock.now(),
        }
        self.storage.add_artifact(self.job_id, kind, rel_path, sha256, meta)
        return sha256


# -----------------------------------------------------------------------------
# Manifest build
# -----------------------------------------------------------------------------
def leaves_from_storage(storage, job_id: str) -> list[ManifestLeaf]:
    leaves = []
    for row in storage.artifacts_for_job(job_id):
        meta = row["meta"]
        leaves.append(
            ManifestLeaf(
                sha256=row["sha256"],
                kind=meta.get("kind", row["kind"]),
                model=meta.get("model", ""),
                prompt_sha256=meta.get("prompt_sha256", ""),
                qwen_task_id=meta.get("qwen_task_id", ""),
                parent_ids=meta.get("parent_ids", []),
                cost_usd=meta.get("cost_usd", 0.0),
                ts=meta.get("ts", 0),
                path=row["path"],
            )
        )
    return leaves


def build_manifest(*, storage, job_id: str, incident_id: str, budget_usd: float,
                   edit_list: list[str], qc_rejected: list[str],
                   signing_key: SigningKey, created_ts: int) -> Manifest:
    leaves = leaves_from_storage(storage, job_id)
    if not leaves:
        raise ValueError("cannot build a manifest with zero leaves")
    root = merkle_root([hash_leaf(leaf.leaf_payload()) for leaf in leaves])
    spent = storage.ledger_total(job_id)
    draft = Manifest(
        job_id=job_id,
        incident_id=incident_id,
        budget_usd=usd(budget_usd),
        spent_usd=spent,
        created_ts=created_ts,
        leaves=leaves,
        edit_list=edit_list,
        qc_rejected=qc_rejected,
        merkle_root=root,
        signer_pubkey=pubkey_hex(signing_key),
        signature="0" * 128,  # placeholder replaced below
    )
    signature = sign_payload(signing_key, canonical_json(draft.signed_payload()))
    return draft.model_copy(update={"signature": signature})


# -----------------------------------------------------------------------------
# Verification (I1-I4)
# -----------------------------------------------------------------------------
@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class VerifyReport:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(Check(name, passed, detail))

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)

    def get(self, name: str) -> Check:
        for c in self.checks:
            if c.name == name:
                return c
        raise KeyError(name)


def _ancestor_has_task_id(sha: str, by_sha: dict[str, ManifestLeaf]) -> bool:
    seen: set[str] = set()
    stack = [sha]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        leaf = by_sha.get(current)
        if leaf is None:
            return False
        if leaf.qwen_task_id:
            return True
        stack.extend(leaf.parent_ids)
    return False


def verify_manifest(manifest: Manifest, base_dir: Path | None = None,
                    film_path: Path | None = None,
                    trusted_pubkey_hex: str | None = None) -> VerifyReport:
    report = VerifyReport()
    by_sha = {leaf.sha256: leaf for leaf in manifest.leaves}

    # signature ---------------------------------------------------------------
    signer = trusted_pubkey_hex or manifest.signer_pubkey
    sig_ok = verify_signature(
        signer, canonical_json(manifest.signed_payload()), manifest.signature
    )
    report.add("signature", sig_ok, f"Ed25519 signer {signer[:16]}...")
    if trusted_pubkey_hex is not None:
        report.add(
            "trusted_signer",
            trusted_pubkey_hex == manifest.signer_pubkey,
            "manifest pubkey matches --trusted-key",
        )

    # merkle root ---------------------------------------------------------------
    recomputed = merkle_root([hash_leaf(leaf.leaf_payload()) for leaf in manifest.leaves])
    report.add(
        "merkle_root",
        recomputed == manifest.merkle_root,
        f"recomputed {recomputed[:16]}...",
    )

    # I4: artifact re-hash (any 1-byte tamper must fail here) --------------------
    if base_dir is not None:
        bad: list[str] = []
        missing: list[str] = []
        for leaf in manifest.leaves:
            path = base_dir / leaf.path
            if not path.exists():
                missing.append(leaf.path)
            elif sha256_file(path) != leaf.sha256:
                bad.append(leaf.path)
        detail = ""
        if bad:
            detail = f"hash mismatch: {', '.join(bad[:5])}"
        if missing:
            detail += (" | " if detail else "") + f"missing: {', '.join(missing[:5])}"
        report.add(
            "I4_artifact_hashes",
            not bad and not missing,
            detail or f"{len(manifest.leaves)} artifact hashes re-verified",
        )
    if film_path is not None:
        film_leaves = [leaf for leaf in manifest.leaves if leaf.kind == "film"]
        film_ok = bool(film_leaves) and sha256_file(Path(film_path)) == film_leaves[0].sha256
        report.add("I4_film_hash", film_ok, "film file matches its manifest leaf")

    # I1: edit list fully traceable to real task ids -----------------------------
    untraceable = [
        sha for sha in manifest.edit_list if not _ancestor_has_task_id(sha, by_sha)
    ]
    report.add(
        "I1_traceable_edit_list",
        not untraceable,
        (
            f"{len(manifest.edit_list)} cut entries trace to task ids"
            if not untraceable
            else f"untraceable: {', '.join(s[:12] for s in untraceable[:5])}"
        ),
    )

    # I2: budget --------------------------------------------------------------
    within = manifest.spent_usd <= manifest.budget_usd + 1e-9
    leaf_cost = usd(sum(leaf.cost_usd for leaf in manifest.leaves))
    reconciles = abs(leaf_cost - manifest.spent_usd) < 1e-6
    report.add(
        "I2_budget",
        within and reconciles,
        f"spent ${manifest.spent_usd:.2f} <= budget ${manifest.budget_usd:.2f}; "
        f"leaf costs ${leaf_cost:.2f} reconcile",
    )

    # I3: rejected clips excluded from the cut -----------------------------------
    overlap = set(manifest.edit_list) & set(manifest.qc_rejected)
    rejected_kinds = [
        by_sha[sha].kind for sha in manifest.edit_list
        if sha in by_sha and by_sha[sha].kind == "clip_rejected"
    ]
    report.add(
        "I3_rejected_excluded",
        not overlap and not rejected_kinds,
        (
            f"{len(manifest.qc_rejected)} rejected clip(s) provably outside the cut"
            if not overlap and not rejected_kinds
            else f"rejected material in edit list: {len(overlap) + len(rejected_kinds)} entr(ies)"
        ),
    )
    return report
