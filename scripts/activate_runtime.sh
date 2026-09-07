#!/usr/bin/env bash
# Source this file on the verified vla01 host before running experiments.
LAB_DATA_ROOT=/home/shadeform/vla-data
source "$LAB_DATA_ROOT/venvs/aerovla/bin/activate"
LAB_SITE_DIR="$LAB_DATA_ROOT/venvs/aerovla/lib/python3.10/site-packages"
LAB_CUDA_LIB_DIRS="$LAB_SITE_DIR/nvidia/cuda_runtime/lib:$LAB_SITE_DIR/nvidia/cuda_nvrtc/lib:$LAB_SITE_DIR/nvidia/cublas/lib:$LAB_SITE_DIR/nvidia/cusparse/lib"
export LD_LIBRARY_PATH="$LAB_CUDA_LIB_DIRS${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export HF_HOME="$LAB_DATA_ROOT/cache/huggingface"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export CUDA_VISIBLE_DEVICES=0
export PYTHONUNBUFFERED=1
