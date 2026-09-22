"""RealEngine.poll() progress transitions — no engine process, no network."""
from __future__ import annotations

import asyncio

import pytest

from backend import engine as engine_mod


class _FakeResponse:
    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._data


class _FakeAsyncClient:
    """Minimal stand-in for the httpx.AsyncClient used inside RealEngine.poll()."""

    payload: dict = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url: str):
        return _FakeResponse(type(self).payload)


@pytest.fixture()
def engine_factory(monkeypatch, tmp_path):
    monkeypatch.setattr(engine_mod.config, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(engine_mod.httpx, "AsyncClient", _FakeAsyncClient)

    def make(status: str) -> engine_mod.RealEngine:
        _FakeAsyncClient.payload = {"status": status}
        return engine_mod.RealEngine({"engine": {}})

    return make


def test_poll_queued_keeps_phase_queued(engine_factory):
    eng = engine_factory("queued")
    eng.state = "busy"
    eng.progress = {"phase": "queued", "ts": 0}

    data = asyncio.run(eng.poll("job-queued"))

    assert data["status"] == "queued"
    assert eng.progress["phase"] == "queued"
    assert eng.state == "busy"


def test_poll_generating_upgrades_phase_to_rendering(engine_factory):
    eng = engine_factory("generating")
    eng.state = "busy"
    eng.progress = {"phase": "queued", "ts": 0}

    asyncio.run(eng.poll("job-generating"))

    assert eng.progress["phase"] == "rendering"
    assert eng.progress["ts"] > 0
    assert eng.state == "busy"


def test_poll_generating_keeps_stdout_sampling_progress(engine_factory):
    eng = engine_factory("generating")
    eng.state = "busy"
    eng.progress = {"phase": "sampling", "step": 3, "total": 10}

    asyncio.run(eng.poll("job-sampling"))

    assert eng.progress["phase"] == "sampling"
    assert eng.progress["step"] == 3
    assert eng.progress["total"] == 10


def test_poll_completed_returns_state_to_ready(engine_factory):
    eng = engine_factory("completed")
    eng.state = "busy"
    eng.progress = {"phase": "rendering", "ts": 0}

    data = asyncio.run(eng.poll("job-completed"))

    assert data["status"] == "completed"
    assert eng.state == "ready"
