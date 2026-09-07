"""Explicit runtime environment selection; no retired-host defaults."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex

TIMED_RESET = "paused-final-pose-time-v1"


def selected_environment(*, data_root: Path, python: Path, reset_protocol: str,
                         runtime_id: str, receipt: Path, evidence: Path,
                         inherited: dict | None = None) -> dict:
    if reset_protocol not in ("upstream", TIMED_RESET):
        raise ValueError("Choose upstream or the separately named timed reset")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", runtime_id):
        raise ValueError("A bounded explicit runtime ID is required")
    if reset_protocol == TIMED_RESET and TIMED_RESET not in runtime_id:
        raise ValueError("Timed reset must appear in the separately frozen runtime ID")
    for name, path in (("data-root", data_root), ("python", python), ("receipt", receipt), ("evidence", evidence)):
        if not path.is_absolute():
            raise ValueError(name + " must be an explicit absolute path")
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("Runtime interpreter is missing or not executable")
    if evidence.exists() and any(evidence.iterdir()):
        raise ValueError("Evidence directory must be absent or empty")
    document = json.loads(receipt.read_text(encoding="utf-8"))
    if document.get("runtime_id") != runtime_id or document.get("reset_protocol") != reset_protocol:
        raise ValueError("Runtime receipt differs from the requested runtime/reset")
    environment = dict(inherited or {})
    environment.update(VLA_LAB_RESET_PROTOCOL=reset_protocol, VLA_LAB_RUNTIME_ID=runtime_id,
                       VLA_LAB_RUNTIME_RECEIPT=str(receipt), VLA_LAB_EVENT_DIR=str(evidence),
                       VLA_DATA_ROOT=str(data_root), VLA_RUNTIME_PYTHON=str(python),
                       HF_HOME=str(data_root / "cache/huggingface"), HF_HUB_OFFLINE="1",
                       TRANSFORMERS_OFFLINE="1", CUDA_VISIBLE_DEVICES="0", PYTHONUNBUFFERED="1")
    return environment


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data-root", "python", "receipt", "evidence"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--reset-protocol", required=True, choices=("upstream", TIMED_RESET))
    parser.add_argument("--runtime-id", required=True)
    parser.add_argument("--format", choices=("shell", "json"), default="shell")
    args = parser.parse_args(argv)
    values = selected_environment(data_root=args.data_root, python=args.python,
                                 reset_protocol=args.reset_protocol, runtime_id=args.runtime_id,
                                 receipt=args.receipt, evidence=args.evidence)
    if args.format == "shell":
        print("\n".join("export " + key + "=" + shlex.quote(value) for key, value in values.items()))
    else:
        print(json.dumps({"environment": values, "receipt_sha256": hashlib.sha256(args.receipt.read_bytes()).hexdigest(),
                          "scope": "Validated configuration exports, not a runtime readiness test"}, indent=2))
    return 0
