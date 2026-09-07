#!/usr/bin/env bash
# Verify complete downloaded parts immediately; no wait on a retired host path.
set -euo pipefail
if [[ "${1:-}" = --help || "${1:-}" = -h ]]; then
  echo 'usage: VLA_DATA_ROOT=ABS uav-vla runtime extract-simulator'; exit 0
fi
: "${VLA_DATA_ROOT:?Set explicit persistent VLA_DATA_ROOT}"
VLA_ARCHIVES="$VLA_DATA_ROOT/assets/archives/envs"
VLA_DEST="$VLA_DATA_ROOT/assets/envs"
VLA_SETUP="$VLA_DATA_ROOT/setup/simulator-extraction"
[[ ! -e "$VLA_DEST/closeloop_envs" && ! -e "$VLA_SETUP" ]] || { echo 'Extraction/output already exists; preserve it' >&2; exit 2; }
mkdir -p "$VLA_SETUP" "$VLA_DEST" "$VLA_DATA_ROOT/manifests"
uav-vla assets --report "$VLA_SETUP/archives-verified.json" verify --archive-dir "$VLA_ARCHIVES" --category envs
python - "$VLA_DEST" <<'PY'
import shutil,sys
# Published declared expansion plus explicit operational reserve.
required=19576208267 + 60*1024**3
assert shutil.disk_usage(sys.argv[1]).free >= required, 'Insufficient measured free storage for declared environment expansion +60GiB reserve'
PY
7z t "$VLA_ARCHIVES/closeloop_envs.zip" > "$VLA_SETUP/archive-test.log"
7z x -y "-o$VLA_DEST" "$VLA_ARCHIVES/closeloop_envs.zip" > "$VLA_SETUP/extract.log"
chmod u+x "$VLA_DEST/closeloop_envs/ModernCityMap.sh" "$VLA_DEST/closeloop_envs/ModernCityDowntown/Binaries/Linux/ModernCityDowntown"
echo 'Pinned environment extracted. Actual graphics/reset/controller validation remains required.'
