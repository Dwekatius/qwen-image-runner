#!/usr/bin/env bash
# Run one Phase 0 txt2img job through sd-server with resource sampling.
# Usage: phase0_job.sh <width> <height> <steps> <seed> <prefix> [prompt]
set -u
cd "$(dirname "$0")/.." || exit 1
LOG=${LOG:-logs/phase0-A.log}
W=$1; H=$2; STEPS=$3; SEED=$4; PREFIX=$5
PROMPT=${6:-"a red apple on a wooden table, studio light, photorealistic"}

bash scripts/sample_resources.sh "test-artifacts/phase0/sample-${PREFIX}.csv" &
SAMPLER=$!

T0=$(date +%s)
RESP=$(curl -s -X POST http://127.0.0.1:1235/sdcpp/v1/img_gen -H "Content-Type: application/json" -d "{
  \"prompt\": \"$PROMPT\",
  \"width\": $W, \"height\": $H,
  \"seed\": $SEED, \"batch_count\": 1,
  \"embed_image_metadata\": true,
  \"output_format\": \"png\",
  \"sample_params\": {\"scheduler\":\"discrete\",\"sample_method\":\"euler\",\"sample_steps\":$STEPS,\"guidance\":{\"txt_cfg\":6.0}}
}")
JOB=$(echo "$RESP" | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "job: $JOB"
while true; do
  J=$(curl -s "http://127.0.0.1:1235/sdcpp/v1/jobs/$JOB")
  ST=$(echo "$J" | python -c "import sys,json; print(json.load(sys.stdin).get('status','?'))")
  NOW=$(date +%s)
  echo "[$((NOW-T0))s] $ST"
  case "$ST" in
    completed|failed|cancelled|error) echo "$J" > "test-artifacts/phase0/job-${PREFIX}.json"; break;;
  esac
  sleep 3
done
T1=$(date +%s)
kill $SAMPLER 2>/dev/null
echo "WALL: $((T1-T0))s"
awk -F, 'NR>1 {if($2+0>v)v=$2+0; if($3+0>r)r=$3+0} END {printf "PEAK VRAM: %d MiB | PEAK RAM: %.1f GiB | samples: %d\n", v, r/1048576, NR-1}' "test-artifacts/phase0/sample-${PREFIX}.csv"
grep -a "sampling completed" "$LOG" | tail -1
grep -a "generate_image completed" "$LOG" | tail -1
