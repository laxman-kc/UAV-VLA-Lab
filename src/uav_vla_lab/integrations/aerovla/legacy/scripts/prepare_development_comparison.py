#!/usr/bin/env python3
"""Freeze P13 metadata from an actual passed P12 receipt and exact P08 reuse.

Reads bounded JSON/source metadata only. No weights, events, images, evaluation,
training, result creation or checkpoint selection. P14 remains a later plan.
"""
import argparse
import datetime as dt
import json
from pathlib import Path, PurePosixPath

import compare_navigation as comparator

REQUEST_SCHEMA = "vla.development-comparison-preparation.v1"
REFERENCES = ("original_navigation_plan", "original_analysis", "frozen_split", "runtime_receipt",
              "episode_selection", "episode_rows", "analyzer_source")
require = comparator.require


def equal_record(record, actual):
    require(isinstance(record, dict) and record.get("sha256") == actual["sha256"] and record.get("bytes") == actual["bytes"], "Receipt does not identify the supplied actual metadata bytes")


def validate_p12(checkpoint, run, dataset, parent, records, started):
    require(checkpoint.get("schema_version") == "vla.training-checkpoint.v1" and checkpoint.get("status") == "mechanics_verified" and checkpoint.get("phase") == "P12", "A real completed P12 checkpoint receipt is required; P10 is not a candidate")
    require(run.get("schema_version") == "vla.training-run.v1" and run.get("phase") == "P12" and run.get("status") == "passed" and run.get("stage") == "complete", "P12 execution must have actually passed")
    config = checkpoint.get("config", {})
    require(config == run.get("config") and config.get("phase") == "P12" and config.get("supervision_mode") == "reviewed-expert" and config.get("validate_only") is False, "P12 config must match an executed reviewed-expert run")
    steps = checkpoint.get("optimizer_steps")
    require(type(steps) is int and steps > 0 and steps == config.get("steps") == run.get("completed_optimizer_steps"), "Completed optimizer steps differ from the frozen final-step budget")
    require(checkpoint.get("selection_rule") == config.get("selection_rule") == "fixed_final_step_candidate", "Only the recorded fixed-final-step checkpoint is supported")
    require(comparator.instant(run["started_at_utc"]) < comparator.instant(run["completed_at_utc"]) <= started, "Training receipt chronology is invalid or incomplete")
    for key in ("parent", "dataset", "reload_validation", "checkpoint_files", "code"):
        require(checkpoint.get(key) == run.get(key), "Checkpoint and completed-run receipts disagree: " + key)
    reload = checkpoint["reload_validation"]
    require(checkpoint.get("projector_preserved_and_saved") is True and all(reload.get(k) is True for k in ("exact_adapter_and_projector_hashes_match", "last_token_logits_allclose", "loss_isclose")), "Saved/reloaded adapter and projector validation did not pass")
    require(parent.get("schema_version") == "vla.adapter-parent.v1" and parent.get("preserve_projector") is True, "Released parent receipt is incomplete")
    equal_record(checkpoint["parent"]["manifest"], records["released_parent_manifest"])
    require(all(checkpoint["parent"].get(k) == parent.get(k) for k in ("checkpoint_id", "base", "adapter")), "P12 parent inventory differs from the supplied released parent")
    equal_record(checkpoint["dataset"]["dataset_manifest"], records["training_dataset_manifest"])
    require(checkpoint["dataset"].get("status") == "passed" and checkpoint["dataset"].get("supervision_mode") == "reviewed-expert", "Training dataset contract did not pass reviewed-expert mode")
    require(dataset.get("schema_version") == "vla.training-dataset.v1" and dataset.get("status") == "validated" and dataset.get("approval", {}).get("status") == "approved", "Actual reviewed training manifest is required")
    require(dataset.get("approval") == checkpoint["dataset"].get("approval") and dataset.get("label_policy") == checkpoint["dataset"].get("label_policy"), "P12 did not use these reviewed dataset semantics")
    require(len(dataset.get("samples", [])) == checkpoint["dataset"].get("sample_count") and set(checkpoint["dataset"].get("episode_ids", [])) == {s["episode_id"] for s in dataset["samples"]}, "Training sample membership differs from its executed contract")
    model_path = PurePosixPath(config["output"]) / "checkpoint"
    require(model_path.is_absolute(), "Checkpoint output must retain the actual absolute host path")
    files = []
    for record in checkpoint["checkpoint_files"]:
        path = PurePosixPath(record["path"])
        require(path.parent == model_path and comparator.hash_value(record.get("sha256")) and type(record.get("bytes")) is int and record["bytes"] > 0, "Checkpoint file inventory differs from the actual saved directory")
        files.append({"path": path.name, "sha256": record["sha256"], "bytes": record["bytes"]})
    names = {f["path"] for f in files}
    require(len(files) == len(names) and {"adapter_model.safetensors", "adapter_config.json"}.issubset(names), "Saved candidate inventory is incomplete or duplicated")
    return {"model_path": str(model_path), "model_files": files, "optimizer_steps": steps, "training_completed_at_utc": run["completed_at_utc"]}


def validate_baseline(documents, records, inputs, request, started):
    nav, analysis, split, runtime, selection, episodes = (documents[k] for k in REFERENCES[:-1])
    require(nav.get("schema_version") == "vla.navigation-plan.v1" and analysis.get("schema_version") == "vla.baseline-reset-analysis.v1", "Original P08 navigation plan/reset-aware analysis required")
    require(analysis.get("plan_sha256") == records["original_navigation_plan"]["sha256"] and analysis.get("plan_id") == nav.get("plan_id"), "Original analysis is not bound to the actual navigation plan")
    require(analysis.get("configuration") == nav.get("configuration"), "Original analyzed execution config differs")
    config = comparator.configuration(nav["configuration"])
    require(nav.get("retry_policy") == {"selection": "first_valid_attempt", "max_attempts_per_trial": 1}, "Exactly one observed attempt per development trial is required")
    require(split.get("schema_version") == "vla.splits.v1" and comparator.instant(split["frozen_at_utc"]) <= started, "Frozen split is missing or future")
    memberships = {}
    for group, values in split["groups"].items():
        require(isinstance(values, list) and len(values) == len(set(values)), "Malformed split group")
        for value in values:
            path = PurePosixPath(value)
            require(not path.is_absolute() and len(path.parts) == 3 and path.name == "merged_data.json" and tuple(path.parts[:2]) not in memberships, "Invalid or overlapping frozen membership")
            memberships[tuple(path.parts[:2])] = group
    missions = [comparator.mission(t) for t in nav["trials"]]
    require(len(missions) == len(set(missions)) and set(missions) == {m for m, g in memberships.items() if g == "development"}, "Original must cover the entire frozen development group")
    require(selection.get("schema_version") == "vla.evaluation-batch.v1" and selection.get("group") == "development" and selection.get("execution_performed") is False, "Actual prepared development selection required")
    equal_record(selection["outputs"]["episodes.json"], records["episode_rows"])
    equal_record(selection["outputs"]["frozen_split.snapshot.json"], records["frozen_split"])
    require({tuple(PurePosixPath(row["json"]).parts[:2]) for row in episodes} == set(missions), "Episode rows do not cover precisely the original missions")
    for key, expected in (("split_sha256", records["frozen_split"]["sha256"]), ("runtime_receipt_sha256", records["runtime_receipt"]["sha256"]), ("episode_rows_sha256", records["episode_rows"]["sha256"]), ("selection_manifest_sha256", records["episode_selection"]["sha256"])):
        require(nav["source_plan"].get(key) == expected, "Original source contract differs: " + key)
    require(runtime.get("schema_version") == "vla.runtime-receipt.v1" and runtime.get("runtime_id") == config["runtime_id"] and runtime.get("reset_protocol") == config["reset_protocol"] and runtime.get("upstream_revision") == split.get("upstream_code_revision"), "Shared runtime/split/config identity differs")
    require(isinstance(runtime.get("upstream_revision"), str) and comparator.re.fullmatch(r"[0-9a-f]{40}", runtime["upstream_revision"]), "Runtime upstream revision is not an exact commit")
    require({"reset_protocol.py", "_aerovla_runtime_hooks.py"}.issubset(runtime.get("code", {})) and all(comparator.hash_value(r.get("sha256")) for r in runtime["code"].values()), "Runtime code inventory is incomplete")
    require(runtime.get("code", {}).get("reset_protocol.py", {}).get("sha256") == config["reset_helper_sha256"], "Reset helper digest differs from recorded runtime")
    require(comparator.instant(runtime["created_at_utc"]) <= comparator.instant(nav["frozen_at_utc"]) < comparator.instant(analysis["generated_at_utc"]) <= started, "Original plan/runtime/analysis chronology differs")
    inventory = comparator.source_inventory(analysis)
    for key in ("original_navigation_plan", "runtime_receipt"):
        comparator.represented(inventory, records[key])
    for name in ("reset_protocol.py", "_aerovla_runtime_hooks.py"):
        require(any(r["sha256"] == runtime["code"][name]["sha256"] for r in inventory.values()), "Original inventory lacks declared runtime code")
    accounting = comparator.account(analysis, nav)
    require(not analysis.get("source_errors"), "Original analysis has unresolved source errors")
    audits = analysis.get("session_reset_audits", [])
    require(len(audits) == len(nav["sessions"]) and len({a["session_id"] for a in audits}) == len(audits)
            and {a["session_id"] for a in audits} == {s["session_id"] for s in nav["sessions"]}, "Missing/duplicate original reset-session audits")
    for audit in audits:
        require(isinstance(audit.get("errors"), list), "Original session reset errors are missing")
        require(not audit["errors"] or not any(a.get("joint_valid") is True for a in analysis["attempts"] if a.get("session_id") == audit["session_id"]), "Scored original attempt belongs to a rejected reset session")
    mappings = request.get("original_session_reports", [])
    require(len(mappings) == len(nav["sessions"]) and {m["session_id"] for m in mappings} == {s["session_id"] for s in nav["sessions"]}, "Map every original session receipt explicitly")
    mapped = []
    for item in mappings:
        report, record = inputs.document(item)
        comparator.represented(inventory, record, item["analysis_source_path"])
        require(report.get("schema_version") == "vla.simulation-session.v1", "Original session receipt schema differs")
        start, finish = comparator.instant(report["started_at_utc"]), comparator.instant(report["finished_at_utc"])
        require(comparator.instant(nav["frozen_at_utc"]) < start < finish <= comparator.instant(analysis["generated_at_utc"]), "Original session was not frozen/finished before analysis")
        for attempt in analysis["attempts"]:
            if attempt.get("session_id") == item["session_id"] and attempt.get("navigation_attempt_observed") is True:
                require(start <= comparator.instant(attempt["start_wall_time_utc"]) <= finish, "Original attempt lies outside its session")
        mapped.append({"session_id": item["session_id"], "record": record, "analysis_source_path": item["analysis_source_path"]})
    require(Path(records["analyzer_source"]["path"]).name == "analyze_baseline.py", "Declare the actual analyze_baseline.py source")
    return {"configuration": config, "missions": missions, "accounting": accounting, "session_reports": mapped}


def prepare(request_path, p12_checkpoint_manifest, p12_report, training_dataset_manifest, released_parent_manifest, output):
    require(not output.exists(), "Output must be new")
    started = dt.datetime.now(dt.timezone.utc)
    inputs = comparator.Inputs(request_path.parent)
    _, helper_record = inputs.read(Path(__file__).resolve())
    _, comparator_record = inputs.read(Path(comparator.__file__).resolve())
    raw, request_record = inputs.read(request_path)
    request = comparator.json_bytes(raw)
    require(request.get("schema_version") == REQUEST_SCHEMA, "Explicit P13 preparation request required")
    require(request.get("holdout_used_for_training_or_selection") is False and request.get("automatic_checkpoint_selection") is False, "Caller must declare no holdout-based or automatic checkpoint selection")
    require(type(request.get("exact_discordant_test")) is bool, "Predeclare the descriptive exact-test choice")
    for field in ("plan_id", "candidate_plan_id", "candidate_trial_prefix"):
        require(isinstance(request.get(field), str) and request[field], "Missing planned identifier: " + field)
    documents, records = {}, {}
    for key in REFERENCES:
        if key == "analyzer_source":
            _, records[key] = inputs.read(request[key]["path"], request[key]["sha256"])
        else:
            documents[key], records[key] = inputs.document(request[key])
    for key, path in (("p12_checkpoint_manifest", p12_checkpoint_manifest), ("p12_report", p12_report),
                      ("training_dataset_manifest", training_dataset_manifest), ("released_parent_manifest", released_parent_manifest)):
        raw, records[key] = inputs.read(path)
        documents[key] = comparator.json_bytes(raw)
    trained = validate_p12(documents["p12_checkpoint_manifest"], documents["p12_report"], documents["training_dataset_manifest"], documents["released_parent_manifest"], records, started)
    baseline = validate_baseline(documents, records, inputs, request, started)
    parent, checkpoint = documents["released_parent_manifest"], documents["p12_checkpoint_manifest"]
    original_config = documents["original_navigation_plan"]["configuration"]
    require(parent["checkpoint_id"] == original_config["checkpoint_id"] and checkpoint["config"]["adapter"] == original_config["model_path"], "P12 parent is not the original recorded baseline checkpoint/path")
    equal_record(documents["training_dataset_manifest"]["split_manifest"], records["frozen_split"])
    require(all(s.get("split") == "train" and s["episode_id"] in documents["frozen_split"]["groups"]["train"] for s in documents["training_dataset_manifest"]["samples"]), "Candidate training rows are outside frozen train")
    slot = request["candidate_session"]
    for field in ("session_id", "evidence_dir", "supervisor_report", "session_report", "comparison_report_path", "analysis_source_path"):
        require(isinstance(slot.get(field), str) and slot[field], "Predeclare every future candidate session path: " + field)
    require(type(request.get("candidate_wall_limit_seconds")) is int and request["candidate_wall_limit_seconds"] > 0, "Candidate session wall bound required")
    inputs.recheck()
    output.mkdir(parents=True)
    metadata = output / "metadata"
    metadata.mkdir()
    def write(name, value):
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
        return {"path": name, "sha256": comparator.digest(path)}
    def copy_record(name, record):
        data, _ = inputs.read(record["path"], record["sha256"])
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {"path": name, "sha256": comparator.digest(path)}
    copied = {key: copy_record("metadata/" + ("analyze_baseline.py" if key == "analyzer_source" else key + ".json"), record) for key, record in records.items()}
    copy_record("metadata/preparation_request.json", request_record)
    copy_record("metadata/prepare_development_comparison.py", helper_record)
    copy_record("metadata/compare_navigation.py", comparator_record)
    checkpoint_frozen = dt.datetime.now(dt.timezone.utc)
    now = checkpoint_frozen.isoformat()
    base_ref = write("metadata/base-inventory.json", {"schema_version": "vla.recorded-base-inventory.v1", "source_parent_manifest_sha256": records["released_parent_manifest"]["sha256"], **parent["base"]})
    released_ref = write("metadata/released-adapter-inventory.json", {"schema_version": "vla.recorded-adapter-inventory.v1", "source_parent_manifest_sha256": records["released_parent_manifest"]["sha256"], **parent["adapter"]})
    common = {"schema_version": "vla.comparison-checkpoint.v1", "frozen_at_utc": now, "base_manifest_sha256": base_ref["sha256"], "holdout_used_for_training_or_selection": False}
    original = {**common, "source_kind": "released", "checkpoint_id": original_config["checkpoint_id"], "model_path": original_config["model_path"], "artifact_manifest_sha256": released_ref["sha256"], "model_files": parent["adapter"]["files"]}
    candidate = {**common, "source_kind": "trained", "checkpoint_id": "p12-fixed-final-" + records["p12_checkpoint_manifest"]["sha256"][:16],
                 "model_path": trained["model_path"], "artifact_manifest_sha256": records["p12_checkpoint_manifest"]["sha256"], "model_files": trained["model_files"],
                 "parent_checkpoint_id": original["checkpoint_id"], "training_split": "train", "supervision_mode": "reviewed-expert",
                 "training_manifest_sha256": records["training_dataset_manifest"]["sha256"], "source_training_report_sha256": records["p12_report"]["sha256"]}
    for value, role in ((original, "original"), (candidate, "candidate")):
        comparator.validate_checkpoint(value, role, checkpoint_frozen)
    original_ref, candidate_ref = write("metadata/original-checkpoint.json", original), write("metadata/candidate-checkpoint.json", candidate)
    trial_rows = [{"trial_id": request["candidate_trial_prefix"] + "-" + mission[1], "map_name": mission[0], "episode_id": mission[1]} for mission in baseline["missions"]]
    candidate_nav = {"schema_version": "vla.navigation-plan.v1", "plan_id": request["candidate_plan_id"], "frozen_at_utc": now,
                     "configuration": {**baseline["configuration"], "checkpoint_id": candidate["checkpoint_id"], "model_path": candidate["model_path"]},
                     "retry_policy": documents["original_navigation_plan"]["retry_policy"], "trials": trial_rows,
                     "sessions": [{"session_id": slot["session_id"], "order": 1, "trial_ids": [t["trial_id"] for t in trial_rows],
                                   **{k: slot[k] for k in ("evidence_dir", "supervisor_report", "session_report")}}],
                     "source_plan": {k: documents["original_navigation_plan"]["source_plan"][k] for k in ("split_sha256", "runtime_receipt_sha256", "episode_rows_sha256", "selection_manifest_sha256")},
                     "predeclared_wall_limit_seconds": request["candidate_wall_limit_seconds"],
                     "execution_scope": "Future full frozen development group, one observed attempt each, fixed final P12 checkpoint; no outcomes exist in this preparation",
                     "source_original_plan_sha256": records["original_navigation_plan"]["sha256"]}
    nav_ref = write("metadata/candidate-navigation-plan.json", candidate_nav)
    sessions = []
    for index, item in enumerate(baseline["session_reports"]):
        ref = copy_record(f"metadata/original-session-{index:02d}.json", item["record"])
        sessions.append({"session_id": item["session_id"], "path": ref["path"], "analysis_source_path": item["analysis_source_path"]})
    paired_at = dt.datetime.now(dt.timezone.utc).isoformat()
    plan = {"schema_version": comparator.SCHEMA, "plan_id": request["plan_id"], "frozen_at_utc": paired_at, "phase": "P13",
            "purpose": "development_comparison", "split_group": "development", "holdout_used_for_selection": False, "automatic_checkpoint_selection": False,
            "exact_discordant_test": request["exact_discordant_test"], "missions": [{"map_name": m[0], "episode_id": m[1]} for m in baseline["missions"]],
            "shared_contract": {"configuration": baseline["configuration"], "retry_policy": candidate_nav["retry_policy"], "split": copied["frozen_split"],
                                "runtime_receipt": copied["runtime_receipt"], "episode_rows_sha256": records["episode_rows"]["sha256"], "analyzer_source": copied["analyzer_source"]},
            "arms": {"original": {"navigation_plan": copied["original_navigation_plan"], "checkpoint_contract": original_ref,
                                  "reuse_existing_analysis_sha256": records["original_analysis"]["sha256"], "session_reports": sessions},
                     "candidate": {"navigation_plan": nav_ref, "checkpoint_contract": candidate_ref, "reuse_existing_analysis_sha256": None,
                                   "session_reports": [{"session_id": slot["session_id"], "path": slot["comparison_report_path"], "analysis_source_path": slot["analysis_source_path"]}]}},
            "predeclared_P14_rule": {"candidate_checkpoint_contract_sha256": candidate_ref["sha256"], "policy": "Same fixed final P12 candidate regardless of P13 outcome; no best-of or model switch. Report P13 outcomes honestly before creating the actual P14 plan. Both P14 arms require fresh post-freeze holdout execution; no improvement is promised."}}
    plan_ref = write("paired-plan.json", plan)
    inputs.recheck()
    result = {"schema_version": "vla.development-comparison-readiness.v1", "status": "metadata_prepared_evaluation_not_run", "created_at_utc": paired_at,
              "paired_plan": plan_ref, "baseline_reuse_accounting": baseline["accounting"], "candidate": candidate,
              "input_sources": list(inputs.records.values()), "source_code": {"helper": helper_record, "comparator": comparator_record},
              "full_comparator_validation": "Deferred until real candidate analysis/session receipts exist; no synthetic candidate was used",
              "limitations": ["Recorded inventories are copied from actual receipts; remote weight bytes are not opened or reverified by this metadata helper.",
                              "No-holdout-use is the caller's explicit declaration supported by frozen train membership and fixed-final-step training receipts, not proof of all prior decisions.",
                              "P08 reuse is a historical development baseline under the matched protocol; this is not a contemporaneous or causal comparison.",
                              "Future report paths are declared without invented contents, timestamps or hashes. No P14 plan/results are generated."]}
    write("readiness.json", result)
    write("checksums.json", {str(p.relative_to(output)): comparator.digest(p) for p in sorted(output.rglob("*")) if p.is_file() and p.name != "checksums.json"})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("request", "p12-checkpoint-manifest", "p12-report", "training-dataset-manifest", "released-parent-manifest", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    options = parser.parse_args()
    result = prepare(*(getattr(options, name).resolve() for name in ("request", "p12_checkpoint_manifest", "p12_report", "training_dataset_manifest", "released_parent_manifest", "output")))
    print(json.dumps({"status": result["status"], "paired_plan": result["paired_plan"], "evaluation_executed": False}))


if __name__ == "__main__":
    main()
