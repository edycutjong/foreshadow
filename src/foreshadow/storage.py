"""Storage layer — SPEC.md section 7 tables behind a small interface.

The spec targets Supabase (Postgres) in production; this package ships a
storage abstraction with a SQLite default so the entire pipeline — and every
test — runs offline with zero services. `Storage` is the seam where a
Postgres/Supabase implementation plugs in (see infra/fc/handler.py notes).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Protocol

from .utils import usd

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'created',
    budget_usd  REAL NOT NULL,
    spent_usd   REAL NOT NULL DEFAULT 0,
    transport   TEXT NOT NULL DEFAULT 'fake',
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS stages (
    job_id   TEXT NOT NULL,
    name     TEXT NOT NULL,
    status   TEXT NOT NULL DEFAULT 'pending',
    started  INTEGER,
    finished INTEGER,
    error    TEXT,
    detail   TEXT,
    PRIMARY KEY (job_id, name)
);
CREATE TABLE IF NOT EXISTS shots (
    job_id   TEXT NOT NULL,
    shot_id  TEXT NOT NULL,
    plan     TEXT NOT NULL,
    tier     TEXT,
    task_id  TEXT,
    artifact_path TEXT,
    qc       TEXT,
    cost_usd REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (job_id, shot_id)
);
CREATE TABLE IF NOT EXISTS ledger (
    seq      INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id   TEXT NOT NULL,
    ts       INTEGER NOT NULL,
    item     TEXT NOT NULL,
    cost_usd REAL NOT NULL,
    rationale TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS artifacts (
    job_id  TEXT NOT NULL,
    kind    TEXT NOT NULL,
    path    TEXT NOT NULL,
    sha256  TEXT NOT NULL,
    meta    TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (job_id, path)
);
CREATE TABLE IF NOT EXISTS manifests (
    job_id      TEXT PRIMARY KEY,
    merkle_root TEXT NOT NULL,
    signature   TEXT NOT NULL,
    leaf_count  INTEGER NOT NULL,
    verified_at INTEGER
);
"""


class Storage(Protocol):
    """Persistence seam. SQLiteStorage is the default; a Supabase-backed
    implementation satisfies the same protocol in production."""

    def create_job(self, job_id: str, incident_id: str, budget_usd: float, transport: str, created_at: int) -> None: ...
    def get_job(self, job_id: str) -> dict[str, Any] | None: ...
    def set_job_status(self, job_id: str, status: str) -> None: ...
    def add_spend(self, job_id: str, amount: float) -> float: ...
    def stage_status(self, job_id: str, name: str) -> str: ...
    def mark_stage(self, job_id: str, name: str, status: str, ts: int | None = None,
                   error: str | None = None, detail: str | None = None) -> None: ...


class SQLiteStorage:
    def __init__(self, path: Path | str = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- jobs ---------------------------------------------------------------
    def create_job(self, job_id: str, incident_id: str, budget_usd: float,
                   transport: str, created_at: int) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO jobs (id, incident_id, status, budget_usd, spent_usd, transport, created_at)"
            " VALUES (?, ?, 'created', ?, 0, ?, ?)",
            (job_id, incident_id, usd(budget_usd), transport, created_at),
        )
        self._conn.commit()

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def set_job_status(self, job_id: str, status: str) -> None:
        self._conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
        self._conn.commit()

    def add_spend(self, job_id: str, amount: float) -> float:
        """Atomically add to spent_usd; returns the new total."""
        self._conn.execute(
            "UPDATE jobs SET spent_usd = ROUND(spent_usd + ?, 6) WHERE id = ?",
            (usd(amount), job_id),
        )
        self._conn.commit()
        job = self.get_job(job_id)
        assert job is not None
        return usd(job["spent_usd"])

    # -- stages ---------------------------------------------------------------
    def stage_status(self, job_id: str, name: str) -> str:
        row = self._conn.execute(
            "SELECT status FROM stages WHERE job_id = ? AND name = ?", (job_id, name)
        ).fetchone()
        return row["status"] if row else "pending"

    def get_stage(self, job_id: str, name: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM stages WHERE job_id = ? AND name = ?", (job_id, name)
        ).fetchone()
        return dict(row) if row else None

    def mark_stage(self, job_id: str, name: str, status: str, ts: int | None = None,
                   error: str | None = None, detail: str | None = None) -> None:
        existing = self.get_stage(job_id, name)
        if existing is None:
            self._conn.execute(
                "INSERT INTO stages (job_id, name, status) VALUES (?, ?, ?)",
                (job_id, name, status),
            )
            existing = {"started": None, "finished": None}
        sets, params = ["status = ?"], [status]
        if status == "running" and ts is not None:
            sets.append("started = ?")
            params.append(ts)
        if status in ("done", "failed", "skipped") and ts is not None:
            sets.append("finished = ?")
            params.append(ts)
        if error is not None:
            sets.append("error = ?")
            params.append(error)
        if detail is not None:
            sets.append("detail = ?")
            params.append(detail)
        params.extend([job_id, name])
        self._conn.execute(
            f"UPDATE stages SET {', '.join(sets)} WHERE job_id = ? AND name = ?", params
        )
        self._conn.commit()

    def stages_for_job(self, job_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM stages WHERE job_id = ? ORDER BY rowid", (job_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # -- shots ----------------------------------------------------------------
    def upsert_shot(self, job_id: str, shot_id: str, plan: dict, tier: str | None = None,
                    task_id: str | None = None, artifact_path: str | None = None,
                    qc: dict | None = None, cost_usd: float | None = None) -> None:
        self._conn.execute(
            "INSERT INTO shots (job_id, shot_id, plan) VALUES (?, ?, ?)"
            " ON CONFLICT(job_id, shot_id) DO UPDATE SET plan = excluded.plan",
            (job_id, shot_id, json.dumps(plan, sort_keys=True)),
        )
        sets, params = [], []
        for col, val in (
            ("tier", tier),
            ("task_id", task_id),
            ("artifact_path", artifact_path),
            ("qc", json.dumps(qc, sort_keys=True) if qc is not None else None),
            ("cost_usd", usd(cost_usd) if cost_usd is not None else None),
        ):
            if val is not None:
                sets.append(f"{col} = ?")
                params.append(val)
        if sets:
            params.extend([job_id, shot_id])
            self._conn.execute(
                f"UPDATE shots SET {', '.join(sets)} WHERE job_id = ? AND shot_id = ?",
                params,
            )
        self._conn.commit()

    def shots_for_job(self, job_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM shots WHERE job_id = ? ORDER BY shot_id", (job_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["plan"] = json.loads(d["plan"])
            d["qc"] = json.loads(d["qc"]) if d["qc"] else None
            out.append(d)
        return out

    # -- ledger -----------------------------------------------------------------
    def append_ledger(self, job_id: str, ts: int, item: str, cost_usd: float,
                      rationale: str = "") -> None:
        self._conn.execute(
            "INSERT INTO ledger (job_id, ts, item, cost_usd, rationale) VALUES (?, ?, ?, ?, ?)",
            (job_id, ts, item, usd(cost_usd), rationale),
        )
        self._conn.commit()

    def ledger_for_job(self, job_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT ts, item, cost_usd, rationale FROM ledger WHERE job_id = ? ORDER BY seq",
            (job_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def ledger_total(self, job_id: str) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM ledger WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return usd(row["total"])

    # -- artifacts ----------------------------------------------------------------
    def add_artifact(self, job_id: str, kind: str, path: str, sha256: str,
                     meta: dict | None = None) -> None:
        self._conn.execute(
            "INSERT INTO artifacts (job_id, kind, path, sha256, meta) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(job_id, path) DO UPDATE SET kind = excluded.kind,"
            " sha256 = excluded.sha256, meta = excluded.meta",
            (job_id, kind, path, sha256, json.dumps(meta or {}, sort_keys=True)),
        )
        self._conn.commit()

    def artifacts_for_job(self, job_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT kind, path, sha256, meta FROM artifacts WHERE job_id = ? ORDER BY rowid",
            (job_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["meta"] = json.loads(d["meta"])
            out.append(d)
        return out

    # -- manifests ----------------------------------------------------------------
    def save_manifest(self, job_id: str, merkle_root: str, signature: str,
                      leaf_count: int, verified_at: int | None = None) -> None:
        self._conn.execute(
            "INSERT INTO manifests (job_id, merkle_root, signature, leaf_count, verified_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(job_id) DO UPDATE SET merkle_root = excluded.merkle_root,"
            " signature = excluded.signature, leaf_count = excluded.leaf_count,"
            " verified_at = excluded.verified_at",
            (job_id, merkle_root, signature, leaf_count, verified_at),
        )
        self._conn.commit()

    def get_manifest(self, job_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM manifests WHERE job_id = ?", (job_id,)
        ).fetchone()
        return dict(row) if row else None

    # -- job deletion (fresh replay semantics) ---------------------------------
    def delete_job(self, job_id: str) -> None:
        for table in ("jobs", "stages", "shots", "ledger", "artifacts", "manifests"):
            column = "id" if table == "jobs" else "job_id"
            self._conn.execute(f"DELETE FROM {table} WHERE {column} = ?", (job_id,))
        self._conn.commit()
