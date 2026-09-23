# Changelog

All notable changes to this project are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project uses semantic versioning.

## [Unreleased]

### Changed

- **Relicensed to GPL-3.0** — the app code moved from PolyForm Noncommercial 1.0.0 to the GNU
  General Public License v3: use, modify, fork and share it freely, but any version you distribute
  must stay GPL-3.0 with its source available, so it cannot become a closed, paid product. The
  Qwen model weights keep their own research/evaluation terms and are never bundled.

### Fixed

- Progress no longer sits on 'Queued…' during a render — the panel now shows 'Rendering…' while the
  engine works (this engine build does not emit per-step progress; real step counts still show when
  available).
- Desktop shortcut now carries the app logo: `Install.bat` points the shortcut's icon at the new
  multi-size `Logo.ico`, and the app serves a `favicon.ico` fallback next to the SVG favicon.
- Suggested image filenames fall back to `qwen-image-runner` instead of the old `local-canvas` name.

## [1.2.0] — 2026-09-22

### Added

- **Settings profiles & Auto mode** — the right-hand panel can now save named profiles of the generation
  defaults (size, steps, CFG, sampler, batch, transparency) and switch between them:
  - **Auto** (default) lets the prompt assistant adjust the settings per prompt, starting from the app
    baseline — *1024×1024 · 40 steps · CFG 6*, not the last profile — and reports what it used in the
    chat as **✨ AI settings: …**;
  - **Manual (current)** and saved profiles keep your values exactly as entered; the model never
    changes them, and editing any control switches the panel to Manual automatically;
  - profiles are stored in `settings.json` (gitignored), sanitized and clamped on save, and exposed at
    `/api/profiles`, `/api/profiles/{id}` and `/api/profiles/active`.
- **Delete chats (with cleanup)** — delete a chat from the **✕** on its sidebar entry or **Delete chat**
  in the chat header. The confirmation dialog removes the chat's messages, its gallery images, its files
  under `outputs/chats/<chat-id>/` and their thumbnails; **Save as…** copies you made elsewhere are never
  touched. `DELETE /api/chats/{chat_id}?delete_images=false` keeps the images instead.
- **Right-panel quick controls** — settings profile, prompt-assistant toggle with a masked DeepSeek key
  field (*•••••••• saved (…hint) - type to replace*), a GPU/CPU segmented toggle that switches the engine
  backend, and a collapsible **Generation settings** block that shows a `1024×1024 · 40 steps · cfg 6.0`
  summary and starts collapsed in Auto mode.

### Changed

- **Expert prompt assistant** — rewritten system prompt: the assistant now structures scenes
  (subject → setting → camera → lighting → style/palette), follows Qwen-Image's text-rendering
  strengths (exact quoted text, placement and lettering style), prefers positive phrasing over
  negations, describes quality through technique instead of “masterpiece / 8k”, and replies with strict
  single-line JSON that includes four worked examples.
- **Assistant-chosen generation settings** — `/api/chat/submit` accepts `auto_settings`; when DeepSeek is
  enabled, the assistant's `settings` object is sanitized/clamped, merged into the job and returned as
  `assistant_settings` for the chat. Manual and saved profiles ignore it. The assistant also receives
  the current defaults as a hint so it only changes what serves the prompt.
- `config.load_settings()` normalizes `defaults` back to the app baseline whenever `profiles.active` is
  `auto`, so stale manual values cannot leak into Auto.

### Fixed

- Assistant replies in chat no longer leave a phantom progress card, and DeepSeek now only starts an
  image job when the user actually asks for one — greetings and questions are answered in the chat.
- Chat history is ordered deterministically (`created` + rowid), so messages created in the same second
  keep their real order.

## [1.1.0] — 2026-09-22

### Added

- **Prompt assistant (DeepSeek)** — optional chat model in front of the image model:
  - routes each chat message through DeepSeek, which decides **new image vs edit**, writes the image
    prompt (shown in the chat under your message) and can **answer questions** without generating;
  - configured in Settings: API key, model, base URL (any OpenAI-compatible endpoint) and a
    **Test connection** button; the key is stored locally in `settings.json` (gitignored) and is never
    sent back to the browser (only a masked hint is shown);
  - fully non-blocking: if the assistant fails, the raw prompt is used and the failure is noted in the chat.
- **CPU-only and Vulkan backends** — the app can install and switch engine builds in
  *Settings → Engine backend*: NVIDIA CUDA (default), Vulkan (AMD/Intel) and CPU. CPU mode was measured
  and documented (128 s/step at 512×512 on a 6-core Ryzen), the UI warns about it, the size hint switches
  to CPU timings and a “CPU draft · 512×512” preset was added.
- **Guides** — a **Guide** tab inside the app (renders `docs/GUIDE.md`) plus `docs/INSTALL.md` with
  prerequisites, the dependency list, manual installation and checksum verification.
- **Project identity** — renamed to **Qwen Image Runner** (app, launchers `Launch.bat` / `Stop.bat`,
  package, environment variables), with the project logo (PNG + hand-drawn vector SVGs) in the app and
  the repository.
- Repository hygiene: `.gitattributes`, issue + PR templates, topics, private vulnerability reporting
  and Dependabot enabled.
- An explicit note that the project is **AI-generated under human supervision**, in the README, the
  Guide and the release notes.

### Fixed

- Settings text and password inputs were not themed (white system inputs) — now consistent with the UI.
- The engine's per-backend binary path, arguments and error messages are backend-aware, and switching
  backends restarts the engine with the right build.

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
