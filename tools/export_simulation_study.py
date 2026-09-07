#!/usr/bin/env python3
"""Export only approved numeric/identity fields from the sealed simulation study.

The private release directories are read-only inputs. This does not run an
experiment, reopen a review, copy raw data, or confer publication rights.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import random
import statistics

STUDY = "simulation-sft-v1"
PHASES = {
    "training": "P12/20260907-reference-adaptation-v2",
    "development": "P13/20260907-paired-development-v1",
    "holdout": "P14/20260907-paired-holdout-v1",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def load(data):
    def invalid(value):
        raise ValueError("Non-finite JSON: " + value)
    return json.loads(data, parse_constant=invalid)


class SealedSource:
    def __init__(self, root, phase, catalog):
        self.root = root / PHASES[phase]
        self.phase = phase
        self.catalog = catalog
        self.checksums = dict(line.split("  ", 1)[::-1] for line in
                              (self.root / "checksums.sha256").read_text().splitlines())
        self.manifest = load(self.read("manifest.json", phase + "-sealed-manifest"))
        require(self.manifest["artifact_status"] == "verified", "Release is not sealed")
        self.files = {r["path"]: r for r in self.manifest["artifacts"]}

    def read(self, relative, source_id):
        path = self.root / relative
        require(not path.is_symlink() and path.is_file(), "Expected a regular sealed file")
        data = path.read_bytes()
        sha = digest(data)
        require(self.checksums.get(relative) == sha, "Sealed checksum mismatch: " + relative)
        if hasattr(self, "files"):
            require(self.files[relative]["sha256"] == sha and
                    self.files[relative]["bytes"] == len(data), "Manifest differs from sealed bytes")
        self.catalog[source_id] = {"id": source_id, "sha256": sha, "bytes": len(data),
                                  "sealed_release_id": PHASES[self.phase],
                                  "availability": "retained_private_source",
                                  "validation": "Bytes match sealed checksum; input also matches manifest when inventoried"}
        return data

    def json(self, prefix, source_id):
        matches = sorted(p for p in self.files if Path(p).name.startswith(prefix))
        require(bool(matches), "Missing sealed source prefix: " + prefix)
        require(len({self.files[p]["sha256"] for p in matches}) == 1, "Ambiguous source prefix")
        return load(self.read(matches[0], source_id))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def write_csv(path, rows):
    require(bool(rows), "Refusing empty study table")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summarize(episodes, cohort, role):
    rows = [r for r in episodes if r["cohort"] == cohort and r["arm"] == role]
    return {"trials": len(rows), "valid_trials": sum(r["valid"] for r in rows),
            "observed_attempts": sum(r["observed_attempts"] for r in rows),
            "successes": sum(r["success"] for r in rows), "oracle_successes": sum(r["oracle_success"] for r in rows),
            "actions_completed": sum(r["actions_completed"] for r in rows),
            "observations_recorded": sum(r["observations_recorded"] for r in rows),
            "policy_outputs_recorded": sum(r["policy_outputs_recorded"] for r in rows),
            "accepted_resets": sum(r["accepted_reset"] for r in rows),
            "any_sampled_endpoint_contact": sum(r["any_sampled_endpoint_contact"] for r in rows),
            "upstream_collision_flag": sum(r["upstream_collision_flag"] for r in rows)}


def export(releases, output):
    require(not output.resolve().is_relative_to(releases.resolve()) and
            not releases.resolve().is_relative_to(output.resolve()), "Separate input and output roots required")
    catalog, episodes, pairs, aggregates, timings = {}, [], [], {}, []
    selected = {}
    for cohort, comparison_prefix, analysis_prefixes in [
        ("development", "056a946bdeef4d2d-", {"original": "db751d89adb9de1a-", "candidate": "e8f817eb84a9b135-"}),
        ("holdout", "0c50f8d3ba8cc36a-", {"original": "2a2b83a5bc5244d2-", "candidate": "6554c573c7021837-"}),
    ]:
        source = SealedSource(releases, cohort, catalog)
        comparison = source.json(comparison_prefix, cohort + "-comparison")
        spec = load(source.read("evidence/release-spec.json", cohort + "-sealed-spec"))
        require(comparison["planned_pairs"] == comparison["matched_valid_pairs"] and
                comparison["unmatched_or_invalid_pairs"] == 0, "Incomplete paired comparison")
        selected[cohort] = comparison
        for role, prefix in analysis_prefixes.items():
            analysis_id = cohort + "-" + role + "-analysis"
            analysis = source.json(prefix, analysis_id)
            require(catalog[analysis_id]["sha256"] == comparison["arms"][role]["analysis_sha256"], "Comparison/analysis mismatch")
            require(not analysis["source_errors"], "Analysis contains source errors")
            attempts = {a["attempt_id"]: a for a in analysis["attempts"]}
            for t in comparison["trials"]:
                a = attempts[t[role + "_selected_attempt_id"]]
                require(a["joint_valid"] is True and a["navigation_attempt_observed"] is True, "Unscored attempt")
                require(a["reset_audit"]["accepted_reset_evidence"] is True, "Missing accepted reset")
                require(a["episode_id"] == t["episode_id"] and t[role + "_observed_attempts"] == 1, "Mission/attempt mismatch")
                require(a["policy_outputs_recorded"] == a["actions_completed"] == a["actions_requested"], "Action counts disagree")
                require(a["observations_recorded"] == a["actions_completed"] + 1, "Observation sequence differs")
                latencies = a["generate_call_return_seconds"]
                require(len(latencies) == a["policy_outputs_recorded"], "Missing generation intervals")
                episodes.append({
                    "cohort": cohort, "mission_ordinal": t["ordinal"], "episode_id": t["episode_id"], "arm": role,
                    "valid": True, "observed_attempts": t[role + "_observed_attempts"],
                    "success": t[role + "_upstream_success"], "oracle_success": t[role + "_upstream_osr_success"],
                    "upstream_collision_flag": t[role + "_upstream_collision_flag"],
                    "any_sampled_endpoint_contact": a["contact"]["any_recorded_endpoint_contact"],
                    "terminal_endpoint_contact": a["contact"]["terminal_contact"],
                    "terminal_loop_index": t[role + "_terminal_loop_index"],
                    "final_target_distance_m": t[role + "_distance_to_spawned_target_m"],
                    "termination_reason": t[role + "_termination_reason"], "accepted_reset": True,
                    "observations_recorded": a["observations_recorded"],
                    "policy_outputs_recorded": a["policy_outputs_recorded"], "actions_completed": a["actions_completed"],
                    "generate_host_interval_count": len(latencies), "generate_host_seconds_total": sum(latencies),
                    "generate_host_seconds_mean": statistics.mean(latencies),
                    "generate_host_seconds_median": statistics.median(latencies),
                    "comparison_source_id": cohort + "-comparison", "analysis_source_id": analysis_id,
                })
            for m in analysis["measurements"]:
                timings.append({"cohort": cohort, "arm": role,
                                "command_elapsed_seconds": m["command_elapsed_seconds"],
                                "generate_host_call_return_seconds": m["generate_host_call_return_seconds"],
                                "action_execution_host_seconds": m["action_execution_host_seconds"],
                                "image_write_hash_host_seconds": m["image_write_hash_host_seconds"],
                                "source_id": analysis_id})
            own = summarize(episodes, cohort, role)
            require(own["successes"] == comparison["success"][role + "_successes"] and
                    own["oracle_successes"] == comparison["oracle_success"][role + "_successes"], "Source totals differ")
            causal = spec["measurements"]["artifact_causal_validation"][role]
            require(own["observations_recorded"] == causal["causally_ordered_observations"] and
                    own["actions_completed"] == causal["event_type_counts"]["action.completed"] and
                    own["trials"] == causal["attempts_checked"], "Sealed causal counts differ")
            aggregates.setdefault(cohort, {})[role] = own
        for t in comparison["trials"]:
            pairs.append({"cohort": cohort, "mission_ordinal": t["ordinal"], "episode_id": t["episode_id"],
                          "original_success": t["original_upstream_success"], "candidate_success": t["candidate_upstream_success"],
                          "original_oracle_success": t["original_upstream_osr_success"], "candidate_oracle_success": t["candidate_upstream_osr_success"],
                          "sr_difference_candidate_minus_original": t["success_difference_candidate_minus_original"],
                          "comparison_source_id": cohort + "-comparison"})
        aggregates[cohort]["paired_sr_transitions"] = comparison["success"]["transitions"]
        aggregates[cohort]["paired_osr_transitions"] = comparison["oracle_success"]["transitions"]

    train_source = SealedSource(releases, "training", catalog)
    training = train_source.json("d9f85078870f4ae9-", "training-run")
    checkpoint = train_source.json("c8fdf4cc533e7360-", "candidate-checkpoint-manifest")
    dataset = train_source.json("140681ffe3f883f1-", "training-dataset-manifest")
    train_source.json("d2b0c01173ca26e9-", "released-parent-manifest")
    train_source.json("ee1b2f0a491157b0-", "training-launch-plan")
    train_spec = load(train_source.read("evidence/release-spec.json", "training-sealed-spec"))
    data = train_source.read("evidence/inputs/e0d21988e6fd65f4-steps.jsonl", "training-step-log")
    steps = [load(line) for line in data.splitlines()]
    config = training["config"]
    require(training["status"] == "passed" and training["completed_optimizer_steps"] == len(steps) == 25, "Incomplete training")
    require(len(dataset["samples"]) == 25 and dataset["approval"]["status"] == "approved", "Dataset differs")
    expected_order = list(range(25)); random.Random(config["seed"]).shuffle(expected_order)
    require([s["sample_indices"][0] for s in steps] == expected_order, "Exposure order differs")
    training_rows = []
    for s in steps:
        i = s["sample_indices"][0]
        require(s["sample_ids"] == [dataset["samples"][i]["sample_id"]] and s["all_trainable_gradients_present_finite"] is True, "Step evidence differs")
        training_rows.append({"optimizer_step": s["optimizer_step"], "training_row_index": i,
                              "sample_id": s["sample_ids"][0], "microbatch_loss": s["mean_microbatch_loss"],
                              "gradient_norm_before_clip": s["gradient_norm_before_clip"], "learning_rate": s["learning_rate"],
                              "completed_sample_exposures": s["completed_sample_exposures"],
                              "recorded_step_seconds": s["elapsed_seconds"], "source_id": "training-step-log"})
    membership = [{"training_row_index": s["row_index"], "sample_id": s["sample_id"],
                   "episode_id": s["episode_id"].split("/")[1], "publisher_row_index": s["source_row_index"],
                   "publisher_row_sha256": s["row_sha256"], "source_id": "training-dataset-manifest"} for s in dataset["samples"]]
    groups = [{r["episode_id"] for r in episodes if r["cohort"] == c} for c in ("development", "holdout")]
    train_ids = {r["episode_id"] for r in membership}
    require(len(train_ids) == 25 and not groups[0] & groups[1] and not train_ids & (groups[0] | groups[1]), "Split overlap")
    summary = {"schema_version": "uav-vla-lab.study-training-summary.v1", "optimizer_steps": len(steps),
               "training_rows": len(membership), "sample_exposures": len(steps), "complete_passes": 1,
               "changed_tensors": training["weight_changes"]["changed_tensor_count"],
               "trainable_tensors": training["weight_changes"]["total_tensor_count"],
               "trainable_parameters": train_spec["measurements"]["trainable_parameters"],
               "fixed_training_row_index": 0, "fixed_row_exposed_at_step": expected_order.index(0) + 1,
               "fixed_row_loss": {k: training["prediction_" + k]["loss"] for k in ("before", "after", "reloaded")},
               "reload_validation": training["reload_validation"],
               "training_elapsed_seconds": training["training_elapsed_seconds"],
               "supervised_command_elapsed_seconds": train_spec["measurements"]["supervised_command_elapsed_seconds"],
               "candidate_files": [{"filename": Path(f["path"]).name, "bytes": f["bytes"], "sha256": f["sha256"]}
                                   for f in checkpoint["checkpoint_files"]],
               "source_ids": ["training-run", "candidate-checkpoint-manifest", "training-sealed-spec"],
               "scope": "Teacher-forced training-sample fit and checkpoint mechanics; no held-out loss or navigation conclusion"}
    effective = {k: v for k, v in config.items() if k in {
        "phase", "supervision_mode", "steps", "learning_rate", "batch_size", "gradient_accumulation", "seed",
        "weight_decay", "max_grad_norm", "reload_atol", "reload_rtol", "selection_rule", "validate_only", "algorithm"}}
    effective.update(schema_version="uav-vla-lab.historical-training-config.v1", purpose="Historical effective settings; not a runnable launch plan",
                     source_id="training-run", parent_manifest_source_id="released-parent-manifest",
                     dataset_manifest_source_id="training-dataset-manifest")
    dev_source = SealedSource(releases, "development", catalog)
    runtime = dev_source.json("8b233b2ed04bdda5-", "evaluation-runtime-receipt")
    dev_plan = dev_source.json("1c4bfed56252d92a-", "development-paired-plan")
    hold_source = SealedSource(releases, "holdout", catalog)
    hold_plan = hold_source.json("707a69c0557e0f60-", "holdout-original-frozen-plan")
    hold_source.json("b67b320ea77f2fe6-", "holdout-effective-path-amended-plan")
    protocol = {"schema_version": "uav-vla-lab.study-protocol.v1", "study_id": STUDY, "map": "ModernCityMap",
                "task": "Official target-bearing-assisted navigation", "upstream_revision": runtime["upstream_revision"],
                "runtime_id": runtime["runtime_id"], "reset_protocol": runtime["reset_protocol"],
                "runtime_code": runtime["code"], "clock_speed": 10, "max_actions": 200,
                "position_acceptance_tolerance_m": 0.1, "angle_acceptance_tolerance_rad": 0.05,
                "requested_reset_continuation_seconds": 0.001,
                "maximum_observed_attempts_per_mission_per_arm": 1,
                "development_original_reused": True, "holdout_both_arms_fresh": True,
                "development_plan_frozen_at_utc": dev_plan["frozen_at_utc"],
                "holdout_plan_frozen_at_utc": hold_plan["frozen_at_utc"],
                "holdout_candidate_infrastructure_launches": 2, "failed_launch_navigation_attempts": 0,
                "candidate_rule": "Same fixed final P12 checkpoint before development and regardless of development outcomes",
                "generation": {"forward_m": [0, 5], "down_m": [-5, 5], "yaw_rad": [-1.1, 1.1]},
                "physical_touchdown_measured": False, "physical_label_horizon_seconds": None,
                "source_ids": ["evaluation-runtime-receipt", "development-paired-plan", "holdout-original-frozen-plan", "holdout-effective-path-amended-plan"]}
    identities = {"schema_version": "uav-vla-lab.study-model-identities.v1",
                  "base": {"repository": "openvla/openvla-7b", "revision": "47a0ec7fc4ec123775a391911046cf33cf9ed83f"},
                  "released_adapter": {"repository": "XuPeng23/AerialVLA", "revision": "196f2f3253b69df6e90ac10b6ae041c7b3a9569e", "subfolder": "aero_vla"},
                  "candidate_manifest_sha256": catalog["candidate-checkpoint-manifest"]["sha256"],
                  "candidate_checkpoint_contract_sha256": selected["development"]["arms"]["candidate"]["checkpoint_contract_sha256"],
                  "candidate_weights_publicly_available": False,
                  "source_id": "candidate-checkpoint-manifest"}
    require(selected["development"]["arms"]["candidate"]["checkpoint_contract_sha256"] ==
            selected["holdout"]["arms"]["candidate"]["checkpoint_contract_sha256"], "Different candidate used")
    outputs = {"results/aggregate.json": {"study_id": STUDY, "cohorts": aggregates,
                "scope": "Descriptive paired counts; no significance test or pooled cross-cohort estimate"},
               "results/timing.json": {"arms": timings, "scope": "Nested recorded host intervals; different trajectories/lengths, not a policy speed comparison"},
               "results/training-summary.json": summary, "configs/training.json": effective,
               "configs/protocol.json": protocol, "configs/model-identities.json": identities,
               "source-catalog.json": {"schema_version": "uav-vla-lab.public-source-catalog.v1", "sources": list(catalog.values()),
                  "scope": "Identifiers and exact hashes only. Full private sources are not supplied; public rows are selected-field transcriptions, not raw traces.",
                  "exporter_sha256": digest(Path(__file__).read_bytes())}}
    for relative, value in outputs.items():
        write_json(output / relative, value)
    write_csv(output / "results/episodes.csv", episodes)
    write_csv(output / "results/paired.csv", pairs)
    write_csv(output / "results/training-steps.csv", training_rows)
    write_csv(output / "dataset/membership.csv", membership)
    print(json.dumps({"study": STUDY, "episodes": len(episodes), "pairs": len(pairs),
                      "training_steps": len(training_rows), "source_records": len(catalog), "status": "exported_from_verified_selected_source_bytes"}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sealed-releases", type=Path, required=True, help="Private retained release root; read only")
    p.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "experiments" / STUDY)
    a = p.parse_args()
    export(a.sealed_releases, a.output)


if __name__ == "__main__":
    main()
