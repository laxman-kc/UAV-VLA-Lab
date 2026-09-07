"""Create a new source/runtime receipt after an actual local readiness probe."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess

from ..integrations.aerovla.compat import legacy_script
from .environment import TIMED_RESET

REVISION = "e37685afb8953d1f5a09155d7255960cee1bfd9d"


def record(path: Path) -> dict:
    data = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--readiness-report", type=Path, required=True)
    parser.add_argument("--runtime-id", required=True)
    parser.add_argument("--reset-protocol", required=True, choices=("upstream", TIMED_RESET))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("Runtime receipt must be new; historical receipts are immutable")
    if args.reset_protocol == TIMED_RESET and TIMED_RESET not in args.runtime_id:
        parser.error("Timed reset requires a separately named runtime ID containing the protocol")
    revision = subprocess.check_output(["git", "-C", str(args.upstream), "rev-parse", "HEAD"], text=True).strip()
    if revision != REVISION:
        raise ValueError("Upstream revision differs from the inspected integration")
    readiness = json.loads(args.readiness_report.read_text())
    if readiness.get("passed") is not True or readiness.get("cuda", {}).get("ok") is not True:
        raise ValueError("Actual successful CUDA/import readiness evidence required")
    manifest_path = args.upstream / "vla_lab_patch_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    code = {}
    for name, installed in (("_aerovla_runtime_hooks.py", "_vla_lab_runtime.py"), ("reset_protocol.py", "_vla_lab_reset.py")):
        source = legacy_script(name[:-3])
        rec = record(source)
        if rec["sha256"] != record(args.upstream / installed)["sha256"] or rec["sha256"] != manifest.get("files", {}).get(installed, {}).get("sha256"):
            raise ValueError("Installed patch differs from packaged source or patch manifest")
        code[name] = rec
    code["patch_aerovla_runtime.py"] = record(legacy_script("patch_aerovla_runtime"))
    receipt = {"schema_version": "vla.runtime-receipt.v1", "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
               "runtime_id": args.runtime_id, "reset_protocol": args.reset_protocol, "upstream_revision": revision,
               "code": code, "patch_manifest": record(manifest_path), "readiness_report": record(args.readiness_report),
               "limitation": "Source freeze binds a caller-supplied passed import/CUDA probe. It is not a camera/reset/navigation acceptance or a claim of historical runtime identity."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(receipt, handle, indent=2)
        handle.write("\n")
    print(json.dumps({"status": "source_runtime_frozen", "receipt": record(args.output)}))
    return 0
