"""Acquire only explicitly pinned, hash-declared model or dataset files."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
from urllib.parse import quote


def validate_intent(document: dict) -> list[dict]:
    if document.get("schema_version") != "uav-vla.snapshot-intent.v1" or not document.get("files"):
        raise ValueError("An explicit nonempty uav-vla.snapshot-intent.v1 is required")
    files, destinations = [], set()
    for item in document["files"]:
        repo, revision = item["repository"], item["revision"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("Repository and immutable 40-hex revision required; latest/main are forbidden")
        kind = item.get("repo_type", "model")
        if kind not in ("model", "dataset"):
            raise ValueError("Only model/dataset repositories are supported")
        for field in ("filename", "relative_path"):
            value = item[field]
            path = PurePosixPath(value)
            if not value or not path.parts or path.is_absolute() or ".." in path.parts or "\\" in value or str(path) != value or "\x00" in value:
                raise ValueError("Snapshot paths must be canonical contained relative paths")
        if item["relative_path"] in destinations:
            raise ValueError("Duplicate snapshot destination")
        destinations.add(item["relative_path"])
        if not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) or type(item["bytes"]) is not int or item["bytes"] < 0:
            raise ValueError("Every file needs its previously declared byte size and SHA256")
        url = "https://huggingface.co/" + ("datasets/" if kind == "dataset" else "") + repo + "/resolve/" + revision + "/" + quote(item["filename"], safe="/")
        if "url" in item and item["url"] != url:
            raise ValueError("Declared URL is inconsistent with the immutable repository path")
        files.append({**item, "url": url})
    return files


def target(root: Path, relative: str) -> Path:
    result = root / relative
    if not result.resolve().is_relative_to(root.resolve()) or any(p.is_symlink() for p in [result, *result.parents] if p != root.parent):
        raise ValueError("Snapshot destination contains a symlink or escapes its root")
    return result


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intent", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Download missing files; default validates intent and prints storage plan only")
    parser.add_argument("--reserve-gib", type=int, default=60)
    args = parser.parse_args(argv)
    if args.reserve_gib < 0:
        parser.error("reserve must be nonnegative")
    files = validate_intent(json.loads(args.intent.read_text()))
    if not args.apply:
        print(json.dumps({"status": "planned_not_downloaded", "file_count": len(files), "declared_bytes": sum(f["bytes"] for f in files), "intent_sha256": digest(args.intent)}, indent=2))
        return 0
    args.root = args.root.resolve()
    receipt = args.root / "snapshot-files.verified.json"
    if receipt.exists():
        raise ValueError("Receipt already exists; preserve it and choose a separate acquisition root")
    args.root.mkdir(parents=True, exist_ok=True)
    missing = sum(f["bytes"] for f in files if not target(args.root, f["relative_path"]).exists())
    if shutil.disk_usage(args.root).free < missing + args.reserve_gib * 1024**3:
        raise ValueError("Insufficient measured free space for missing files and explicit reserve")
    records = []
    for item in files:
        output = target(args.root, item["relative_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        if not output.exists():
            partial = target(args.root, item["relative_path"] + ".partial")
            subprocess.run(["curl", "--fail", "--location", "--proto", "=https", "--proto-redir", "=https", "--continue-at", "-", "--retry", "4", "--connect-timeout", "30", "--max-time", "3600", "--output", str(partial), item["url"]], check=True)
            if partial.stat().st_size != item["bytes"] or digest(partial) != item["sha256"]:
                raise ValueError("Downloaded file differs from declared intent; partial retained")
            partial.rename(output)
        if output.stat().st_size != item["bytes"] or digest(output) != item["sha256"]:
            raise ValueError("Existing file differs from declared intent; not overwritten")
        records.append({**item, "path": str(output.resolve()), "status": "verified"})
    receipt.write_text(json.dumps({"schema_version": "uav-vla.snapshot-verification.v1", "intent_sha256": digest(args.intent), "files": records}, indent=2) + "\n")
    print(json.dumps({"status": "verified", "files": len(records), "receipt": str(receipt)}))
    return 0
