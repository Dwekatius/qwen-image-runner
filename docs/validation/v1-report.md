# Qwen Image Runner v1.0 — Validation Report

**Date:** 2026-09-21 · **Build:** v1.0.0 · **Machine:** RTX 5070 Ti 16 GB · Ryzen 5 5600G · 128 GB RAM · Windows

## Verdict

**v1.0 is complete and functional.** All Phase 1–5 exit criteria from `PLAN.md` were met: real browser generation and editing, persistence across restarts, honest stop semantics, model setup wizard, gallery, settings, and lifecycle scripts. Engine behavior was first proven in `phase0-report.md`; this report covers the application layer.

## What was built

| Component | Status |
|---|---|
| FastAPI backend (127.0.0.1:7878) + engine supervisor (sd-server, 127.0.0.1:1235) | ✅ |
| Job queue (one worker, one in-flight engine job) + SQLite persistence + crash reconciliation | ✅ |
| Server-Sent Events with **real step progress parsed from engine stdout** | ✅ |
| LM Studio–style UI: sidebar / canvas / parameter panel (dark, no build step) | ✅ |
| Generate workflow (sizes, steps, CFG, sampler, seed, batch, negative prompt, transparency) | ✅ |
| Edit workflow (reuse from gallery, upload, instruction, before/after compare slider) | ✅ |
| Gallery + history with thumbnails, metadata, reuse settings, use-as-input, delete | ✅ |
| Setup wizard: license gate, component status, resumable downloads, engine start | ✅ |
| Settings + engine logs modals, quit; CSRF + Host/Origin protection | ✅ |
| Install.bat / Launch.bat / Stop.bat + desktop shortcut, single-instance reuse | ✅ |
| MockEngine (`QCANVAS_FAKE_ENGINE=1`), 7 pytest tests, pinned `engine.json` / `models.json` | ✅ |

## Automated tests — 7/7 passed

`pytest`: meta + CSRF enforcement, generate→gallery→file→thumb→delete flow, queued cancellation
(`marked` → `cancelled`, no-op on finished jobs), edit validation, transparent prompt wrapping,
settings round-trip, downloader **resume + SHA-256** against a local Range-capable fixture server.

## Browser E2E (Chrome, real engine, real generations)

| Check | Result |
|---|---|
| Setup wizard, license gate, component badges, engine start | ✅ (screenshot `01-setup.png`) |
| Generate 1024²/20 steps via UI | ✅ 51 s; result + meta chips (`seed`, steps, CFG, sampler, time) |
| **Live progress** | ✅ "Step 9 / 20 · 2.31 s/it · elapsed 29s" + determinate bar |
| Engine returns to Ready after completion | ✅ |
| Resolved seed captured for `seed=-1` runs | ✅ (e.g. seed 31411 written to DB + chips) |
| Edit via gallery "Use as input" | ✅ red paisley bandana added, rest of image preserved |
| Two-reference edit (fox + puppy) combined scene | ✅ completed through app API |
| Batch ×2 | ✅ jobs completed with consecutive seeds 500/501 |
| Transparent generation | ✅ 48.9 % of pixels α<16; checkerboard stage + "alpha" chip |
| Gallery, history, filters, settings modal (real paths + storage inventory), logs modal | ✅ (screenshots `gallery.png`, `03-settings.png`) |
| Stop semantics | ✅ active stop → HTTP 409 passthrough → engine reloaded; job = **interrupted**, "stopped by user (engine reloaded)"; engine ready again in 3 s |
| Persistence | ✅ gallery/history/config survive app restart; unfinished jobs marked interrupted |
| Lifecycle | ✅ launcher reuses a running instance; `stop.py` graceful quit in ~2.2 s **with an open SSE connection**; cold start works; no orphan engine/wrapper processes |
| Installer | ✅ `Install.bat` idempotent, creates desktop shortcut |

## Measured performance (app defaults: Q8_0 + Q4_K_M encoder, Euler, CFG 6, `--offload-to-cpu --sage-attn`)

**SageAttention A/B (measured 2026-09-21, sampling time from engine logs):**

| Test | without sage | with sage | gain |
|---|---|---|---|
| 1024² × 20 steps | 46.06 s | **41.37 s** | −10 % |
| 1024² × 40 steps | 85.18 s | **77.64 s** | −9 % |
| 1536² × 20 steps (mean of 2 runs each) | 132.35 s | **92.85 s** | **−30 %** |

Visually identical output (mean pixel diff 1.1/255 at 1024²); the engine auto-falls back to flash attention for unsupported layers. 2048² with sage was not measured (est. scan ~30 % gain, ~7–8 min).

| Size | Steps | Sampling | Approx. wall |
|---|---|---|---|
| 1024² | 20 | 41 s | ~47 s |
| 1024² | 40 | 78 s | ~85 s |
| 1536² | 20 | 93 s | ~101 s |
| 1536² | 40 | ~186 s (est., 2 × 20) | ~3.3 min |
| 2048² | 40 | 617 s (no sage, Phase 0) | ~10.6 min |
| Edit, 1 ref | 20–40 | — | ~110–214 s |

Peak VRAM ≈ 12.6 GB; peak server RAM ≈ 12.7 GiB. UI shows honest per-step rate and elapsed time; the estimate hint is derived from these measurements.

## Known limitations (proven, documented, not hidden)

1. **Mask editing is broken in the engine build** (unmasked regions are corrupted) → not exposed in the UI.
2. **RGBA inputs are flattened** → no transparent-layer editing; transparency *output* works.
3. **Active generation cannot be cooperatively cancelled** by the engine → "Stop generation — reloads model" (measured: engine back in ~3 s warm).
4. **2048² takes ~10.6 minutes** at 40 steps — native 2K is a "coffee break" operation.
5. Occasional speckle artifacts observed with the Q8 build at 20 steps (visible on the puppy image); not blocking, could be sampler/quant related.

## Evidence

- Screenshots: `test-artifacts/v1-ui/` (setup, gallery, settings, progress)
- Engine evidence: `docs/validation/phase0-report.md`, `test-artifacts/phase0/`
- Hashes: `test-artifacts/phase0/hashes.txt`; manifests: `engine.json`, `models.json`
- Logs: `logs/app.log`, `logs/engine.log`

## Post-release addition — Chat & Save As (2026-09-22)

**Chat workflow (default view):** conversation-style generation and refinement.
- Server-side conversation state (`chat_messages` table), persisted across restarts.
- Intent detection: a message with no generate keywords after an image exists → **edit the last image**; explicit words like "generate/create/draw/new image" → fresh generation; the UI shows an "Editing the image above / Starting a new image" context bar with a one-click toggle.
- Every assistant result is a card with **Save as…**, Use as input, Reuse settings; progress renders as a live step/s-it/elapsed card inside the conversation; failures/cancellations appear as notes in the thread.

**Native Save As:** `POST /api/images/{id}/save_as` opens the real Windows save dialog (Win32 `comdlg32.GetSaveFileNameW`, no browser download quirks) and copies the PNG to the chosen location. Available on every chat card, every gallery card, and in the Generate view's action row under the image.

**UI additions (2026-09-22):** `＋ New chat` button in the sidebar (clears the conversation with confirmation and focuses the input); Generate view action row under the result: `Save as… · Edit this image · Reuse settings` (`test-artifacts/v1-ui/09-generate-actions.png`).

**Chat UX fixes (2026-09-22, after first user feedback):**
- Scrolling is continuous and stable: the message list preserves the reader's scroll position across live updates and only auto-scrolls when already at the bottom (verified with a 16-message conversation: 5,050 px of scrollable history, wheel scrolling checked — `test-artifacts/v1-ui/10-chat-scroll.png`).
- The sidebar HISTORY list is hidden while in Chat view — the chat *is* the history there (it remains available in Generate/Edit/Gallery).
- The Generate view now states "New image every time — use Chat to edit with context" with a clickable link, to prevent the (observed) confusion where follow-up prompts like "add X to this image" were typed into Generate and therefore produced unrelated new images (`chat=false` in the job log, no reference passed).

**Multiple conversations + per-chat image folders (2026-09-22):**
- `＋ New chat` **creates** a conversation — no confirmation, nothing is deleted. Previous chats stay in the sidebar **Chats** list (title set from the first message, image count, timestamp) and can be reopened at any time.
- Every chat's images live in their own repo folder: `outputs/chats/<chat_id>/`. Non-chat generations keep using `outputs/YYYY-MM-DD/`.
- Existing installation migrated automatically: the earlier single conversation became its own chat with its images moved into `outputs/chats/<id>/` (`test-artifacts/v1-ui/11-chats-list.png`).
- Chat messages are scoped per conversation in SQLite (`chats` table + `chat_messages.chat_id`), so each chat edits only its own last image.

**Robustness fixes (2026-09-22, after a "missing or invalid CSRF token" report):**
- The CSRF token is now **persisted in `settings.json`** and stays stable across app restarts (previously a restart invalidated every open window's token). Verified identical before/after restarts.
- The UI **self-heals** if a token ever rotates: on a 403 CSRF rejection it fetches the fresh token from `/api/meta` and retries the action once. Verified live: token rotated under an open page → "＋ New chat" still succeeded.
- The frontend is served with `Cache-Control: no-store, must-revalidate`, so the browser can never run a stale UI bundle again (root cause of both the earlier "missing Chat tab" and the ineffective retry).

Verified:
- pytest 9/9 — new: chat generate→edit→generate intent routing, message persistence, clear; save-as export copy (test mode).
- Live Chrome E2E: "a golden retriever puppy sitting in a library" → image in chat; "make it wear sunglasses" → auto-**edit** with the previous image as reference (job `mode=edit`, refs populated) → sunglasses result in the same thread; context bar and "New image" toggle working (`test-artifacts/v1-ui/07-chat-edit.png`).
- Native dialog verified end-to-end: clicking **Save as…** opened `Save image - Qwen Image Runner` (Win32 dialog, backend pid), the file was written to the chosen Desktop path and re-opened as a valid 1024×1024 RGBA PNG.
