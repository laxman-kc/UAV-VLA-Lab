#!/usr/bin/env python3
"""Compare predeclared navigation trials using existing audited JSON only.

No evaluation, checkpoint selection, raw event/image loading or training occurs.
Input hashes and small metadata sidecars bind the declared comparison contract.
"""
import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re

SCHEMA = "vla.paired-navigation-plan.v1"
MODEL_FIELDS = {"checkpoint_id", "model_path"}
REQUIRED_CONFIG = {"task_mode", "protocol", "runtime_id", "require_recorded_runtime_id",
                   "reset_protocol", "reset_helper_sha256", "max_actions"}
TRIAL_FIELDS = ("observed_attempts", "attempts_beyond_cap", "joint_valid_attempts",
                "selected_attempt_id", "selected_session_id", "status", "upstream_success",
                "upstream_osr_success", "upstream_collision_flag", "terminal_loop_index",
                "distance_to_spawned_target_m", "termination_reason")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hash_value(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def instant(value):
    require(isinstance(value, str), "Missing timestamp")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "Timestamp must have an explicit timezone")
    return parsed.astimezone(dt.timezone.utc)


def json_bytes(data):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "Duplicate JSON key: " + key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError("Nonfinite JSON constant: " + value)
    def number(value):
        parsed = float(value)
        require(math.isfinite(parsed), "Nonfinite JSON number")
        return parsed
    return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid, parse_float=number)


class Inputs:
    def __init__(self, root):
        self.root = Path(root)
        self.records = {}

    def read(self, path, expected=None):
        path = Path(path)
        path = path if path.is_absolute() else self.root / path
        require(path.is_file() and not path.is_symlink(), "Input must be a regular nonsymlink file")
        require(path.suffix in {".json", ".py"} and path.stat().st_size <= 128 * 1024 * 1024,
                "Only bounded JSON metadata and declared Python source are read")
        data = path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        if expected is not None:
            require(hash_value(expected) and sha == expected, "Input SHA256 mismatch: " + path.name)
        record = {"path": str(path.resolve()), "sha256": sha, "bytes": len(data)}
        previous = self.records.get(record["path"])
        require(previous is None or previous == record, "Input changed during comparison")
        self.records[record["path"]] = record
        return data, record

    def document(self, reference):
        require(isinstance(reference, dict) and hash_value(reference.get("sha256")), "Expected hash-pinned metadata reference")
        require(Path(reference["path"]).suffix == ".json", "Metadata sidecar must be JSON")
        data, record = self.read(reference["path"], reference["sha256"])
        return json_bytes(data), record

    def recheck(self):
        for record in list(self.records.values()):
            self.read(record["path"], record["sha256"])


def mission(row):
    values = (row.get("map_name"), row.get("episode_id"))
    require(all(isinstance(v, str) and v and "/" not in v for v in values), "Invalid mission identity")
    return values


def configuration(value):
    require(isinstance(value, dict) and REQUIRED_CONFIG.issubset(value), "Incomplete execution configuration")
    require(value["require_recorded_runtime_id"] is True, "Recorded runtime identity is required")
    require(type(value["max_actions"]) is int and value["max_actions"] > 0, "Invalid action budget")
    require(hash_value(value["reset_helper_sha256"]), "Missing reset helper digest")
    require(all(isinstance(value[k], str) and value[k] for k in ("task_mode", "protocol", "runtime_id", "reset_protocol")), "Missing protocol identity")
    return {k: v for k, v in value.items() if k not in MODEL_FIELDS}


def validate_checkpoint(value, role, frozen):
    require(value.get("schema_version") == "vla.comparison-checkpoint.v1", "Unsupported checkpoint contract")
    require(instant(value["frozen_at_utc"]) <= frozen, "Checkpoint contract was frozen after paired plan")
    require(all(isinstance(value.get(k), str) and value[k] for k in MODEL_FIELDS), "Checkpoint/model identity missing")
    require(hash_value(value.get("base_manifest_sha256")) and hash_value(value.get("artifact_manifest_sha256")), "Checkpoint manifest hashes required")
    require(value.get("holdout_used_for_training_or_selection") is False, "Holdout use for training or selection is prohibited")
    files = value.get("model_files")
    require(isinstance(files, list) and files, "Declared checkpoint file inventory required")
    names = []
    for item in files:
        name = item.get("path")
        require(isinstance(name, str) and name and "\\" not in name, "Checkpoint file name missing or non-POSIX")
        path = PurePosixPath(name)
        require(path.parts and not path.is_absolute() and ".." not in path.parts, "Checkpoint file names must be relative")
        require(hash_value(item.get("sha256")) and type(item.get("bytes")) is int and item["bytes"] > 0, "Invalid checkpoint file inventory")
        names.append(name)
    require(len(set(names)) == len(names), "Duplicate checkpoint artifact")
    if role == "original":
        require(value.get("source_kind") == "released", "Original checkpoint must be declared released")
    else:
        require(value.get("source_kind") == "trained" and value.get("training_split") == "train", "Candidate must declare training-split provenance")
        require(value.get("supervision_mode") == "reviewed-expert", "P10 published-reference mechanics is not a P13/P14 trained candidate")
        require(hash_value(value.get("training_manifest_sha256")), "Candidate training manifest hash required")
    return value


def source_inventory(analysis):
    inventory = analysis.get("source_files")
    require(isinstance(inventory, list) and inventory, "Analysis has no source inventory")
    result = {}
    for record in inventory:
        require(isinstance(record, dict) and isinstance(record.get("path"), str), "Malformed analysis source record")
        require(record["path"] not in result, "Duplicate analysis source path")
        require(hash_value(record.get("sha256")) and type(record.get("bytes")) is int and record["bytes"] >= 0, "Invalid analysis source digest/size")
        result[record["path"]] = record
    return result


def represented(inventory, record, recorded_path=None):
    found = [r for r in inventory.values() if r["sha256"] == record["sha256"] and r["bytes"] == record["bytes"]
             and (recorded_path is None or r["path"] == recorded_path)]
    require(bool(found), "Metadata bytes are absent from the analysis source inventory")


def flags(outcome):
    require(isinstance(outcome, dict), "Scored attempt lacks outcome")
    values = outcome.get("upstream_flags", {})
    require(all(type(values.get(k)) is bool for k in ("success", "oracle_success", "collisions")), "Scored outcome flags must be actual booleans")
    distance = outcome.get("distance_to_target_m")
    require(type(distance) in (int, float) and math.isfinite(distance) and distance >= 0, "Scored target distance is invalid")
    require(type(outcome.get("step")) is int and outcome["step"] >= 0, "Scored step is invalid")
    require(isinstance(outcome.get("termination_reason"), str) and outcome["termination_reason"], "Scored termination reason missing")
    return values


def account(analysis, nav_plan):
    """Recompute first-observed-attempt selection; invalid rows never become zeros."""
    trials, attempts = analysis.get("trials"), analysis.get("attempts")
    require(isinstance(trials, list) and isinstance(attempts, list), "Missing trial/attempt accounting")
    require(isinstance(analysis.get("source_errors"), list), "Source-error accounting is missing")
    require([mission(t) for t in trials] == [mission(t) for t in nav_plan["trials"]], "Analysis trial order/membership differs from frozen plan")
    require([t.get("trial_id") for t in trials] == [t["trial_id"] for t in nav_plan["trials"]], "Analysis trial IDs differ from frozen plan")
    trial_ids = {t["trial_id"] for t in trials}
    declared_sessions = {s["session_id"]: set(s["trial_ids"]) for s in nav_plan["sessions"]}
    assignments = [tid for s in nav_plan["sessions"] for tid in s["trial_ids"]]
    require(len(declared_sessions) == len(nav_plan["sessions"]) and len(assignments) == len(set(assignments))
            and set(assignments) == trial_ids, "Frozen sessions must account for each trial exactly once")
    groups, seen = collections.defaultdict(list), set()
    for a in attempts:
        require(a.get("session_id") in declared_sessions, "Undeclared attempt session")
        observed = a.get("navigation_attempt_observed")
        require(type(observed) is bool, "Attempt observed flag must be boolean")
        require(type(a.get("joint_valid")) is bool, "Attempt joint-valid flag must be boolean")
        if not observed:
            require(a["joint_valid"] is False, "Unobserved attempt cannot be scored")
            continue
        require(a.get("trial_id") in trial_ids and a["trial_id"] in declared_sessions[a["session_id"]], "Unplanned or session-mismatched observed attempt")
        key = (a["session_id"], a.get("attempt_id"))
        require(isinstance(key[1], str) and key[1] and key not in seen, "Missing/duplicate observed attempt identity")
        seen.add(key)
        require(type(a.get("start_event_id")) is int and a["start_event_id"] > 0, "Observed start event is invalid")
        instant(a["start_wall_time_utc"])
        groups[a["trial_id"]].append(a)
        if a["joint_valid"]:
            require(a.get("status") == "valid_navigation_outcome" and a.get("within_declared_attempt_cap") is True, "Invalid attempt marked joint-valid")
            require(not analysis.get("source_errors") and not any(a.get(k) for k in ("joint_errors", "errors", "source_parse_errors", "session_report_errors")), "Joint-valid attempt contains integrity errors")
            audit = a.get("reset_audit", {})
            require(audit.get("accepted_reset_evidence") is True and not audit.get("errors"), "Scored attempt lacks accepted reset audit")
            flags(a.get("raw_outcome"))
    for row in trials:
        observed = groups[row["trial_id"]]
        require(len(observed) <= 1, "Observed attempt cap exceeded; pairing refuses retries")
        require(all(mission(a) == mission(row) for a in observed), "Attempt mission differs from its trial")
        chosen = observed[0] if observed and observed[0]["joint_valid"] else None
        expected = dict(observed_attempts=len(observed), attempts_beyond_cap=0,
                        joint_valid_attempts=int(chosen is not None), selected_attempt_id=None,
                        selected_session_id=None, status="unscored_observed_trial" if observed else "unstarted_trial",
                        upstream_success=None, upstream_osr_success=None, upstream_collision_flag=None,
                        terminal_loop_index=None, distance_to_spawned_target_m=None, termination_reason=None)
        if chosen:
            out = chosen["raw_outcome"]
            f = flags(out)
            expected.update(selected_attempt_id=chosen["attempt_id"], selected_session_id=chosen["session_id"],
                            status="scored_valid_trial", upstream_success=f["success"],
                            upstream_osr_success=f["success"] or f["oracle_success"], upstream_collision_flag=f["collisions"],
                            terminal_loop_index=out["step"], distance_to_spawned_target_m=out["distance_to_target_m"],
                            termination_reason=out["termination_reason"])
        require(all(row.get(k) == v and (type(row.get(k)) is type(v) or k == "distance_to_spawned_target_m") for k, v in expected.items()), "Trial summary disagrees with observed attempts")
    valid = [r for r in trials if r["status"] == "scored_valid_trial"]
    counts = dict(planned_unique_trials=len(trials), observed_attempts=len(seen), unplanned_observed_attempts=0,
                  observed_unique_trials=sum(bool(groups[r["trial_id"]]) for r in trials), valid_scored_trials=len(valid),
                  unscored_trials=len(trials)-len(valid), unstarted_trials=sum(r["status"] == "unstarted_trial" for r in trials), attempts_beyond_cap=0)
    for key, value in counts.items():
        require(type(analysis.get("aggregate", {}).get(key)) is int and analysis["aggregate"][key] == value, "Analysis aggregate accounting mismatch: " + key)
    for key, field in (("success_among_valid_trials", "upstream_success"), ("osr_among_valid_trials", "upstream_osr_success")):
        stat = analysis["aggregate"].get(key, {})
        numerator = sum(r[field] is True for r in valid)
        require(stat.get("numerator") == numerator and stat.get("denominator") == len(valid), "Analysis rate denominator/numerator mismatch")
    counts["all_attempt_records"] = len(attempts)
    counts["non_observed_attempt_records"] = len(attempts)-len(seen)
    counts["successes_among_own_valid_trials"] = sum(r["upstream_success"] is True for r in valid)
    counts["sr_among_own_valid_trials"] = counts["successes_among_own_valid_trials"] / len(valid) if valid else None
    return counts


def exact_discordant(gains, losses):
    """Two-sided equal-tail binomial probability conditional on discordant pairs."""
    n = gains + losses
    return min(1., 2 * sum(math.comb(n, k) for k in range(min(gains, losses)+1)) / (2**n)) if n else 1.


def paired_metrics(rows, field, exact):
    pairs = [r for r in rows if r["matched_valid_pair"]]
    transitions = {"both_failure": 0, "original_only_success": 0, "candidate_only_success": 0, "both_success": 0}
    for row in pairs:
        old, new = row["original_"+field], row["candidate_"+field]
        transitions["both_success" if old and new else "original_only_success" if old else "candidate_only_success" if new else "both_failure"] += 1
    n = len(pairs)
    old = transitions["both_success"] + transitions["original_only_success"]
    new = transitions["both_success"] + transitions["candidate_only_success"]
    return {"matched_valid_pairs": n, "original_successes": old, "candidate_successes": new,
            "original_sr": old/n if n else None, "candidate_sr": new/n if n else None,
            "paired_mean_difference_candidate_minus_original": (new-old)/n if n else None,
            "transitions": transitions,
            "exact_discordant_two_sided_p_descriptive": exact_discordant(transitions["candidate_only_success"], transitions["original_only_success"]) if n and exact else None,
            "exact_test_requested_in_plan": exact}


def compare(plan_path, original_path, candidate_path):
    inputs = Inputs(Path(plan_path).resolve().parent)
    plan_raw, plan_record = inputs.read(Path(plan_path).resolve())
    plan = json_bytes(plan_raw)
    require(plan.get("schema_version") == SCHEMA, "Unsupported paired plan")
    frozen = instant(plan["frozen_at_utc"])
    group = plan.get("split_group")
    require((plan.get("phase"), group, plan.get("purpose")) in {("P13", "development", "development_comparison"), ("P14", "holdout", "holdout_confirmation")}, "Phase/split/purpose mismatch; holdout cannot select a checkpoint")
    require(plan.get("holdout_used_for_selection") is False and plan.get("automatic_checkpoint_selection") is False, "No holdout or automatic checkpoint selection permitted")
    require(type(plan.get("exact_discordant_test")) is bool, "Predeclare whether descriptive exact test is requested")
    ordered = [mission(r) for r in plan["missions"]]
    require(0 < len(ordered) <= 1000 and len(set(ordered)) == len(ordered), "Paired mission list must be unique and bounded")
    shared = plan["shared_contract"]
    config = configuration(shared["configuration"])
    require(not (MODEL_FIELDS & set(shared["configuration"])), "Shared configuration must not contain model identity")
    require(shared.get("retry_policy") == {"selection": "first_valid_attempt", "max_attempts_per_trial": 1}, "Only one observed attempt is supported")
    require(type(shared["retry_policy"]["max_attempts_per_trial"]) is int, "Retry cap must be an integer")
    split, split_record = inputs.document(shared["split"])
    require(split.get("schema_version") == "vla.splits.v1" and instant(split["frozen_at_utc"]) <= frozen, "Invalid or late frozen split")
    groups = split.get("groups", {})
    memberships = {}
    for label, entries in groups.items():
        require(isinstance(entries, list) and len(set(entries)) == len(entries), "Duplicate or invalid split membership")
        for entry in entries:
            parts = PurePosixPath(entry).parts
            require(len(parts) == 3 and parts[-1] == "merged_data.json", "Invalid frozen split mission path")
            key = tuple(parts[:2])
            require(key not in memberships, "Overlapping frozen split groups")
            memberships[key] = label
    require(set(ordered) == {key for key, label in memberships.items() if label == group}, "Comparison must cover the entire frozen split group")
    receipt, receipt_record = inputs.document(shared["runtime_receipt"])
    require(receipt.get("schema_version") == "vla.runtime-receipt.v1" and receipt.get("runtime_id") == config["runtime_id"] and receipt.get("reset_protocol") == config["reset_protocol"], "Runtime receipt/configuration mismatch")
    require(instant(receipt["created_at_utc"]) <= frozen, "Runtime receipt postdates paired plan")
    require(isinstance(receipt.get("upstream_revision"), str) and re.fullmatch(r"[0-9a-f]{40}", receipt["upstream_revision"])
            and split.get("upstream_code_revision") == receipt["upstream_revision"], "Frozen split/runtime upstream source revision differs or is missing")
    code = receipt.get("code", {})
    require({"reset_protocol.py", "_aerovla_runtime_hooks.py"}.issubset(code) and all(hash_value(v.get("sha256")) for v in code.values()), "Incomplete runtime code inventory")
    require(code.get("reset_protocol.py", {}).get("sha256") == config["reset_helper_sha256"], "Runtime helper digest differs")
    require(hash_value(shared.get("episode_rows_sha256")), "Shared episode-row digest required")
    analyzer = shared["analyzer_source"]
    require(Path(analyzer["path"]).name == "analyze_baseline.py" and hash_value(analyzer.get("sha256")), "Declare the baseline analyzer source and its hash")
    inputs.read(analyzer["path"], analyzer["sha256"])
    arms, arm_counts, contracts = {}, {}, {}
    for role, path in (("original", original_path), ("candidate", candidate_path)):
        definition = plan["arms"][role]
        data, analysis_record = inputs.read(Path(path).resolve())
        analysis = json_bytes(data)
        require(analysis.get("schema_version") == "vla.baseline-reset-analysis.v1", "Only completed baseline-reset analysis v1 is supported")
        generated = instant(analysis["generated_at_utc"])
        nav, nav_record = inputs.document(definition["navigation_plan"])
        require(nav.get("schema_version") == "vla.navigation-plan.v1", "Navigation plan schema mismatch")
        require(analysis.get("plan_sha256") == nav_record["sha256"] and analysis.get("plan_id") == nav.get("plan_id"), "Analysis is not bound to the supplied navigation plan")
        require(instant(nav["frozen_at_utc"]) <= frozen, "Navigation plan postdates paired-plan freeze")
        require(configuration(nav["configuration"]) == config and analysis["configuration"] == nav["configuration"], "Task/protocol/reset/runtime/action configuration differs")
        require(nav.get("retry_policy") == shared["retry_policy"], "Retry policy differs")
        require([mission(t) for t in nav["trials"]] == ordered, "Ordered planned missions differ")
        require(len({t["trial_id"] for t in nav["trials"]}) == len(ordered), "Duplicate frozen trial ID")
        source = nav.get("source_plan", {})
        for key, expected in (("split_sha256", split_record["sha256"]), ("runtime_receipt_sha256", receipt_record["sha256"]), ("episode_rows_sha256", shared["episode_rows_sha256"])):
            require(source.get(key) == expected, "Navigation source contract differs: " + key)
        require(hash_value(source.get("selection_manifest_sha256")), "Selection metadata hash missing")
        inventory = source_inventory(analysis)
        represented(inventory, nav_record)
        represented(inventory, receipt_record)
        for name in ("reset_protocol.py", "_aerovla_runtime_hooks.py"):
            require(any(r["sha256"] == code[name]["sha256"] for r in inventory.values()), "Analysis inventory lacks pinned runtime source: " + name)
        checkpoint, checkpoint_record = inputs.document(definition["checkpoint_contract"])
        contracts[role] = validate_checkpoint(checkpoint, role, frozen)
        require(all(checkpoint[k] == nav["configuration"][k] for k in MODEL_FIELDS), "Declared checkpoint differs from analyzed configuration")
        audits = analysis.get("session_reset_audits", [])
        require(len(audits) == len(nav["sessions"]) and len({a["session_id"] for a in audits}) == len(audits)
                and {a["session_id"] for a in audits} == {s["session_id"] for s in nav["sessions"]}, "Missing/duplicate reset-audit session accounting")
        for audit in audits:
            require(isinstance(audit.get("errors"), list), "Session reset errors are missing")
            require(not audit["errors"] or not any(a.get("joint_valid") is True for a in analysis["attempts"] if a.get("session_id") == audit["session_id"]), "Joint-valid attempt belongs to a rejected reset session")
        session_defs = definition["session_reports"]
        require(len({r["session_id"] for r in session_defs}) == len(session_defs) and {r["session_id"] for r in session_defs} == {s["session_id"] for s in nav["sessions"]}, "Session receipt mapping incomplete or duplicate")
        first_start = None
        for s in session_defs:
            raw, record = inputs.read(s["path"])
            represented(inventory, record, s["analysis_source_path"])
            report = json_bytes(raw)
            require(report.get("schema_version") == "vla.simulation-session.v1", "Completed simulation-session receipt required")
            start, finish = instant(report["started_at_utc"]), instant(report["finished_at_utc"])
            require(start < finish <= generated, "Session was unfinished or analysis predates its completion")
            require(start > instant(nav["frozen_at_utc"]), "Navigation plan was not frozen before execution")
            first_start = min(first_start, start) if first_start else start
            for a in analysis["attempts"]:
                if a.get("session_id") == s["session_id"] and a.get("navigation_attempt_observed") is True:
                    require(start <= instant(a["start_wall_time_utc"]) <= finish, "Attempt start falls outside its session receipt")
        require(first_start is not None, "At least one completed session receipt required")
        reuse = definition.get("reuse_existing_analysis_sha256")
        if role == "candidate":
            require(reuse is None and first_start > frozen, "Candidate evaluation must start after the paired plan; no candidate reuse")
        elif first_start <= frozen:
            require(group == "development", "Holdout confirmation requires both arms to start after the paired plan")
            require(reuse == analysis_record["sha256"], "Original reuse requires explicit exact analysis hash in the paired plan")
        else:
            require(reuse is None, "Fresh original evaluation must not claim reuse")
        arm_counts[role] = account(analysis, nav)
        arms[role] = {"analysis": analysis, "analysis_sha256": analysis_record["sha256"],
                      "navigation_plan_sha256": nav_record["sha256"], "checkpoint_contract_sha256": checkpoint_record["sha256"],
                      "reused_original_analysis": role == "original" and first_start <= frozen}
    require(contracts["original"]["checkpoint_id"] != contracts["candidate"]["checkpoint_id"], "Comparison checkpoints must have distinct identities")
    require(contracts["candidate"].get("parent_checkpoint_id") == contracts["original"]["checkpoint_id"], "Candidate parent checkpoint differs from original")
    require(contracts["original"]["base_manifest_sha256"] == contracts["candidate"]["base_manifest_sha256"], "Frozen base model identity differs")
    require(contracts["original"]["artifact_manifest_sha256"] != contracts["candidate"]["artifact_manifest_sha256"], "Candidate artifact identity must differ from original")
    rows = []
    for index, (old, new) in enumerate(zip(arms["original"]["analysis"]["trials"], arms["candidate"]["analysis"]["trials"]), 1):
        paired = old["status"] == new["status"] == "scored_valid_trial"
        row = {"ordinal": index, "map_name": old["map_name"], "episode_id": old["episode_id"], "matched_valid_pair": paired}
        for role, trial in (("original", old), ("candidate", new)):
            for key in ("trial_id", *TRIAL_FIELDS):
                row[role+"_"+key] = trial.get(key)
        row["success_difference_candidate_minus_original"] = int(new["upstream_success"])-int(old["upstream_success"]) if paired else None
        rows.append(row)
    inputs.recheck()
    result = {"schema_version": "vla.paired-navigation-comparison.v1", "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "plan_id": plan["plan_id"], "plan_sha256": plan_record["sha256"], "phase": plan["phase"], "split_group": group,
              "contract_status": "passed", "selection_decision": None, "planned_pairs": len(rows),
              "matched_valid_pairs": sum(r["matched_valid_pair"] for r in rows), "unmatched_or_invalid_pairs": sum(not r["matched_valid_pair"] for r in rows),
              "arm_counts": arm_counts, "success": paired_metrics(rows, "upstream_success", plan["exact_discordant_test"]),
              "oracle_success": paired_metrics(rows, "upstream_osr_success", False), "trials": rows,
              "arms": {role: {k: v for k, v in arm.items() if k != "analysis"} for role, arm in arms.items()},
              "attempts": {role: arm["analysis"]["attempts"] for role, arm in arms.items()},
              "input_sources": list(inputs.records.values()), "comparison_source_sha256": digest(__file__),
              "limitations": [
                  "Fixed missions from one map and correlated behavior limit population interpretation; prior overlap with model training may be unresolved.",
                  "Paired SR and binary mean difference use matched valid pairs only. Unstarted/invalid outcomes are null, never imputed failures; differing missingness can bias this subset.",
                  "The optional exact discordant-binomial value is descriptive and conditional on discordant pairs under equal directional probability; it is not a causal, independence or generalization guarantee.",
                  "Upstream success is benchmark navigation success, not physical touchdown. Endpoint contact and upstream heuristic collision remain distinct raw fields.",
                  "This read-only comparison validates metadata hashes and accounting; it does not rerun raw-event/reset checks, verify remote model bytes or prove the declared analyzer/training code produced its input JSON.",
                  "A local freeze timestamp and hash binding provide recorded ordering, not independent trusted timestamping or proof that holdout was never previously consulted.",
                  "No checkpoint usefulness, promotion, stopping, selection or adaptation-completion decision is made. Holdout is confirmation-only and cannot select a checkpoint.",
                  "Output retains private input provenance and all attempt records; it is not automatically a public release payload."]}
    return result


def markdown(result):
    metric = result["success"]
    lines = ["# Predeclared paired navigation comparison", "", f"Plan `{result['plan_id']}`: **{result['matched_valid_pairs']}/{result['planned_pairs']} matched valid pairs**; {result['unmatched_or_invalid_pairs']} pairs remain unscored. No checkpoint selection decision.", "",
             f"Within those same pairs: original success **{metric['original_successes']}/{metric['matched_valid_pairs']}**, candidate success **{metric['candidate_successes']}/{metric['matched_valid_pairs']}**. Paired mean difference (candidate minus original): **{metric['paired_mean_difference_candidate_minus_original']}**.", "",
             f"Exact discordant two-sided descriptive p: **{metric['exact_discordant_two_sided_p_descriptive']}** (null means not requested or no valid pairs).", "",
             "| Outcome transition | Count |", "|---|---:|"]
    lines.extend(f"| {key} | {value} |" for key, value in metric["transitions"].items())
    lines.extend(["", "| Arm | Planned | Observed attempts | Own valid | Unscored | Unstarted |", "|---|---:|---:|---:|---:|---:|"])
    for role, c in result["arm_counts"].items():
        lines.append(f"| {role} | {c['planned_unique_trials']} | {c['observed_attempts']} | {c['valid_scored_trials']} | {c['unscored_trials']} | {c['unstarted_trials']} |")
    lines.extend(["", "[Per-mission CSV](trials.csv) retains every planned pair. [comparison.json](comparison.json) retains all input hashes, attempt records, arm coverage and secondary OSR. Blank CSV outcome cells are unavailable, never failures.", ""])
    lines.extend("- "+text for text in result["limitations"])
    return "\n".join(lines)+"\n"


def write_result(result, output):
    output = Path(output)
    require(not output.exists(), "Output must be a fresh path")
    output.mkdir(parents=True)
    (output / "comparison.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    with (output / "trials.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result["trials"][0]))
        writer.writeheader()
        writer.writerows(result["trials"])
    (output / "REPORT.md").write_text(markdown(result))
    (output / "checksums.sha256").write_text("".join(digest(output / name)+"  "+name+"\n" for name in ("comparison.json", "trials.csv", "REPORT.md")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "original", "candidate", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    try:
        require(not args.output.exists(), "Output must be a fresh path")
        result = compare(args.plan, args.original, args.candidate)
        write_result(result, args.output)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, "Comparison contract rejected: "+str(exc)+"\n")
    print(json.dumps({k: result[k] for k in ("contract_status", "planned_pairs", "matched_valid_pairs", "unmatched_or_invalid_pairs", "selection_decision")}))
    return 0 if result["unmatched_or_invalid_pairs"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
