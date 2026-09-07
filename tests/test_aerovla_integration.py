"""Unit fixtures are synthetic and never constitute simulator/model evidence."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hooks = load("_aerovla_runtime_hooks")
patcher = load("patch_aerovla_runtime")
selector = load("prepare_aerovla_episode")
probe = load("simulator_probe")


class IntegrationTests(unittest.TestCase):
    def test_probe_displacement_tracks_upstream_large_yaw_branch(self):
        import math
        delta = probe.expected_displacement({"fwd": 2, "down": -1, "yaw": 0}, math.pi / 2)
        self.assertAlmostEqual(delta[0], 0)
        self.assertAlmostEqual(delta[1], 2)
        self.assertEqual(delta[2], -1)
        self.assertEqual(probe.expected_displacement({"fwd": 2, "down": -1, "yaw": 0.25}, 0), [0, 0, -1])

    def test_probe_rejects_nonisolated_controller_configuration(self):
        from copy import deepcopy
        config = deepcopy(probe.DEFAULT_PROBES)
        self.assertEqual(probe.validate_probes(config), config)
        config[0]["action"]["fwd"] = 1
        with self.assertRaisesRegex(ValueError, "isolate"):
            probe.validate_probes(config)

    def test_reset_check_handles_quaternion_sign_and_detects_wrong_position(self):
        result = probe.reset_checks({"position": [1, 0, -2], "orientation": [0, 0, 0, -1]},
                                    {"position": [0, 0, -2], "orientation": [0, 0, 0, 1]}, 0.1, 0.05)
        self.assertTrue(result["checks"]["reset_orientation_within_tolerance"])
        self.assertFalse(result["checks"]["reset_position_within_tolerance"])

    def test_probe_empty_evidence_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            checks = probe.log_checks(Path(directory), [], "capture", 2)
        self.assertFalse(checks["expected_observation_count"])
        self.assertFalse(checks["images_present_and_hashes_match"])
        self.assertFalse(checks["capture_links_and_timestamps_present"])

    def test_patch_rejects_changed_source(self):
        with self.assertRaisesRegex(ValueError, "differs"):
            patcher.instrument("print('other checkout')\n")

    def test_cancellation_propagates_but_regular_fallback_remains(self):
        source = "def example(error):\n    try:\n        raise error\n    except:\n        return 'fallback'\n"
        namespace = {}
        exec(patcher.propagate_cancellation(source), namespace)
        self.assertEqual(namespace["example"](ValueError("fixture")), "fallback")
        with self.assertRaises(SystemExit):
            namespace["example"](SystemExit(143))

    def test_patch_preserves_original_call_and_adds_finally(self):
        source = (
            'if __name__ == "__main__":\n'
            '    model_wrapper = AerialVLAWrapper(model_args=model_args, data_args=data_args)\n'
            '    eval(model_wrapper=model_wrapper)\n'
            '    eval_env.delete_VectorEnvUtil()\n'
        )
        with patch.object(patcher, "EVALUATOR_SHA256", patcher.digest(source.encode())):
            result = patcher.instrument(source)
        self.assertEqual(result.count("eval(model_wrapper=model_wrapper)"), 1)
        self.assertEqual(result.count("eval_env.delete_VectorEnvUtil()"), 1)
        self.assertIn("_vla_runtime.close(error=sys.exc_info()[1])", result)

    def test_recorder_rejects_attempt_log_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = hooks.Recorder(directory)
            recorder.emit("test.fixture", a=1)
            recorder.stream.close()
            with self.assertRaises(FileExistsError):
                hooks.Recorder(directory)

    def test_wrapped_action_returns_same_object_and_logs_requested_value(self):
        with tempfile.TemporaryDirectory() as directory:
            env = types.SimpleNamespace(batch_size=1, data=[{}])
            args = types.SimpleNamespace(eval_save_path=directory, maxWaypoints=2)
            with patch.dict(os.environ, {"VLA_LAB_SCENE_MANAGER_EXCLUSIVE": "1", "VLA_LAB_EVENT_DIR": directory}):
                runtime = hooks.Runtime(env, args, types.SimpleNamespace(model_path="fixture-adapter"))
            expected = [[{"position": [1, 2, 3]}]]
            actions = [{"fwd": 1.2, "down": -0.4, "yaw": 0.5}]
            seen = []
            def original(value):
                seen.append(value)
                return expected
            try:
                actual = runtime.action(original, actions)
                self.assertIs(actual, expected)
                self.assertIs(seen[0], actions)
            finally:
                runtime.close()
            events = [json.loads(row) for row in (Path(directory) / "events.jsonl").read_text().splitlines()]
            request = next(row for row in events if row["event_type"] == "action.requested")
            self.assertEqual(request["actions"], actions)

    def test_outcome_retains_upstream_oracle_before_collision_precedence(self):
        state = types.SimpleNamespace(success=[False], oracle_success=[True], collisions=[True], early_end=[False],
                                      dones=[True], predict_dones=[False], distance_to_ends=[[21.0]], stuck_counters=[16],
                                      episodes=[[{"sensors": {"state": {"collision": {"has_collided": False}, "timestamp": 7}}}]])
        result = hooks.outcome_for(state, 8)
        self.assertEqual(result["termination_reason"], "oracle_success")
        self.assertTrue(result["upstream_flags"]["collisions"])
        self.assertFalse(result["endpoint_contact"]["has_collided"])

    def test_selector_preserves_genuine_rows_and_requires_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "dataset_raw" / "FixtureMap" / "fixture-episode"
            raw.mkdir(parents=True)
            metadata = root / "meta"
            metadata.mkdir()
            rows = [{"json": "FixtureMap/fixture-episode/merged_data.json", "frame": 1},
                    {"json": "FixtureMap/fixture-episode/merged_data.json", "frame": 2}]
            split = root / "split.json"
            split.write_text(json.dumps(rows))
            (raw / "merged_data.json").write_text(json.dumps({
                "trajectory_raw_detailed": [{"position": [0, 0, -2], "orientation": [0, 0, 0, 1]}],
                "conversations": [{"value": "Target is 5 degrees from you. Fixture description. Please control the UAV."}]}))
            (raw / "mark.json").write_text(json.dumps({"object_name": "fixture", "target": {"position": [1, 2, 3]}}))
            (raw / "object_description.json").write_text("{}")
            (metadata / "object_description.json").write_text("[]")
            (metadata / "map_spawnarea_info.json").write_text(json.dumps({"FixtureMap": [[0] * 18]}))
            selected, manifest = selector.select_and_validate(split, root / "dataset_raw", metadata, "fixture-episode")
            self.assertEqual(selected, rows)
            self.assertEqual(manifest["unique_trajectories"], 1)
            (raw / "mark.json").unlink()
            with self.assertRaises(FileNotFoundError):
                selector.select_and_validate(split, root / "dataset_raw", metadata, "fixture-episode")


if __name__ == "__main__":
    unittest.main()
