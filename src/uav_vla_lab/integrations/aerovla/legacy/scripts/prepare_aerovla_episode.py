#!/usr/bin/env python3
"""Select one genuine upstream trajectory and validate its evaluation metadata.

This never creates mark.json, merged_data.json, expert labels or model results.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def file_record(path: Path) -> dict:
    data = path.read_bytes()
    return {"path": str(path.resolve()), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def load_json(path: Path):
    return json.loads(path.read_text())


def select_and_validate(split: Path, dataset_root: Path, metadata_root: Path, episode_id: str):
    rows = load_json(split)
    if not isinstance(rows, list):
        raise ValueError("Split must be the original JSON row array")
    selected = [row for row in rows if PurePosixPath(row["json"]).parts[-2] == episode_id]
    paths = {row["json"] for row in selected}
    if len(paths) != 1:
        raise ValueError(f"Episode ID must identify exactly one original trajectory; found {len(paths)}")
    relative = PurePosixPath(next(iter(paths)))
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 3:
        raise ValueError("Expected Map/episode-id/merged_data.json in original split")
    if relative.name != "merged_data.json":
        raise ValueError("Selected trajectory does not reference merged_data.json")
    trajectory_dir = dataset_root / str(relative.parent)
    merged_path = trajectory_dir / "merged_data.json"
    mark_path = trajectory_dir / "mark.json"
    description_path = trajectory_dir / "object_description.json"
    merged, mark = load_json(merged_path), load_json(mark_path)
    load_json(description_path)
    trajectory = merged["trajectory_raw_detailed"]
    if not trajectory:
        raise ValueError("Original trajectory contains no initial state")
    if len(trajectory[0]["position"]) != 3 or len(trajectory[0]["orientation"]) != 4:
        raise ValueError("Initial state must contain xyz position and xyzw quaternion")
    if len(mark["target"]["position"]) != 3 or not mark["object_name"]:
        raise ValueError("Target metadata is incomplete")
    instruction = merged["conversations"][0]["value"]
    if "degrees from you." not in instruction or " Please control" not in instruction:
        raise ValueError("Instruction does not satisfy the unchanged upstream prompt parser")
    spawn_path = metadata_root / "map_spawnarea_info.json"
    objects_path = metadata_root / "object_description.json"
    spawn = load_json(spawn_path)
    load_json(objects_path)
    map_name = relative.parts[0]
    if not any(len(area) >= 18 for area in spawn.get(map_name, [])):
        raise ValueError(f"No upstream-compatible target spawn areas for {map_name}")
    manifest = {
        "schema_version": 1, "kind": "genuine_upstream_episode_selection", "map_name": map_name,
        "episode_id": episode_id, "unique_trajectories": 1, "original_row_count": len(selected),
        "reference_frame_count": len(trajectory), "instruction": instruction,
        "goal_information": "official benchmark target-position-derived bearing",
        "source_files": [file_record(path) for path in
                         (split, merged_path, mark_path, description_path, spawn_path, objects_path)],
        "not_validated_here": ["compiled scene assets and their shared libraries", "model files", "CUDA/graphics", "scene manager"],
        "dataset_path_requirement": "Launch from upstream checkout with --dataset_path ./dataset_raw/; use a symlink if needed",
    }
    return selected, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--list", action="store_true", help="List genuine unique IDs; needs only --split")
    parser.add_argument("--episode-id")
    parser.add_argument("--dataset-root", type=Path)
    parser.add_argument("--metadata-root", type=Path, help="Upstream data/meta directory")
    parser.add_argument("--output-dir", type=Path)
    options = parser.parse_args()
    if options.list:
        paths = sorted({row["json"] for row in load_json(options.split)})
        for path in paths:
            print(json.dumps({"episode_id": PurePosixPath(path).parts[-2], "json": path}))
        return
    if not all((options.episode_id, options.dataset_root, options.metadata_root, options.output_dir)):
        parser.error("Selection requires --episode-id, --dataset-root, --metadata-root and --output-dir")
    rows, manifest = select_and_validate(options.split, options.dataset_root, options.metadata_root, options.episode_id)
    options.output_dir.mkdir(parents=True, exist_ok=True)
    for name, data in (("episode.json", rows), ("selection_manifest.json", manifest)):
        with (options.output_dir / name).open("x") as output:
            json.dump(data, output, indent=2)
            output.write("\n")
    print(json.dumps({"selected": True, "episode": options.episode_id, "output_dir": str(options.output_dir.resolve())}))


if __name__ == "__main__":
    main()
