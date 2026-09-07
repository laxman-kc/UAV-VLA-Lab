"""Synthetic contract tests; no simulator, model, expert review or real labels."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collect_heading_corrections as collector


class HeadingCorrectionTests(unittest.TestCase):
    def fixture_plan(self):
        samples = [{"sample_id": f"sample-{i}", "episode_id": f"Map/mission-{i}/merged_data.json",
                    "phase": "P09" if i < 5 else "P11", "yaw_perturbation_rad": .5 if i % 2 == 0 else -.5} for i in range(25)]
        plan = {"schema_version": collector.PLAN_SCHEMA, "protocol_id": collector.PROTOCOL,
                "frozen_at_utc": "2020-01-01T00:00:00+00:00", "samples": samples,
                "declared_acceptance": dict(collector.DECLARED_ACCEPTANCE)}
        splits = {"schema_version": "vla.splits.v1", "frozen_at_utc": "2020-01-01T00:00:00+00:00",
                  "groups": {"train": [s["episode_id"] for s in samples], "development": [], "holdout": []}}
        return plan, splits, [{"json": s["episode_id"]} for s in samples]

    def state(self, yaw=0, pitch=0, roll=0, position=(1, 2, -3)):
        return {"position": list(position), "orientation": collector.quaternion_from_zyx(yaw, pitch, roll)}

    def test_geometry_roundtrip_and_sign_invariance(self):
        for yaw in (-3.1, -.5, 0, .5, 3.1):
            for pitch, roll in ((0, 0), (.03, -.08), (-.06, .09)):
                q = collector.quaternion_from_zyx(yaw, pitch, roll)
                self.assertAlmostEqual(sum(v*v for v in q), 1)
                for actual, expected in zip(collector.quaternion_zyx(q), (yaw, pitch, roll)):
                    self.assertAlmostEqual(actual, expected)
                for a, b in zip(collector.quaternion_zyx(q), collector.quaternion_zyx([-v for v in q])):
                    self.assertAlmostEqual(a, b)

    def test_perturb_preserves_source_position_tilt_and_wraps(self):
        source = self.state(3.0, .04, -.02)
        before = copy.deepcopy(source)
        perturbed = collector.perturbed_reference(source, .5)
        self.assertEqual(source, before)
        self.assertEqual(perturbed["position"], source["position"])
        ypr = collector.quaternion_zyx(perturbed["orientation"])
        self.assertAlmostEqual(ypr[0], collector.wrap_angle(3.5))
        self.assertAlmostEqual(ypr[1], .04)
        self.assertAlmostEqual(ypr[2], -.02)
        action = collector.continuous_action(source, perturbed)
        self.assertAlmostEqual(action["yaw"], -.5)
        self.assertEqual((action["fwd"], action["down"]), (0, 0))

    def test_geometry_rejects_unsupported_states_and_noop(self):
        for q in ([0, 0, 0, 0], [0, 0, 0, float("nan")], [True, 0, 0, 1]):
            with self.assertRaises(ValueError): collector.quaternion_zyx(q)
        with self.assertRaisesRegex(ValueError, "near level"):
            collector.perturbed_reference(self.state(pitch=.11), .5)
        with self.assertRaises(ValueError): collector.perturbed_reference(self.state(), .6)
        with self.assertRaises(ValueError): collector.continuous_action(self.state(), self.state())

    def test_plan_train_isolation_and_frozen_thresholds(self):
        plan, splits, rows = self.fixture_plan()
        self.assertEqual(len(collector.validate_plan(plan, splits, rows)), 25)
        bad = copy.deepcopy(plan)
        bad["declared_acceptance"]["final_heading_error_rad"] = 1.5
        with self.assertRaisesRegex(ValueError, "acceptance"): collector.validate_plan(bad, splits, rows)
        bad = copy.deepcopy(splits)
        bad["groups"]["development"] = [bad["groups"]["train"][0]]
        with self.assertRaisesRegex(ValueError, "overlap"): collector.validate_plan(plan, bad, rows)
        with self.assertRaisesRegex(ValueError, "official training"): collector.validate_plan(plan, splits, rows[1:])

    def test_plan_rejects_duplicate_replacement_phase_and_unfrozen(self):
        plan, splits, rows = self.fixture_plan()
        for mutate in (lambda p: p["samples"].pop(),
                       lambda p: p["samples"][0].update(episode_id=p["samples"][1]["episode_id"]),
                       lambda p: p["samples"][5].update(phase="P09"),
                       lambda p: p.pop("frozen_at_utc")):
            bad = copy.deepcopy(plan)
            mutate(bad)
            with self.assertRaises(ValueError): collector.validate_plan(bad, splits, rows)

    def test_freeze_chronology_requires_real_aware_nonfuture_dates(self):
        plan, splits, rows = self.fixture_plan()
        started = "2026-09-07T00:00:00+00:00"
        self.assertEqual(len(collector.validate_plan(plan, splits, rows, started)), 25)
        for value in ("not-a-date", "2026-09-06T00:00:00", "2026-09-08T00:00:00Z", True):
            bad = copy.deepcopy(plan)
            bad["frozen_at_utc"] = value
            with self.assertRaises(ValueError): collector.validate_plan(bad, splits, rows, started)
        bad = copy.deepcopy(splits)
        bad["frozen_at_utc"] = "2026-09-08T00:00:00Z"
        with self.assertRaises(ValueError): collector.validate_plan(plan, bad, rows, started)
        collector.freeze_before_start("2026-09-06T20:00:00-04:00", started)

    def test_exact_reader_parser_methods_without_importing_model(self):
        # Exercise AST extraction using tiny synthetic fixtures. A separate source-
        # pinned integration check is run locally; this fixture is not source proof.
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "fixture.py"
            source.write_text("raise RuntimeError('must not import module')\nclass Fixture:\n    def method(self, value):\n        return value + 1\n")
            function = collector.pure_method(source, "Fixture", "method", {})
            self.assertEqual(function(None, 2), 3)

    def test_continuous_label_and_executed_decoded_value_remain_distinct(self):
        def quantize(self, value, axis):
            vmin, vmax = collector.STATS[axis]["min"], collector.STATS[axis]["max"]
            return int((max(vmin, min(vmax, value)) - vmin) / (vmax - vmin) * 98)
        def parse(self, text):
            bins = map(int, text.split(": ")[1].split())
            return tuple(b / 98 * (collector.STATS[axis]["max"] - collector.STATS[axis]["min"]) + collector.STATS[axis]["min"] for b, axis in zip(bins, ("forward", "down", "yaw")))
        result = collector.label_roundtrip({"fwd": 0., "down": 0., "yaw": -.5}, quantize, parse)
        self.assertEqual(result["action_text"], "00 49 26")
        self.assertNotEqual(result["decoded_action"]["yaw"], -.5)
        self.assertFalse(result["decoded_should_stop"])
        self.assertEqual(result["continuous_label"]["yaw"], -.5)
        with self.assertRaises(ValueError): collector.label_roundtrip({"fwd": 0., "down": 0., "yaw": 0.}, quantize, parse)

    def test_stale_camera_fails_even_with_good_groundtruth(self):
        reference, initial, final = self.state(), self.state(.5), self.state(.02)
        good = collector.endpoint_measurements(reference, initial, final, final["orientation"], initial["position"], final["position"])
        self.assertTrue(all(good["checks"].values()))
        stale = collector.endpoint_measurements(reference, initial, final, initial["orientation"], initial["position"], final["position"])
        self.assertFalse(stale["checks"]["front_camera_heading_restored"])
        self.assertFalse(stale["checks"]["front_camera_heading_error_reduced"])

    def test_drift_and_error_reduction_are_independent(self):
        result = collector.endpoint_measurements(self.state(), self.state(.1), self.state(.14), self.state(.14)["orientation"], [0, 0, 0], [.4, 0, -.4])
        self.assertTrue(result["checks"]["groundtruth_heading_restored"])
        self.assertFalse(result["checks"]["groundtruth_heading_error_reduced"])
        self.assertFalse(result["checks"]["horizontal_drift_bounded"])
        self.assertFalse(result["checks"]["vertical_drift_bounded"])

    def test_candidate_export_keeps_unapproved_status_and_exact_source_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "evidence").mkdir()
            images = []
            for camera in ("front", "down"):
                path = root / "evidence" / (camera + ".png")
                path.write_bytes(b"synthetic-test-bytes-not-video-or-observation")
                images.append({"camera": camera, "modality": "rgb", "path": path.name, "sha256": collector.sha(path)})
            sample = {"sample_id": "synthetic", "episode_id": "Map/fixture/merged_data.json"}
            action = {"continuous_label": {"fwd": 0., "down": 0., "yaw": -.5}}
            result = collector.export_candidate(root, sample, {"event_id": 1, "images": images}, action, "<image>\nSynthetic prompt", {})
            self.assertEqual(result["approval"], "not_asserted")
            row = json.loads((root / "candidate/candidate_rows.json").read_text())[0]
            self.assertFalse(row["is_last_step"])
            self.assertFalse(row["is_penultimate"])
            self.assertEqual(row["traj_rel_dir"], "Map/fixture")
            self.assertFalse((root / "manifest.json").exists())
            self.assertEqual(collector.sha(root / "candidate/Map/fixture/frontcamera/000000.png"), images[0]["sha256"])


if __name__ == "__main__":
    unittest.main()
