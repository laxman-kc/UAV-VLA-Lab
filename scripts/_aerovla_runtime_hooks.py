"""Copied into a pinned upstream checkout by patch_aerovla_runtime.py.

Hooks return the original values and retain upstream policy/control decisions.
Recording is synchronous, so this is a separately named instrumented protocol.
Only a dedicated scene-manager port may be used: its cleanup RPC is global to
that manager. This module does not launch/kill the manager process itself.
"""
from __future__ import annotations

import functools
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import threading
import time
import uuid
from datetime import datetime, timezone


TIMED_RESET_PROTOCOL = "paused-final-pose-time-v1"
RESET_POSITION_TOLERANCE_M = 0.1
RESET_ANGLE_TOLERANCE_RAD = 0.05


def reset_configuration(patch_manifest, runtime_id):
    """Validate the opt-in before installing hooks or issuing simulator calls."""
    protocol = os.environ.get("VLA_LAB_RESET_PROTOCOL", "upstream")
    if protocol == "upstream":
        return {"name": "upstream", "helper_sha256": None, "module": None}
    if protocol != TIMED_RESET_PROTOCOL:
        raise ValueError(f"Unsupported evaluator reset protocol: {protocol!r}")
    # A new ID must explicitly name the behavior. Merely supplying the previous
    # upstream runtime ID would otherwise silently mix unlike reset protocols.
    if not isinstance(runtime_id, str) or protocol not in runtime_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", runtime_id):
        raise ValueError("Timed reset requires an explicit VLA_LAB_RUNTIME_ID containing " + protocol)
    if not isinstance(patch_manifest, dict) or patch_manifest.get("protocol") != "aerovla-e37685a-observed-v1":
        raise ValueError("Timed reset requires its recorded patch manifest")
    declared = patch_manifest.get("optional_reset_protocols", {}).get(protocol)
    if not isinstance(declared, dict) or declared.get("helper") != "_vla_lab_reset.py":
        raise ValueError("Patch manifest does not declare the timed reset helper")
    path = (Path.cwd() / "_vla_lab_reset.py").resolve()
    expected = patch_manifest.get("files", {}).get("_vla_lab_reset.py", {}).get("sha256")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected or actual != declared.get("sha256"):
        raise ValueError("Timed reset helper path or SHA256 differs from the patch manifest")
    import importlib
    module = importlib.import_module("_vla_lab_reset")
    if Path(module.__file__).resolve() != path:
        raise ValueError("Reset helper was imported from a different checkout")
    if getattr(module, "TIMED_PROTOCOL", None) != protocol:
        raise ValueError("Copied reset helper does not expose the declared protocol")
    return {"name": protocol, "helper_sha256": actual, "module": module}


def initial_reset_checks(outputs, reference):
    """P03 image/contact/cached-pose gates, without importing probe/SciPy code."""
    latest = outputs[0][0][-1]
    if len(latest["rgb"]) != 5 or len(latest["depth"]) != 5:
        raise ValueError("Upstream did not return five RGB and five depth views")
    for modality, expected in (("rgb", (256, 256, 3)), ("depth", (256, 256))):
        for image in latest[modality]:
            if tuple(image.shape) != expected:
                raise ValueError(f"Unexpected {modality} shape: {image.shape}")
    state = plain(latest["sensors"]["state"])
    reference = plain(reference)
    for pose in (state, reference):
        for key, size in (("position", 3), ("orientation", 4)):
            values = pose[key]
            if not isinstance(values, list) or len(values) != size or not all(
                    type(v) in (int, float) and math.isfinite(v) for v in values):
                raise ValueError("Reset pose must contain finite xyz and xyzw components")
    position_error = math.dist(state["position"], reference["position"])
    first, second = state["orientation"], reference["orientation"]
    norm = math.sqrt(sum(v * v for v in first) * sum(v * v for v in second))
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("Simulator or reference returned an invalid/zero quaternion")
    angle_error = 2 * math.acos(min(1.0, abs(sum(a * b for a, b in zip(first, second))) / norm))
    collision = state.get("collision")
    return {"initial_state": state, "initial_imu": plain(latest["sensors"].get("imu")),
            "reset_position_error_m": position_error, "reset_orientation_error_rad": angle_error,
            "checks": {"images_and_state_captured": True,
                       "no_initial_endpoint_contact": isinstance(collision, dict) and collision.get("has_collided") is False,
                       "reset_position_within_tolerance": position_error <= RESET_POSITION_TOLERANCE_M,
                       "reset_orientation_within_tolerance": angle_error <= RESET_ANGLE_TOLERANCE_RAD},
            "state_semantics": "Actual reset-return cached sensor state; not a new collision query. Zero setters do not establish zero velocity after timed physics continuation."}


def plain(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if hasattr(value, "tolist"):
        return plain(value.tolist())
    if hasattr(value, "to_msgpack"):
        return plain(value.to_msgpack())
    return repr(value)


def outcome_for(state, step):
    """Mirror the upstream displayed outcome precedence; expose all raw flags."""
    flags = {name: bool(getattr(state, name)[0]) for name in
             ("success", "oracle_success", "collisions", "early_end", "dones", "predict_dones")}
    reason = next((reason for flag, reason in
                   (("success", "success"), ("oracle_success", "oracle_success"),
                    ("collisions", "upstream_collision_flag"), ("early_end", "early_end"))
                   if flags[flag]), "step_limit_or_other_done")
    latest = state.episodes[0][-1]["sensors"]["state"]
    return {"status": "completed", "termination_reason": reason, "step": step,
            "upstream_flags": flags, "distance_to_target_m": state.distance_to_ends[0][-1],
            "endpoint_contact": latest.get("collision"), "endpoint_state_timestamp": latest.get("timestamp"),
            "contact_scope": "sampled endpoint; not continuous contact monitoring",
            "stuck_counter": state.stuck_counters[0],
            "interpretation": "Upstream success is a navigation criterion, not physical touchdown"}


class Recorder:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.stream = (self.root / "events.jsonl").open("x", buffering=1)
        self.lock = threading.Lock()
        self.serial = 0
        self.run_id = str(uuid.uuid4())
        self.context = {}
        self.event_serialization_write_ns = 0
        self.json_artifact_write_ns = 0
        self.json_artifact_count = 0

    def emit(self, kind, **data):
        with self.lock:
            started = time.monotonic_ns()
            self.serial += 1
            event = {"schema_version": 1, "run_id": self.run_id, "event_id": self.serial,
                     "event_type": kind, "host_monotonic_ns": time.monotonic_ns(),
                     "wall_time_utc": datetime.now(timezone.utc).isoformat(),
                     **self.context, **plain(data)}
            self.stream.write(json.dumps(event, allow_nan=False) + "\n")
            self.event_serialization_write_ns += time.monotonic_ns() - started
            return event["event_id"]

    def write_json(self, name, data):
        started = time.monotonic_ns()
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(plain(data), indent=2, allow_nan=False) + "\n")
        temporary.replace(target)
        self.json_artifact_write_ns += time.monotonic_ns() - started
        self.json_artifact_count += 1


class Runtime:
    def __init__(self, env, args, model_args):
        if env.batch_size != 1:
            raise ValueError("Initial integration supports batchSize=1 only")
        if os.environ.get("VLA_LAB_SCENE_MANAGER_EXCLUSIVE") != "1":
            raise ValueError("Start a dedicated scene manager and set VLA_LAB_SCENE_MANAGER_EXCLUSIVE=1")
        patch_manifest_path = Path("vla_lab_patch_manifest.json")
        patch_manifest = json.loads(patch_manifest_path.read_text()) if patch_manifest_path.exists() else None
        runtime_id = os.environ.get("VLA_LAB_RUNTIME_ID", "unrecorded")
        self.reset_config = reset_configuration(patch_manifest, runtime_id)
        self.reset_helper = None
        self.reset_accepted_attempt = None
        receipt_path = os.environ.get("VLA_LAB_RUNTIME_RECEIPT")
        runtime_receipt = None
        if receipt_path:
            receipt = Path(receipt_path)
            runtime_receipt = {"path": str(receipt.resolve()),
                               "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
                               "content": json.loads(receipt.read_text())}
        root = os.environ.get("VLA_LAB_EVENT_DIR", str(Path(args.eval_save_path) / "_vla_lab"))
        self.rec = Recorder(root)
        self.env, self.args = env, args
        self.observation_id = self.capture_id = self.policy_id = self.command_id = None
        self.attempt_id = None
        self.attempt_complete = False
        self.observation_count = 0
        self.scene_ports = []
        self.restore = []
        self.closed = False
        self.old_sigterm = signal.getsignal(signal.SIGTERM)
        def terminate(signum, frame):
            raise SystemExit(128 + signum)
        signal.signal(signal.SIGTERM, terminate)
        self.rec.emit("run.start", protocol="aerovla-e37685a-observed-v1", argv=__import__("sys").argv,
                      process_id=os.getpid(),
                      runtime_id=runtime_id, runtime_receipt=runtime_receipt,
                      reset_protocol=self.reset_config["name"], reset_helper_sha256=self.reset_config["helper_sha256"],
                      model_path=model_args.model_path, base_model_path="./openvla-7b",
                      batch_size=env.batch_size, episode_count=len(env.data), max_actions=args.maxWaypoints,
                      patch_manifest=patch_manifest,
                      timing_note=("Recording overhead is present; upstream pause/clock behavior is unchanged"
                                   if self.reset_config["name"] == "upstream" else
                                   "Recording overhead and opt-in timed reset/acceptance RPCs are present; ClockSpeed and controller are unchanged"))

    def patch(self, obj, name, hook):
        original = getattr(obj, name)
        @functools.wraps(original)
        def wrapped(*args, **kwargs):
            return hook(original, *args, **kwargs)
        setattr(obj, name, wrapped)
        self.restore.append((obj, name, original))

    def episode(self, original, *args, **kwargs):
        result = original(*args, **kwargs)
        if result:
            meta = result[0]
            self.attempt_id = str(uuid.uuid4())
            self.attempt_complete = False
            self.reset_accepted_attempt = None
            self.observation_id = self.capture_id = self.policy_id = self.command_id = None
            self.rec.context = {"episode_id": meta["seq_name"], "map_name": meta["map_name"], "attempt_id": self.attempt_id}
            self.rec.emit("episode.start", instruction=meta["instruction"], source_json=meta["merged_json"],
                          target_position=meta["object_position"], goal_source="upstream benchmark object_position",
                          initial_reference_state=meta["trajectory"][0])
        return result

    def observe(self, latest, prepare_start_ns=None):
        """Persist an actual upstream observation, also usable by model-free probes."""
        import cv2
        before = prepare_start_ns if prepare_start_ns is not None else time.monotonic_ns()
        self.observation_count += 1
        files = []
        folder = self.rec.root / "observations" / self.attempt_id / f"{self.observation_count:06d}"
        folder.mkdir(parents=True, exist_ok=True)
        image_write_hash_start_ns = time.monotonic_ns()
        for modality in ("rgb", "depth"):
            for index, name in enumerate(("front", "left", "right", "rear", "down")):
                path = folder / f"{name}_{modality}.png"
                if not cv2.imwrite(str(path), latest[modality][index]):
                    raise IOError(f"Could not write {path}")
                files.append({"path": str(path.relative_to(self.rec.root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                              "modality": modality, "camera": name})
        image_write_hash_end_ns = time.monotonic_ns()
        self.observation_id = self.rec.emit("observation.prepared", images=files, sensors=latest["sensors"],
                                           image_capture_event_id=self.capture_id,
                                           image_write_hash_start_ns=image_write_hash_start_ns,
                                           image_write_hash_end_ns=image_write_hash_end_ns,
                                           image_write_hash_ns=image_write_hash_end_ns - image_write_hash_start_ns,
                                           image_write_hash_scope="Ten synchronous PNG encodes/writes and readback SHA256 hashes; includes loop bookkeeping, excludes directory creation, model preprocessing and event serialization; no fsync durability claim",
                                           prepare_and_record_ns=time.monotonic_ns() - before,
                                           state_image_alignment="State is the upstream cached endpoint; image response timestamps are separate")
        return self.observation_id

    def prepare(self, original, model, *args, **kwargs):
        if self.reset_config["name"] != "upstream" and (
                self.attempt_id is None or self.reset_accepted_attempt != self.attempt_id):
            raise RuntimeError("Timed reset acceptance must pass for this attempt before model input preparation")
        before = time.monotonic_ns()
        result = original(model, *args, **kwargs)
        episodes = kwargs.get("episodes", args[0] if args else None)
        self.observe(episodes[0][-1], prepare_start_ns=before)
        inputs = result[0]
        self.rec.emit("prompt.prepared", observation_event_id=self.observation_id,
                      exact_prompt=model.tokenizer.batch_decode(inputs["input_ids"], skip_special_tokens=False),
                      pixel_tensor_shape=list(inputs["pixel_values"].shape),
                      hint_source="exact benchmark target position transformed by estimated pose")
        return result

    def install_optional_reset(self):
        """Called only after base observation/controller hooks are installed."""
        if self.reset_config["name"] == "upstream":
            return
        module = self.reset_config["module"]
        self.reset_helper = module.install(self.env, self, protocol=module.TIMED_PROTOCOL)
        if self.reset_helper.source_sha256 != self.reset_config["helper_sha256"]:
            raise ValueError("Installed reset helper identity differs from run.start")
        self.patch(self.env, "reset", self.accept_reset)

    def accept_reset(self, original, *args, **kwargs):
        """Reject a failed reset before its return can reach model preparation."""
        self.reset_accepted_attempt = None
        result = None
        acceptance = {"protocol": self.reset_config["name"], "source_sha256": self.reset_config["helper_sha256"],
                      "gate_passed": False, "position_tolerance_m": RESET_POSITION_TOLERANCE_M,
                      "orientation_tolerance_rad": RESET_ANGLE_TOLERANCE_RAD}
        error = None
        try:
            result = original(*args, **kwargs)
            if self.attempt_id is None:
                raise ValueError("Reset has no recorded episode attempt")
            acceptance["camera_reset_measurements"] = self.reset_helper.acceptance(
                RESET_POSITION_TOLERANCE_M, RESET_ANGLE_TOLERANCE_RAD)
            acceptance["cached_reset_measurements"] = initial_reset_checks(result, self.env.batch[0]["trajectory"][0])
            camera_checks = acceptance["camera_reset_measurements"]["checks"]
            if not camera_checks or not all(type(v) is bool for v in camera_checks.values()):
                raise ValueError("Reset helper returned missing or nonboolean acceptance checks")
            acceptance["checks"] = {**camera_checks, **acceptance["cached_reset_measurements"]["checks"]}
            ports = self.env.simulator_tool.airsim_ports
            if len(ports) != 1:
                raise ValueError("Expected exactly one scene settings file")
            settings_bytes = (Path("airsim_plugin/settings") / str(ports[0]) / "settings.json").read_bytes()
            settings = json.loads(settings_bytes)
            acceptance["checks"]["upstream_clock_speed_10"] = settings.get("ClockSpeed") == 10
            acceptance["checks"]["settings_unchanged_since_camera_acceptance"] = (
                hashlib.sha256(settings_bytes).hexdigest() == acceptance["camera_reset_measurements"].get("settings_sha256"))
            acceptance["gate_passed"] = all(acceptance["checks"].values())
            if not acceptance["gate_passed"]:
                failed = [key for key, passed in acceptance["checks"].items() if not passed]
                raise RuntimeError("Timed reset acceptance failed: " + ", ".join(failed))
            self.reset_accepted_attempt = self.attempt_id
        except BaseException as exc:
            error = exc
            acceptance.update(error_type=type(exc).__name__, error=str(exc))
            raise
        finally:
            acceptance.update(status="accepted" if error is None else "rejected",
                              reset_ordinal=self.reset_helper.reset_ordinal)
            event_id = self.rec.emit("reset_protocol.evaluator_acceptance", **acceptance)
            self.rec.write_json(f"reset_acceptance/{self.attempt_id or 'no-attempt'}-{self.reset_helper.reset_ordinal}.json",
                                {**self.rec.context, **acceptance, "event_id": event_id})
        return result

    def model_init(self, original, model, *args, **kwargs):
        result = original(model, *args, **kwargs)
        def generate(call, *inputs, **settings):
            start = time.monotonic_ns()
            result = call(*inputs, **settings)
            generation_end = time.monotonic_ns()
            token_ids = result.detach().cpu().tolist()
            self.policy_id = self.rec.emit("policy.generated", observation_event_id=self.observation_id,
                                          token_ids=token_ids,
                                          raw_text=model.tokenizer.batch_decode(token_ids, skip_special_tokens=False),
                                          inference_start_ns=start, inference_return_ns=generation_end,
                                          token_copy_end_ns=time.monotonic_ns())
            return result
        self.patch(model.model, "generate", generate)
        return result

    def action(self, original, *args, **kwargs):
        action_list = kwargs.get("actions_list", args[0] if args else None)
        self.command_id = self.rec.emit("action.requested", observation_event_id=self.observation_id,
                                       policy_event_id=self.policy_id, actions=action_list,
                                       units={"fwd": "metres", "down": "metres", "yaw": "radians"})
        start = time.monotonic_ns()
        result = original(*args, **kwargs)
        self.rec.emit("action.completed", command_event_id=self.command_id, execution_start_ns=start,
                      execution_end_ns=time.monotonic_ns(), endpoint_states=result,
                      sampling_note="Upstream returns five copies of one endpoint state/IMU per action")
        return result

    def policy_run(self, original, model, *args, **kwargs):
        result = original(model, *args, **kwargs)
        self.rec.emit("policy.decoded", observation_event_id=self.observation_id,
                      policy_event_id=self.policy_id, upstream_actions=result[0], upstream_stop_flags=result[1],
                      semantics="Unmodified upstream parser, including malformed-output-to-zero fallback")
        return result

    def scene_open(self, original, tool, *args, **kwargs):
        result = original(tool, *args, **kwargs)
        self.scene_ports = list(tool.airsim_ports)
        settings = []
        for port in self.scene_ports:
            path = Path("airsim_plugin/settings") / str(port) / "settings.json"
            settings.append({"port": port, "path": str(path.resolve()),
                             "content": json.loads(path.read_text()) if path.exists() else None,
                             "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None})
        self.rec.emit("scene.connected", scene_ports=self.scene_ports, machines=tool.machines_info, generated_settings=settings)
        for machine in tool.airsim_clients:
            for client in machine:
                if client is None:
                    continue
                for name in ("enableApiControl", "armDisarm", "simPause", "rotateToYawAsync", "moveByVelocityAsync", "moveToZAsync",
                             "simSetKinematics", "simContinueForFrames", "simSpawnObject", "simDestroyObject"):
                    def record_call(call, *args, _method=name, **kwargs):
                        start = time.monotonic_ns()
                        event_id = self.rec.emit("controller.call", command_event_id=self.command_id, method=_method, args=args, kwargs=kwargs)
                        result = call(*args, **kwargs)
                        self.rec.emit("controller.call_returned", controller_event_id=event_id, dispatch_start_ns=start,
                                      dispatch_end_ns=time.monotonic_ns(),
                                      object_spawn_result=result if _method == "simSpawnObject" else None,
                                      object_spawn_returned_name=bool(result) if _method == "simSpawnObject" else None,
                                      completion_scope="RPC return; asynchronous future is joined by unchanged upstream executor")
                        return result
                    self.patch(client, name, record_call)
                def capture(call, *args, **kwargs):
                    start = time.monotonic_ns()
                    result = call(*args, **kwargs)
                    self.capture_id = self.rec.emit("images.received", command_event_id=self.command_id,
                        capture_start_ns=start, capture_return_ns=time.monotonic_ns(),
                        responses=[{key: plain(getattr(item, key, None)) for key in
                                    ("time_stamp", "width", "height", "image_type", "camera_position", "camera_orientation", "message")} for item in result])
                    return result
                self.patch(client, "simGetImages", capture)
                def collision_response(call, *args, **kwargs):
                    start = time.monotonic_ns()
                    result = call(*args, **kwargs)
                    self.rec.emit("collision.response", command_event_id=self.command_id,
                                  call_start_ns=start, call_return_ns=time.monotonic_ns(),
                                  response=plain(result),
                                  semantics="Existing upstream query only; event/latch semantics depend on compiled server. No extra collision query was added.")
                    return result
                self.patch(client, "simGetCollisionInfo", collision_response)
        return result

    def monitor(self, original, state, step):
        result = original(state, step)
        if state.skips[0] and not self.attempt_complete:
            outcome = {**self.rec.context, **outcome_for(state, step)}
            self.rec.emit("episode.completed", **outcome)
            self.rec.write_json(f"outcomes/{self.attempt_id}.json", outcome)
            self.attempt_complete = True
        return result

    def close(self, error=None):
        if self.closed:
            return
        self.closed = True
        cleanup_errors = []
        try:
            if self.attempt_id and not self.attempt_complete:
                partial = {**self.rec.context, "status": "interrupted", "error_type": type(error).__name__ if error else None,
                           "error": str(error) if error else "Run ended before an upstream terminal outcome"}
                self.rec.emit("episode.interrupted", **partial)
                self.rec.write_json(f"partial/{self.attempt_id}.json", partial)
            tool = getattr(self.env, "simulator_tool", None)
            if tool is not None:
                try:
                    tool._closeConnection()
                except Exception as exc:
                    cleanup_errors.append(f"AirSim connections: {exc}")
                for machine in tool.machines_info:
                    rpc = None
                    try:
                        import msgpackrpc
                        rpc = msgpackrpc.Client(msgpackrpc.Address(machine["MACHINE_IP"], machine["SOCKET_PORT"]), timeout=20)
                        ok = rpc.call("close_scenes", machine["MACHINE_IP"])
                        if ok is not True:
                            raise RuntimeError(f"Scene cleanup returned {ok!r}")
                        self.rec.emit("cleanup.scenes_closed", manager=machine, scene_ports=self.scene_ports)
                    except Exception as exc:
                        cleanup_errors.append(f"Scene manager {machine}: {exc}")
                    finally:
                        if rpc is not None:
                            try:
                                rpc.close()
                            except Exception as exc:
                                cleanup_errors.append(f"Cleanup RPC connection: {exc}")
            run_status = "completed" if error is None and self.attempt_complete else "interrupted"
            if cleanup_errors:
                run_status = "cleanup_failed"
            self.rec.emit("run.end", status=run_status,
                          error_type=type(error).__name__ if error else None, error=str(error) if error else None,
                          cleanup_errors=cleanup_errors,
                          recording_measurements={
                              "event_count_before_run_end": self.rec.serial,
                              "event_serialization_write_ns_before_run_end": self.rec.event_serialization_write_ns,
                              "json_artifact_count_before_run_end": self.rec.json_artifact_count,
                              "json_artifact_write_ns_before_run_end": self.rec.json_artifact_write_ns,
                              "scope": "Cumulative host intervals for event envelope/serialization/line-buffered write, and separate JSON artifact serialization/write/rename. Excludes run.end itself, lock wait, final flush/fsync, image encoding/hashing, simulator RPC time and preprocessing; not all instrumentation overhead."})
            if cleanup_errors:
                print("VLA cleanup requires supervisor attention:", cleanup_errors, flush=True)
        finally:
            for obj, name, original in reversed(self.restore):
                setattr(obj, name, original)
            signal.signal(signal.SIGTERM, self.old_sigterm)
            self.rec.stream.flush()
            os.fsync(self.rec.stream.fileno())
            self.rec.stream.close()


def install(env, args, model_args):
    from src.model_wrapper.aerovla_wrapper_ui import AerialVLAWrapper
    from src.vlnce_src.closeloop_util import EvalBatchState
    from airsim_plugin.AirVLNSimulatorClientTool_AeroVLA import AirVLNSimulatorClientTool
    runtime = Runtime(env, args, model_args)
    try:
        runtime.patch(env, "next_minibatch", runtime.episode)
        runtime.patch(env, "makeActions", runtime.action)
        runtime.patch(AerialVLAWrapper, "__init__", runtime.model_init)
        runtime.patch(AerialVLAWrapper, "prepare_inputs", runtime.prepare)
        runtime.patch(AerialVLAWrapper, "run", runtime.policy_run)
        runtime.patch(AirVLNSimulatorClientTool, "run_call", runtime.scene_open)
        runtime.patch(EvalBatchState, "check_batch_termination", runtime.monitor)
        runtime.install_optional_reset()
    except BaseException as exc:
        runtime.close(error=exc)
        raise
    return runtime
