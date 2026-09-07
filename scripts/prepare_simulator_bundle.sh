#!/usr/bin/env bash
# Portable entrypoint; historical execution sources remain in the compatibility snapshot.
set -euo pipefail
exec "${VLA_TOOL_PYTHON:-python3}" -m uav_vla_lab runtime extract-simulator "$@"
