"""Synthetic hook contracts; no simulator, model or rendering evidence."""
import copy
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
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
probe = load("simulator_probe")


class OptionalResetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.previous_cwd = Path.cwd()
        os.chdir(self.root)
        self.env_patch = patch.dict(os.environ, {
            "VLA_LAB_SCENE_MANAGER_EXCLUSIVE": "1",
            "VLA_LAB_RESET_PROTOCOL": hooks.TIMED_RESET_PROTOCOL,
            "VLA_LAB_RUNTIME_ID": "aerovla-rpcfix-msgpack112-paused-final-pose-time-v1",
            "VLA_LAB_EVENT_DIR": str(self.root / "events"),
            "VLA_LAB_RUNTIME_RECEIPT": "",
        })
        self.env_patch.start()
        self.runtime = None
        self.trace = []
        self.camera_checks = {"synthetic_camera_gate": True}
        self.helper_file = self.root / "_vla_lab_reset.py"
        self.helper_file.write_bytes((SCRIPTS / "reset_protocol.py").read_bytes())
        self.helper_sha = hashlib.sha256(self.helper_file.read_bytes()).hexdigest()
        self.manifest = {
            "protocol": "aerovla-e37685a-observed-v1",
            "files": {"_vla_lab_reset.py": {"sha256": self.helper_sha}},
            "optional_reset_protocols": {hooks.TIMED_RESET_PROTOCOL: {
                "helper": "_vla_lab_reset.py", "sha256": self.helper_sha}}
        }
        (self.root / "vla_lab_patch_manifest.json").write_text(json.dumps(self.manifest))
        self.settings = self.root / "airsim_plugin/settings/30001/settings.json"
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text(json.dumps({"ClockSpeed": 10}))
        self.reference = {"position": [1, 2, -3], "orientation": [0, 0, 0, 1]}
        state = {**copy.deepcopy(self.reference), "collision": {"has_collided": False}}
        self.latest = {"rgb": [SimpleNamespace(shape=(256, 256, 3)) for _ in range(5)],
                       "depth": [SimpleNamespace(shape=(256, 256)) for _ in range(5)],
                       "sensors": {"state": state, "imu": {"timestamp": 7}}}
        self.outputs = ([[self.latest]], "original second return")
        self.env = SimpleNamespace(batch_size=1, data=[{}], batch=[{"trajectory": [self.reference]}],
            simulator_tool=SimpleNamespace(airsim_ports=[30001], machines_info=[], _closeConnection=lambda: None),
            changeToNewTrajectorys=lambda: self.trace.append("original_trajectory_reset"))
        def reset():
            self.env.changeToNewTrajectorys()
            self.trace.append("original_image_capture")
            return self.outputs
        self.env.reset = reset
        def install(env, runtime, protocol):
            self.trace.append("install_helper")
            self.base_hooks_before_helper = [name for _, name, _ in runtime.restore]
            helper = SimpleNamespace(source_sha256=self.helper_sha, reset_ordinal=0)
            def after(original, *args, **kwargs):
                result = original(*args, **kwargs)
                helper.reset_ordinal += 1
                self.trace.append("timed_pose_and_cache_refresh")
                return result
            runtime.patch(env, "changeToNewTrajectorys", after)
            def acceptance(position, angle):
                self.assertEqual((position, angle), (0.1, 0.05))
                self.trace.append("camera_acceptance")
                return {"checks": self.camera_checks,
                        "settings_sha256": hashlib.sha256(self.settings.read_bytes()).hexdigest()}
            helper.acceptance = acceptance
            return helper
        self.module = SimpleNamespace(__file__=str(self.helper_file), TIMED_PROTOCOL=hooks.TIMED_RESET_PROTOCOL, install=install)
        self.module_patch = patch.dict(sys.modules, {"_vla_lab_reset": self.module})
        self.module_patch.start()

    def tearDown(self):
        if self.runtime:
            self.runtime.close()
        self.module_patch.stop()
        self.env_patch.stop()
        os.chdir(self.previous_cwd)
        self.tmp.cleanup()

    def make_runtime(self):
        self.runtime = hooks.Runtime(self.env, SimpleNamespace(eval_save_path=str(self.root), maxWaypoints=200),
                                     SimpleNamespace(model_path="synthetic-adapter"))
        self.runtime.attempt_id = "synthetic-attempt"
        self.runtime.rec.context = {"attempt_id": self.runtime.attempt_id}
        return self.runtime

    def events(self):
        return [json.loads(row) for row in (self.root / "events/events.jsonl").read_text().splitlines()]

    def test_default_never_loads_helper_or_changes_reset(self):
        os.environ.pop("VLA_LAB_RESET_PROTOCOL")
        os.environ.pop("VLA_LAB_RUNTIME_ID")
        self.helper_file.unlink()
        (self.root / "vla_lab_patch_manifest.json").unlink()
        runtime = self.make_runtime()
        original = self.env.reset
        runtime.install_optional_reset()
        self.assertIs(self.env.reset, original)
        self.assertIs(self.env.reset(), self.outputs)
        self.assertEqual(self.trace, ["original_trajectory_reset", "original_image_capture"])
        start = self.events()[0]
        self.assertEqual(start["reset_protocol"], "upstream")
        self.assertIsNone(start["reset_helper_sha256"])

    def test_missing_or_previous_runtime_identity_is_rejected_before_recorder(self):
        for runtime_id in ("unrecorded", "aerovla-official-rpcfix-msgpack112-v1", "", hooks.TIMED_RESET_PROTOCOL + "\nwrong"):
            with self.subTest(runtime_id=runtime_id):
                os.environ["VLA_LAB_RUNTIME_ID"] = runtime_id
                with self.assertRaisesRegex(ValueError, "explicit VLA_LAB_RUNTIME_ID"):
                    self.make_runtime()
                self.assertFalse((self.root / "events").exists())

    def test_unknown_or_empty_option_is_rejected(self):
        for name in ("paused-final-pose-v1", "", "other"):
            with self.subTest(name=name):
                os.environ["VLA_LAB_RESET_PROTOCOL"] = name
                with self.assertRaisesRegex(ValueError, "Unsupported"):
                    self.make_runtime()

    def test_missing_manifest_and_helper_hash_mismatch_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "patch manifest"):
            hooks.reset_configuration(None, os.environ["VLA_LAB_RUNTIME_ID"])
        self.helper_file.write_text("# changed helper\n")
        with self.assertRaisesRegex(ValueError, "SHA256"):
            self.make_runtime()
        self.assertNotIn("install_helper", self.trace)

    def test_imported_helper_from_other_checkout_is_rejected(self):
        self.module.__file__ = str(self.root / "other.py")
        with self.assertRaisesRegex(ValueError, "different checkout"):
            self.make_runtime()

    def test_acceptance_is_after_capture_before_prepare_and_return_is_unchanged(self):
        runtime = self.make_runtime()
        self.env.base_hook = lambda: None
        runtime.patch(self.env, "base_hook", lambda original: original())
        runtime.install_optional_reset()
        self.assertEqual(self.base_hooks_before_helper, ["base_hook"])
        self.assertIs(self.env.reset(), self.outputs)
        self.assertEqual(self.trace, ["install_helper", "original_trajectory_reset", "timed_pose_and_cache_refresh",
                                      "original_image_capture", "camera_acceptance"])
        inputs = [{"input_ids": [[1]], "pixel_values": SimpleNamespace(shape=(1, 3, 224, 224))}]
        model = SimpleNamespace(tokenizer=SimpleNamespace(batch_decode=lambda *args, **kw: ["synthetic prompt"]))
        runtime.observe = lambda *args, **kwargs: self.trace.append("record_observation")
        result = runtime.prepare(lambda *args, **kwargs: (self.trace.append("model_prepare") or inputs), model,
                                 episodes=[[self.latest]])
        self.assertIs(result, inputs)
        self.assertLess(self.trace.index("camera_acceptance"), self.trace.index("model_prepare"))
        start = self.events()[0]
        self.assertEqual(start["reset_helper_sha256"], self.helper_sha)
        self.assertEqual(start["reset_protocol"], hooks.TIMED_RESET_PROTOCOL)
        self.assertEqual(start["protocol"], "aerovla-e37685a-observed-v1")
        outcome = json.loads(next((self.root / "events/reset_acceptance").glob("*.json")).read_text())
        self.assertTrue(outcome["gate_passed"])
        self.assertNotIn("episode.completed", [e["event_type"] for e in self.events()])

    def test_bad_camera_is_retained_as_rejection_and_cannot_reach_prepare(self):
        runtime = self.make_runtime()
        runtime.install_optional_reset()
        self.camera_checks["synthetic_camera_gate"] = False
        with self.assertRaisesRegex(RuntimeError, "synthetic_camera_gate"):
            self.env.reset()
        called = []
        with self.assertRaisesRegex(RuntimeError, "before model input"):
            runtime.prepare(lambda *args: called.append(1), None)
        self.assertEqual(called, [])
        event = self.events()[-1]
        self.assertEqual(event["status"], "rejected")
        self.assertFalse(event["gate_passed"])
        self.assertIn("camera_reset_measurements", event)

    def test_contact_and_clock_change_fail_existing_gates(self):
        runtime = self.make_runtime()
        runtime.install_optional_reset()
        self.latest["sensors"]["state"]["collision"]["has_collided"] = True
        self.settings.write_text(json.dumps({"ClockSpeed": 1}))
        with self.assertRaisesRegex(RuntimeError, "no_initial_endpoint_contact.*upstream_clock_speed_10"):
            self.env.reset()

    def test_shape_and_zero_quaternion_fail_without_scipy(self):
        self.latest["rgb"][0].shape = (1, 1, 3)
        with self.assertRaisesRegex(ValueError, "shape"):
            hooks.initial_reset_checks(self.outputs, self.reference)
        self.latest["rgb"][0].shape = (256, 256, 3)
        self.latest["sensors"]["state"]["orientation"] = [0, 0, 0, 0]
        with self.assertRaisesRegex(ValueError, "zero quaternion"):
            hooks.initial_reset_checks(self.outputs, self.reference)
        self.latest["sensors"]["state"]["orientation"] = [0, 0, 0, float("nan")]
        with self.assertRaisesRegex(ValueError, "finite xyz"):
            hooks.initial_reset_checks(self.outputs, self.reference)

    def test_cached_pose_matches_original_p03_checks_at_boundaries(self):
        for position, orientation in (([1.1, 2, -3], [0, 0, 0, -1]), ([1, 2, -3], [0, 0, math.sin(.04), math.cos(.04)])):
            self.latest["sensors"]["state"].update(position=position, orientation=orientation)
            actual = hooks.initial_reset_checks(self.outputs, self.reference)
            expected = probe.reset_checks(self.latest["sensors"]["state"], self.reference, .1, .05)
            for name, value in expected["checks"].items():
                self.assertEqual(actual["checks"][name], value)
            self.assertEqual(actual["reset_orientation_error_rad"], expected["reset_orientation_error_rad"])
            self.assertEqual(actual["reset_position_error_m"], expected["reset_position_error_m"])

    def test_previous_acceptance_cannot_authorize_a_new_attempt(self):
        runtime = self.make_runtime()
        runtime.install_optional_reset()
        self.env.reset()
        runtime.episode(lambda: [{"seq_name": "new", "map_name": "synthetic", "instruction": "synthetic",
                                 "merged_json": "synthetic.json", "object_position": [0, 0, 0], "trajectory": [self.reference]}])
        with self.assertRaisesRegex(RuntimeError, "before model input"):
            runtime.prepare(lambda *args: self.fail("must not prepare"), None)
        self.assertIsNone(runtime.reset_accepted_attempt)

    def test_reset_rpc_error_is_a_failed_reset_record(self):
        runtime = self.make_runtime()
        runtime.install_optional_reset()
        self.env.changeToNewTrajectorys = lambda: (_ for _ in ()).throw(RuntimeError("synthetic RPC error"))
        with self.assertRaisesRegex(RuntimeError, "synthetic RPC error"):
            self.env.reset()
        event = self.events()[-1]
        self.assertEqual(event["status"], "rejected")
        self.assertEqual(event["error_type"], "RuntimeError")
        self.assertFalse(event["gate_passed"])

    def test_image_write_hash_timing_and_close_prefix_accounting(self):
        os.environ["VLA_LAB_RESET_PROTOCOL"] = "upstream"
        runtime = self.make_runtime()
        def write(path, image):
            Path(path).write_bytes(b"synthetic unit fixture; not image evidence")
            return True
        with patch.dict(sys.modules, {"cv2": SimpleNamespace(imwrite=write)}):
            runtime.observe(self.latest, prepare_start_ns=0)
        event = self.events()[-1]
        self.assertEqual(len(event["images"]), 10)
        self.assertEqual(event["image_write_hash_ns"], event["image_write_hash_end_ns"] - event["image_write_hash_start_ns"])
        self.assertGreaterEqual(event["prepare_and_record_ns"], event["image_write_hash_ns"])
        runtime.rec.write_json("synthetic.json", {"fixture": True})
        runtime.close()
        end = self.events()[-1]
        measurement = end["recording_measurements"]
        self.assertEqual(measurement["event_count_before_run_end"], end["event_id"] - 1)
        self.assertGreater(measurement["event_serialization_write_ns_before_run_end"], 0)
        self.assertGreater(measurement["json_artifact_write_ns_before_run_end"], 0)
        self.assertEqual(measurement["json_artifact_count_before_run_end"], 2)  # Explicit fixture + interrupted partial.
        self.assertIn("Excludes run.end", measurement["scope"])

    def test_main_installs_optional_helper_after_all_base_hooks(self):
        class Wrapper:
            def __init__(self): pass
            def prepare_inputs(self): pass
            def run(self): pass
        class BatchState:
            def check_batch_termination(self): pass
        class ClientTool:
            def run_call(self): pass
        self.env.next_minibatch = lambda: None
        self.env.makeActions = lambda: None
        modules = {
            "src.model_wrapper.aerovla_wrapper_ui": SimpleNamespace(AerialVLAWrapper=Wrapper),
            "src.vlnce_src.closeloop_util": SimpleNamespace(EvalBatchState=BatchState),
            "airsim_plugin.AirVLNSimulatorClientTool_AeroVLA": SimpleNamespace(AirVLNSimulatorClientTool=ClientTool),
        }
        with patch.dict(sys.modules, modules):
            self.runtime = hooks.install(self.env, SimpleNamespace(eval_save_path=str(self.root), maxWaypoints=200),
                                         SimpleNamespace(model_path="synthetic"))
        self.assertEqual(self.base_hooks_before_helper,
                         ["next_minibatch", "makeActions", "__init__", "prepare_inputs", "run", "run_call", "check_batch_termination"])

    def test_patcher_copies_helper_bytes_and_manifest_without_activating(self):
        source = ('if __name__ == "__main__":\n'
                  '    model_wrapper = AerialVLAWrapper(model_args=model_args, data_args=data_args)\n'
                  '    eval(model_wrapper=model_wrapper)\n'
                  '    eval_env.delete_VectorEnvUtil()\n')
        checkout = self.root / "checkout"
        target = checkout / patcher.RELATIVE_EVALUATOR
        target.parent.mkdir(parents=True)
        target.write_text(source)
        with patch.object(patcher, "PROTECTED_SOURCE_HASHES", {}), \
                patch.object(patcher, "EVALUATOR_SHA256", patcher.digest(source.encode())), \
                patch.object(sys, "argv", ["patcher", "--checkout", str(checkout), "--apply"]), \
                patch("sys.stdout", io.StringIO()):
            patcher.main()
        self.assertEqual((checkout / "_vla_lab_reset.py").read_bytes(), (SCRIPTS / "reset_protocol.py").read_bytes())
        manifest = json.loads((checkout / "vla_lab_patch_manifest.json").read_text())
        self.assertEqual(manifest["default_reset_protocol"], "upstream")
        self.assertEqual(manifest["files"]["_vla_lab_reset.py"]["sha256"], self.helper_sha)
        self.assertEqual(manifest["optional_reset_protocols"][hooks.TIMED_RESET_PROTOCOL]["sha256"], self.helper_sha)
        self.assertNotIn("VLA_LAB_RESET_PROTOCOL=", target.read_text())


if __name__ == "__main__":
    unittest.main()
