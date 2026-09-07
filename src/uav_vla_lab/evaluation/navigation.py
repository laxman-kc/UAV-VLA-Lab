#!/usr/bin/env python3
"""Account planned navigation trials using recorded AeroVLA hook evidence.

Read-only with respect to experiments. Missing files, interrupted attempts and
unexpected retries remain visible; they are never assigned a navigation score.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import statistics


FLAGS = ("success", "oracle_success", "collisions", "early_end", "dones", "predict_dones")
OUTCOME_FIELDS = ("episode_id", "map_name", "attempt_id", "status", "termination_reason", "step",
                  "upstream_flags", "distance_to_target_m", "endpoint_contact", "endpoint_state_timestamp",
                  "contact_scope", "stuck_counter", "interpretation")
PROTOCOL = "aerovla-e37685a-observed-v1"


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def instant(value):
    if not isinstance(value, str):
        raise ValueError("Timestamp must be an ISO8601 string with timezone")
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp needs a timezone")
    return result


def finite(value):
    return type(value) in (float, int) and math.isfinite(value)


def resolve(base, value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (Path(base) / path).resolve()


def strict_relative(root, value):
    if not isinstance(value, str) or not value:
        raise ValueError("Missing relative evidence path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or "\\" in value:
        raise ValueError("Evidence path escapes navigation evidence directory")
    path = (Path(root) / value).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError("Evidence symlink escapes navigation evidence directory")
    return path


def safe_value(value):
    """Preserve invalid JSON-number evidence without emitting nonstandard JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return {"invalid_nonfinite_number": str(value)}
    if isinstance(value, dict):
        return {key: safe_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_value(item) for item in value]
    return value


def obj(value):
    return value if isinstance(value, dict) else {}


def identity_key(value):
    return json.dumps(safe_value(value), sort_keys=True, allow_nan=False)


class Evidence:
    def __init__(self):
        self.files = {}

    def record(self, path):
        path = Path(path).resolve()
        if str(path) not in self.files:
            self.files[str(path)] = {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}
        return self.files[str(path)]

    def json(self, path):
        if path is None:
            return None, "not_declared"
        try:
            self.record(path)
            return read_json(path), None
        except (OSError, ValueError) as exc:
            return None, f"{type(exc).__name__}: {exc}"

    def events(self, path):
        events, errors = [], []
        try:
            self.record(path)
            with Path(path).open(encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, 1):
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict):
                            raise ValueError("Event is not a JSON object")
                        events.append({**event, "_source_line": line_number})
                    except ValueError as exc:
                        errors.append({"line": line_number, "error": str(exc)})
        except (OSError, UnicodeError) as exc:
            errors.append({"line": None, "error": f"{type(exc).__name__}: {exc}"})
        return events, errors

    def changed_files(self):
        changed = []
        for path, recorded in self.files.items():
            try:
                if sha256(path) != recorded["sha256"] or Path(path).stat().st_size != recorded["bytes"]:
                    changed.append({"path": path, "error": "Source changed while being summarized"})
            except OSError as exc:
                changed.append({"path": path, "error": str(exc)})
        return changed


def validate_plan(plan):
    if not isinstance(plan, dict):
        raise ValueError("Plan must be an object")
    if plan.get("schema_version") != "vla.navigation-plan.v1":
        raise ValueError("Expected vla.navigation-plan.v1")
    if not isinstance(plan.get("plan_id"), str) or not plan["plan_id"]:
        raise ValueError("plan_id is required")
    instant(plan.get("frozen_at_utc"))
    config = obj(plan.get("configuration"))
    for key in ("checkpoint_id", "model_path", "task_mode", "runtime_id"):
        if not isinstance(config.get(key), str) or not config[key]:
            raise ValueError(f"configuration.{key} is required")
    if config.get("protocol") != PROTOCOL:
        raise ValueError("Only the inspected instrumented AeroVLA protocol is supported")
    if type(config.get("require_recorded_runtime_id", True)) is not bool:
        raise ValueError("configuration.require_recorded_runtime_id must be a boolean")
    if type(config.get("max_actions")) is not int or config["max_actions"] < 1:
        raise ValueError("configuration.max_actions must be positive")
    retry = obj(plan.get("retry_policy"))
    if retry.get("selection") != "first_valid_attempt" or type(retry.get("max_attempts_per_trial")) is not int or retry["max_attempts_per_trial"] < 1:
        raise ValueError("Declare first_valid_attempt selection and a positive maximum attempt count")
    trials = plan.get("trials")
    if not isinstance(trials, list) or not trials:
        raise ValueError("Explicit planned trials are required")
    ids, episodes = set(), set()
    for trial in trials:
        if not isinstance(trial, dict):
            raise ValueError("Every trial must be an object")
        for key in ("trial_id", "map_name", "episode_id"):
            if not isinstance(trial.get(key), str) or not trial[key] or "/" in trial[key] or "\\" in trial[key]:
                raise ValueError(f"Trial {key} must be a nonempty single component")
        episode = (trial["map_name"], trial["episode_id"])
        if trial["trial_id"] in ids or episode in episodes:
            raise ValueError("A policy/episode may appear only once in planned trials")
        if trial.get("checkpoint_id", config["checkpoint_id"]) != config["checkpoint_id"]:
            raise ValueError("One plan summarizes one checkpoint; use paired plans for candidate comparison")
        ids.add(trial["trial_id"])
        episodes.add(episode)
    sessions = plan.get("sessions", [])
    if not isinstance(sessions, list):
        raise ValueError("sessions must be a list (empty is allowed for an unstarted plan)")
    session_ids, orders = set(), set()
    for session in sessions:
        if not isinstance(session, dict):
            raise ValueError("Every session must be an object")
        identifier, order = session.get("session_id"), session.get("order")
        if not isinstance(identifier, str) or not identifier or identifier in session_ids:
            raise ValueError("Session IDs must be unique")
        if type(order) is not int or order < 1 or order in orders:
            raise ValueError("Session order must be unique positive integers")
        assigned = session.get("trial_ids")
        if not isinstance(assigned, list) or not assigned or any(not isinstance(item, str) for item in assigned) or len(set(assigned)) != len(assigned) or not set(assigned).issubset(ids):
            raise ValueError("Session must explicitly name its unique planned trial IDs")
        for key in ("evidence_dir", "supervisor_report"):
            if not isinstance(session.get(key), str) or not session[key]:
                raise ValueError(f"Session {key} must point to actual expected evidence")
        session_ids.add(identifier)
        orders.add(order)
    return plan


def process_issue(supervisor, session):
    """Describe only explicit process/lifecycle failures, not navigation outcomes."""
    if isinstance(supervisor, dict):
        status = supervisor.get("status")
        if status in ("timed_out", "interrupted", "supervisor_error", "exited_with_error", "cleanup_incomplete"):
            return "supervisor_" + status
        code = supervisor.get("child_returncode")
        if type(code) is int and code != 0:
            return "child_nonzero_exit"
    if isinstance(session, dict):
        status = session.get("status")
        if status in ("command_failed", "manager_readiness_timeout", "manager_exited_early", "interrupted",
                      "session_error", "cleanup_or_evidence_incomplete"):
            return "session_" + status
        code = session.get("session_returncode")
        if type(code) is int and code != 0:
            return "session_nonzero_exit"
    return None


def contact_value(value):
    if isinstance(value, dict) and type(value.get("has_collided")) is bool:
        return value["has_collided"]
    return None


def endpoint_contacts(events, outcome):
    samples = []
    for event in events:
        if event.get("event_type") == "observation.prepared":
            state = obj(obj(event.get("sensors")).get("state"))
            samples.append({"event_id": event.get("event_id"), "source": "observation.prepared",
                            "timestamp": state.get("timestamp"), "value": contact_value(state.get("collision"))})
        elif event.get("event_type") == "action.completed":
            # makeActions returns [batch][five duplicate endpoint state records].
            result = event.get("endpoint_states")
            if isinstance(result, list) and len(result) == 1 and isinstance(result[0], list) and result[0]:
                state = obj(obj(obj(result[0][-1]).get("sensors")).get("state"))
                samples.append({"event_id": event.get("event_id"), "source": "action.completed:last_endpoint_only",
                                "timestamp": state.get("timestamp"), "value": contact_value(state.get("collision"))})
    if isinstance(outcome, dict):
        samples.append({"event_id": None, "source": "terminal_outcome", "timestamp": outcome.get("endpoint_state_timestamp"),
                        "value": contact_value(outcome.get("endpoint_contact"))})
    values = [item["value"] for item in samples]
    any_contact = True if any(value is True for value in values) else False if values and all(value is False for value in values) else None
    return {"terminal_contact": contact_value(outcome.get("endpoint_contact")) if isinstance(outcome, dict) else None,
            "any_recorded_endpoint_contact": any_contact, "records": samples,
            "known_records": sum(value is not None for value in values), "record_count": len(values),
            "scope": "Recorded endpoints only; repeated endpoint records are not independent contact observations or continuous monitoring"}


def validate_outcome(outcome, completed, start, max_actions):
    errors = []
    if not isinstance(outcome, dict):
        return ["Missing or malformed completed outcome file"]
    if completed is None:
        return ["No matching episode.completed event"]
    for field in OUTCOME_FIELDS:
        if outcome.get(field) != completed.get(field):
            errors.append(f"Outcome file/event disagree: {field}")
    for field in ("episode_id", "map_name", "attempt_id"):
        if outcome.get(field) != start.get(field):
            errors.append(f"Outcome/start identity disagrees: {field}")
    if outcome.get("status") != "completed":
        errors.append("Outcome is not an upstream completed navigation outcome")
    flags = outcome.get("upstream_flags", {})
    if not isinstance(flags, dict) or any(type(flags.get(key)) is not bool for key in FLAGS):
        errors.append("All six upstream flags must be explicit booleans")
        return errors
    if flags["dones"] is not True:
        errors.append("Completed outcome lacks the upstream done flag")
    reason = next((reason for key, reason in (("success", "success"), ("oracle_success", "oracle_success"),
        ("collisions", "upstream_collision_flag"), ("early_end", "early_end")) if flags[key]), "step_limit_or_other_done")
    if outcome.get("termination_reason") != reason:
        errors.append("Termination reason disagrees with upstream flag precedence")
    distance = outcome.get("distance_to_target_m")
    if not finite(distance) or distance < 0:
        errors.append("Terminal distance is missing, negative or nonfinite")
    elif flags["success"] and (distance > 20 or not flags["predict_dones"] or flags["early_end"]):
        errors.append("Success flag contradicts the inspected upstream success conditions")
    step = outcome.get("step")
    if type(step) is not int or not 0 <= step <= max_actions:
        errors.append("Upstream terminal loop index is invalid or outside the declared action budget")
    return errors


def classify_attempt(attempt, outcome, maximum):
    if attempt["status"] != "valid_navigation_outcome":
        return [attempt["status"]]
    flags = outcome["upstream_flags"]
    categories = []
    if flags["success"]:
        categories.append("upstream_success")
    elif flags["oracle_success"]:
        categories.append("oracle_without_terminal_success")
    if flags["collisions"]:
        categories.append("upstream_collision_flag_contact_not_established")
        if type(outcome.get("stuck_counter")) is int and outcome["stuck_counter"] > 15:
            categories.append("recorded_stuck_counter_exceeds_upstream_threshold")
    if flags["early_end"]:
        categories.append("upstream_early_end_flag")
    if not flags["success"] and outcome["step"] == maximum:
        categories.append("declared_step_budget_reached")
    if attempt["contact"]["terminal_contact"] is True:
        categories.append("terminal_endpoint_contact_reported")
    if not categories:
        categories.append("other_upstream_done_cause_unavailable")
    return categories


def check_images(events, root, evidence):
    errors = []
    for event in events:
        if event.get("event_type") != "observation.prepared":
            continue
        images = event.get("images")
        if not isinstance(images, list) or not images:
            errors.append(f"Observation {event.get('event_id')} has no image evidence")
            continue
        cameras = set()
        for item in images:
            try:
                if not isinstance(item, dict):
                    raise ValueError("Image reference is not an object")
                path = strict_relative(root, item.get("path"))
                record = evidence.record(path)
                if record["sha256"] != item.get("sha256"):
                    raise ValueError("Image SHA256 differs")
                if not isinstance(item.get("camera"), str) or not isinstance(item.get("modality"), str):
                    raise ValueError("Camera/modality must be strings")
                cameras.add((item["camera"], item["modality"]))
            except (ValueError, OSError) as exc:
                errors.append(f"Observation {event.get('event_id')} image evidence: {exc}")
        if not {("front", "rgb"), ("down", "rgb")}.issubset(cameras):
            errors.append(f"Observation {event.get('event_id')} lacks both policy RGB views")
    return errors


def check_event_links(events, start, completed, outcome):
    """Check the observed upstream order; a stop still executes its decoded action."""
    errors = []
    by_id = {event["event_id"]: event for event in events if type(event.get("event_id")) is int}
    kinds = collections.defaultdict(list)
    for event in events:
        if isinstance(event.get("event_type"), str):
            kinds[event["event_type"]].append(event)
        for field in ("episode_id", "map_name", "attempt_id"):
            if event.get(field) != start.get(field):
                errors.append(f"Event {event.get('event_id')} has inconsistent {field}")
        if not start["_source_line"] <= event["_source_line"] <= completed["_source_line"]:
            errors.append(f"Attempt event {event.get('event_id')} falls outside its start/completion boundary")

    def link(event, field, target_kind):
        identifier = event.get(field)
        target = by_id.get(identifier) if type(identifier) is int else None
        if target is None or target.get("event_type") != target_kind or target["_source_line"] >= event["_source_line"]:
            errors.append(f"Event {event.get('event_id')} lacks an earlier same-attempt {target_kind} via {field}")
            return None
        return target

    for event in kinds["prompt.prepared"]:
        link(event, "observation_event_id", "observation.prepared")
    for event in kinds["policy.generated"]:
        link(event, "observation_event_id", "observation.prepared")
        prompts = [item for item in kinds["prompt.prepared"] if item.get("observation_event_id") == event.get("observation_event_id")
                   and item["_source_line"] < event["_source_line"]]
        if len(prompts) != 1:
            errors.append(f"Generation {event.get('event_id')} must have one matching prepared prompt")
        if not isinstance(event.get("token_ids"), list) or not isinstance(event.get("raw_text"), list):
            errors.append(f"Generation {event.get('event_id')} lacks recorded token IDs/text")
    for event in kinds["policy.decoded"] + kinds["action.requested"]:
        link(event, "observation_event_id", "observation.prepared")
        generated = link(event, "policy_event_id", "policy.generated")
        if generated and generated.get("observation_event_id") != event.get("observation_event_id"):
            errors.append(f"Event {event.get('event_id')} shifts the policy/observation mapping")
        if event.get("event_type") == "action.requested":
            decoded = [item for item in kinds["policy.decoded"] if item.get("policy_event_id") == event.get("policy_event_id")
                       and item["_source_line"] < event["_source_line"]]
            if len(decoded) != 1 or decoded[0].get("upstream_actions") != event.get("actions"):
                errors.append(f"Action {event.get('event_id')} differs from its unique recorded decode")
        else:
            actions, stops = event.get("upstream_actions"), event.get("upstream_stop_flags")
            if not isinstance(actions, list) or len(actions) != 1 or any(not finite(obj(actions[0]).get(key)) for key in ("fwd", "down", "yaw")):
                errors.append(f"Decode {event.get('event_id')} has malformed batch-one actions")
            if not isinstance(stops, list) or len(stops) != 1 or type(stops[0]) is not bool:
                errors.append(f"Decode {event.get('event_id')} lacks an explicit batch-one stop flag")
    for event in kinds["action.completed"]:
        link(event, "command_event_id", "action.requested")
    for source_kind, target_kind, field in (("policy.generated", "policy.decoded", "policy_event_id"),
                                           ("policy.generated", "action.requested", "policy_event_id"),
                                           ("action.requested", "action.completed", "command_event_id")):
        for event in kinds[source_kind]:
            if sum(item.get(field) == event.get("event_id") for item in kinds[target_kind]) != 1:
                errors.append(f"Event {event.get('event_id')} needs one {target_kind} completion")
    # The inspected loop checks termination at t, then performs one action, then prepares
    # the next observation; terminal t is the number of completed actions, not elapsed time.
    step = obj(outcome).get("step")
    if type(step) is int and (len(kinds["action.completed"]) != step or len(kinds["observation.prepared"]) != step + 1):
        errors.append("Action/observation counts disagree with the recorded upstream terminal loop index")
    if kinds["policy.decoded"] and isinstance(obj(outcome).get("upstream_flags"), dict):
        stops = kinds["policy.decoded"][-1].get("upstream_stop_flags")
        if isinstance(stops, list) and len(stops) == 1 and stops[0] != outcome["upstream_flags"].get("predict_dones"):
            errors.append("Terminal predict_dones differs from the last recorded policy stop flag")
    return errors


def analyze_session(declaration, plan, base, evidence):
    config = plan["configuration"]
    root = resolve(base, declaration["evidence_dir"])
    supervisor_path = resolve(base, declaration["supervisor_report"])
    session_path = resolve(base, declaration["session_report"]) if declaration.get("session_report") else None
    supervisor, supervisor_error = evidence.json(supervisor_path)
    session_report, session_error = evidence.json(session_path)
    report_errors = []
    if supervisor_error:
        report_errors.append({"source": "supervisor_report", "error": supervisor_error})
    elif not isinstance(supervisor, dict) or supervisor.get("schema_version") != "vla.supervised_run.v1":
        report_errors.append({"source": "supervisor_report", "error": "Unexpected supervisor report schema"})
    if session_path and session_error:
        report_errors.append({"source": "session_report", "error": session_error})
    elif session_path and (not isinstance(session_report, dict) or session_report.get("schema_version") != "vla.simulation-session.v1"):
        report_errors.append({"source": "session_report", "error": "Unexpected simulation-session report schema"})
    process_failure = process_issue(supervisor, session_report)
    events, parse_errors = evidence.events(root / "events.jsonl")
    run_starts = [e for e in events if e.get("event_type") == "run.start"]
    protocol_errors = []
    run_start = run_starts[0] if len(run_starts) == 1 else {}
    if len(run_starts) != 1:
        protocol_errors.append("Expected one recorded run.start")
    for field in ("protocol", "max_actions"):
        if run_start.get(field) != config[field]:
            protocol_errors.append(f"Recorded run.start {field} differs from the declared configuration")
    if run_start.get("model_path") != config["model_path"]:
        protocol_errors.append("Recorded model path differs from the declared checkpoint path")
    if run_start.get("runtime_id") is not None:
        if run_start["runtime_id"] != config["runtime_id"]:
            protocol_errors.append("Recorded runtime ID differs from the declared runtime")
    elif config.get("require_recorded_runtime_id", True):
        protocol_errors.append("Recorded runtime ID is absent but required by this plan")
    if run_start.get("batch_size") != 1:
        protocol_errors.append("Only the inspected batch-size-one hook is supported")
    try:
        if instant(run_start.get("wall_time_utc")) < instant(plan["frozen_at_utc"]):
            protocol_errors.append("The plan was frozen after recorded execution began")
    except ValueError as exc:
        protocol_errors.append(f"Cannot establish plan timing: {exc}")
    ids = [event.get("event_id") for event in events]
    if any(type(value) is not int or value < 1 for value in ids) or ids != sorted(set(ids)):
        protocol_errors.append("Event IDs must be unique increasing positive integers")
    if any(event.get("schema_version") != 1 or not isinstance(event.get("event_type"), str) for event in events):
        protocol_errors.append("Event schema/version or event type is malformed")
    run_ids = {identity_key(event.get("run_id")) for event in events}
    if len(run_ids) != 1 or not isinstance(run_start.get("run_id"), str) or not run_start.get("run_id"):
        protocol_errors.append("Event stream has missing or mixed run IDs")
    outcomes, outcome_errors = {}, {}
    outcome_files = sorted((root / "outcomes").glob("*.json")) if (root / "outcomes").is_dir() else []
    for path in outcome_files:
        value, error = evidence.json(path)
        identifier = value.get("attempt_id", path.stem) if isinstance(value, dict) else path.stem
        if not isinstance(identifier, str) or not identifier:
            identifier = path.stem
            error = "Outcome has a missing or malformed attempt ID"
        if identifier != path.stem:
            error = "Outcome filename does not match its recorded attempt ID"
        if identifier in outcomes:
            outcome_errors[identifier] = "Multiple outcome files claim the same attempt"
        outcomes[identifier] = value
        if error:
            outcome_errors[identifier] = error
    partials = []
    for path in sorted((root / "partial").glob("*.json")) if (root / "partial").is_dir() else []:
        value, error = evidence.json(path)
        partials.append({"path": str(path), "content": safe_value(value), "error": error})
    attempts, observed_ids = [], set()
    starts = [e for e in events if e.get("event_type") == "episode.start"]
    assigned = {item["trial_id"]: item for item in plan["trials"] if item["trial_id"] in declaration["trial_ids"]}
    by_episode = {(item["map_name"], item["episode_id"]): item for item in assigned.values()}
    for start in starts:
        raw_identifier = start.get("attempt_id")
        identifier = raw_identifier if isinstance(raw_identifier, str) and raw_identifier else None
        attempt_events = [e for e in events if e.get("attempt_id") == raw_identifier]
        complete = [e for e in attempt_events if e.get("event_type") == "episode.completed"]
        interrupted = [e for e in attempt_events if e.get("event_type") == "episode.interrupted"]
        outcome = outcomes.get(identifier)
        episode_identity = (start.get("map_name"), start.get("episode_id"))
        trial = by_episode.get(episode_identity) if all(isinstance(part, str) for part in episode_identity) else None
        row = {"session_id": declaration["session_id"], "session_order": declaration["order"],
            "attempt_id": identifier, "raw_attempt_id": safe_value(raw_identifier), "run_id": safe_value(start.get("run_id")), "start_event_id": start.get("event_id"),
            "trial_id": trial["trial_id"] if trial else None, "map_name": start.get("map_name"), "episode_id": start.get("episode_id"),
            "navigation_attempt_observed": True, "process_issue": process_failure,
            "start_wall_time_utc": start.get("wall_time_utc"), "status": None, "errors": list(protocol_errors),
            "source_parse_errors": parse_errors, "session_report_errors": report_errors,
            "raw_outcome": safe_value(outcome), "interruption_events": safe_value(interrupted),
            "partial_files": [item for item in partials if obj(item["content"]).get("attempt_id") == raw_identifier],
            "observations_recorded": sum(e.get("event_type") == "observation.prepared" for e in attempt_events),
            "policy_outputs_recorded": sum(e.get("event_type") == "policy.generated" for e in attempt_events),
            "actions_requested": sum(e.get("event_type") == "action.requested" for e in attempt_events),
            "actions_completed": sum(e.get("event_type") == "action.completed" for e in attempt_events),
            "selected_for_trial": False}
        if not isinstance(identifier, str) or not identifier or identifier in observed_ids:
            row["errors"].append("Missing or duplicate episode attempt ID")
        observed_ids.add(identifier)
        if trial is None:
            row["errors"].append("Episode was not assigned to this declared session")
        if len(complete) > 1 or (complete and interrupted):
            row["errors"].append("Conflicting terminal events")
        if identifier in outcome_errors:
            row["errors"].append(outcome_errors[identifier])
        if complete:
            terminal = complete[0]
            if terminal["_source_line"] <= start["_source_line"]:
                row["errors"].append("Completion appears before episode start")
            if any(error["line"] is None or start["_source_line"] <= error["line"] <= terminal["_source_line"] for error in parse_errors):
                row["errors"].append("Malformed event evidence inside the recorded attempt")
            row["errors"].extend(validate_outcome(outcome, terminal, start, config["max_actions"]))
            if not row["policy_outputs_recorded"] or not row["observations_recorded"]:
                row["errors"].append("No recorded model generation and policy observation for this outcome")
            row["errors"].extend(check_images(attempt_events, root, evidence))
            domain_events = [event for event in attempt_events if event.get("event_type") in
                             ("episode.start", "observation.prepared", "prompt.prepared", "policy.generated", "policy.decoded",
                              "action.requested", "action.completed", "episode.completed", "episode.interrupted")]
            row["errors"].extend(check_event_links(domain_events, start, terminal, outcome))
            row["status"] = "invalid_evidence" if row["errors"] else "valid_navigation_outcome"
        elif outcome is not None:
            row["errors"].append("Outcome file exists without episode.completed")
            row["status"] = "invalid_evidence"
        elif interrupted or process_failure:
            row["status"] = "interrupted_navigation_attempt" if not row["errors"] else "invalid_evidence"
        else:
            row["status"] = "incomplete_or_missing_outcome"
        row["contact"] = endpoint_contacts(attempt_events, outcome)
        latencies = []
        for event in attempt_events:
            if event.get("event_type") == "policy.generated":
                begin, end = event.get("inference_start_ns"), event.get("inference_return_ns")
                latencies.append((end - begin) / 1e9 if type(begin) is int and type(end) is int and 0 <= begin <= end else None)
        row["generate_call_return_seconds"] = latencies
        row["mechanically_supported_categories"] = classify_attempt(row, outcome, config["max_actions"])
        attempts.append(row)
    for identifier, value in outcomes.items():
        if identifier not in observed_ids:
            attempts.append({"session_id": declaration["session_id"], "session_order": declaration["order"],
                "attempt_id": identifier, "trial_id": None, "navigation_attempt_observed": False,
                "status": "orphan_outcome", "errors": ["Outcome file has no recorded episode.start"],
                "raw_outcome": safe_value(value), "selected_for_trial": False,
                "mechanically_supported_categories": ["orphan_outcome"]})
    started_trials = {attempt["trial_id"] for attempt in attempts if attempt.get("navigation_attempt_observed")}
    for trial_id in declaration["trial_ids"]:
        if trial_id not in started_trials:
            attempts.append({"session_id": declaration["session_id"], "session_order": declaration["order"],
                "attempt_id": None, "trial_id": trial_id, "map_name": assigned[trial_id]["map_name"],
                "episode_id": assigned[trial_id]["episode_id"], "navigation_attempt_observed": False,
                "status": "session_failed_before_episode_start" if process_failure else "no_recorded_episode_start",
                "process_issue": process_failure, "errors": list(protocol_errors), "source_parse_errors": parse_errors,
                "session_report_errors": report_errors, "raw_outcome": None, "selected_for_trial": False,
                "mechanically_supported_categories": ["no_recorded_episode_start"]})
    summary = {"session_id": declaration["session_id"], "order": declaration["order"], "trial_ids": declaration["trial_ids"],
        "evidence_dir": str(root), "supervisor_report": safe_value(supervisor), "simulation_session_report": safe_value(session_report),
        "process_issue": process_failure, "report_errors": report_errors, "event_parse_errors": parse_errors,
        "protocol_errors": protocol_errors, "observed_episode_starts": len(starts),
        "recorded_run_start": safe_value(run_starts), "runtime_identity_recorded": run_start.get("runtime_id") is not None,
        "partial_files": partials,
        "recorded_run_end": safe_value([e for e in events if e.get("event_type") == "run.end"])}
    return attempts, summary


def wilson(successes, count):
    if count < 2:
        return {"bounds": None, "reason": "Fewer than two valid unique episode trials; descriptive count only"}
    z = 1.959963984540054
    p = successes / count
    divisor = 1 + z * z / count
    centre = (p + z * z / (2 * count)) / divisor
    radius = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / divisor
    return {"bounds": [max(0.0, centre - radius), min(1.0, centre + radius)], "confidence": 0.95,
            "method": "Wilson score interval", "scope": "Descriptive binomial interval over selected valid unique episodes",
            "limitation": "Independent Bernoulli sampling is a modeling assumption; fixed same-map trials and validity exclusions limit generalization"}


def metric(values, denominator_definition):
    known = [value for value in values if type(value) is bool]
    numerator, denominator = sum(known), len(known)
    return {"numerator": numerator, "denominator": denominator, "unavailable_count": len(values) - denominator,
            "rate": numerator / denominator if denominator else None, "denominator_definition": denominator_definition,
            "wilson_95": wilson(numerator, denominator)}


def summarize(plan_path):
    plan_path = Path(plan_path).resolve()
    plan = validate_plan(read_json(plan_path))
    evidence = Evidence()
    evidence.record(plan_path)
    attempts, sessions = [], []
    for declaration in sorted(plan.get("sessions", []), key=lambda item: item["order"]):
        rows, session = analyze_session(declaration, plan, plan_path.parent, evidence)
        attempts.extend(rows)
        sessions.append(session)
    # Global duplicate run/attempt identity prevents counting copied evidence twice.
    changed_sources = evidence.changed_files()
    claimed = collections.Counter(identity_key([row.get("run_id"), row.get("attempt_id")]) for row in attempts if row.get("navigation_attempt_observed"))
    for row in attempts:
        if row.get("navigation_attempt_observed") and claimed[identity_key([row.get("run_id"), row.get("attempt_id")])] > 1:
            row["errors"].append("The same run/attempt evidence was declared more than once")
            row["status"] = "invalid_evidence"
            row["mechanically_supported_categories"] = ["duplicate_evidence"]
        if changed_sources and row.get("navigation_attempt_observed"):
            row["errors"].append("Source files changed during summary; rerun against stable evidence")
            row["status"] = "invalid_evidence"
            row["mechanically_supported_categories"] = ["source_changed_during_summary"]
    trial_rows, deviations = [], []
    for trial in plan["trials"]:
        rows = [row for row in attempts if row.get("trial_id") == trial["trial_id"]]
        observed = [row for row in rows if row.get("navigation_attempt_observed")]
        valid = [row for row in observed if row["status"] == "valid_navigation_outcome"]
        for index, row in enumerate(observed, 1):
            row["observed_attempt_ordinal"] = index
            row["within_declared_attempt_cap"] = index <= plan["retry_policy"]["max_attempts_per_trial"]
        eligible = [row for row in valid if row["within_declared_attempt_cap"]]
        selected = eligible[0] if eligible else None
        if len(observed) > plan["retry_policy"]["max_attempts_per_trial"]:
            deviations.append({"trial_id": trial["trial_id"], "kind": "attempt_cap_exceeded", "observed_attempts": len(observed)})
        if len(valid) > 1:
            deviations.append({"trial_id": trial["trial_id"], "kind": "retry_after_valid_outcome", "valid_attempts": len(valid),
                               "effect": "Later outcomes cannot replace the first valid result"})
        if selected:
            selected["selected_for_trial"] = True
            outcome = selected["raw_outcome"]
            flags = outcome["upstream_flags"]
        else:
            outcome, flags = {}, {}
        trial_rows.append({**trial, "checkpoint_id": plan["configuration"]["checkpoint_id"],
            "observed_navigation_attempts": len(observed), "declared_session_slots": len({row["session_id"] for row in rows}),
            "valid_navigation_attempts": len(valid), "valid_attempts_within_declared_cap": len(eligible),
            "selected_session_id": selected["session_id"] if selected else None,
            "selected_attempt_id": selected["attempt_id"] if selected else None,
            "status": "scored_valid_trial" if selected else "no_eligible_valid_outcome" if valid else "no_valid_outcome" if observed else "not_observed_started",
            "upstream_success": flags.get("success"),
            "upstream_oracle_success_flag": flags.get("oracle_success"),
            "upstream_osr_success": bool(flags["success"] or flags["oracle_success"]) if selected else None,
            "upstream_collision_flag": flags.get("collisions"), "upstream_early_end_flag": flags.get("early_end"),
            "terminal_endpoint_contact": selected["contact"]["terminal_contact"] if selected else None,
            "any_recorded_endpoint_contact": selected["contact"]["any_recorded_endpoint_contact"] if selected else None,
            "distance_to_spawned_target_m": outcome.get("distance_to_target_m"), "terminal_loop_index": outcome.get("step"),
            "termination_reason": outcome.get("termination_reason"),
            "categories": selected["mechanically_supported_categories"] if selected else sorted({row["status"] for row in rows}) or ["no_session_declared"],
            "attempt_statuses": [row["status"] for row in rows]})
    selected_trials = [row for row in trial_rows if row["status"] == "scored_valid_trial"]
    selected_attempts = [row for row in attempts if row["selected_for_trial"]]
    latency_values = [value for row in selected_attempts for value in row.get("generate_call_return_seconds", []) if value is not None]
    aggregate = {"checkpoint_id": plan["configuration"]["checkpoint_id"],
        "counts": {"planned_unique_episode_trials": len(trial_rows), "declared_sessions": len(sessions),
            "sessions_with_recorded_process_issue": sum(row["process_issue"] is not None for row in sessions),
            "observed_navigation_attempts": sum(row.get("navigation_attempt_observed", False) for row in attempts),
            "valid_navigation_attempts": sum(row["status"] == "valid_navigation_outcome" for row in attempts),
            "selected_valid_trials": len(selected_trials), "unscored_planned_trials": len(trial_rows) - len(selected_trials),
            "trials_without_observed_episode_start": sum(row["status"] == "not_observed_started" for row in trial_rows),
            "attempt_records_by_status": dict(collections.Counter(row["status"] for row in attempts)),
            "unplanned_or_unmatched_evidence_records": sum(row.get("trial_id") is None for row in attempts)},
        "coverage": {"numerator": len(selected_trials), "denominator": len(trial_rows), "fraction": len(selected_trials) / len(trial_rows),
                     "meaning": "Valid outcome coverage of the declared plan, not navigation success rate"},
        "upstream_sr": metric([row["upstream_success"] for row in selected_trials], "First valid completed outcome within declared attempt cap per planned policy/episode trial; infrastructure/missing/invalid attempts excluded"),
        "upstream_osr": metric([row["upstream_osr_success"] for row in selected_trials], "Same selected valid trials; upstream success OR oracle_success, matching upstream metric counting"),
        "upstream_collision_flag_rate": metric([row["upstream_collision_flag"] for row in selected_trials], "Selected valid trials; flag may reflect depth, stuck or distance heuristics, not necessarily contact"),
        "terminal_endpoint_contact_rate": metric([row["terminal_endpoint_contact"] for row in selected_trials], "Selected valid trials with an explicit terminal has_collided boolean; missing contact evidence excluded"),
        "any_recorded_endpoint_contact_rate": metric([row["any_recorded_endpoint_contact"] for row in selected_trials], "Selected valid trials whose recorded endpoint contact status is decidable; not continuous collision monitoring"),
        "selected_category_counts": dict(collections.Counter(category for row in selected_trials for category in row["categories"])),
        "generation_return_timing": {"known_call_count": len(latency_values), "missing_call_count": sum(value is None for row in selected_attempts for value in row.get("generate_call_return_seconds", [])),
            "mean_seconds": statistics.mean(latency_values) if latency_values else None,
            "median_seconds": statistics.median(latency_values) if latency_values else None,
            "minimum_seconds": min(latency_values) if latency_values else None, "maximum_seconds": max(latency_values) if latency_values else None,
            "scope": "Recorded host generate-call return durations; CUDA synchronization and real-time policy frequency are not asserted"},
        "not_computed": {"spl": "Needs a separately audited complete trajectory/reference-path metric contract",
                         "upstream_ne": "Hook distance is to the spawned target; upstream metric.py compares the reference final point instead"},
        "retry_deviations": deviations,
        "limitations": ["Conditional rates exclude unscored trials; report valid coverage and every interruption beside them.",
            "A process cleanup failure after a validated terminal event does not erase that already recorded navigation outcome.",
            "A successfully exited process alone is never a valid navigation outcome.",
            "Category counts overlap and cannot be summed as mutually exclusive failure causes.",
            "The checkpoint ID/task mode are plan declarations; hook model-path matching is not cryptographic proof of loaded weight identity.",
            "Runtime IDs label the declared runtime; inspect its independently hashed runtime manifest. Missing recorded runtime IDs are allowed only by an explicit plan override.",
            "Image bytes are hash-checked, not decoded or visually reviewed by this summarizer.",
            "No physical touchdown, continuous collision-free flight, learning improvement or population-level significance is established."]}
    return safe_value({"schema_version": "vla.navigation-summary.v1", "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "plan": plan, "plan_source": evidence.files[str(plan_path)], "configuration": plan["configuration"],
        "trials": trial_rows, "attempts": attempts, "sessions": sessions, "aggregate": aggregate,
        "source_consistency_errors": changed_sources,
        "source_files": list(evidence.files.values())})


def markdown(summary):
    aggregate = summary["aggregate"]
    counts = aggregate["counts"]
    text = [f"# Navigation summary — {summary['plan']['plan_id']}", "",
        f"Checkpoint: {aggregate['checkpoint_id']}. Protocol: {summary['configuration']['protocol']}.", "",
        f"{counts['selected_valid_trials']} of {counts['planned_unique_episode_trials']} planned trials have a valid selected outcome. "
        f"{counts['observed_navigation_attempts']} navigation attempts were recorded across {counts['declared_sessions']} declared sessions.", "",
        "Rates below condition on valid outcomes. Infrastructure failures and missing/invalid evidence receive no navigation score.", "",
        "| Metric | Count | Rate | Wilson 95% interval |", "|---|---:|---:|---:|"]
    for key in ("upstream_sr", "upstream_osr", "upstream_collision_flag_rate", "terminal_endpoint_contact_rate", "any_recorded_endpoint_contact_rate"):
        value = aggregate[key]
        rate = f"{100 * value['rate']:.2f}%" if value["rate"] is not None else "unavailable"
        interval = value["wilson_95"]["bounds"]
        formatted = f"{interval[0] * 100:.2f}%–{interval[1] * 100:.2f}%" if interval else "not reported"
        text.append(f"| {key} | {value['numerator']}/{value['denominator']} | {rate} | {formatted} |")
    text.extend(["", "Wilson intervals are descriptive binomial intervals. Fixed same-map samples, correlations and validity exclusions limit generalization.", "",
        "## Trial accounting", "", "| Trial | Episode | Observed attempts | Selected attempt | Outcome |", "|---|---|---:|---|---|"])
    for row in summary["trials"]:
        def cell(value):
            return str(value if value is not None else "unavailable").replace("|", "\\|").replace("\n", " ")
        text.append("| " + " | ".join(cell(value) for value in (row["trial_id"], row["map_name"] + "/" + row["episode_id"],
            row["observed_navigation_attempts"], row["selected_attempt_id"], row["termination_reason"] or row["status"])) + " |")
    text.extend(["", "[All attempts](attempts.jsonl) · [Per-trial CSV](trials.csv) · [Aggregates and denominators](aggregate.json) · [Complete summary](summary.json)", "",
                 "## Limits", ""])
    text.extend("- " + item for item in aggregate["limitations"])
    text.extend(["", "Raw flags, original outcomes, report errors and invalid/missing evidence remain in summary.json. A null is unavailable, never an inferred failure or zero.", ""])
    return "\n".join(text)


def build(plan_path, output):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Output already exists; use a new immutable summary directory")
    summary = summarize(plan_path)
    output.mkdir(parents=True)
    write_json(output / "summary.json", summary)
    write_json(output / "plan.snapshot.json", summary["plan"])
    write_json(output / "configuration.json", summary["configuration"])
    write_json(output / "aggregate.json", summary["aggregate"])
    write_json(output / "source-files.json", summary["source_files"])
    with (output / "attempts.jsonl").open("x", encoding="utf-8") as handle:
        for row in summary["attempts"]:
            handle.write(json.dumps(row, allow_nan=False) + "\n")
    with (output / "trials.csv").open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary["trials"][0]))
        writer.writeheader()
        for row in summary["trials"]:
            writer.writerow({key: json.dumps(value) if isinstance(value, (dict, list)) else value for key, value in row.items()})
    (output / "REPORT.md").write_text(markdown(summary), encoding="utf-8")
    write_json(output / "checksums.json", {path.name: sha256(path) for path in sorted(output.iterdir()) if path.is_file()})
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args(argv)
    summary = build(options.plan, options.output)
    print(json.dumps({"output": str(options.output.resolve()), "counts": summary["aggregate"]["counts"],
                      "note": "Evidence accounting completed; unscored or invalid trials remain visible"}))


if __name__ == "__main__":
    main()
