"""Portable file receipts. Hash agreement proves integrity, not authenticity."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from .config import ContractError


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path, *, relative_to):
    path = Path(path)
    return {"path": path.relative_to(relative_to).as_posix(),
            "bytes": path.stat().st_size, "sha256": sha256(path)}


def local_file(root, relative):
    """Resolve a manifest member without allowing traversal or symlink redirection."""
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ContractError("Expected a portable relative file path")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in (".", "..") for part in relative.split("/")) or pure.as_posix() != relative:
        raise ContractError("Manifest path must stay inside the bundle")
    root = Path(root).resolve()
    path = root.joinpath(*pure.parts)
    cursor = root
    for part in pure.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ContractError("Symlink members are not allowed in a replay bundle")
    if not path.is_file():
        raise ContractError(f"Missing bundle member: {relative}")
    return path


def verify_record(root, record):
    if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
        raise ContractError("Invalid file receipt")
    path = local_file(root, record["path"])
    if type(record["bytes"]) is not int or record["bytes"] < 0 or path.stat().st_size != record["bytes"]:
        raise ContractError(f"File size mismatch: {record['path']}")
    if sha256(path) != record["sha256"]:
        raise ContractError(f"SHA256 mismatch: {record['path']}")
    return path
