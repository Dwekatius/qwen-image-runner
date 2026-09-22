# Phase 0 — Engine Proof Report

**Date:** 2026-09-21 · **Engine:** stable-diffusion.cpp `master-889-c678dfe` (win-cuda12 build)
**Machine:** RTX 5070 Ti 16 GB (16,303 MiB) · Ryzen 5 5600G · 128 GB RAM · Windows · driver 596.36

## Verdict

**✅ The locked Q8 configuration works** — Q8_0 DiT + Q4_K_M encoder + F16/Q8 projectors + VAE.
- 1024²: **102 s** (1.7 min) · 1536²: **274 s** (4.6 min) · 2048²: **634 s** (10.6 min)
- 2048² requires `--offload-to-cpu` (without it, VAE decode fails with OOM — details below)
- Offload costs ~1 % sampling speed. **Ship `--offload-to-cpu --diffusion-fa` as default.**
- Not "too slow" — but 2048² is a "coffee break" operation; 1024²/1536² are comfortable.

## Verified files & hashes

`test-artifacts/phase0/hashes.txt` — sd-server.exe `a81432d6…`, DiT Q8 `f8b244b0…`, encoder Q4_K_M `67d1659b…`,
mmproj F16 `ca524100…`, mmproj Q8 `c6ba8550…`, VAE `bb21f747…`.

## Performance (locked config, Euler, CFG 6, 40 steps, seed 42)

| Test | Config A: no offload | Config B: `--offload-to-cpu` |
|---|---|---|
| 1024² t2i | 106 s wall · sampling 96.4 s · **2.35 s/it** · peak VRAM 14,730 MiB* | **102 s** wall · sampling 96.0 s · peak VRAM 11,926 MiB |
| 1536² t2i | 274 s wall · sampling 261.2 s · **6.53 s/it** · peak VRAM 14,730 MiB | not run |
| 2048² t2i | **FAILED (decode OOM)** after 615 s · sampling completed 612.4 s · **15.3 s/it** | **634 s** wall · sampling 617.5 s · **15.4 s/it** · decode 13.5 s · peak VRAM 12,596 MiB |
| 1024² t2i, 20 steps | — | **51 s** (fast preset, quality still good) |
| 1-ref edit (F16 proj) | — | 214 s |
| 1-ref edit (Q8 proj) | — | 220 s (visually identical) |
| 2-ref edit | — | 368 s |
| Transparency generation | — | 93 s |
| Alpha-input edit | — | 199 s |
| Mask edit | — | 199 s |

\* 1024²-A peak not sampled (sampler bug fixed before A-1536). Peak RAM (server process): **12.6–12.7 GiB**.

## 2048² failure analysis (why offload is mandatory)

```
sampling completed in 612.36s                       ✓
decoding 1 latents
[WARN] cannot make enough memory: need 40175 MB, available 7329 MB
[WARN] VAE decode failed (likely OOM); retrying with spatial tiling   (auto-retry)
       → VAE Tile size 64x64, 9 tiles → need 10792 MB vs 7329 MB      ✗ FAILED
```
Cause: the Q8 DiT (7,331 MiB) stays resident in VRAM during decode. With `--offload-to-cpu` all weights live in RAM
(0 MiB resident), decode gets the full GPU → works. Note: **every** decode is auto-tiled by the engine
(1024²→32 px, 1536²→48 px, 2048²→64 px tiles); decode times 4.5–13.5 s.

## Feature verification

| Feature | Result | Notes |
|---|---|---|
| t2i 1024²/1536²/2048² | ✅ | 2048² only with offload |
| 1-ref edit | ✅ | red→green apple: background/lighting identical, subject preserved |
| 2-ref edit | ✅ | apple + vase composed into one coherent scene, both identities preserved |
| Transparency output | ✅ | real alpha: 40 % of pixels α 1–15 (effectively transparent), 0.5 % exactly 0; sticker border clean |
| Alpha input (RGBA ref) | ⚠️ flattened | accepted without error; output opaque — **no transparent-layer editing** |
| Mask editing | ❌ unusable | white = editable confirmed (masked quadrant changed), but **unmasked area corrupted** (blurred mush) → defer mask UI |
| Queued cancel | ✅ HTTP 200 | `{"code":"cancelled","message":"job cancelled by client"}` |
| Active cancel | ⚠️ HTTP 409 | `job is currently generating and cannot be interrupted yet` → "Stop generation — reloads model" semantics confirmed |
| Real progress | ✅ available | server stdout emits `\r`-updated `|====| 12/40 - 2.35s/it` lines → **real progress bar + s/it possible** |
| PNG metadata | ✅ | `parameters` tEXt chunk: prompt, Steps, CFG, Guidance, Seed, Size, Sampler, RNG, TE |
| Job API | ✅ | `POST /sdcpp/v1/img_gen` → 202 `{id,status:"queued",poll_url}`; statuses queued→generating→completed/failed/cancelled; result `images[0].b64_json` |

## Engine behavior notes (from verbose log)

- `--auto-fit` (default): DiT→VRAM (7,331 MB), encoder (5,408 MB) + VAE (644 MB)→RAM.
- Weight stats: diffusion = q8_0 (192 tensors) + bf16 (73); VAE = bf16; encoder = q4_K/q6_K mix.
- FLOW mode; flash attention active; VAE conv type "3D" (Wan VAE); tokenizer qwen2, vocab 151,674.
- Server ready ~45 s after launch (cold start, not precisely instrumented).

## Implications for v1 implementation

1. **Default engine flags:** `--offload-to-cpu --diffusion-fa --cfg-scale 6.0` — proven, ~1 % cost, fixes 2K decode.
2. **Progress:** parse sd-server stdout (`\r`-separated `N/M - X.XXs/it`) → real progress bar + step rate + elapsed.
3. **Stop button:** queued → cancel (200); active → 409 → labeled engine reload.
4. **Size presets:** 1024² (fast/52 s @20 steps, 102 s @40), 1536² (4.6 min), 2048² (10.6 min, offload).
5. **Transparency UI:** treat alpha < 16 as transparent for checkerboard display; only for *outputs*.
6. **Deferred (proved broken/unverified):** mask painting, transparent-layer editing, alpha-preserving inputs.
7. **Encoders/projectors:** F16 and Q8 projectors perform identically; keep F16 (default) — or Q8 to save 0.4 GB RAM.
8. **Expected peaks for the app's memory budget:** VRAM ~12.6 GB (2K), RAM ~12.7 GiB server process.

## Evidence index (`test-artifacts/phase0/`)

- `hashes.txt` · sample CSVs (`sample-*.csv`) · final job JSONs (`job-*.json`) · cancel-test JSONs
- `alphaout-checkerboard.png` (transparency verification)
- Engine logs: `logs/phase0-A.log.done` (no offload), `logs/phase0-B.log` (offload, F16), `logs/phase0-B2.log` (offload, Q8 proj)
- Output images: `outputs/phase0-*.png` (apple 1024/1536/2048, edits, mask, transparency, 20-step)
