#!/usr/bin/env python3
"""Opt-in preparation of five unchanged published training rows for P10 only.

No downloads, model imports, expert approval, recovery labels, or P09 completion.
The resulting strict reference schema is distinct from a reviewed-expert dataset.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import math
from pathlib import Path, PurePosixPath


PUBLISHED = {"repository": "XuPeng23/AerialVLA", "revision": "196f2f3253b69df6e90ac10b6ae041c7b3a9569e",
    "filename": "aerovla_train_dataset.json", "sha256": "1c1e32787cedb096fe5df2511e5bf3cc81901b8a30d261df73ebcb800c868a67",
    "bytes": 257288037}
OFFICIAL_TRAIN = {"repository": "wangxiangyu0814/TravelUAV_data_json", "revision": "5a1ed4c99d3e7bb2b35fa34135910cb7687fc831",
    "file": "data/uav_dataset/trainset.json", "sha256": "5c1c82df9f3b2b351499bcbcce7af02e17445e9e931f5569d546aefd4ce5eb8c"}
UPSTREAM_REVISION = "e37685afb8953d1f5a09155d7255960cee1bfd9d"
UPSTREAM_FILES = {"src/aerovla_dataset.py": "55f2804162f4992eb481cda68b971edca833841a3fe5170560a8878ddb6916f7",
                  "src/train_aerovla.py": "5bde78d405c6153d89440d0c81acae5e0be9ca67cb9843141827ddd7a19d6ec2"}
BOUNDS = {"fwd": (0, 5), "down": (-5, 5), "yaw": (-1.1, 1.1)}
ROW_FIELDS = {"traj_rel_dir", "img_name", "instruction", "label", "is_last_step", "is_penultimate"}
COUNT = 5
RULE = "aerovla-published-reference-five-v1"
SCHEMA = "vla.published-reference-preparation.v1"
STATUS = "prepared_published_reference_not_expert_approved"
POLICY = {"source_kind": "publisher_provided_reference_targets", "purpose": "P10_published_reference_mechanics_only",
    "action_units_consumed_by_training_contract": {"fwd": "m", "down": "m", "yaw": "rad"},
    "physical_action_horizon": {"status": "not_established", "value": None},
    "physical_action_frame": {"status": "not_independently_established", "value": None},
    "physical_label_generation_and_alignment": "Not established by publisher manifest membership or reader code",
    "stop_semantics": "Original reader appends LAND when is_last_step OR is_penultimate; flags remain exactly publisher supplied",
    "label_changes": "None; out-of-range/nonfinite rows are rejected before selection, never clipped or regenerated",
    "expert_or_recovery_correctness": "Not asserted"}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for data in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            result.update(data)
    return result.hexdigest()


def file_record(path, relative_to=None):
    path = Path(path).resolve()
    return {"path": str(path.relative_to(Path(relative_to).resolve())) if relative_to is not None else str(path),
            "sha256": digest(path), "bytes": path.stat().st_size}


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                    allow_nan=False).encode("utf-8")).hexdigest()


def read_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def contained(root, relative):
    if not isinstance(relative, str) or not relative:
        raise ValueError("A relative source path is required")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative or str(pure) != relative:
        raise ValueError("Noncanonical or escaping source path")
    result = (Path(root) / relative).resolve()
    if not result.is_relative_to(Path(root).resolve()):
        raise ValueError("Source symlink escapes dataset root")
    return result


def episode_path(value, map_name=None):
    if not isinstance(value, str):
        raise ValueError("Episode membership must be a string")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value or str(path) != value or len(path.parts) != 3 or path.name != "merged_data.json":
        raise ValueError("Expected canonical Map/episode/merged_data.json membership")
    if map_name is not None and path.parts[0] != map_name:
        raise ValueError("Frozen membership differs from map_id")
    return path


def validate_split(frozen, official_rows):
    if not isinstance(frozen, dict) or frozen.get("schema_version") != "vla.splits.v1" or frozen.get("upstream_code_revision") != UPSTREAM_REVISION:
        raise ValueError("Expected frozen split for the inspected upstream revision")
    try:
        stamp = dt.datetime.fromisoformat(frozen["frozen_at_utc"].replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp > dt.datetime.now(dt.timezone.utc):
            raise ValueError("Future or naive frozen time")
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError("An actual prior timezone-aware split freeze time is required") from exc
    map_name, groups, counts = frozen.get("map_id"), frozen.get("groups"), frozen.get("counts")
    if not isinstance(map_name, str) or not map_name or not isinstance(groups, dict) or not isinstance(counts, dict):
        raise ValueError("Frozen map/groups/counts are required")
    if not {"train", "development", "holdout", "demo"}.issubset(groups):
        raise ValueError("Frozen training and evaluation isolation must be explicit")
    seen, memberships = set(), {}
    for group, members in groups.items():
        if not isinstance(members, list):
            raise ValueError("Every split membership must be a list")
        for member in members:
            episode_path(member, map_name)
        if len(set(members)) != len(members) or seen.intersection(members):
            raise ValueError("Duplicate or overlapping frozen split memberships")
        if type(counts.get(group)) is not int or counts[group] != len(members):
            raise ValueError("Frozen counts disagree with membership")
        memberships[group] = set(members)
        seen.update(members)
    sources = frozen.get("sources")
    source = sources.get("train") if isinstance(sources, dict) else None
    if not isinstance(source, dict) or any(source.get(key) != value for key, value in OFFICIAL_TRAIN.items()):
        raise ValueError("Frozen official training-source provenance differs from the pinned source")
    if not isinstance(official_rows, list):
        raise ValueError("Official training split must be a row array")
    map_rows = [row for row in official_rows if isinstance(row, dict) and isinstance(row.get("json"), str)
                and episode_path(row["json"]).parts[0] == map_name]
    official_members = {row["json"] for row in map_rows}
    if memberships["train"] != official_members or source.get("unique_map_episodes") != len(official_members) or source.get("map_rows") != len(map_rows):
        raise ValueError("Frozen train membership does not exactly match the official map training split")
    return map_name, memberships


def row_reasons(row, dataset_root):
    errors, images = [], {}
    if not isinstance(row, dict) or set(row) != ROW_FIELDS:
        return ["unexpected_row_schema"], images
    try:
        episode_path(str(row.get("traj_rel_dir")) + "/merged_data.json")
        name = row.get("img_name")
        if not isinstance(name, str) or PurePosixPath(name).name != name or Path(name).suffix.lower() not in (".png", ".jpg", ".jpeg"):
            raise ValueError("Invalid image filename")
        for camera, folder in (("front", "frontcamera"), ("down", "downcamera")):
            relative = f"{row['traj_rel_dir']}/{folder}/{name}"
            path = contained(dataset_root, relative)
            if not path.is_file():
                errors.append("missing_" + camera + "_image")
            images[camera] = relative
    except (ValueError, OSError):
        errors.append("invalid_image_or_trajectory_path")
    if not isinstance(row.get("instruction"), str) or not row["instruction"].strip():
        errors.append("missing_instruction")
    if any(type(row.get(key)) is not bool for key in ("is_last_step", "is_penultimate")):
        errors.append("invalid_terminal_flags")
    label = row.get("label")
    if not isinstance(label, dict) or set(label) != set(BOUNDS):
        errors.append("invalid_label_schema")
    else:
        for key, (low, high) in BOUNDS.items():
            if type(label[key]) not in (int, float) or not math.isfinite(label[key]) or not low <= label[key] <= high:
                errors.append("invalid_or_out_of_range_" + key)
    return errors, images


def rank(kind, value):
    return hashlib.sha256((RULE + "\n" + kind + "\n" + value).encode("utf-8")).hexdigest()


def collect(source, official_train_json, frozen_split, audit_report, dataset_root, upstream):
    source, official_train_json, frozen_split, audit_report = map(lambda path: Path(path).resolve(),
                                                                 (source, official_train_json, frozen_split, audit_report))
    dataset_root, upstream = Path(dataset_root).resolve(), Path(upstream).resolve()
    inputs = {name: file_record(path) for name, path in (("published_manifest", source), ("official_train_manifest", official_train_json),
             ("frozen_split", frozen_split), ("published_audit", audit_report))}
    if inputs["published_manifest"]["sha256"] != PUBLISHED["sha256"] or inputs["published_manifest"]["bytes"] != PUBLISHED["bytes"]:
        raise ValueError("Published training manifest bytes differ from the authoritative pinned release")
    if inputs["official_train_manifest"]["sha256"] != OFFICIAL_TRAIN["sha256"]:
        raise ValueError("Official training split differs from its pinned SHA256")
    code = []
    for relative, expected in UPSTREAM_FILES.items():
        record = file_record(upstream / relative)
        if record["sha256"] != expected:
            raise ValueError("Original dataset reader/trainer source differs from the inspected hash")
        code.append(record)
    frozen, audit = read_json(frozen_split), read_json(audit_report)
    map_name, groups = validate_split(frozen, read_json(official_train_json))
    if not isinstance(audit, dict) or audit.get("schema_version") != "vla.published-training-audit.v1" or audit.get("status") != "audit_completed_not_label_approval":
        raise ValueError("Require the existing published-source audit, without treating it as approval")
    if audit.get("source") != PUBLISHED or audit.get("split_sha256") != inputs["frozen_split"]["sha256"]:
        raise ValueError("Published audit is not bound to these source and frozen split bytes")
    rows = read_json(source)
    if not isinstance(rows, list) or len(rows) != audit.get("rows"):
        raise ValueError("Published row count disagrees with its audit")
    overlap = {name: {"published_rows": 0, "episodes": set()} for name in groups}
    eligible, rejected, pair_counts = collections.defaultdict(list), [], collections.Counter()
    inspected = []
    selected_map_count = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("traj_rel_dir"), str):
            raise ValueError("Pinned source has an unidentifiable trajectory row")
        episode = row["traj_rel_dir"] + "/merged_data.json"
        if row["traj_rel_dir"].split("/", 1)[0] == map_name:
            selected_map_count += 1
        for name, members in groups.items():
            if episode in members:
                overlap[name]["published_rows"] += 1
                overlap[name]["episodes"].add(episode)
        if episode not in groups["train"]:
            continue  # Never read/hash any evaluation or holdout image/state file.
        errors, images = row_reasons(row, dataset_root)
        pair = (row["traj_rel_dir"], row.get("img_name"))
        if isinstance(pair[1], str):
            pair_counts[pair] += 1
        inspected.append((index, row, episode, errors, images))
    for name, actual in overlap.items():
        expected = {"published_rows": actual["published_rows"], "represented_episodes": len(actual["episodes"]), "declared_episodes": len(groups[name])}
        if audit.get("project_overlap", {}).get(name) != expected:
            raise ValueError("Recomputed source membership differs from published audit")
        if name != "train" and actual["published_rows"]:
            raise ValueError("Published rows overlap project evaluation membership")
    for index, row, episode, errors, images in inspected:
        if isinstance(row.get("img_name"), str) and pair_counts[(row["traj_rel_dir"], row["img_name"])] > 1:
            errors.append("duplicate_published_image_pair")
        if errors:
            rejected.append({"source_row_index": index, "episode_id": episode, "img_name": row.get("img_name") if isinstance(row.get("img_name"), str) else None,
                             "reasons": errors})
        else:
            eligible[episode].append((index, row, images))
    if selected_map_count != audit.get("selected_map_file_and_schema_audit", {}).get("rows"):
        raise ValueError("Selected-map published row count disagrees with audit")
    if len(eligible) < COUNT:
        raise ValueError(f"Need five distinct official training episodes with eligible original rows; found {len(eligible)}")
    selected_rows, samples, chosen_files = [], [], []
    for episode in sorted(eligible, key=lambda value: (rank("episode", value), value))[:COUNT]:
        index, row, image_paths = min(eligible[episode], key=lambda item: (rank("image", episode + "\n" + item[1]["img_name"]), item[1]["img_name"], item[0]))
        row_hash = canonical_hash(row)
        sample = {"row_index": len(samples), "source_row_index": index, "source_row_sha256": row_hash, "row_sha256": row_hash,
            "sample_id": "published-" + row_hash[:20], "episode_id": episode, "split": "train",
            "episode_selection_rank": rank("episode", episode), "image_selection_rank": rank("image", episode + "\n" + row["img_name"]),
            "images": {camera: file_record(contained(dataset_root, path), dataset_root) for camera, path in image_paths.items()},
            "state_file": None, "state_alignment_claim": "No action interval inferred; any state link uses filename correspondence only"}
        # This is optional provenance, not an invented requirement of the reader.
        state_relative = row["traj_rel_dir"] + "/log/" + Path(row["img_name"]).stem + ".json"
        state_path = contained(dataset_root, state_relative)
        if state_path.is_file():
            sample["state_file"] = file_record(state_path, dataset_root)
        selected_rows.append(row)
        samples.append(sample)
        chosen_files.extend({**record, "path": str(contained(dataset_root, record["path"]))} for record in sample["images"].values())
        if sample["state_file"]:
            chosen_files.append({**sample["state_file"], "path": str(state_path)})
    for original in list(inputs.values()) + code + chosen_files:
        if file_record(original["path"]) != original:
            raise ValueError("Input bytes changed during published-reference preparation")
    details = {"inputs": inputs, "upstream": {"root": str(upstream), "revision": UPSTREAM_REVISION, "files": code},
        "publisher": dict(PUBLISHED),
        "publisher_source_url": f"https://huggingface.co/{PUBLISHED['repository']}/resolve/{PUBLISHED['revision']}/{PUBLISHED['filename']}",
        "official_training_source": dict(OFFICIAL_TRAIN), "split_id": frozen["split_id"],
        "split_frozen_at_utc": frozen["frozen_at_utc"], "map_name": map_name, "sample_count": COUNT, "samples": samples,
        "selection": {"rule_id": RULE, "count": COUNT, "separate_episodes": True,
            "method": "Rank eligible official train episodes by SHA256(rule + newline + 'episode' + newline + episode), select first five; per episode choose minimum analogous 'image' rank of episode + newline + img_name. Lexicographic ties, then source row index.",
            "eligible_training_episodes": len(eligible), "eligible_training_rows": sum(len(value) for value in eligible.values()),
            "rejected_training_rows": len(rejected), "training_rows_inspected": len(inspected),
            "rejection_reason_counts": dict(collections.Counter(reason for item in rejected for reason in item["reasons"])),
            "uses_model_outputs_or_evaluation_outcomes": False, "pixel_content_used_for_selection": False},
        "label_policy": dict(POLICY), "approval": {"status": "not_asserted"}, "p09_expert_correction_complete": False,
        "reader_semantics": {"source_verified": True, "executed_here": False, "bins": 99,
            "quantization": "Unchanged reader: clip to ACTION_STATS, normalize and int(norm * 98); preparation rejects outside bounds before reader use",
            "image_layout": "Original reader converts RGB, resizes each view to 224x224 bicubic, puts front above down in a 224x448 mosaic",
            "text": "Original instruction.strip(), newline, 'Action: ', quantized fwd/down/yaw; LAND on either terminal flag; tokenizer EOS",
            "tokenization_and_image_decode_checks": "Deferred to the real unchanged reader/collator during P10"},
        "validation_scope": "Unchanged publisher targets and file identities; physical correctness, horizon, expert quality and recovery relevance are not established"}
    return selected_rows, details, rejected


def prepare(source, official_train_json, frozen_split, audit_report, dataset_root, upstream, output_dir, opt_in=False):
    if not opt_in:
        raise ValueError("Explicit opt-in to published-reference preparation is required")
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        raise FileExistsError("Use a new immutable published-reference directory")
    rows, details, rejected = collect(source, official_train_json, frozen_split, audit_report, dataset_root, upstream)
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json(output_dir / "published_rows.json", rows)
    write_json(output_dir / "rejected_rows.json", rejected)
    (output_dir / "splits.json").write_bytes(Path(frozen_split).read_bytes())
    manifest = {"schema_version": SCHEMA, "status": STATUS, "created_at_utc": now(), "explicit_preparation_opt_in": True,
        **details, "data_json": file_record(output_dir / "published_rows.json", output_dir),
        "split_manifest": file_record(output_dir / "splits.json", output_dir),
        "rejections": file_record(output_dir / "rejected_rows.json", output_dir), "preparer_code": file_record(__file__)}
    write_json(output_dir / "reference_manifest.json", manifest)
    write_json(output_dir / "checksums.json", {path.name: digest(path) for path in sorted(output_dir.iterdir()) if path.is_file()})
    return manifest


def validate_for_mechanics(data_json, dataset_root, manifest_path):
    """Recompute pinned provenance/selection. No source/expert approval is inferred."""
    manifest_path, data_json = Path(manifest_path).resolve(), Path(data_json).resolve()
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA or manifest.get("status") != STATUS:
        raise ValueError("Expected the strict published-reference preparation schema")
    if manifest.get("explicit_preparation_opt_in") is not True or manifest.get("p09_expert_correction_complete") is not False or manifest.get("approval") != {"status": "not_asserted"}:
        raise ValueError("Published reference preparation cannot assert expert approval or P09 completion")
    if manifest.get("label_policy") != POLICY:
        raise ValueError("Published reference label/horizon scope has been changed")
    inputs = manifest.get("inputs", {})
    try:
        rows, expected, rejected = collect(*(inputs[name]["path"] for name in
            ("published_manifest", "official_train_manifest", "frozen_split", "published_audit")), dataset_root, manifest["upstream"]["root"])
    except (KeyError, TypeError) as exc:
        raise ValueError("Reference source/provenance paths are incomplete") from exc
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"Reference manifest differs from recomputed pinned evidence: {key}")
    for key in ("data_json", "split_manifest", "rejections"):
        record = manifest.get(key, {})
        path = contained(manifest_path.parent, record.get("path"))
        if file_record(path, manifest_path.parent) != record:
            raise ValueError("Prepared reference file hash/size differs")
        if key == "data_json" and (path != data_json or read_json(path) != rows):
            raise ValueError("Prepared rows differ from the five unchanged deterministically selected publisher rows")
        if key == "split_manifest" and digest(path) != expected["inputs"]["frozen_split"]["sha256"]:
            raise ValueError("Frozen split snapshot differs")
        if key == "rejections" and read_json(path) != rejected:
            raise ValueError("Prepared rejection accounting differs")
    return {"status": "passed", "supervision_mode": "published-reference-mechanics", "allowed_phase": "P10",
        "sample_count": COUNT, "sample_ids": [sample["sample_id"] for sample in expected["samples"]],
        "episode_ids": sorted(sample["episode_id"] for sample in expected["samples"]), "data_json": file_record(data_json),
        "dataset_manifest": file_record(manifest_path), "split_manifest": file_record(contained(manifest_path.parent, manifest["split_manifest"]["path"])),
        "publisher": expected["publisher"], "approval": expected["approval"], "label_policy": expected["label_policy"],
        "p09_expert_correction_complete": False, "provenance_inputs": expected["inputs"],
        "limitation": "P10 mechanics on unchanged publisher targets only; no expert-correction, physical-horizon, recovery or learning-improvement claim"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("source", "official-train-json", "frozen-split", "audit-report", "dataset-root", "upstream", "output-dir"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--opt-in-published-reference-preparation", action="store_true")
    options = parser.parse_args()
    if not options.opt_in_published_reference_preparation:
        parser.error("Use the explicit preparation opt-in; this does not approve expert labels")
    result = prepare(options.source, options.official_train_json, options.frozen_split, options.audit_report,
        options.dataset_root, options.upstream, options.output_dir, opt_in=True)
    print(json.dumps({"status": result["status"], "sample_count": result["sample_count"], "output_dir": str(options.output_dir.resolve()),
                      "p09_expert_correction_complete": False, "training_executed": False}))


if __name__ == "__main__":
    main()
