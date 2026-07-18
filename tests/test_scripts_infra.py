"""Lock in the mandated scripts + the FC handler stub (all offline)."""

from __future__ import annotations

import importlib.util
import json
import runpy
import subprocess
import sys
from pathlib import Path

BUILD_ROOT = Path(__file__).resolve().parent.parent


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_fc_handler_runs_offline():
    handler = _load(BUILD_ROOT / "infra" / "fc" / "handler.py", "fc_handler").handler
    resp = handler(json.dumps({"incident_id": "forklift", "budget_usd": 4,
                               "transport": "fake"}), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "published"
    assert len(body["merkle_root"]) == 64
    assert body["stages"]


def test_fc_handler_reports_error_cleanly():
    handler = _load(BUILD_ROOT / "infra" / "fc" / "handler.py", "fc_handler2").handler
    resp = handler(json.dumps({"incident_id": "forklift", "budget_usd": 0.1,
                               "transport": "fake"}), None)
    assert resp["statusCode"] == 500
    assert "error" in json.loads(resp["body"])


def test_fc_handler_accepts_bytes_event(tmp_path):
    """FC delivers HTTP bodies as bytes — the handler must decode before parsing."""
    handler = _load(BUILD_ROOT / "infra" / "fc" / "handler.py", "fc_handler3").handler
    raw = json.dumps({"incident_id": "forklift", "budget_usd": 4,
                      "transport": "fake", "home": str(tmp_path)}).encode("utf-8")
    resp = handler(raw, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "published"
    assert len(body["merkle_root"]) == 64


def test_fc_handler_main_smoke_prints_json(tmp_path, monkeypatch, capsys):
    """`python infra/fc/handler.py` is the documented local smoke — it must print
    a 200 envelope as one JSON line, fully offline."""
    monkeypatch.setenv("FORESHADOW_HOME", str(tmp_path))
    runpy.run_path(str(BUILD_ROOT / "infra" / "fc" / "handler.py"), run_name="__main__")
    out = capsys.readouterr().out.strip()
    resp = json.loads(out)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["status"] == "published"


def test_verify_offline_script_exits_zero():
    proc = subprocess.run(
        [sys.executable, "scripts/verify_offline.py"],
        cwd=BUILD_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OFFLINE VERIFICATION PASS" in proc.stdout


def test_check_submission_readiness_exits_zero():
    proc = subprocess.run(
        [sys.executable, "scripts/check_submission_readiness.py"],
        cwd=BUILD_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "SUBMISSION READY" in proc.stdout


def test_bench_script_exits_zero():
    proc = subprocess.run(
        [sys.executable, "scripts/bench.py"],
        cwd=BUILD_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Budget sweep" in proc.stdout
