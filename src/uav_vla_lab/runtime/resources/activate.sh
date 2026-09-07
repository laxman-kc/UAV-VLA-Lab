#!/usr/bin/env bash
# Source this from bash. It selects dependencies, not a reset or experiment.
if [[ "${BASH_SOURCE[0]}" = "$0" ]]; then
  echo 'Source this script with VLA_DATA_ROOT set, or source scripts/activate_runtime.sh; execution in a child shell cannot activate its parent.' >&2
  exit 2
fi
: "${VLA_DATA_ROOT:?Set VLA_DATA_ROOT to the explicit persistent data directory}"
VLA_ENV="${VLA_ENV:-$VLA_DATA_ROOT/venvs/aerovla}"
[[ -f "$VLA_ENV/bin/activate" ]] || { echo 'Selected environment is absent' >&2; return 2; }
source "$VLA_ENV/bin/activate"
VLA_SITE_DIR="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
VLA_CUDA_LIB_DIRS="$VLA_SITE_DIR/nvidia/cuda_runtime/lib:$VLA_SITE_DIR/nvidia/cuda_nvrtc/lib:$VLA_SITE_DIR/nvidia/cublas/lib:$VLA_SITE_DIR/nvidia/cusparse/lib"
export LD_LIBRARY_PATH="$VLA_CUDA_LIB_DIRS${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export HF_HOME="$VLA_DATA_ROOT/cache/huggingface"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 CUDA_VISIBLE_DEVICES=0 PYTHONUNBUFFERED=1
export VLA_DATA_ROOT VLA_ENV
