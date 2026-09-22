#!/usr/bin/env bash
# Phase 0 downloads for Qwen Image Runner — resumable, sequential, logged.
set -u
cd "$(dirname "$0")/.." || exit 1
LOG() { echo "[$(date +%H:%M:%S)] $*"; }

dl() {
  local url="$1" out="$2"
  mkdir -p "$(dirname "$out")"
  local cont=""
  [ -s "$out" ] && cont="-C -"
  LOG "START $out"
  if curl -fL $cont --retry 5 --retry-delay 3 -sS -o "$out" "$url"; then
    LOG "DONE  $out ($(stat -c%s "$out") bytes)"
  else
    LOG "FAIL  $out"
    return 1
  fi
}

dl "https://github.com/leejet/stable-diffusion.cpp/releases/download/master-889-c678dfe/sd-master-c678dfe-bin-win-cuda12-x64.zip" "engine/sd-win-cuda12.zip"
dl "https://github.com/leejet/stable-diffusion.cpp/releases/download/master-889-c678dfe/cudart-sd-bin-win-cu12-x64.zip" "engine/cudart-win-cu12.zip"
dl "https://huggingface.co/leejet/Qwen-Image-2.1-GGUF/resolve/main/qwen_image_2.1-Q8_0.gguf" "models/diffusion/qwen_image_2.1-Q8_0.gguf"
dl "https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF/resolve/main/Qwen3VL-8B-Instruct-Q4_K_M.gguf" "models/text_encoders/Qwen3VL-8B-Instruct-Q4_K_M.gguf"
dl "https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF/resolve/main/mmproj-Qwen3VL-8B-Instruct-F16.gguf" "models/text_encoders/mmproj-Qwen3VL-8B-Instruct-F16.gguf"
dl "https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF/resolve/main/mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf" "models/text_encoders/mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf"
dl "https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/vae/qwen_image_2.1_vae_bf16.safetensors" "models/vae/qwen_image_2.1_vae_bf16.safetensors"

LOG "ALL DOWNLOADS FINISHED"
