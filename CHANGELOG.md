# Changelog

All notable changes to this project are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project uses semantic versioning.

## [1.0.0] — 2026-09-22

First release: a local, LM Studio–style studio for running **Qwen-Image-2.1 (Q8 GGUF)** on a
16 GB NVIDIA GPU, with generation, instruction editing, chat, gallery and a native save dialog.

### Added

- **Chat-first workflow** — conversations are the primary interface; each result stays in the thread,
  follow-ups (“make it wear sunglasses”) edit the last image, and “New image” starts a fresh
  generation instead. Intent is routed server-side; the UI shows which mode will be used.
- **Multiple conversations** — “＋ New chat” creates a new chat without deleting anything; every chat
  keeps its own messages and images (`outputs/chats/<chat-id>/`) and can be reopened from the sidebar.
- **Generate view** — size presets (draft 1024² → native 2K), steps, CFG, sampler, seed, negative
  prompt, batch (sequential seeds), transparent-background toggle.
- **Edit view** — up to 10 references (1 and 2 verified), instruction editing, before/after comparison.
- **Gallery & history** — thumbnails, full parameters, reuse-settings, use-as-input, delete.
- **Native “Save as…”** — Win32 save dialog on every chat card, gallery card, and under the generated
  image in the Generate view.
- **Real progress** — step count, s/it rate and elapsed time parsed from the engine’s own output;
  queued jobs cancel instantly, active jobs stop via an honestly-labelled engine reload.
- **First-run setup** — license presentation, component status, resumable SHA-256-verified downloads.
- **Setup/launch scripts** — `Install.bat`, `Launch.bat`, `Stop.bat`, desktop shortcut,
  single-instance reuse, clean shutdown (including with an open event stream).
- **Pinned engine & models** — `engine.json` / `models.json` with sizes and checksums; engine release
  `master-889-c678dfe` (stable-diffusion.cpp) validated on RTX 5070 Ti.
- **MockEngine mode** (`QCANVAS_FAKE_ENGINE=1`) so the whole app and test suite run without a GPU.

### Performance (RTX 5070 Ti 16 GB, Q8_0 + Q4_K_M encoder, Euler, CFG 6, `--offload-to-cpu --sage-attn`)

- 1024² × 20 steps ≈ 47 s · 1024² × 40 ≈ 85 s · 1536² × 20 ≈ 101 s · 2048² × 40 ≈ 10.6 min
- SageAttention measured A/B: −10 % at 1024², −30 % at 1536²
- Peak VRAM ≈ 12.6 GB · peak engine RAM ≈ 12.7 GiB

### Fixed

- 2048² generation failed at the VAE decode stage without CPU offload → offload is now the default.
- Engine stdout reader blocked on partial lines (startup appeared to hang) → fixed with non-blocking reads.
- Active “stop” could be reported as a 404 failure instead of an interrupted job → stop/reload path
  is now coordinated and reported honestly.
- CSRF token rotation on restart broke open windows → token is persisted; the UI also self-heals by
  refreshing the token and retrying once.
- Browser could serve a stale UI after an update → the frontend is now served `no-store`.
- Chat list reset scroll position when new images arrived → scroll position is preserved.

### Known limitations (verified, intentionally not shipped)

- Mask-based local editing corrupts unmasked areas (engine behaviour) — no mask UI.
- RGBA inputs are flattened to RGB — transparency *output* works, transparent-layer editing does not.
- Active generation cannot be cooperatively cancelled by the current engine build — the UI reloads
  the model instead, and says so.
- 2048² takes ~10.6 minutes at 40 steps on the tested GPU.
