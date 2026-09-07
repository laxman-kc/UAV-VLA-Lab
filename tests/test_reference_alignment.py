"""Synthetic source/measurement contracts; never simulator or label approval."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import audit_reference_alignment as audit


class ReferenceAlignmentTests(unittest.TestCase):
    def raw(self, frame=10):
        return {"frame": frame, "sensors": {"state": {"position": [1., 2., -3.], "orientation": [0., 0., 0., 1.]}}}

    def test_frame_identity_and_no_invented_timestamp(self):
        state = audit.validated_pose(self.raw(), 10)
        self.assertEqual(state["timestamp_fields"], [])
        self.assertEqual(state["quaternion_norm"], 1)
        with self.assertRaisesRegex(ValueError, "identity"):
            audit.validated_pose(self.raw(), 15)
        bad = self.raw()
        bad["frame"] = True
        with self.assertRaises(ValueError): audit.validated_pose(bad, 1)

    def test_nonfinite_bool_zero_and_shape_rejected(self):
        for key, value in (("position", [True, 0, 0]), ("position", [math.inf, 0, 0]),
                           ("position", [0, 0]), ("orientation", [0, 0, 0, 0]),
                           ("orientation", [0, 0, 0, math.nan])):
            bad = self.raw()
            bad["sensors"]["state"][key] = value
            with self.assertRaises(ValueError): audit.validated_pose(bad, 10)

    def test_timestamp_fields_are_preserved_without_units_inference(self):
        raw = self.raw()
        raw["sensors"]["state"]["timestamp"] = 1234
        self.assertEqual(audit.validated_pose(raw, 10)["timestamp_fields"], [{"path": "state.timestamp", "value": 1234}])

    def test_exact_components_preserve_dropped_axes(self):
        result = audit.scalar_residuals({"fwd": 2., "down": -1., "yaw": .1}, [2., .7, -1.], [.1, .03, -.04])
        self.assertTrue(result["all_components_within_tolerance"])
        self.assertEqual(result["absolute_residuals"], {"fwd": 0., "down": 0., "yaw": 0.})
        self.assertEqual(result["dropped_body_y_m"], .7)
        self.assertEqual(result["dropped_relative_pitch_rad"], .03)
        self.assertEqual(result["dropped_relative_roll_rad"], -.04)
        self.assertNotIn("approval", result)

    def test_fixed_residual_threshold_rejects_mismatch_without_regeneration(self):
        label = {"fwd": 2., "down": -1., "yaw": .1}
        before = copy.deepcopy(label)
        result = audit.scalar_residuals(label, [2.+2e-9, 0., -1.], [.1, 0., 0.])
        self.assertFalse(result["all_components_within_tolerance"])
        self.assertEqual(label, before)
        self.assertEqual(audit.TOLERANCE, 1e-9)
        self.assertEqual(audit.OFFSET, 5)

    def test_controller_large_yaw_drops_forward(self):
        result = audit.nominal_controller({"fwd": 3., "down": -1., "yaw": .5}, 0, [3., 0., -1.], .5)
        self.assertEqual(result["branch"], "rotate_then_altitude_only")
        self.assertEqual(result["nominal_world_delta_m"], [0., 0., -1.])
        self.assertEqual(result["reference_minus_nominal_l2_m"], 3.)

    def test_controller_rotates_before_translation(self):
        result = audit.nominal_controller({"fwd": 2., "down": 0., "yaw": .1}, 0, [2., 0., 0.], .1)
        self.assertAlmostEqual(result["nominal_world_delta_m"][0], 2 * math.cos(.1))
        self.assertAlmostEqual(result["nominal_world_delta_m"][1], 2 * math.sin(.1))
        self.assertGreater(result["reference_minus_nominal_l2_m"], 0.)

    def test_byte_receipts_preserve_historical_path_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.json"
            path.write_text("[]\n")
            receipt = audit.preparation.file_record(path)
            receipt["path"] = "/historical/remote/source.json"
            self.assertEqual(audit.match_record(path, receipt)["sha256"], receipt["sha256"])
            path.write_text("[1]\n")
            with self.assertRaisesRegex(ValueError, "mismatch"): audit.match_record(path, receipt)

    def test_preparation_chronology_rejects_future_naive_and_malformed(self):
        started = "2026-09-07T00:00:00+00:00"
        audit.before_start("2026-09-06T20:00:00-04:00", started)
        for bad in ("2026-09-08T00:00:00Z", "2026-09-06T00:00:00", "bad", None):
            with self.assertRaises(ValueError): audit.before_start(bad, started)

    def test_codec_isolates_method_without_module_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "test.py"
            source.write_text("raise RuntimeError('not imported')\nclass Codec:\n    def value(self, x):\n        return x * 2\n")
            method = audit.pure_method(source, "Codec", "value", {})
            self.assertEqual(method(None, 3), 6)
            with self.assertRaises(ValueError): audit.pure_method(source, "Missing", "value", {})


if __name__ == "__main__":
    unittest.main()
