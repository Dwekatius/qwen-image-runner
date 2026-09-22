"""Qwen Image Runner — SQLite persistence (jobs, images) with migrations."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Any, Optional

from . import config

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    params TEXT NOT NULL,
    status TEXT NOT NULL,
    engine_job TEXT,
    progress TEXT,
    error TEXT,
    created REAL NOT NULL,
    started REAL,
    finished REAL
);
CREATE TABLE IF NOT EXISTS images (
    id TEXT PRIMARY KEY,
    job_id TEXT,
    path TEXT NOT NULL,
    thumb TEXT,
    width INTEGER,
    height INTEGER,
    mode TEXT,
    seed INTEGER,
    prompt TEXT,
    negative TEXT,
    params TEXT,
    created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_images_created ON images(created DESC);
CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    chat_id TEXT,
    role TEXT NOT NULL,
    text TEXT,
    image_id TEXT,
    job_id TEXT,
    meta TEXT,
    created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_created ON chat_messages(created DESC);
CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY,
    title TEXT,
    created REAL NOT NULL,
    updated REAL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            config.ensure_dirs()
            _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SCHEMA)
            _conn.commit()
            _migrate_chats(_conn)
        return _conn


def _migrate_chats(conn: sqlite3.Connection) -> None:
    """Add chat_id to existing databases and give legacy messages their own chat
    (moving those images into the chat's folder)."""
    try:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(chat_messages)").fetchall()]
        if "chat_id" not in cols:
            conn.execute("ALTER TABLE chat_messages ADD COLUMN chat_id TEXT")
            conn.commit()
        if "meta" not in cols:
            conn.execute("ALTER TABLE chat_messages ADD COLUMN meta TEXT")
            conn.commit()
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_chatid ON chat_messages(chat_id, created)"
        )
        conn.commit()
        orphan_count = conn.execute(
            "SELECT COUNT(*) AS c FROM chat_messages WHERE chat_id IS NULL"
        ).fetchone()["c"]
        if not orphan_count:
            return
        now = time.time()
        chat_id = new_id()
        first_user = conn.execute(
            "SELECT text FROM chat_messages WHERE role='user' AND text IS NOT NULL ORDER BY created ASC LIMIT 1"
        ).fetchone()
        title = (first_user["text"][:60] if first_user and first_user["text"] else "Previous chat")
        conn.execute(
            "INSERT INTO chats (id, title, created, updated) VALUES (?,?,?,?)",
            (chat_id, title, now, now),
        )
        conn.execute("UPDATE chat_messages SET chat_id=? WHERE chat_id IS NULL", (chat_id,))
        conn.commit()
        # move the legacy conversation's images into its own folder
        from . import storage
        rows = conn.execute(
            "SELECT DISTINCT i.id, i.path FROM images i "
            "JOIN chat_messages m ON m.image_id = i.id WHERE m.chat_id=?", (chat_id,)
        ).fetchall()
        for row in rows:
            try:
                new_path = storage.move_image_into_chat(row["path"], chat_id)
                if new_path and new_path != row["path"]:
                    conn.execute("UPDATE images SET path=? WHERE id=?", (new_path, row["id"]))
            except Exception:
                pass
        conn.commit()
    except Exception:
        pass


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------- jobs

def create_job(kind: str, params: dict) -> str:
    job_id = new_id()
    conn = connect()
    with _lock:
        conn.execute(
            "INSERT INTO jobs (id, kind, params, status, created) VALUES (?,?,?,?,?)",
            (job_id, kind, json.dumps(params), "queued", time.time()),
        )
        conn.commit()
    return job_id


def update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    conn = connect()
    cols = ", ".join(f"{k}=?" for k in fields)
    values = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in fields.values()]
    with _lock:
        conn.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*values, job_id))
        conn.commit()


def get_job(job_id: str) -> Optional[dict]:
    conn = connect()
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        return None
    job = dict(row)
    for key in ("params", "progress"):
        if job.get(key):
            try:
                job[key] = json.loads(job[key])
            except Exception:
                pass
    return job


def list_jobs(limit: int = 50) -> list[dict]:
    conn = connect()
    rows = conn.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for row in rows:
        j = dict(row)
        for key in ("params", "progress"):
            if j.get(key):
                try:
                    j[key] = json.loads(j[key])
                except Exception:
                    pass
        out.append(j)
    return out


def reconcile_on_start() -> int:
    """Mark any non-terminal jobs as interrupted (crash recovery)."""
    conn = connect()
    with _lock:
        cur = conn.execute(
            "UPDATE jobs SET status='interrupted', finished=? "
            "WHERE status IN ('queued','running','saving')",
            (time.time(),),
        )
        conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------- images

def add_image(**fields: Any) -> str:
    image_id = fields.pop("id", None) or new_id()
    fields["id"] = image_id
    fields.setdefault("created", time.time())
    fields.setdefault("params", "{}")
    if isinstance(fields["params"], (dict, list)):
        fields["params"] = json.dumps(fields["params"])
    conn = connect()
    keys = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    with _lock:
        conn.execute(f"INSERT INTO images ({keys}) VALUES ({marks})", tuple(fields.values()))
        conn.commit()
    return image_id


def get_image(image_id: str) -> Optional[dict]:
    conn = connect()
    row = conn.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
    if not row:
        return None
    img = dict(row)
    if img.get("params"):
        try:
            img["params"] = json.loads(img["params"])
        except Exception:
            pass
    return img


def list_images(limit: int = 60, offset: int = 0, kind: str | None = None) -> list[dict]:
    conn = connect()
    if kind:
        rows = conn.execute(
            "SELECT * FROM images WHERE json_extract(params,'$.mode')=? "
            "ORDER BY created DESC LIMIT ? OFFSET ?",
            (kind, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM images ORDER BY created DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    images = []
    for row in rows:
        img = dict(row)
        if img.get("params"):
            try:
                img["params"] = json.loads(img["params"])
            except Exception:
                pass
        images.append(img)
    return images


def delete_image(image_id: str) -> Optional[dict]:
    img = get_image(image_id)
    if not img:
        return None
    conn = connect()
    with _lock:
        conn.execute("DELETE FROM images WHERE id=?", (image_id,))
        conn.commit()
    return img


# ---------------------------------------------------------------- chats

def create_chat(title: str | None = None) -> dict:
    chat_id = new_id()
    now = time.time()
    conn = connect()
    with _lock:
        conn.execute(
            "INSERT INTO chats (id, title, created, updated) VALUES (?,?,?,?)",
            (chat_id, title or "New chat", now, now),
        )
        conn.commit()
    return get_chat(chat_id)


def get_chat(chat_id: str) -> Optional[dict]:
    conn = connect()
    row = conn.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
    return dict(row) if row else None


def latest_chat() -> Optional[dict]:
    conn = connect()
    row = conn.execute("SELECT * FROM chats ORDER BY updated DESC, created DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def list_chats(limit: int = 60) -> list[dict]:
    conn = connect()
    rows = conn.execute(
        "SELECT c.*, "
        " (SELECT COUNT(*) FROM chat_messages m WHERE m.chat_id=c.id AND m.image_id IS NOT NULL) AS image_count, "
        " (SELECT COUNT(*) FROM chat_messages m WHERE m.chat_id=c.id) AS message_count, "
        " (SELECT m.image_id FROM chat_messages m WHERE m.chat_id=c.id AND m.image_id IS NOT NULL "
        "  ORDER BY m.created DESC LIMIT 1) AS last_image_id "
        "FROM chats c ORDER BY c.updated DESC, c.created DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def touch_chat(chat_id: str) -> None:
    conn = connect()
    with _lock:
        conn.execute("UPDATE chats SET updated=? WHERE id=?", (time.time(), chat_id))
        conn.commit()


def set_chat_title_if_new(chat_id: str, text: str) -> None:
    conn = connect()
    row = conn.execute("SELECT title FROM chats WHERE id=?", (chat_id,)).fetchone()
    if row and (not row["title"] or row["title"] == "New chat"):
        title = (text or "New chat").strip()[:60] or "New chat"
        with _lock:
            conn.execute("UPDATE chats SET title=? WHERE id=?", (title, chat_id))
            conn.commit()


def delete_chat(chat_id: str) -> int:
    conn = connect()
    with _lock:
        conn.execute("DELETE FROM chat_messages WHERE chat_id=?", (chat_id,))
        cur = conn.execute("DELETE FROM chats WHERE id=?", (chat_id,))
        conn.commit()
        return cur.rowcount


def chat_image_ids(chat_id: str) -> list[str]:
    """Distinct image ids linked to a chat (no guaranteed order)."""
    conn = connect()
    rows = conn.execute(
        "SELECT DISTINCT image_id FROM chat_messages "
        "WHERE chat_id=? AND image_id IS NOT NULL",
        (chat_id,),
    ).fetchall()
    return [row["image_id"] for row in rows]


def add_chat_message(chat_id: str, role: str, text: str | None = None,
                     image_id: str | None = None, job_id: str | None = None,
                     meta: dict | None = None) -> str:
    message_id = new_id()
    conn = connect()
    with _lock:
        conn.execute(
            "INSERT INTO chat_messages (id, chat_id, role, text, image_id, job_id, meta, created) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (message_id, chat_id, role, text, image_id, job_id,
             json.dumps(meta) if meta else None, time.time()),
        )
        conn.execute("UPDATE chats SET updated=? WHERE id=?", (time.time(), chat_id))
        conn.commit()
    return message_id


def list_chat(chat_id: str, limit: int = 500) -> list[dict]:
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM (SELECT *, rowid AS _rid FROM chat_messages WHERE chat_id=? "
        "ORDER BY created DESC, rowid DESC LIMIT ?) ORDER BY created ASC, _rid ASC",
        (chat_id, limit),
    ).fetchall()
    messages = []
    for row in rows:
        message = dict(row)
        message.pop("_rid", None)  # rowid only orders the window, never exposed
        if message.get("meta"):
            try:
                message["meta"] = json.loads(message["meta"])
            except Exception:
                message["meta"] = None
        if message.get("image_id"):
            message["image"] = get_image(message["image_id"])
        messages.append(message)
    return messages


def last_chat_image(chat_id: str) -> Optional[dict]:
    conn = connect()
    row = conn.execute(
        "SELECT image_id FROM chat_messages WHERE chat_id=? AND image_id IS NOT NULL "
        "ORDER BY created DESC LIMIT 1",
        (chat_id,),
    ).fetchone()
    if not row or not row["image_id"]:
        return None
    return get_image(row["image_id"])


def clear_chat(chat_id: str | None = None) -> int:
    conn = connect()
    with _lock:
        if chat_id:
            cur = conn.execute("DELETE FROM chat_messages WHERE chat_id=?", (chat_id,))
        else:
            cur = conn.execute("DELETE FROM chat_messages")
        conn.commit()
        return cur.rowcount
