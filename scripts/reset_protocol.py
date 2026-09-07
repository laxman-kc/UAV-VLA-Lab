"""Opt-in paused final-pose candidate and captured-camera reset acceptance.

This changes reset behavior only when explicitly selected. It does not change
the upstream controller, policy, target construction or ClockSpeed. A passing
local unit test is not evidence that the candidate works in the simulator.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import time

PROTOCOL = "paused-final-pose-v1"
TIMED_PROTOCOL = "paused-final-pose-time-v1"
TIMED_CONTINUATION_SECONDS = 0.001


def plain(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if hasattr(value, "to_msgpack"):
        return plain(value.to_msgpack())
    if hasattr(value, "tolist"):
        return plain(value.tolist())
    raise TypeError(f"Unsupported API response type: {type(value).__name__}")


def coords(value, axes):
    result = [value[f"{axis}_val"] for axis in axes]
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in result):
        raise ValueError("Pose contains a missing or nonfinite component")
    return result


def angle_error(first, second):
    norm = math.sqrt(sum(v * v for v in first) * sum(v * v for v in second))
    if not norm:
        raise ValueError("Pose contains a zero quaternion")
    return 2 * math.acos(min(1.0, abs(sum(a * b for a, b in zip(first, second))) / norm))


def state_errors(raw, reference):
    return {"position_error_m": math.dist(coords(raw["position"], "xyz"), reference["position"]),
            "orientation_error_rad": angle_error(coords(raw["orientation"], "xyzw"), reference["orientation"])}


def full_zero(airsim, reference):
    state = airsim.KinematicsState()
    state.position = airsim.Vector3r(*reference["position"])
    state.orientation = airsim.Quaternionr(*reference["orientation"])
    for key in ("linear_velocity", "angular_velocity", "linear_acceleration", "angular_acceleration"):
        setattr(state, key, airsim.Vector3r(0.0, 0.0, 0.0))
    return state


class ResetProtocol:
    def __init__(self, env, runtime, protocol, airsim):
        if protocol not in ("upstream", PROTOCOL, TIMED_PROTOCOL) or env.batch_size != 1:
            raise ValueError("Choose upstream or the explicit single-episode candidate")
        self.env, self.runtime, self.protocol, self.airsim = env, runtime, protocol, airsim
        self.last_capture = None
        self.clients_wrapped = set()
        self.reset_ordinal = 0
        self.source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

    def client(self):
        clients = [c for machine in self.env.simulator_tool.airsim_clients for c in machine if c is not None]
        if len(clients) != 1:
            raise ValueError("Reset protocol requires exactly one simulator client")
        return clients[0]

    def call(self, client, method, **kwargs):
        start = time.monotonic_ns()
        event = self.runtime.rec.emit("reset_protocol.call", protocol=self.protocol, method=method,
                                      kwargs=plain(kwargs), reset_ordinal=self.reset_ordinal)
        result = getattr(client, method)(**kwargs)
        self.runtime.rec.emit("reset_protocol.call_returned", protocol=self.protocol, method=method,
                              request_event_id=event, call_start_ns=start, call_return_ns=time.monotonic_ns(),
                              response=plain(result))
        return result

    def watch_capture(self, client):
        if id(client) in self.clients_wrapped:
            return
        self.clients_wrapped.add(id(client))
        def capture(call, *args, **kwargs):
            requests = kwargs.get("requests", args[0] if args else None)
            if requests is None:
                raise ValueError("Image capture did not expose its actual requests")
            start = time.monotonic_ns()
            result = call(*args, **kwargs)
            returned = time.monotonic_ns()
            metadata = [{key: plain(getattr(item, key, None)) for key in
                         ("time_stamp", "image_type", "width", "height", "camera_position", "camera_orientation", "message")}
                        for item in result]
            request_metadata = [{key: plain(getattr(item, key, None)) for key in
                                 ("camera_name", "image_type", "pixels_as_float", "compress")} for item in requests]
            self.last_capture = {"requests": request_metadata, "responses": metadata,
                                 "call_start_ns": start, "call_return_ns": returned,
                                 "reset_ordinal": self.reset_ordinal, "attempt_id": self.runtime.attempt_id}
            self.last_capture["event_id"] = self.runtime.rec.emit("reset_protocol.image_capture", **self.last_capture)
            return result
        self.runtime.patch(client, "simGetImages", capture)

    def after_original_reset(self, original, *args, **kwargs):
        self.reset_ordinal += 1
        self.last_capture = None
        result = original(*args, **kwargs)
        client = self.client()
        self.watch_capture(client)
        if self.protocol == "upstream":
            return result
        reference = self.env.batch[0]["trajectory"][0]
        self.runtime.rec.emit("reset_protocol.begin", protocol=self.protocol, source_sha256=self.source_sha256,
                              reset_ordinal=self.reset_ordinal, reference=reference,
                              stage="After original trajectory reset, target spawn and measurement update; before get_obs",
                              added_collision_queries=1, api_reset_added=False,
                              frame_advance_added=self.protocol == TIMED_PROTOCOL,
                              requested_continuation_seconds=TIMED_CONTINUATION_SECONDS if self.protocol == TIMED_PROTOCOL else 0,
                              collision_semantics="The required fresh getSensorInfo adds one collision-latch query; its raw returned event is retained. No separate clearing query is issued.")
        self.call(client, "simPause", is_paused=True)
        if self.call(client, "simIsPause") is not True:
            raise RuntimeError("Simulator did not report paused before final pose application")
        state = full_zero(self.airsim, reference)
        pose = self.airsim.Pose(position_val=state.position, orientation_val=state.orientation)
        self.call(client, "simSetKinematics", state=state, ignore_collision=True, vehicle_name="")
        self.call(client, "simSetVehiclePose", pose=pose, ignore_collision=True, vehicle_name="")
        if self.call(client, "simIsPause") is not True:
            raise RuntimeError("Simulator did not remain paused after final pose application")
        if self.protocol == TIMED_PROTOCOL:
            # Pending render state requires a world tick. Time-based continuation
            # bounds requested physics time independently of the render frame;
            # actual API timestamps/poses remain the acceptance evidence.
            before = self.call(client, "getMultirotorState", vehicle_name="")
            self.call(client, "simContinueForTime", seconds=TIMED_CONTINUATION_SECONDS)
            if self.call(client, "simIsPause") is not True:
                raise RuntimeError("Timed reset continuation did not return to pause")
            after = self.call(client, "getMultirotorState", vehicle_name="")
            self.runtime.rec.emit("reset_protocol.timed_continuation", protocol=self.protocol,
                                  requested_seconds=TIMED_CONTINUATION_SECONDS,
                                  before_state=plain(before), after_state=plain(after),
                                  interpretation="One requested time continuation; actual elapsed simulator time may exceed its request. No exact tick count is assumed.")
        # Preserve the exact existing sensor envelope; do not synthesize state.
        started = time.monotonic_ns()
        refreshed = self.env.simulator_tool.getSensorInfo()
        if len(refreshed) != 1 or len(refreshed[0]) != 1 or "sensors" not in refreshed[0][0]:
            raise ValueError("Unexpected one-client sensor response")
        self.env.sim_states[0].trajectory = [copy.deepcopy(refreshed[0][0])]
        self.env.update_measurements()
        self.runtime.rec.emit("reset_protocol.sensor_refresh", protocol=self.protocol,
                              call_start_ns=started, call_return_ns=time.monotonic_ns(),
                              response=refreshed[0][0], added_collision_queries=1,
                              cache_replaced=True, frame_advance_added=self.protocol == TIMED_PROTOCOL)
        return result

    def acceptance(self, position_tolerance=0.1, angle_tolerance=0.05):
        """Check actual camera responses and post-capture GT; no collision query."""
        capture = self.last_capture
        if capture is None or capture["attempt_id"] != self.runtime.attempt_id or capture["reset_ordinal"] != self.reset_ordinal:
            raise ValueError("No actual image capture is linked to this reset attempt")
        client = self.client()
        pause_before = self.call(client, "simIsPause")
        ground_truth = plain(self.call(client, "simGetGroundTruthKinematics", vehicle_name=""))
        vehicle_pose = plain(self.call(client, "simGetVehiclePose", vehicle_name=""))
        pause_after = self.call(client, "simIsPause")
        ports = self.env.simulator_tool.airsim_ports
        if len(ports) != 1:
            raise ValueError("Expected exactly one scene settings file")
        path = Path("airsim_plugin/settings") / str(ports[0]) / "settings.json"
        settings = json.loads(path.read_text())
        vehicles = settings["Vehicles"]
        if len(vehicles) != 1:
            raise ValueError("Default-vehicle extrinsics require exactly one configured vehicle")
        cameras = next(iter(vehicles.values()))["Cameras"]
        # Use only comparisons whose camera extrinsics are exact in the actual
        # settings. If these change, fail rather than assume an Euler convention.
        extrinsics_ok = (all(cameras["FrontCamera"].get(k) == 0 for k in ("Roll", "Pitch", "Yaw")) and
                         all(cameras["DownCamera"].get(k) == 0 for k in ("X", "Y", "Z")))
        reference = self.env.batch[0]["trajectory"][0]
        gt_errors, pose_errors = state_errors(ground_truth, reference), state_errors(vehicle_pose, reference)
        requests, responses = capture["requests"], capture["responses"]
        expected = {(camera, modality) for camera in ("FrontCamera", "LeftCamera", "RightCamera", "RearCamera", "DownCamera")
                    for modality in (0, 2)}
        request_keys = [(r["camera_name"], r["image_type"]) for r in requests]
        mapping_ok = (len(responses) == len(requests) == 10 and len(set(request_keys)) == 10 and
                      set(request_keys) == expected and all(req["image_type"] == response["image_type"]
                                                         for req, response in zip(requests, responses)))
        checks = {"camera_extrinsics_verified": extrinsics_ok, "camera_request_response_mapping_verified": mapping_ok,
                  "paused_before_and_after_groundtruth_readback": pause_before is True and pause_after is True,
                  "groundtruth_position_within_tolerance": gt_errors["position_error_m"] <= position_tolerance,
                  "groundtruth_orientation_within_tolerance": gt_errors["orientation_error_rad"] <= angle_tolerance,
                  "vehicle_pose_position_within_tolerance": pose_errors["position_error_m"] <= position_tolerance,
                  "vehicle_pose_orientation_within_tolerance": pose_errors["orientation_error_rad"] <= angle_tolerance}
        comparisons = []
        if mapping_ok and extrinsics_ok:
            for request, response in zip(requests, responses):
                name = request["camera_name"]
                if name not in ("FrontCamera", "DownCamera"):
                    continue
                item = {"camera": name, "image_type": request["image_type"], "timestamp": response["time_stamp"]}
                if name == "FrontCamera":
                    actual = coords(response["camera_orientation"], "xyzw")
                    item["orientation_error_rad"] = angle_error(actual, reference["orientation"])
                    item["groundtruth_orientation_difference_rad"] = angle_error(actual, coords(ground_truth["orientation"], "xyzw"))
                    passed = item["orientation_error_rad"] <= angle_tolerance and item["groundtruth_orientation_difference_rad"] <= angle_tolerance
                else:
                    actual = coords(response["camera_position"], "xyz")
                    item["position_error_m"] = math.dist(actual, reference["position"])
                    item["groundtruth_position_difference_m"] = math.dist(actual, coords(ground_truth["position"], "xyz"))
                    passed = item["position_error_m"] <= position_tolerance and item["groundtruth_position_difference_m"] <= position_tolerance
                checks[f"{name}_{request['image_type']}_captured_pose_within_tolerance"] = passed
                comparisons.append(item)
        else:
            checks["captured_camera_pose_checks_available"] = False
        result = {"protocol": self.protocol, "source_sha256": self.source_sha256,
                  "capture_event_id": capture["event_id"], "capture": capture,
                  "settings_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                  "verified_extrinsics": {"front": cameras["FrontCamera"], "down": cameras["DownCamera"]},
                  "ground_truth": ground_truth, "vehicle_pose": vehicle_pose,
                  "groundtruth_errors": gt_errors, "vehicle_pose_errors": pose_errors,
                  "camera_comparisons": comparisons, "checks": checks,
                  "position_tolerance_m": position_tolerance, "orientation_tolerance_rad": angle_tolerance,
                  "alignment_note": "Camera response timestamps are actual. Ground truth is a separate post-capture paused readback; pause checks do not make API acquisitions atomic."}
        self.runtime.rec.emit("reset_protocol.acceptance", **result)
        return result


def install(env, runtime, protocol=PROTOCOL, airsim=None):
    if airsim is None:
        import airsim
    helper = ResetProtocol(env, runtime, protocol, airsim)
    runtime.patch(env, "changeToNewTrajectorys", helper.after_original_reset)
    runtime.rec.emit("reset_protocol.installed", protocol=protocol, source_sha256=helper.source_sha256,
                     candidate_behavior_change=protocol != "upstream",
                     interpretation="Opt-in reset candidate; actual captured-camera and ground-truth gates determine acceptance")
    return helper
