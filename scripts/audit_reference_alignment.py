#!/usr/bin/env python3
"""Audit unchanged publisher labels against actual raw poses i -> i+5.

No simulator, policy model, training, label rewriting or expert approval. Five
numeric record increments do not establish a physical duration or executable
controller equivalence. Every mismatch remains a recorded rejection.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from types import SimpleNamespace

import prepare_published_reference as preparation

SCHEMA = "vla.reference-alignment-audit.v1"
OFFSET = 5
TOLERANCE = 1e-9
ALLOWED_SCHEMAS = {"vla.published-reference-preparation.v1": 5, "vla.published-reference-extension.v1": 20}
CONTROLLER = "airsim_plugin/AirVLNSimulatorClientTool_AeroVLA.py"
WRAPPER = "src/model_wrapper/aerovla_wrapper_ui.py"
ADDITIONAL_PINS = {CONTROLLER: "66dfb3d97ebaeacfec7e3786de52e146dd68b1277c5d6b0316252229fbf3fe9d",
                   WRAPPER: "1e18357cedf0af5b36ccf4078373417d7e2b7d084487cb2b81282db3a008f3e8"}
LIMITATIONS = [
    "Numerical agreement supports this observed pose-to-label formula for audited rows, not proof of the publisher's original generator implementation or all released rows.",
    "Horizon is five consecutive raw frame/record identifiers; physical duration and camera/state acquisition simultaneity remain unestablished without clock metadata.",
    "Source body-frame x/z and relative zyx yaw omit body y and relative pitch/roll. The upstream controller rotates before translating in world NED and has a large-yaw branch; matching source labels does not prove identical executed motion.",
    "These are ordinary published reference demonstrations, not newly collected model-failure corrections, human expert certification, or independently approved training labels.",
    "Frozen project split separation does not prove which samples trained the released checkpoint.",
]


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    temporary.replace(path)


def match_record(path, record):
    actual = preparation.file_record(path)
    if not isinstance(record, dict) or actual["sha256"] != record.get("sha256") or actual["bytes"] != record.get("bytes"):
        raise ValueError(f"Source hash/size mismatch: {path}")
    return actual


def before_start(stamp, started):
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        current = datetime.fromisoformat(started)
        if parsed.tzinfo is None or parsed.utcoffset() is None or parsed > current:
            raise ValueError("Naive/future timestamp")
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Source preparation must have a valid prior timezone-aware timestamp") from exc


def validated_pose(raw, expected_frame):
    if type(raw.get("frame")) is not int or raw["frame"] != expected_frame:
        raise ValueError("Raw log frame identity differs from numeric filename")
    state = raw["sensors"]["state"]
    result = {}
    for key, length in (("position", 3), ("orientation", 4)):
        values = state.get(key)
        if not isinstance(values, list) or len(values) != length or any(type(value) not in (float, int) or not math.isfinite(value) for value in values):
            raise ValueError("Raw pose requires finite xyz and xyzw arrays")
        result[key] = list(values)
    squared_norm = sum(value * value for value in result["orientation"])
    if not math.isfinite(squared_norm) or squared_norm <= 0:
        raise ValueError("Raw pose contains zero quaternion")
    result["quaternion_norm"] = math.sqrt(squared_norm)
    timestamps = []
    for name, envelope in (("raw", raw), ("state", state), ("imu", raw.get("sensors", {}).get("imu", {}))):
        for field in ("timestamp", "time_stamp"):
            if field in envelope:
                timestamps.append({"path": name + "." + field, "value": envelope[field]})
    result["timestamp_fields"] = timestamps
    return result


def scalar_residuals(label, body_delta, relative_zyx):
    inferred = {"fwd": float(body_delta[0]), "down": float(body_delta[2]), "yaw": float(relative_zyx[0])}
    residuals = {key: abs(float(label[key]) - value) for key, value in inferred.items()}
    return {"inferred_label": inferred, "absolute_residuals": residuals,
            "all_components_within_tolerance": all(value <= TOLERANCE for value in residuals.values()),
            "dropped_body_y_m": float(body_delta[1]), "dropped_relative_pitch_rad": float(relative_zyx[1]),
            "dropped_relative_roll_rad": float(relative_zyx[2])}


def nominal_controller(action, initial_yaw, actual_delta, actual_final_yaw):
    yaw = initial_yaw + action["yaw"]
    forward = action["fwd"] if abs(action["yaw"]) < .25 else 0.
    nominal = [forward * math.cos(yaw), forward * math.sin(yaw), action["down"]]
    residual = [float(a - b) for a, b in zip(actual_delta, nominal)]
    return {"branch": "rotate_then_translate" if abs(action["yaw"]) < .25 else "rotate_then_altitude_only",
            "nominal_world_delta_m": nominal, "reference_minus_nominal_delta_m": residual,
            "reference_minus_nominal_l2_m": math.sqrt(sum(value * value for value in residual)),
            "reference_minus_nominal_yaw_rad": math.atan2(math.sin(actual_final_yaw - yaw), math.cos(actual_final_yaw - yaw)),
            "interpretation": "Algebraic nominal command comparison only; no simulator execution or controller endpoint accuracy measurement"}


def pure_method(source, class_name, method_name, namespace):
    classes = [n for n in ast.parse(Path(source).read_text()).body if isinstance(n, ast.ClassDef) and n.name == class_name]
    methods = [n for n in classes[0].body if isinstance(n, ast.FunctionDef) and n.name == method_name] if len(classes) == 1 else []
    if len(methods) != 1:
        raise ValueError("Cannot isolate exact pinned action codec method")
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), "exec"), namespace)
    return namespace[method_name]


def codec(upstream):
    import numpy as np
    stats = {"forward": {"min": 0., "max": 5.}, "down": {"min": -5., "max": 5.}, "yaw": {"min": -1.1, "max": 1.1}}
    scope = {"np": np, "NUM_BINS": 99, "ACTION_STATS": stats, "re": re}
    quantize = pure_method(upstream / "src/aerovla_dataset.py", "AeroVLADataset", "_quantize_action", scope)
    parse = pure_method(upstream / WRAPPER, "AerialVLAWrapper", "_parse_action_from_text", scope)
    def roundtrip(label):
        bins = [quantize(None, label[key], axis) for key, axis in (("fwd", "forward"), ("down", "down"), ("yaw", "yaw"))]
        text = " ".join(f"{value:02d}" for value in bins)
        decoded = dict(zip(("fwd", "down", "yaw"), parse(SimpleNamespace(norm_stats=stats, NUM_BINS=99), "Action: " + text)))
        return {"bins": bins, "action_text": text, "decoded": decoded}
    return roundtrip


def verify_sources(options, started):
    manifest = preparation.read_json(options.reference_manifest)
    count = ALLOWED_SCHEMAS.get(manifest.get("schema_version"))
    if count is None or count != options.expected_count or manifest.get("sample_count") != count:
        raise ValueError("Use explicit original-five or extension-twenty preparation schema/count")
    if manifest.get("approval") != {"status": "not_asserted"}:
        raise ValueError("This audit requires unapproved prepared publisher rows")
    before_start(manifest.get("created_at_utc"), started)
    if manifest.get("publisher") != preparation.PUBLISHED or manifest.get("official_training_source") != preparation.OFFICIAL_TRAIN or manifest.get("upstream", {}).get("revision") != preparation.UPSTREAM_REVISION:
        raise ValueError("Preparation source pins differ from the audited official releases")
    inputs = {name: match_record(path, manifest["inputs"][name]) for name, path in
              (("published_manifest", options.published_manifest), ("official_train_manifest", options.official_train_json),
               ("frozen_split", options.frozen_split), ("published_audit", options.audit_report))}
    if inputs["published_manifest"]["sha256"] != preparation.PUBLISHED["sha256"] or inputs["published_manifest"]["bytes"] != preparation.PUBLISHED["bytes"] or inputs["official_train_manifest"]["sha256"] != preparation.OFFICIAL_TRAIN["sha256"]:
        raise ValueError("Actual publisher/official manifest bytes differ from pinned sources")
    source_files = []
    for relative, expected in {**preparation.UPSTREAM_FILES, **ADDITIONAL_PINS}.items():
        path = options.upstream / relative
        # Runtime may carry the already reviewed cancellation-only rewrite.
        source = path.read_text()
        backup = path.with_suffix(".py.vla-lab-original")
        original = backup.read_text() if backup.exists() else source
        import hashlib
        cancelled = re.sub(r"(?m)^([ \t]*)except:[ \t]*$", lambda match: match[1] + "except (KeyboardInterrupt, SystemExit):\n" + match[1] + "    raise\n" + match[1] + "except:", original)
        if hashlib.sha256(original.encode()).hexdigest() != expected or source not in (original, cancelled):
            raise ValueError(f"Unreviewed source modification: {relative}")
        source_files.append({**preparation.file_record(path), "pinned_original_sha256": expected})
    rows = preparation.read_json(options.data_json)
    match_record(options.data_json, manifest["data_json"])
    match_record(options.frozen_split, manifest["split_manifest"])
    frozen = preparation.read_json(options.frozen_split)
    before_start(frozen.get("frozen_at_utc"), started)
    _, groups = preparation.validate_split(frozen, preparation.read_json(options.official_train_json))
    audit = preparation.read_json(options.audit_report)
    if audit.get("schema_version") != "vla.published-training-audit.v1" or audit.get("status") != "audit_completed_not_label_approval" or audit.get("source") != preparation.PUBLISHED or audit.get("split_sha256") != inputs["frozen_split"]["sha256"]:
        raise ValueError("Source audit is not bound to the same publisher/split")
    published = preparation.read_json(options.published_manifest)
    if len(published) != audit.get("rows") or len(rows) != count or len(manifest["samples"]) != count:
        raise ValueError("Source or prepared row count differs from its receipt")
    episodes, sample_ids = set(), set()
    for index, (row, sample) in enumerate(zip(rows, manifest["samples"])):
        reasons, _ = preparation.row_reasons(row, options.dataset_root)
        if reasons:
            raise ValueError(f"Invalid unmodified publisher row {index}: {reasons}")
        episode = row["traj_rel_dir"] + "/merged_data.json"
        row_hash = preparation.canonical_hash(row)
        source_index = sample.get("source_row_index")
        if type(source_index) is not int or not 0 <= source_index < len(published) or published[source_index] != row:
            raise ValueError("Prepared row is not identical to its exact published source index")
        if sample.get("row_index") != index or sample.get("row_sha256") != row_hash or sample.get("source_row_sha256") != row_hash or sample.get("episode_id") != episode or sample.get("split") != "train" or episode not in groups["train"]:
            raise ValueError("Row identity/hash or train membership mismatch")
        if episode in episodes or sample.get("sample_id") in sample_ids or not isinstance(sample.get("sample_id"), str):
            raise ValueError("Duplicate mission/sample in this bounded audit")
        episodes.add(episode)
        sample_ids.add(sample["sample_id"])
    exclusion = None
    if count == 20:
        if options.excluded_prior_manifest is None:
            raise ValueError("Extension audit needs explicit --excluded-prior-manifest path mapping")
        record = match_record(options.excluded_prior_manifest, manifest["excluded_prior_manifest"])
        prior = preparation.read_json(options.excluded_prior_manifest)
        if prior.get("schema_version") != "vla.published-reference-preparation.v1" or prior.get("sample_count") != 5 or prior.get("publisher") != preparation.PUBLISHED:
            raise ValueError("Excluded prior source is not the original five-row preparation")
        excluded = {s["episode_id"] for s in prior["samples"]}
        if set(manifest["excluded_episode_ids"]) != excluded or len(excluded) != 5 or excluded.intersection(episodes):
            raise ValueError("Extension exclusion receipt or mission isolation differs")
        exclusion = {"source": record, "episode_ids": sorted(excluded)}
    return manifest, rows, {"inputs": inputs, "source_code": source_files, "excluded_prior": exclusion,
                            "manifest": preparation.file_record(options.reference_manifest),
                            "data_json": preparation.file_record(options.data_json),
                            "path_mapping": "Explicit current paths verified by bytes; historical absolute receipt paths remain unchanged"}


def audit_sample(row, sample, dataset_root, roundtrip):
    import numpy as np
    from scipy.spatial.transform import Rotation
    if row["is_last_step"] is not False or row["is_penultimate"] is not False:
        raise ValueError("Current bounded audit requires both original stop flags false")
    if not re.fullmatch(r"[0-9]{6}\.png", row["img_name"]):
        raise ValueError("Current source interval requires a six-digit PNG frame identity")
    current_id = int(Path(row["img_name"]).stem)
    future_id = current_id + OFFSET
    trajectory = row["traj_rel_dir"]
    records, states = [], []
    for frame in range(current_id, future_id + 1):
        path = preparation.contained(dataset_root, f"{trajectory}/log/{frame:06d}.json")
        raw = preparation.read_json(path)
        states.append(validated_pose(raw, frame))
        records.append(preparation.file_record(path, dataset_root))
    if sample.get("state_sequence_files") is not None:
        sequence = sample["state_sequence_files"]
        if not isinstance(sequence, list) or len(sequence) != OFFSET + 1:
            raise ValueError("Declared raw-state sequence must contain all six records")
        for offset, (declared, actual) in enumerate(zip(sequence, records)):
            if declared.get("frame_index") != current_id + offset or declared.get("offset") != offset or declared.get("path") != actual["path"]:
                raise ValueError("Declared raw-state sequence identity/order differs")
            match_record(preparation.contained(dataset_root, actual["path"]), declared)
    if sample.get("state_file") is None or sample["state_file"].get("path") != records[0]["path"]:
        raise ValueError("Preparation does not bind this exact current raw state")
    match_record(preparation.contained(dataset_root, records[0]["path"]), sample["state_file"])
    if sample.get("future_state_file") is not None:
        if sample["future_state_file"].get("path") != records[-1]["path"]:
            raise ValueError("Declared future state path differs from i+5")
        match_record(preparation.contained(dataset_root, records[-1]["path"]), sample["future_state_file"])
    images = {"current": {}, "future": {}}
    for stage, frame in (("current", current_id), ("future", future_id)):
        for camera, folder in (("front", "frontcamera"), ("down", "downcamera")):
            relative = f"{trajectory}/{folder}/{frame:06d}.png"
            path = preparation.contained(dataset_root, relative)
            record = preparation.file_record(path, dataset_root)
            declared = sample["images"][camera] if stage == "current" else sample.get("future_images", {}).get(camera)
            if declared is not None:
                if declared["path"] != relative:
                    raise ValueError("Declared paired image path differs from frame identity")
                match_record(path, declared)
            images[stage][camera] = record
    first, last = states[0], states[-1]
    q0, q1 = Rotation.from_quat(first["orientation"]), Rotation.from_quat(last["orientation"])
    delta = np.asarray(last["position"]) - np.asarray(first["position"])
    body = q0.inv().apply(delta)
    relative = (q0.inv() * q1).as_euler("zyx")
    measured = scalar_residuals(row["label"], body, relative)
    coded = roundtrip(row["label"])
    initial_yaw, final_yaw = float(q0.as_euler("zyx")[0]), float(q1.as_euler("zyx")[0])
    return {"sample_id": sample["sample_id"], "episode_id": sample["episode_id"], "source_row_index": sample["source_row_index"],
            "row_sha256": preparation.canonical_hash(row), "current_frame": current_id, "future_frame": future_id,
            "consecutive_record_increments": OFFSET, "raw_log_records": records, "endpoint_images": images,
            "current_state": first, "future_state": last, "intermediate_timestamp_fields": [state["timestamp_fields"] for state in states[1:-1]],
            "physical_horizon_seconds": None, "timestamp_interpretation": "Report raw fields only; no physical duration or timestamp-unit inference",
            "formula": "d=R(q_i).inv().apply(p_(i+5)-p_i); fwd=d[0]; down=d[2]; yaw=(R(q_i).inv()*R(q_(i+5))).as_euler('zyx')[0]",
            "published_label": row["label"], "world_delta_m": delta.tolist(), "body_delta_m": body.tolist(),
            "relative_zyx_rad": relative.tolist(), **measured, "action_codec": coded,
            "controller_nominal_comparison_continuous": nominal_controller(row["label"], initial_yaw, delta.tolist(), final_yaw),
            "controller_nominal_comparison_quantized": nominal_controller(coded["decoded"], initial_yaw, delta.tolist(), final_yaw),
            "stop_flags": {"is_last_step": False, "is_penultimate": False},
            "alignment_gate_passed": measured["all_components_within_tolerance"], "approval": "not_asserted"}


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data-json", "dataset-root", "reference-manifest", "published-manifest", "official-train-json", "frozen-split", "audit-report", "upstream", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected-count", type=int, choices=(5, 20), default=5)
    parser.add_argument("--excluded-prior-manifest", type=Path)
    options = parser.parse_args()
    for name, value in vars(options).items():
        if isinstance(value, Path):
            setattr(options, name, value.resolve())
    return options


def main():
    options = arguments()
    options.output_dir.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": SCHEMA, "status": "started", "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "tolerance_absolute": TOLERANCE, "record_offset": OFFSET, "expected_count": options.expected_count,
              "physical_horizon_seconds": None, "approval": "not_asserted", "samples": [], "limitations": LIMITATIONS,
              "implementation": [preparation.file_record(__file__), preparation.file_record(preparation.__file__)],
              "simulator_started": False, "model_loaded": False, "training_executed": False}
    write_json(options.output_dir / "config.resolved.json", {"options": {k: str(v) if isinstance(v, Path) else v for k, v in vars(options).items()},
               "started_at_utc": report["started_at_utc"], "tolerance_absolute": TOLERANCE, "record_offset": OFFSET,
               "selection_policy": "Audit every prepared row; no reselection using residuals"})
    failed = False
    try:
        manifest, rows, provenance = verify_sources(options, report["started_at_utc"])
        report["provenance"] = provenance
        import numpy
        import scipy
        report["packages"] = {"numpy": numpy.__version__, "scipy": scipy.__version__}
        roundtrip = codec(options.upstream)
        for row, sample in zip(rows, manifest["samples"]):
            try:
                result = audit_sample(row, sample, options.dataset_root, roundtrip)
            except Exception as exc:
                result = {"sample_id": sample["sample_id"], "episode_id": sample["episode_id"], "alignment_gate_passed": False,
                          "error_type": type(exc).__name__, "error": str(exc), "approval": "not_asserted"}
            report["samples"].append(result)
            write_json(options.output_dir / "report.json", report)
        report["alignment_gate_passed"] = len(report["samples"]) == options.expected_count and all(s["alignment_gate_passed"] for s in report["samples"])
        report["status"] = "alignment_audited_not_approved" if report["alignment_gate_passed"] else "alignment_rejected_not_approved"
        component_values = [value for sample in report["samples"] for value in sample.get("absolute_residuals", {}).values()]
        report["measured_components"] = len(component_values)
        report["maximum_absolute_label_residual"] = max(component_values) if component_values else None
        # Recheck all evidence bytes after calculation; no successful audit of a moving source.
        for record in list(provenance["inputs"].values()) + provenance["source_code"] + [provenance["manifest"], provenance["data_json"]]:
            match_record(record["path"], record)
        for sample in report["samples"]:
            for record in sample.get("raw_log_records", []) + [record for stage in sample.get("endpoint_images", {}).values() for record in stage.values()]:
                match_record(preparation.contained(options.dataset_root, record["path"]), record)
    except Exception as exc:
        failed = True
        report.update(status="audit_failed_not_approved", alignment_gate_passed=False, error_type=type(exc).__name__, error=str(exc))
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(options.output_dir / "report.json", report)
    print(json.dumps({"status": report["status"], "sample_count": len(report["samples"]), "alignment_gate_passed": report.get("alignment_gate_passed", False),
                      "approval": "not_asserted", "report": str(options.output_dir / "report.json")}))
    return 1 if failed else 0 if report["alignment_gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
