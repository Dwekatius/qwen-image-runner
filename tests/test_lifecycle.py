"""Window-lifecycle tests: heartbeat/closing endpoints, tracker logic and the setting.

These tests never trigger a real shutdown: the monitor is inert until a window actually
connects and the ``app_module`` fixture resets the tracker (and the SHUTDOWN event) per test.
"""
from __future__ import annotations


def _token(client) -> str:
    return client.get("/api/meta").json()["csrf"]


def _post_without_csrf_header(client, path: str, payload: dict):
    """Browser beacons cannot set X-CSRF; remove it from the client defaults for this call."""
    saved = client.headers.pop("X-CSRF", None)
    try:
        return client.post(path, json=payload)
    finally:
        if saved is not None:
            client.headers["X-CSRF"] = saved


def _new_tracker():
    from backend.main import WindowLifecycle

    return WindowLifecycle()


# ------------------------------------------------------------------ endpoints
def test_lifecycle_ping_accepts_body_token_without_csrf_header(client):
    r = _post_without_csrf_header(client, "/api/lifecycle/ping", {"id": "win-1", "token": _token(client)})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}


def test_lifecycle_closing_accepts_body_token_without_csrf_header(client):
    r = _post_without_csrf_header(client, "/api/lifecycle/closing", {"id": "win-1", "token": _token(client)})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}


def test_lifecycle_rejects_a_wrong_token(client):
    for path in ("/api/lifecycle/ping", "/api/lifecycle/closing"):
        r = _post_without_csrf_header(client, path, {"id": "win-1", "token": "not-the-real-token"})
        assert r.status_code == 403, (path, r.text)


def test_lifecycle_rejects_a_missing_token(client):
    for path in ("/api/lifecycle/ping", "/api/lifecycle/closing"):
        r = _post_without_csrf_header(client, path, {"id": "win-1"})
        assert r.status_code == 403, (path, r.text)


def test_lifecycle_still_enforces_the_host_check(client):
    r = client.post("/api/lifecycle/ping", json={"id": "win-1", "token": _token(client)},
                    headers={"Host": "evil.example"})
    assert r.status_code == 403, r.text


def test_lifecycle_endpoints_update_the_tracker(client, app_module):
    token = _token(client)
    client.post("/api/lifecycle/ping", json={"id": "win-x", "token": token})
    assert "win-x" in app_module.WINDOW.sessions
    assert app_module.WINDOW.ever_connected is True

    client.post("/api/lifecycle/closing", json={"id": "win-x", "token": token})
    assert "win-x" not in app_module.WINDOW.sessions
    assert app_module.WINDOW._idle_since is not None
    assert app_module.WINDOW.fired is False


# ------------------------------------------------------------------ tracker logic
def test_ping_registers_a_window_and_blocks_shutdown():
    w = _new_tracker()
    w.ping("win-1", now=100.0)
    assert w.ever_connected is True
    assert w.sessions == {"win-1": 100.0}
    assert w.evaluate(105.0, enabled=True) is False  # fresh session keeps the app alive
    assert w.fired is False


def test_closing_one_of_two_windows_keeps_the_app_alive():
    w = _new_tracker()
    w.ping("win-1", now=0.0)
    w.ping("win-2", now=0.0)
    w.closing("win-1", now=1.0)
    assert w.sessions == {"win-2": 0.0}
    assert w._idle_since is None
    w.ping("win-2", now=5.0)  # the surviving window keeps pinging
    assert w.evaluate(7.0, enabled=True) is False
    assert w.fired is False


def test_last_window_closed_fires_once_after_the_grace_period():
    w = _new_tracker()
    w.ping("win-1", now=10.0)
    w.closing("win-1", now=20.0)
    assert w.sessions == {}
    assert w._idle_since == 20.0

    assert w.evaluate(20.0 + w.IDLE_GRACE - 0.01, enabled=True) is False
    assert w.fired is False

    assert w.evaluate(20.0 + w.IDLE_GRACE, enabled=True) is True
    assert w.fired is True
    assert w.evaluate(200.0, enabled=True) is False  # fires exactly once


def test_ping_cancels_a_pending_shutdown_reload_safe():
    w = _new_tracker()
    w.ping("win-1", now=0.0)
    w.closing("win-1", now=10.0)
    w.ping("win-1", now=12.0)  # reload lands inside the grace window
    assert w._idle_since is None
    assert w.evaluate(20.0, enabled=True) is False
    assert w.fired is False


def test_disabled_setting_never_shuts_down():
    w = _new_tracker()
    w.ping("win-1", now=0.0)
    w.closing("win-1", now=1.0)
    assert w.evaluate(10_000.0, enabled=False) is False
    assert w.fired is False


def test_never_connected_headless_start_never_shuts_down():
    w = _new_tracker()
    assert w.evaluate(0.0, enabled=True) is False
    assert w.evaluate(10_000.0, enabled=True) is False
    assert w.ever_connected is False
    assert w.fired is False


def test_stale_session_is_pruned_and_counts_as_closed():
    w = _new_tracker()
    w.ping("win-1", now=100.0)
    t = 100.0 + w.HEARTBEAT_STALE_AFTER + 0.5
    assert w.evaluate(t, enabled=True) is False
    assert w.sessions == {}
    assert w._idle_since == t

    assert w.evaluate(t + w.IDLE_GRACE - 0.01, enabled=True) is False
    assert w.evaluate(t + w.IDLE_GRACE, enabled=True) is True
    assert w.fired is True


def test_hidden_tab_throttling_does_not_look_stale():
    """Chrome throttles hidden tabs to ~1 ping/min, so a 150 s gap must stay alive."""
    w = _new_tracker()
    w.ping("win-1", now=100.0)

    # 150 s without a ping is inside the throttling budget: still a live session.
    assert w.evaluate(250.0, enabled=True) is False
    assert w.sessions == {"win-1": 100.0}
    assert w.fired is False

    # 200 s is past HEARTBEAT_STALE_AFTER: prune, then the usual grace period applies.
    assert w.evaluate(300.0, enabled=True) is False
    assert w.sessions == {}
    assert w._idle_since == 300.0
    assert w.evaluate(300.0 + w.IDLE_GRACE - 0.01, enabled=True) is False
    assert w.evaluate(300.0 + w.IDLE_GRACE, enabled=True) is True
    assert w.fired is True


# ------------------------------------------------------------------ settings
def test_quit_on_window_close_defaults_to_on(client):
    assert client.get("/api/settings").json()["app"]["quit_on_window_close"] is True


def test_quit_on_window_close_roundtrip(client):
    off = client.put("/api/settings", json={"app": {"quit_on_window_close": False}})
    assert off.status_code == 200, off.text
    assert off.json()["app"]["quit_on_window_close"] is False
    assert client.get("/api/settings").json()["app"]["quit_on_window_close"] is False

    on = client.put("/api/settings", json={"app": {"quit_on_window_close": True}})
    assert on.status_code == 200, on.text
    assert client.get("/api/settings").json()["app"]["quit_on_window_close"] is True
