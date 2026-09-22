#!/usr/bin/env bash
# Sample GPU VRAM + sd-server RAM once per second until the process exits.
# Usage: sample_resources.sh <out.csv>
set -u
OUT="$1"
echo "ts,vram_mib,ram_k" > "$OUT"
while true; do
  LINE=$(tasklist //FI "IMAGENAME eq sd-server.exe" //FO CSV //NH 2>/dev/null | head -1)
  [ -z "$LINE" ] && break
  VRAM=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | tr -d ' ')
  RAM=$(echo "$LINE" | awk -F'","' '{print $5}' | tr -d ' K,')
  echo "$(date +%s),$VRAM,$RAM" >> "$OUT"
  sleep 1
done
