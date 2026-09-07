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
import os
from pathlib import Path
import signal
import threading
import time
import uuid
from datetime import datetime, timezone


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

    def emit(self, kind, **data):
        with self.lock:
            self.serial += 1
            event = {"schema_version": 1, "run_id": self.run_id, "event_id": self.serial,
                     "event_type": kind, "host_monotonic_ns": time.monotonic_ns(),
                     "wall_time_utc": datetime.now(timezone.utc).isoformat(),
                     **self.context, **plain(data)}
            self.stream.write(json.dumps(event, allow_nan=False) + "\n")
            return event["event_id"]

    def write_json(self, name, data):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(plain(data), indent=2, allow_nan=False) + "\n")
        temporary.replace(target)


class Runtime:
    def __init__(self, env, args, model_args):
        if env.batch_size != 1:
            raise ValueError("Initial integration supports batchSize=1 only")
        if os.environ.get("VLA_LAB_SCENE_MANAGER_EXCLUSIVE") != "1":
            raise ValueError("Start a dedicated scene manager and set VLA_LAB_SCENE_MANAGER_EXCLUSIVE=1")
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
        patch_manifest = Path("vla_lab_patch_manifest.json")
        self.rec.emit("run.start", protocol="aerovla-e37685a-observed-v1", argv=__import__("sys").argv,
                      model_path=model_args.model_path, base_model_path="./openvla-7b",
                      batch_size=env.batch_size, episode_count=len(env.data), max_actions=args.maxWaypoints,
                      patch_manifest=json.loads(patch_manifest.read_text()) if patch_manifest.exists() else None,
                      timing_note="Recording overhead is present; upstream pause/clock behavior is unchanged")

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
        for modality in ("rgb", "depth"):
            for index, name in enumerate(("front", "left", "right", "rear", "down")):
                path = folder / f"{name}_{modality}.png"
                if not cv2.imwrite(str(path), latest[modality][index]):
                    raise IOError(f"Could not write {path}")
                files.append({"path": str(path.relative_to(self.rec.root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                              "modality": modality, "camera": name})
        self.observation_id = self.rec.emit("observation.prepared", images=files, sensors=latest["sensors"],
                                           image_capture_event_id=self.capture_id,
                                           prepare_and_record_ns=time.monotonic_ns() - before,
                                           state_image_alignment="State is the upstream cached endpoint; image response timestamps are separate")
        return self.observation_id

    def prepare(self, original, model, *args, **kwargs):
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
                          cleanup_errors=cleanup_errors)
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
    runtime.patch(env, "next_minibatch", runtime.episode)
    runtime.patch(env, "makeActions", runtime.action)
    runtime.patch(AerialVLAWrapper, "__init__", runtime.model_init)
    runtime.patch(AerialVLAWrapper, "prepare_inputs", runtime.prepare)
    runtime.patch(AerialVLAWrapper, "run", runtime.policy_run)
    runtime.patch(AirVLNSimulatorClientTool, "run_call", runtime.scene_open)
    runtime.patch(EvalBatchState, "check_batch_termination", runtime.monitor)
    return runtime
