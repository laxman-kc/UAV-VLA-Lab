"""Run checksum-bound historical workflows from an installed wheel.

The compatibility tree is generated from the retained public scripts. Its layout
is intentional: sibling imports and source-file hashes are part of the protocol.
It is never copied into, or looked up relative to, the caller's checkout.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


RESOURCE_ROOT = Path(__file__).with_name("legacy")


def verify_snapshot(root: Path = RESOURCE_ROOT) -> dict:
    manifest = json.loads((root / "snapshot.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "uav-vla.legacy-source-snapshot.v1":
        raise ValueError("Unsupported legacy source snapshot")
    seen = set()
    for record in manifest["files"]:
        relative = Path(record["path"])
        if relative.is_absolute() or ".." in relative.parts or str(relative) in seen:
            raise ValueError("Invalid or duplicate legacy resource path")
        seen.add(str(relative))
        path = root / relative
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Legacy source must be a contained regular file: " + str(relative))
        data = path.read_bytes()
        if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError("Packaged historical source changed: " + str(relative))
    return manifest


def legacy_script(name: str) -> Path:
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]*", name):
        raise ValueError("Use a historical script basename without an extension")
    manifest = verify_snapshot()
    relative = "scripts/" + name + ".py"
    if relative not in {r["path"] for r in manifest["files"]}:
        raise ValueError("Unknown compatibility script: " + name)
    return RESOURCE_ROOT / relative


def run(name: str, argv: list[str], *, env: dict | None = None) -> int:
    """No shell parsing; preserve cwd, signals, argv and inherited environment."""
    command = [sys.executable, "-B", str(legacy_script(name)), *argv]
    return subprocess.call(command, env=env)
