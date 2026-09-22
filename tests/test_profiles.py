"""Settings profiles + AI-controlled settings tests (MockEngine, no GPU)."""
from __future__ import annotations

import json

from conftest import wait_job


def test_profiles_payload_starts_empty(client):
    data = client.get("/api/profiles").json()
    assert data["active"] == "auto"
    assert data["profiles"] == []
    assert data["assistant_ready"] is False
    assert data["effective"]["size"] == "1024x1024"
    assert data["effective"]["steps"] == 40


def test_profiles_assistant_ready_flag(client):
    assert client.get("/api/profiles").json()["assistant_ready"] is False
    client.put("/api/settings", json={"assistant": {"enabled": True, "api_key": "test"}})
    assert client.get("/api/profiles").json()["assistant_ready"] is True


def test_profiles_crud_roundtrip(client):
    created = client.post("/api/profiles", json={
        "name": "  Portrait  ",
        "defaults": {"size": "1536x1536", "steps": 55, "cfg": 7.5, "sampler": "euler",
                     "batch": 2, "transparent": True},
    }).json()
    pid = created["active"]
    assert pid.startswith("p_") and len(pid) == 10
    assert created["profiles"][0]["name"] == "Portrait"
    assert created["profiles"][0]["defaults"] == {
        "size": "1536x1536", "steps": 55, "cfg": 7.5, "sampler": "euler",
        "batch": 2, "transparent": True,
    }
    effective = client.get("/api/settings").json()["defaults"]
    assert effective["size"] == "1536x1536"
    assert effective["steps"] == 55

    updated = client.put(f"/api/profiles/{pid}", json={"name": "Portrait HD", "defaults": {"steps": 30}}).json()
    item = updated["profiles"][0]
    assert item["name"] == "Portrait HD"
    assert item["defaults"]["steps"] == 30
    assert item["defaults"]["size"] == "1536x1536"  # partial update keeps the rest
    assert client.get("/api/settings").json()["defaults"]["steps"] == 30

    assert client.put("/api/profiles/does-not-exist", json={"name": "x"}).status_code == 404

    deleted = client.delete(f"/api/profiles/{pid}").json()
    assert deleted["active"] == "auto"
    assert deleted["profiles"] == []
    assert client.delete(f"/api/profiles/{pid}").status_code == 404


def test_profiles_active_selection_and_unknown_404(client):
    pid = client.post("/api/profiles", json={
        "name": "Movie",
        "defaults": {"size": "2752x1536", "steps": 60, "cfg": 5.0, "sampler": "euler",
                     "batch": 1, "transparent": False},
    }).json()["active"]

    manual = client.post("/api/profiles/active", json={"id": "manual"}).json()
    assert manual["active"] == "manual"
    assert manual["effective"]["size"] == "2752x1536"  # keeps the current values

    again = client.post("/api/profiles/active", json={"id": pid}).json()
    assert again["active"] == pid
    assert again["effective"]["steps"] == 60

    auto = client.post("/api/profiles/active", json={"id": "auto"}).json()
    assert auto["active"] == "auto"
    # Auto resets to the app baseline, it does not keep the last profile's values
    assert auto["effective"] == {
        "size": "1024x1024", "steps": 40, "cfg": 6.0,
        "sampler": "euler", "batch": 1, "transparent": False,
    }
    persisted = client.get("/api/settings").json()["defaults"]
    assert persisted["size"] == "1024x1024"
    assert persisted["steps"] == 40

    assert client.post("/api/profiles/active", json={"id": "p_deadbeef"}).status_code == 404


def test_profiles_delete_active_restores_baseline(client):
    created = client.post("/api/profiles", json={
        "name": "Temporary",
        "defaults": {"size": "2048x2048", "steps": 55, "cfg": 7.5, "sampler": "euler",
                     "batch": 2, "transparent": True},
    }).json()
    pid = created["active"]
    assert client.get("/api/settings").json()["defaults"]["steps"] == 55

    deleted = client.delete(f"/api/profiles/{pid}").json()
    baseline = {"size": "1024x1024", "steps": 40, "cfg": 6.0,
                "sampler": "euler", "batch": 1, "transparent": False}
    assert deleted["active"] == "auto"
    assert deleted["profiles"] == []
    assert deleted["effective"] == baseline
    assert client.get("/api/settings").json()["defaults"] == baseline


def test_put_settings_defaults_ignored_while_auto(client):
    baseline = {"size": "1024x1024", "steps": 40, "cfg": 6.0,
                "sampler": "euler", "batch": 1, "transparent": False}
    client.post("/api/profiles/active", json={"id": "auto"})
    ignored = client.put("/api/settings", json={"defaults": {"steps": 55, "size": "2048x2048"}}).json()
    assert ignored["defaults"] == baseline
    assert client.get("/api/settings").json()["defaults"] == baseline
    assert client.get("/api/profiles").json()["effective"] == baseline

    # the client flips to manual before its debounced PUT, so that path still persists
    client.post("/api/profiles/active", json={"id": "manual"})
    saved = client.put("/api/settings", json={"defaults": {"steps": 55, "size": "2048x2048"}}).json()
    assert saved["defaults"]["steps"] == 55
    assert saved["defaults"]["size"] == "2048x2048"


def test_profiles_sanitize_bogus_defaults(client):
    created = client.post("/api/profiles", json={
        "name": "Bogus",
        "defaults": {"size": "garbage", "steps": 999, "cfg": 99, "sampler": "", "batch": 9,
                     "transparent": "yes"},
    }).json()
    defaults = created["profiles"][0]["defaults"]
    assert defaults["size"] == "1024x1024"   # unparseable -> keep the app default
    assert defaults["steps"] == 60           # clamped
    assert defaults["cfg"] == 10.0
    assert defaults["batch"] == 4
    assert defaults["sampler"] == "euler"
    assert defaults["transparent"] is True

    odd = client.post("/api/profiles", json={
        "name": "Odd", "defaults": {"size": "5000x100"},
    }).json()["profiles"][-1]["defaults"]
    assert odd["size"] == "4096x256"


def test_profiles_reject_bad_names(client):
    assert client.post("/api/profiles", json={"name": "   ", "defaults": {}}).status_code == 400
    assert client.post("/api/profiles", json={"name": "x" * 41, "defaults": {}}).status_code == 400


def test_parse_reply_extracts_and_clamps_settings():
    from backend import assistant

    parsed = assistant.parse_reply(json.dumps({
        "action": "generate", "prompt": "x",
        "settings": {"size": "2048x2048", "steps": 999, "cfg": 99, "transparent": True},
    }))
    assert parsed["settings"] == {"size": "2048x2048", "steps": 60, "cfg": 10.0, "transparent": True}

    malformed = assistant.parse_reply(json.dumps({
        "action": "generate", "prompt": "x",
        "settings": {"size": "garbage", "steps": "lots", "cfg": None, "transparent": "yes"},
    }))
    assert malformed["settings"] == {}

    assert assistant.parse_reply('{"action":"generate","prompt":"x"}')["settings"] == {}

    clamped = assistant.parse_reply(json.dumps({
        "action": "generate", "prompt": "x",
        "settings": {"size": "5000x5000", "steps": 3, "cfg": 0.5},
    }))
    assert clamped["settings"] == {"size": "4096x4096", "steps": 10, "cfg": 1.0}


def test_build_messages_includes_current_settings_hint():
    from backend import assistant

    messages = assistant.build_messages([], "more effort please", False,
                                        {"size": "1536x1536", "steps": 55, "cfg": 7.5})
    assert "Current settings: 1536x1536, 55 steps, cfg 7.5" in messages[-1]["content"]
    plain = assistant.build_messages([], "more effort please", False)
    assert "Current settings" not in plain[-1]["content"]


def test_assistant_settings_apply_only_when_auto(client, monkeypatch):
    from backend import assistant as assistant_mod

    calls: list = []

    async def fake_run(settings, history, user_text, has_last_image, current=None):
        calls.append(current)
        return {
            "action": "generate", "prompt": "x", "reply": "",
            "settings": {"size": "2048x2048", "steps": 55, "cfg": 7.5},
        }

    monkeypatch.setattr(assistant_mod, "run", fake_run)
    client.put("/api/settings", json={"assistant": {"enabled": True, "api_key": "test"}})

    chat = client.post("/api/chats", json={}).json()["chat"]
    res = client.post("/api/chat/submit", json={
        "text": "make the best apple ever", "chat_id": chat["id"], "auto_settings": True,
        "params": {"width": 512, "height": 512, "steps": 8, "cfg": 3.0},
    }).json()
    assert res["assistant_settings"] == {"size": "2048x2048", "steps": 55, "cfg": 7.5}
    assert calls[0] is not None
    assert calls[0]["steps"] == 40  # the current defaults travel as a hint

    job = wait_job(client, res["job"])
    assert job["status"] == "completed"
    assert (job["params"]["width"], job["params"]["height"]) == (2048, 2048)
    assert job["params"]["steps"] == 55
    assert job["params"]["cfg"] == 7.5
    # chat always runs a single image per prompt (batch is popped by submit_batch)
    chat_jobs = [j for j in client.get("/api/jobs").json()["jobs"]
                 if j["params"].get("chat_id") == chat["id"]]
    assert len(chat_jobs) == 1

    messages = client.get(f"/api/chat?chat_id={chat['id']}").json()["messages"]
    assert messages[0]["meta"]["assistant_settings"]["size"] == "2048x2048"

    # manual (auto_settings off): the client's values win untouched
    res2 = client.post("/api/chat/submit", json={
        "text": "generate a small apple", "chat_id": chat["id"], "auto_settings": False,
        "params": {"width": 512, "height": 768, "steps": 8, "cfg": 3.0},
    }).json()
    assert res2["assistant_settings"] is None
    assert calls[1] is None
    job2 = wait_job(client, res2["job"])
    assert job2["status"] == "completed"
    assert (job2["params"]["width"], job2["params"]["height"]) == (512, 768)
    assert job2["params"]["steps"] == 8
    assert job2["params"]["cfg"] == 3.0

    # assistant disabled: settings are ignored even when auto_settings is on
    client.put("/api/settings", json={"assistant": {"enabled": False}})
    res3 = client.post("/api/chat/submit", json={
        "text": "generate a tiny apple", "chat_id": chat["id"], "auto_settings": True,
        "params": {"width": 512, "height": 512, "steps": 8, "cfg": 3.0},
    }).json()
    assert res3["assistant_settings"] is None
    assert len(calls) == 2
