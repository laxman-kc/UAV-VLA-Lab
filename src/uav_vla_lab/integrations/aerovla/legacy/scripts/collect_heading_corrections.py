#!/usr/bin/env python3
"""Collect one unapproved privileged heading-restoration candidate per fresh session.

This model-free collection protocol changes an in-memory reset reference and adds
an action-end pause/fresh sensor read. It never changes evaluation code or approves
labels. Use the owned scene-manager/supervisor wrapper for every invocation.
"""
from __future__ import annotations

import argparse
import ast
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import sys
import time
import traceback
from types import SimpleNamespace

from offline_policy_probe import cancellation_only, contained, lookup_target, validate_state, verify_sources
from prepare_aerovla_episode import select_and_validate
from simulator_probe import atomic_json, latest_observation, reset_checks, sha
from reset_protocol import TIMED_PROTOCOL, coords, plain, angle_error

PROTOCOL = "privileged-heading-restoration-v1"
PLAN_SCHEMA = "vla.heading-correction-plan.v1"
SOURCE_HASHES = {
    "src/aerovla_dataset.py": "55f2804162f4992eb481cda68b971edca833841a3fe5170560a8878ddb6916f7",
    "airsim_plugin/AirVLNSimulatorClientTool_AeroVLA.py": "66dfb3d97ebaeacfec7e3786de52e146dd68b1277c5d6b0316252229fbf3fe9d",
}
LIMITS = {"near_level_rad": 0.10, "target_distance_min_m": 25.0,
          "reset_position_m": 0.1, "reset_orientation_rad": 0.05,
          "final_heading_rad": 0.15, "horizontal_drift_m": 0.35,
          "vertical_drift_m": 0.35}
DECLARED_ACCEPTANCE = {"near_level_roll_pitch_rad": 0.1, "starting_target_distance_m_strictly_greater_than": 25,
                      "reset_position_error_m": 0.1, "reset_orientation_error_rad": 0.05,
                      "final_heading_error_rad": 0.15, "horizontal_drift_m": 0.35, "vertical_drift_m": 0.35,
                      "heading_error_must_decrease": True, "sampled_endpoint_contacts_must_be_false": True}
STATS = {"forward": {"min": 0.0, "max": 5.0}, "down": {"min": -5.0, "max": 5.0},
         "yaw": {"min": -1.1, "max": 1.1}}
LABEL_POLICY = {
    "source_kind_proposed": "approved_controller_expert",
    "approval": "not_asserted; candidate eligibility is not expert review",
    "source_description": "New privileged deterministic heading restoration to a recorded train-mission initial heading; no model predictions and no human certification",
    "semantic_review_status": "Not asserted. The unchanged target-navigation prompt does not expose the privileged original-heading goal; physical restoration does not establish that the label is a correct navigation action for that prompt. Independent semantic review is required before any approved training use.",
    "action_units": {"fwd": "m", "down": "m", "yaw": "rad"},
    "action_frame": "Yaw delta from actual cached pre-action quaternion using upstream scipy Rotation.as_euler('zyx')[0]; NED down; forward/down are zero. Reference heading is privileged teacher information.",
    "action_horizon": "One exact upstream move_path_by_actions macro: unpause, rotateToYawAsync(timeout=3s, margin=5deg).join, for decoded abs(yaw)>=0.25 moveToZAsync(same cached z, velocity=2, timeout=3).join, then zero-velocity 0.5s brake.join. Variable API horizon; host and simulator timestamps recorded separately.",
    "stop_semantics": "Both last/penultimate flags false; no LAND. Nonzero decoded yaw prevents numeric stop. This sample stops collection after one macro, not the navigation episode, and provides no positive stop supervision.",
    "temporal_alignment": "Fresh perturbed reset sensor cache and paused paired image capture precede the action. After macro return a collection-only pause and one additional getSensorInfo collision-latch read refresh the cache before paired post-action capture. These separate reads are not atomic. The action-end measurement gap is recorded.",
    "scope": "Controlled privileged heading restoration only; not optimal navigation, general failure recovery, route progress, physical landing, or continuous collision certification",
}


def wrap_angle(value):
    return math.atan2(math.sin(value), math.cos(value))


def quaternion_zyx(quaternion):
    """Near-level extrinsic zyx decomposition; runtime checks SciPy equivalence."""
    if len(quaternion) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in quaternion):
        raise ValueError("Expected finite xyzw quaternion")
    norm = math.sqrt(sum(v * v for v in quaternion))
    if not norm:
        raise ValueError("Zero quaternion")
    x, y, z, w = [v / norm for v in quaternion]
    pitch = math.asin(max(-1.0, min(1.0, 2 * (x * z + y * w))))
    if abs(math.cos(pitch)) < 1e-8:
        raise ValueError("Gimbal-singular heading is unsupported")
    return [math.atan2(2 * (z * w - x * y), 1 - 2 * (y * y + z * z)), pitch,
            math.atan2(2 * (x * w - y * z), 1 - 2 * (x * x + y * y))]


def quaternion_from_zyx(yaw, pitch, roll):
    cy, sy, cp, sp, cr, sr = (math.cos(yaw / 2), math.sin(yaw / 2), math.cos(pitch / 2),
                              math.sin(pitch / 2), math.cos(roll / 2), math.sin(roll / 2))
    # qx(roll) * qy(pitch) * qz(yaw): extrinsic zyx, matching the executor.
    return [sr * cp * cy + cr * sp * sy, cr * sp * cy - sr * cp * sy,
            cr * cp * sy + sr * sp * cy, cr * cp * cy - sr * sp * sy]


def perturbed_reference(reference, perturbation):
    validate_state(reference)
    if perturbation not in (-0.5, 0.5):
        raise ValueError("The frozen v1 perturbation must be exactly +/-0.5 rad")
    yaw, pitch, roll = quaternion_zyx(reference["orientation"])
    if max(abs(pitch), abs(roll)) > LIMITS["near_level_rad"]:
        raise ValueError("Original reference is not near level")
    result = copy.deepcopy(reference)
    result["orientation"] = quaternion_from_zyx(wrap_angle(yaw + perturbation), pitch, roll)
    return result


def continuous_action(reference, actual):
    validate_state(actual)
    yaw, pitch, roll = quaternion_zyx(actual["orientation"])
    if max(abs(pitch), abs(roll)) > LIMITS["near_level_rad"]:
        raise ValueError("Actual pre-action pose is not near level")
    delta = wrap_angle(quaternion_zyx(reference["orientation"])[0] - yaw)
    if not 0.25 <= abs(delta) <= 1.1:
        raise ValueError("Actual correction is outside the declared yaw-only macro branch")
    return {"fwd": 0.0, "down": 0.0, "yaw": delta}


def freeze_before_start(value, started_at_utc):
    def parse(text):
        if not isinstance(text, str):
            raise ValueError("Freeze/start timestamp must be an ISO string")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Malformed ISO freeze/start timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Freeze/start timestamp must be timezone-aware")
        return parsed
    if parse(value) > parse(started_at_utc):
        raise ValueError("Freeze timestamp is after collection start")


def validate_plan(plan, splits, source_rows, started_at_utc=None):
    if plan.get("schema_version") != PLAN_SCHEMA or plan.get("protocol_id") != PROTOCOL:
        raise ValueError("Unexpected heading collection plan/protocol")
    if not plan.get("frozen_at_utc"):
        raise ValueError("Collection plan must be frozen before execution")
    started_at_utc = started_at_utc or datetime.now(timezone.utc).isoformat()
    freeze_before_start(plan["frozen_at_utc"], started_at_utc)
    if plan.get("declared_acceptance") != DECLARED_ACCEPTANCE:
        raise ValueError("Plan acceptance differs from the fixed v1 collector")
    if splits.get("schema_version") != "vla.splits.v1" or not splits.get("frozen_at_utc"):
        raise ValueError("Require the frozen project split manifest")
    freeze_before_start(splits["frozen_at_utc"], started_at_utc)
    seen = set()
    for entries in splits["groups"].values():
        if len(entries) != len(set(entries)) or seen.intersection(entries):
            raise ValueError("Split groups overlap or contain duplicate missions")
        seen.update(entries)
    samples = plan.get("samples")
    if not isinstance(samples, list) or len(samples) != 25:
        raise ValueError("Prelock exactly 25 missions: five P09 and twenty P11")
    ids, missions = set(), set()
    train, official = set(splits["groups"]["train"]), {row["json"] for row in source_rows}
    for i, item in enumerate(samples):
        mission = item["episode_id"]
        relative = PurePosixPath(mission)
        if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 3 or relative.name != "merged_data.json":
            raise ValueError("Invalid mission path")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", item["sample_id"]):
            raise ValueError("Invalid sample ID")
        if item["sample_id"] in ids or mission in missions:
            raise ValueError("Duplicate sample or mission")
        if mission not in train or mission not in official:
            raise ValueError("Every sample must belong to both frozen and official training")
        if item["phase"] != ("P09" if i < 5 else "P11") or item["yaw_perturbation_rad"] not in (-0.5, 0.5):
            raise ValueError("Invalid phase ordering or perturbation")
        ids.add(item["sample_id"])
        missions.add(mission)
    return samples


def selected_metadata(options, sample):
    selection, metadata = select_and_validate(options.source_split, options.dataset_root, options.upstream / "data/meta", PurePosixPath(sample["episode_id"]).parts[1])
    if {row["json"] for row in selection} != {sample["episode_id"]}:
        raise ValueError("Official selection resolved a different mission")
    merged_path = contained(options.dataset_root, sample["episode_id"])
    merged = json.loads(merged_path.read_text())
    reference = merged["trajectory_raw_detailed"][0]
    perturbed = perturbed_reference(reference, sample["yaw_perturbation_rad"])
    raw_paths = sorted((merged_path.parent / "log").glob("*.json"))
    if not raw_paths:
        raise ValueError("Original first raw log is unavailable")
    raw = json.loads(raw_paths[0].read_text())
    if validate_state(raw["sensors"]["state"]) != validate_state(reference):
        raise ValueError("Merged initial state differs from original first raw log")
    target = lookup_target(options.upstream, PurePosixPath(sample["episode_id"]).parts[0], json.loads((merged_path.parent / "mark.json").read_text()))
    distance = math.dist(reference["position"], target["target_position"])
    if distance <= LIMITS["target_distance_min_m"]:
        raise ValueError("Reference starts inside the predeclared >25m nonterminal margin")
    metadata.update(first_raw_log=file_record(raw_paths[0]), target_lookup=target, reference_target_distance_m=distance)
    return selection, metadata, reference, perturbed


def pure_method(source, class_name, method_name, namespace):
    tree = ast.parse(Path(source).read_text())
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name]
    nodes = [n for n in classes[0].body if isinstance(n, ast.FunctionDef) and n.name == method_name] if len(classes) == 1 else []
    if len(nodes) != 1:
        raise ValueError("Cannot isolate exact pinned pure method")
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    return namespace[method_name]


def source_functions(upstream):
    import numpy as np
    from scipy.spatial.transform import Rotation
    records = verify_sources(upstream)
    for relative, expected in SOURCE_HASHES.items():
        path = upstream / relative
        source = path.read_text()
        backup = path.with_suffix(".py.vla-lab-original")
        original = backup.read_text() if backup.exists() else source
        if hashlib.sha256(original.encode()).hexdigest() != expected or source not in (original, cancellation_only(original)):
            raise ValueError(f"Unreviewed pinned source: {relative}")
        records.append({"path": str(path), "sha256": sha(path), "pinned_original_sha256": expected})
    namespace = {"np": np, "R": Rotation, "re": re, "NUM_BINS": 99, "ACTION_STATS": STATS}
    wrapper = upstream / "src/model_wrapper/aerovla_wrapper_ui.py"
    quantize = pure_method(upstream / "src/aerovla_dataset.py", "AeroVLADataset", "_quantize_action", namespace)
    parse = pure_method(wrapper, "AerialVLAWrapper", "_parse_action_from_text", namespace)
    direction = pure_method(wrapper, "AerialVLAWrapper", "get_semantic_direction", namespace)
    return records, quantize, parse, direction, Rotation


def label_roundtrip(label, quantize, parse):
    bins = [quantize(None, label[key], axis) for key, axis in (("fwd", "forward"), ("down", "down"), ("yaw", "yaw"))]
    text = " ".join(f"{value:02d}" for value in bins)
    decoded = dict(zip(("fwd", "down", "yaw"), parse(SimpleNamespace(norm_stats=STATS, NUM_BINS=99), "Action: " + text)))
    if decoded["fwd"] != 0 or decoded["down"] != 0 or not 0.25 <= abs(decoded["yaw"]) <= 1.1:
        raise ValueError("Quantized command does not satisfy yaw-only nonterminal semantics")
    return {"continuous_label": label, "bins": bins, "action_text": text, "decoded_action": decoded,
            "decoded_should_stop": False, "quantization_note": "Execute exact parser output, not the continuous target or re-quantized decoded floats"}


def endpoint_measurements(reference, initial, final, camera_quaternion, initial_position, final_position):
    reference_yaw = quaternion_zyx(reference["orientation"])[0]
    initial_error = abs(wrap_angle(quaternion_zyx(initial["orientation"])[0] - reference_yaw))
    final_error = abs(wrap_angle(quaternion_zyx(final["orientation"])[0] - reference_yaw))
    camera_error = abs(wrap_angle(quaternion_zyx(camera_quaternion)[0] - reference_yaw))
    delta = [b - a for a, b in zip(initial_position, final_position)]
    measures = {"initial_heading_error_rad": initial_error, "final_heading_error_rad": final_error,
                "front_camera_heading_error_rad": camera_error, "horizontal_drift_m": math.hypot(*delta[:2]),
                "vertical_drift_m": abs(delta[2])}
    checks = {"groundtruth_heading_restored": final_error <= LIMITS["final_heading_rad"],
              "front_camera_heading_restored": camera_error <= LIMITS["final_heading_rad"],
              "groundtruth_heading_error_reduced": final_error < initial_error,
              "front_camera_heading_error_reduced": camera_error < initial_error,
              "horizontal_drift_bounded": measures["horizontal_drift_m"] <= LIMITS["horizontal_drift_m"],
              "vertical_drift_bounded": measures["vertical_drift_m"] <= LIMITS["vertical_drift_m"]}
    return {"measurements": measures, "checks": checks}


def capture_pose(capture, camera, field):
    selected = [response[field] for request, response in zip(capture["requests"], capture["responses"])
                if request["camera_name"] == camera and request["image_type"] == 0]
    if len(selected) != 1:
        raise ValueError("Missing unique actual RGB camera response")
    return coords(selected[0], "xyzw" if field == "camera_orientation" else "xyz")


def file_record(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}


def export_candidate(root, sample, observation, action, prompt, result):
    """Only mechanically eligible rows are copied; no approval manifest is made."""
    relative = PurePosixPath(sample["episode_id"])
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 3 or relative.name != "merged_data.json":
        raise ValueError("Candidate mission path must preserve Map/episode identity")
    trajectory = str(relative.parent)
    destination = root / "candidate" / trajectory
    destination.mkdir(parents=True)
    files = []
    for camera, folder in (("front", "frontcamera"), ("down", "downcamera")):
        source = next(item for item in observation["images"] if item["camera"] == camera and item["modality"] == "rgb")
        original = contained(root / "evidence", source["path"])
        if sha(original) != source["sha256"]:
            raise ValueError("Recorded source image changed before candidate export")
        target = destination / folder / "000000.png"
        target.parent.mkdir()
        shutil.copyfile(original, target)
        files.append({"camera": camera, "path": str(target.relative_to(root)), "sha256": sha(target),
                      "source_observation_event_id": observation["event_id"], "source_image": source})
    row = {"traj_rel_dir": trajectory, "img_name": "000000.png", "instruction": prompt,
           "label": action["continuous_label"], "is_last_step": False, "is_penultimate": False}
    atomic_json(root / "candidate" / "candidate_rows.json", [row])
    atomic_json(destination / "source.json", {"sample": sample, "observation": observation,
                 "action": action, "result_path": "../../../result.json", "images": files,
                 "status": "mechanically_eligible_pending_expert_review", "approval": "not_asserted",
                 "teacher_goal": "Restore privileged recorded initial heading; no navigation-optimality claim"})
    return {"row": row, "row_sha256": hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest(),
            "images": files, "dataset_root": str(root / "candidate"), "approval": "not_asserted"}


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("upstream", "dataset-root", "source-split", "split-manifest", "plan", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--sample-index", type=int, default=0)
    parser.add_argument("--simulator-port", type=int, default=30000)
    parser.add_argument("--gpu-id", type=int, default=0, help="Simulator rendering GPU; no policy model is loaded")
    parser.add_argument("--max-wall-seconds", type=float, default=180)
    parser.add_argument("--scene-manager-exclusive", action="store_true", required=True)
    parser.add_argument("--validate-only", action="store_true", help="Validate plan, hashes and selected real source metadata; no simulator imports")
    parser.add_argument("--preflight-all", action="store_true", help="With --validate-only, audit all 25 prelocked source missions before any simulator run")
    args = parser.parse_args()
    if args.preflight_all and not args.validate_only:
        parser.error("--preflight-all requires --validate-only")
    if not 0 <= args.sample_index < 25 or not 1024 <= args.simulator_port <= 64535 or args.gpu_id < 0 or not math.isfinite(args.max_wall_seconds) or args.max_wall_seconds <= 0:
        parser.error("Invalid sample index, port, GPU or wall-time bound")
    for name in ("upstream", "dataset_root", "source_split", "split_manifest", "plan", "output_dir"):
        setattr(args, name, getattr(args, name).resolve())
    return args


def main():
    options = arguments()
    root = options.output_dir
    root.mkdir(parents=True, exist_ok=False)
    failure = runtime = env = None
    result = {"schema_version": "vla.heading-correction-result.v1", "protocol_id": PROTOCOL,
              "approval": "not_asserted", "status": "started", "candidate_eligible": False,
              "model_loaded": False, "checks": {}, "limits": LIMITS, "label_policy": LABEL_POLICY}
    started = time.monotonic_ns()
    started_at_utc = datetime.now(timezone.utc).isoformat()
    result["started_at_utc"] = started_at_utc
    old_alarm = signal.getsignal(signal.SIGALRM)
    def deadline(signum, frame):
        raise SystemExit(124)
    signal.signal(signal.SIGALRM, deadline)
    signal.setitimer(signal.ITIMER_REAL, options.max_wall_seconds)
    try:
        plan, splits, rows = (json.loads(path.read_text()) for path in (options.plan, options.split_manifest, options.source_split))
        if plan["source_split_sha256"] != sha(options.source_split) or plan["split_manifest_sha256"] != sha(options.split_manifest):
            raise ValueError("Plan source/split hash mismatch")
        samples = validate_plan(plan, splits, rows, started_at_utc)
        sample = samples[options.sample_index]
        result["sample"] = sample
        result["inputs"] = [file_record(p) for p in (options.plan, options.source_split, options.split_manifest, Path(__file__),
                             Path(__file__).with_name("offline_policy_probe.py"), Path(__file__).with_name("prepare_aerovla_episode.py"),
                             Path(__file__).with_name("simulator_probe.py"), Path(__file__).with_name("reset_protocol.py"))]
        atomic_json(root / "plan.json", plan)
        result["source_code"] = verify_sources(options.upstream)
        if options.preflight_all:
            preflight = []
            for candidate in samples:
                try:
                    _, meta, original, changed = selected_metadata(options, candidate)
                    preflight.append({"sample": candidate, "passed": True, "metadata": meta,
                                      "original_reference": original, "perturbed_reference": changed})
                except Exception as exc:
                    preflight.append({"sample": candidate, "passed": False, "error_type": type(exc).__name__, "error": str(exc)})
                atomic_json(root / "preflight.json", {"protocol_id": PROTOCOL, "plan_sha256": sha(options.plan), "results": preflight,
                            "all25_passed": len(preflight) == 25 and all(row["passed"] for row in preflight), "simulator_started": False})
            if not all(row["passed"] for row in preflight):
                raise ValueError("At least one prelocked mission failed metadata preflight; preserve all rejected IDs and do not replace by outcome")
        selection, metadata, reference, perturbed = selected_metadata(options, sample)
        result.update(original_reference=reference, perturbed_reference=perturbed, source_metadata=metadata)
        atomic_json(root / "episode.json", selection)
        atomic_json(root / "selection_manifest.json", metadata)
        atomic_json(root / "config.resolved.json", {"options": {k: str(v) if isinstance(v, Path) else v for k, v in vars(options).items()},
                    "plan_sha256": sha(options.plan), "sample": sample, "limits": LIMITS, "label_policy": LABEL_POLICY, "started_at_utc": started_at_utc,
                    "protocol_id": PROTOCOL, "reset_protocol": TIMED_PROTOCOL, "model_loaded": False,
                    "modified_disk_trajectory": False, "post_action_pause_added": True,
                    "post_action_sensor_refresh_added_collision_queries": 1})
        if options.validate_only:
            result.update(status="source_validated_only", checks={"plan_and_selected_metadata_valid": True})
            return_code = 0
        else:
            sources, quantize, parse, direction, Rotation = source_functions(options.upstream)
            for state in (reference, perturbed):
                expected = Rotation.from_quat(state["orientation"]).as_euler("zyx")
                if max(abs(wrap_angle(a - float(b))) for a, b in zip(quaternion_zyx(state["orientation"]), expected)) > 1e-9:
                    raise ValueError("Geometry differs from exact upstream SciPy convention")
            result["source_code"] = sources
            manifest = json.loads((options.upstream / "vla_lab_patch_manifest.json").read_text())
            for relative, record in manifest["files"].items():
                if sha(options.upstream / relative) != record.get("patched_sha256", record.get("sha256")):
                    raise ValueError(f"Installed integration file changed: {relative}")
            if (options.upstream / "dataset_raw").resolve() != options.dataset_root:
                raise ValueError("Upstream dataset_raw symlink must match --dataset-root")
            os.environ["CUDA_VISIBLE_DEVICES"] = str(options.gpu_id)
            os.environ["VLA_LAB_SCENE_MANAGER_EXCLUSIVE"] = "1"
            os.environ["VLA_LAB_EVENT_DIR"] = str(root / "evidence")
            # Explicit collection identity; the immutable parent receipt is retained separately.
            parent_runtime_id = os.environ.get("VLA_LAB_RUNTIME_ID", "unrecorded")
            os.environ["VLA_LAB_RUNTIME_ID"] = PROTOCOL + "-" + TIMED_PROTOCOL
            os.environ["VLA_LAB_RESET_PROTOCOL"] = TIMED_PROTOCOL
            os.chdir(options.upstream)
            sys.path.insert(0, str(options.upstream))
            sys.path.insert(0, str(options.upstream / "src/vlnce_src"))
            results_root = root / "upstream_results"
            results_root.mkdir()
            sys.argv = [str(options.upstream / "src/vlnce_src/eval_aerovla.py"), "--run_type", "eval", "--name", "HeadingCorrectionCollection", "--batchSize", "1", "--maxWaypoints", "1", "--gpu_id", str(options.gpu_id), "--simulator_tool_port", str(options.simulator_port), "--dataset_path", "./dataset_raw/", "--eval_save_path", str(results_root), "--eval_json_path", str(root / "episode.json"), "--map_spawn_area_json_path", "./data/meta/map_spawnarea_info.json", "--object_name_json_path", "./data/meta/object_description.json"]
            from src.common.param import args
            from src.vlnce_src.env_uav import AirVLNENV
            from airsim_plugin.AirVLNSimulatorClientTool_AeroVLA import AirVLNSimulatorClientTool
            from _vla_lab_runtime import Runtime
            env = AirVLNENV(batch_size=1, dataset_path="./dataset_raw/", save_path=str(results_root), eval_json_path=str(root / "episode.json"))
            if len(env.data) != 1 or env.data[0]["trajectory"][0] != reference:
                raise ValueError("Upstream did not load the exact recorded initial state")
            target = env.data[0]["object_position"]
            result["target_position"] = target
            result["reference_target_distance_m"] = math.dist(reference["position"], target)
            if result["reference_target_distance_m"] <= LIMITS["target_distance_min_m"]:
                raise ValueError("Reference starts inside the predeclared nonterminal margin")
            runtime = Runtime(env, args, SimpleNamespace(model_path=None))
            runtime.rec.emit("collection.protocol", protocol_id=PROTOCOL, parent_runtime_id=parent_runtime_id,
                             label_policy=LABEL_POLICY, limits=LIMITS, plan_sha256=sha(options.plan), sample=sample,
                             note="runtime collision.response wording describes the base hook; explicit collection sensor refresh events identify its additional latch query")
            runtime.patch(env, "next_minibatch", runtime.episode)
            runtime.patch(env, "makeActions", runtime.action)
            runtime.patch(AirVLNSimulatorClientTool, "run_call", runtime.scene_open)
            helper = runtime.reset_config["module"].install(env, runtime, protocol=TIMED_PROTOCOL)
            # Only an isolated in-memory copy is changed. Source bytes and env.data stay original.
            env.next_minibatch()
            original_batch = copy.deepcopy(env.batch)
            env.batch = copy.deepcopy(env.batch)
            env.batch[0]["trajectory"][0] = copy.deepcopy(perturbed)
            env.VectorEnvUtil.set_batch(env.batch)
            runtime.rec.emit("collection.reference_perturbed", original=reference, requested=perturbed,
                             method="Preserve extrinsic zyx pitch/roll and add signed 0.5rad to its yaw; collection-only in-memory batch")
            initial = latest_observation(env.reset())
            camera_reset = helper.acceptance(LIMITS["reset_position_m"], LIMITS["reset_orientation_rad"])
            initial_capture = copy.deepcopy(helper.last_capture)
            runtime.observe(initial)
            reset = reset_checks(initial["sensors"]["state"], perturbed, LIMITS["reset_position_m"], LIMITS["reset_orientation_rad"])
            result.update(attempt_id=runtime.attempt_id, initial_state=plain(initial["sensors"]["state"]),
                          reset_measurements=reset, reset_camera=camera_reset)
            checks = result["checks"]
            checks.update(reset["checks"])
            checks.update(camera_reset["checks"])
            checks["initial_endpoint_contact_false"] = initial["sensors"]["state"].get("collision", {}).get("has_collided") is False
            checks["initial_target_margin"] = math.dist(initial["sensors"]["state"]["position"], target) > LIMITS["target_distance_min_m"]
            settings = json.loads((options.upstream / "airsim_plugin/settings" / str(env.simulator_tool.airsim_ports[0]) / "settings.json").read_text())
            checks["clock_speed_unchanged"] = settings.get("ClockSpeed") == 10
            if not all(checks.values()):
                result["status"] = "rejected_before_action"
            else:
                action = label_roundtrip(continuous_action(reference, initial["sensors"]["state"]), quantize, parse)
                raw_instruction = original_batch[0]["instruction"]
                object_description = raw_instruction.split("degrees from you.")[1].split(" Please control")[0].strip()
                prompt = f"<image>\nFly {direction(None, initial['sensors']['state'], target)}and find the target. {object_description}"
                result.update(action=action, prompt=prompt, prompt_source="Pinned semantic bearing from actual pre-action state and official target; unchanged extracted benchmark object description")
                runtime.rec.emit("teacher.proposed", observation_event_id=runtime.observation_id, action=action,
                                 prompt=prompt, original_reference=reference, approval="not_asserted")
                before = time.monotonic_ns()
                env.makeActions([action["decoded_action"]])
                action_return = time.monotonic_ns()
                original_action_endpoint = copy.deepcopy(env.sim_states[0].trajectory[-1]["sensors"]["state"])
                client = helper.client()
                helper.call(client, "simPause", is_paused=True)
                if helper.call(client, "simIsPause") is not True:
                    raise RuntimeError("Post-action measurement did not pause")
                runtime.rec.emit("collection.sensor_refresh_begin", added_collision_queries=1,
                                 semantics="Fresh getSensorInfo samples state/IMU and one collision latch after action; preserves raw result, not continuous contact history")
                refreshed = env.simulator_tool.getSensorInfo()[0][0]
                env.sim_states[0].trajectory.append(copy.deepcopy(refreshed))
                env.update_measurements()
                runtime.rec.emit("collection.sensor_refresh_end", response=refreshed, added_collision_queries=1)
                final = latest_observation(env.get_obs())
                runtime.observe(final)
                final_capture = copy.deepcopy(helper.last_capture)
                # Reuse the exact extrinsic/mapping checks against this actual endpoint,
                # then independently compare endpoint GT/camera to the original heading.
                actual_endpoint = {"position": list(refreshed["sensors"]["state"]["position"]),
                                   "orientation": list(refreshed["sensors"]["state"]["orientation"])}
                env.batch[0]["trajectory"][0] = actual_endpoint
                try:
                    aligned = helper.acceptance(LIMITS["reset_position_m"], LIMITS["reset_orientation_rad"])
                finally:
                    env.batch[0]["trajectory"][0] = copy.deepcopy(perturbed)
                initial_gt = {k: coords(camera_reset["ground_truth"][k], "xyz" if k == "position" else "xyzw") for k in ("position", "orientation")}
                final_gt = {k: coords(aligned["ground_truth"][k], "xyz" if k == "position" else "xyzw") for k in ("position", "orientation")}
                measured = endpoint_measurements(reference, initial_gt, final_gt,
                             capture_pose(final_capture, "FrontCamera", "camera_orientation"), initial_gt["position"], final_gt["position"])
                camera_delta = [b - a for a, b in zip(capture_pose(initial_capture, "DownCamera", "camera_position"), capture_pose(final_capture, "DownCamera", "camera_position"))]
                checks.update({"post_capture_" + key: value for key, value in aligned["checks"].items()})
                checks.update(measured["checks"])
                checks["down_camera_horizontal_drift_bounded"] = math.hypot(*camera_delta[:2]) <= LIMITS["horizontal_drift_m"]
                checks["down_camera_vertical_drift_bounded"] = abs(camera_delta[2]) <= LIMITS["vertical_drift_m"]
                checks["final_endpoint_contact_false"] = refreshed["sensors"]["state"].get("collision", {}).get("has_collided") is False
                checks["original_action_endpoint_contact_false"] = original_action_endpoint.get("collision", {}).get("has_collided") is False
                checks["final_nonterminal_distance"] = math.dist(final_gt["position"], target) > 20
                result.update(final_state=plain(final["sensors"]["state"]), final_camera_alignment=aligned,
                              original_action_endpoint_state=plain(original_action_endpoint),
                              heading_measurements=measured["measurements"], down_camera_displacement_m=camera_delta,
                              action_start_ns=before, action_return_ns=action_return,
                              final_capture_return_ns=final_capture["call_return_ns"],
                              action_return_to_capture_ns=final_capture["call_return_ns"] - action_return,
                              status="measured_candidate_pending_review" if all(checks.values()) else "rejected_after_action")
            checks["disk_source_metadata_unchanged"] = all(sha(Path(info["path"])) == info["sha256"] for info in metadata["source_files"] + [metadata["first_raw_log"]])
            checks["original_loader_reference_unchanged"] = env.data[0]["trajectory"][0] == reference
            runtime.rec.emit("collection.completed", result=result)
            runtime.rec.write_json(f"outcomes/{runtime.attempt_id}.json", result)
            runtime.attempt_complete = True
            return_code = 0 if all(checks.values()) else 2
    except BaseException as exc:
        failure = exc
        result.update(status="interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "rejected_or_failed",
                      error_type=type(exc).__name__, error=str(exc))
        traceback.print_exc()
        return_code = exc.code if isinstance(exc, SystemExit) and isinstance(exc.code, int) else 130 if isinstance(exc, KeyboardInterrupt) else 1
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_alarm)
        cleanup = []
        for name, close in (("runtime", lambda: runtime.close(error=failure) if runtime else None),
                            ("workers", lambda: env.delete_VectorEnvUtil() if env else None)):
            try:
                close()
            except BaseException as exc:
                cleanup.append(f"{name}: {type(exc).__name__}: {exc}")
        result.update(cleanup_exceptions=cleanup, wall_duration_ns=time.monotonic_ns() - started)
        event_path = root / "evidence/events.jsonl"
        if event_path.exists():
            try:
                events = [json.loads(line) for line in event_path.read_text().splitlines() if line.strip()]
                endings = [e for e in events if e["event_type"] == "run.end"]
                observations = [e for e in events if e["event_type"] == "observation.prepared"]
                requests = [e for e in events if e["event_type"] == "action.requested"]
                completed = [e for e in events if e["event_type"] == "action.completed"]
                captures = {e["event_id"]: e for e in events if e["event_type"] == "images.received"}
                result["cleanup_succeeded"] = bool(endings) and not endings[-1]["cleanup_errors"] and not cleanup
                chain = {"two_actual_observations": len(observations) == 2,
                         "one_action_completed": len(requests) == len(completed) == 1 and completed[0]["command_event_id"] == requests[0]["event_id"],
                         "action_uses_initial_observation": len(requests) == 1 and bool(observations) and requests[0]["observation_event_id"] == observations[0]["event_id"],
                         "no_model_events": not any(e["event_type"].startswith("policy.") for e in events),
                         "cleanup_succeeded": result["cleanup_succeeded"]}
                chain["paired_image_hashes_and_timestamps"] = len(observations) == 2 and all(
                    len(e["images"]) == 10 and all(sha(contained(root / "evidence", image["path"])) == image["sha256"] for image in e["images"]) and
                    len(captures.get(e["image_capture_event_id"], {}).get("responses", [])) == 10 and
                    all(type(response.get("time_stamp")) in (int, float) and response["time_stamp"] > 0 for response in captures[e["image_capture_event_id"]]["responses"]) and
                    type(e["sensors"]["state"].get("timestamp")) in (int, float) and e["sensors"]["state"]["timestamp"] > 0
                    for e in observations)
                chain["observation_action_completion_order"] = len(observations) == 2 and len(requests) == len(completed) == 1 and observations[0]["event_id"] < requests[0]["event_id"] < completed[0]["event_id"] < observations[1]["event_id"]
                chain["executed_exact_decoded_teacher_action"] = len(requests) == 1 and requests[0]["actions"] == [result.get("action", {}).get("decoded_action")]
                result["evidence_checks"] = chain
                result["candidate_eligible"] = failure is None and result["status"] == "measured_candidate_pending_review" and all(result["checks"].values()) and all(chain.values())
                if result["candidate_eligible"]:
                    result["candidate_export"] = export_candidate(root, result["sample"], observations[0], result["action"], result["prompt"], result)
                else:
                    return_code = return_code or 2
            except BaseException as exc:
                result.update(candidate_eligible=False, export_error=f"{type(exc).__name__}: {exc}")
                return_code = 1
        if cleanup:
            return_code = 1
        atomic_json(root / "result.json", result)
        print(json.dumps({"status": result["status"], "candidate_eligible": result["candidate_eligible"], "approval": "not_asserted", "output_dir": str(root)}), flush=True)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
