# Qwen Image Runner — v1.0: Local image web UI

**Revised 2026-09-21 · Initial model: Qwen-Image-2.1**

## 1. Release scope

Build a clean, LM Studio–style Windows web app that dwekat can use to generate and edit images locally. Start with Qwen-Image-2.1 and target Q8_0 diffusion weights on the RTX 5070 Ti with 16 GB VRAM.

**v1.0 is the working image UI. v2.0 adds external APIs and AI control.** The separate [PLAN_V2.md](PLAN_V2.md) contains all integration work. v1.0 ships independently of it.

| v1.0 includes | Deferred to v2.0 |
|---|---|
| Generate, Edit, Gallery, Settings | Documented external REST API |
| Model installation, loading, and tested presets | OpenAI-compatible endpoints |
| Persistent results, inputs, and settings | MCP and pi/other AI clients |
| Reliable launch, stop, and recovery | Headless automation and multi-client ownership |
| Minimal local server needed by the browser | Integration dependencies, setup cards, and documentation |

Private browser requests remain necessary for a web app. They are internal implementation details, not a supported external API. Do not build an API product or agent scaffolding in v1.0.

Working name: **Qwen Image Runner**, with Qwen-Image-2.1 used descriptively as the supported model. Retire Qwen Canvas: the model license restricts Qwen as a primary product identifier. Name/repository availability remains unverified. [S7]

## 2. Architecture

- Python 3.11, FastAPI, uvicorn, httpx, Pillow, python-multipart.
- HTML/CSS and vanilla JavaScript ES modules; separate UI, state, canvas, and gallery modules. No Node requirement for users.
- SQLite for jobs, inputs, and gallery; versioned settings.
- One owned stable-diffusion.cpp sd-server process behind a small EngineAdapter.
- App bound to 127.0.0.1:7878; engine explicitly bound to 127.0.0.1:1235.
- Chrome app-mode window when available; standard browser fallback.
- Windows + NVIDIA is the v1.0 release platform.

```text
Launch.bat -> local application -> browser UI
                          |
               jobs / inputs / gallery / settings
                          |
                    EngineAdapter
                          |
                 sd-server -> GPU / offload
```

Keep model components, defaults, and validated controls in a profile so other image models can be added later. v1.0 supports the tested Qwen package; it does not promise arbitrary GGUF compatibility or require a generic plugin system.

The engine's built-in compatibility routes remain internal, unsupported details. Do not advertise direct engine access or proxy arbitrary routes as a v1.0 feature.

## 3. Pinned engine and model files

Candidate engine: release **master-889-c678dfe**, commit **c678dfe704a2230342376b46add9c8ca736a653d**; asset **sd-master-c678dfe-bin-win-cuda12-x64.zip**. Matching runtime asset if needed: **cudart-sd-bin-win-cu12-x64.zip**. Validate this candidate in Phase 0, then record the tested release and published SHA-256 digests in engine.json. A driver supporting CUDA does not prove runtime DLLs are installed. Checksums do not establish executable signing; make no signed-binary claim without verification. [S1]

**Target configuration locked by the owner (2026-09-21): Q8_0 diffusion + Q4_K_M encoder + VAE, with both projectors (F16 default, Q8_0 tested alternative).** System VRAM was freed before Phase 0; re-check free memory immediately before every benchmark. Approximate download sizes use decimal GB/MB; runtime memory reports use explicit MiB/GiB.

| Component | Filename | Size |
|---|---|---|
| Default diffusion | qwen_image_2.1-Q8_0.gguf | 7.69 GB |
| Default encoder | Qwen3VL-8B-Instruct-Q4_K_M.gguf | 5.03 GB |
| Editing projector (default) | mmproj-Qwen3VL-8B-Instruct-F16.gguf | 1.16 GB |
| Editing projector (tested alt) | mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf | 0.75 GB |
| Required VAE | qwen_image_2.1_vae_bf16.safetensors | 676 MB |
| Optional tested encoder | Qwen3VL-8B-Instruct-Q8_0.gguf | 8.71 GB |

Sources: diffusion [S9], encoder/projector [S10], VAE [S11]. The previous BF16 projector filename was incorrect. The default package is approximately **14.6 GB of downloads**, not a peak-VRAM calculation.

Before implementing downloads, models.json must pin repository revisions, exact paths, byte counts, hashes, component licenses, and compatible profiles. Obtain missing hashes from pinned artifact metadata. Verify lower-quant filenames before offering them; do not silently substitute models or use moving main URLs as reproducible pins.

## 4. Verified limitations and performance targets

| Finding | Required behavior |
|---|---|
| **Confirmed:** active cancellation returns HTTP 409 (`"job is currently generating and cannot be interrupted yet"`); queued cancel returns 200 | Queued cancellation plus explicitly labeled stop/reload for active inference |
| **Confirmed: real per-step progress exists in sd-server stdout** (`\r`-updated `|====| 12/40 - 2.35s/it`) | UI progress bar driven by parsed engine stdout (steps + s/it + elapsed). No invented values. |
| Reference/init images are documented as RGB | **Tested: alpha inputs are accepted and flattened to RGB** — no transparent-layer editing; only transparency *output* is supported |
| Masks, strength, and reference fields are generic | **Tested: mask edits change the masked region but corrupt the unmasked area → mask UI deferred** |
| Model-level support includes transparency and up to 10 references | **Tested: 1- and 2-reference edits work; transparency output verified (α 1–15 background). Advertise only these.** |
| **New: 2048² VAE decode OOMs without offload** (decode graph 40 GB; auto-tiling insufficient because DiT stays resident) | **Ship `--offload-to-cpu --diffusion-fa` as the default working configuration** (measured ~1 % speed cost) |
| **New: all decodes are auto-tiled by the engine** (1024²→32 px, 1536²→48 px, 2048²→64 px tiles) | No action needed; decode 4.5–13.5 s |

**Phase 0 results (2026-09-21) — Q8 PROVEN.** Measured on the target machine with the locked configuration: 1024² = 102 s, 1536² = 274 s, 2048² = 634 s (offload; without offload 2048² fails at decode). 20-step fast preset = 51 s. 1-ref edit 214 s, 2-ref edit 368 s. Peak VRAM 12.6 GB, peak RAM 12.7 GiB. **SageAttention enabled by default (measured A/B: −10 % at 1024², −30 % at 1536² — see `docs/validation/v1-report.md`).** Full evidence: `docs/validation/phase0-report.md`.

Sources: model card [S3], pinned API [S4], cancellation source [S5]. Generic engine flags are insufficient proof of each model feature.

Audit-confirmed hardware: RTX 5070 Ti, 16,303 MiB VRAM, driver 596.36, Python 3.11.9. VRAM usage was 1,511 MiB at that moment. Recheck available memory before benchmarking. The prior CPU/RAM and free-disk figures require reconfirmation.

Start testing with Euler, CFG 6, 40 steps, dimensions divisible by 32, and automatic resolution-dependent flow scheduling. These are baseline settings, not a guarantee against invalid output. [S2]

Measure cold/warm Q8 generation at 1024², 1536², and 2048², one/two-reference edits, total latency, peak VRAM, and system RAM where available. Test flash attention, offloading, VAE tiling, and a reserved-headroom memory budget before selecting defaults. Compute buffers, caches, and other GPU applications consume memory beyond weight files. [S6]

**Q8 on 16 GB is a target awaiting proof.** Never silently downgrade it. Offer tested lower resolutions/quants explicitly after OOM and store the effective configuration. Q4 success cannot satisfy a Q8 acceptance test. **Owner rule (2026-09-21): if the locked Q8 configuration proves unusable (OOM or impractically slow) in Phase 0, stop and report with recorded evidence — no downgrade without explicit approval.** Always record *why* (peak VRAM, peak RAM, wall time, per-step time, cold vs warm) so decisions are evidence-based.

Disk checks include archives/extraction, partial downloads, extra quants, rollback copies, inputs, and outputs. Remove the unconditional under-25-GB claim.

## 5. UI and workflows

Use a readable dark theme with model/status/load controls at the top, Generate/Edit/Gallery navigation on the left, image canvas/results in the center, a prompt composer, and a small parameter panel. Status shows actual job state, elapsed time, queue depth, and useful persistent errors. Keep protocol details and raw engine flags out of ordinary user flows.

Required workflows:

1. **Generate:** prompt, tested size/aspect presets, seed, steps, preview/zoom, and download. Default to one output; up to four outputs run as sequential jobs with separate seeds.
2. **Edit:** upload or reuse an image, enter an instruction, and compare before/after. Validate at least one/two references; display only the tested maximum.
3. **Gallery:** persisted full-resolution outputs/thumbnails, filtering, effective settings, reuse parameters, delete, and reopen saved editing inputs after restart.
4. **Settings:** model installation/selection, downloads/loading, storage, unload, logs, and licenses. No API/MCP/pi configuration in v1.0.

Ctrl+Enter generates; text entry must not trigger single-letter shortcuts.

Conditional controls:

- Native 2K presets require successful measured Q8 tests at those sizes.
- Transparent PNG generation requires real alpha values surviving saving, preview, and download. Show a checkerboard when supported.
- Transparent-layer editing requires a separate alpha-input round-trip test; RGBA output alone is insufficient.
- Mask painting/annotations require verified polarity, coordinates, resizing, reference association, and visible edit behavior.
- Strength, cache, sampler, and higher reference-count options appear only after validation.

Basic generation and editing are mandatory. Unsupported advanced controls remain absent and documented as deferred. Failed Q8/2K targets require an explicit recorded scope/engine decision before release claims.

## 6. Setup, lifecycle, and state

Install.bat checks prerequisites, creates a venv, installs locked dependencies, and prepares the pinned engine/runtime. Launch.bat opens the UI promptly; loading is visible inside it. First run presents actual model terms, component sizes, resumable downloads, and a smoke generation at settings proved in Phase 0. Never present placeholders as generated results.

Use one downloader for setup and UI. Validate range/resume responses and hashes; finalize files atomically. Incomplete/corrupt files cannot be selected. Missing Python/runtime prerequisites receive clear instructions. Test paths with spaces/non-ASCII characters and use direct process arguments rather than shell commands assembled from prompts.

A second launch reuses the verified application instance through a lock and identity/readiness check. A matching port alone is not ownership. Never kill an unrelated process to free a port.

**Closing the browser leaves the app running.** Reopening reconnects. Explicit **Quit app** stops owned work, engine, and application; provide Stop.bat for stopping it after closing the window. Warn when quitting would discard active work. Track owned processes and use bounded graceful-stop/child cleanup.

Bound crash restarts; pause pending work after failure. No infinite restart loops or silent reruns. Model changes must not silently alter queued work.

### Jobs and recovery

Use one authoritative application queue and one in-flight engine job. Persist jobs/inputs before dispatch and retain the engine job ID.

States: queued -> running -> saving -> completed, with failed/cancelled/interrupted outcomes. Completion requires durable output and database recording.

- Cancel queued work without stopping the model.
- Label active stopping **Stop generation — reloads model**. Stop the owned engine, retain any completed result, mark unfinished work accurately, and pause the remaining queue before reload/resume.
- After a crash, reconcile saved/partial results, mark unresolved active jobs interrupted, and offer Resume/Retry without automatically duplicating work.
- Poll real status. SSE may relay state changes but cannot create nonexistent step progress. Reconnection fetches a current snapshot. Downloads may show measured byte progress.

### Persistence

Use SQLite from the first working generation, with migrations and transactions. Retain original/effective parameters, resolved seeds, component hashes, engine build/backend, sampling settings, dimensions, and timing. Save uploaded references/masks under stable IDs so edit history remains usable.

Write outputs atomically and keep originals separate from thumbnails. Database history is authoritative. Make prompt inclusion in exported metadata visible; a PNG extension/metadata flag does not establish alpha preservation. Do not promise identical pixels across differing hardware/drivers/builds.

### Local protection

Validate Host/Origin and protect browser mutations with session/CSRF controls. Verify the engine port separately: wrapper protection does not cover requests that bypass it. Address unsafe engine access before public distribution.

Use managed asset IDs, constrained storage roots, traversal checks, and bounds on upload bytes, decoded pixels, dimensions, references, and queue size. No arbitrary read/delete interface. Rotate logs, omit secrets/full image payloads, and keep prompts/images local. Explicit installation downloads use the network.

## 7. Repository and releases

```text
PLAN.md, PLAN_V2.md
README.md, LICENSE, THIRD_PARTY_LICENSES.md, SECURITY.md, CHANGELOG.md
pyproject.toml, dependency lock
engine.json, models.json
Install.bat, Launch.bat, Stop.bat
backend/                 # local app, adapter, supervisor, jobs, storage
frontend/                # modular browser UI
scripts/, tests/, docs/validation/
engine/, models/, inputs/, outputs/, data/, logs/, test-artifacts/
settings.json
```

**No git initialization, publishing, badges, or governance work during the v1 build (owner decision 2026-09-21) — build first; publishing is revisited when v1 is usable.** Runtime files, weights, user content, settings, and private test artifacts stay out of any future VCS. No MCP dependency/module or pi extension ships in v1.0.

Updates select an application release and tested manifests, preserving data and rollback configuration; never independently pull latest engine/unbounded dependencies. Uninstall first stops the app and identifies external storage explicitly; never silently purge user-selected folders.

## 8. Implementation phases

| Phase | Work | Exit condition |
|---|---|---|
| 0. Engine proof | Actual **sd-server** generation/editing at the locked Q8 config, both edit projectors, runtime/files, alpha/masks, jobs API, cold/warm memory + timing with resource recording | Recorded evidence (`docs/validation/`, `test-artifacts/`); capability profile validated; **stop & report** if Q8 unusable |
| 1. Working slice | Minimal launch/stop, browser prompt, adapter, queue, SQLite, storage | Real browser result survives restart |
| 2. Daily generation | Parameters, presets, serial outputs, stop/reload, gallery | Repeated generation and recovery through UI |
| 3. Editing | Upload/reuse, instruction edits, comparison, proved controls | Two-reference edit; inputs reusable after restart |
| 4. Setup and polish | Installer/downloads, wizard, settings, docs | Clean Windows setup reaches an image from README/UI |
| 5. Verify and release | Browser/recovery checks, benchmarks, manifests, licensing | v1.0 gates pass; v1.0.0 ready |

Phase 0 must test **sd-server**, not merely sd-cli. Record exact configuration/hashes, requests/responses, representative images, cold/warm memory and latency, cancellation outcomes, alpha output versus input behavior, and each advertised reference count. Additionally record for every run: component hashes, wall time, per-step timing if emitted by logs, **peak VRAM (sampled) and peak system RAM**, and raw logs — the owner requires resource evidence to explain slow runs. Failed required capabilities stop dependent UI work until resolved. Mock images, CLI-only success, or a lower quant cannot substitute for advertised behavior.

Use bounded resource tests and simulated OOM rather than arbitrarily huge GPU allocations. Add meaningful checks during each phase. Remove speculative line-count/hour estimates and mandatory subagent choreography from the implementation specification.

## 9. Acceptance criteria

- Clean setup, download resume/hash failures, missing prerequisites, and disk checks work.
- Launch, duplicate launch, close/reopen, Quit, and stop helper leave no orphan engine.
- Real browser generation/editing, controls, effective settings, and history work after restart.
- Q8 is measured at every advertised Q8 preset on the target GPU; unsupported targets are resolved explicitly.
- One/two-reference edits work; every enabled transparency/mask feature passes its own round-trip test.
- Serial outputs, queued cancellation, active stop/reload, model changes, and crash recovery have accurate states.
- Engine failure, OOM, full disk, invalid uploads, and port conflicts produce useful errors without loops/data loss.
- Generate/Edit/Gallery/Settings pass interaction and screenshot review, including narrower windows.
- Local protection, storage boundaries, release docs, manifests, and license statements are verified.

Use MockEngine tests for queue/storage/recovery/UI and a local fixture server for downloads. Model the engine's missing step progress and active cooperative cancellation honestly. CI does not download weights. Windows is the release gate; optional Linux mock tests do not prove other GPU/platform support.

Browser tests must be reproducible without a private pi extension. A clean folder is not a clean-machine test: validate setup in a clean Windows user/VM and inference on the target GPU.

## 10. Licensing and deferred work

Retain application code under **PolyForm Noncommercial 1.0.0**, labeled **source-available**. Summarize actual permitted purposes/organizations; remove blanket corporate bans and unconditional personal-use promises. [S8]

Qwen-Image-2.1 limits its noncommercial grant to research/evaluation and requires separate permission for commercial use. App licensing cannot expand model permissions. Present the actual terms before downloads and record licenses per component. Keep descriptive model references and an unofficial-project disclaimer. [S7]

Inventory actual third-party licenses/notices; do not assume every dependency is MIT or separate processes remove obligations. Do not bundle weights. Inbound/outbound contribution terms do not automatically grant commercial relicensing rights over others' work; address rights before relying on that ability.

Maintain basic release/security docs alongside code. Badges, templates, governance, and cross-platform installers must not delay a usable personal app. This plan does not publish a repository.

**All external APIs, OpenAI compatibility, MCP, pi, agent image delivery, headless automation, and integration cards are reserved for [v2.0](PLAN_V2.md).**

Other models, LoRA management, prompt enhancement, HiRes, video, native wrapping, light theme, command palette, mirrors, Docker/PyPI, and auto-update feeds are separate future decisions, not automatic v2.0 requirements.

## Sources and status

Checked during the 2026-09-21 audit. **No project inference benchmarks have been run yet.** Recheck mutable model/license listings when pinning downloads.

[S1]: https://github.com/leejet/stable-diffusion.cpp/releases/expanded_assets/master-889-c678dfe
[S2]: https://raw.githubusercontent.com/leejet/stable-diffusion.cpp/c678dfe/docs/qwen_image_2.1.md
[S3]: https://huggingface.co/Qwen/Qwen-Image-2.1
[S4]: https://raw.githubusercontent.com/leejet/stable-diffusion.cpp/c678dfe/examples/server/api.md
[S5]: https://github.com/leejet/stable-diffusion.cpp/blob/c678dfe/examples/server/routes_sdcpp.cpp
[S6]: https://raw.githubusercontent.com/leejet/stable-diffusion.cpp/c678dfe/docs/performance.md
[S7]: https://huggingface.co/Qwen/Qwen-Image-2.1/raw/main/LICENSE
[S8]: https://polyformproject.org/licenses/noncommercial/1.0.0
[S9]: https://huggingface.co/leejet/Qwen-Image-2.1-GGUF
[S10]: https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF/tree/main
[S11]: https://huggingface.co/Comfy-Org/Qwen-Image-2.1/tree/main/vae

**Status: v1.0 COMPLETE + PUBLISHED (2026-09-22)** — https://github.com/Dwekatious/qwen-image-runner — all Phase 1–5 exit criteria met; application + engine validation in `docs/validation/v1-report.md` and `docs/validation/phase0-report.md`. Repository hygiene, CI, third-party license inventory, screenshots and clean-room verification are in place; the mechanical publishing steps are listed in `docs/PUBLISHING.md` (nothing published yet). External integrations (REST/OpenAI/MCP/pi) remain deferred to v2.0 per `PLAN_V2.md`.
