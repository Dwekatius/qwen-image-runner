# Contributing to Qwen Image Runner

Thanks for your interest! This is a small, focused project — an unofficial local image studio for
Qwen-Image-2.1 on Windows + NVIDIA.

## Ground rules

- **Do not commit** model weights, engine binaries, generated images, local databases, logs, or
  `settings.json`. They are covered by `.gitignore` — keep it that way.
- The project license is **PolyForm Noncommercial 1.0.0**. By contributing you agree that your
  contribution is licensed under the same terms.
- Keep the app **local-only**: no telemetry, no network calls except the explicit model/engine
  downloads the user triggers.

## Development setup

```bat
Install.bat                     REM creates .venv, installs deps, fetches the pinned engine
.venv\Scripts\python.exe -m pytest -q
```

You do **not** need a GPU or the model weights to develop the UI/backend: the test suite and a
MockEngine mode run everything locally.

```bat
set QCANVAS_FAKE_ENGINE=1
.venv\Scripts\python.exe -m backend.main
```

then open http://127.0.0.1:7878 — the engine is simulated (instant startup, fake progress,
placeholder images), so the whole UI is exercisable on any machine.

## Layout

| Path | What it is |
|---|---|
| `backend/` | FastAPI app, engine supervisor, job queue, SQLite persistence, downloads, save dialog |
| `frontend/` | Vanilla ES-module UI (no build step) |
| `scripts/` | bootstrap, launcher, stopper, and the Phase-0 validation tooling |
| `tests/` | pytest suite (runs against MockEngine + a local fixture HTTP server) |
| `docs/` | architecture/validation reports |
| `engine.json`, `models.json` | pinned engine/model artifacts (size + SHA-256) |

## What we look for in a PR

- Tests for new behaviour (`python -m pytest -q` must stay green).
- Honest UX: never invent progress, never silently downgrade quality, label destructive actions.
- No new runtime dependencies unless they are well maintained and permissively licensed.
- Keep the UI clean and quiet — it is meant to feel like a desktop app, not a dashboard.

## Reporting bugs

Include: what you did, what you expected, what happened, plus the contents of the **Logs** dialog
(engine log) and your GPU/driver. Screenshots help a lot.
