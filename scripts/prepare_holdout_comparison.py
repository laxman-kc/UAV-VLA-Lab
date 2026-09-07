#!/usr/bin/env python3
"""Freeze two fresh P14 holdout arms after the actual P13 report is recorded.

Copies the already chosen checkpoint contracts unchanged. Reads bounded metadata
and the completed P13 Markdown report only; no images, weights or holdout results.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
from pathlib import Path, PurePosixPath

import compare_navigation as comparator

REQUEST_SCHEMA = "vla.holdout-comparison-preparation.v1"
FIXED_P14_POLICY = "Same fixed final P12 candidate regardless of P13 outcome; no best-of or model switch. Report P13 outcomes honestly before creating the actual P14 plan. Both P14 arms require fresh post-freeze holdout execution; no improvement is promised."
SELECTION_CHECKS = {"complete_group_selected", "all_groups_disjoint", "original_eval_hash_matches_frozen_source",
                    "full_eval_partition_matches_original", "unique_loader_identity_per_episode", "all_original_selected_rows_preserved",
                    "existing_episode_metadata_checks_passed", "source_files_stable_during_validation"}
require = comparator.require


class Inputs(comparator.Inputs):
    def read(self, path, expected=None):
        path = Path(path)
        path = path if path.is_absolute() else self.root / path
        if path.suffix != ".md":
            return super().read(path, expected)
        require(path.name == "REPORT.md" and path.is_file() and not path.is_symlink() and path.stat().st_size <= 4 * 1024 * 1024,
                "Only the bounded completed P13 REPORT.md may be read as Markdown")
        data = path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        require(comparator.hash_value(expected) and expected == sha, "P13 Markdown SHA256 mismatch")
        record = {"path": str(path.resolve()), "bytes": len(data), "sha256": sha}
        previous = self.records.get(record["path"])
        require(previous is None or previous == record, "P13 Markdown changed during preparation")
        self.records[record["path"]] = record
        return data, record


def equal_record(value, actual):
    require(isinstance(value, dict) and value.get("sha256") == actual["sha256"] and value.get("bytes") == actual["bytes"],
            "Metadata bytes differ from their recorded hash/size")


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def episode(value, map_name):
    require(isinstance(value, str) and "\\" not in value, "Episode membership must be a POSIX path")
    p = PurePosixPath(value)
    require(not p.is_absolute() and ".." not in p.parts and len(p.parts) == 3 and str(p) == value
            and p.parts[0] == map_name and p.name == "merged_data.json" and "data6" not in value,
            "Invalid canonical frozen episode identity")
    return tuple(p.parts[:2])


def validate_holdout(split, split_record, selection, selection_record, rows, rows_record, dataset, dataset_record, candidate, started):
    require(split.get("schema_version") == "vla.splits.v1" and comparator.instant(split["frozen_at_utc"]) <= started, "A prior frozen split is required")
    map_name = split.get("map_id")
    require(isinstance(map_name, str) and map_name and "/" not in map_name, "Frozen map identity missing")
    groups = split.get("groups", {})
    require({"train", "development", "holdout", "demo", "unassigned"} == set(groups), "Complete frozen split groups required")
    seen = set()
    for group, entries in groups.items():
        require(isinstance(entries, list) and len(set(entries)) == len(entries), "Duplicate frozen group membership")
        require(type(split.get("counts", {}).get(group)) is int and split["counts"][group] == len(entries), "Frozen group count differs")
        for entry in entries:
            key = episode(entry, map_name)
            require(key not in seen, "Frozen split groups overlap")
            seen.add(key)
    ordered = [episode(item, map_name) for item in groups["holdout"]]
    require(len(ordered) == 10, "P14 requires the entire frozen ten-mission holdout group")
    require(selection.get("schema_version") == "vla.evaluation-batch.v1" and selection.get("kind") == "complete_frozen_evaluation_group_selection"
            and selection.get("group") == "holdout" and selection.get("execution_performed") is False, "Completed metadata-only holdout selection required")
    require(comparator.instant(split["frozen_at_utc"]) <= comparator.instant(selection["created_at_utc"]) <= started, "Selection chronology differs")
    require(selection.get("split_id") == split.get("split_id") and selection.get("split_frozen_at_utc") == split["frozen_at_utc"]
            and selection.get("map_name") == map_name and selection.get("unique_episodes") == 10
            and selection.get("selected_trajectories_in_frozen_order") == groups["holdout"], "Selection does not preserve the full frozen holdout order")
    require(all(selection.get("checks", {}).get(k) is True for k in SELECTION_CHECKS), "Original selection metadata gates are incomplete")
    require(selection.get("holdout_access", {}).get("pixel_files_opened") is False
            and selection["holdout_access"].get("pixel_files_rendered") is False, "Metadata-only selection scope must remain explicit")
    equal_record(selection["outputs"]["episodes.json"], rows_record)
    equal_record(selection["outputs"]["frozen_split.snapshot.json"], split_record)
    equal_record(selection["frozen_split_source"], split_record)
    original_sha = split.get("sources", {}).get("seen", {}).get("sha256")
    require(comparator.hash_value(original_sha) and selection.get("original_evaluation_source", {}).get("sha256") == original_sha,
            "Holdout selection is not bound to the frozen original evaluation source")
    require(isinstance(rows, list) and rows and len(rows) == selection.get("original_row_count")
            and canonical(rows) == selection.get("preserved_rows_canonical_sha256"), "Preserved holdout row bytes or count differ")
    by_episode, frame_keys = collections.defaultdict(list), set()
    for row in rows:
        require(isinstance(row, dict), "Holdout row must be an object")
        key = episode(row.get("json"), map_name)
        require(key in ordered and type(row.get("frame")) is int and row["frame"] >= 0, "Undeclared holdout row or invalid frame")
        require((key, row["frame"]) not in frame_keys, "Duplicate holdout trajectory/frame row")
        frame_keys.add((key, row["frame"])); by_episode[row["json"]].append(row)
    require(set(by_episode) == set(groups["holdout"]), "Missing or additional holdout episode rows")
    entries = selection.get("episodes", [])
    require(len(entries) == 10 and {e.get("json") for e in entries} == set(groups["holdout"]), "Selection per-episode ledger differs")
    indices = []
    for entry in entries:
        key = episode(entry["json"], map_name)
        require(entry.get("map_name") == key[0] and entry.get("episode_id") == key[1] and entry.get("metadata_validated") is True
                and entry.get("loader_identity") == {"map_name": key[0], "seq_name": key[1], "merged_json_relative": entry["json"]}, "Unique upstream loader identity or metadata gate differs")
        selected = by_episode[entry["json"]]
        require(entry.get("original_row_count") == len(selected) and entry.get("preserved_rows_canonical_sha256") == canonical(selected), "Per-mission preserved rows differ")
        source_indices = entry.get("source_row_indices", [])
        require(len(source_indices) == len(selected) and all(type(i) is int and i >= 0 for i in source_indices), "Original row index ledger differs")
        indices.extend(source_indices)
    require(len(set(indices)) == len(indices) and sorted(indices) == selection.get("selected_source_row_indices"), "Original row selection ledger is duplicated or incomplete")
    require(candidate.get("training_manifest_sha256") == dataset_record["sha256"], "Candidate training manifest identity changed")
    require(dataset.get("schema_version") == "vla.training-dataset.v1" and dataset.get("status") == "validated"
            and dataset.get("approval", {}).get("status") == "approved", "Actual reviewed training membership required")
    equal_record(dataset["split_manifest"], split_record)
    samples = dataset.get("samples", [])
    require(samples and dataset.get("sample_count") == len(samples), "Training sample membership is incomplete")
    require(all(s.get("split") == "train" and s.get("episode_id") in groups["train"] for s in samples), "Candidate training overlaps holdout or lies outside frozen train")
    return ordered


def prepare(request_path, output):
    require(not output.exists(), "Output must be new; no existing plan is overwritten")
    started = dt.datetime.now(dt.timezone.utc)
    inputs = Inputs(request_path.parent)
    raw, request_record = inputs.read(request_path)
    request = comparator.json_bytes(raw)
    require(request.get("schema_version") == REQUEST_SCHEMA, "Explicit P14 preparation request required")
    expected_keys = {"schema_version", "p13_paired_plan", "p13_comparison_result", "p13_report", "holdout_selection", "holdout_episode_rows",
                     "p13_reported_at_utc", "p13_reported_before_p14", "p13_result_used_for_selection", "automatic_checkpoint_selection",
                     "holdout_used_for_training_or_selection", "fresh_empty_remote_evidence_directories", "plan_id", "wall_limit_seconds", "arms"}
    require(set(request) == expected_keys, "Request fields must be explicit; configuration/checkpoint overrides are unsupported")
    require(request["p13_reported_before_p14"] is True and request["p13_result_used_for_selection"] is False
            and request["automatic_checkpoint_selection"] is False and request["holdout_used_for_training_or_selection"] is False,
            "Caller must record reported P13 results without holdout or automatic checkpoint selection")
    require(request["fresh_empty_remote_evidence_directories"] is True, "Fresh empty remote evidence destinations must be explicitly declared")
    reported = comparator.instant(request["p13_reported_at_utc"])
    plan, plan_record = inputs.document(request["p13_paired_plan"])
    result, result_record = inputs.document(request["p13_comparison_result"])
    report_raw, report_record = inputs.read(request["p13_report"]["path"], request["p13_report"]["sha256"])
    require(plan.get("schema_version") == comparator.SCHEMA and (plan.get("phase"), plan.get("split_group"), plan.get("purpose")) == ("P13", "development", "development_comparison"), "Actual P13 paired development plan required")
    require(plan.get("holdout_used_for_selection") is False and plan.get("automatic_checkpoint_selection") is False, "P13 selection declaration differs")
    require(type(plan.get("exact_discordant_test")) is bool, "P13 descriptive-test choice must be explicit and remains unchanged")
    require(result.get("schema_version") == "vla.paired-navigation-comparison.v1" and result.get("contract_status") == "passed"
            and result.get("phase") == "P13" and result.get("split_group") == "development" and result.get("selection_decision") is None,
            "Completed P13 comparison required; outcomes cannot select the P14 candidate")
    require(result.get("plan_sha256") == plan_record["sha256"] and result.get("plan_id") == plan.get("plan_id"), "P13 result does not bind this exact paired plan")
    require(comparator.instant(plan["frozen_at_utc"]) < comparator.instant(result["generated_at_utc"]) <= reported <= started, "P13 completion/report must precede actual P14 freeze")
    require(result.get("comparison_source_sha256") == comparator.digest(comparator.__file__), "Use the exact comparator version that produced the P13 report")
    require(report_raw == comparator.markdown(result).encode(), "P13 REPORT.md is not the complete comparator-generated report for these results")
    base = Path(plan_record["path"]).parent
    def document(reference):
        p = Path(reference["path"])
        return inputs.document({**reference, "path": str(p if p.is_absolute() else base / p)})
    shared = plan["shared_contract"]
    config = comparator.configuration(shared["configuration"])
    require(not comparator.MODEL_FIELDS.intersection(shared["configuration"]), "P13 shared configuration must exclude model identity")
    require(shared.get("retry_policy") == {"selection": "first_valid_attempt", "max_attempts_per_trial": 1}, "Only one observed attempt per trial is supported")
    split, split_record = document(shared["split"])
    runtime, runtime_record = document(shared["runtime_receipt"])
    require(runtime.get("schema_version") == "vla.runtime-receipt.v1" and runtime.get("runtime_id") == config["runtime_id"]
            and runtime.get("reset_protocol") == config["reset_protocol"] and runtime.get("upstream_revision") == split.get("upstream_code_revision"), "Existing shared runtime/source identity differs")
    require(isinstance(runtime.get("upstream_revision"), str) and comparator.re.fullmatch(r"[0-9a-f]{40}", runtime["upstream_revision"]), "Runtime requires an exact upstream revision")
    require(runtime.get("code", {}).get("reset_protocol.py", {}).get("sha256") == config["reset_helper_sha256"]
            and {"reset_protocol.py", "_aerovla_runtime_hooks.py"}.issubset(runtime.get("code", {}))
            and all(comparator.hash_value(v.get("sha256")) for v in runtime["code"].values()), "Runtime code inventory differs")
    require(comparator.instant(runtime["created_at_utc"]) <= comparator.instant(plan["frozen_at_utc"]), "P13 runtime was frozen too late")
    analyzer_path = Path(shared["analyzer_source"]["path"])
    require(analyzer_path.name == "analyze_baseline.py", "Declared baseline analyzer source required")
    _, analyzer_record = inputs.read(analyzer_path if analyzer_path.is_absolute() else base/analyzer_path, shared["analyzer_source"]["sha256"])
    _, helper_record = inputs.read(Path(__file__).resolve())
    _, comparator_record = inputs.read(Path(comparator.__file__).resolve())
    inventory = {r["path"]: r for r in result.get("input_sources", [])}
    require(len(inventory) == len(result.get("input_sources", [])) and inventory, "P13 input provenance is missing or duplicated")
    comparator.represented(inventory, plan_record)
    comparator.represented(inventory, split_record); comparator.represented(inventory, runtime_record)
    contracts, contract_records, prior_navs = {}, {}, {}
    for role in ("original", "candidate"):
        contract, record = document(plan["arms"][role]["checkpoint_contract"])
        comparator.validate_checkpoint(contract, role, comparator.instant(plan["frozen_at_utc"]))
        nav, nav_record = document(plan["arms"][role]["navigation_plan"])
        require(comparator.configuration(nav["configuration"]) == config and nav.get("retry_policy") == shared["retry_policy"], "P13 arm protocol differs from shared configuration")
        require(all(nav["configuration"][k] == contract[k] for k in comparator.MODEL_FIELDS), "P13 analyzed model identity differs")
        require(result["arms"][role].get("checkpoint_contract_sha256") == record["sha256"] and result["arms"][role].get("navigation_plan_sha256") == nav_record["sha256"], "Completed P13 arm did not use these exact contracts/plans")
        comparator.represented(inventory, record); comparator.represented(inventory, nav_record)
        contracts[role], contract_records[role], prior_navs[role] = contract, record, nav
    rule = plan.get("predeclared_P14_rule", {})
    require(rule == {"candidate_checkpoint_contract_sha256": contract_records["candidate"]["sha256"], "policy": FIXED_P14_POLICY}, "The predeclared fixed P14 candidate/rule differs")
    require(contracts["candidate"].get("parent_checkpoint_id") == contracts["original"]["checkpoint_id"]
            and contracts["candidate"]["base_manifest_sha256"] == contracts["original"]["base_manifest_sha256"], "Checkpoint parent/base identity differs")
    dataset_path = base/"metadata/training_dataset_manifest.json"
    dataset, dataset_record = inputs.document({"path": str(dataset_path), "sha256": contracts["candidate"]["training_manifest_sha256"]})
    selection, selection_record = inputs.document(request["holdout_selection"])
    rows, rows_record = inputs.document(request["holdout_episode_rows"])
    ordered = validate_holdout(split, split_record, selection, selection_record, rows, rows_record, dataset, dataset_record, contracts["candidate"], started)
    development = {episode(p, split["map_id"]) for p in split["groups"]["development"]}
    planned = [comparator.mission(m) for m in plan["missions"]]
    require(len(set(planned)) == len(planned) and set(planned) == development
            and [comparator.mission(t) for t in result["trials"]] == planned and result.get("planned_pairs") == len(planned), "P13 result does not account for the complete planned development group")
    old_session_ids = {s["session_id"] for nav in prior_navs.values() for s in nav["sessions"]}
    old_paths = {s[k] for nav in prior_navs.values() for s in nav["sessions"] for k in ("evidence_dir", "supervisor_report", "session_report") if k in s}
    identifiers = [request["plan_id"]]
    require(set(request["arms"]) == {"original", "candidate"}, "Exactly two future arms required")
    require(type(request["wall_limit_seconds"]) is int and request["wall_limit_seconds"] > 0, "Explicit positive shared session wall bound required")
    future_paths = []
    for role, slot in request["arms"].items():
        require(set(slot) == {"plan_id", "trial_prefix", "session_id", "evidence_dir", "supervisor_report", "session_report", "comparison_report_path", "analysis_source_path"}, "Predeclare exactly the future arm identity/path fields")
        identifiers.extend(slot[k] for k in ("plan_id", "trial_prefix", "session_id"))
        require(slot["session_id"] not in old_session_ids, "Future arm reuses a P13 session identity")
        for key in ("evidence_dir", "supervisor_report", "session_report", "comparison_report_path", "analysis_source_path"):
            value = slot[key]; path = PurePosixPath(value)
            require(isinstance(value, str) and path.is_absolute() and ".." not in path.parts and str(path) == value and "\\" not in value
                    and value not in old_paths, "Fresh canonical absolute future paths required")
        require(slot["analysis_source_path"] == slot["session_report"], "Future analysis source must identify the declared remote session report exactly")
        require(not Path(slot["comparison_report_path"]).exists(), "Future local receipt path already exists; no holdout receipt is read or reused")
        future_paths.extend(slot[k] for k in ("evidence_dir", "supervisor_report", "session_report", "comparison_report_path"))
    require(all(isinstance(v, str) and comparator.re.fullmatch(r"[A-Za-z0-9_.-]+", v) for v in identifiers) and len(set(identifiers)) == len(identifiers), "Future identifiers must be unique safe names")
    require(not set(identifiers).intersection({plan["plan_id"], *(nav["plan_id"] for nav in prior_navs.values())}), "P14 plan identity must be fresh")
    require(len(set(future_paths)) == len(future_paths), "Future arms share an evidence or receipt path")
    old_evidence = [PurePosixPath(nav_s["evidence_dir"]) for nav in prior_navs.values() for nav_s in nav["sessions"] if "evidence_dir" in nav_s]
    future_evidence = [PurePosixPath(s["evidence_dir"]) for s in request["arms"].values()]
    for a in future_evidence:
        require(not any(a == b or a.is_relative_to(b) or b.is_relative_to(a) for b in old_evidence), "Fresh holdout evidence must not overlap a P13 evidence directory")
    require(not future_evidence[0].is_relative_to(future_evidence[1]) and not future_evidence[1].is_relative_to(future_evidence[0]), "Holdout arm evidence directories overlap")
    inputs.recheck()
    output.mkdir(parents=True, exist_ok=False)
    def write(name, value):
        path = output/name; path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x") as f: f.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+"\n")
        return {"path": name, "sha256": comparator.digest(path)}
    def copy(name, record):
        data, _ = inputs.read(record["path"], record["sha256"])
        path = output/name; path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as f: f.write(data)
        return {"path": name, "sha256": comparator.digest(path)}
    copied = {key: copy("metadata/"+name, record) for key, name, record in (
        ("split", "frozen_split.json", split_record), ("runtime_receipt", "runtime_receipt.json", runtime_record),
        ("analyzer_source", "analyze_baseline.py", analyzer_record), ("training_manifest", "training_dataset_manifest.json", dataset_record),
        ("holdout_selection", "holdout_selection.json", selection_record), ("episode_rows", "holdout_episode_rows.json", rows_record),
        ("p13_paired_plan", "p13_paired_plan.json", plan_record), ("p13_result", "p13_comparison_result.json", result_record),
        ("p13_report", "REPORT.md", report_record), ("request", "preparation_request.json", request_record),
        ("helper", "prepare_holdout_comparison.py", helper_record), ("comparator", "compare_navigation.py", comparator_record))}
    checkpoint_refs = {role: copy("metadata/"+role+"-checkpoint.json", record) for role, record in contract_records.items()}
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    arms = {}
    for role, slot in request["arms"].items():
        trials = [{"trial_id": slot["trial_prefix"]+"-"+m[1], "map_name": m[0], "episode_id": m[1]} for m in ordered]
        nav = {"schema_version": "vla.navigation-plan.v1", "plan_id": slot["plan_id"], "frozen_at_utc": now,
               "configuration": {**config, **{k: contracts[role][k] for k in comparator.MODEL_FIELDS}}, "retry_policy": shared["retry_policy"],
               "trials": trials, "sessions": [{"session_id": slot["session_id"], "order": 1, "trial_ids": [t["trial_id"] for t in trials],
                   **{k: slot[k] for k in ("evidence_dir", "supervisor_report", "session_report")}}],
               "source_plan": {"split_sha256": split_record["sha256"], "runtime_receipt_sha256": runtime_record["sha256"],
                               "episode_rows_sha256": rows_record["sha256"], "selection_manifest_sha256": selection_record["sha256"]},
               "predeclared_wall_limit_seconds": request["wall_limit_seconds"], "source_p13_plan_sha256": plan_record["sha256"],
               "execution_scope": "Fresh post-freeze full ten-mission holdout confirmation, one observed attempt per mission. No P14 outcome exists in this preparation."}
        nav_ref = write("metadata/"+role+"-navigation-plan.json", nav)
        arms[role] = {"navigation_plan": nav_ref, "checkpoint_contract": checkpoint_refs[role], "reuse_existing_analysis_sha256": None,
                      "session_reports": [{"session_id": slot["session_id"], "path": slot["comparison_report_path"], "analysis_source_path": slot["analysis_source_path"]}]}
    paired = {"schema_version": comparator.SCHEMA, "plan_id": request["plan_id"], "frozen_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "phase": "P14", "purpose": "holdout_confirmation", "split_group": "holdout", "holdout_used_for_selection": False,
              "automatic_checkpoint_selection": False, "exact_discordant_test": plan["exact_discordant_test"],
              "missions": [{"map_name": m[0], "episode_id": m[1]} for m in ordered],
              "shared_contract": {"configuration": config, "retry_policy": shared["retry_policy"], "split": copied["split"],
                                  "runtime_receipt": copied["runtime_receipt"], "analyzer_source": copied["analyzer_source"], "episode_rows_sha256": rows_record["sha256"]},
              "arms": arms, "predeclared_P14_rule": rule,
              "p13_chronology_only": {"paired_plan": copied["p13_paired_plan"], "comparison_result": copied["p13_result"], "report": copied["p13_report"],
                                      "reported_at_utc": request["p13_reported_at_utc"], "result_used_for_selection": False,
                                      "report_delivery_evidence": "Caller records actual reporting; this helper does not independently verify delivery or trusted timestamps."}}
    plan_ref = write("paired-plan.json", paired)
    inputs.recheck()
    readiness = {"schema_version": "vla.holdout-comparison-readiness.v1", "status": "metadata_prepared_evaluation_not_run",
                 "created_at_utc": paired["frozen_at_utc"], "paired_plan": plan_ref, "planned_pairs": 10, "planned_fresh_attempts": 20,
                 "checkpoint_contract_bytes_unchanged": True, "candidate_checkpoint_contract_sha256": checkpoint_refs["candidate"]["sha256"],
                 "p13_outcomes_used_for_selection": False, "holdout_results_read": False, "images_read": False, "model_files_read": False,
                 "evaluation_executed": False, "input_sources": list(inputs.records.values()),
                 "full_comparator_validation": "Deferred until both actual fresh holdout analyses and session receipts exist; no synthetic outcome is produced here.",
                 "limitations": ["P13 result/report hashes establish recorded chronology and provenance; no P13 score controls checkpoint or mission selection.",
                                 "The actual released/candidate contracts are copied byte-for-byte. Model weight bytes and original full source lists are not reopened here.",
                                 "Training/holdout separation follows the exact reviewed manifest and frozen split; original model pretraining overlap remains unknown.",
                                 "Future local receipt existence is checked without opening it. Remote emptiness/report delivery are caller declarations, not independent host inspection.",
                                 "Output carries private metadata paths and is not a public release payload."]}
    write("readiness.json", readiness)
    write("checksums.json", {str(p.relative_to(output)): comparator.digest(p) for p in sorted(output.rglob("*")) if p.is_file() and p.name != "checksums.json"})
    return readiness


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.request.resolve(), args.output.resolve())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, "Holdout preparation rejected: "+str(exc)+"\n")
    print(json.dumps({k: result[k] for k in ("status", "planned_pairs", "planned_fresh_attempts", "paired_plan", "evaluation_executed")}))


if __name__ == "__main__":
    main()
