"""Alibaba Function Compute 3.0 — MANAGED python runtime entrypoint (EVENT handler).

No container / no ACR: FC installs requirements.txt under /code/python and
invokes this `handler(event, context)` for the HTTP trigger. `event` is the HTTP
request as JSON bytes; we return {statusCode, headers, body} (NOT a WSGI app — a
WSGI callable makes FC 3.0's HTTP trigger fail with 502 'FCContext' not callable).

Foreshadow targets python3.12 but the managed runtime tops out at 3.10; the only
3.11+ symbol the package could reach is enum.StrEnum, so we shim it BEFORE any
foreshadow import (StrEnum is just str+Enum — byte-identical behaviour).

Endpoints (anonymous HTTP GET/POST):
  GET /         service banner
  GET /health   liveness -> {"status":"ok"}
  GET /verify   offline verify of the committed forklift replay ledger:
                deterministic FakeQwen replay -> re-hash 36 leaves + Ed25519
                signature + invariants I1-I4 + byte-identical cache match. JSON.
  GET /run      offline deterministic pipeline replay (FakeQwen, no key):
                ?incident=forklift&budget=4 -> compact JSON (spend, QC, verdicts).

All paths are OFFLINE and deterministic — no DASHSCOPE key, no image/video/TTS.
"""

from __future__ import annotations

import datetime as _dt
import enum
import json
import os
import sys
import tempfile
from pathlib import Path

# --- 3.10 compat shims: must run before any foreshadow import ----------------
# enum.StrEnum is 3.11+; it is just str+Enum (byte-identical behaviour).
if not hasattr(enum, "StrEnum"):
    class StrEnum(str, enum.Enum):  # noqa: D401 - drop-in for 3.11 enum.StrEnum
        def __str__(self) -> str:
            return str(self.value)
    enum.StrEnum = StrEnum  # type: ignore[attr-defined]

# datetime.UTC is a 3.11+ alias for datetime.timezone.utc (foreshadow.utils uses
# `from datetime import UTC`); expose it so the import resolves on 3.10.
if not hasattr(_dt, "UTC"):
    _dt.UTC = _dt.timezone.utc  # type: ignore[attr-defined]

# The package ships under src/ in the deployed code bundle (code root = build/).
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "..", "..", "src")
if os.path.isdir(_SRC):
    sys.path.insert(0, os.path.abspath(_SRC))


def _tmp_home() -> Path:
    # FC code bundle is read-only except /tmp; replay writes db + job artifacts.
    return Path(tempfile.mkdtemp(prefix="fc-foreshadow-"))


def _verify() -> dict:
    """Re-run the committed forklift replay offline and verify its provenance."""
    from foreshadow.pipeline.engine import replay
    from foreshadow.provenance import verify_manifest
    from foreshadow.schemas import Manifest

    incident, budget = "forklift", 4.0
    result, matches_cache = replay(incident, budget, home=_tmp_home())
    manifest = Manifest.load(result.manifest_path)
    report = verify_manifest(
        manifest, base_dir=result.job_dir, film_path=result.job_dir / "film.mp4"
    )
    return {
        "overall": "PASS" if (report.ok and matches_cache is True) else "FAILED",
        "incident": incident,
        "budget_usd": budget,
        "spent_usd": round(result.spent_usd, 4),
        "merkle_root": result.merkle_root,
        "leaves": len(manifest.leaves),
        "byte_identical_cache": matches_cache,
        "checks": [
            {"name": c.name, "ok": c.passed, "detail": c.detail} for c in report.checks
        ],
        "source": "committed forklift replay ledger (FakeQwen, zero network, zero keys)",
    }


def _run(incident: str, budget: float) -> dict:
    """One deterministic offline pipeline replay -> compact summary."""
    from foreshadow.pipeline.engine import replay

    stages: dict[str, dict] = {}

    def _on_stage(name, status, detail):
        if status == "done" and detail:
            stages[name] = detail

    result, matches_cache = replay(incident, budget, home=_tmp_home(), on_stage=_on_stage)
    qc = stages.get("qc", {})
    alloc = stages.get("budget_alloc", {})
    publish = stages.get("publish", {})
    return {
        "incident": incident,
        "budget_usd": budget,
        "transport": "FakeQwen (offline deterministic — no key required)",
        "status": result.status,
        "spent_usd": round(result.spent_usd, 4),
        "merkle_root": result.merkle_root,
        "byte_identical_cache": matches_cache,
        "budget_mix": alloc.get("mix"),
        "render_spend_usd": alloc.get("render_spend_usd"),
        "qc": {
            "reviewed": qc.get("reviewed"),
            "rejected": qc.get("rejected"),
            "demoted": qc.get("demoted"),
            "retries": qc.get("retries"),
        },
        "invariants": publish.get("invariants"),
        "leaves": publish.get("leaves"),
    }


def _route(path: str, qs: dict) -> tuple[int, dict]:
    path = path.rstrip("/") or "/"
    if path == "/":
        return 200, {
            "service": "foreshadow — agent film studio: incident report -> provenance-signed safety film (Qwen Cloud)",
            "endpoints": {
                "/health": "liveness",
                "/verify": "re-verify the committed forklift replay (Ed25519 + Merkle + I1-I4, byte-identical)",
                "/run": "run one deterministic offline pipeline replay (?incident=&budget=)",
            },
            "repo": "https://github.com/edycutjong/foreshadow",
        }
    if path == "/health":
        return 200, {"status": "ok"}
    if path == "/verify":
        return 200, _verify()
    if path == "/run":
        incident = qs.get("incident", ["forklift"])[0]
        budget = float(qs.get("budget", ["4"])[0])
        return 200, _run(incident, budget)
    return 404, {"error": f"no route {path}"}


def handler(event, context):
    """FC 3.0 event handler for an HTTP trigger.

    `event` is the HTTP request as JSON bytes; return {statusCode, headers, body}.
    """
    from urllib.parse import parse_qs

    try:
        req = json.loads(event) if isinstance(event, (bytes, bytearray, str)) else (event or {})
    except Exception:
        req = {}
    rc_http = (req.get("requestContext") or {}).get("http") or {}
    path = req.get("rawPath") or req.get("path") or rc_http.get("path") or "/"
    qp = req.get("queryParameters") or req.get("queryStringParameters")
    if qp:
        qs = {k: (v if isinstance(v, list) else [v]) for k, v in qp.items()}
    else:
        qs = parse_qs(req.get("rawQueryString", "") or "")
    try:
        code, payload = _route(path, qs)
    except Exception as exc:  # never 500 opaque
        code, payload = 500, {"error": type(exc).__name__, "detail": str(exc)[:400]}
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "isBase64Encoded": False,
        "body": json.dumps(payload, sort_keys=True, indent=2),
    }
