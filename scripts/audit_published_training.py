#!/usr/bin/env python3
"""Audit the pinned publisher's training manifest; do not approve or train labels."""
import argparse
import collections
import datetime
import hashlib
import json
import math
from pathlib import Path

EXPECTED_SHA = "1c1e32787cedb096fe5df2511e5bf3cc81901b8a30d261df73ebcb800c868a67"


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--split", type=Path, required=True)
    p.add_argument("--dataset-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if digest(a.source) != EXPECTED_SHA:
        raise SystemExit("Published source differs from the pinned SHA256")
    a.output.mkdir(parents=True, exist_ok=False)
    rows = json.loads(a.source.read_text())
    split = json.loads(a.split.read_text())
    groups = {k: set(v) for k, v in split["groups"].items()}
    maps, schemas, represented = collections.Counter(), collections.Counter(), set()
    overlap_rows = {k: 0 for k in groups}
    target = {"rows": 0, "missing_front": 0, "missing_down": 0, "duplicate_image_pairs": 0,
              "invalid_or_out_of_range_labels": 0, "invalid_terminal_flags": 0}
    seen = set()
    for row in rows:
        schemas[",".join(sorted(row))] += 1
        trajectory = row.get("traj_rel_dir", "")
        parts = trajectory.split("/")
        maps[parts[0]] += 1
        episode = trajectory + "/merged_data.json"
        represented.add(episode)
        for k, members in groups.items():
            overlap_rows[k] += episode in members
        if parts[0] != split["map_id"]:
            continue
        target["rows"] += 1
        if len(parts) != 2 or ".." in parts or Path(trajectory).is_absolute():
            raise ValueError("Unexpected trajectory path in selected-map source")
        filename = row.get("img_name", "")
        if not filename or Path(filename).name != filename:
            raise ValueError("Unexpected image path in selected-map source")
        pair = (trajectory, filename)
        target["duplicate_image_pairs"] += pair in seen
        seen.add(pair)
        # Check filenames only. Do not inspect holdout pixels, target descriptions or labels for selection.
        for name, folder in (("front", "frontcamera"), ("down", "downcamera")):
            target["missing_" + name] += not (a.dataset_root / trajectory / folder / filename).is_file()
        label = row.get("label", {})
        bounds = {"fwd": (0, 5), "down": (-5, 5), "yaw": (-1.1, 1.1)}
        valid = set(label) == set(bounds) and all(type(label[k]) in (int, float) and math.isfinite(label[k]) and lo <= label[k] <= hi for k, (lo, hi) in bounds.items())
        target["invalid_or_out_of_range_labels"] += not valid
        target["invalid_terminal_flags"] += any(type(row.get(k)) is not bool for k in ("is_last_step", "is_penultimate"))
    report = {"schema_version": "vla.published-training-audit.v1", "status": "audit_completed_not_label_approval",
              "recorded_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "source": {"repository": "XuPeng23/AerialVLA", "revision": "196f2f3253b69df6e90ac10b6ae041c7b3a9569e",
                         "filename": "aerovla_train_dataset.json", "sha256": EXPECTED_SHA, "bytes": a.source.stat().st_size},
              "split_sha256": digest(a.split), "script_sha256": digest(Path(__file__)),
              "rows": len(rows), "unique_episodes": len(represented), "rows_by_map": maps, "row_schemas": schemas,
              "project_overlap": {k: {"published_rows": overlap_rows[k], "represented_episodes": len(members & represented),
                                      "declared_episodes": len(members)} for k, members in groups.items()},
              "selected_map_file_and_schema_audit": target,
              "limitations": ["Manifest membership does not prove which rows were actually used for released weights.",
                  "No label source or exact action horizon is inferred; this is not approval for training.",
                  "No image pixels were read; existence and schema checks do not establish action correctness.",
                  "No samples were selected, rewritten, clipped, or exported for training."]}
    (a.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
