#!/usr/bin/env python3
"""Inspect and validate the pinned ModernCityMap assets without installing software.

Downloads and extraction are deliberately separate operator steps. This command
never downloads archives or executes an environment binary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "configs/assets/modern_city_map.json"
DEFAULT_SPLITS = PROJECT_ROOT / "configs/splits/modern_city_map_v1.json"


def read_json(path: Path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def contained(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    candidate.relative_to(root.resolve())
    return candidate


def output_report(result: dict, path: Path | None) -> int:
    text = json.dumps(result, indent=2) + "\n"
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    print(text, end="")
    return 0 if result.get("ok", True) else 1


def verify_archives(manifest: dict, archive_dir: Path, category: str | None) -> dict:
    """Verify flat archive staging files; a checksum is never inferred from size."""
    checks = []
    for asset in manifest["assets"]:
        if category and asset["category"] != category:
            continue
        path = contained(archive_dir, asset["filename"])
        check = {"filename": asset["filename"], "path": str(path), "ok": False}
        if not path.is_file():
            check["error"] = "missing file"
        elif path.stat().st_size != asset["size_bytes"]:
            check.update(error="size mismatch", actual_size_bytes=path.stat().st_size)
        else:
            actual_hash = digest(path)
            check.update(actual_sha256=actual_hash, ok=actual_hash == asset["sha256"])
            if not check["ok"]:
                check["error"] = "SHA256 mismatch"
        checks.append(check)
    return {"schema_version": "vla.asset-checks.v1", "kind": "archives", "ok": bool(checks) and all(c["ok"] for c in checks), "checks": checks}


def finite_vector(value, length: int) -> bool:
    return isinstance(value, list) and len(value) == length and all(
        isinstance(number, (int, float)) and not isinstance(number, bool) and math.isfinite(number)
        for number in value
    )


def inspect_png(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError(f"Invalid PNG header: {path.name}")
    width, height = struct.unpack(">II", header[16:24])
    if not width or not height:
        raise ValueError(f"Invalid PNG dimensions: {path.name}")
    return width, height


def inspect_episode(raw_root: Path, trajectory: str, require_merged: bool) -> dict:
    """Validate metadata and paired input references without printing target data."""
    merged_path = contained(raw_root, trajectory)
    episode = merged_path.parent
    result = {"trajectory": trajectory, "ok": False}
    try:
        mark = read_json(episode / "mark.json")
        if not isinstance(mark.get("object_name"), str) or not finite_vector(mark["target"]["position"], 3):
            raise ValueError("mark.json lacks object name or finite target position")
        descriptions = read_json(episode / "object_description.json")
        if not isinstance(descriptions, list) or not descriptions or not all(isinstance(x, str) for x in descriptions):
            raise ValueError("object_description.json must be a nonempty list of strings")
        log_files = sorted((episode / "log").glob("*.json"))
        if not log_files:
            raise ValueError("No trajectory logs")
        matched = []
        for log_path in log_files:
            state = read_json(log_path)["sensors"]["state"]
            if not finite_vector(state["position"], 3) or not finite_vector(state["orientation"], 4):
                raise ValueError(f"Invalid state in {log_path.name}")
            image_name = log_path.with_suffix(".png").name
            front = episode / "frontcamera" / image_name
            down = episode / "downcamera" / image_name
            if front.is_file() and down.is_file():
                inspect_png(front)
                inspect_png(down)
                matched.append(image_name)
        if len(matched) < 5:
            raise ValueError("Fewer than five log frames with front/down PNG pairs")
        if require_merged:
            merged = read_json(merged_path)
            if not merged.get("trajectory_raw_detailed") or not isinstance(merged["conversations"][0]["value"], str):
                raise ValueError("merged_data.json has an invalid trajectory/instruction")
        result.update(ok=True, log_count=len(log_files), paired_frame_count=len(matched), merged_verified=require_merged)
    except (OSError, KeyError, IndexError, TypeError, ValueError) as error:
        result["error"] = str(error)
    return result


def validate_extracted(manifest: dict, splits: dict, data_root: Path, groups: list[str], require_merged: bool) -> dict:
    assets_root = data_root / "assets"
    launcher = contained(assets_root, manifest["layout"]["environment_launcher"])
    binary = contained(assets_root, manifest["layout"]["environment_binary"])
    checks = [
        {"kind": "launcher", "path": str(launcher), "ok": launcher.is_file()},
        {"kind": "binary", "path": str(binary), "ok": binary.is_file() and os.access(binary, os.X_OK)},
    ]
    seen = set()
    for group in groups:
        for trajectory in splits["groups"][group]:
            if trajectory in seen:
                continue
            seen.add(trajectory)
            check = inspect_episode(assets_root / "dataset_raw", trajectory, require_merged)
            check["group"] = group
            checks.append(check)
    return {"schema_version": "vla.asset-checks.v1", "kind": "extracted", "groups": groups, "ok": all(c["ok"] for c in checks), "checks": checks, "limitations": ["PNG headers are checked; full image decoding is a later observation gate.", "Validation does not launch the environment or claim runtime compatibility.", "Metadata validation does not authorize using holdout images or labels for training."]}


def convert_metadata(manifest: dict, data_root: Path, converter: Path, seed: int) -> int:
    expected = manifest["conversion"]["sha256"]
    if digest(converter) != expected:
        raise ValueError("Converter SHA256 differs from the pinned source; refusing to run")
    # Upstream assigns random.seed = 1 instead of invoking it. Set the generator
    # before executing the unchanged source, and record this compatibility fix.
    wrapper = (
        "import random,runpy,sys; "
        "random.seed(int(sys.argv[2])); "
        "path=sys.argv[1]; sys.argv=[path]+sys.argv[3:]; "
        "runpy.run_path(path,run_name='__main__')"
    )
    command = [sys.executable, "-c", wrapper, str(converter.resolve()), str(seed),
               "--root_dir", str((data_root / "assets/dataset_raw").resolve()),
               "--map_list", manifest["map_id"]]
    return subprocess.run(command, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", help="Print exact pinned URLs/checksums; perform no downloads")
    verify = sub.add_parser("verify", help="Verify the downloaded flat archive staging directory")
    verify.add_argument("--archive-dir", type=Path, required=True)
    verify.add_argument("--category", choices=["envs", "dataset_raw"])
    validate = sub.add_parser("validate", help="Validate the extracted environment and requested episode groups")
    validate.add_argument("--data-root", type=Path, required=True)
    validate.add_argument("--splits", type=Path, default=DEFAULT_SPLITS)
    validate.add_argument("--groups", nargs="+", choices=["demo", "train", "development", "holdout", "unassigned"], default=["demo"])
    validate.add_argument("--require-merged", action="store_true")
    convert = sub.add_parser("convert", help="Run the hash-verified upstream metadata converter")
    convert.add_argument("--data-root", type=Path, required=True)
    convert.add_argument("--converter", type=Path, required=True)
    convert.add_argument("--seed", type=int, default=100)
    args = parser.parse_args()
    manifest = read_json(args.manifest)
    if args.command == "plan":
        return output_report(manifest, args.report)
    if args.command == "verify":
        return output_report(verify_archives(manifest, args.archive_dir, args.category), args.report)
    if args.command == "validate":
        splits = read_json(args.splits)
        if splits["map_id"] != manifest["map_id"]:
            raise ValueError("Asset manifest and split map differ")
        return output_report(validate_extracted(manifest, splits, args.data_root, args.groups, args.require_merged), args.report)
    return convert_metadata(manifest, args.data_root, args.converter, args.seed)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, KeyError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
