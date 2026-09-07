"""Synthetic contract/accounting fixtures only; no evaluation results are generated."""
import copy
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import compare_navigation as c


def stamp(hour):
    return f"2026-01-01T{hour:02d}:00:00+00:00"


class Fixture:
    def __init__(self, root):
        self.root = Path(root)
        self.write("analyze_baseline.py", b"# synthetic declared source; never executed\n")
        self.split = dict(schema_version="vla.splits.v1", frozen_at_utc=stamp(0), upstream_code_revision="9"*40,
                          groups=dict(development=[f"SyntheticMap/e{i}/merged_data.json" for i in range(3)], holdout=[]))
        self.config = dict(task_mode="synthetic benchmark", protocol="observed-test-v1", runtime_id="synthetic-runtime",
                           require_recorded_runtime_id=True, reset_protocol="synthetic-reset", reset_helper_sha256="a"*64, max_actions=200)
        self.receipt = dict(schema_version="vla.runtime-receipt.v1", runtime_id="synthetic-runtime", created_at_utc=stamp(0),
                            reset_protocol="synthetic-reset", upstream_revision="9"*40,
                            code={"reset_protocol.py": dict(sha256="a"*64), "_aerovla_runtime_hooks.py": dict(sha256="3"*64)})
        self.plan = dict(schema_version=c.SCHEMA, plan_id="synthetic-paired-plan", frozen_at_utc=stamp(5), phase="P13",
                         purpose="development_comparison", split_group="development", holdout_used_for_selection=False,
                         automatic_checkpoint_selection=False, exact_discordant_test=True,
                         missions=[dict(map_name="SyntheticMap", episode_id=f"e{i}") for i in range(3)],
                         shared_contract=dict(configuration=self.config, retry_policy=dict(selection="first_valid_attempt", max_attempts_per_trial=1), episode_rows_sha256="e"*64), arms={})
        self.navs, self.analyses, self.checkpoints, self.reports = {}, {}, {}, {}
        for role, successes in (("original", [True, False, False]), ("candidate", [False, True, False])):
            checkpoint = dict(schema_version="vla.comparison-checkpoint.v1", frozen_at_utc=stamp(1), checkpoint_id=role,
                              model_path=f"synthetic-model/{role}", base_manifest_sha256="b"*64,
                              artifact_manifest_sha256=("c" if role == "candidate" else "d")*64,
                              holdout_used_for_training_or_selection=False,
                              model_files=[dict(path="adapter_model.safetensors", bytes=1, sha256="f"*64)],
                              source_kind="released" if role == "original" else "trained")
            if role == "candidate":
                checkpoint.update(parent_checkpoint_id="original", training_split="train", supervision_mode="reviewed-expert", training_manifest_sha256="1"*64)
            self.checkpoints[role] = checkpoint
            nav = dict(schema_version="vla.navigation-plan.v1", plan_id=role+"-plan", frozen_at_utc=stamp(2),
                       configuration={**self.config, "checkpoint_id": role, "model_path": checkpoint["model_path"]},
                       retry_policy=copy.deepcopy(self.plan["shared_contract"]["retry_policy"]),
                       trials=[dict(trial_id=role+f"-t{i}", map_name="SyntheticMap", episode_id=f"e{i}") for i in range(3)],
                       sessions=[dict(session_id=role+"-session", trial_ids=[role+f"-t{i}" for i in range(3)])], source_plan={})
            self.navs[role] = nav
            start = 3 if role == "original" else 6
            self.reports[role] = dict(schema_version="vla.simulation-session.v1", started_at_utc=stamp(start), finished_at_utc=stamp(start+1))
            rows, attempts = [], []
            for i, success in enumerate(successes):
                trial = nav["trials"][i]
                out = dict(upstream_flags=dict(success=success, oracle_success=False, collisions=False),
                           distance_to_target_m=3., step=2, termination_reason="success" if success else "max_actions")
                attempt = dict(**trial, attempt_id=role+f"-a{i}", session_id=role+"-session", start_event_id=i+1,
                               start_wall_time_utc=stamp(start), navigation_attempt_observed=True, joint_valid=True,
                               joint_status="valid_navigation_and_reset", status="valid_navigation_outcome", within_declared_attempt_cap=True,
                               reset_audit=dict(accepted_reset_evidence=True, errors=[]), errors=[], joint_errors=[], raw_outcome=out)
                attempts.append(attempt)
                rows.append(dict(**trial, observed_attempts=1, attempts_beyond_cap=0, joint_valid_attempts=1,
                                 selected_attempt_id=attempt["attempt_id"], selected_session_id=attempt["session_id"], status="scored_valid_trial",
                                 upstream_success=success, upstream_osr_success=success, upstream_collision_flag=False,
                                 terminal_loop_index=2, distance_to_spawned_target_m=3., termination_reason=out["termination_reason"]))
            self.analyses[role] = dict(schema_version="vla.baseline-reset-analysis.v1", generated_at_utc=stamp(start+1),
                                       plan_id=nav["plan_id"], configuration=nav["configuration"], trials=rows, attempts=attempts,
                                       session_reset_audits=[dict(session_id=role+"-session", errors=[])], source_errors=[])
            self.plan["arms"][role] = dict(session_reports=[dict(session_id=role+"-session", path=role+"-session.json", analysis_source_path=str(self.root / (role+"-session.json")))])
            self.count(role)

    def count(self, role):
        a = self.analyses[role]
        rows = a["trials"]
        valid = [r for r in rows if r["status"] == "scored_valid_trial"]
        a["aggregate"] = dict(planned_unique_trials=len(rows), observed_attempts=sum(r["navigation_attempt_observed"] for r in a["attempts"]),
                              unplanned_observed_attempts=0, observed_unique_trials=sum(r["observed_attempts"] > 0 for r in rows),
                              valid_scored_trials=len(valid), unscored_trials=len(rows)-len(valid),
                              unstarted_trials=sum(r["status"] == "unstarted_trial" for r in rows), attempts_beyond_cap=0,
                              success_among_valid_trials=dict(numerator=sum(r["upstream_success"] for r in valid), denominator=len(valid)),
                              osr_among_valid_trials=dict(numerator=sum(r["upstream_osr_success"] for r in valid), denominator=len(valid)))

    def invalidate(self, role, index, unstarted=False):
        a = self.analyses[role]
        row = a["trials"][index]
        attempt = next(x for x in a["attempts"] if x["trial_id"] == row["trial_id"])
        if unstarted:
            a["attempts"].remove(attempt)
            row["observed_attempts"] = 0
        else:
            attempt.update(joint_valid=False, joint_errors=["synthetic reset failure"])
            attempt["reset_audit"].update(accepted_reset_evidence=False, errors=["synthetic reset failure"])
        row.update(joint_valid_attempts=0, selected_attempt_id=None, selected_session_id=None,
                   status="unstarted_trial" if unstarted else "unscored_observed_trial")
        for key in ("upstream_success", "upstream_osr_success", "upstream_collision_flag", "terminal_loop_index", "distance_to_spawned_target_m", "termination_reason"):
            row[key] = None
        self.count(role)

    def write(self, name, value):
        p = self.root / name
        p.write_bytes(value if isinstance(value, bytes) else (json.dumps(value, indent=2)+"\n").encode())
        return dict(path=name, sha256=c.digest(p))

    def save(self):
        shared = self.plan["shared_contract"]
        shared["split"] = self.write("split.json", self.split)
        shared["runtime_receipt"] = self.write("runtime.json", self.receipt)
        shared["analyzer_source"] = dict(path="analyze_baseline.py", sha256=c.digest(self.root / "analyze_baseline.py"))
        for role in ("original", "candidate"):
            nav = self.navs[role]
            nav["source_plan"].update(split_sha256=shared["split"]["sha256"], runtime_receipt_sha256=shared["runtime_receipt"]["sha256"], episode_rows_sha256=shared["episode_rows_sha256"], selection_manifest_sha256="2"*64)
            definition = self.plan["arms"][role]
            definition["navigation_plan"] = self.write(role+"-plan.json", nav)
            definition["checkpoint_contract"] = self.write(role+"-checkpoint.json", self.checkpoints[role])
            self.write(role+"-session.json", self.reports[role])
            a = self.analyses[role]
            a["plan_sha256"] = definition["navigation_plan"]["sha256"]
            a["source_files"] = [dict(path=str(self.root/name), sha256=c.digest(self.root/name), bytes=(self.root/name).stat().st_size)
                                 for name in (role+"-plan.json", "runtime.json", role+"-session.json")]
            a["source_files"].extend(dict(path=str(self.root/name), sha256=value["sha256"], bytes=1) for name, value in self.receipt["code"].items())
            ref = self.write(role+".json", a)
            definition["reuse_existing_analysis_sha256"] = ref["sha256"] if role == "original" and c.instant(self.reports[role]["started_at_utc"]) <= c.instant(self.plan["frozen_at_utc"]) else None
        self.write("paired.json", self.plan)

    def run(self):
        return c.compare(self.root/"paired.json", self.root/"original.json", self.root/"candidate.json")


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = Fixture(self.temp.name)

    def test_complete_pairs_transitions_and_output_integrity(self):
        self.f.save()
        result = self.f.run()
        self.assertEqual(result["matched_valid_pairs"], 3)
        self.assertEqual(result["success"]["paired_mean_difference_candidate_minus_original"], 0)
        self.assertEqual(result["success"]["transitions"], dict(both_failure=1, both_success=0, original_only_success=1, candidate_only_success=1))
        self.assertIsNone(result["selection_decision"])
        output = Path(self.temp.name)/"result"
        c.write_result(result, output)
        for line in (output/"checksums.sha256").read_text().splitlines():
            digest, name = line.split("  ", 1)
            self.assertEqual(c.digest(output/name), digest)
        with self.assertRaisesRegex(ValueError, "fresh"):
            c.write_result(result, output)

    def test_invalid_and_unstarted_remain_null_and_all_attempts_retained(self):
        self.f.invalidate("candidate", 0)
        self.f.invalidate("original", 2, unstarted=True)
        self.f.save()
        r = self.f.run()
        self.assertEqual(r["matched_valid_pairs"], 1)
        self.assertEqual(r["unmatched_or_invalid_pairs"], 2)
        self.assertIsNone(r["trials"][0]["candidate_upstream_success"])
        self.assertEqual(len(r["attempts"]["candidate"]), 3)
        self.assertEqual(r["success"]["paired_mean_difference_candidate_minus_original"], 1.)
        self.assertIn("synthetic reset failure", r["attempts"]["candidate"][0]["joint_errors"])
        output = Path(self.temp.name)/"missing"
        c.write_result(r, output)
        with (output/"trials.csv").open() as h:
            rows = list(csv.DictReader(h))
        self.assertEqual(rows[0]["candidate_upstream_success"], "")

    def test_zero_pairs_no_rate_difference_or_p(self):
        for i in range(3):
            self.f.invalidate("candidate", i)
        self.f.save()
        result = self.f.run()
        for key in ("original_sr", "candidate_sr", "paired_mean_difference_candidate_minus_original", "exact_discordant_two_sided_p_descriptive"):
            self.assertIsNone(result["success"][key])

    def test_order_protocol_and_model_config_mismatch_rejected(self):
        for field in ("order", "reset", "budget", "task", "retry", "model"):
            with self.subTest(field=field):
                self.f = Fixture(self.temp.name)
                nav = self.f.navs["candidate"]
                if field == "order": nav["trials"].reverse()
                elif field == "reset": nav["configuration"]["reset_protocol"] = "changed"
                elif field == "budget": nav["configuration"]["max_actions"] = 199
                elif field == "task": nav["configuration"]["task_mode"] = "other"
                elif field == "retry": nav["retry_policy"]["max_attempts_per_trial"] = 2
                else: nav["configuration"]["model_path"] = "undeclared"
                self.f.save()
                with self.assertRaises(ValueError): self.f.run()

    def test_posthoc_plan_original_implicit_reuse_and_timestamp_missing_rejected(self):
        for field in ("posthoc", "reuse", "unfinished", "outside"):
            with self.subTest(field=field):
                self.f = Fixture(self.temp.name)
                if field == "posthoc": self.f.plan["frozen_at_utc"] = stamp(7)
                elif field == "unfinished": del self.f.reports["candidate"]["finished_at_utc"]
                elif field == "outside": self.f.analyses["candidate"]["attempts"][0]["start_wall_time_utc"] = stamp(1)
                self.f.save()
                if field == "reuse":
                    self.f.plan["arms"]["original"]["reuse_existing_analysis_sha256"] = None
                    self.f.write("paired.json", self.f.plan)
                with self.assertRaises((ValueError, KeyError)): self.f.run()

    def test_retries_unplanned_duplicates_and_forged_aggregate_rejected(self):
        for field in ("retry", "extra", "duplicate", "aggregate", "flag"):
            with self.subTest(field=field):
                self.f = Fixture(self.temp.name)
                a = self.f.analyses["candidate"]
                if field in ("retry", "extra", "duplicate"):
                    extra = copy.deepcopy(a["attempts"][0])
                    if field != "duplicate": extra["attempt_id"] = "extra"
                    if field == "extra": extra["trial_id"] = "unplanned"
                    a["attempts"].append(extra)
                elif field == "aggregate": a["aggregate"]["valid_scored_trials"] = 99
                else: a["attempts"][0]["raw_outcome"]["upstream_flags"]["success"] = 0
                self.f.save()
                with self.assertRaises(ValueError): self.f.run()

    def test_split_overlap_subset_and_holdout_selection_rejected(self):
        for field in ("overlap", "subset", "holdout", "prior_use", "mechanics"):
            with self.subTest(field=field):
                self.f = Fixture(self.temp.name)
                if field == "overlap": self.f.split["groups"]["holdout"] = self.f.split["groups"]["development"][:1]
                elif field == "subset": self.f.plan["missions"].pop()
                elif field == "holdout": self.f.plan.update(split_group="holdout", phase="P14", purpose="development_comparison")
                elif field == "prior_use": self.f.checkpoints["candidate"]["holdout_used_for_training_or_selection"] = True
                else: self.f.checkpoints["candidate"]["supervision_mode"] = "published-reference-mechanics"
                self.f.save()
                with self.assertRaises(ValueError): self.f.run()

    def test_hash_tampering_and_duplicate_json_keys_rejected(self):
        self.f.save()
        with (Path(self.temp.name)/"runtime.json").open("a") as h: h.write(" ")
        with self.assertRaisesRegex(ValueError, "SHA256"): self.f.run()
        with self.assertRaisesRegex(ValueError, "Duplicate JSON"):
            c.json_bytes('{"a":1,"a":2}')
        with self.assertRaisesRegex(ValueError, "Nonfinite"):
            c.json_bytes('{"a":NaN}')
        with self.assertRaisesRegex(ValueError, "Nonfinite"):
            c.json_bytes('{"a":1e999}')

    def test_exact_discordant_values_and_disabled_test(self):
        self.assertEqual(c.exact_discordant(0, 0), 1.)
        self.assertEqual(c.exact_discordant(4, 0), .125)
        self.assertEqual(c.exact_discordant(1, 3), .625)
        self.f.plan["exact_discordant_test"] = False
        self.f.save()
        self.assertIsNone(self.f.run()["success"]["exact_discordant_two_sided_p_descriptive"])

    def test_confirmatory_holdout_is_supported_without_selection(self):
        self.f.split["groups"]["holdout"] = self.f.split["groups"].pop("development")
        self.f.plan.update(phase="P14", split_group="holdout", purpose="holdout_confirmation")
        self.f.reports["original"].update(started_at_utc=stamp(6), finished_at_utc=stamp(7))
        self.f.analyses["original"]["generated_at_utc"] = stamp(7)
        for a in self.f.analyses["original"]["attempts"]:
            a["start_wall_time_utc"] = stamp(6)
        self.f.save()
        self.assertEqual(self.f.run()["split_group"], "holdout")

    def test_holdout_original_reuse_rejected_even_with_explicit_hash(self):
        self.f.split["groups"]["holdout"] = self.f.split["groups"].pop("development")
        self.f.plan.update(phase="P14", split_group="holdout", purpose="holdout_confirmation")
        self.f.save()
        with self.assertRaisesRegex(ValueError, "both arms"):
            self.f.run()

    def test_runtime_source_and_frozen_base_parent_contracts_rejected(self):
        for field in ("upstream", "source", "base", "parent", "session"):
            with self.subTest(field=field):
                self.f = Fixture(self.temp.name)
                if field == "upstream": self.f.receipt["upstream_revision"] = "8"*40
                elif field == "source": del self.f.receipt["code"]["_aerovla_runtime_hooks.py"]
                elif field == "base": self.f.checkpoints["candidate"]["base_manifest_sha256"] = "8"*64
                elif field == "parent": self.f.checkpoints["candidate"]["parent_checkpoint_id"] = "unknown"
                else: self.f.analyses["candidate"]["session_reset_audits"][0]["errors"] = ["synthetic rejected session"]
                self.f.save()
                with self.assertRaises(ValueError): self.f.run()

    def test_cli_exit_codes_do_not_convert_missing_into_success(self):
        for state, expected in (("complete", 0), ("partial", 2), ("rejected", 1)):
            with self.subTest(state=state):
                self.f = Fixture(self.temp.name)
                if state == "partial": self.f.invalidate("candidate", 1)
                if state == "rejected": self.f.plan["automatic_checkpoint_selection"] = True
                self.f.save()
                out = Path(self.temp.name)/state
                run = subprocess.run([sys.executable, c.__file__, "--plan", str(self.f.root/"paired.json"),
                                      "--original", str(self.f.root/"original.json"), "--candidate", str(self.f.root/"candidate.json"),
                                      "--output", str(out)], capture_output=True, text=True)
                self.assertEqual(run.returncode, expected, run.stderr)
                self.assertEqual(out.exists(), state != "rejected")


if __name__ == "__main__":
    unittest.main()
