# Installing Qwen Image Runner

This page lists everything you need, what gets downloaded, and how to do it by hand if you prefer.

## 1. What you need

| Requirement | Notes |
|---|---|
| **Windows 10 or 11 (64-bit)** | The launcher scripts and the engine builds are Windows-specific. |
| **Python 3.11 or newer** | [python.org/downloads](https://www.python.org/downloads/) — tick **“Add python.exe to PATH”** during setup. Verify with `python --version`. |
| **~25 GB free disk** | Engine ≈ 0.9 GB + models ≈ 14.6 GB + room for your images. |
| **8 GB+ RAM** | 16 GB+ recommended. The engine keeps model weights in RAM when CUDA offload is on (≈13 GB peak). |
| **A GPU — optional** | NVIDIA (CUDA) is fastest. AMD/Intel work through Vulkan. **No GPU at all is fine: CPU mode works, it is just slow.** |
| **Internet** | Only for the one-time downloads. Nothing is sent anywhere afterwards. |

> You do **not** need to install CUDA, cuDNN, or any GPU toolkit. The CUDA runtime DLLs ship with the
> engine download, and the GPU driver you already have is enough.

## 2. Automatic install (recommended)

```
Install.bat      (once)
Launch.bat       (every time — or use the desktop shortcut)
```

`Install.bat` does four things:

1. creates a virtual environment in `.venv/` (nothing is installed globally),
2. installs the Python dependencies listed in `pyproject.toml`,
3. downloads the engine build for the selected backend and verifies its SHA-256,
4. creates a desktop shortcut.

**Choosing a backend at install time:** by default the CUDA build is installed. To install a different
one up front:

```bat
set QIR_BACKEND=cpu
Install.bat
```

Accepted values: `cuda` (NVIDIA, default), `vulkan` (AMD/Intel), `cpu`. You can install the others at
any time from **Settings → Engine backend → Install**.

## 3. First run

`Launch.bat` starts the local service and opens the studio in its own window. The setup screen asks for:

1. **Licence acceptance** — the app (GPL-3.0) and the model weights
   (Qwen Research License). Nothing is downloaded before you accept.
2. **Compute backend** — pick what runs the model; download it if it is not installed yet.
3. **Model files** — ~14.6 GB, resumable, checksum-verified.
4. **Start engine** — the first start loads ~13 GB from disk and takes a while; later starts are seconds.

## 4. Manual install (no scripts)

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".[dev]"     REM omit [dev] to skip test tooling
.venv\Scripts\python.exe -m backend.main                REM serves the UI on http://127.0.0.1:7878
.venv\Scripts\python.exe scripts\stop.py                REM to stop it again
```

The engine and models can then be downloaded from the app's setup screen, or manually (below).

## 5. Downloading engine builds and models by hand

Everything is pinned in `engine.json` (engine) and `models.json` (weights) with URL, size and SHA-256.

**Engine** (from the [stable-diffusion.cpp release](https://github.com/leejet/stable-diffusion.cpp/releases/tag/master-889-c678dfe)):

| Backend | Archive | Extract to |
|---|---|---|
| NVIDIA CUDA | `sd-master-c678dfe-bin-win-cuda12-x64.zip` + `cudart-sd-bin-win-cu12-x64.zip` | `engine/sd-cuda12/` |
| Vulkan | `sd-master-c678dfe-bin-win-vulkan-x64.zip` | `engine/sd-vulkan/` |
| CPU | `sd-master-c678dfe-bin-win-cpu-x64.zip` | `engine/sd-cpu/` |

**Models** (Hugging Face):

| File | Put it in |
|---|---|
| [leejet/Qwen-Image-2.1-GGUF](https://huggingface.co/leejet/Qwen-Image-2.1-GGUF) → `qwen_image_2.1-Q8_0.gguf` | `models/diffusion/` |
| [unsloth/Qwen3-VL-8B-Instruct-GGUF](https://huggingface.co/unsloth/Qwen3-VL-8B-Instruct-GGUF) → `Qwen3VL-8B-Instruct-UD-Q4_K_XL.gguf` | `models/text_encoders/` |
| [Qwen/Qwen3-VL-8B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF) → `mmproj-Qwen3VL-8B-Instruct-F16.gguf` | `models/text_encoders/` |
| [Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/tree/main/vae) → `qwen_image_2.1_vae_bf16.safetensors` | `models/vae/` |

Cheaper GPU or CPU-only? The Q8 diffusion file can be replaced with `Q6_K`, `Q5_0` or `Q4_K` from the
same repository — smaller and faster, with a small quality cost. Point
`settings.json → engine.diffusion_model` at the file you downloaded.

## 6. Verifying a download

```bat
.venv\Scripts\python.exe -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" path\to\file
```

Compare the output with the `sha256` value in `engine.json` / `models.json`.

## 7. Uninstall

- Delete the project folder (that removes the app, engine and models).
- Delete the desktop shortcut.
- Nothing is written to the registry and nothing is installed system-wide.

## 8. Troubleshooting installer problems

| Problem | Fix |
|---|---|
| `python` is not recognised | Re-install Python and tick “Add python.exe to PATH”, or run `py -3 scripts\bootstrap.py`. |
| Antivirus blocks `sd-server.exe` | It is a freshly downloaded executable from the upstream release; allow/restore it, or re-run `Install.bat` after whitelisting the folder. |
| Downloads keep failing | Re-run `Install.bat` / the setup screen — downloads resume where they stopped. |
| Wrong backend installed | Settings → Engine backend → install the one you want and press **Use**. |
