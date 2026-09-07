#!/usr/bin/env python3
"""Join navigation validation with independently checked timed-reset evidence.

Read-only inputs; writes a fresh analysis directory. No simulator, model or
holdout loading. A reset pass never creates a navigation outcome.
"""
import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import statistics

NATIVE_DEPENDENCY_SHA256 = {'navigation.py': '2a3a32012125f0f73f8b708a422cf3caea37755a9fe150ac94c4c90e6bfcf0c6', 'context.py': '74e0c1694764765ed370b129dbb86295d7c353250dc42298990e90bde95e90d2'}

PROTOCOL = "paused-final-pose-time-v1"
POSITION_TOLERANCE = 0.1
ANGLE_TOLERANCE = 0.05
CAMERA_CHECKS = {
    "camera_extrinsics_verified", "camera_request_response_mapping_verified",
    "paused_before_and_after_groundtruth_readback", "groundtruth_position_within_tolerance",
    "groundtruth_orientation_within_tolerance", "vehicle_pose_position_within_tolerance",
    "vehicle_pose_orientation_within_tolerance", "FrontCamera_0_captured_pose_within_tolerance",
    "FrontCamera_2_captured_pose_within_tolerance", "DownCamera_0_captured_pose_within_tolerance",
    "DownCamera_2_captured_pose_within_tolerance",
}
CACHE_CHECKS = {"images_and_state_captured", "no_initial_endpoint_contact",
                "reset_position_within_tolerance", "reset_orientation_within_tolerance"}
ALL_CHECKS = CAMERA_CHECKS | CACHE_CHECKS | {
    "upstream_clock_speed_10", "settings_unchanged_since_camera_acceptance"}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    def invalid(value):
        raise ValueError("Non-finite JSON number: " + value)
    return json.loads(Path(path).read_text(), parse_constant=invalid)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def vector(value, count):
    if not isinstance(value, list) or len(value) != count or not all(finite(x) for x in value):
        raise ValueError(f"Expected {count} finite vector components")
    return value


def coords(value, axes):
    return vector([value[k + "_val"] for k in axes], len(axes))


def angle(first, second):
    first, second = vector(first, 4), vector(second, 4)
    norm = math.sqrt(sum(x*x for x in first) * sum(x*x for x in second))
    if norm == 0:
        raise ValueError("Zero quaternion")
    return 2 * math.acos(min(1.0, abs(sum(x*y for x, y in zip(first, second))) / norm))


def pose_errors(raw, reference, structured=True):
    position = coords(raw["position"], "xyz") if structured else vector(raw["position"], 3)
    orientation = coords(raw["orientation"], "xyzw") if structured else vector(raw["orientation"], 4)
    return {"position_error_m": math.dist(position, vector(reference["position"], 3)),
            "orientation_error_rad": angle(orientation, reference["orientation"])}


def required_true(values, expected, label, errors):
    if not isinstance(values, dict) or set(values) != expected or any(value is not True for value in values.values()):
        errors.append(label + " is missing, nonboolean, false, or has an unexpected key set")


def matches_numbers(actual, expected, label, errors):
    # Python 3.12 changed float sum accuracy; acos near zero amplifies one-ulp
    # differences between the recorded Python 3.10 host and newer reviewers.
    # This is an equality allowance, never a relaxation of the 0.05-rad gate.
    if not isinstance(actual, dict) or any(not finite(actual.get(k)) or not math.isclose(actual[k], v, rel_tol=1e-8, abs_tol=1e-7 if k.endswith("rad") else 1e-9)
                                           for k, v in expected.items()):
        errors.append(label + " disagrees with independently recomputed values")


def audit_run(run, installed, plan, receipt, receipt_sha, helper_sha, hook_sha):
    errors = []
    config = plan["configuration"]
    for key in ("protocol", "runtime_id", "model_path", "max_actions", "reset_protocol", "reset_helper_sha256"):
        if run.get(key) != config.get(key):
            errors.append("run.start " + key + " differs from frozen plan")
    expected_receipt = plan.get("source_plan", {}).get("runtime_receipt_sha256", plan.get("runtime_receipt_sha256"))
    if not expected_receipt or receipt_sha != expected_receipt:
        errors.append("Runtime receipt bytes do not match the frozen plan hash")
    recorded = run.get("runtime_receipt", {})
    if recorded.get("sha256") != receipt_sha or recorded.get("content") != receipt:
        errors.append("Recorded runtime receipt hash/content differs from supplied actual receipt")
    if receipt.get("runtime_id") != config.get("runtime_id") or receipt.get("reset_protocol") != PROTOCOL:
        errors.append("Runtime receipt identity differs from frozen plan")
    if config.get("reset_protocol") != PROTOCOL or config.get("reset_helper_sha256") != helper_sha:
        errors.append("Supplied helper source differs from frozen reset configuration")
    manifest = run.get("patch_manifest") or {}
    optional = (manifest.get("optional_reset_protocols") or {}).get(PROTOCOL, {})
    if (optional.get("helper") != "_vla_lab_reset.py" or optional.get("sha256") != helper_sha or
            optional.get("acceptance_before_model_preparation") is not True):
        errors.append("Patch manifest does not bind the selected helper and pre-input acceptance guard")
    if (manifest.get("files", {}).get("_vla_lab_runtime.py", {}).get("sha256") != hook_sha or
            receipt.get("code", {}).get("_aerovla_runtime_hooks.py", {}).get("sha256") != hook_sha):
        errors.append("Supplied runtime-hook source differs from recorded manifest/receipt")
    if (manifest.get("files", {}).get("_vla_lab_reset.py", {}).get("sha256") != helper_sha or
            receipt.get("code", {}).get("reset_protocol.py", {}).get("sha256") != helper_sha):
        errors.append("Helper identity differs across manifest and receipt")
    if len(installed) != 1 or installed[0].get("source_sha256") != helper_sha or installed[0].get("protocol") != PROTOCOL:
        errors.append("Expected exactly one installation of the declared reset helper")
    if run.get("batch_size") != 1:
        errors.append("Only recorded batch size one is supported")
    return errors


def audit_attempt(events, start, settings, settings_sha, payload, helper_sha):
    """Validate raw evidence, including numerical checks; preserve rejects as rejects."""
    errors = []
    types = collections.defaultdict(list)
    for event in events:
        types[event.get("event_type")].append(event)
    acceptances = types["reset_protocol.evaluator_acceptance"]
    observations = types["observation.prepared"]
    inputs = [event for event in events if event.get("event_type") in
              {"observation.prepared", "prompt.prepared", "policy.generated"}]
    result = {"attempt_id": start.get("attempt_id"), "start_event_id": start.get("event_id"),
              "reset_acceptance_events": len(acceptances), "first_input_event_id": min((e["event_id"] for e in inputs), default=None),
              "accepted_reset_evidence": False, "errors": errors}
    if len(acceptances) != 1:
        errors.append("Expected exactly one evaluator reset-acceptance event for this attempt")
        result["status"] = "missing_or_multiple_reset_records"
        return result
    accepted = acceptances[0]
    result.update(reset_acceptance_event_id=accepted.get("event_id"), reset_ordinal=accepted.get("reset_ordinal"),
                  recorded_status=accepted.get("status"), recorded_gate_passed=accepted.get("gate_passed"))
    if accepted.get("status") != "accepted" or accepted.get("gate_passed") is not True:
        errors.append("Recorded reset was rejected or did not pass")
        result["status"] = "reset_rejected"
        return result
    try:
        for event in events:
            if any(event.get(key) != start.get(key) for key in ("attempt_id", "run_id", "episode_id", "map_name")):
                errors.append("Event context differs from its episode start")
                break
        if accepted.get("protocol") != PROTOCOL or accepted.get("source_sha256") != helper_sha:
            errors.append("Acceptance protocol/helper identity mismatch")
        if accepted.get("position_tolerance_m") != POSITION_TOLERANCE or accepted.get("orientation_tolerance_rad") != ANGLE_TOLERANCE:
            errors.append("Evaluator pose tolerances differ from the inspected contract")
        if not isinstance(payload, dict) or payload != {k: accepted.get(k) for k in payload}:
            errors.append("Separate reset-acceptance payload differs from the event or is unavailable")
        mandatory_payload = {"attempt_id", "episode_id", "map_name", "protocol", "source_sha256", "gate_passed",
                             "status", "event_id", "reset_ordinal", "checks", "camera_reset_measurements", "cached_reset_measurements"}
        if not isinstance(payload, dict) or not mandatory_payload.issubset(payload):
            errors.append("Separate reset-acceptance payload is incomplete")
        if accepted["event_id"] <= start["event_id"] or (inputs and accepted["event_id"] >= min(e["event_id"] for e in inputs)):
            errors.append("Accepted reset is not strictly before every first recorded model input")
        if inputs and (not finite(accepted.get("host_monotonic_ns")) or
                       any(not finite(e.get("host_monotonic_ns")) or accepted["host_monotonic_ns"] >= e["host_monotonic_ns"] for e in inputs)):
            errors.append("Acceptance host timestamp is not before recorded model input")
        for name in ("reset_protocol.begin", "reset_protocol.timed_continuation", "reset_protocol.sensor_refresh", "reset_protocol.acceptance"):
            if len(types[name]) != 1 or not start["event_id"] < types[name][0]["event_id"] < accepted["event_id"]:
                errors.append("Expected one ordered " + name + " before acceptance")
        if len(types["reset_protocol.begin"]) == 1:
            begin = types["reset_protocol.begin"][0]
            if (begin.get("protocol") != PROTOCOL or begin.get("source_sha256") != helper_sha or
                    begin.get("reset_ordinal") != accepted.get("reset_ordinal")):
                errors.append("Reset begin does not match accepted helper/protocol/ordinal")
        required_true(accepted.get("checks"), ALL_CHECKS, "Combined evaluator checks", errors)
        camera, cached = accepted["camera_reset_measurements"], accepted["cached_reset_measurements"]
        required_true(camera.get("checks"), CAMERA_CHECKS, "Camera/ground-truth checks", errors)
        required_true(cached.get("checks"), CACHE_CHECKS, "Cached state checks", errors)
        if camera.get("settings_sha256") != settings_sha or settings.get("ClockSpeed") != 10:
            errors.append("Saved settings hash or ClockSpeed disagrees with acceptance")
        if camera.get("source_sha256") != helper_sha or camera.get("protocol") != PROTOCOL:
            errors.append("Camera acceptance helper/protocol mismatch")
        if camera.get("position_tolerance_m") != POSITION_TOLERANCE or camera.get("orientation_tolerance_rad") != ANGLE_TOLERANCE:
            errors.append("Camera acceptance tolerance mismatch")
        vehicles = settings.get("Vehicles", {})
        if len(vehicles) != 1:
            raise ValueError("Expected one configured vehicle")
        cameras = next(iter(vehicles.values()))["Cameras"]
        if (any(cameras["FrontCamera"].get(k) != 0 for k in ("Roll", "Pitch", "Yaw")) or
                any(cameras["DownCamera"].get(k) != 0 for k in ("X", "Y", "Z")) or
                camera.get("verified_extrinsics") != {"front": cameras["FrontCamera"], "down": cameras["DownCamera"]}):
            errors.append("Actual saved camera extrinsics differ from accepted comparisons")
        reference = start["initial_reference_state"]
        for name, raw in (("groundtruth_errors", camera["ground_truth"]), ("vehicle_pose_errors", camera["vehicle_pose"])):
            calculated = pose_errors(raw, reference)
            matches_numbers(camera.get(name), calculated, name, errors)
            if calculated["position_error_m"] > POSITION_TOLERANCE or calculated["orientation_error_rad"] > ANGLE_TOLERANCE:
                errors.append(name + " exceeds declared pose tolerance")
        calculated = pose_errors(cached["initial_state"], reference, structured=False)
        matches_numbers(cached, {"reset_position_error_m": calculated["position_error_m"],
                                "reset_orientation_error_rad": calculated["orientation_error_rad"]}, "Cached pose errors", errors)
        if calculated["position_error_m"] > POSITION_TOLERANCE or calculated["orientation_error_rad"] > ANGLE_TOLERANCE:
            errors.append("Cached initial pose exceeds declared tolerance")
        if cached["initial_state"].get("collision", {}).get("has_collided") is not False:
            errors.append("Cached reset initial contact was not false")
        if observations and cached["initial_state"] != observations[0].get("sensors", {}).get("state"):
            errors.append("Accepted cached state differs from first model observation")
        helper_events = types["reset_protocol.acceptance"]
        if len(helper_events) == 1 and camera != {k: helper_events[0].get(k) for k in camera}:
            errors.append("Embedded camera acceptance differs from helper event")
        capture = camera["capture"]
        capture_event = next((e for e in types["reset_protocol.image_capture"] if e.get("event_id") == camera.get("capture_event_id")), None)
        if (capture_event is None or capture != {k: capture_event.get(k) for k in capture} or
                capture.get("attempt_id") != start.get("attempt_id") or capture.get("reset_ordinal") != accepted.get("reset_ordinal")):
            errors.append("Camera capture is not bound to this attempt/reset")
        if observations:
            original_capture = next((e for e in types["images.received"] if e["event_id"] == observations[0].get("image_capture_event_id")), None)
            if original_capture is None or original_capture.get("responses") != capture.get("responses"):
                errors.append("First model images do not point to the accepted camera batch")
        # Independently bind the paused readback bracket to raw RPC return events.
        helper_accept_id = helper_events[0]["event_id"] if len(helper_events) == 1 else accepted["event_id"]
        bracket = [e for e in types["reset_protocol.call_returned"]
                   if camera["capture_event_id"] < e["event_id"] < helper_accept_id]
        expected_methods = ["simIsPause", "simGetGroundTruthKinematics", "simGetVehiclePose", "simIsPause"]
        expected_responses = [True, camera["ground_truth"], camera["vehicle_pose"], True]
        if [e.get("method") for e in bracket] != expected_methods:
            errors.append("Raw paused ground-truth/vehicle readback bracket is incomplete or reordered")
        else:
            for response, expected_response in zip(bracket, expected_responses):
                request = next((e for e in types["reset_protocol.call"] if e["event_id"] == response.get("request_event_id")), None)
                if (response.get("response") != expected_response or
                        (expected_response is True and response.get("response") is not True) or
                        request is None or request.get("method") != response["method"] or
                        not camera["capture_event_id"] < request["event_id"] < response["event_id"] or
                        not finite(response.get("call_start_ns")) or not finite(response.get("call_return_ns")) or
                        response["call_return_ns"] < response["call_start_ns"]):
                    errors.append("Raw acceptance RPC does not substantiate its readback payload")
        requests, responses = capture["requests"], capture["responses"]
        expected = {(c, m) for c in ("FrontCamera", "LeftCamera", "RightCamera", "RearCamera", "DownCamera") for m in (0, 2)}
        keys = [(r["camera_name"], r["image_type"]) for r in requests]
        if len(requests) != 10 or len(responses) != 10 or len(set(keys)) != 10 or set(keys) != expected:
            raise ValueError("Incomplete or duplicate camera request/response mapping")
        comparisons = {}
        for request, response in zip(requests, responses):
            if request["image_type"] != response["image_type"] or response.get("width") != 256 or response.get("height") != 256:
                errors.append("Camera modality/dimensions differ from the inspected input contract")
            name = request["camera_name"]
            if name == "FrontCamera":
                actual = coords(response["camera_orientation"], "xyzw")
                values = {"orientation_error_rad": angle(actual, reference["orientation"]),
                          "groundtruth_orientation_difference_rad": angle(actual, coords(camera["ground_truth"]["orientation"], "xyzw"))}
                limit = ANGLE_TOLERANCE
            elif name == "DownCamera":
                actual = coords(response["camera_position"], "xyz")
                values = {"position_error_m": math.dist(actual, reference["position"]),
                          "groundtruth_position_difference_m": math.dist(actual, coords(camera["ground_truth"]["position"], "xyz"))}
                limit = POSITION_TOLERANCE
            else:
                continue
            key = (name, request["image_type"])
            if any(value > limit for value in values.values()):
                errors.append(str(key) + " camera pose exceeds tolerance")
            matching = [v for v in camera["camera_comparisons"] if (v.get("camera"), v.get("image_type")) == key]
            if len(matching) != 1 or matching[0].get("timestamp") != response.get("time_stamp"):
                errors.append("Missing, duplicate or mis-timestamped camera comparison " + str(key))
            else:
                matches_numbers(matching[0], values, str(key), errors)
            comparisons[str(key)] = values
        if len(camera.get("camera_comparisons", [])) != 4:
            errors.append("Expected exactly four front/down RGB/depth comparisons")
        if types["reset_protocol.timed_continuation"]:
            continuation = types["reset_protocol.timed_continuation"][0]
            if continuation.get("requested_seconds") != 0.001:
                errors.append("Timed continuation request differs from declared helper")
            result["requested_continuation_seconds"] = continuation.get("requested_seconds")
            timestamps = [continuation[k]["timestamp"] for k in ("before_state", "after_state")]
            if any(type(value) is not int or value < 0 for value in timestamps) or timestamps[1] < timestamps[0]:
                raise ValueError("Invalid timed-continuation simulator timestamps")
            result["recorded_simulator_delta_seconds"] = (continuation["after_state"]["timestamp"] - continuation["before_state"]["timestamp"]) / 1e9
        result["recomputed_camera_errors"] = comparisons
        result["actual_ground_truth_velocity"] = camera["ground_truth"].get("linear_velocity")
        result["actual_ground_truth_angular_velocity"] = camera["ground_truth"].get("angular_velocity")
        result["settings_sha256"] = settings_sha
    except (KeyError, TypeError, ValueError, StopIteration, OverflowError) as exc:
        errors.append("Malformed or incomplete reset evidence: " + str(exc))
    result["accepted_reset_evidence"] = not errors
    result["status"] = "accepted_reset_verified" if not errors else "reset_evidence_invalid"
    return result


def remap(value, mappings):
    path = Path(value)
    for remote, local in sorted(mappings, key=lambda pair: len(pair[0].parts), reverse=True):
        if path.is_relative_to(remote):
            return (local / path.relative_to(remote)).resolve()
    return path.resolve()


def stats(values):
    accepted = [value for value in values if finite(value) and value >= 0]
    return {"recorded_count": len(values), "valid_count": len(accepted),
            "missing_or_invalid_count": len(values) - len(accepted),
            "min": min(accepted) if accepted else None, "max": max(accepted) if accepted else None,
            "mean": statistics.mean(accepted) if accepted else None,
            "median": statistics.median(accepted) if accepted else None,
            "sum": sum(accepted) if accepted else None}


def proportion(successes, denominator):
    if not denominator:
        return {"numerator": successes, "denominator": denominator, "value": None, "wilson_95": None}
    z = 1.959963984540054
    p = successes / denominator
    center = (p + z*z / (2*denominator)) / (1 + z*z / denominator)
    margin = z * math.sqrt(p*(1-p)/denominator + z*z/(4*denominator**2)) / (1 + z*z/denominator)
    return {"numerator": successes, "denominator": denominator, "value": p,
            "wilson_95": [max(0., center-margin), min(1., center+margin)]}


def combine_trials(plan, attempts):
    """One observed attempt is the cap: invalid attempts never authorize replacements."""
    if plan["retry_policy"]["max_attempts_per_trial"] != 1:
        raise ValueError("This baseline analysis requires a frozen one-observed-attempt cap")
    trial_rows = []
    for trial in plan["trials"]:
        rows = sorted([row for row in attempts if row.get("trial_id") == trial["trial_id"] and
                       row.get("navigation_attempt_observed") is True],
                      key=lambda row: (row["session_order"], row["start_event_id"]))
        selected = rows[0] if rows and rows[0].get("joint_valid") is True else None
        result = {**trial, "observed_attempts": len(rows), "attempts_beyond_cap": max(0, len(rows)-1),
                  "joint_valid_attempts": sum(row.get("joint_valid") is True for row in rows),
                  "selected_attempt_id": selected["attempt_id"] if selected else None,
                  "selected_session_id": selected["session_id"] if selected else None,
                  "status": "scored_valid_trial" if selected else ("unscored_observed_trial" if rows else "unstarted_trial"),
                  "upstream_success": None, "upstream_osr_success": None, "upstream_collision_flag": None,
                  "any_recorded_endpoint_contact": None, "terminal_endpoint_contact": None,
                  "terminal_loop_index": None, "distance_to_spawned_target_m": None, "termination_reason": None,
                  "attempt_audit_statuses": [row["joint_status"] for row in rows]}
        if selected:
            outcome = selected["raw_outcome"]
            flags = outcome["upstream_flags"]
            result.update(upstream_success=flags["success"], upstream_osr_success=flags["success"] or flags["oracle_success"],
                          upstream_collision_flag=flags["collisions"], terminal_loop_index=outcome["step"],
                          distance_to_spawned_target_m=outcome["distance_to_target_m"],
                          termination_reason=outcome["termination_reason"],
                          any_recorded_endpoint_contact=selected.get("contact", {}).get("any_recorded_endpoint_contact"),
                          terminal_endpoint_contact=selected.get("contact", {}).get("terminal_contact"))
        trial_rows.append(result)
    return trial_rows


def video_selection(trials, attempts, session_events, evidence_roots):
    selected_ids = {(row["selected_session_id"], row["selected_attempt_id"]) for row in trials if row["selected_attempt_id"]}
    ordered = sorted([row for row in attempts if (row["session_id"], row["attempt_id"]) in selected_ids],
                     key=lambda row: (row["session_order"], row["start_event_id"]))
    choices = []
    for category, success in (("first_valid_success", True), ("first_valid_non_success", False)):
        chosen = next((row for row in ordered if row["raw_outcome"]["upstream_flags"]["success"] is success), None)
        entry = {"category": category, "status": "selected" if chosen else "category_absent", "attempt_id": None}
        if chosen:
            events = [e for e in session_events[chosen["session_id"]] if e.get("attempt_id") == chosen["raw_attempt_id"] and
                      e.get("event_type") == "observation.prepared"]
            indices = sorted(set((0, (len(events)-1)//2, len(events)-1))) if events else []
            entry.update(attempt_id=chosen["attempt_id"], session_id=chosen["session_id"], trial_id=chosen["trial_id"],
                         total_recorded_observations=len(events), observations=[])
            for index in indices:
                event = events[index]
                images = [{**v, "local_path": str((evidence_roots[chosen["session_id"]] / v["path"]).resolve())}
                          for v in event.get("images", []) if v.get("camera") in {"front", "down"} and v.get("modality") == "rgb"]
                entry["observations"].append({"ordinal_one_based": index+1, "event_id": event["event_id"],
                                               "wall_time_utc": event.get("wall_time_utc"),
                                               "sensor_timestamp": event.get("sensors", {}).get("state", {}).get("timestamp"),
                                               "images": images})
        choices.append(entry)
    return {"rule": "All planned-trial rows; first valid success and non-success in execution order; first/middle/final observations",
            "middle_definition": "Zero-based floor((recorded observation count - 1)/2); duplicate indices shown only once",
            "playback": "Editorial static holds of sampled observations, not real-time or continuous flight footage",
            "all_trial_table": trials, "categories": choices}


class Sources:
    def __init__(self, mappings):
        self.mappings = mappings
        self.records = {}

    def record(self, path, expected=None):
        path = Path(path).resolve()
        record = {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
        if expected and any(record[key] != expected.get(key) for key in ("bytes", "sha256")):
            raise ValueError("Source hash/size mismatch: " + str(path))
        if str(path) in self.records and record != self.records[str(path)]:
            raise ValueError("Source changed during analysis: " + str(path))
        self.records[str(path)] = record
        return record

    def json(self, path, expected=None):
        self.record(path, expected)
        return read_json(path)

    def events(self, path, expected=None):
        self.record(path, expected)
        result = []
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                raise ValueError("Empty event line: " + str(path))
            value = json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            if not isinstance(value, dict):
                raise ValueError("Non-object event in " + str(path))
            result.append(value)
        return result


def duration(event, start, end):
    first, last = event.get(start), event.get(end)
    return (last-first)/1e9 if finite(first) and finite(last) and last >= first else None


def session_measurements(session, events, sources, mappings):
    supervisor = session.get("supervisor_report") or {}
    simulation = session.get("simulation_session_report") or {}
    result = {"session_id": session["session_id"], "command_elapsed_seconds": supervisor.get("command_elapsed_seconds"),
              "supervisor_status": supervisor.get("status"), "child_returncode": supervisor.get("child_returncode"),
              "supervisor_termination_reason": supervisor.get("termination_reason"),
              "command_group_exists_at_end": supervisor.get("process_group_exists_at_end"),
              "session_status": simulation.get("status"), "session_returncode": simulation.get("session_returncode"),
              "generate_host_call_return_seconds": stats([duration(e, "inference_start_ns", "inference_return_ns") for e in events if e.get("event_type") == "policy.generated"]),
              "token_copy_host_seconds": stats([duration(e, "inference_return_ns", "token_copy_end_ns") for e in events if e.get("event_type") == "policy.generated"]),
              "action_execution_host_seconds": stats([duration(e, "execution_start_ns", "execution_end_ns") for e in events if e.get("event_type") == "action.completed"]),
              "image_write_hash_host_seconds": stats([e.get("image_write_hash_ns") / 1e9 if finite(e.get("image_write_hash_ns")) else None for e in events if e.get("event_type") == "observation.prepared"]),
              "recording_measurements": [e.get("recording_measurements") for e in events if e.get("event_type") == "run.end"],
              "gpu_sampling": {"status": "unavailable", "scope": "Sampled host-wide totals, not per-process or continuous peak"}}
    monitor_record = supervisor.get("events")
    if monitor_record:
        try:
            monitors = sources.events(remap(monitor_record["path"], mappings), monitor_record)
            samples = [e for e in monitors if e.get("event") == "monitor.sampled"]
            devices = collections.defaultdict(list)
            for sample in samples:
                for device in (sample.get("gpu") or {}).get("devices", []):
                    try:
                        value = float(device.get("memory_used_mib"))
                        if not math.isfinite(value) or value < 0:
                            continue
                    except (TypeError, ValueError):
                        continue
                    devices[str(device.get("index"))].append(value)
            result["gpu_sampling"].update(status="recorded" if devices else "unavailable", monitor_samples=len(samples),
                                          devices=[{"index": index, "memory_used_mib": stats(values)} for index, values in devices.items()])
        except (OSError, ValueError) as exc:
            result["gpu_sampling"]["error"] = str(exc)
    return result


def analyze(args):
    for dependency, expected in NATIVE_DEPENDENCY_SHA256.items():
        if sha256(Path(__file__).with_name(dependency)) != expected:
            raise ValueError("Native analyzer dependency differs from hash-bound source: " + dependency)
    from . import navigation as nav
    mappings = []
    for value in args.path_map:
        if "=" not in value:
            raise ValueError("--path-map must be REMOTE_PREFIX=LOCAL_PREFIX")
        remote, local = value.split("=", 1)
        if not Path(remote).is_absolute() or not Path(local).is_absolute():
            raise ValueError("Both path-map prefixes must be absolute")
        mappings.append((Path(remote), Path(local)))
    sources = Sources(mappings)
    plan = sources.json(args.plan)
    nav.validate_plan(plan)
    if plan["retry_policy"]["max_attempts_per_trial"] != 1:
        raise ValueError("Reset analysis requires one observed attempt per trial")
    summary = sources.json(args.navigation_summary)
    if summary.get("schema_version") != "vla.navigation-summary.v1" or summary.get("plan") != plan:
        raise ValueError("Navigation summary must embed this exact frozen plan")
    sources.record(args.plan, summary["plan_source"])
    receipt = sources.json(args.runtime_receipt)
    receipt_sha = sha256(args.runtime_receipt)
    helper_sha, hook_sha = sha256(args.reset_helper), sha256(args.runtime_hook)
    sources.record(args.reset_helper)
    sources.record(args.runtime_hook)
    global_errors = list(summary.get("source_consistency_errors", []))
    for record in summary.get("source_files", []):
        try:
            path = Path(args.plan) if record["path"] == summary["plan_source"]["path"] else remap(record["path"], mappings)
            sources.record(path, record)
        except (OSError, ValueError) as exc:
            global_errors.append(str(exc))
    if not summary.get("source_files"):
        global_errors.append("Navigation summary has no source inventory")
    session_results, event_map, roots, reset_results = [], {}, {}, {}
    measurements, storage = [], []
    for declared in plan["sessions"]:
        sid = declared["session_id"]
        matching = [s for s in summary["sessions"] if s["session_id"] == sid]
        errors = []
        result = {"session_id": sid, "errors": errors}
        session_results.append(result)
        if len(matching) != 1:
            errors.append("Missing or duplicate navigation-summary session")
            continue
        session = matching[0]
        root = remap(declared["evidence_dir"], mappings)
        roots[sid] = root
        events = []
        try:
            events = sources.events(root / "events.jsonl")
            ids = [e.get("event_id") for e in events]
            if any(type(value) is not int for value in ids) or ids != sorted(set(ids)):
                raise ValueError("Raw event IDs are missing, duplicated, or out of order")
            runs = [e for e in events if e.get("event_type") == "run.start"]
            installed = [e for e in events if e.get("event_type") == "reset_protocol.installed"]
            if len(runs) != 1:
                raise ValueError("Expected one run.start per session")
            errors.extend(audit_run(runs[0], installed, plan, receipt, receipt_sha, helper_sha, hook_sha))
            if any(e.get("run_id") != runs[0].get("run_id") for e in events):
                errors.append("Events do not share the declared run ID")
            starts = [e for e in events if e.get("event_type") == "episode.start"]
            if installed and starts and installed[0]["event_id"] >= min(e["event_id"] for e in starts):
                errors.append("Reset helper installation was not before first episode")
            if nav.instant(runs[0]["wall_time_utc"]) <= nav.instant(plan["frozen_at_utc"]):
                errors.append("Plan was not frozen before run.start")
            simulation = session.get("simulation_session_report") or {}
            settings_records = [r for r in simulation.get("artifacts", []) if "/settings/" in r["path"] and r["path"].endswith("/settings.json")]
            if len(settings_records) != 1:
                raise ValueError("Expected exactly one preserved scene-settings artifact")
            settings_record = settings_records[0]
            settings = sources.json(remap(settings_record["path"], mappings), settings_record)
            expected_starts = {(a.get("raw_attempt_id"), a.get("start_event_id")) for a in summary["attempts"] if a.get("session_id") == sid and a.get("navigation_attempt_observed") is True}
            if expected_starts != {(s.get("attempt_id"), s.get("event_id")) for s in starts}:
                errors.append("Raw episode starts differ from summarized observed attempts")
            for start in starts:
                ae = [e for e in events if e.get("attempt_id") == start.get("attempt_id")]
                accepted = [e for e in ae if e.get("event_type") == "reset_protocol.evaluator_acceptance"]
                payload = None
                payload_errors = []
                if len(accepted) == 1:
                    try:
                        aid = start["attempt_id"]
                        ordinal = accepted[0].get("reset_ordinal")
                        if not isinstance(aid, str) or Path(aid).name != aid or type(ordinal) is not int or ordinal < 1:
                            raise ValueError("Invalid reset payload path components")
                        payload = sources.json(root / "reset_acceptance" / f"{aid}-{ordinal}.json")
                    except (OSError, ValueError) as exc:
                        payload_errors.append(str(exc))
                audit = audit_attempt(ae, start, settings, settings_record["sha256"], payload, helper_sha)
                audit["errors"].extend(payload_errors)
                audit["accepted_reset_evidence"] = not audit["errors"]
                reset_results[(sid, start.get("attempt_id"), start.get("event_id"))] = audit
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(str(exc))
        event_map[sid] = events
        result["raw_events_recorded"] = len(events)
        measurements.append(session_measurements(session, events, sources, mappings))
        # Only declared session and run roots; no dataset traversal.
        for label, tree in (("navigation_run", root.parent), ("simulation_session", remap(declared["session_report"], mappings).parent)):
            files = [p for p in tree.rglob("*") if p.is_file() and not p.is_symlink()] if tree.is_dir() else []
            storage.append({"session_id": sid, "scope": label, "path": str(tree), "regular_files": len(files),
                            "logical_bytes": sum(p.stat().st_size for p in files),
                            "note": "Copied local regular-file logical sizes at analysis time; excludes symlinks, filesystem allocation and model/assets"})
    session_errors = {s["session_id"]: s["errors"] for s in session_results}
    attempts = []
    for attempt in summary["attempts"]:
        audit = reset_results.get((attempt["session_id"], attempt.get("raw_attempt_id"), attempt.get("start_event_id")),
                                  {"accepted_reset_evidence": False, "status": "reset_evidence_unavailable", "errors": ["No auditable episode-start/reset pair"]})
        errors = [*global_errors, *session_errors.get(attempt["session_id"], ["Undeclared session"]), *audit["errors"]]
        valid = (attempt.get("status") == "valid_navigation_outcome" and attempt.get("navigation_attempt_observed") is True and
                 attempt.get("within_declared_attempt_cap") is True and audit["accepted_reset_evidence"] is True and
                 audit.get("first_input_event_id") is not None and not errors)
        attempts.append({**attempt, "reset_audit": audit, "joint_valid": valid,
                         "joint_status": "valid_navigation_and_reset" if valid else "unscored_evidence_or_process_failure",
                         "joint_errors": errors})
    # Sources must remain unchanged throughout the analysis; never silently score a moving target.
    for record in list(sources.records.values()):
        try:
            sources.record(record["path"], record)
        except (OSError, ValueError) as exc:
            global_errors.append(str(exc))
    if global_errors:
        for attempt in attempts:
            attempt.update(joint_valid=False, joint_status="unscored_source_integrity_failure")
    trials = combine_trials(plan, attempts)
    scored = [row for row in trials if row["status"] == "scored_valid_trial"]
    observed = [row for row in attempts if row.get("navigation_attempt_observed") is True]
    aggregate = {"planned_unique_trials": len(trials), "observed_attempts": len(observed),
                 "unplanned_observed_attempts": sum(row.get("trial_id") not in {t["trial_id"] for t in trials} for row in observed),
                 "observed_unique_trials": sum(row["observed_attempts"] > 0 for row in trials),
                 "valid_scored_trials": len(scored), "unscored_trials": len(trials)-len(scored),
                 "unstarted_trials": sum(row["status"] == "unstarted_trial" for row in trials),
                 "attempts_beyond_cap": sum(row["attempts_beyond_cap"] for row in trials),
                 "reset_accepted_attempts": sum(row["reset_audit"]["accepted_reset_evidence"] is True for row in observed),
                 "success_among_valid_trials": proportion(sum(row["upstream_success"] is True for row in scored), len(scored)),
                 "osr_among_valid_trials": proportion(sum(row["upstream_osr_success"] is True for row in scored), len(scored)),
                 "recorded_successes_per_planned_trial": {"numerator": sum(row["upstream_success"] is True for row in scored),
                                                        "denominator": len(trials), "note": "Completion accounting only; unscored trials are not navigation failures"}}
    aggregate["sampled_endpoint_contact_among_valid_trials"] = {
        "true": sum(row["any_recorded_endpoint_contact"] is True for row in scored),
        "false": sum(row["any_recorded_endpoint_contact"] is False for row in scored),
        "unavailable": sum(type(row["any_recorded_endpoint_contact"]) is not bool for row in scored),
        "scope": "Any recorded endpoint/latch flag, not continuous contact incidence"}
    from .context import evaluation_context, scope_limitations
    context = evaluation_context(plan, getattr(args, "role", "unspecified"), getattr(args, "split", None))
    limitations = scope_limitations(context) + [
        "Wilson intervals summarize a binomial model conditional on valid outcomes. Fixed missions from one map and correlated behavior limit population interpretation; missing or invalid trials are not assigned failures.",
        "Success/OSR use upstream navigation flags and target-distance conventions. LAND is a stop token, not evidence of physical touchdown.",
        "Contact values are sampled/latching endpoint reports, not continuous monitoring. Upstream collision flags also include heuristics; neither field proves a collision-free path.",
        "Reset evidence recomputes pose/camera checks and binds source/settings hashes; matched hook source enforces acceptance before model preparation. Timestamp ordering alone establishes only recorded-event order.",
        "The 0.001-second continuation request can advance simulator time by a different amount. Pose tolerances do not require exact-zero velocity.",
        "Host generate/copy/action/image-write intervals and GPU samples retain their stated scopes; they are not synchronized CUDA latency, continuous peaks or all instrumentation overhead.",
        "This analysis reads metadata and events, not image pixels. Its video-selection.json is a descriptive execution-order suggestion; it does not replace a separately frozen paired editorial rule."
    ]
    from . import context as context_module
    implementation_files = [sources.record(p) for p in (Path(__file__), Path(nav.__file__), Path(context_module.__file__))]
    implementation = {"engine": "uav-vla.native-analysis.v1", "source_files": implementation_files, "scope": "Generated native numerical engine with explicit role/split prose; these are actual new source hashes, never historical analyzer hashes."}
    result = {"implementation": implementation, "schema_version": "vla.baseline-reset-analysis.v1", "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "evaluation_context": context, "plan_id": plan["plan_id"], "plan_sha256": sha256(args.plan), "configuration": plan["configuration"],
              "aggregate": aggregate, "trials": trials, "attempts": attempts, "session_reset_audits": session_results,
              "measurements": measurements, "storage": storage, "source_errors": global_errors,
              "limitations": limitations, "source_files": list(sources.records.values())}
    return result, video_selection(trials, attempts, event_map, roots)


def report_markdown(result):
    counts = result["aggregate"]
    sr = counts["success_among_valid_trials"]
    status = "complete" if counts["valid_scored_trials"] == counts["planned_unique_trials"] and counts["attempts_beyond_cap"] == 0 and counts["unplanned_observed_attempts"] == 0 else "incomplete"
    context = result.get("evaluation_context", {"split": "unspecified", "role": "unspecified"})
    lines = [f"# {context['split'].capitalize()} {context['role']} evaluation with audited reset evidence", "",
             f"Analysis status: **{status}**. Frozen plan `{result['plan_id']}`.", "",
             f"Planned unique missions: **{counts['planned_unique_trials']}**. Observed attempts: **{counts['observed_attempts']}**. "
             f"Valid scored trials: **{counts['valid_scored_trials']}**. Unscored: **{counts['unscored_trials']}**, including "
             f"**{counts['unstarted_trials']}** unstarted. Attempts beyond the declared cap: **{counts['attempts_beyond_cap']}**.", "",
             f"Upstream success among valid trials: **{sr['numerator']}/{sr['denominator']}**. "
             + (f"Wilson 95% descriptive interval: **{sr['wilson_95'][0]:.3f}–{sr['wilson_95'][1]:.3f}**." if sr['wilson_95'] else "Interval unavailable: no valid outcomes."), "",
             "| Trial | Observed | Reset + navigation | Outcome | Distance (m) |", "|---|---:|---|---|---:|"]
    for row in result["trials"]:
        distance = row["distance_to_spawned_target_m"]
        lines.append(f"| {row['trial_id']} | {row['observed_attempts']} | {row['status']} | {row['termination_reason'] or 'unscored'} | {distance if distance is not None else 'unavailable'} |")
    lines.extend(["", "Per-attempt rejection details, source hashes, raw outcome flags, measured timing scopes and storage counts are retained in [analysis.json](analysis.json). "
                  "The exact editorial selection is in [video-selection.json](video-selection.json).", ""])
    lines.extend("- " + value for value in result["limitations"])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("plan", "navigation-summary", "runtime-receipt", "reset-helper", "runtime-hook", "output"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--path-map", action="append", default=[], metavar="REMOTE_PREFIX=LOCAL_PREFIX")
    parser.add_argument("--role", choices=("original", "candidate", "unspecified"), default="unspecified")
    parser.add_argument("--split", choices=("demo", "development", "holdout"), help="Must match any frozen split declaration; otherwise retained as caller display context")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("Output must be a fresh path; existing analysis is immutable")
    result, selection = analyze(args)
    args.output.mkdir(parents=True)
    write_json(args.output / "analysis.json", result)
    write_json(args.output / "video-selection.json", selection)
    write_json(args.output / "reset-audits.json", [{"session_id": a["session_id"], **a["reset_audit"]} for a in result["attempts"]])
    with (args.output / "trials.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result["trials"][0]))
        writer.writeheader()
        writer.writerows(result["trials"])
    (args.output / "REPORT.md").write_text(report_markdown(result))
    print(json.dumps({"output": str(args.output.resolve()), "aggregate": result["aggregate"], "source_errors": result["source_errors"]}, indent=2))
    return 0 if not result["source_errors"] and result["aggregate"]["unscored_trials"] == 0 and result["aggregate"]["attempts_beyond_cap"] == 0 and result["aggregate"]["unplanned_observed_attempts"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
