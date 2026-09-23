# Publishing checklist

> **Status: PUBLISHED** — https://github.com/Dwekatius/qwen-image-runner (v1.0.0 tag + release,
> created 2026-09-22). The steps below are kept as a record and for future releases.

## 1. Name

| Option | Notes |
|---|---|
| `qwen-canvas` | proposed; verify it is still free on GitHub |
| `qwen-image-studio` | fallback |
| anything else | avoid implying official affiliation with Alibaba/Qwen |

Repo description suggestion:

> Source-available local studio for Qwen-Image-2.1 — chat-first generation & editing with a native save dialog (unofficial)

Topics: `qwen-image`, `stable-diffusion-cpp`, `gguf`, `local-first`, `text-to-image`, `image-editing`, `fastapi`, `windows`

## 2. First commit

Runtime data is already excluded by `.gitignore` (verified: 48 source files, no models/engine/outputs/data/venv).

```bat
git init
git add -A
git status --short          REM sanity check: no models/, engine/, outputs/, data/, logs/, settings.json
git commit -m "Qwen Image Runner 1.0.0"
```

## 3. GitHub

1. Create the repository (public) — **do not** let GitHub add a README/LICENSE (they exist).
2. Push: `git remote add origin <url> && git push -u origin main`
3. **Issues** on; **Security → Private vulnerability reporting** on (matches `SECURITY.md`).
4. CI runs automatically (`.github/workflows/ci.yml`: pytest on Windows + Ubuntu, Python 3.11/3.12,
   MockEngine — no GPU, no model downloads in CI).

## 4. Release

1. Tag and release `v1.2.0` — copy the `[1.2.0]` entry from `CHANGELOG.md` (v1.0.0 is already
   published; do not reuse that tag).
2. Release notes should repeat the model-license caveat (Qwen Research License; weights are *not*
   in the release — the app downloads them after showing the terms).

## 5. Wording rules (kept consistent across README / repo description)

- App code is **GPL-3.0** and OSI-approved: call it open source. The **model weights** are not open
  source — the Qwen Research License limits them to research/evaluation.
- Always include the disclaimer: *unofficial project, not affiliated with Alibaba/Qwen*.
- State the hardware assumption: Windows + NVIDIA, validated on RTX 5070 Ti 16 GB.

## 6. What a stranger needs

- Windows 10/11, NVIDIA GPU, Python 3.11+, ~25 GB free disk, internet for the one-time ~15.5 GB
  of engine + model downloads.
- `Install.bat` → `Launch.bat` → first-run wizard. No manual configuration required.

## Not planned for v1

External REST/OpenAI-compatible API, MCP server, pi/agent integration, headless automation, LoRA
management — see `PLAN_V2.md`. These are intentionally out of scope for the 1.0 release.
