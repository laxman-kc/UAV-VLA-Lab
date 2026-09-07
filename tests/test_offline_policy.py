"""Synthetic unit fixtures only: these are not recorded flights or model evidence."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("offline_policy_probe", Path(__file__).resolve().parents[1] / "scripts/offline_policy_probe.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class OfflinePolicyTests(unittest.TestCase):
    def fixture(self, root):
        trajectory = root / "Map/demo"
        for directory in ("log", "frontcamera", "downcamera"):
            (trajectory / directory).mkdir(parents=True)
        states = [{"position": [float(i), 0, -2], "orientation": [0, 0, 0, 1]} for i in range(7)]
        for i, state in enumerate(states):
            (trajectory / "log" / f"{i:06d}.json").write_text(json.dumps({"frame": i, "sensors": {"state": state}}))
            for camera in ("frontcamera", "downcamera"):
                (trajectory / camera / f"{i:06d}.png").write_bytes(b"synthetic-placeholder-not-image-evidence")
        merged = {"trajectory_raw_detailed": states, "trajectory_raw": states, "index": list(range(7)),
                  "conversations": [{"value": "Target 25 degrees from you. Original benchmark description. Please control the drone."}]}
        (trajectory / "merged_data.json").write_text(json.dumps(merged))
        (trajectory / "mark.json").write_text(json.dumps({"target": {"position": [4, 5, 6]}, "object_name": "fixture"}))
        (trajectory / "object_description.json").write_text(json.dumps(["Original benchmark description."]))
        selection = root / "selection.json"
        selection.write_text(json.dumps({"kind": "genuine_upstream_episode_selection", "map_name": "Map", "episode_id": "demo"}))
        return trajectory, selection

    def test_input_selection_preserves_real_mapping_and_instruction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trajectory, selection = self.fixture(root)
            provenance, mark = probe.prepare_recorded_inputs(root, selection)
            self.assertEqual([frame["frame_id"] for frame in provenance["frames"]], [0, 3, 6])
            self.assertEqual(provenance["frames"][1]["state"]["position"], [3.0, 0, -2])
            self.assertEqual(provenance["instruction"], json.loads((trajectory / "merged_data.json").read_text())["conversations"][0]["value"])
            self.assertEqual(mark["object_name"], "fixture")
            self.assertEqual(len(provenance["frames"][0]["source_files"]), 3)

    def test_rejects_shifted_state_alignment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trajectory, selection = self.fixture(root)
            path = trajectory / "log/000003.json"
            log = json.loads(path.read_text())
            log["sensors"]["state"]["position"][0] = 500
            path.write_text(json.dumps(log))
            with self.assertRaisesRegex(ValueError, "disagrees"):
                probe.prepare_recorded_inputs(root, selection)

    def test_requires_three_complete_pairs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trajectory, selection = self.fixture(root)
            for i in range(5):
                (trajectory / "downcamera" / f"{i:06d}.png").unlink()
            with self.assertRaisesRegex(ValueError, "three complete"):
                probe.prepare_recorded_inputs(root, selection)

    def test_rejects_dataset_escape_and_multiple_trajectories(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                probe.contained(Path(directory), "../another/merged_data.json")
            outside = Path(directory).parent / "outside-dataset-fixture"
            (Path(directory) / "escape").symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "escapes"):
                probe.contained(Path(directory), "escape/merged_data.json")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            probe.selected_trajectory([{"json": "Map/a/merged_data.json"}, {"json": "Map/b/merged_data.json"}])

    def test_strict_target_grammar_and_upstream_fallback_are_distinct(self):
        self.assertTrue(probe.parse_diagnostic("Prompt 200: Action: 00 49 98 LAND</s>")["strict_valid"])
        self.assertTrue(probe.parse_diagnostic("12 34 56</s>")["strict_valid"])
        malformed = probe.parse_diagnostic("Action: failed</s>")
        self.assertFalse(malformed["strict_valid"])
        self.assertTrue(malformed["upstream_numeric_default_to_zero"])
        oversized = probe.parse_diagnostic("Action: 00 49 100")
        self.assertFalse(oversized["strict_valid"])
        self.assertTrue(oversized["upstream_clamps_selected_bins"])
        extra = probe.parse_diagnostic("Action: reason 77 then 01 49 49")
        self.assertFalse(extra["strict_valid"])
        self.assertEqual(extra["upstream_selected_last_three_bins"], [1, 49, 49])
        negative = probe.parse_diagnostic("Action: -01 49 49")
        self.assertFalse(negative["strict_valid"])
        self.assertEqual(negative["upstream_selected_last_three_bins"], [1, 49, 49])

    def test_nonfinite_or_invalid_state_rejected(self):
        for state in ({"position": [float("nan"), 0, 0], "orientation": [0, 0, 0, 1]},
                      {"position": [0, 0, 0], "orientation": [0, 0, 0, 0]},
                      {"position": [True, 0, 0], "orientation": [0, 0, 0, 1]}):
            with self.assertRaises(ValueError):
                probe.validate_state(state)

    def test_model_identity_detects_changed_receipt_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "base"
            model.mkdir()
            config = model / "config.json"
            config.write_text("{}")
            entry = {"relative_path": "base/config.json", "bytes": config.stat().st_size,
                     "sha256": probe.digest(config), "repository": "synthetic/fixture", "revision": "fixture-revision"}
            (root / "model-files.verified.json").write_text(json.dumps([entry]))
            self.assertEqual(probe.model_identity(model)["repositories"], [("synthetic/fixture", "fixture-revision")])
            config.write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError, "differs"):
                probe.model_identity(model)


if __name__ == "__main__":
    unittest.main()
