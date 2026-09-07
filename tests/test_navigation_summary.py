"""Synthetic accounting fixtures only. These are not navigation/flight results."""
import copy
import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("summarize_navigation", Path(__file__).resolve().parents[1] / "scripts/summarize_navigation.py")
navigation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(navigation)


class NavigationSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.plan = {"schema_version": "vla.navigation-plan.v1", "plan_id": "synthetic-contract-fixture",
            "frozen_at_utc": "2026-01-01T00:00:00+00:00",
            "configuration": {"checkpoint_id": "fixture-weights", "model_path": "fixture-model",
                "runtime_id": "fixture-runtime", "require_recorded_runtime_id": True,
                "task_mode": "synthetic unit fixture, not flight", "protocol": navigation.PROTOCOL, "max_actions": 1},
            "retry_policy": {"selection": "first_valid_attempt", "max_attempts_per_trial": 3},
            "trials": [{"trial_id": "trial-a", "map_name": "FixtureMap", "episode_id": "episode-a"}], "sessions": []}

    def write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def save_events(self, root, events):
        (root / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")

    def summary(self):
        self.write_json(self.root / "plan.json", self.plan)
        return navigation.summarize(self.root / "plan.json")

    def session(self, *, success=False, oracle=False, collision=False, contact=False,
                interrupted=False, startup_failure=False, process_failure=False, trial_id="trial-a"):
        number = len(self.plan["sessions"]) + 1
        name, attempt = f"session-{number}", f"attempt-{number}"
        root = self.root / name
        root.mkdir()
        trial = next(item for item in self.plan["trials"] if item["trial_id"] == trial_id)
        self.plan["sessions"].append({"session_id": name, "order": number, "trial_ids": [trial_id],
            "evidence_dir": name, "supervisor_report": f"{name}/supervisor.json", "session_report": f"{name}/session.json"})
        self.write_json(root / "supervisor.json", {"schema_version": "vla.supervised_run.v1",
            "status": "exited_with_error" if process_failure or interrupted else "exited_successfully",
            "child_returncode": 1 if process_failure or interrupted else 0})
        self.write_json(root / "session.json", {"schema_version": "vla.simulation-session.v1",
            "status": "manager_readiness_timeout" if startup_failure else "command_failed" if process_failure or interrupted else "command_succeeded",
            "session_returncode": 1 if startup_failure or interrupted or process_failure else 0})
        if startup_failure:
            return root, [], None
        events = []
        context = {}

        def event(kind, **fields):
            item = {"schema_version": 1, "run_id": f"run-{number}", "event_id": len(events) + 1,
                "event_type": kind, "host_monotonic_ns": (len(events) + 1) * 1000,
                "wall_time_utc": "2026-01-02T00:00:00+00:00", **context, **fields}
            events.append(item)
            return item["event_id"]

        event("run.start", protocol=navigation.PROTOCOL, model_path="fixture-model", runtime_id="fixture-runtime",
              batch_size=1, max_actions=1, episode_count=1)
        context.update({"attempt_id": attempt, "map_name": trial["map_name"], "episode_id": trial["episode_id"]})
        event("episode.start", instruction="Synthetic accounting test only", source_json="fixture.json")
        if interrupted:
            partial = {**context, "status": "interrupted", "error_type": "RuntimeError", "error": "Synthetic interruption fixture"}
            event("episode.interrupted", **partial)
            self.write_json(root / "partial" / f"{attempt}.json", partial)
            event("run.end", status="interrupted")
            self.save_events(root, events)
            return root, events, None
        endpoint = {"sensors": {"state": {"timestamp": 10,
                    "collision": {"has_collided": contact} if contact is not None else None}}}

        def observation(index):
            images = []
            for camera in ("front", "down"):
                relative = f"images/{index}-{camera}.png"
                path = root / relative
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(b"Synthetic unit fixture bytes; not a real flight image")
                images.append({"camera": camera, "modality": "rgb", "path": relative, "sha256": navigation.sha256(path)})
            obs = event("observation.prepared", images=images, sensors=endpoint["sensors"])
            event("prompt.prepared", observation_event_id=obs, exact_prompt=["synthetic"], pixel_tensor_shape=[1, 6, 224, 224])
            return obs

        obs = observation(1)
        policy = event("policy.generated", observation_event_id=obs, token_ids=[[1, 2]], raw_text=["synthetic action"],
                       inference_start_ns=1_000_000_000, inference_return_ns=1_500_000_000)
        actions = [{"fwd": 0.0 if success else 1.0, "down": 0.0, "yaw": 0.0}]
        event("policy.decoded", observation_event_id=obs, policy_event_id=policy,
              upstream_actions=actions, upstream_stop_flags=[success])
        command = event("action.requested", observation_event_id=obs, policy_event_id=policy, actions=actions)
        event("action.completed", command_event_id=command, endpoint_states=[[endpoint] * 5])
        observation(2)
        flags = {"success": success, "oracle_success": oracle, "collisions": collision,
                 "early_end": False, "dones": True, "predict_dones": success}
        reason = "success" if success else "oracle_success" if oracle else "upstream_collision_flag" if collision else "step_limit_or_other_done"
        outcome = {**context, "status": "completed", "termination_reason": reason, "step": 1, "upstream_flags": flags,
            "distance_to_target_m": 2.0 if success else 30.0, "endpoint_contact": endpoint["sensors"]["state"]["collision"],
            "endpoint_state_timestamp": 10, "contact_scope": "sampled endpoint; not continuous contact monitoring",
            "stuck_counter": 16 if collision else 0, "interpretation": "Upstream success is a navigation criterion, not physical touchdown"}
        event("episode.completed", **outcome)
        event("run.end", status="interrupted" if process_failure else "completed")
        self.write_json(root / "outcomes" / f"{attempt}.json", outcome)
        self.save_events(root, events)
        return root, events, outcome

    def test_explicit_denominators_exclude_startup_and_navigation_interruptions(self):
        self.plan["trials"] += [{"trial_id": f"trial-{char}", "map_name": "FixtureMap", "episode_id": f"episode-{char}"} for char in "bcd"]
        self.session(success=True)
        self.session(oracle=True, contact=None, trial_id="trial-b")
        self.session(startup_failure=True, trial_id="trial-c")
        self.session(interrupted=True, trial_id="trial-d")
        summary = self.summary()
        aggregate = summary["aggregate"]
        self.assertEqual(aggregate["counts"]["planned_unique_episode_trials"], 4)
        self.assertEqual(aggregate["counts"]["observed_navigation_attempts"], 3)
        self.assertEqual(aggregate["counts"]["selected_valid_trials"], 2)
        self.assertEqual((aggregate["upstream_sr"]["numerator"], aggregate["upstream_sr"]["denominator"]), (1, 2))
        self.assertEqual((aggregate["upstream_osr"]["numerator"], aggregate["upstream_osr"]["denominator"]), (2, 2))
        self.assertEqual(aggregate["terminal_endpoint_contact_rate"]["denominator"], 1)
        self.assertIsNone(summary["trials"][2]["upstream_success"])
        self.assertIsNone(summary["trials"][3]["upstream_success"])
        self.assertEqual(summary["attempts"][3]["partial_files"][0]["content"]["status"], "interrupted")
        self.assertEqual(aggregate["coverage"]["fraction"], 0.5)

    def test_prior_completed_outcome_survives_later_process_failure(self):
        self.session(success=True, process_failure=True)
        summary = self.summary()
        self.assertEqual(summary["aggregate"]["upstream_sr"]["rate"], 1.0)
        self.assertEqual(summary["attempts"][0]["process_issue"], "supervisor_exited_with_error")

    def test_heuristic_collision_and_duplicate_endpoint_records_are_not_physical_contact(self):
        self.session(collision=True, contact=False)
        summary = self.summary()
        attempt = summary["attempts"][0]
        self.assertEqual(summary["aggregate"]["upstream_collision_flag_rate"]["rate"], 1.0)
        self.assertEqual(summary["aggregate"]["terminal_endpoint_contact_rate"]["rate"], 0.0)
        self.assertEqual(attempt["contact"]["record_count"], 4)  # two observations, one action endpoint, terminal
        self.assertIn("recorded_stuck_counter_exceeds_upstream_threshold", attempt["mechanically_supported_categories"])
        self.assertNotIn("terminal_endpoint_contact_reported", attempt["mechanically_supported_categories"])

    def test_retry_selects_first_valid_result_never_later_better_result(self):
        self.session(interrupted=True)
        self.session(success=False)
        self.session(success=True)
        summary = self.summary()
        self.assertEqual(summary["trials"][0]["selected_attempt_id"], "attempt-2")
        self.assertFalse(summary["trials"][0]["upstream_success"])
        self.assertEqual(summary["aggregate"]["retry_deviations"][0]["kind"], "retry_after_valid_outcome")

    def test_valid_result_beyond_declared_cap_remains_visible_unscored(self):
        self.plan["retry_policy"]["max_attempts_per_trial"] = 1
        self.session(interrupted=True)
        self.session(success=True)
        summary = self.summary()
        self.assertEqual(summary["trials"][0]["status"], "no_eligible_valid_outcome")
        self.assertEqual(summary["trials"][0]["valid_navigation_attempts"], 1)
        self.assertEqual(summary["aggregate"]["upstream_sr"]["denominator"], 0)
        self.assertIsNone(summary["aggregate"]["upstream_sr"]["rate"])
        self.assertFalse(summary["attempts"][1]["within_declared_attempt_cap"])

    def test_copied_run_and_attempt_evidence_cannot_be_counted_twice(self):
        self.session(success=True)
        second = copy.deepcopy(self.plan["sessions"][0])
        second.update(session_id="declared-copy", order=2)
        self.plan["sessions"].append(second)
        summary = self.summary()
        self.assertEqual(summary["aggregate"]["counts"]["selected_valid_trials"], 0)
        self.assertTrue(all(row["status"] == "invalid_evidence" for row in summary["attempts"]))

    def test_shifted_observation_policy_link_or_action_is_invalid(self):
        root, events, _ = self.session(success=True)
        request = next(event for event in events if event["event_type"] == "action.requested")
        request["observation_event_id"] = 999
        self.save_events(root, events)
        summary = self.summary()
        self.assertEqual(summary["attempts"][0]["status"], "invalid_evidence")
        self.assertTrue(any("mapping" in error for error in summary["attempts"][0]["errors"]))

    def test_image_hash_change_invalidates_navigation_evidence(self):
        root, _, _ = self.session(success=True)
        (root / "images/1-front.png").write_bytes(b"different synthetic fixture")
        summary = self.summary()
        self.assertEqual(summary["aggregate"]["counts"]["selected_valid_trials"], 0)
        self.assertTrue(any("SHA256" in error for error in summary["attempts"][0]["errors"]))

    def test_missing_flag_is_retained_without_imputing_false(self):
        root, events, outcome = self.session(success=True)
        del outcome["upstream_flags"]["oracle_success"]
        self.write_json(root / "outcomes/attempt-1.json", outcome)
        self.save_events(root, events)
        summary = self.summary()
        self.assertEqual(summary["attempts"][0]["status"], "invalid_evidence")
        self.assertNotIn("oracle_success", summary["attempts"][0]["raw_outcome"]["upstream_flags"])
        self.assertIsNone(summary["trials"][0]["upstream_success"])

    def test_malformed_trailing_line_does_not_erase_prior_complete_evidence(self):
        root, _, _ = self.session(success=True)
        with (root / "events.jsonl").open("a") as handle:
            handle.write("{broken-after-terminal\n")
        summary = self.summary()
        self.assertEqual(summary["aggregate"]["counts"]["selected_valid_trials"], 1)
        self.assertEqual(len(summary["sessions"][0]["event_parse_errors"]), 1)

    def test_malformed_line_inside_attempt_does_invalidate_outcome(self):
        root, events, _ = self.session(success=True)
        lines = [json.dumps(event) + "\n" for event in events]
        lines.insert(4, "{broken-inside-attempt\n")
        (root / "events.jsonl").write_text("".join(lines))
        summary = self.summary()
        self.assertEqual(summary["aggregate"]["counts"]["selected_valid_trials"], 0)

    def test_malformed_nested_values_are_retained_and_do_not_crash_report(self):
        root, events, outcome = self.session(success=True)
        events[1]["attempt_id"] = {"malformed": "identifier"}
        events[1]["run_id"] = ["bad-id"]
        next(event for event in events if event["event_type"] == "observation.prepared")["sensors"] = {"state": []}
        outcome["distance_to_target_m"] = float("nan")
        self.write_json(root / "outcomes/attempt-1.json", outcome)
        self.save_events(root, events)
        self.write_json(root / "supervisor.json", {"schema_version": "vla.supervised_run.v1", "status": {"bad": "value"}})
        summary = self.summary()
        json.dumps(summary, allow_nan=False)
        self.assertEqual(summary["aggregate"]["counts"]["selected_valid_trials"], 0)
        self.assertTrue(any(row["status"] == "orphan_outcome" for row in summary["attempts"]))

    def test_new_runtime_requires_identity_and_legacy_override_is_explicit(self):
        root, events, _ = self.session(success=True)
        del events[0]["runtime_id"]
        self.save_events(root, events)
        self.assertEqual(self.summary()["aggregate"]["counts"]["selected_valid_trials"], 0)
        self.plan["configuration"]["require_recorded_runtime_id"] = False
        summary = self.summary()
        self.assertEqual(summary["aggregate"]["counts"]["selected_valid_trials"], 1)
        self.assertFalse(summary["sessions"][0]["runtime_identity_recorded"])
        events[0]["runtime_id"] = "different-runtime"
        self.save_events(root, events)
        self.assertEqual(self.summary()["aggregate"]["counts"]["selected_valid_trials"], 0)

    def test_postdated_plan_and_source_mutation_cannot_supply_eligible_scores(self):
        self.session(success=True)
        self.plan["frozen_at_utc"] = "2026-01-03T00:00:00+00:00"
        self.assertEqual(self.summary()["aggregate"]["counts"]["selected_valid_trials"], 0)
        self.plan["frozen_at_utc"] = "2026-01-01T00:00:00+00:00"
        with patch.object(navigation.Evidence, "changed_files", return_value=[{"path": "fixture", "error": "changed"}]):
            summary = self.summary()
        self.assertEqual(summary["aggregate"]["counts"]["selected_valid_trials"], 0)
        self.assertEqual(summary["source_consistency_errors"][0]["error"], "changed")

    def test_empty_sessions_account_for_every_planned_trial_without_scores(self):
        del self.plan["sessions"]
        summary = self.summary()
        self.assertEqual(summary["trials"][0]["status"], "not_observed_started")
        self.assertEqual(summary["trials"][0]["categories"], ["no_session_declared"])
        self.assertIsNone(summary["aggregate"]["upstream_sr"]["rate"])

    def test_wilson_only_for_at_least_two_known_unique_trials(self):
        self.assertIsNone(navigation.wilson(0, 0)["bounds"])
        self.assertIsNone(navigation.wilson(1, 1)["bounds"])
        bounds = navigation.wilson(1, 2)["bounds"]
        self.assertAlmostEqual(bounds[0], 0.0945312057)
        self.assertAlmostEqual(bounds[1], 0.9054687943)

    def test_bundle_hashes_and_csv_accounting_are_complete_and_immutable(self):
        self.session(success=True)
        self.summary()
        output = self.root / "summary-output"
        summary = navigation.build(self.root / "plan.json", output)
        hashes = json.loads((output / "checksums.json").read_text())
        self.assertEqual(set(hashes), {path.name for path in output.iterdir()} - {"checksums.json"})
        for name, digest in hashes.items():
            self.assertEqual(navigation.sha256(output / name), digest)
        with (output / "trials.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), len(self.plan["trials"]))
        self.assertEqual(rows[0]["selected_attempt_id"], summary["trials"][0]["selected_attempt_id"])
        self.assertIn("Infrastructure failures", (output / "REPORT.md").read_text())
        with self.assertRaisesRegex(ValueError, "already exists"):
            navigation.build(self.root / "plan.json", output)


if __name__ == "__main__":
    unittest.main()
