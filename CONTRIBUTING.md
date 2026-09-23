# Contributing

**This project does not accept external contributions.** Qwen Image Runner is a personal,
source-available project: the repository is maintained by its owner alone, and **pull requests are
closed without review**. There is no CLA to sign and no contribution process to follow.

You are still very welcome to:

- **Download and run** it for whatever you like — the app code is GPL-3.0.
- **Fork it** and adapt it to your own needs under the license below.
- **Report bugs or share ideas** in the issue tracker — reports are read, but fixes and features
  are implemented only by the owner, at their discretion.

## Ground rules

- **Do not commit** model weights, engine binaries, generated images, local databases, logs, or
  `settings.json`. They are covered by `.gitignore` — keep it that way.
- The app code is licensed under the **GNU GPL v3** ([LICENSE](LICENSE)): use it, modify it, fork
  it, share it. If you distribute your version it must stay GPL-3.0 with its source available —
  nobody can turn it into a closed, paid product. The **model weights** keep their own terms
  (Qwen Research License) and are never bundled with the code.
- Keep the app **local-only**: no telemetry, no network calls except the explicit model/engine
  downloads the user triggers.

## Development setup (for forks and local builds)

```bat
Install.bat                     REM creates .venv, installs deps, fetches the pinned engine
.venv\Scripts\python.exe -m pytest -q
```

You do **not** need a GPU or the model weights to work on the UI/backend: the test suite and a
MockEngine mode run everything locally.

```bat
set QIR_FAKE_ENGINE=1
.venv\Scripts\python.exe -m backend.main
```

then open http://127.0.0.1:7878 — the engine is simulated (instant startup, fake progress,
placeholder images), so the whole UI runs on any machine.

## Layout

| Path | What it is |
|---|---|
| `backend/` | FastAPI app, engine supervisor, job queue, SQLite persistence, downloads, save dialog |
| `frontend/` | Vanilla ES-module UI (no build step) |
| `scripts/` | bootstrap, launcher, stopper, and the validation tooling |
| `tests/` | pytest suite (runs against MockEngine + a local fixture HTTP server) |
| `docs/` | architecture/validation reports |
| `engine.json`, `models.json` | pinned engine/model artifacts (size + SHA-256) |

## Bug reports

Include: what you did, what you expected, what happened, plus the contents of the **Logs** dialog
(engine log) and your GPU/driver. Screenshots help a lot. Bug reports are welcome; code changes
are not accepted.
