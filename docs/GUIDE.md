# Qwen Image Runner — Guide

A local, chat-first studio for **Qwen-Image-2.1**. Everything runs on your own PC: no accounts, no
cloud, no telemetry. This guide is also available inside the app (**Guide** tab).

> Unofficial project — not affiliated with, endorsed by, or connected to Alibaba/Qwen.

## Quick start

1. Run `Install.bat` (once). It creates the Python environment and downloads the engine build.
2. Run `Launch.bat` (or the desktop shortcut). The app opens in its own window.
3. On first run: accept the licenses, pick a **compute backend**, download the model files, start the engine.

Full details, including prerequisites and how to install dependencies by hand: `docs/INSTALL.md`.

## Chat (the main workflow)

Describe an image and send it. The result appears in the conversation and stays there.

- **Follow-ups edit the last image.** Type “make it wear sunglasses” and the previous image is edited —
  the scene, subject and lighting are kept.
- **New images need a hint.** Start with *generate / create / draw / new image* and the app makes a
  fresh image instead of editing. The context bar above the input always shows which mode will be used
  (“Editing the image above” / “Starting a new image”).
- **New chat** (`＋ New chat`) opens a fresh conversation. Every chat keeps its messages and its own
  images, and you can reopen any of them from the sidebar.
- **Delete a chat** with the **✕** on its sidebar entry or **Delete chat** in the chat header. The chat
  and the images it generated (gallery entries, files and thumbnails) are removed; copies you made with
  **Save as…** are kept.
- Every result has **Save as…**, **Use as input** and **Reuse settings**.
- Progress is real: you see the actual step count, seconds per step and elapsed time. Queued jobs
  cancel instantly; an active generation stops by reloading the model (the button says so).

## Prompt assistant (DeepSeek) - optional

*Settings → Prompt assistant (DeepSeek)*, or the **Prompt assistant** section in the right-hand panel.

Paste a DeepSeek API key, tick **DeepSeek prompts** (or **Let DeepSeek write the image prompts** in
Settings), press **Save**, then **Test connection**. The stored key is never shown again — the field
reads `•••••••• saved (…hint)` and typing replaces it. From then on every chat message goes to
DeepSeek first:

- it decides whether you want a **new image** or an **edit of the last one**,
- it writes the actual image prompt (subject, composition, lighting, style) - that prompt is what the
  image model receives, and you can read it in the chat right under your message,
- if you are only asking a question or brainstorming, it **answers in the chat** and no image is made.

Details:

- The key is stored locally in `settings.json` (gitignored) and is sent only to the provider you
  configure. No telemetry, no third party.
- Defaults are DeepSeek (`https://api.deepseek.com`, `deepseek-chat`). Any OpenAI-compatible endpoint
  works - change *Base URL* and *Model*.
- The app never sends the key back to the browser; Settings only shows a masked hint (`...464d`).
- If the assistant is unreachable, generation still works: the app falls back to your raw prompt and
  notes the failure in the chat.
- DeepSeek bills per token on your own account; a typical prompt rewrite is a few hundred tokens.

## Settings profiles & Auto mode

The **Settings profile** section in the right-hand panel decides who owns the generation settings
(size, steps, CFG, sampler, batch, transparency):

- **Auto** (default) — the prompt assistant adjusts the settings for each prompt and the app reports
  what was used in the chat as *✨ AI settings: …*. Selecting Auto resets the fallback settings to the
  app baseline (1024×1024, 40 steps, CFG 6), not to the last profile's values. It needs DeepSeek
  prompts enabled with an API key; the panel says so until then. The **Generation settings** block
  starts collapsed in Auto mode and shows a summary of the values it is about to use.
- **Manual (current)** — your values are used exactly as entered; the model never changes them. Editing
  any control in the panel switches the profile to Manual automatically.
- **Saved profiles** — **Save as…** stores the current defaults under a name, **Update** overwrites the
  active one and **Delete** removes it (falling back to Auto). Switching a profile applies its saved
  values to the panel immediately.

## Generate view

For precise work outside a conversation.

- **Size presets** from a 1024×1024 draft up to native 2K, or a custom size (multiples of 32).
- **Steps, CFG, sampler, seed** (leave the seed at `-1` for a random one; the resolved seed is stored
  with the image), **negative prompt**, **batch** (rendered as separate jobs with consecutive seeds).
- **Transparent** produces a real RGBA image; the preview shows a checkerboard where it is transparent.
- Each result has an action row underneath: **Save as…**, **Edit this image**, **Reuse settings**.

## Edit view

- Add reference images: “Use as input” from the gallery/chat, or **＋ Add images** to upload your own.
- Describe the change. One and two reference images are verified; up to 10 are accepted.
- A comparison slider shows before/after.

## Gallery

Every image, newest first, with its full effective parameters. Actions: use as input, reuse settings,
save as, delete. The sidebar history list appears here (it is hidden in Chat, where the conversation is
the history).

## Save as

Images are saved automatically inside the app's `outputs/` folder, and **Save as…** opens the real
Windows save dialog so you can put a copy anywhere you like (chat cards, gallery cards, and under the
generated image in the Generate view).

## Settings

- **Engine backend** — switch between CUDA / Vulkan / CPU and install builds you do not have yet.
- **Start engine automatically** when the app opens.
- **Storage** — where the engine, models, outputs and database live.
- **Logs** (top bar) — the engine's own log, useful when something fails.
- **Quit** — stops the engine and closes the service. Closing the window alone leaves the engine warm.

## Compute backends

| Backend | Who it is for | Extra download | Speed |
|---|---|---|---|
| **NVIDIA CUDA** (default) | NVIDIA GPUs | ~0.9 GB (includes CUDA runtime DLLs) | 1024×1024 in ~50 s (RTX 5070 Ti, 20 steps) |
| **Vulkan** | AMD / Intel / other GPUs | ~32 MB | tens of seconds to a few minutes per image |
| **CPU only** | machines without a usable GPU | ~17 MB | very slow — see below |

### Running without a GPU (CPU mode)

CPU mode works and produces the same images, but it is **very slow**. Measured on a Ryzen 5 5600G
(6 cores / 12 threads, 128 GB RAM, Q8 model) at 512×512:

| | measured |
|---|---|
| Prompt encoding (text + vision encoder) | ≈ 4 minutes |
| Sampling | **128 s per step** (≈ 8.5 min for 4 steps) |
| Total for a 512×512, 4-step image | ≈ 9 minutes |

Scaling is roughly linear in pixels, so 1024×1024 is about 4× slower (~8.5 min **per step**) and
1536×1536 / 2048×2048 are impractical.

Practical advice for CPU:

- Stay at **512×512**, use **4–8 steps**.
- Prompt encoding alone takes minutes — batch your ideas instead of iterating quickly.
- A smaller quant (Q6_K / Q5_0 / Q4_K) reduces memory traffic and speeds things up further; download it
  into `models/diffusion/` and point `settings.json → engine.diffusion_model` at it.
- More CPU cores help; close other applications and make sure the machine is plugged in / not thermal
  throttling.
- If you have any modern GPU (even integrated), try **Vulkan** first — it is usually much faster than CPU.

The app shows a warning in the Engine panel whenever the CPU backend is active, and the size hint
switches to CPU timings. The **GPU / CPU** segmented toggle in the right-hand panel also switches the
engine backend directly: it picks an installed GPU backend (CUDA first, then Vulkan) and never
downloads anything — install or switch builds in *Settings → Engine backend*.

## Model files

Model weights are **not** shipped with the app. The first-run setup downloads them from Hugging Face
after showing the licence terms, with resume support and SHA-256 verification:

| File | Size | Licence |
|---|---|---|
| `qwen_image_2.1-Q8_0.gguf` (diffusion) | 7.7 GB | Qwen Research License |
| `Qwen3VL-8B-Instruct-Q4_K_M.gguf` (text encoder) | 5.0 GB | Apache-2.0 |
| `mmproj-Qwen3VL-8B-Instruct-F16.gguf` (vision, for editing) | 1.2 GB | Apache-2.0 |
| `qwen_image_2.1_vae_bf16.safetensors` (VAE) | 0.7 GB | Qwen Research License |

Total ≈ 14.6 GB. The Qwen Research License allows research/evaluation use; commercial use needs
separate permission from Alibaba.

## Where things are stored

```
engine/       engine builds (one folder per backend) + downloaded archives
models/       model weights
outputs/      your images, including outputs/chats/<chat-id>/ per conversation
inputs/       reference images you upload
thumbnails/   gallery thumbnails
data/canvas.db  chats, messages, images and job history (SQLite)
logs/         app + engine logs
settings.json your settings (backend, defaults, licence acceptance)
```

## Performance reference

Measured on the RTX 5070 Ti 16 GB with the default Q8 build and CUDA backend:

| Size | Steps | Time |
|---|---|---|
| 1024 × 1024 | 20 | ~47 s |
| 1024 × 1024 | 40 | ~85 s |
| 1536 × 1536 | 20 | ~101 s |
| 2048 × 2048 | 40 | ~10.6 min |

A single edit with one reference takes roughly 110–214 s at 1024×1024.

## Troubleshooting

| Symptom | What to do |
|---|---|
| Engine stuck on “Loading…” | The first start reads ~13 GB from disk. Later starts take seconds. |
| “Engine: Failed” | Open **Logs**. Usually the engine build is missing (Settings → Engine backend → Install) or antivirus quarantined `sd-server.exe` (restore it and re-run `Install.bat`). |
| Out of memory at 1536²/2048² | Stay at or below 1536² on a 16 GB GPU; keep CPU offload enabled (default for CUDA). |
| Very slow generation | Check which backend is active in the Engine panel. CPU mode is expected to be slow. |
| Port already in use | The app uses 7878, the engine 1235. LM Studio's own server uses 1234, so they can coexist. |
| UI looks outdated after an update | Reload once (`Ctrl+R`); the frontend is served no-store, so this only happens for windows already open during the update. |
| “Save as…” doesn't appear | It opens on the machine running the app and blocks until you choose a location or cancel. |

## Licences

- App code: **PolyForm Noncommercial 1.0.0** — free for personal, educational, research and nonprofit
  use; commercial use and monetisation are not permitted.
- Model weights: **Qwen Research License** (see above).
- Engine: [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) (MIT).

## About this project

This software was generated by an AI agent (Claude in pi) working under human supervision and
direction — architecture, code, tests and documentation. Every feature was verified on real hardware
before being claimed: measurements, screenshots and known limitations are recorded in
`docs/validation/`.
