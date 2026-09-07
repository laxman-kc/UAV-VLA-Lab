#!/usr/bin/env python3
"""One fresh-scene reset diagnostic; no policy, controller action or claimed fix.

Run separately under run_simulation_session.py for each variant. Additional
readbacks are sequential and perturb timing; pose is argument-equivalent to the
upstream setter, not a timing-equivalent baseline. No collision query is added.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import signal
import sys
import time
import traceback
from types import SimpleNamespace

from simulator_probe import atomic_json, latest_observation, reset_checks, sha


VARIANTS = ("pose", "full-zero", "reset-full-zero")


def plain(value):
    """Keep API field names, including quaternion xyzw names; no reordering."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"nonfinite_float": repr(value)}
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if hasattr(value, "to_msgpack"):
        return plain(value.to_msgpack())
    if hasattr(value, "tolist"):
        return plain(value.tolist())
    raise TypeError(f"Unsupported API response type: {type(value).__name__}")


def zero_kinematics(airsim, pose):
    """Explicit complete state; do not depend on omitted RPC field defaults."""
    state = airsim.KinematicsState()
    state.position = airsim.Vector3r(pose.position.x_val, pose.position.y_val, pose.position.z_val)
    state.orientation = airsim.Quaternionr(pose.orientation.x_val, pose.orientation.y_val,
                                          pose.orientation.z_val, pose.orientation.w_val)
    for field in ("linear_velocity", "angular_velocity", "linear_acceleration", "angular_acceleration"):
        setattr(state, field, airsim.Vector3r(0.0, 0.0, 0.0))
    return state


def pose_error(state, reference):
    if not isinstance(state, dict) or not all(key in state for key in ("position", "orientation")):
        return None
    try:
        p, q = state["position"], state["orientation"]
        actual = {"position": [p[f"{axis}_val"] for axis in "xyz"],
                  "orientation": [q[f"{axis}_val"] for axis in "xyzw"]}
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for values in actual.values() for v in values):
            return None
        return reset_checks(actual, reference, 0.1, 0.05)
    except (KeyError, TypeError, ValueError):
        return None


class Diagnostic:
    def __init__(self, runtime, airsim, variant, reference):
        self.runtime, self.airsim, self.variant, self.reference = runtime, airsim, variant, reference
        self.snapshots = []
        self.read_errors = []
        self.set_calls = self.frame_calls = self.api_resets = self.collision_responses = 0
        self.clients = 0

    def snapshot(self, client, label):
        """Read APIs in a fixed order; each has its own actual acquisition bounds."""
        queries = [
            ("pause_before", "simIsPause", {}),
            ("ground_truth", "simGetGroundTruthKinematics", {"vehicle_name": ""}),
            ("estimated_state", "getMultirotorState", {"vehicle_name": ""}),
            ("vehicle_pose", "simGetVehiclePose", {"vehicle_name": ""}),
            ("imu", "getImuData", {"imu_name": "", "vehicle_name": ""}),
            ("api_control_enabled", "isApiControlEnabled", {"vehicle_name": ""}),
            ("pause_after", "simIsPause", {}),
        ]
        snapshot = {"label": label, "sequence": len(self.snapshots) + 1,
                    "acquisition_start_ns": time.monotonic_ns(), "queries": {}}
        for name, method, kwargs in queries:
            query = {"method": method, "kwargs": kwargs, "call_start_ns": time.monotonic_ns()}
            try:
                query["response"] = plain(getattr(client, method)(**kwargs))
            except Exception as exc:
                query["error"] = {"type": type(exc).__name__, "message": str(exc)}
                self.read_errors.append({"label": label, "method": method, **query["error"]})
            query["call_return_ns"] = time.monotonic_ns()
            snapshot["queries"][name] = query
        snapshot["acquisition_end_ns"] = time.monotonic_ns()
        snapshot["pose_comparisons"] = {}
        for name in ("ground_truth", "estimated_state", "vehicle_pose"):
            response = snapshot["queries"][name].get("response")
            if name == "estimated_state" and isinstance(response, dict):
                response = response.get("kinematics_estimated")
            snapshot["pose_comparisons"][name] = pose_error(response, self.reference)
        self.snapshots.append(snapshot)
        self.runtime.rec.emit("diagnostic.snapshot", **snapshot)
        return snapshot

    def install(self, client):
        self.clients += 1
        if self.clients != 1:
            raise ValueError("Diagnostic requires exactly one newly connected simulator client")
        self.snapshot(client, "scene_connected")

        def set_kinematics(call, *args, **kwargs):
            if args or set(kwargs) != {"state", "ignore_collision"} or kwargs["ignore_collision"] is not True:
                raise ValueError("Pinned upstream setter signature changed; do not infer a new protocol")
            self.set_calls += 1
            label = f"set_{self.set_calls}"
            self.snapshot(client, label + ".before")
            if self.variant == "reset-full-zero" and self.api_resets == 0:
                self.runtime.rec.emit("diagnostic.api_reset_requested", scope="Once before first setter; no rearm or takeoff")
                start = time.monotonic_ns()
                result = client.reset()
                self.api_resets += 1
                self.runtime.rec.emit("diagnostic.api_reset_returned", call_start_ns=start,
                                      call_return_ns=time.monotonic_ns(), response=plain(result))
                self.snapshot(client, "api_reset.after")
            applied = dict(kwargs)
            if self.variant != "pose":
                applied["state"] = zero_kinematics(self.airsim, kwargs["state"])
            self.runtime.rec.emit("diagnostic.kinematics_requested", ordinal=self.set_calls,
                                  variant=self.variant, original_kwargs=plain(kwargs), applied_kwargs=plain(applied))
            result = call(**applied)
            self.snapshot(client, label + ".after")
            return result

        self.runtime.patch(client, "simSetKinematics", set_kinematics)
        for name in ("simContinueForFrames", "simPause", "simSpawnObject", "simGetImages"):
            def around(call, *args, _name=name, **kwargs):
                if _name == "simContinueForFrames":
                    self.frame_calls += 1
                    if args != (1,) or kwargs:
                        raise ValueError("Pinned upstream one-frame protocol changed")
                label = f"{_name}_{self.frame_calls}"
                self.snapshot(client, label + ".before")
                start = time.monotonic_ns()
                result = call(*args, **kwargs)
                self.runtime.rec.emit("diagnostic.rpc_returned", method=_name, args=plain(args), kwargs=plain(kwargs),
                                      call_start_ns=start, call_return_ns=time.monotonic_ns())
                self.snapshot(client, label + ".after")
                return result
            self.runtime.patch(client, name, around)

        def collision(call, *args, **kwargs):
            start = time.monotonic_ns()
            result = call(*args, **kwargs)
            self.collision_responses += 1
            self.runtime.rec.emit("diagnostic.existing_collision_response", call_start_ns=start,
                                  call_return_ns=time.monotonic_ns(), response=plain(result),
                                  scope="Existing upstream call only; no extra collision query or latch clear")
            return result
        self.runtime.patch(client, "simGetCollisionInfo", collision)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("upstream", "episode-json", "dataset-root", "output-dir"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--variant", choices=VARIANTS, required=True)
    p.add_argument("--simulator-port", type=int, default=30000)
    p.add_argument("--gpu-id", type=int, default=0)
    p.add_argument("--scene-manager-exclusive", action="store_true", required=True)
    p.add_argument("--max-wall-seconds", type=float, default=180)
    return p


def main(argv=None):
    options = parser().parse_args(argv)
    if (not 1024 <= options.simulator_port <= 64535 or options.gpu_id < 0 or
            not math.isfinite(options.max_wall_seconds) or options.max_wall_seconds <= 0):
        raise ValueError("Invalid port, GPU or wall-time bound")
    for key in ("upstream", "episode_json", "dataset_root", "output_dir"):
        setattr(options, key, getattr(options, key).resolve())
    if (options.upstream / "dataset_raw").resolve() != options.dataset_root:
        raise ValueError("Upstream dataset_raw must resolve to the explicit dataset root")
    manifest_path = options.upstream / "vla_lab_patch_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for relative, info in manifest["files"].items():
        if sha(options.upstream / relative) != info.get("patched_sha256", info.get("sha256")):
            raise ValueError(f"Integration source hash mismatch: {relative}")
    rows = json.loads(options.episode_json.read_text())
    if not rows or len({row["json"] for row in rows}) != 1:
        raise ValueError("Use a genuine one-episode selection")
    options.output_dir.mkdir(parents=True, exist_ok=False)
    config = {"schema_version": "vla.reset-diagnostic.v1", "variant": options.variant,
              "source_sha256": sha(__file__), "episode_json_sha256": sha(options.episode_json),
              "patch_manifest_sha256": sha(manifest_path), "expected_clock_speed": 10,
              "one_fresh_scene_per_invocation": True, "model_loaded": False,
              "max_wall_seconds": options.max_wall_seconds, "simulator_port": options.simulator_port,
              "dataset_root": str(options.dataset_root), "upstream": str(options.upstream),
              "interpretation": "Diagnostic only. Added sequential readbacks perturb unpaused dynamics. No reset fix or navigation claim.",
              "pose_thresholds_for_comparison_only": {"position_m": 0.1, "orientation_rad": 0.05},
              "collision_query_policy": "Wrap existing upstream response only; add none",
              "snapshot_atomicity": "None; per-API monotonic intervals and returned simulator timestamps retained",
              "vehicle_name": "", "vehicle_semantics": "Same API default vehicle as unchanged upstream setter"}
    atomic_json(options.output_dir / "config.resolved.json", config)
    os.environ.update(CUDA_VISIBLE_DEVICES=str(options.gpu_id), VLA_LAB_SCENE_MANAGER_EXCLUSIVE="1",
                      VLA_LAB_EVENT_DIR=str(options.output_dir / "evidence"))
    os.chdir(options.upstream)
    sys.path[:0] = [str(options.upstream), str(options.upstream / "src/vlnce_src")]
    result_root = options.output_dir / "upstream_results"
    result_root.mkdir()
    sys.argv = [str(options.upstream / "src/vlnce_src/eval_aerovla.py"), "--run_type", "eval",
                "--name", "ResetDiagnostic", "--batchSize", "1", "--maxWaypoints", "1",
                "--gpu_id", str(options.gpu_id), "--simulator_tool_port", str(options.simulator_port),
                "--dataset_path", "./dataset_raw/", "--eval_save_path", str(result_root),
                "--eval_json_path", str(options.episode_json),
                "--map_spawn_area_json_path", "./data/meta/map_spawnarea_info.json",
                "--object_name_json_path", "./data/meta/object_description.json"]
    env = runtime = diagnostic = None
    failure = None
    cleanup_errors = []
    final = None
    started = time.monotonic_ns()
    old_alarm = signal.getsignal(signal.SIGALRM)
    def deadline(signum, frame):
        raise SystemExit(124)
    signal.signal(signal.SIGALRM, deadline)
    signal.setitimer(signal.ITIMER_REAL, options.max_wall_seconds)
    try:
        import airsim
        from src.common.param import args
        from src.vlnce_src.env_uav import AirVLNENV
        from airsim_plugin.AirVLNSimulatorClientTool_AeroVLA import AirVLNSimulatorClientTool
        from _vla_lab_runtime import Runtime
        env = AirVLNENV(batch_size=1, dataset_path="./dataset_raw/", save_path=str(result_root),
                        eval_json_path=str(options.episode_json))
        if len(env.data) != 1:
            raise ValueError("Loader did not resolve exactly one trajectory")
        runtime = Runtime(env, args, SimpleNamespace(model_path=None))
        runtime.patch(env, "next_minibatch", runtime.episode)
        env.next_minibatch()
        diagnostic = Diagnostic(runtime, airsim, options.variant, env.batch[0]["trajectory"][0])
        runtime.rec.emit("diagnostic.start", config=config)
        def scene_open(original, tool, *args, **kwargs):
            result = runtime.scene_open(original, tool, *args, **kwargs)
            for machine in tool.airsim_clients:
                for client in machine:
                    if client is not None:
                        diagnostic.install(client)
            return result
        runtime.patch(AirVLNSimulatorClientTool, "run_call", scene_open)
        observed = latest_observation(env.reset())
        runtime.observe(observed)
        for port in env.simulator_tool.airsim_ports:
            settings = json.loads((options.upstream / "airsim_plugin/settings" / str(port) / "settings.json").read_text())
            if settings.get("ClockSpeed") != 10:
                raise ValueError("ClockSpeed changed from recorded upstream protocol")
        final = {"cached_observation_sensors": plain(observed["sensors"]),
                 "cached_state_comparison": reset_checks(observed["sensors"]["state"], diagnostic.reference, 0.1, 0.05)}
        runtime.attempt_complete = True
        runtime.rec.emit("diagnostic.completed", **final)
    except BaseException as exc:
        failure = exc
        traceback.print_exc()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_alarm)
        for name, close in (("runtime", lambda: runtime.close(error=failure) if runtime else None),
                            ("workers", lambda: env.delete_VectorEnvUtil() if env else None)):
            try:
                close()
            except BaseException as exc:
                cleanup_errors.append(f"{name}: {type(exc).__name__}: {exc}")
        endings = []
        events = options.output_dir / "evidence/events.jsonl"
        if events.exists():
            endings = [json.loads(line) for line in events.read_text().splitlines()
                       if line.strip() and json.loads(line).get("event_type") == "run.end"]
        cleanup_ok = bool(endings) and not endings[-1]["cleanup_errors"] and not cleanup_errors
        protocol_ok = (diagnostic is not None and diagnostic.clients == 1 and diagnostic.set_calls == 3 and
                       diagnostic.frame_calls == 4 and diagnostic.collision_responses == 1 and
                       diagnostic.api_resets == (1 if options.variant == "reset-full-zero" else 0))
        complete = failure is None and final is not None and protocol_ok and not diagnostic.read_errors and cleanup_ok
        result = {**config, "status": "completed" if failure is None else "interrupted",
                  "diagnostic_capture_complete": complete, "reset_gate_passed": None,
                  "final_observation": final, "snapshots": diagnostic.snapshots if diagnostic else [],
                  "read_errors": diagnostic.read_errors if diagnostic else [],
                  "set_calls": diagnostic.set_calls if diagnostic else 0,
                  "frame_calls": diagnostic.frame_calls if diagnostic else 0,
                  "api_resets": diagnostic.api_resets if diagnostic else 0,
                  "existing_collision_responses": diagnostic.collision_responses if diagnostic else 0,
                  "cleanup_succeeded": cleanup_ok, "cleanup_errors": cleanup_errors,
                  "wall_duration_ns": time.monotonic_ns() - started,
                  "error": {"type": type(failure).__name__, "message": str(failure)} if failure else None}
        atomic_json(options.output_dir / "report.json", result)
        print(json.dumps({k: result[k] for k in ("variant", "status", "diagnostic_capture_complete", "set_calls",
                                               "frame_calls", "api_resets", "cleanup_succeeded", "error")}), flush=True)
    if isinstance(failure, SystemExit) and isinstance(failure.code, int):
        return failure.code
    if isinstance(failure, KeyboardInterrupt):
        return 130
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
