"""End-to-end evidence integrity tests; fixtures never claim a real flight."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from uav_vla_lab.config import ContractError, read_json, validate_replay, write_json
from uav_vla_lab.provenance import file_record
from uav_vla_lab.replay import calculate, run_replay, verify_bundle


class CoreReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = ROOT / "examples/synthetic-replay/input.json"
        self.spec = read_json(self.input)
        self.output = self.root / "replay"

    def test_hand_calculated_geometry_and_explicit_scope(self):
        events, metrics = calculate(self.spec)
        self.assertEqual(metrics["action_count"], 4)
        self.assertEqual(metrics["state_count"], 5)
        expected = {"x": 1, "y": 1.5, "z": -0.25, "yaw": 0}
        for key, value in expected.items():
            self.assertAlmostEqual(metrics["final_state"][key], value, places=12)
        self.assertAlmostEqual(metrics["logical_path_length_metres"], 2 + 0.3125 ** 0.5)
        self.assertIsNone(metrics["navigation_success"])
        self.assertIsNone(metrics["physical_elapsed_seconds"])
        self.assertEqual([event["event_id"] for event in events], list(range(1, 10)))

    def test_replay_outputs_can_be_moved_and_verified(self):
        receipt = run_replay(self.input, self.output)
        moved = self.root / "elsewhere"
        self.output.rename(moved)
        self.assertEqual(verify_bundle(moved), receipt)
        self.assertEqual((moved / "input.json").read_bytes(), self.input.read_bytes())
        self.assertIn("Synthetic", (moved / "report.html").read_text())
        self.assertNotIn(str(ROOT), (moved / "manifest.json").read_text())

    def test_existing_attempt_never_overwritten(self):
        run_replay(self.input, self.output)
        before = (self.output / "manifest.json").read_bytes()
        with self.assertRaises(FileExistsError):
            run_replay(self.input, self.output)
        self.assertEqual(before, (self.output / "manifest.json").read_bytes())

    def rehash(self, member):
        manifest = read_json(self.output / "manifest.json")
        manifest["files"] = [file_record(self.output / record["path"], relative_to=self.output)
                             if record["path"] == member else record for record in manifest["files"]]
        write_json(self.output / "manifest.json", manifest)

    def test_changed_source_bytes_fail_integrity(self):
        run_replay(self.input, self.output)
        with (self.output / "input.json").open("a") as handle:
            handle.write(" ")
        with self.assertRaisesRegex(ContractError, "size mismatch"):
            verify_bundle(self.output)

    def test_rehashed_false_metrics_still_fail(self):
        run_replay(self.input, self.output)
        metrics = read_json(self.output / "metrics.json")
        metrics["navigation_success"] = True
        write_json(self.output / "metrics.json", metrics)
        self.rehash("metrics.json")
        with self.assertRaisesRegex(ContractError, "contradict"):
            verify_bundle(self.output)

    def test_rehashed_broken_causal_link_fails(self):
        run_replay(self.input, self.output)
        path = self.output / "events.jsonl"
        events = [json.loads(line) for line in path.read_text().splitlines()]
        events[3]["source_state_event_id"] = 1
        path.write_text("".join(json.dumps(event) + "\n" for event in events))
        self.rehash("events.jsonl")
        with self.assertRaisesRegex(ContractError, "contradict"):
            verify_bundle(self.output)

    def test_boolean_event_id_cannot_impersonate_integer(self):
        run_replay(self.input, self.output)
        path = self.output / "events.jsonl"
        events = [json.loads(line) for line in path.read_text().splitlines()]
        events[0]["event_id"] = True
        path.write_text("".join(json.dumps(event) + "\n" for event in events))
        self.rehash("events.jsonl")
        with self.assertRaisesRegex(ContractError, "contradict"):
            verify_bundle(self.output)

    def test_different_producer_implementation_is_not_certified(self):
        run_replay(self.input, self.output)
        manifest = read_json(self.output / "manifest.json")
        manifest["producer"]["source_files"][0]["sha256"] = "0" * 64
        write_json(self.output / "manifest.json", manifest)
        with self.assertRaisesRegex(ContractError, "Producer source differs"):
            verify_bundle(self.output)

    def test_rehashed_misleading_report_fails(self):
        run_replay(self.input, self.output)
        (self.output / "report.html").write_text("<h1>Real flight succeeded</h1>")
        self.rehash("report.html")
        with self.assertRaisesRegex(ContractError, "Report contradicts"):
            verify_bundle(self.output)

    def test_manifest_traversal_duplicate_extra_and_symlink_rejected(self):
        for mutation in ("traversal", "duplicate", "extra", "symlink"):
            with self.subTest(mutation=mutation):
                output = self.root / mutation
                run_replay(self.input, output)
                manifest = read_json(output / "manifest.json")
                if mutation == "traversal":
                    manifest["files"][0]["path"] = "../input.json"
                elif mutation == "duplicate":
                    manifest["files"][1] = manifest["files"][0]
                elif mutation == "extra":
                    (output / "unknown.txt").write_text("unlisted")
                else:
                    (output / "input.json").unlink()
                    (output / "input.json").symlink_to(self.input)
                write_json(output / "manifest.json", manifest)
                with self.assertRaises(ContractError):
                    verify_bundle(output)

    def test_reject_real_data_claim_and_malformed_numbers_before_output(self):
        for field, bad in (("source_kind", "simulator"), ("number", True), ("number", float("nan")),
                           ("number", 10 ** 500), ("actions", [])):
            spec = copy.deepcopy(self.spec)
            if field == "number":
                spec["initial_state"]["x"] = bad
            else:
                spec[field] = bad
            with self.subTest(field=field, value=str(bad)[:20]), self.assertRaises(ContractError):
                validate_replay(spec)
        path = self.root / "invalid.json"
        path.write_text('{"schema_version": "bad", "schema_version": "other"}')
        with self.assertRaisesRegex(ContractError, "Duplicate"):
            run_replay(path, self.output)
        self.assertFalse(self.output.exists())

    def test_bundled_example_matches_editable_example(self):
        self.assertEqual(self.input.read_bytes(), (ROOT / "src/uav_vla_lab/data/synthetic-replay.json").read_bytes())

    def test_core_import_and_parser_do_not_import_gpu_libraries(self):
        code = ("import sys; sys.path.insert(0, " + repr(str(ROOT / "src")) + "); "
                "from uav_vla_lab.cli import parser; parser(); "
                "assert not {'torch', 'transformers', 'peft', 'airsim'} & sys.modules.keys()")
        subprocess.run([sys.executable, "-c", code], check=True, cwd=self.root, capture_output=True)


if __name__ == "__main__":
    unittest.main()
