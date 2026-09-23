# Third-party licenses & notices

Qwen Image Runner itself is licensed under the **GNU General Public License v3.0** (see `LICENSE`).
This file lists the third-party components the app uses and their licenses.

> Versions below are from the environment pinned at the v1.0 release (2026-09-22).

## Python dependencies (installed via `pyproject.toml`)

| Package | Version | License |
|---|---|---|
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| certifi | 2026.7.22 | MPL-2.0 |
| charset-normalizer | 3.5.1 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| colorama | 0.4.6 | BSD-3-Clause |
| fastapi | 0.141.1 | MIT |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httptools | 0.8.0 | MIT |
| httpx | 0.28.1 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pillow | 12.3.0 | MIT-CMU (HPND) |
| pluggy | 1.6.0 | MIT |
| pydantic | 2.13.5 | MIT |
| pydantic_core | 2.46.5 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| python-dotenv | 1.2.3 | BSD-3-Clause |
| python-multipart | 0.0.32 | Apache-2.0 |
| PyYAML | 6.0.3 | MIT |
| requests | 2.34.2 | Apache-2.0 |
| starlette | 1.6.0 | BSD-3-Clause |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| urllib3 | 2.8.0 | MIT |
| uvicorn | 0.53.0 | BSD-3-Clause |
| watchfiles | 1.3.0 | MIT |
| websockets | 17.1 | BSD-3-Clause |

Development-only: pytest (MIT), iniconfig (MIT).

## Inference engine (downloaded at install time, not bundled)

| Component | Source | License |
|---|---|---|
| stable-diffusion.cpp (`sd-server.exe`, release `master-889-c678dfe`) | https://github.com/leejet/stable-diffusion.cpp | MIT |

The engine binary and its CUDA runtime DLLs are downloaded from the upstream GitHub release by
`Install.bat` / `scripts/bootstrap.py` and pinned by size + SHA-256 in `engine.json`.

## Model weights (downloaded at first run by the user, never bundled)

| Component | Source | License |
|---|---|---|
| Qwen-Image-2.1 (Q8_0 GGUF by leejet) | https://huggingface.co/leejet/Qwen-Image-2.1-GGUF | Qwen Research License |
| Qwen3-VL-8B-Instruct (UD-Q4_K_XL GGUF, by Unsloth) | https://huggingface.co/unsloth/Qwen3-VL-8B-Instruct-GGUF | Apache-2.0 |
| Qwen3-VL-8B-Instruct (mmproj GGUF) | https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF | Apache-2.0 |
| Qwen-Image-2.1 VAE | https://huggingface.co/Comfy-Org/Qwen-Image-2.1 | Qwen Research License |

The Qwen Research License permits research/evaluation use; commercial use requires separate
permission from Alibaba. The app shows these terms before downloading anything.

## Fonts / icons

The UI uses system fonts and CSS-drawn elements only — no third-party fonts or icon sets are bundled.
