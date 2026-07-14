"""Alibaba Function Compute entry point for the Foreshadow pipeline worker.

This is the deployment-proof surface (SPEC.md §13, ARCHITECTURE.md). The FC
container ships the `foreshadow-pipeline` package plus an ffmpeg layer; each
invocation runs one film job and streams stage events back.

STATUS: the handler is real and import-clean, but the account has NOT been
deployed to (see PROOF.md — honest). It runs identically to the local pipeline
because the pipeline core is transport- and host-agnostic: the only FC-specific
code is this thin request/response shim. In production the `home` points at a
mounted NAS / OSS-backed path and `transport="live"` reads DASHSCOPE_API_KEY
from the function's environment.

Local smoke (no FC, no network, no key):
    python -c "import json; from infra.fc.handler import handler; \
        print(handler(json.dumps({'incident_id':'forklift','budget_usd':4, \
        'transport':'fake'}), None))"
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _run(event: dict[str, Any]) -> dict[str, Any]:
    # Imported lazily so cold-start only pays for what a request needs.
    from foreshadow.pipeline.engine import create_context, run_pipeline

    incident_id = event.get("incident_id", "forklift")
    budget_usd = float(event.get("budget_usd", 4.0))
    transport = event.get("transport", os.environ.get("FORESHADOW_TRANSPORT", "fake"))
    home = Path(event.get("home") or os.environ.get("FORESHADOW_HOME")
                or tempfile.mkdtemp(prefix="fc-foreshadow-"))

    events: list[dict[str, Any]] = []
    ctx = create_context(incident_id, budget_usd, transport, home=home)
    result = run_pipeline(
        ctx,
        on_stage=lambda name, status, detail: events.append(
            {"stage": name, "status": status, "detail": detail}
        ),
    )
    return {
        "job_id": result.job_id,
        "status": result.status,
        "spent_usd": result.spent_usd,
        "budget_usd": ctx.budget_usd,
        "merkle_root": result.merkle_root,
        "manifest": str(result.manifest_path) if result.manifest_path else None,
        "stages": events,
    }


def handler(event, context):  # noqa: ARG001 - FC signature (event, context)
    """FC HTTP/event entry point. `event` is a JSON string (or dict)."""
    if isinstance(event, (bytes, bytearray)):
        event = event.decode("utf-8")
    if isinstance(event, str):
        event = json.loads(event or "{}")
    try:
        body = _run(event)
        return {"statusCode": 200, "headers": {"Content-Type": "application/json"},
                "body": json.dumps(body)}
    except Exception as exc:  # surface a clean error to the caller
        return {"statusCode": 500, "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": type(exc).__name__, "detail": str(exc)})}


if __name__ == "__main__":  # local smoke, offline
    print(json.dumps(handler(json.dumps({"incident_id": "forklift", "budget_usd": 4,
                                         "transport": "fake"}), None)))
