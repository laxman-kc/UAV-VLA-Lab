#!/usr/bin/env bash
set -euo pipefail
LAB_SOURCE=/home/shadeform/UAV-VLA-Lab
LAB_DATA=/home/shadeform/vla-data
mkdir -p "$LAB_DATA/setup" "$LAB_DATA/assets" "$LAB_DATA/manifests" "$LAB_DATA/runs"
exec > >(tee -a "$LAB_DATA/setup/bootstrap.log") 2>&1
date -u
sudo -n apt-get update -qq
sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y python3.10-venv python3-tk p7zip-full zip unzip net-tools ripgrep libvulkan1 vulkan-tools libomp5 libgl1 libegl1 libxrandr2 libxinerama1 libxcursor1 libxi6 libasound2 build-essential git-lfs
if [ ! -d "$LAB_SOURCE/.git" ]; then
  git clone https://github.com/laxman-kc/UAV-VLA-Lab.git "$LAB_SOURCE"
fi
mkdir -p "$LAB_SOURCE/third_party"
if [ ! -d "$LAB_SOURCE/third_party/AeroVLA/.git" ]; then
  git clone https://github.com/XuPeng23/AeroVLA.git "$LAB_SOURCE/third_party/AeroVLA"
fi
git -C "$LAB_SOURCE/third_party/AeroVLA" checkout e37685afb8953d1f5a09155d7255960cee1bfd9d
python3.10 -m venv "$LAB_DATA/venvs/aerovla"
LAB_PY="$LAB_DATA/venvs/aerovla/bin/python"
"$LAB_PY" -m pip install --upgrade 'pip<26' 'setuptools<81' wheel packaging ninja
"$LAB_PY" -m pip install torch==2.1.2 torchvision==0.16.2 torchaudio==2.1.2 --index-url https://download.pytorch.org/whl/cu118
"$LAB_PY" -m pip install numpy==1.26.3 'msgpack-rpc-python==0.4' tornado==4.5.3
"$LAB_PY" -m pip install opencv-contrib-python==4.10.0.84 airsim==1.8.1 --no-build-isolation
python3 - "$LAB_SOURCE/third_party/AeroVLA/requirements.txt" "$LAB_DATA/setup/requirements-without-flash.txt" <<'PY'
import pathlib, sys
lines=pathlib.Path(sys.argv[1]).read_text().splitlines()
pathlib.Path(sys.argv[2]).write_text('\n'.join(x for x in lines if not x.startswith(('torch==','torchvision==','flash-attn==','airsim==','numpy==','tornado==','msgpack-rpc-python=='))) + '\n')
PY
"$LAB_PY" -m pip install -r "$LAB_DATA/setup/requirements-without-flash.txt" numpy==1.26.3 numba==0.60.0 attrs tensorboard sentencepiece huggingface_hub==0.24.7
"$LAB_PY" -m pip install 'https://github.com/Dao-AILab/flash-attention/releases/download/v2.5.8/flash_attn-2.5.8%2Bcu118torch2.1cxx11abiFALSE-cp310-cp310-linux_x86_64.whl'
"$LAB_PY" -m pip install nvidia-cuda-runtime-cu11==11.8.89 nvidia-cuda-nvrtc-cu11==11.8.89 nvidia-cublas-cu11==11.11.3.6 nvidia-cusparse-cu11==11.7.5.86
"$LAB_PY" -m pip check
"$LAB_PY" -m pip freeze > "$LAB_DATA/setup/runtime.freeze.txt"
"$LAB_PY" - <<'PY'
import torch, json
print(json.dumps({'torch':torch.__version__, 'cuda_runtime':torch.version.cuda, 'available':torch.cuda.is_available(), 'gpu':torch.cuda.get_device_name(0), 'bf16':torch.cuda.is_bf16_supported()}))
x=torch.ones((128,128),device='cuda',dtype=torch.bfloat16)
print('CUDA matmul:',float((x@x).mean()))
PY
date -u
touch "$LAB_DATA/setup/bootstrap.complete"
