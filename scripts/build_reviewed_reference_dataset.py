#!/usr/bin/env python3
"""Package unchanged source demonstrations accepted by existing named reviews.

This validates and copies evidence; it cannot create semantic approval. No model,
simulator, GPU, training, remote transfer or publication is performed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil

import audit_reference_alignment as alignment
import prepare_published_reference as source
import train_adapter_mvp as trainer

PART_SCHEMA = "vla.reviewed-reference-part.v1"
REVIEW_SCHEMA = "vla.reference-expert-review.v1"
REQUIRED_FILES = ("data_json", "reference_manifest", "alignment_report", "independent_review")
LABEL_POLICY = {
    "source_kind": "audited_reference_expert",
    "source_description": "Unchanged pinned publisher reference demonstrations accepted by the existing named independent reviews copied into this release. Package assembly derives approval from those reviews; it does not perform semantic approval.",
    "action_units": {"fwd": "m", "down": "m", "yaw": "rad"},
    "action_frame": "Projected source body-frame displacement: R(q_i).inv().apply(p_(i+5)-p_i) x and z; relative quaternion (R(q_i).inv()*R(q_(i+5))).as_euler('zyx')[0] yaw. Body y and relative pitch/roll are omitted and reported in the audit.",
    "action_horizon": "Five consecutive numeric raw record/frame increments i through i+5. Physical elapsed seconds are unknown; this is not a fixed-duration upstream executor macro.",
    "stop_semantics": "Original publisher is_last_step and is_penultimate are both false for every packaged row; no LAND target. This corpus supplies no positive stop examples and no physical-touchdown certification.",
    "temporal_alignment": "Original front/down images use current frame i's filename and exact hashed raw state; all six raw records i..i+5 and endpoint images are retained. Labels agree numerically with the stated pose projection within 1e-9. Sensor/image acquisition simultaneity and physical duration are not established.",
    "physical_horizon_seconds": None,
    "label_changes": "None; no dropped/replaced/recomputed targets",
    "qualification": "Ordinary source demonstrations, not newly collected model-failure corrections. Omitted body y/tilt and rotate-before-translate/large-yaw/quantization controller differences remain explicit. Review does not establish collision-free execution, optimal navigation, human certification, or policy improvement.",
}


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Timestamp is naive")
        return parsed.astimezone(timezone.utc)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("Expected actual timezone-aware ISO timestamp") from exc


def text_required(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Missing explicit " + name)


def resolve_record(base, record):
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise ValueError("Part requires actual file records")
    requested = Path(record["path"])
    path = requested.resolve() if requested.is_absolute() else source.contained(base, record["path"])
    alignment.match_record(path, record)
    return path


def bound_to(path, record):
    return alignment.match_record(path, record)


def validate_split(path, started):
    split = source.read_json(path)
    if split.get("schema_version") != "vla.splits.v1" or split.get("upstream_code_revision") != source.UPSTREAM_REVISION:
        raise ValueError("Expected actual frozen split for pinned upstream")
    if timestamp(split.get("frozen_at_utc")) > started:
        raise ValueError("Split freeze is after package assembly")
    groups = split.get("groups", {})
    if not {"train", "development", "holdout", "demo"}.issubset(groups):
        raise ValueError("Train/development/holdout/demo separation is required")
    seen = set()
    for group, entries in groups.items():
        if not isinstance(entries, list) or len(entries) != len(set(entries)) or seen.intersection(entries):
            raise ValueError("Split groups overlap or contain duplicates")
        for entry in entries:
            source.episode_path(entry, split["map_id"])
        seen.update(entries)
    return split


def validate_part(path, dataset_root, split_path, split, started):
    part_record = source.file_record(path)
    part = source.read_json(path)
    if part.get("schema_version") != PART_SCHEMA:
        raise ValueError("Expected explicit reviewed-reference part manifest")
    paths = {key: resolve_record(path.parent, part[key]) for key in REQUIRED_FILES}
    values = {key: source.read_json(value) for key, value in paths.items()}
    rows, prepared, audit, review = (values[key] for key in REQUIRED_FILES)
    expected = alignment.ALLOWED_SCHEMAS.get(prepared.get("schema_version"))
    if expected not in (5, 20) or prepared.get("sample_count") != expected or len(rows) != expected or len(prepared.get("samples", [])) != expected:
        raise ValueError("Only complete original-five or extension-twenty parts are accepted")
    if prepared.get("publisher") != source.PUBLISHED or prepared.get("official_training_source") != source.OFFICIAL_TRAIN or prepared.get("upstream", {}).get("revision") != source.UPSTREAM_REVISION:
        raise ValueError("Prepared source pins differ")
    if prepared.get("approval") != {"status": "not_asserted"}:
        raise ValueError("Preparation receipt must remain its original unapproved artifact")
    bound_to(paths["data_json"], prepared["data_json"])
    bound_to(split_path, prepared["split_manifest"])
    if audit.get("schema_version") != alignment.SCHEMA or audit.get("status") != "alignment_audited_not_approved" or audit.get("alignment_gate_passed") is not True or audit.get("approval") != "not_asserted":
        raise ValueError("Require a completed passing alignment audit, distinct from approval")
    if audit.get("record_offset") != 5 or audit.get("tolerance_absolute") != 1e-9 or audit.get("expected_count") != expected or len(audit.get("samples", [])) != expected:
        raise ValueError("Alignment offset/tolerance/complete sample count differs")
    bound_to(paths["data_json"], audit["provenance"]["data_json"])
    bound_to(paths["reference_manifest"], audit["provenance"]["manifest"])
    bound_to(split_path, audit["provenance"]["inputs"]["frozen_split"])
    if audit["provenance"]["inputs"]["published_manifest"]["sha256"] != source.PUBLISHED["sha256"] or audit["provenance"]["inputs"]["official_train_manifest"]["sha256"] != source.OFFICIAL_TRAIN["sha256"]:
        raise ValueError("Alignment source pins differ from prepared publisher")
    if review.get("schema_version") != REVIEW_SCHEMA or review.get("status") != "approved" or review.get("source_kind") != "audited_reference_expert" or review.get("human_review") is not False:
        raise ValueError("Require an existing explicit qualified agent reference-expert review")
    for key in ("reviewer", "qualified_scope"):
        text_required(review.get(key), key)
    reviewed = timestamp(review.get("reviewed_at_utc"))
    if reviewed > started or reviewed < timestamp(audit.get("finished_at_utc")) or reviewed < timestamp(prepared.get("created_at_utc")):
        raise ValueError("Review must follow its actual audited/prepared inputs and precede package assembly")
    for key in ("data_json", "reference_manifest", "alignment_report"):
        bound_to(paths[key], review["inputs"][key])
    accepted = review.get("accepted_samples")
    if not isinstance(accepted, list) or len(accepted) != expected:
        raise ValueError("Named review must explicitly accept every unchanged original row")
    accepted_map = {record.get("sample_id"): record for record in accepted}
    audited_map = {record.get("sample_id"): record for record in audit["samples"]}
    if len(accepted_map) != expected or len(audited_map) != expected:
        raise ValueError("Duplicate accepted or audited sample")
    candidates = []
    for index, (row, prepared_sample) in enumerate(zip(rows, prepared["samples"])):
        row_hash = source.canonical_hash(row)
        sample_id, episode = prepared_sample["sample_id"], row["traj_rel_dir"] + "/merged_data.json"
        errors, _ = source.row_reasons(row, dataset_root)
        if errors or row["is_last_step"] is not False or row["is_penultimate"] is not False:
            raise ValueError(f"Invalid/bounds/terminal publisher row {sample_id}: {errors}")
        if prepared_sample.get("row_index") != index or prepared_sample.get("row_sha256") != row_hash or prepared_sample.get("source_row_sha256") != row_hash or prepared_sample.get("episode_id") != episode or prepared_sample.get("split") != "train" or episode not in split["groups"]["train"]:
            raise ValueError("Prepared row/source hash or train membership mismatch")
        accepted_sample, measured = accepted_map.get(sample_id, {}), audited_map.get(sample_id, {})
        for record in (accepted_sample, measured):
            if record.get("episode_id") != episode or record.get("row_sha256") != row_hash or record.get("source_row_index") != prepared_sample["source_row_index"]:
                raise ValueError("Review/audit does not identify the exact unchanged publisher row")
        if accepted_sample.get("accepted") is not True or measured.get("alignment_gate_passed") is not True or measured.get("published_label") != row["label"]:
            raise ValueError("A row was not accepted by both actual audit and named review")
        residuals = measured.get("absolute_residuals", {})
        inferred = measured.get("inferred_label", {})
        if set(residuals) != set(source.BOUNDS) or set(inferred) != set(source.BOUNDS):
            raise ValueError("Alignment must preserve all measured label components")
        for key in source.BOUNDS:
            error = residuals[key]
            if type(error) not in (int, float) or not math.isfinite(error) or not 0 <= error <= 1e-9 or abs(abs(row["label"][key] - inferred[key]) - error) > 1e-15:
                raise ValueError("Alignment residuals are missing, inconsistent or outside the fixed tolerance")
        frame = int(Path(row["img_name"]).stem)
        if measured.get("current_frame") != frame or measured.get("future_frame") != frame + 5 or measured.get("consecutive_record_increments") != 5:
            raise ValueError("Audited frame interval differs from current row")
        raw_records = measured.get("raw_log_records", [])
        if len(raw_records) != 6:
            raise ValueError("All six actual raw records must remain available")
        copy_records = []
        for offset, record in enumerate(raw_records):
            relative = f"{row['traj_rel_dir']}/log/{frame+offset:06d}.json"
            if record.get("path") != relative:
                raise ValueError("Audited raw sequence is out of order or identifies another mission")
            actual = source.contained(dataset_root, relative)
            bound_to(actual, record)
            pose = alignment.validated_pose(source.read_json(actual), frame + offset)
            if offset in (0, 5):
                measured_pose = measured["current_state" if offset == 0 else "future_state"]
                if any(pose[key] != measured_pose[key] for key in ("position", "orientation")):
                    raise ValueError("Raw endpoint pose differs from actual audited state")
            copy_records.append(record)
        bound_to(source.contained(dataset_root, raw_records[0]["path"]), prepared_sample["state_file"])
        images = measured.get("endpoint_images", {})
        for stage, image_frame in (("current", frame), ("future", frame + 5)):
            for camera, folder in (("front", "frontcamera"), ("down", "downcamera")):
                record = images[stage][camera]
                relative = f"{row['traj_rel_dir']}/{folder}/{image_frame:06d}.png"
                if record.get("path") != relative:
                    raise ValueError("Actual paired image identity differs from audited record")
                actual = source.contained(dataset_root, relative)
                bound_to(actual, record)
                if stage == "current":
                    if prepared_sample["images"][camera].get("path") != relative:
                        raise ValueError("Prepared observation pair path mismatch")
                    bound_to(actual, prepared_sample["images"][camera])
                copy_records.append(record)
        candidates.append({"row": row, "prepared": prepared_sample, "audit": measured, "accepted": accepted_sample, "copy_records": copy_records})
    if {c["prepared"]["sample_id"] for c in candidates} != set(accepted_map) or len({c["prepared"]["episode_id"] for c in candidates}) != expected:
        raise ValueError("Part contains dropped/replaced or repeated mission samples")
    extras = [resolve_record(path.parent, r) for r in part.get("review_evidence", [])]
    available = {(record["sha256"], record["bytes"]) for record in
                 [source.file_record(p) for p in list(paths.values()) + extras] +
                 [r for candidate in candidates for r in candidate["copy_records"]]}
    supporting = review.get("evidence")
    if not isinstance(supporting, list) or not supporting:
        raise ValueError("Named review must identify its supporting evidence")
    for record in supporting:
        if not isinstance(record, dict) or (record.get("sha256"), record.get("bytes")) not in available:
            raise ValueError("Part omits supporting review evidence; supply explicit current review_evidence path mapping")
    return {"part_path": path, "part_record": part_record, "part": part, "paths": paths, "values": values, "count": expected,
            "candidates": candidates, "review_evidence": extras}


def phase_parts(parts, phase):
    counts = [part["count"] for part in parts]
    if counts != ([5] if phase == "P09" else [5, 20]):
        raise ValueError("P09 requires original five; P11 requires original five followed by twenty new rows")
    episodes = [c["prepared"]["episode_id"] for part in parts for c in part["candidates"]]
    sample_ids = [c["prepared"]["sample_id"] for part in parts for c in part["candidates"]]
    if len(episodes) != len(set(episodes)) or len(sample_ids) != len(set(sample_ids)):
        raise ValueError("Parts overlap; cannot drop/rewrite duplicate samples")
    if phase == "P11":
        original, extension = parts
        receipt = extension["values"]["reference_manifest"]
        bound_to(original["paths"]["reference_manifest"], receipt["excluded_prior_manifest"])
        if set(receipt["excluded_episode_ids"]) != {c["prepared"]["episode_id"] for c in original["candidates"]}:
            raise ValueError("Extension does not exclude these exact original five missions")


def copy_exact(path, target, record=None):
    receipt = source.file_record(path)
    if record is not None:
        bound_to(path, record)
    target.parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("rb") as src, target.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    bound_to(target, receipt)
    return receipt


def build(part_paths, dataset_root, frozen_split, phase, output):
    started = datetime.now(timezone.utc)
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": "vla.reviewed-reference-package.v1", "phase": phase,
              "started_at_utc": started.isoformat(), "status": "started", "semantic_approval_performed_here": False,
              "model_loaded": False, "training_executed": False, "simulator_started": False,
              "implementation": [source.file_record(p) for p in (__file__, source.__file__, alignment.__file__, trainer.__file__)]}
    tracked = []
    try:
        frozen_record = source.file_record(frozen_split)
        split = validate_split(frozen_split, started)
        parts = [validate_part(path, dataset_root, frozen_split, split, started) for path in part_paths]
        phase_parts(parts, phase)
        tracked.append(copy_exact(frozen_split, output / "splits.json", frozen_record))
        for implementation in report["implementation"]:
            tracked.append(copy_exact(implementation["path"], output / "implementation" / Path(implementation["path"]).name, implementation))
        rows, samples, approval_parts = [], [], []
        for part_index, part in enumerate(parts):
            folder = output / "evidence" / f"part-{part_index:02d}"
            bundle_refs = {}
            tracked.append(copy_exact(part["part_path"], folder / "part.json", part["part_record"]))
            for key, path in part["paths"].items():
                target = folder / (key + ".json")
                tracked.append(copy_exact(path, target, part["part"][key]))
                bundle_refs[key] = source.file_record(target, output)
            copied_review_evidence = []
            for index, path in enumerate(part["review_evidence"]):
                target = folder / "review-evidence" / f"{index:03d}-{path.name}"
                tracked.append(copy_exact(path, target, part["part"]["review_evidence"][index]))
                copied_review_evidence.append({"original": source.file_record(path), "copied": source.file_record(target, output)})
            bundle_refs["supporting_review_evidence"] = copied_review_evidence
            review = part["values"]["independent_review"]
            approval_parts.append({"part_index": part_index, "reviewer": review["reviewer"], "reviewed_at_utc": review["reviewed_at_utc"],
                                   "human_review": False, "qualified_scope": review["qualified_scope"], "review": bundle_refs["independent_review"],
                                   "alignment": bundle_refs["alignment_report"], "supporting_evidence": copied_review_evidence,
                                   "accepted_sample_ids": [c["prepared"]["sample_id"] for c in part["candidates"]]})
            for candidate in part["candidates"]:
                row, prepared, measured = candidate["row"], candidate["prepared"], candidate["audit"]
                for record in candidate["copy_records"]:
                    source_path = source.contained(dataset_root, record["path"])
                    tracked.append(copy_exact(source_path, output / "assets" / record["path"], record))
                provenance_path = output / "assets" / row["traj_rel_dir"] / "source-provenance.json"
                source.write_json(provenance_path, {"schema_version": "vla.reviewed-reference-sample.v1", "original_row": row,
                    "original_prepared_sample": prepared, "alignment_measurement": measured, "accepted_review_sample": candidate["accepted"],
                    "bundle_evidence_root": "Dataset release root (parent of assets)", "bundle_evidence": bundle_refs,
                    "qualification": LABEL_POLICY["qualification"], "label_changes": "None"})
                rows.append(row)
                sources = measured["raw_log_records"] + list(measured["endpoint_images"]["future"].values()) + [source.file_record(provenance_path, output / "assets")]
                samples.append({"row_index": len(rows)-1, "row_sha256": source.canonical_hash(row), "sample_id": prepared["sample_id"],
                                "episode_id": prepared["episode_id"], "split": "train", "images": measured["endpoint_images"]["current"],
                                "source_evidence": sources, "source_row_index": prepared["source_row_index"], "source_row_sha256": prepared["source_row_sha256"]})
        source.write_json(output / "train.json", rows)
        approval = {"schema_version": "vla.derived-reference-review-receipt.v1", "status": "approved", "source_kind": "audited_reference_expert",
                    "semantic_approval_performed_here": False, "human_review": False, "parts": approval_parts,
                    "scope": "Exact union of existing named qualified approvals; package construction adds no semantic endorsement",
                    "sample_ids": [s["sample_id"] for s in samples]}
        source.write_json(output / "approval_receipt.json", approval)
        manifest = {"schema_version": "vla.training-dataset.v1", "status": "validated", "phase": phase,
                    "created_at_utc": datetime.now(timezone.utc).isoformat(), "sample_count": len(rows),
                    "data_json": source.file_record(output / "train.json", output), "split_manifest": source.file_record(output / "splits.json", output),
                    "label_policy": LABEL_POLICY, "samples": samples,
                    "approval": {"status": "approved", "reviewer": "; ".join(dict.fromkeys(r["reviewer"] for r in approval_parts)),
                                 "reviewed_at_utc": max(timestamp(r["reviewed_at_utc"]) for r in approval_parts).isoformat(),
                                 "evidence": source.file_record(output / "approval_receipt.json", output), "human_review": False,
                                 "derived_from_existing_reviews": True}}
        source.write_json(output / "dataset_manifest.json", manifest)
        validation = trainer.validate_dataset(output / "train.json", output / "assets", output / "dataset_manifest.json")
        source.write_json(output / "training_contract_validation.json", validation)
        for record in tracked:
            bound_to(record["path"], record)
        report.update(status="packaged_and_contract_validated", sample_count=len(rows), label_changes=False, source_inputs=tracked,
                      train_json=source.file_record(output / "train.json"), dataset_manifest=source.file_record(output / "dataset_manifest.json"),
                      training_contract_validation=validation)
    except Exception as exc:
        report.update(status="packaging_failed", error_type=type(exc).__name__, error=str(exc))
        if (output / "dataset_manifest.json").exists():
            invalid = source.read_json(output / "dataset_manifest.json")
            invalid["status"] = "invalid_packaging_failed"
            source.write_json(output / "dataset_manifest.json", invalid)
        raise
    finally:
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        source.write_json(output / "packaging_report.json", report)
        source.write_json(output / "checksums.json", {str(path.relative_to(output)): source.digest(path) for path in sorted(output.rglob("*")) if path.is_file() and path.name != "checksums.json"})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", type=Path, action="append", required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--frozen-split", type=Path, required=True)
    parser.add_argument("--phase", choices=("P09", "P11"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    result = build([p.resolve() for p in options.part], options.dataset_root.resolve(), options.frozen_split.resolve(), options.phase, options.output.resolve())
    print(json.dumps({"status": result["status"], "sample_count": result["sample_count"], "output": str(options.output.resolve()),
                      "semantic_approval_performed_here": False, "training_executed": False}))


if __name__ == "__main__":
    main()
