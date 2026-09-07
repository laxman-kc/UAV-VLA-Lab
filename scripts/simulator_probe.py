#!/usr/bin/env python3
"""Run genuine model-free TravelUAV capture/controller probes on a prepared host.

No scene manager is started here. Use an exclusively owned, already running
manager. Inputs must be a real one-episode selection; simulator results are never
fabricated from metadata. The upstream controller and ClockSpeed=10 are retained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sys
import time
import traceback
from types import SimpleNamespace

DEFAULT_PROBES = [
    {"name": "heading", "action": {"fwd": 0.0, "down": 0.0, "yaw": 0.5},
     "tolerances": {"yaw_error_rad": 0.15, "horizontal_error_m": 0.35, "vertical_error_m": 0.35}},
    {"name": "horizontal", "action": {"fwd": 2.0, "down": 0.0, "yaw": 0.0},
     "tolerances": {"yaw_error_rad": 0.15, "horizontal_error_m": 0.5, "vertical_error_m": 0.35}},
    {"name": "vertical", "action": {"fwd": 0.0, "down": -1.0, "yaw": 0.0},
     "tolerances": {"yaw_error_rad": 0.15, "horizontal_error_m": 0.35, "vertical_error_m": 0.4}},
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, value):
    target = Path(path)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(target)


def validate_probes(probes):
    if not isinstance(probes, list) or len(probes) != 3:
        raise ValueError("Controller config must contain three isolated probes")
    if {item["name"] for item in probes} != {"heading", "horizontal", "vertical"}:
        raise ValueError("Required probe names: heading, horizontal, vertical")
    for item in probes:
        action = item["action"]
        if set(action) != {"fwd", "down", "yaw"} or not all(math.isfinite(value) for value in action.values()):
            raise ValueError("Actions require three finite fwd/down/yaw values")
        if not (0 <= action["fwd"] <= 5 and -5 <= action["down"] <= 5 and -1.1 <= action["yaw"] <= 1.1):
            raise ValueError("Probe exceeds the released action ranges")
        active = {axis for axis, value in action.items() if value != 0}
        expected = {"heading": {"yaw"}, "horizontal": {"fwd"}, "vertical": {"down"}}[item["name"]]
        if active != expected:
            raise ValueError(f"Probe {item['name']} must isolate {expected}")
        tolerance = item["tolerances"]
        if set(tolerance) != {"yaw_error_rad", "horizontal_error_m", "vertical_error_m"}:
            raise ValueError("Specify all three numerical tolerances")
        if not all(math.isfinite(value) and value >= 0 for value in tolerance.values()):
            raise ValueError("Tolerances must be finite and nonnegative")
    return probes


def expected_displacement(action, initial_yaw):
    # Exactly the released executor's new-heading and large-yaw branch semantics.
    target_yaw = initial_yaw + action["yaw"]
    forward = action["fwd"] if abs(action["yaw"]) < 0.25 else 0.0
    return [forward * math.cos(target_yaw), forward * math.sin(target_yaw), action["down"]]


def reset_checks(actual, reference, position_tolerance, angle_tolerance):
    position_error = math.dist(actual["position"], reference["position"])
    first, second = actual["orientation"], reference["orientation"]
    norm = math.sqrt(sum(value * value for value in first) * sum(value * value for value in second))
    if norm == 0:
        raise ValueError("Simulator or reference returned a zero quaternion")
    angle_error = 2 * math.acos(min(1.0, abs(sum(a * b for a, b in zip(first, second))) / norm))
    return {"reset_position_error_m": position_error, "reset_orientation_error_rad": angle_error,
            "checks": {"reset_position_within_tolerance": position_error <= position_tolerance,
                       "reset_orientation_within_tolerance": angle_error <= angle_tolerance}}


def movement_checks(initial, final, action, tolerance):
    from scipy.spatial.transform import Rotation
    initial_yaw = float(Rotation.from_quat(initial["orientation"]).as_euler("zyx")[0])
    final_yaw = float(Rotation.from_quat(final["orientation"]).as_euler("zyx")[0])
    displacement = [float(b - a) for a, b in zip(initial["position"], final["position"])]
    expected = expected_displacement(action, initial_yaw)
    yaw_change = math.atan2(math.sin(final_yaw - initial_yaw), math.cos(final_yaw - initial_yaw))
    yaw_error = abs(math.atan2(math.sin(yaw_change - action["yaw"]), math.cos(yaw_change - action["yaw"])))
    measured_errors = {"yaw_error_rad": yaw_error,
                       "horizontal_error_m": math.hypot(displacement[0] - expected[0], displacement[1] - expected[1]),
                       "vertical_error_m": abs(displacement[2] - expected[2])}
    return {"expected_displacement_m": expected, "measured_displacement_m": displacement,
            "measured_yaw_change_rad": yaw_change, "errors": measured_errors,
            "tolerances": tolerance, "checks": {key: measured_errors[key] <= limit for key, limit in tolerance.items()}}


def latest_observation(outputs):
    latest = outputs[0][0][-1]
    if len(latest["rgb"]) != 5 or len(latest["depth"]) != 5:
        raise ValueError("Upstream did not return five RGB and five depth views")
    for image in latest["rgb"]:
        if tuple(image.shape) != (256, 256, 3):
            raise ValueError(f"Unexpected RGB shape: {image.shape}")
    for image in latest["depth"]:
        if tuple(image.shape) != (256, 256):
            raise ValueError(f"Unexpected depth shape: {image.shape}")
    return latest


def log_checks(event_root, events, mode, expected_attempts):
    """Verify evidence is present and causally linked, without inventing samples."""
    observations = [event for event in events if event["event_type"] == "observation.prepared"]
    captures = {event["event_id"]: event for event in events if event["event_type"] == "images.received"}
    actions = [event for event in events if event["event_type"] == "action.requested"]
    completed = [event for event in events if event["event_type"] == "action.completed"]
    spawns = [event for event in events if event["event_type"] == "controller.call" and event["method"] == "simSpawnObject"]
    spawn_results = {event["controller_event_id"]: event for event in events if event["event_type"] == "controller.call_returned"}
    expected_observations = expected_attempts * (2 if mode == "controller" else 1)
    checks = {
        "expected_observation_count": len(observations) == expected_observations,
        "expected_action_count": len(actions) == (expected_attempts if mode == "controller" else 0),
        "all_requested_actions_completed": len(actions) == len(completed) and
            {event["event_id"] for event in actions} == {event["command_event_id"] for event in completed},
        "no_model_events": not any(event["event_type"].startswith("policy.") for event in events),
        "target_spawn_returned_name_each_reset": len(spawns) == expected_attempts and all(
            spawn_results.get(event["event_id"], {}).get("object_spawn_returned_name") is True for event in spawns),
        "unique_reset_attempts": len({event["attempt_id"] for event in events if event["event_type"] == "episode.start"}) == expected_attempts,
        "monotonic_event_order": all(a["host_monotonic_ns"] <= b["host_monotonic_ns"] for a, b in zip(events, events[1:])),
        "images_present_and_hashes_match": bool(observations),
        "capture_links_and_timestamps_present": bool(observations),
        "state_and_imu_timestamps_present": bool(observations),
    }
    for observation in observations:
        files = observation["images"]
        checks["images_present_and_hashes_match"] &= len(files) == 10 and all(
            (event_root / item["path"]).is_file() and sha(event_root / item["path"]) == item["sha256"] for item in files)
        capture = captures.get(observation.get("image_capture_event_id"), {})
        responses = capture.get("responses", [])
        checks["capture_links_and_timestamps_present"] &= (
            capture.get("attempt_id") == observation["attempt_id"] and len(responses) == 10 and
            all(isinstance(item.get("time_stamp"), (int, float)) and item["time_stamp"] > 0 for item in responses))
        sensors = observation["sensors"]
        checks["state_and_imu_timestamps_present"] &= (
            isinstance(sensors["state"].get("timestamp"), (int, float)) and sensors["state"]["timestamp"] > 0 and
            isinstance(sensors.get("imu", {}).get("time_stamp"), (int, float)) and sensors["imu"]["time_stamp"] > 0)
    return checks


def read_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("capture", "controller"), required=True)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--episode-json", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--simulator-port", type=int, default=30000)
    parser.add_argument("--gpu-id", type=int, default=0)
    parser.add_argument("--scene-manager-exclusive", action="store_true", required=True)
    parser.add_argument("--reset-protocol", choices=("upstream", "paused-final-pose-v1", "paused-final-pose-time-v1"), default="upstream",
                        help="Explicit reset behavior; all modes verify captured camera pose and paused ground truth")
    parser.add_argument("--probe-config", type=Path, help="JSON array overriding the proposed recorded default probes/tolerances")
    parser.add_argument("--capture-resets", type=int, default=2, help="Proposed capture scope; no action during these resets")
    parser.add_argument("--reset-position-tolerance-m", type=float, default=0.1, help="Proposed reset acceptance tolerance, recorded before measurement")
    parser.add_argument("--reset-angle-tolerance-rad", type=float, default=0.05, help="Proposed quaternion rotation-distance tolerance")
    parser.add_argument("--max-wall-seconds", type=float, default=180, help="Explicit process wall-time bound; external supervisor remains responsible for forced cleanup")
    options = parser.parse_args()
    if not (1024 <= options.simulator_port <= 64535):
        parser.error("Select a nonprivileged manager port with room for its scene-port allocation")
    if options.gpu_id < 0 or options.capture_resets < 1 or options.max_wall_seconds <= 0:
        parser.error("GPU, reset count or wall-time limit is invalid")
    if not all(math.isfinite(value) and value >= 0 for value in (options.reset_position_tolerance_m, options.reset_angle_tolerance_rad)):
        parser.error("Reset tolerances must be finite and nonnegative")
    return options


def main():
    options = read_args()
    options.upstream = options.upstream.resolve()
    options.episode_json = options.episode_json.resolve()
    options.dataset_root = options.dataset_root.resolve()
    options.output_dir = options.output_dir.resolve()
    probes = validate_probes(json.loads(options.probe_config.read_text()) if options.probe_config else DEFAULT_PROBES)
    if (options.upstream / "dataset_raw").resolve() != options.dataset_root:
        raise ValueError("The upstream ./dataset_raw path must resolve to --dataset-root (create the intended symlink first)")
    manifest_path = options.upstream / "vla_lab_patch_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for relative, info in manifest["files"].items():
        if sha(options.upstream / relative) != info.get("patched_sha256", info.get("sha256")):
            raise ValueError(f"Installed integration file changed: {relative}")
    rows = json.loads(options.episode_json.read_text())
    if len({row["json"] for row in rows}) != 1:
        raise ValueError("Supply the genuine single-episode selection JSON")
    options.output_dir.mkdir(parents=True, exist_ok=False)
    resolved = {"schema_version": 1, "mode": options.mode, "upstream": str(options.upstream),
                "episode_json": str(options.episode_json), "episode_json_sha256": sha(options.episode_json),
                "dataset_root": str(options.dataset_root), "simulator_port": options.simulator_port,
                "gpu_id": options.gpu_id, "expected_clock_speed": 10, "model_loaded": False,
                "reset_protocol": options.reset_protocol, "probe_source_sha256": sha(__file__),
                "reset_protocol_source_sha256": sha(Path(__file__).with_name("reset_protocol.py")),
                "reset_acceptance_scope": "Cached state plus actual front-camera rotation/down-camera origin and post-capture paused ground truth; same declared tolerances",
                "capture_resets": options.capture_resets, "max_wall_seconds": options.max_wall_seconds,
                "reset_position_tolerance_m": options.reset_position_tolerance_m,
                "reset_angle_tolerance_rad": options.reset_angle_tolerance_rad,
                "controller_probes": probes, "probe_config_source": str(options.probe_config) if options.probe_config else "proposed_defaults_v1",
                "interpretation": "Scripted sensor/controller acceptance probes, not learned-navigation success"}
    atomic_json(options.output_dir / "config.resolved.json", resolved)
    print(json.dumps(resolved, indent=2), flush=True)
    os.environ["CUDA_VISIBLE_DEVICES"] = str(options.gpu_id)
    os.environ["VLA_LAB_SCENE_MANAGER_EXCLUSIVE"] = "1"
    os.environ["VLA_LAB_EVENT_DIR"] = str(options.output_dir / "evidence")
    os.chdir(options.upstream)
    sys.path.insert(0, str(options.upstream))
    sys.path.insert(0, str(options.upstream / "src/vlnce_src"))
    results_root = options.output_dir / "upstream_results"
    results_root.mkdir()
    sys.argv = [str(options.upstream / "src/vlnce_src/eval_aerovla.py"),
                "--run_type", "eval", "--name", "ScriptedSimulatorProbe", "--batchSize", "1", "--maxWaypoints", "1",
                "--gpu_id", str(options.gpu_id), "--simulator_tool_port", str(options.simulator_port),
                "--dataset_path", "./dataset_raw/", "--eval_save_path", str(results_root),
                "--eval_json_path", str(options.episode_json),
                "--map_spawn_area_json_path", "./data/meta/map_spawnarea_info.json",
                "--object_name_json_path", "./data/meta/object_description.json"]
    runtime = env = None
    failure = None
    results = []
    started = time.monotonic_ns()
    old_alarm = signal.getsignal(signal.SIGALRM)
    def deadline(signum, frame):
        raise SystemExit(124)
    signal.signal(signal.SIGALRM, deadline)
    signal.setitimer(signal.ITIMER_REAL, options.max_wall_seconds)
    try:
        from src.common.param import args
        from src.vlnce_src.env_uav import AirVLNENV
        from airsim_plugin.AirVLNSimulatorClientTool_AeroVLA import AirVLNSimulatorClientTool
        from _vla_lab_runtime import Runtime
        from reset_protocol import install as install_reset_protocol
        env = AirVLNENV(batch_size=1, dataset_path="./dataset_raw/", save_path=str(results_root), eval_json_path=str(options.episode_json))
        if len(env.data) != 1:
            raise ValueError("Upstream loader did not resolve exactly one trajectory")
        runtime = Runtime(env, args, SimpleNamespace(model_path=None))
        runtime.rec.emit("probe.mode", mode=options.mode, model_loaded=False, resolved_config=resolved)
        runtime.patch(env, "next_minibatch", runtime.episode)
        runtime.patch(env, "makeActions", runtime.action)
        runtime.patch(AirVLNSimulatorClientTool, "run_call", runtime.scene_open)
        reset_helper = install_reset_protocol(env, runtime, protocol=options.reset_protocol)
        work = probes if options.mode == "controller" else [{"name": f"capture_reset_{i + 1}"} for i in range(options.capture_resets)]
        for probe in work:
            env.index_data = 0
            env.next_minibatch()
            runtime.rec.emit("probe.start", probe=probe)
            initial = latest_observation(env.reset())
            for port in env.simulator_tool.airsim_ports:
                actual_settings = json.loads((options.upstream / "airsim_plugin/settings" / str(port) / "settings.json").read_text())
                if actual_settings.get("ClockSpeed") != 10:
                    raise ValueError("Generated ClockSpeed differs from the recorded upstream reference of 10")
            camera_reset = reset_helper.acceptance(options.reset_position_tolerance_m, options.reset_angle_tolerance_rad)
            runtime.observe(initial)
            result = {"name": probe["name"], "attempt_id": runtime.attempt_id, "initial_state": initial["sensors"]["state"],
                      "initial_imu": initial["sensors"].get("imu"), "observation_shapes_verified": True}
            reset = reset_checks(initial["sensors"]["state"], env.batch[0]["trajectory"][0],
                                 options.reset_position_tolerance_m, options.reset_angle_tolerance_rad)
            result["reset_measurements"] = reset
            result["camera_reset_measurements"] = camera_reset
            if options.mode == "controller":
                before = time.monotonic_ns()
                env.makeActions([probe["action"]])
                final = latest_observation(env.get_obs())
                runtime.observe(final)
                result.update({"action": probe["action"], "final_state": final["sensors"]["state"],
                               "final_imu": final["sensors"].get("imu"), "execution_and_capture_ns": time.monotonic_ns() - before,
                               **movement_checks(initial["sensors"]["state"], final["sensors"]["state"], probe["action"], probe["tolerances"])})
                result["checks"]["no_endpoint_contact"] = final["sensors"]["state"].get("collision", {}).get("has_collided") is False
            else:
                result["checks"] = {"images_and_state_captured": True, "no_initial_endpoint_contact": initial["sensors"]["state"].get("collision", {}).get("has_collided") is False}
            result["checks"].update(reset["checks"])
            result["checks"].update(camera_reset["checks"])
            result["gate_passed"] = all(result["checks"].values())
            result["status"] = "completed"
            runtime.rec.emit("probe.completed", **result)
            runtime.rec.write_json(f"outcomes/{runtime.attempt_id}.json", result)
            runtime.attempt_complete = True
            results.append(result)
            atomic_json(options.output_dir / "results.json", {"status": "running", "results": results})
    except BaseException as exc:
        failure = exc
        traceback.print_exc()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_alarm)
        cleanup_exceptions = []
        for name, close in (("runtime", lambda: runtime.close(error=failure) if runtime is not None else None),
                            ("workers", lambda: env.delete_VectorEnvUtil() if env is not None else None)):
            try:
                close()
            except BaseException as exc:
                cleanup_exceptions.append(f"{name}: {type(exc).__name__}: {exc}")
                traceback.print_exc()
        cleanup_succeeded = False
        evidence_checks = {}
        event_path = options.output_dir / "evidence/events.jsonl"
        if event_path.exists():
            try:
                events = [json.loads(line) for line in event_path.read_text().splitlines() if line.strip()]
                endings = [event for event in events if event["event_type"] == "run.end"]
                cleanup_succeeded = bool(endings) and not endings[-1]["cleanup_errors"] and not cleanup_exceptions
                evidence_checks = log_checks(event_path.parent, events, options.mode, len(probes) if options.mode == "controller" else options.capture_resets)
            except Exception as exc:
                evidence_checks = {"readable_complete_log": False}
                cleanup_exceptions.append(f"Evidence validation: {type(exc).__name__}: {exc}")
        summary = {"schema_version": 1, "mode": options.mode, "reset_protocol": options.reset_protocol,
                   "status": "completed" if failure is None else "interrupted",
                   "model_loaded": False, "results": results, "wall_duration_ns": time.monotonic_ns() - started,
                   "cleanup_succeeded": cleanup_succeeded,
                   "cleanup_exceptions": cleanup_exceptions, "evidence_checks": evidence_checks,
                   "gate_passed": failure is None and bool(results) and all(result["gate_passed"] for result in results) and cleanup_succeeded and bool(evidence_checks) and all(evidence_checks.values()),
                   "error_type": type(failure).__name__ if failure else None, "error": str(failure) if failure else None}
        atomic_json(options.output_dir / "results.json", summary)
        atomic_json(options.output_dir / "checks.json", {"gate_passed": summary["gate_passed"], "evidence_checks": evidence_checks,
                    "probe_checks": {item["attempt_id"]: item["checks"] for item in results}, "cleanup_succeeded": cleanup_succeeded})
        lines = [f"# Simulator {options.mode} probe", "", f"Status: {summary['status']}",
                 f"Acceptance gate passed: {summary['gate_passed']}", f"Scene cleanup succeeded: {cleanup_succeeded}",
                 "", "No VLA model was loaded. These are genuine simulator observations/scripted controller checks.",
                 "Tolerances and scope were recorded in config.resolved.json before measurement.",
                 "The upstream ClockSpeed=10 and controller behavior were retained; timing includes synchronous recording.",
                 f"Reset protocol: {options.reset_protocol}. The paused-final-pose-v1 option is an explicit reset behavior change.",
                 "Reset acceptance includes actual captured-camera pose and post-capture paused ground truth, not only cached state.",
                 "Endpoint contact samples do not establish collision-free motion between observations.", ""]
        lines.extend(f"- {result['name']}: gate_passed={result['gate_passed']}; checks={json.dumps(result['checks'])}" for result in results)
        lines.extend(["", "Evidence checks: " + json.dumps(evidence_checks), "Cleanup exceptions: " + json.dumps(cleanup_exceptions)])
        if failure:
            lines.extend(["", f"Error: {type(failure).__name__}: {failure}"])
        (options.output_dir / "REPORT.md").write_text("\n".join(lines) + "\n")
    return 0 if summary["gate_passed"] else (124 if isinstance(failure, SystemExit) and failure.code == 124 else 1)


if __name__ == "__main__":
    raise SystemExit(main())
