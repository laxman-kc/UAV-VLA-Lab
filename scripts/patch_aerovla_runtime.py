#!/usr/bin/env python3
"""Install reversible observation hooks in the pinned AeroVLA evaluator."""
from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
from pathlib import Path
import re

PINNED_REVISION = "e37685afb8953d1f5a09155d7255960cee1bfd9d"
EVALUATOR_SHA256 = "df897e4b827da123cc2922a913ba369ed27c0eea033b6cd00b876008e52c48d2"
RELATIVE_EVALUATOR = Path("src/vlnce_src/eval_aerovla.py")
PROTECTED_SOURCE_HASHES = {
    "src/model_wrapper/aerovla_wrapper_ui.py": "1e18357cedf0af5b36ccf4078373417d7e2b7d084487cb2b81282db3a008f3e8",
    "airsim_plugin/AirVLNSimulatorClientTool_AeroVLA.py": "66dfb3d97ebaeacfec7e3786de52e146dd68b1277c5d6b0316252229fbf3fe9d",
    "airsim_plugin/AirVLNSimulatorServerTool.py": "bcc5d134315ed656a01d3b87fe2ad5729e0eb905b77e63a7969957fbf3e9199f",
    "src/vlnce_src/env_uav.py": "9399f0d474f8376664c2c1abbb5c6b136d59080070c3b9798556f75fec8c1b4c",
    "src/vlnce_src/closeloop_util.py": "e3d806176dec3e9dd584e7883085fe70c71f14dacc84542a19e9f47ad874eca4",
    "src/vlnce_src/assist.py": "2e6e7561b6ba09bfe180ad044c75843311fe593b2aa4a43100b411f6d58b463a",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def instrument(source: str) -> str:
    if digest(source.encode()) != EVALUATOR_SHA256:
        raise ValueError("Evaluator differs from inspected revision; refusing an unreviewed patch")
    start = source.index("    model_wrapper = AerialVLAWrapper(model_args=model_args, data_args=data_args)")
    end = source.index("    eval_env.delete_VectorEnvUtil()", start)
    original = source[start:end].rstrip() + "\n"
    replacement = (
        "    from _vla_lab_runtime import install\n"
        "    _vla_runtime = None\n"
        "    try:\n"
        "        _vla_runtime = install(eval_env, args, model_args)\n"
        + "".join("    " + line if line.strip() else line for line in original.splitlines(True))
        + "    finally:\n"
        "        try:\n"
        "            if _vla_runtime is not None:\n"
        "                _vla_runtime.close(error=sys.exc_info()[1])\n"
        "        finally:\n"
        "            eval_env.delete_VectorEnvUtil()\n"
    )
    patched = source[:start] + replacement + source[end + len("    eval_env.delete_VectorEnvUtil()"):].lstrip("\n")
    ast.parse(patched)
    return patched


def propagate_cancellation(source: str) -> str:
    """Keep ordinary fallback behavior while allowing interruption cleanup."""
    return re.sub(r"(?m)^([ \t]*)except:[ \t]*$",
                  lambda match: (match[1] + "except (KeyboardInterrupt, SystemExit):\n" +
                                 match[1] + "    raise\n" + match[1] + "except:"), source)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Default only prints the reviewed diff")
    options = parser.parse_args()
    checkout = options.checkout.resolve()
    changed_protocol_paths = {"src/model_wrapper/aerovla_wrapper_ui.py",
                              "airsim_plugin/AirVLNSimulatorClientTool_AeroVLA.py", "src/vlnce_src/env_uav.py"}
    extra_patches = []
    for relative, expected_hash in PROTECTED_SOURCE_HASHES.items():
        path = checkout / relative
        saved = path.with_suffix(".py.vla-lab-original")
        data = saved.read_text() if saved.exists() else path.read_text()
        if digest(data.encode()) != expected_hash:
            raise SystemExit(f"Protocol source differs from inspected revision: {relative}")
        revised = propagate_cancellation(data) if relative in changed_protocol_paths else data
        if path.read_text() not in (data, revised):
            raise SystemExit(f"Protocol source contains another change: {relative}")
        if revised != data:
            ast.parse(revised)
            extra_patches.append((path, saved, data, revised))
    target = checkout / RELATIVE_EVALUATOR
    backup = target.with_suffix(".py.vla-lab-original")
    original = backup.read_text() if backup.exists() else target.read_text()
    patched = instrument(original)
    current = target.read_text()
    if current not in (original, patched):
        raise SystemExit("Evaluator contains another change; refusing to overwrite it")
    print("".join(difflib.unified_diff(original.splitlines(True), patched.splitlines(True),
                                   fromfile=str(RELATIVE_EVALUATOR), tofile=str(RELATIVE_EVALUATOR))), end="")
    for path, saved, data, revised in extra_patches:
        relative = str(path.relative_to(checkout))
        print("".join(difflib.unified_diff(data.splitlines(True), revised.splitlines(True),
                                        fromfile=relative, tofile=relative)), end="")
    if not options.apply:
        return
    hooks = Path(__file__).with_name("_aerovla_runtime_hooks.py").read_bytes()
    ast.parse(hooks)
    destination = checkout / "_vla_lab_runtime.py"
    if not backup.exists():
        backup.write_text(original)
    target.write_text(patched)
    for path, saved, data, revised in extra_patches:
        if not saved.exists():
            saved.write_text(data)
        path.write_text(revised)
    destination.write_bytes(hooks)
    manifest = {
        "schema_version": 1,
        "upstream_revision": PINNED_REVISION,
        "protocol": "aerovla-e37685a-observed-v1",
        "behavior": "Existing parser, commands, stopping, cameras and clock settings retained; cancellation propagates through broad upstream exception handlers",
        "timing_note": "Synchronous event/image recording adds measurable overhead to an unpaused simulator",
        "files": {
            str(RELATIVE_EVALUATOR): {"original_sha256": EVALUATOR_SHA256, "patched_sha256": digest(patched.encode())},
            destination.name: {"sha256": digest(hooks)},
        },
        "upstream_protocol_source_sha256": PROTECTED_SOURCE_HASHES,
    }
    for path, saved, data, revised in extra_patches:
        manifest["files"][str(path.relative_to(checkout))] = {"original_sha256": digest(data.encode()), "patched_sha256": digest(revised.encode())}
    (checkout / "vla_lab_patch_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"applied": True, "checkout": str(checkout), "manifest": str(checkout / "vla_lab_patch_manifest.json")}))


if __name__ == "__main__":
    main()
