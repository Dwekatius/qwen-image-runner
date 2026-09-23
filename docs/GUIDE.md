# Qwen Image Runner — Guide

A local, chat-first studio for **Qwen-Image-2.1**. Everything runs on your own PC: no accounts, no
cloud, no telemetry. This guide is also available inside the app (**Guide** tab).

> Unofficial project — not affiliated with, endorsed by, or connected to Alibaba/Qwen.

**New here?** Follow Steps 1–4 in order — they take you from an empty folder to your first image.
Everything after that is reference material you can read when you need it.

## What this is and what you get

Qwen Image Runner installs a small local service and opens a studio window in your browser. It runs
the Qwen-Image-2.1 image model on your own hardware, so your prompts and pictures stay on your
machine.

- **Chat** — describe an image and refine it in plain language; the conversation keeps every result.
- **Generate** — a simple form for one image with exact settings (size, steps, CFG, seed, batch).
- **Edit** — change an existing image with a written instruction and reference images.
- **Gallery** — every image you have made, with the parameters that produced it.
- **Native Save as…** — the real Windows save dialog on every result.
- **Local-only** — the app binds to `127.0.0.1`, stores everything on disk and sends nothing anywhere. The optional DeepSeek prompt assistant is the one exception, and only if you turn it on.

### Requirements

| Requirement | Notes |
|---|---|
| **Windows 10 or 11 (64-bit)** | The launchers and the pinned engine builds are Windows-specific. |
| **Python 3.11 or newer** | [python.org/downloads](https://www.python.org/downloads/) — tick **“Add python.exe to PATH”** during setup. Verify with `python --version`. |
| **A GPU — NVIDIA recommended** | NVIDIA CUDA is fastest. AMD/Intel GPUs work through **Vulkan**. **CPU-only works, but it is very slow** (measured: 128 s per step at 512×512). |
| **~25 GB free disk** | Engine ≈0.9 GB + all four model files ≈14.7 GB, plus room for your own images. |
| **16 GB RAM recommended** | With CUDA CPU-offload the engine peaks at ≈13 GB of RAM, so an 8 GB machine will swap heavily and be very slow. |
| **Internet** | Only for the one-time downloads. Nothing is sent anywhere afterwards. |

Model weights are **not** bundled with the app. They download inside the app on first run, after you
accept the licence terms, with resume support and SHA-256 verification.

## Step 1 — Get the app

Open a terminal and clone the repository:

```bat
git clone https://github.com/Dwekatius/qwen-image-runner.git
cd qwen-image-runner
```

**No Git?** On the repository page click the green **Code** button, choose **Download ZIP**, then
right-click the downloaded archive and choose **Extract All**. The extracted folder works the same.

**Tip:** put the folder somewhere simple, for example `C:\QwenImageRunner`. Avoid OneDrive-synced
folders — the model files are large and sync clients can block or slow down the downloads.

## Step 2 — Install

Double-click **`Install.bat`** (or run it from a terminal). It does four things:

1. checks that Python is installed and on `PATH`, and refuses to continue on versions older than 3.11,
2. creates a private virtual environment in `.venv/` — nothing is installed system-wide,
3. installs the Python dependencies from `pyproject.toml` (`fastapi`, `uvicorn[standard]`, `httpx`, `pillow`, `python-multipart`),
4. downloads the pinned **stable-diffusion.cpp** engine build for the selected backend, verifies its SHA-256, extracts it under `engine/`, and creates the **Qwen Image Runner** desktop shortcut.

By default the CUDA build is installed. To start with a different one (you can add the others later
in **Settings → Engine backend → Install**):

```bat
set QIR_BACKEND=cpu
Install.bat
```

Accepted values: `cuda` (NVIDIA, default), `vulkan` (AMD/Intel), `cpu`.

### Prefer a terminal? Install by hand

These are the same steps, run from the project folder:

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e .          REM add [dev] to include pytest
.venv\Scripts\python.exe scripts\bootstrap.py         REM optional: fetch + verify the engine build too
.venv\Scripts\python.exe -m backend.main              REM serve the UI on http://127.0.0.1:7878
.venv\Scripts\python.exe scripts\stop.py              REM stop the service again
```

The models and any missing engine build can also be downloaded from the app's setup screen.
`docs/INSTALL.md` covers the manual download of every file (with URLs, sizes and checksums).

### If install fails

| Problem | Fix |
|---|---|
| `python` is not recognised | Re-install Python 3.11+ from [python.org](https://www.python.org/downloads/) and tick **Add python.exe to PATH**, or run `py -3 scripts\bootstrap.py`. |
| Python is older than 3.11 | The installer stops; install a newer Python and re-run `Install.bat`. |
| Antivirus quarantines `sd-server.exe` | It is a freshly downloaded executable from the upstream release. Allow/restore it (whitelisting the project folder helps), then re-run `Install.bat`. |
| Downloads keep failing behind a firewall or proxy | Allow Python through the firewall, or set the standard `HTTPS_PROXY` / `HTTP_PROXY` environment variables before running `Install.bat`. Downloads resume where they stopped, so re-running is safe. |

## Step 3 — First launch and first-run setup

Start the app with **`Launch.bat`**, or double-click the **Qwen Image Runner** shortcut that
`Install.bat` created. `Launch.bat` reuses a running instance, starts the local service in the
background and opens the studio in its own app window. The same UI is available at
`http://127.0.0.1:7878`.

The first launch shows a setup overlay. Work through it from top to bottom:

**1. Licences.** Read the terms and tick **“I understand and accept these terms”**. The app code is GPL-3.0; the Qwen-Image-2.1 weights (denoiser and VAE) are under the Qwen Research License (research/evaluation use), while the Qwen3-VL text encoder and vision projector are Apache-2.0. Nothing is downloaded before you accept, and the weights are never bundled with the app.

**2. Compute backend.** Pick what runs the model:

- **NVIDIA CUDA** (recommended for NVIDIA GPUs) — ~0.9 GB download, 1024×1024 in ~50 s on an RTX 5070 Ti.
- **Vulkan** (AMD/Intel and other GPUs) — ~32 MB download, tens of seconds to a few minutes per image.
- **CPU only** (no usable GPU) — ~17 MB download, very slow: measured 128 s per step at 512×512.

Click **Install** if a backend is marked “not installed”, and **Use** to select it. You can change or add more later in **Settings → Engine backend**.

**3. Model files.** Four files are needed, ~14.7 GB in total (see “The four model files, explained” below). Click **Download missing files**. The bar shows the current file and the running total; **Cancel** stops safely and the next attempt resumes where it left off. Every file is checked against its SHA-256 when it finishes.

**4. Start engine.** Click **Start engine**. The first start reads ~13 GB of weights from disk, so **Loading… (first start can take ~1 min)** is normal; later starts take seconds.

**5. Open studio.** The button enables once the required files are present and the engine is ready. The overlay disappears and you land in **Chat**.

The engine keeps running while you work. **`Stop.bat`** stops the app and unloads the model at any time; **Settings → Quit** does the same.

## Step 4 — Your first image

You land in **Chat**. Type a prompt in the box at the bottom, for example:

> a golden retriever puppy on a beach at sunset, photorealistic

Press **Send** (or **Enter**; **Shift+Enter** starts a new line). If the engine is not ready yet, the app tells you instead of silently failing.

What happens next, in order:

1. Your message appears in the conversation and a progress card appears below it.
2. The card shows real progress from the engine: **Step 9 / 40**, the seconds per step (s/it) and the elapsed time; then **Decoding image…**, then **Saving…**.
3. When it finishes, the image card appears with chips (size, mode, steps, seed) and three actions: **Save as…** (open the Windows save dialog and keep a copy anywhere), **Use as input** (send this image to the Edit view as a reference) and **Reuse settings** (copy the exact size, steps, CFG and sampler into the right-hand panel).
4. The file is stored automatically under `outputs/chats/<chat-id>/` (see “Where things are stored” below).

### Follow-ups edit the last image

Type **make it wear sunglasses** and send it. Because the conversation already has an image, the app
edits the image above instead of starting over — the scene, subject and lighting are kept. The small
context bar above the input shows **Editing the image above** with a thumbnail of what will be edited.

### Starting a new image instead

- Begin the message with a clear “new” word: **generate**, **create**, **draw**, **imagine**, **render**, **new image**, **new picture**, **fresh image** or **another image**.
- Or click the mode button in the context bar. It reads **New image** while you are editing and **Edit last image** once you have switched; the label next to it tells you what the next send will do (**Starting a new image** / **Editing the image above**).

## DeepSeek (optional, recommended)

The prompt assistant is an optional chat model that sits in front of the image model. It is strongly
recommended: it makes local generation noticeably better without changing how the image is made.

### Why turn it on

- It rewrites a rough idea into a much better image prompt (subject, composition, camera, light, style, exact text in the image) — Qwen-Image follows rich natural language far better than keyword lists.
- It decides whether your message is a **new image**, an **edit of the last one**, or just a question, so “make it wear sunglasses” does the right thing automatically.
- It answers plain questions and small talk in the chat without generating anything.
- In **Auto** profile mode it also picks the generation settings (size, steps, CFG, transparent) for the prompt; the chat reports what it used as **✨ AI settings: 1024×1024 · 40 steps · cfg 6.0**.
- You can always read the exact prompt it produced: it appears in the chat under your message as **✨ DeepSeek prompt: …**.

### What is sent

Only your chat text and the recent messages of the current conversation (about the last 12,
including the prompts of images already made), plus the current generation settings when you are in
Auto mode. **The image files themselves are never sent**, and the image model runs locally — the
generation stays on your PC.

### Setting it up

1. Create an account at [platform.deepseek.com](https://platform.deepseek.com) (this happens outside the app, in your browser).
2. Open **API Keys** and click **Create new key**, then copy the key (it starts with `sk-`).
3. In the app, open the **Prompt assistant** section in the right-hand panel, or **Settings → Prompt assistant (DeepSeek)**.
4. Paste the key into the **DeepSeek API key** field and click **Save**.
5. Click **Test connection** — the app reports the model it reached and its reply.
6. Make sure **DeepSeek prompts** is ticked in the right-hand panel (the Settings checkbox is labelled **Let DeepSeek write the image prompts**). That is it — the next message you send goes through the assistant first.

### Good to know

- Once saved, the key is never shown again. The field reads `•••••••• saved (…hint) - type to replace`; typing a new key and pressing **Save** replaces it.
- The key is stored only in the local `settings.json` (gitignored) and is sent only to the provider you configure. The app never sends it back to the browser — Settings shows just the masked hint.
- The defaults are DeepSeek (`https://api.deepseek.com`, model `deepseek-chat`). Any OpenAI-compatible endpoint works — change **Base URL** and **Model** in **Settings → Prompt assistant (DeepSeek)**.
- DeepSeek bills your own account per token. A prompt rewrite is typically a few hundred tokens — fractions of a cent at DeepSeek's published prices.
- If the assistant is off, unreachable, or its key is rejected, generation still works: your raw prompt is used and the chat shows **Prompt assistant unavailable: …** next to the message.

## Every setting, explained

### Right-hand panel

| Control | What it does | Recommended |
|---|---|---|
| **Profile** (Settings profile) | Chooses who owns size, steps, CFG, sampler, batch and transparency: **Auto — AI adjusts settings**, **Manual (current)**, or a saved profile. Auto needs DeepSeek enabled with a key and starts from the app baseline 1024×1024 · 40 steps · CFG 6 — not from the last profile. Editing any control switches to Manual automatically. | Auto if DeepSeek is set up, otherwise Manual |
| **Save as…** | Stores the current values as a named profile (type a name, then **Save** or **✕**). | — |
| **Update** | Overwrites the active saved profile with the current values. | — |
| **Delete** | Removes the active saved profile; the panel falls back to Auto. | — |
| **DeepSeek prompts** | Routes every chat message through the prompt assistant first. | On once the key is saved |
| **DeepSeek API key** + **Save** | Stores your API key locally; the field is shown masked afterwards. | Paste once |
| **Generation settings** (collapsible header) | Opens and closes the controls below; the header shows a summary such as `1024×1024 · 40 steps · cfg 6.0`. Starts collapsed in Auto mode. | Expand for manual work |
| **GPU / CPU** | Switches the engine backend to an installed GPU build (CUDA first, then Vulkan) or CPU. It never downloads anything — install missing builds in **Settings → Engine backend**. | GPU |
| **Size** | Presets from **CPU draft · 512 × 512** and **Draft · 1024 × 1024** up to **Native · 2K** (for example 2048×2048), plus **Custom…**. | Draft 1024×1024 while experimenting; native 2K for a final render |
| **Width / Height** (Custom) | Output size in pixels, 256–4096, rounded to multiples of 32. | 1024×1024 |
| **Steps** | Diffusion steps; more steps add detail and time. Range 10–60. | 20 (**Fast**) for drafts, 40 (**Native**) for final images |
| **Fast (20)** / **Native (40)** | Set the step count with one click. | — |
| **CFG** | How strictly the image follows the prompt. Range 1–10. | 6.0 (app and engine default) |
| **Sampler** | Sampling method, filled from the running engine (default `euler`). | euler |
| **Seed** | `-1` means a random seed; the resolved seed is stored with the image. A fixed seed reproduces the same image with the same settings. | `-1` |
| **Random seed button** (dice) | Fills the seed field with a random number. | — |
| **Images per prompt** (Batch) | Renders 1–4 images as separate queued jobs (a fixed seed is incremented for each one). | 1 |
| **Engine** | Shows the engine state and backend, with **Reload** (restart the model) and **Stop**. | Use **Reload** after a failure |

### Top bar

| Control | What it does |
|---|---|
| **Engine: status** chip | Live engine state (Loading… / Ready / Generating / Stopped / Failed). |
| **VRAM** chip | GPU memory in use, when `nvidia-smi` is available. |
| **Queue** chip | Number of jobs waiting behind the active one. |
| **Logs** | Opens the engine's own log — the first place to look when something fails. |
| **Settings** | Opens the modal described below. |

### Settings modal

| Control | What it does | Default |
|---|---|---|
| **Start engine automatically when the app opens** | Loads the engine in the background at launch. | On |
| **Stop the app and unload the model when its window closes** | When the **last** app window closes, the engine stops and the local server exits (freeing VRAM/RAM). Reloading a page is safe, and extra windows keep the app alive until the last one closes. | On |
| **Engine backend** list | Each build shows its label, description and expected speed; **Install** downloads a missing build, **Use** switches to it, and the active one is badged. | CUDA |
| **engine / models / outputs / inputs / database** | The exact paths the app is using for the engine executable, model files, images, uploaded references and the SQLite database. | — |
| Model file list | Present or missing, per file, with destination paths. | — |
| **Reload engine** / **Stop engine** | The same actions as the Engine panel. | — |
| **Let DeepSeek write the image prompts** | Same toggle as **DeepSeek prompts** in the right-hand panel. | Off |
| **API key**, **Model**, **Base URL**, **Save**, **Test connection** | Prompt-assistant configuration (any OpenAI-compatible endpoint). | `deepseek-chat`, `https://api.deepseek.com` |
| **Quit Qwen Image Runner** (Danger zone) | Stops the engine and closes the local server immediately; your images stay on disk. | — |

## The four model files, explained

These four files are components of **one** model, and the app needs all of them. The first-run setup
downloads them from Hugging Face after you accept the licence terms; they are **not** bundled with
the app. Total ≈14.7 GB.

| File | Size | What it is for | Licence |
|---|---|---|---|
| `qwen_image_2.1-Q8_0.gguf` (denoiser) | 7.7 GB | The image model itself — it paints the picture. leejet's Q8_0 quant. | Qwen Research License |
| `Qwen3VL-8B-Instruct-UD-Q4_K_XL.gguf` (text encoder) | 5.1 GB | Turns your prompt into the model's language. Unsloth Dynamic 2.0 quant (UD-Q4_K_XL), measured better than uniform Q4_K_M. | Apache-2.0 |
| `mmproj-Qwen3VL-8B-Instruct-F16.gguf` (vision projector) | 1.2 GB | Lets the text encoder see reference images — this is what makes instruction editing work. | Apache-2.0 |
| `qwen_image_2.1_vae_bf16.safetensors` (VAE) | 0.7 GB | Converts between pixels and the latents the denoiser works in. | Qwen Research License |

They live in `models/diffusion/`, `models/text_encoders/` (two files) and `models/vae/`. Downloads
resume after an interruption, and every file is verified against the SHA-256 recorded in
`models.json`.

**Weak hardware:** you can replace the Q8_0 denoiser with a smaller quant (`Q6_K`, `Q5_0` or `Q4_K`)
from the same repository — smaller and faster, with a small quality cost. Put the file in
`models/diffusion/` and point `settings.json → engine.diffusion_model` at it.

## Workflows

### Chat — the main workflow

Describe an image and send it. The result appears in the conversation and stays there.

- **Follow-ups edit the last image.** Type “make it wear sunglasses” and the previous image is edited; the scene, subject and lighting are kept.
- **New images need a hint.** Start with “generate / create / draw / new image” and the app makes a fresh image instead of editing. The context bar above the input always shows which mode will be used, and its button toggles it.
- **New chat** (`＋ New chat`) opens a fresh conversation. Every chat keeps its messages and its own images, and you can reopen any of them from the **Chats** list in the sidebar.
- **Delete a chat** with the **✕** on its sidebar entry or **Delete chat** in the chat header. The confirmation removes the chat and the images it generated (gallery entries, files and thumbnails); copies you made with **Save as…** are kept.
- Every result has **Save as…**, **Use as input** and **Reuse settings**.
- Progress is real: you see the actual step count, seconds per step and elapsed time. Queued jobs cancel instantly; an active generation stops by reloading the model (the button says **Stop generation — reloads model**).

### Generate view

For precise work outside a conversation.

- **Size presets** from a 1024×1024 draft up to native 2K, or a custom size (multiples of 32).
- **Steps, CFG, sampler, seed** (leave the seed at `-1` for a random one; the resolved seed is stored with the image), **negative prompt** (the **+ Negative prompt** button reveals the field), and **batch** (1–4 images, rendered as separate jobs with consecutive seeds).
- **Transparent** produces a real RGBA PNG; the preview shows a checkerboard where it is transparent.
- Every generation here is a new image — there is no “last image” context. The hint under the prompt box links to Chat if you want to edit instead.
- Each result has an action row underneath: **Save as…**, **Edit this image**, **Reuse settings**.

### Edit view

- Add reference images: **Use as input** from the gallery or a chat card, or **+ Add images** to upload your own (`png` / `jpeg` / `webp`, up to 32 MB each). One and two reference images are verified; up to 10 are accepted.
- Describe the change, then press **Edit image**. The comparison slider shows before/after, and the result is added to the Gallery (where it can be saved or reused like any other image).
- **Transparent background** produces a real RGBA result.

### Gallery

Every image, newest first, with its full effective parameters. Actions per card: **Use as input**,
**Reuse settings**, **Save as…**, **Delete**. The filter switches between **All**, **Generated** and
**Edited**. The sidebar **History** list appears here (it is hidden in Chat, where the conversation
is the history).

### Save as…

Images are saved automatically inside the app's `outputs/` folder, and **Save as…** opens the real
Windows save dialog so you can put a copy anywhere you like (chat cards, gallery cards, and under the
generated image in the Generate view). The button blocks until you choose a location or cancel; your
copy is independent of the app's own file.

### Deleting chats

Deleting a chat removes its messages and the images it created — gallery entries, files under
`outputs/chats/<chat-id>/` and their thumbnails. Images you saved elsewhere with **Save as…** are
never touched. **＋ New chat** only creates a conversation; it never deletes anything.

### Where things are stored

```
engine/         engine builds (one folder per backend) + downloaded archives
models/         model weights
outputs/        your images, including outputs/chats/<chat-id>/ per conversation
inputs/         reference images you upload
thumbnails/     gallery thumbnails
data/canvas.db  chats, messages, images and job history (SQLite)
logs/           app + engine logs
settings.json   your settings (backend, defaults, licence acceptance, keys)
```

### Performance reference

Measured on an RTX 5070 Ti 16 GB with the default Q8 build and the CUDA backend:

| Size | Steps | Time |
|---|---|---|
| 1024 × 1024 | 20 | ~47 s |
| 1024 × 1024 | 40 | ~85 s |
| 1536 × 1536 | 20 | ~101 s |
| 2048 × 2048 | 40 | ~10.6 min |

A single edit with one reference takes roughly 110–214 s at 1024×1024. Peak VRAM is ≈12.6 GB; peak
engine RAM is ≈12.7 GiB. SageAttention (enabled by default for CUDA) measured −10 % at 1024² and
−30 % at 1536².

### Compute backends

| Backend | Who it is for | Extra download | Speed |
|---|---|---|---|
| **NVIDIA CUDA** (default) | NVIDIA GPUs | ~0.9 GB (includes CUDA runtime DLLs) | 1024×1024 in ~50 s (RTX 5070 Ti, 20 steps) |
| **Vulkan** | AMD / Intel / other GPUs | ~32 MB | tens of seconds to a few minutes per image |
| **CPU only** | machines without a usable GPU | ~17 MB | very slow — see below |

You can install several and switch instantly in **Settings → Engine backend**. You do **not** need to
install CUDA, cuDNN or any GPU toolkit — the CUDA runtime DLLs come with the engine build, and your
existing GPU driver is enough.

**Running without a GPU (CPU mode)**

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
- A smaller quant (Q6_K / Q5_0 / Q4_K) reduces memory traffic and speeds things up further; download it into `models/diffusion/` and point `settings.json → engine.diffusion_model` at it.
- More CPU cores help; close other applications and make sure the machine is plugged in and not thermal throttling.
- If you have any modern GPU (even integrated), try **Vulkan** first — it is usually much faster than CPU.

The app shows a warning in the Engine panel whenever the CPU backend is active, and the size hint
switches to CPU timings. The **GPU / CPU** segmented toggle in the right-hand panel also switches the
engine backend directly: it picks an installed GPU backend (CUDA first, then Vulkan) and never
downloads anything — install or switch builds in **Settings → Engine backend**.

## Troubleshooting

| Symptom | What to do |
|---|---|
| `python` is not recognised during install | Re-install Python 3.11+ and tick **Add python.exe to PATH**, or run `py -3 scripts\bootstrap.py`. |
| Install stops because Python is too old | Install Python 3.11 or newer, then re-run `Install.bat`. |
| Antivirus blocks `sd-server.exe` | Restore/allow it (and whitelist the project folder), then re-run `Install.bat`. |
| Downloads fail or are interrupted | Re-run `Install.bat` or the setup download — it resumes from the partial file. Behind a proxy, set `HTTPS_PROXY` / `HTTP_PROXY` first. |
| Engine stuck on “Loading…” | The first start reads ~13 GB from disk. Later starts take seconds. If it never finishes, open **Logs**. |
| “Engine: Failed” | Open **Logs**. Usually the engine build is missing (Settings → Engine backend → **Install**) or antivirus quarantined `sd-server.exe` (restore it and re-run `Install.bat`). |
| Out of memory at 1536² or 2048² | Stay at or below 1536² on a 16 GB GPU; keep CPU offload enabled (default for CUDA). |
| Generation is very slow | Check the active backend in the Engine panel. CPU mode is expected to be slow; CPU timings are shown in the size hint. |
| DeepSeek key rejected or no internet | Check the key in **Settings → Prompt assistant (DeepSeek)** and use **Test connection**. Generation still works without the assistant — the raw prompt is used and the failure is noted in the chat. |
| Port already in use | The app uses 7878, the engine 1235. LM Studio's own server uses 1234, so they can coexist. |
| UI looks outdated after an update | Reload once (`Ctrl+R`); the frontend is served no-store, so this only happens for windows already open during the update. |
| “Save as…” doesn't appear | It opens on the machine running the app and blocks until you choose a location or cancel. |
| `Launch.bat` closes immediately | Run it from a terminal to read the message, and check `logs\app.log` for the startup error. |

## FAQ

**Is it private? Does it work offline?**

Yes. Everything runs on your PC: the app binds to `127.0.0.1`, there is no telemetry, and your
prompts and images never leave the machine. Internet is needed only for the one-time install and
model downloads — and for DeepSeek, if you enable that yourself.

**Can I use the images commercially?**

The app code is GPL-3.0, which permits commercial use (any version you distribute must stay GPL-3.0
with its source available). The **model weights** are different: the Qwen Research License covers
research and evaluation only, and commercial use requires separate permission from Alibaba. Read the
licence linked in the setup screen if you plan to sell or publish outputs.

**How do I update?**

Run `git pull` in the project folder, then start the app with `Launch.bat`. Re-run `Install.bat` only
if the dependencies or the pinned engine changed (check the release notes / `CHANGELOG.md`). If you
downloaded a ZIP instead, replace the files with a new ZIP and keep your `settings.json`, `models/`,
`outputs/` and `data/` folders.

**How do I uninstall?**

Delete the project folder (that removes the app, the engine and the models) and delete the desktop
shortcut. Nothing is written to the registry and nothing was installed system-wide.

**Where are my images?**

Inside the app's `outputs/` folder — chat images under `outputs/chats/<chat-id>/`, everything else
under `outputs/YYYY-MM-DD/`. **Save as…** copies are wherever you put them, and deleting a chat never
touches those copies.

**Do I need to install CUDA or Python packages globally?**

No. The engine's CUDA runtime DLLs are part of the engine download, and all Python dependencies live
in the project's `.venv/` folder.

## Licences and credits

- **App code:** GNU GPL v3 — free to use, modify and share; any distributed version must stay open source under the same license. See [gnu.org/licenses/gpl-3.0](https://www.gnu.org/licenses/gpl-3.0.html).
- **Model weights:** Qwen-Image-2.1 denoiser and VAE under the Qwen Research License — research/evaluation use; commercial use requires separate permission from Alibaba. The Qwen3-VL text encoder and vision projector are Apache-2.0. Nothing is bundled; you download the files yourself.
- **Engine:** [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) (MIT).
- **Text encoder:** Qwen3-VL-8B-Instruct UD-Q4_K_XL is Unsloth's Dynamic 2.0 quant (Apache-2.0).
- **Model:** Qwen-Image-2.1 by Alibaba/Qwen.
- Third-party inventory: `THIRD_PARTY_LICENSES.md`.

> Unofficial project — not affiliated with, endorsed by, or connected to Alibaba/Qwen.

This software was generated by an AI agent (Claude in pi) working under human supervision and
direction — architecture, code, tests and documentation. Every feature was verified on real hardware
before being claimed: measurements, screenshots and known limitations are recorded in
`docs/validation/`.
