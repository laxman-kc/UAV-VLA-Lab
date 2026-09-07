#!/usr/bin/env bash
# Verify and extract the pinned bundle after the separately supervised download.
set -euo pipefail
LAB_SOURCE_ROOT=/home/shadeform/UAV-VLA-Lab
LAB_DATA_ROOT=/home/shadeform/vla-data
LAB_SETUP_ROOT="$LAB_DATA_ROOT/setup"
cd "$LAB_SOURCE_ROOT"
source scripts/activate_runtime.sh
LAB_WAIT_DEADLINE=$((SECONDS + 1800))
while [[ ! -f "$LAB_DATA_ROOT/assets/archives/envs/closeloop_envs.z04" ]]; do
  if (( SECONDS >= LAB_WAIT_DEADLINE )); then
    echo "Timed out waiting for the final verified archive part" >&2
    exit 124
  fi
  sleep 10
done
python scripts/prepare_assets.py \
  --report "$LAB_DATA_ROOT/manifests/env-archives-verified.json" \
  verify --archive-dir "$LAB_DATA_ROOT/assets/archives/envs" --category envs
7z t "$LAB_DATA_ROOT/assets/archives/envs/closeloop_envs.zip" > "$LAB_SETUP_ROOT/env-archive-test.log"
test ! -e "$LAB_DATA_ROOT/assets/envs/closeloop_envs"
7z x -y "-o$LAB_DATA_ROOT/assets/envs" "$LAB_DATA_ROOT/assets/archives/envs/closeloop_envs.zip" > "$LAB_SETUP_ROOT/env-extract.log"
chmod u+x "$LAB_DATA_ROOT/assets/envs/closeloop_envs/ModernCityMap.sh"
chmod u+x "$LAB_DATA_ROOT/assets/envs/closeloop_envs/ModernCityDowntown/Binaries/Linux/ModernCityDowntown"
python scripts/prepare_assets.py \
  --report "$LAB_DATA_ROOT/manifests/extracted-demo-verified.json" \
  validate --data-root "$LAB_DATA_ROOT" --groups demo --require-merged
df -B1 "$LAB_DATA_ROOT" > "$LAB_SETUP_ROOT/storage-after-extraction.txt"
echo "Verified simulator bundle and converted demo assets are ready"
