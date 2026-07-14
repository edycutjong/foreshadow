"""Shared fixtures. The ENTIRE suite runs with the network hard-blocked:
any socket connection attempt raises. FakeQwen + demo keys only — no
DASHSCOPE_API_KEY is ever read (proven by test_live_qwen)."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from foreshadow.pipeline.engine import JobContext, JobResult, create_context, run_pipeline

BUILD_ROOT = Path(__file__).resolve().parent.parent


def _blocked(*args, **kwargs):
    raise RuntimeError("network disabled for the entire foreshadow test suite")


@pytest.fixture(scope="session", autouse=True)
def no_network():
    """Session-wide socket guard: every test is an offline test."""
    saved = {
        "connect": socket.socket.connect,
        "connect_ex": socket.socket.connect_ex,
        "create_connection": socket.create_connection,
        "getaddrinfo": socket.getaddrinfo,
    }
    socket.socket.connect = _blocked  # type: ignore[method-assign]
    socket.socket.connect_ex = _blocked  # type: ignore[method-assign]
    socket.create_connection = _blocked  # type: ignore[assignment]
    socket.getaddrinfo = _blocked  # type: ignore[assignment]
    yield
    socket.socket.connect = saved["connect"]  # type: ignore[method-assign]
    socket.socket.connect_ex = saved["connect_ex"]  # type: ignore[method-assign]
    socket.create_connection = saved["create_connection"]  # type: ignore[assignment]
    socket.getaddrinfo = saved["getaddrinfo"]  # type: ignore[assignment]


def full_run(incident: str, budget: float, home: Path, job_id: str | None = None,
             transport="fake") -> tuple[JobContext, JobResult]:
    ctx = create_context(incident, budget, transport,
                         job_id=job_id or f"t-{incident}-b{budget:g}", home=home)
    result = run_pipeline(ctx)
    return ctx, result


@pytest.fixture(scope="session")
def forklift_run(tmp_path_factory, no_network):
    return full_run("forklift", 4.0, tmp_path_factory.mktemp("forklift"))


@pytest.fixture(scope="session")
def chemical_run(tmp_path_factory, no_network):
    return full_run("chemical", 4.0, tmp_path_factory.mktemp("chemical"))


@pytest.fixture(scope="session")
def ladder_run(tmp_path_factory, no_network):
    return full_run("ladder", 2.0, tmp_path_factory.mktemp("ladder"))
