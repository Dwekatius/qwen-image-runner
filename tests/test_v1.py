"""v1.0 acceptance tests — API, queue semantics, gallery, downloader (MockEngine, no GPU)."""
from __future__ import annotations

import hashlib
import http.server
import json
import threading
import time
from pathlib import Path
from conftest import wait_job


def test_meta_and_csrf(client):
    meta = client.get("/api/meta").json()
    assert meta["app"] == "Qwen Image Runner"
    assert len(meta["csrf"]) == 32
    # mutations without CSRF must be rejected
    naked = client.post("/api/generate", json={"prompt": "x"}, headers={"X-CSRF": ""})
    assert naked.status_code == 403


def test_generate_flow_and_gallery(client):
    r = client.post("/api/generate", json={
        "prompt": "a red apple on a wooden table",
        "width": 512, "height": 512, "steps": 8, "seed": 42, "cfg": 6.0,
    })
    assert r.status_code == 200
    job_id = r.json()["jobs"][0]
    job = wait_job(client, job_id)
    assert job["status"] == "completed", job

    gallery = client.get("/api/gallery").json()["images"]
    assert len(gallery) == 1
    image = gallery[0]
    assert image["seed"] == 42
    assert image["prompt"].startswith("a red apple")
    assert image["params"]["steps"] == 8

    f = client.get(f"/api/images/{image['id']}/file")
    assert f.status_code == 200
    assert f.content[:8] == b"\x89PNG\r\n\x1a\n"

    thumb = client.get(f"/api/images/{image['id']}/thumb")
    assert thumb.status_code == 200

    deleted = client.delete(f"/api/images/{image['id']}")
    assert deleted.status_code == 200
    assert client.get("/api/gallery").json()["images"] == []


def test_queued_cancel(client):
    first = client.post("/api/generate", json={
        "prompt": "job one", "width": 512, "height": 512, "steps": 40, "seed": 1,
    }).json()["jobs"][0]
    second = client.post("/api/generate", json={
        "prompt": "job two", "width": 512, "height": 512, "steps": 40, "seed": 2,
    }).json()["jobs"][0]
    time.sleep(0.3)  # let the first job start so the second stays queued
    cancel = client.post(f"/api/jobs/{second}/cancel").json()
    assert cancel["action"] == "marked"

    second_job = wait_job(client, second, timeout=30)
    assert second_job["status"] == "cancelled"
    first_job = wait_job(client, first, timeout=30)
    assert first_job["status"] == "completed"

    # cancel of a finished job is a no-op
    assert client.post(f"/api/jobs/{first}/cancel").json()["action"] == "none"


def test_edit_requires_references(client):
    r = client.post("/api/edit", data={"instruction": "make it green"})
    assert r.status_code == 400


def test_transparent_prompt_wrapping(client):
    r = client.post("/api/generate", json={
        "prompt": "a cute dragon sticker", "width": 512, "height": 512,
        "steps": 8, "seed": 3, "transparent": True,
    })
    job_id = r.json()["jobs"][0]
    job = wait_job(client, job_id)
    assert job["status"] == "completed"
    assert job["params"]["transparent"] is True


def test_settings_roundtrip(client):
    r = client.put("/api/settings", json={"defaults": {"steps": 20, "cfg": 5.5}, "engine_autostart": False})
    assert r.status_code == 200
    meta = client.get("/api/meta").json()
    assert meta["settings"]["defaults"]["steps"] == 20
    assert meta["settings"]["engine_autostart"] is False


class _RangeHandler(http.server.BaseHTTPRequestHandler):
    payload = b"LOCAL-CANVAS-RESUME-TEST-" * 4096  # ~100 KB

    def log_message(self, *args):  # silence
        pass

    def do_GET(self):
        data = self.payload
        start = 0
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            start = int(rng.split("=")[1].split("-")[0])
        body = data[start:]
        self.send_response(206 if start else 200)
        if start:
            self.send_header("Content-Range", f"bytes {start}-{len(data)-1}/{len(data)}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_chat_generate_then_edit(client):
    chat = client.post("/api/chats", json={}).json()["chat"]
    r = client.post("/api/chat/submit", json={
        "text": "a red apple on a table",
        "chat_id": chat["id"],
        "params": {"width": 512, "height": 512, "steps": 8, "seed": 3},
    })
    assert r.status_code == 200
    first = r.json()
    assert first["mode"] == "generate"
    assert first["chat_id"] == chat["id"]
    assert wait_job(client, first["job"])["status"] == "completed"

    data = client.get(f"/api/chat?chat_id={chat['id']}").json()
    assert [m["role"] for m in data["messages"]] == ["user", "assistant"]
    image_id = data["messages"][1]["image"]["id"]
    # chat images live in a per-chat folder
    assert f"chats/{chat['id']}" in data["messages"][1]["image"]["path"].replace("\\", "/")

    # follow-up without generate keywords -> edit, referencing the last image
    second = client.post("/api/chat/submit", json={
        "text": "make it green",
        "chat_id": chat["id"],
        "params": {"width": 512, "height": 512, "steps": 8, "seed": 4},
    }).json()
    assert second["mode"] == "edit"
    assert second["ref_image_id"] == image_id
    job = wait_job(client, second["job"])
    assert job["status"] == "completed"
    assert job["params"]["mode"] == "edit"
    assert job["params"]["refs"]

    # explicit generate keywords -> brand-new image without a reference
    third = client.post("/api/chat/submit", json={
        "text": "generate a blue car",
        "chat_id": chat["id"],
        "params": {"width": 512, "height": 512, "steps": 8},
    }).json()
    assert third["mode"] == "generate"
    assert wait_job(client, third["job"])["status"] == "completed"


def test_new_chat_preserves_previous(client):
    chat = client.post("/api/chats", json={}).json()["chat"]
    job = client.post("/api/chat/submit", json={
        "text": "a lighthouse at dusk",
        "chat_id": chat["id"],
        "params": {"width": 512, "height": 512, "steps": 4},
    }).json()["job"]
    assert wait_job(client, job)["status"] == "completed"

    chat2 = client.post("/api/chats", json={}).json()["chat"]
    assert chat2["id"] != chat["id"]
    assert client.get(f"/api/chat?chat_id={chat2['id']}").json()["messages"] == []

    kept = client.get(f"/api/chat?chat_id={chat['id']}").json()
    assert len(kept["messages"]) == 2
    assert kept["messages"][1]["image"]["id"]
    # the first chat got a title from its first message
    chats = {c["id"]: c for c in client.get("/api/chats").json()["chats"]}
    assert chats[chat["id"]]["title"].startswith("a lighthouse")
    assert chats[chat["id"]]["image_count"] == 1
    assert chats[chat2["id"]]["image_count"] == 0

    images = client.get("/api/gallery").json()["images"]
    assert len(images) == 1
    assert f"chats/{chat['id']}" in images[0]["path"].replace("\\", "/")


def test_save_as_export(client, tmp_path):
    job_id = client.post("/api/generate", json={
        "prompt": "save me", "width": 512, "height": 512, "steps": 4,
    }).json()["jobs"][0]
    assert wait_job(client, job_id)["status"] == "completed"
    image = client.get("/api/gallery").json()["images"][0]
    res = client.post(f"/api/images/{image['id']}/save_as").json()
    assert res["saved"] is True
    assert Path(res["path"]).exists()
    assert Path(res["path"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_downloader_resume_and_hash(tmp_path, monkeypatch, app_module):
    from backend import config, downloader

    handler = _RangeHandler
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    payload = handler.payload
    component = {
        "id": "test-file",
        "name": "test",
        "path": "models/test/blob.bin",
        "url": f"http://127.0.0.1:{port}/blob.bin",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    manifest = tmp_path / "models-test.json"
    manifest.write_text(json.dumps({"components": [component]}))
    monkeypatch.setattr(config, "MODELS_MANIFEST", manifest)
    monkeypatch.setattr(config, "ROOT", tmp_path)

    # simulate an interrupted download (first 1000 bytes already on disk)
    dest = tmp_path / component["path"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload[:1000])

    # reset downloader state
    downloader._state.update(active=False, component=None, done_bytes=0,
                             total_bytes=0, error=None, cancelled=False, verified={})
    downloader.download_all()
    deadline = time.time() + 15
    while downloader.download_state()["active"] and time.time() < deadline:
        time.sleep(0.1)
    state = downloader.download_state()
    assert state["error"] is None, state
    assert dest.read_bytes() == payload
    assert state["verified"].get("test-file") is True
    server.shutdown()


def test_engine_backends_and_switch(client):
    data = client.get("/api/engine/backends").json()
    ids = [b["id"] for b in data["backends"]]
    assert ids == ["cuda", "vulkan", "cpu"], ids
    assert all("label" in b and "detail" in b and "speed" in b for b in data["backends"])
    assert data["current"] == "cuda"

    switched = client.post("/api/engine/backend", json={"backend": "cpu"}).json()
    assert switched["ok"] is True and switched["backend"] == "cpu"
    assert client.get("/api/settings").json()["engine"]["backend"] == "cpu"
    assert client.get("/api/meta").json()["engine"]["backend"] == "cpu"

    client.post("/api/engine/backend", json={"backend": "cuda"})
    assert client.get("/api/settings").json()["engine"]["backend"] == "cuda"

    bad = client.post("/api/engine/backend", json={"backend": "nope"})
    assert bad.status_code == 400


def test_guide_endpoint(client):
    data = client.get("/api/guide").json()
    assert data["markdown"].startswith("#")
    assert "Qwen Image Runner" in data["markdown"]
    assert data["version"]
