#!/usr/bin/env python3
"""Prepare twenty unchanged publisher references, excluding the original five.

Selection uses declared metadata and file existence only, never alignment results,
model predictions or evaluation outcomes. No images are decoded or labels changed.
"""
import argparse
import collections
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import re

import prepare_published_reference as reference

SCHEMA = "vla.published-reference-extension.v1"
STATUS = "prepared_published_reference_extension_not_expert_approved"
COUNT = 20
RULE = "aerovla-reference-extension-twenty-v1"
OFFSET = 5
POLICY = {**reference.POLICY, "purpose": "P11_unchanged_published_reference_extension",
          "physical_label_generation_and_alignment": "Deferred to a separate independent audit; no alignment result is used for selection"}


def rank(kind, value):
    return hashlib.sha256((RULE + "\n" + kind + "\n" + value).encode("utf-8")).hexdigest()


def identity_equal(first, second):
    return all(first.get(k) == second.get(k) for k in ("sha256", "bytes"))


def prior_five(prior_manifest, prior_data_json, rows, inputs, groups, dataset_root):
    """Authenticate the immutable prior examples; do not infer their label quality."""
    prior_manifest, prior_data_json = Path(prior_manifest).resolve(), Path(prior_data_json).resolve()
    manifest = reference.read_json(prior_manifest)
    if (manifest.get("schema_version") != reference.SCHEMA or manifest.get("status") != reference.STATUS
            or manifest.get("sample_count") != 5 or manifest.get("approval") != {"status": "not_asserted"}
            or manifest.get("p09_expert_correction_complete") is not False or manifest.get("explicit_preparation_opt_in") is not True
            or manifest.get("label_policy") != reference.POLICY):
        raise ValueError("Require the original five-reference schema without invented approval or horizon")
    try:
        created = dt.datetime.fromisoformat(manifest["created_at_utc"].replace("Z", "+00:00"))
        if created.tzinfo is None or created > dt.datetime.now(dt.timezone.utc):
            raise ValueError("Naive or future prior timestamp")
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError("Actual prior-five creation time is required") from exc
    if manifest.get("selection", {}).get("rule_id") != reference.RULE:
        raise ValueError("Prior-five selection rule identity differs")
    if manifest.get("publisher") != reference.PUBLISHED or manifest.get("official_training_source") != reference.OFFICIAL_TRAIN:
        raise ValueError("Prior-five publisher/official provenance differs")
    if manifest.get("upstream", {}).get("revision") != reference.UPSTREAM_REVISION:
        raise ValueError("Prior-five upstream revision differs")
    if not identity_equal(manifest.get("preparer_code", {}), reference.file_record(reference.__file__)):
        raise ValueError("Prior-five preparer bytes differ from the unchanged reader of that schema")
    for key, expected in inputs.items():
        if not identity_equal(manifest.get("inputs", {}).get(key, {}), expected):
            raise ValueError("Prior-five input bytes differ: " + key)
    expected_data = manifest.get("data_json", {})
    source_path = reference.contained(prior_manifest.parent, expected_data.get("path"))
    if source_path != prior_data_json or reference.file_record(source_path, prior_manifest.parent) != expected_data:
        raise ValueError("Prior-five data path/hash/size differs")
    split_record = manifest.get("split_manifest", {})
    split_path = reference.contained(prior_manifest.parent, split_record.get("path"))
    if (reference.file_record(split_path, prior_manifest.parent) != split_record
            or not identity_equal(split_record, inputs["frozen_split"])):
        raise ValueError("Prior-five frozen split differs")
    prior_rows, samples = reference.read_json(source_path), manifest.get("samples")
    if not isinstance(prior_rows, list) or not isinstance(samples, list) or len(prior_rows) != 5 or len(samples) != 5:
        raise ValueError("Exactly five prior rows and sample records required")
    episodes, records = [], [reference.file_record(prior_manifest), reference.file_record(prior_data_json), reference.file_record(split_path)]
    for row_index, (row, sample) in enumerate(zip(prior_rows, samples)):
        source_index = sample.get("source_row_index")
        if type(source_index) is not int or not 0 <= source_index < len(rows) or row != rows[source_index]:
            raise ValueError("Prior-five row is not its exact publisher source row")
        row_hash = reference.canonical_hash(row)
        episode = row["traj_rel_dir"] + "/merged_data.json"
        if (type(sample.get("row_index")) is not int or sample.get("row_index") != row_index or sample.get("source_row_sha256") != row_hash
                or sample.get("row_sha256") != row_hash or sample.get("sample_id") != "published-" + row_hash[:20]
                or sample.get("episode_id") != episode or episode not in groups["train"] or sample.get("split") != "train"):
            raise ValueError("Prior-five row/hash/membership identity differs")
        errors, images = reference.row_reasons(row, dataset_root)
        if errors:
            raise ValueError("Prior-five row no longer meets its original reader/file contract")
        expected_images = {camera: reference.file_record(reference.contained(dataset_root, path), dataset_root)
                           for camera, path in images.items()}
        if sample.get("images") != expected_images:
            raise ValueError("Prior-five image bytes differ")
        records.extend(reference.file_record(reference.contained(dataset_root, r["path"])) for r in expected_images.values())
        if sample.get("state_file") is not None:
            state_path = reference.contained(dataset_root, row["traj_rel_dir"] + "/log/" + Path(row["img_name"]).stem + ".json")
            if reference.file_record(state_path, dataset_root) != sample["state_file"]:
                raise ValueError("Prior-five state bytes differ")
            records.append(reference.file_record(state_path))
        episodes.append(episode)
    if len(set(episodes)) != 5:
        raise ValueError("Prior-five episodes are not distinct")
    return set(episodes), records


def extension_reasons(row, dataset_root):
    errors, images = reference.row_reasons(row, dataset_root)
    sequence, future_images = [], {}
    if not isinstance(row, dict):
        return errors, images, sequence, future_images
    for name in ("is_last_step", "is_penultimate"):
        if row.get(name) is True:
            errors.append("excluded_true_" + name)
    name = row.get("img_name")
    stem = Path(name).stem if isinstance(name, str) else ""
    if not isinstance(name, str) or not re.fullmatch(r"[0-9]{6}\.png", name):
        errors.append("unsupported_frame_filename_requires_six_digit_png")
        return errors, images, sequence, future_images
    start = int(stem)
    trajectory = row.get("traj_rel_dir")
    try:
        # Existence, not state content/alignment, is the eligibility gate.
        for offset in range(OFFSET + 1):
            index = start + offset
            filename = f"{index:0{len(stem)}d}"
            relative = f"{trajectory}/log/{filename}.json"
            path = reference.contained(dataset_root, relative)
            if not path.is_file():
                errors.append("missing_log_offset_" + str(offset))
            sequence.append({"offset": offset, "frame_index": index, "path": relative})
        future_name = f"{start + OFFSET:0{len(stem)}d}" + Path(name).suffix
        for camera, folder in (("front", "frontcamera"), ("down", "downcamera")):
            relative = f"{trajectory}/{folder}/{future_name}"
            path = reference.contained(dataset_root, relative)
            if not path.is_file():
                errors.append("missing_future_" + camera + "_image")
            future_images[camera] = relative
    except (ValueError, OSError):
        errors.append("invalid_extension_source_path")
    return errors, images, sequence, future_images


def collect(source, official_train_json, frozen_split, audit_report, dataset_root, upstream, prior_manifest, prior_data_json):
    paths = [Path(p).resolve() for p in (source, official_train_json, frozen_split, audit_report)]
    source, official_train_json, frozen_split, audit_report = paths
    dataset_root, upstream = Path(dataset_root).resolve(), Path(upstream).resolve()
    inputs = {name: reference.file_record(path) for name, path in zip(
        ("published_manifest", "official_train_manifest", "frozen_split", "published_audit"), paths)}
    if inputs["published_manifest"]["sha256"] != reference.PUBLISHED["sha256"] or inputs["published_manifest"]["bytes"] != reference.PUBLISHED["bytes"]:
        raise ValueError("Published manifest differs from the authoritative pinned bytes")
    if inputs["official_train_manifest"]["sha256"] != reference.OFFICIAL_TRAIN["sha256"]:
        raise ValueError("Official training split differs from pinned bytes")
    code = []
    for relative, expected in reference.UPSTREAM_FILES.items():
        record = reference.file_record(upstream / relative)
        if record["sha256"] != expected:
            raise ValueError("Original reader/trainer source differs from pinned hash")
        code.append(record)
    frozen, audit = reference.read_json(frozen_split), reference.read_json(audit_report)
    map_name, groups = reference.validate_split(frozen, reference.read_json(official_train_json))
    if (audit.get("schema_version") != "vla.published-training-audit.v1" or audit.get("status") != "audit_completed_not_label_approval"
            or audit.get("source") != reference.PUBLISHED or audit.get("split_sha256") != inputs["frozen_split"]["sha256"]):
        raise ValueError("Published source audit is missing or does not bind these exact source/split bytes")
    rows = reference.read_json(source)
    if not isinstance(rows, list) or len(rows) != audit.get("rows"):
        raise ValueError("Publisher row count differs from audited count")
    excluded, prior_records = prior_five(prior_manifest, prior_data_json, rows, inputs, groups, dataset_root)
    overlaps = {group: {"published_rows": 0, "episodes": set()} for group in groups}
    inspected, rejected = [], []
    duplicates = collections.Counter()
    selected_map_rows = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("traj_rel_dir"), str):
            raise ValueError("Pinned publisher has an unidentifiable trajectory row")
        episode = row["traj_rel_dir"] + "/merged_data.json"
        selected_map_rows += row["traj_rel_dir"].split("/", 1)[0] == map_name
        for group, members in groups.items():
            if episode in members:
                overlaps[group]["published_rows"] += 1
                overlaps[group]["episodes"].add(episode)
        if episode not in groups["train"]:
            continue  # Do not inspect/hash any evaluation or holdout files.
        if isinstance(row.get("img_name"), str):
            duplicates[(episode, row["img_name"])] += 1
        if episode in excluded:
            inspected.append((index, row, episode, ["excluded_prior_episode"], {}, [], {}))
        else:
            inspected.append((index, row, episode, *extension_reasons(row, dataset_root)))
    for group, values in overlaps.items():
        expected = dict(published_rows=values["published_rows"], represented_episodes=len(values["episodes"]), declared_episodes=len(groups[group]))
        if audit.get("project_overlap", {}).get(group) != expected:
            raise ValueError("Published overlap ledger differs from independent source audit")
        if group != "train" and values["published_rows"]:
            raise ValueError("Publisher overlaps project evaluation membership")
    if selected_map_rows != audit.get("selected_map_file_and_schema_audit", {}).get("rows"):
        raise ValueError("Selected-map publisher row count differs from audit")
    eligible = collections.defaultdict(list)
    for index, row, episode, errors, images, sequence, future_images in inspected:
        if isinstance(row.get("img_name"), str) and duplicates[(episode, row["img_name"])] > 1:
            errors.append("duplicate_published_image_pair")
        if errors:
            rejected.append({"source_row_index": index, "episode_id": episode,
                             "img_name": row.get("img_name") if isinstance(row.get("img_name"), str) else None,
                             "reasons": errors})
        else:
            eligible[episode].append((index, row, images, sequence, future_images))
    if len(eligible) < COUNT:
        raise ValueError(f"Need twenty new distinct eligible training episodes; found {len(eligible)}")
    exported, samples, selected_records = [], [], []
    for episode in sorted(eligible, key=lambda e: (rank("episode", e), e))[:COUNT]:
        index, row, image_paths, sequence, future_paths = min(eligible[episode], key=lambda x: (rank("image", episode + "\n" + x[1]["img_name"]), x[1]["img_name"], x[0]))
        row_hash = reference.canonical_hash(row)
        images = {camera: reference.file_record(reference.contained(dataset_root, path), dataset_root) for camera, path in image_paths.items()}
        future_images = {camera: reference.file_record(reference.contained(dataset_root, path), dataset_root) for camera, path in future_paths.items()}
        logs = [{**reference.file_record(reference.contained(dataset_root, item["path"]), dataset_root), "offset": item["offset"], "frame_index": item["frame_index"]} for item in sequence]
        sample = dict(row_index=len(samples), source_row_index=index, source_row_sha256=row_hash, row_sha256=row_hash,
                      sample_id="published-extension-" + row_hash[:20], episode_id=episode, split="train",
                      episode_selection_rank=rank("episode", episode), image_selection_rank=rank("image", episode + "\n" + row["img_name"]),
                      images=images, future_images=future_images, state_sequence_files=logs,
                      state_file={k: logs[0][k] for k in ("path", "sha256", "bytes")},
                      future_state_file={k: logs[-1][k] for k in ("path", "sha256", "bytes")},
                      filename_offset_for_alignment_audit=OFFSET,
                      state_alignment_claim="Six consecutive filename-linked logs and current/future image files exist; label alignment and physical horizon are not asserted here")
        samples.append(sample)
        exported.append(row)
        for record in [*images.values(), *future_images.values(), *logs]:
            selected_records.append({"path": str(reference.contained(dataset_root, record["path"])), "sha256": record["sha256"], "bytes": record["bytes"]})
    for record in [*inputs.values(), *code, *prior_records, *selected_records]:
        if reference.file_record(record["path"]) != record:
            raise ValueError("Input bytes changed during extension preparation")
    details = dict(inputs=inputs, upstream=dict(root=str(upstream), revision=reference.UPSTREAM_REVISION, files=code),
                   publisher=dict(reference.PUBLISHED), official_training_source=dict(reference.OFFICIAL_TRAIN),
                   publisher_source_url=f"https://huggingface.co/{reference.PUBLISHED['repository']}/resolve/{reference.PUBLISHED['revision']}/{reference.PUBLISHED['filename']}",
                   split_id=frozen["split_id"], split_frozen_at_utc=frozen["frozen_at_utc"], map_name=map_name,
                   sample_count=COUNT, samples=samples, excluded_prior_manifest=reference.file_record(prior_manifest),
                   excluded_prior_data_json=reference.file_record(prior_data_json), excluded_episode_ids=sorted(excluded),
                   selection=dict(rule_id=RULE, count=COUNT, separate_episodes=True,
                                  method="Rank eligible non-prior training episodes by SHA256(rule + newline + 'episode' + newline + episode); first twenty. Within each choose minimum SHA256(rule + newline + 'image' + newline + episode + newline + img_name), then filename/source-index ties.",
                                  eligibility="Original exact schema/bounds; both terminal flags false; exact six-ASCII-digit .png filename; current/future front/down images and every log i..i+5 exist. No numeric state/alignment or pixel-content filter.",
                                  eligible_training_episodes=len(eligible), eligible_training_rows=sum(len(v) for v in eligible.values()),
                                  training_rows_inspected=len(inspected), rejected_training_rows=len(rejected),
                                  prior_episode_rows_excluded=sum("excluded_prior_episode" in r["reasons"] for r in rejected),
                                  rejection_reason_counts=dict(collections.Counter(reason for r in rejected for reason in r["reasons"])),
                                  uses_model_outputs_or_evaluation_outcomes=False, uses_alignment_results=False, pixel_content_used_for_selection=False),
                   label_policy=copy.deepcopy(POLICY), approval=dict(status="not_asserted"), p09_expert_correction_complete=False,
                   reader_semantics=dict(source_verified=True, executed_here=False, labels="Every exported row has identical parsed JSON values to its authenticated publisher row; original reader quantization and image handling are unchanged",
                                         tokenization_and_image_decode_checks="Deferred to the unchanged reader/collator; file presence/hash does not prove decodability"),
                   validation_scope="Publisher membership, unchanged targets, frozen training isolation and file identities only; independent alignment audit is separate; no expert/recovery approval or training execution")
    return exported, details, rejected


def prepare(source, official_train_json, frozen_split, audit_report, dataset_root, upstream, prior_manifest, prior_data_json, output_dir, opt_in=False):
    if not opt_in:
        raise ValueError("Explicit opt-in to published-reference extension preparation is required")
    output = Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError("Use a fresh immutable extension directory")
    rows, details, rejected = collect(source, official_train_json, frozen_split, audit_report, dataset_root, upstream, prior_manifest, prior_data_json)
    output.mkdir(parents=True, exist_ok=False)
    reference.write_json(output / "published_rows.json", rows)
    reference.write_json(output / "rejected_rows.json", rejected)
    (output / "splits.json").write_bytes(Path(frozen_split).read_bytes())
    manifest = dict(schema_version=SCHEMA, status=STATUS, created_at_utc=reference.now(), explicit_preparation_opt_in=True,
                    **details, data_json=reference.file_record(output / "published_rows.json", output),
                    split_manifest=reference.file_record(output / "splits.json", output),
                    rejections=reference.file_record(output / "rejected_rows.json", output), preparer_code=reference.file_record(__file__),
                    original_five_preparer_code=reference.file_record(reference.__file__))
    reference.write_json(output / "reference_manifest.json", manifest)
    reference.write_json(output / "checksums.json", {p.name: reference.digest(p) for p in sorted(output.iterdir()) if p.is_file()})
    return manifest


def validate_extension(data_json, dataset_root, manifest_path):
    """Recompute selection/bytes, with no implied approval or alignment assertion."""
    manifest_path, data_json = Path(manifest_path).resolve(), Path(data_json).resolve()
    manifest = reference.read_json(manifest_path)
    if (manifest.get("schema_version") != SCHEMA or manifest.get("status") != STATUS
            or manifest.get("explicit_preparation_opt_in") is not True or manifest.get("approval") != {"status": "not_asserted"}
            or manifest.get("p09_expert_correction_complete") is not False or manifest.get("label_policy") != POLICY):
        raise ValueError("Require unapproved unchanged-reference extension schema and original label limits")
    inputs = manifest["inputs"]
    rows, details, rejected = collect(*(inputs[name]["path"] for name in ("published_manifest", "official_train_manifest", "frozen_split", "published_audit")),
                                     dataset_root, manifest["upstream"]["root"], manifest["excluded_prior_manifest"]["path"], manifest["excluded_prior_data_json"]["path"])
    for key, value in details.items():
        if manifest.get(key) != value:
            raise ValueError("Extension differs from recomputed source/selection: " + key)
    for key in ("data_json", "split_manifest", "rejections"):
        record = manifest[key]
        path = reference.contained(manifest_path.parent, record["path"])
        if reference.file_record(path, manifest_path.parent) != record:
            raise ValueError("Prepared extension file hash/size differs")
        if key == "data_json" and (path != data_json or reference.read_json(path) != rows):
            raise ValueError("Exported rows differ from unchanged publisher selection")
        if key == "rejections" and reference.read_json(path) != rejected:
            raise ValueError("Rejection ledger differs")
        if key == "split_manifest" and not identity_equal(record, details["inputs"]["frozen_split"]):
            raise ValueError("Frozen split snapshot differs")
    return dict(status="passed", sample_count=COUNT, manifest=reference.file_record(manifest_path),
                sample_ids=[s["sample_id"] for s in details["samples"]], excluded_episode_ids=details["excluded_episode_ids"],
                approval=dict(status="not_asserted"), p09_expert_correction_complete=False,
                alignment_audit_executed=False, training_executed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "official-train-json", "frozen-split", "audit-report", "dataset-root", "upstream", "prior-manifest", "prior-data-json", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--opt-in-published-reference-extension", action="store_true")
    args = parser.parse_args()
    if not args.opt_in_published_reference_extension:
        parser.error("Explicit preparation opt-in is required; it does not approve labels")
    try:
        result = prepare(args.source, args.official_train_json, args.frozen_split, args.audit_report, args.dataset_root,
                         args.upstream, args.prior_manifest, args.prior_data_json, args.output_dir, opt_in=True)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, "Reference extension rejected: " + str(exc) + "\n")
    print(json.dumps({k: result[k] for k in ("schema_version", "status", "sample_count", "excluded_episode_ids", "approval", "p09_expert_correction_complete")}))


if __name__ == "__main__":
    main()
