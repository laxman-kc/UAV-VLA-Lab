#!/usr/bin/env python3
"""Prepare one complete frozen development/holdout group using metadata only.

Preserves original upstream evaluation rows and reuses select_and_validate for
every selected episode. No pixels, simulator, model, runtime or checkpoint choice.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath


_SPEC = importlib.util.spec_from_file_location("_vla_episode_selector", Path(__file__).with_name("prepare_aerovla_episode.py"))
_SELECTOR = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SELECTOR)
GROUPS = ("train", "development", "holdout", "demo", "unassigned")
ALLOWED = ("development", "holdout")
PINNED_REVISION = "e37685afb8953d1f5a09155d7255960cee1bfd9d"


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def reject_constant(value):
    raise ValueError(f"Nonfinite JSON number: {value}")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_record(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": digest(data)}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def trajectory_path(value, map_name):
    if not isinstance(value, str):
        raise ValueError("Trajectory membership must use strings")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 3 or "\\" in value or str(path) != value:
        raise ValueError("Expected canonical Map/episode-id/merged_data.json membership")
    if path.parts[0] != map_name or path.name != "merged_data.json" or not path.parts[1]:
        raise ValueError("Trajectory path does not match the frozen map or merged-data filename")
    if "data6" in value:
        raise ValueError("Trajectory path would be changed by the inspected loader's data6-to-data5 rewrite")
    return path


def contained(root, relative):
    result = (Path(root) / relative).resolve()
    if not result.is_relative_to(Path(root).resolve()):
        raise ValueError("Selected metadata symlink escapes its declared root")
    return result


def validate_membership(frozen, rows, original_record, group):
    if group not in ALLOWED:
        raise ValueError("Only an entire development or holdout group can be selected")
    if not isinstance(frozen, dict) or frozen.get("schema_version") != "vla.splits.v1":
        raise ValueError("Expected the existing frozen vla.splits.v1 manifest")
    if not isinstance(frozen.get("split_id"), str) or not frozen["split_id"]:
        raise ValueError("Frozen split_id is required")
    if frozen.get("upstream_code_revision") != PINNED_REVISION:
        raise ValueError("Frozen split does not identify the inspected upstream loader revision")
    try:
        frozen_time = dt.datetime.fromisoformat(frozen["frozen_at_utc"].replace("Z", "+00:00"))
        if frozen_time.tzinfo is None or frozen_time > dt.datetime.now(dt.timezone.utc):
            raise ValueError("Frozen time needs a timezone and cannot be in the future")
    except (KeyError, AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Frozen split requires an actual prior ISO8601 frozen_at_utc") from exc
    map_name = frozen.get("map_id")
    if not isinstance(map_name, str) or not map_name or "/" in map_name or "\\" in map_name:
        raise ValueError("Frozen map_id must be one path component")
    groups, counts = frozen.get("groups"), frozen.get("counts")
    if not isinstance(groups, dict) or set(groups) != set(GROUPS) or not isinstance(counts, dict):
        raise ValueError("Frozen train/development/holdout/demo/unassigned memberships and counts are required")
    membership, seen = {}, set()
    for name in GROUPS:
        values = groups[name]
        if not isinstance(values, list):
            raise ValueError(f"Frozen group {name} must be a list")
        for value in values:
            trajectory_path(value, map_name)
        if len(set(values)) != len(values):
            raise ValueError(f"Duplicate episode membership in frozen {name}")
        if type(counts.get(name)) is not int or counts[name] != len(values):
            raise ValueError(f"Frozen {name} count differs from its explicit membership")
        overlap = seen.intersection(values)
        if overlap:
            raise ValueError(f"Frozen groups overlap: {len(overlap)} episode(s)")
        membership[name] = set(values)
        seen.update(values)
    if not membership[group]:
        raise ValueError("The selected complete split group is empty")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Original evaluation JSON must be a nonempty row array")
    by_path, frame_keys = collections.defaultdict(list), set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"Original row {index} is not an object")
        relative = str(trajectory_path(row.get("json"), map_name))
        frame = row.get("frame")
        if type(frame) is not int or frame < 0:
            raise ValueError(f"Original row {index} lacks a nonnegative integer frame")
        if (relative, frame) in frame_keys:
            raise ValueError("Original evaluation JSON contains duplicate trajectory/frame rows")
        frame_keys.add((relative, frame))
        by_path[relative].append(index)
    original_paths = set(by_path)
    expected_eval_paths = set().union(*(membership[name] for name in GROUPS if name != "train"))
    if original_paths != expected_eval_paths:
        raise ValueError(f"Frozen evaluation partition differs from original rows: {len(expected_eval_paths - original_paths)} missing, {len(original_paths - expected_eval_paths)} undeclared")
    if original_paths.intersection(membership["train"]):
        raise ValueError("Original evaluation membership overlaps frozen training membership")
    sources = frozen.get("sources")
    source = sources.get("seen") if isinstance(sources, dict) else None
    if not isinstance(source, dict) or source.get("sha256") != original_record["sha256"]:
        raise ValueError("Original evaluation file SHA256 differs from frozen sources.seen")
    if type(source.get("rows")) is not int or source["rows"] != len(rows) or type(source.get("unique_episodes")) is not int or source["unique_episodes"] != len(original_paths):
        raise ValueError("Frozen original evaluation row/unique-episode counts disagree")
    # The loader deduplicates JSON paths and uses seq_name as its saved-output ID.
    # Enforce a one-to-one path/seq_name mapping; frames remain original source rows.
    selected_ids = [PurePosixPath(path).parts[1] for path in membership[group]]
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError("Selected unique loader paths collide on their episode/seq_name identity")
    return map_name, membership, by_path


def prepare_batch(split, frozen_split, group, dataset_root, metadata_root, output_dir):
    split, frozen_split = Path(split).resolve(), Path(frozen_split).resolve()
    dataset_root, metadata_root = Path(dataset_root).resolve(), Path(metadata_root).resolve()
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        raise FileExistsError("Output already exists; use a fresh immutable selection directory")
    validation_started = utc_now()
    original_bytes, frozen_bytes = split.read_bytes(), frozen_split.read_bytes()
    original_record = {"path": str(split), "bytes": len(original_bytes), "sha256": digest(original_bytes)}
    frozen_record = {"path": str(frozen_split), "bytes": len(frozen_bytes), "sha256": digest(frozen_bytes)}
    rows = json.loads(original_bytes, parse_constant=reject_constant)
    frozen = json.loads(frozen_bytes, parse_constant=reject_constant)
    map_name, memberships, by_path = validate_membership(frozen, rows, original_record, group)
    selected_paths = memberships[group]
    expected_rows = [row for row in rows if row["json"] in selected_paths]
    expected_indices = [index for index, row in enumerate(rows) if row["json"] in selected_paths]
    ledger = {str(split): original_record, str(frozen_split): frozen_record}
    metadata_paths = [contained(metadata_root, name) for name in ("map_spawnarea_info.json", "object_description.json")]
    for relative in sorted(selected_paths):
        parent = PurePosixPath(relative).parent
        metadata_paths.extend(contained(dataset_root, str(parent / name)) for name in ("merged_data.json", "mark.json", "object_description.json"))
    for path in metadata_paths:
        ledger[str(path)] = file_record(path)
    episodes = []
    for relative in sorted(selected_paths):
        episode_id = PurePosixPath(relative).parts[1]
        selected, episode_manifest = _SELECTOR.select_and_validate(split, dataset_root, metadata_root, episode_id)
        indices = by_path[relative]
        if selected != [rows[index] for index in indices] or episode_manifest["unique_trajectories"] != 1 or episode_manifest["map_name"] != map_name:
            raise ValueError("Existing episode selector differs from complete frozen membership/source rows")
        for record in episode_manifest["source_files"]:
            if record != ledger.get(record["path"]):
                raise ValueError("Metadata/source bytes changed while the existing episode validation ran")
        episodes.append({"map_name": map_name, "episode_id": episode_id, "json": relative,
            "loader_identity": {"map_name": map_name, "seq_name": episode_id, "merged_json_relative": relative},
            "original_row_count": len(indices), "source_row_indices": indices,
            "preserved_rows_canonical_sha256": digest(canonical(selected)),
            "reference_frame_count": episode_manifest["reference_frame_count"],
            "metadata_validated": True,
            "source_files": [record for record in episode_manifest["source_files"] if record["path"] != str(split)]})
    if len(episodes) != len(frozen["groups"][group]) or sum(item["original_row_count"] for item in episodes) != len(expected_rows):
        raise ValueError("Selected row/episode accounting is incomplete")
    for path, initial in ledger.items():
        if file_record(Path(path)) != initial:
            raise ValueError("Source file changed during batch selection; use stable original metadata")
    # Record actual creation time only after metadata validation. It is not the
    # frozen split time and does not imply that any evaluation has been executed.
    created_at = utc_now()
    manifest = {"schema_version": "vla.evaluation-batch.v1", "kind": "complete_frozen_evaluation_group_selection",
        "created_at_utc": created_at, "validation_started_at_utc": validation_started,
        "split_id": frozen["split_id"], "split_frozen_at_utc": frozen["frozen_at_utc"], "group": group, "map_name": map_name,
        "unique_episodes": len(episodes), "original_row_count": len(expected_rows),
        "original_evaluation_rows": len(rows), "original_evaluation_unique_episodes": len(by_path),
        "selected_trajectories_in_frozen_order": frozen["groups"][group],
        "selected_source_row_indices": expected_indices, "preserved_rows_canonical_sha256": digest(canonical(expected_rows)),
        "row_order": "Original evaluation file order; every selected original row is preserved unchanged",
        "source_files": list(ledger.values()), "frozen_split_source": frozen_record, "original_evaluation_source": original_record,
        "episodes": episodes, "checks": {"complete_group_selected": True, "all_groups_disjoint": True,
            "original_eval_hash_matches_frozen_source": True, "full_eval_partition_matches_original": True,
            "unique_loader_identity_per_episode": True, "all_original_selected_rows_preserved": True,
            "existing_episode_metadata_checks_passed": True, "source_files_stable_during_validation": True},
        "loader_semantics": {"inspected_upstream_revision": PINNED_REVISION,
            "source": "src/vlnce_src/env_uav.py:AirVLNENV.load_my_datasets/_group_scenes",
            "deduplication": "One loaded entry per unique JSON trajectory path, not one per frame row",
            "path_sorted_episode_order": [item["episode_id"] for item in episodes],
            "default_same_map_length_grouped_episode_order": [item["episode_id"] for item in sorted(episodes, key=lambda item: (item["reference_frame_count"], item["json"]))],
            "ordering_scope": "Metadata projection for the inspected default scene grouping; actual runtime event order must still be recorded",
            "dataset_path_requirement": "Launch from upstream checkout using --dataset_path ./dataset_raw/ and its verified metadata symlink",
            "save_path_requirement": "Use a fresh empty evaluator save directory; upstream otherwise skips existing saved seq_name entries",
            "batch_size_requirement": "Use batchSize=1 with current instrumentation; a multi-episode JSON is not simultaneous inference batching"},
        "code_files": [file_record(Path(__file__)), file_record(Path(_SELECTOR.__file__))],
        "holdout_access": {"pixel_files_opened": False, "pixel_files_rendered": False,
            "scope": "Only declared JSON metadata was read; source instructions/poses were validated but are not copied into this manifest"},
        "not_validated_here": ["model/checkpoint/runtime identity", "compiled map or simulator readiness", "image contents or quality",
            "actual evaluator episode count/order/outcomes", "absence of these episodes from original pretraining"],
        "execution_performed": False}
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json(output_dir / "episodes.json", expected_rows)
    (output_dir / "frozen_split.snapshot.json").write_bytes(frozen_bytes)
    manifest["outputs"] = {name: file_record(output_dir / name) for name in ("episodes.json", "frozen_split.snapshot.json")}
    write_json(output_dir / "selection_manifest.json", manifest)
    write_json(output_dir / "checksums.json", {path.name: file_record(path)["sha256"] for path in sorted(output_dir.iterdir()) if path.is_file()})
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", type=Path, required=True, help="Original upstream map evaluation row JSON")
    parser.add_argument("--frozen-split", type=Path, required=True, help="Existing vla.splits.v1 membership manifest")
    parser.add_argument("--group", choices=ALLOWED, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--metadata-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    options = parser.parse_args()
    manifest = prepare_batch(options.split, options.frozen_split, options.group, options.dataset_root, options.metadata_root, options.output_dir)
    print(json.dumps({"selected": True, "group": manifest["group"], "unique_episodes": manifest["unique_episodes"],
                      "original_row_count": manifest["original_row_count"], "created_at_utc": manifest["created_at_utc"],
                      "output_dir": str(options.output_dir.resolve()), "pixel_access": False, "execution_performed": False}))


if __name__ == "__main__":
    main()
