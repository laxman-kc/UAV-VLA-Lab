#!/usr/bin/env bash
# Rebuild the recorded dependency family on a fresh Ubuntu 22.04 x86_64 host.
set -euo pipefail
VLA_APPLY=0
VLA_DATA_ROOT=""
VLA_UPSTREAM_ROOT=""
VLA_WHEEL=""
while (($#)); do
  case "$1" in
    --apply) VLA_APPLY=1; shift ;;
    --data-root) VLA_DATA_ROOT="$2"; shift 2 ;;
    --upstream) VLA_UPSTREAM_ROOT="$2"; shift 2 ;;
    --wheel) VLA_WHEEL="$2"; shift 2 ;;
    --help|-h) echo 'usage: uav-vla runtime bootstrap --data-root ABS --upstream ABS --wheel ABS [--apply]'; exit 0 ;;
    *) echo "Unknown bootstrap argument: $1" >&2; exit 2 ;;
  esac
done
for VLA_PATH in "$VLA_DATA_ROOT" "$VLA_UPSTREAM_ROOT" "$VLA_WHEEL"; do
  [[ "$VLA_PATH" = /* && "$VLA_PATH" != / && "$VLA_PATH" =~ ^[A-Za-z0-9_./-]+$ ]] || { echo 'Explicit absolute paths with safe upstream shell characters are required' >&2; exit 2; }
done
[[ -f "$VLA_WHEEL" && "$VLA_WHEEL" = *.whl ]] || { echo 'A locally built UAV-VLA-Lab wheel is required' >&2; exit 2; }
VLA_ENV="$VLA_DATA_ROOT/venvs/aerovla"
[[ ! -e "$VLA_ENV" && ! -e "$VLA_UPSTREAM_ROOT" ]] || { echo 'Choose fresh environment and upstream paths; existing runs are preserved' >&2; exit 2; }
if (( ! VLA_APPLY )); then
  echo "Plan only: Ubuntu 22.04 x86_64/Python3.10; create $VLA_ENV and pinned upstream $VLA_UPSTREAM_ROOT"
  echo 'Installs apt libraries, pinned PyTorch cu118/dependencies, recorded RPC repair and observation hooks; then records real import/CUDA/graphics probes.'
  echo 'No host is provisioned. Re-run with --apply only on the selected fresh host.'
  exit 0
fi
[[ "$(uname -s)" = Linux && "$(uname -m)" = x86_64 ]] || { echo 'This recorded GPU recipe requires Linux x86_64' >&2; exit 2; }
python3 - <<'PY'
import platform
v=platform.freedesktop_os_release()
assert v.get('ID')=='ubuntu' and v.get('VERSION_ID')=='22.04', 'Recorded recipe requires Ubuntu22.04; another OS needs a separately verified environment'
PY
VLA_RESOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VLA_SETUP="$VLA_DATA_ROOT/setup/fresh-runtime"
mkdir -p "$VLA_SETUP" "$VLA_DATA_ROOT/assets" "$VLA_DATA_ROOT/manifests" "$VLA_DATA_ROOT/runs" "$(dirname "$VLA_UPSTREAM_ROOT")"
exec > >(tee -a "$VLA_SETUP/bootstrap.log") 2>&1
date -u
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv > "$VLA_SETUP/gpu-before.csv"
sudo -n apt-get update -qq
sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y python3.10-venv python3-tk p7zip-full zip unzip net-tools ripgrep lsof curl libvulkan1 vulkan-tools libomp5 libgl1 libegl1 libxrandr2 libxinerama1 libxcursor1 libxi6 libasound2 build-essential git-lfs
git clone --no-checkout https://github.com/XuPeng23/AeroVLA.git "$VLA_UPSTREAM_ROOT"
git -C "$VLA_UPSTREAM_ROOT" checkout --detach e37685afb8953d1f5a09155d7255960cee1bfd9d
python3.10 -m venv "$VLA_ENV"
VLA_PY="$VLA_ENV/bin/python"
"$VLA_PY" -m pip install 'pip<26' 'setuptools<81' wheel
"$VLA_PY" -m pip install torch==2.1.2 torchvision==0.16.2 torchaudio==2.1.2 --index-url https://download.pytorch.org/whl/cu118
"$VLA_PY" -m pip install -r "$VLA_RESOURCE_DIR/requirements-locked.txt"
"$VLA_PY" -m pip install airsim==1.8.1 --no-build-isolation
"$VLA_PY" -m pip install 'https://github.com/Dao-AILab/flash-attention/releases/download/v2.5.8/flash_attn-2.5.8%2Bcu118torch2.1cxx11abiFALSE-cp310-cp310-linux_x86_64.whl#sha256=f7b1002a954d42f6451c812d1ab69a0f70092e447df49b6dd384b2006f9094ee'
"$VLA_PY" -m pip install --no-deps "$VLA_WHEEL"
"$VLA_ENV/bin/uav-vla" runtime repair-rpc --upstream "$VLA_UPSTREAM_ROOT" --output "$VLA_SETUP/rpc-repair"
"$VLA_ENV/bin/uav-vla" integration patch --checkout "$VLA_UPSTREAM_ROOT" --apply > "$VLA_SETUP/patch.log"
export VLA_DATA_ROOT
source "$VLA_RESOURCE_DIR/activate.sh"
python -m pip check > "$VLA_SETUP/pip-check.log"
python -m pip freeze > "$VLA_SETUP/runtime.freeze.txt"
vulkaninfo --summary > "$VLA_SETUP/vulkan-summary.log" 2>&1
uav-vla runtime probe --output "$VLA_SETUP/runtime-probe.json"
date -u
echo 'Dependency/import/CUDA and graphics-command probes finished. Inspect real NVIDIA Vulkan visibility, then freeze a NEW runtime receipt; simulator acceptance remains separate.'
