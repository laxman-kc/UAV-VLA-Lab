#!/usr/bin/env bash
# Source after installing the package; selects an explicit local environment.
if [[ "${BASH_SOURCE[0]}" = "$0" ]]; then
  echo 'Source this file from bash with VLA_DATA_ROOT set.' >&2
  exit 2
fi
VLA_ACTIVATION_SCRIPT="$("${VLA_TOOL_PYTHON:-python3}" -c 'from pathlib import Path; import uav_vla_lab.runtime; print(Path(uav_vla_lab.runtime.__file__).parent / "resources/activate.sh")')" || return 2
source "$VLA_ACTIVATION_SCRIPT"
