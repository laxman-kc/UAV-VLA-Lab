"""Generated standard-library reviewed-dataset contract; no labels are created.

Source: scripts/train_adapter_mvp.py. Regenerate with sync_workflow_resources.py.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import math
from pathlib import Path, PurePosixPath

LABEL_BOUNDS = {"fwd": (0.0, 5.0), "down": (-5.0, 5.0), "yaw": (-1.1, 1.1)}
EXPERT_SOURCES = {"human_expert", "audited_reference_expert", "approved_controller_expert"}


class ContractError(ValueError):
    pass


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def file_record(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size}


def contained(root, relative):
    if not isinstance(relative, str) or not relative:
        raise ContractError("A nonempty relative file path is required")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
        raise ContractError(f"Path escapes its declared root: {relative}")
    path = (Path(root) / relative).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ContractError(f"Path escapes its declared root: {relative}")
    return path


def verify_record(record, root, expected_path=None):
    if not isinstance(record, dict) or not record.get("sha256"):
        raise ContractError("File evidence requires path and SHA256")
    path = contained(root, record.get("path"))
    if expected_path is not None and path != Path(expected_path).resolve():
        raise ContractError(f"Evidence references a different file: {record.get('path')}")
    if not path.is_file() or digest(path) != record["sha256"]:
        raise ContractError(f"Missing or changed evidence bytes: {record.get('path')}")
    if "bytes" in record and path.stat().st_size != record["bytes"]:
        raise ContractError(f"Evidence size mismatch: {record['path']}")
    return path


def require_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"Missing explicit {field}")


def validate_dataset(data_json, dataset_root, manifest_path):
    """Recheck declared provenance and split membership; do not approve labels."""
    manifest_path, dataset_root = Path(manifest_path), Path(dataset_root)
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != "vla.training-dataset.v1" or manifest.get("status") != "validated":
        raise ContractError("Dataset requires a vla.training-dataset.v1 manifest with status=validated")
    verify_record(manifest.get("data_json"), manifest_path.parent, data_json)
    split_path = verify_record(manifest.get("split_manifest"), manifest_path.parent)
    split = read_json(split_path)
    if split.get("schema_version") != "vla.splits.v1" or not split.get("frozen_at_utc"):
        raise ContractError("A frozen vla.splits.v1 manifest is required")
    groups = split.get("groups", {})
    if not all(isinstance(groups.get(name), list) for name in ("train", "development", "holdout")):
        raise ContractError("Split must declare train, development and holdout membership")
    seen = set()
    for name, members in groups.items():
        if not isinstance(members, list) or len(set(members)) != len(members) or seen.intersection(members):
            raise ContractError(f"Duplicate or overlapping split membership: {name}")
        for member in members:
            if str(PurePosixPath(member)) != member or len(PurePosixPath(member).parts) != 3 or not member.endswith("/merged_data.json"):
                raise ContractError("Split IDs must be Map/episode/merged_data.json")
            contained(dataset_root, member)
        seen.update(members)
    policy = manifest.get("label_policy", {})
    if policy.get("source_kind") not in EXPERT_SOURCES:
        raise ContractError("Expert provenance must be explicit; model predictions are not expert labels")
    if policy.get("action_units") != {"fwd": "m", "down": "m", "yaw": "rad"}:
        raise ContractError("Upstream physical action labels require fwd/down metres and yaw radians")
    for field in ("source_description", "action_frame", "action_horizon", "stop_semantics", "temporal_alignment"):
        require_text(policy.get(field), f"label_policy.{field}")
    approval = manifest.get("approval", {})
    if approval.get("status") != "approved":
        raise ContractError("Dataset has no recorded expert review approval")
    for field in ("reviewer", "reviewed_at_utc"):
        require_text(approval.get(field), f"approval.{field}")
    verify_record(approval.get("evidence"), manifest_path.parent)
    rows = read_json(data_json)
    records = manifest.get("samples")
    if not isinstance(rows, list) or not rows or not isinstance(records, list) or len(records) != len(rows):
        raise ContractError("Every nonempty training row needs exactly one manifest sample")
    ids, image_pairs = set(), set()
    for index, (row, record) in enumerate(zip(rows, records)):
        if not isinstance(row, dict) or record.get("row_index") != index or record.get("row_sha256") != canonical_hash(row):
            raise ContractError(f"Sample row identity mismatch at index {index}")
        sample_id = record.get("sample_id")
        require_text(sample_id, "sample_id")
        if sample_id in ids:
            raise ContractError("Duplicate sample ID")
        ids.add(sample_id)
        trajectory, filename = row.get("traj_rel_dir"), row.get("img_name")
        if not isinstance(trajectory, str) or len(PurePosixPath(trajectory).parts) != 2:
            raise ContractError("traj_rel_dir must be Map/episode")
        if not isinstance(filename, str) or PurePosixPath(filename).name != filename or Path(filename).suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise ContractError("img_name must identify one saved PNG/JPEG filename")
        episode = trajectory + "/merged_data.json"
        if record.get("episode_id") != episode or record.get("split") != "train" or episode not in groups["train"]:
            raise ContractError(f"Training sample is outside its attested train split: {sample_id}")
        require_text(row.get("instruction"), "instruction")
        if any(type(row.get(key)) is not bool for key in ("is_last_step", "is_penultimate")):
            raise ContractError("Stop flags must be explicit booleans from reviewed labels")
        labels = row.get("label", {})
        if set(labels) != set(LABEL_BOUNDS):
            raise ContractError("label must contain exactly fwd/down/yaw")
        for axis, (low, high) in LABEL_BOUNDS.items():
            value = labels[axis]
            if type(value) not in (float, int) or not math.isfinite(value) or not low <= value <= high:
                raise ContractError(f"Invalid {axis} label; refusing upstream silent clipping")
        pair = (trajectory, filename)
        if pair in image_pairs:
            raise ContractError("Duplicate observation pair in training data")
        image_pairs.add(pair)
        for camera, folder in (("front", "frontcamera"), ("down", "downcamera")):
            expected = contained(dataset_root, f"{trajectory}/{folder}/{filename}")
            verify_record(record.get("images", {}).get(camera), dataset_root, expected)
        sources = record.get("source_evidence")
        if not isinstance(sources, list) or not sources:
            raise ContractError("Every label needs source evidence, including its temporal/state provenance")
        for evidence in sources:
            verify_record(evidence, dataset_root)
    return {"status": "passed", "sample_count": len(rows), "sample_ids": [r["sample_id"] for r in records],
            "episode_ids": sorted({r["episode_id"] for r in records}),
            "data_json": file_record(data_json), "dataset_manifest": file_record(manifest_path),
            "split_manifest": file_record(split_path), "approval": approval, "label_policy": policy,
            "limitation": "Hashes and declarations are checked; this program does not establish that expert labels are correct."}


