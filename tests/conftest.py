"""Pytest fixtures: run the app with the MockEngine and isolated temp paths."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["QIR_FAKE_ENGINE"] = "1"


@pytest.fixture()
def app_module(tmp_path, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "data" / "test.db")
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(config, "INPUTS_DIR", tmp_path / "inputs")
    monkeypatch.setattr(config, "THUMBS_DIR", tmp_path / "thumbs")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(config, "MODELS_MANIFEST", ROOT / "models.json")

    from backend import db

    monkeypatch.setattr(db, "_conn", None)

    from backend import main

    main.settings = config.load_settings()
    main.settings["license_accepted"] = True
    main.runner.settings = main.settings
    # fresh window-lifecycle state per test: a monitor task from a previous test
    # must never see a stale idle timer and trigger a real shutdown
    main.WINDOW = main.WindowLifecycle()
    main.SHUTDOWN.clear()
    # each TestClient runs its own event loop; give the runner a fresh worker
    import asyncio
    main.runner._task = None
    main.runner.queue = asyncio.Queue()
    main.runner.cancel_requests.clear()
    main.runner.stopping.clear()
    main.runner.active_job = None
    yield main


@pytest.fixture()
def client(app_module):
    from fastapi.testclient import TestClient

    with TestClient(app_module.app) as c:
        c.headers.update({"X-CSRF": app_module.CSRF_TOKEN})
        yield c


def wait_job(client, job_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    job = {}
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job.get("status") in ("completed", "failed", "cancelled", "interrupted"):
            return job
        time.sleep(0.1)
    return job
