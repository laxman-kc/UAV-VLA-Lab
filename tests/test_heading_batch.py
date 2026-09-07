import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class HeadingBatchTests(unittest.TestCase):
    def invoke(self, root, returncode):
        scripts = root / "scripts"
        scripts.mkdir()
        shutil.copyfile(Path(__file__).parents[1] / "scripts/run_heading_batch.py", scripts / "run_heading_batch.py")
        (scripts / "collect_heading_corrections.py").write_text("# Synthetic collector identity only\n")
        (scripts / "run_simulation_session.py").write_text(
            "import json,pathlib,sys\n"
            "out=pathlib.Path(sys.argv[sys.argv.index('--output')+1]);out.mkdir()\n"
            "(out/'report.json').write_text(json.dumps({'synthetic':True}))\n"
            f"sys.exit({returncode})\n")
        source = root / "train.json"
        split = root / "splits.json"
        source.write_text("[]\n")
        split.write_text("{}\n")
        plan = root / "plan.json"
        plan.write_text(json.dumps({"schema_version": "vla.heading-correction-plan.v1",
            "source_split_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "split_manifest_sha256": hashlib.sha256(split.read_bytes()).hexdigest(),
            "samples": [{"phase": "P09" if i < 5 else "P11", "sample_id": f"synthetic-{i}"} for i in range(25)]}))
        command = [sys.executable, str(scripts / "run_heading_batch.py"), "--phase", "P09",
                   "--plan", str(plan), "--source-split", str(source), "--split-manifest", str(split),
                   "--upstream", str(root), "--dataset-root", str(root), "--env-root", str(root),
                   "--output", str(root / "result")]
        result = subprocess.run(command, capture_output=True, text=True)
        return result, json.loads((root / "result/batch.json").read_text()), command

    def test_failed_child_preserves_unstarted_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, report, _ = self.invoke(root, 7)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(report["status"], "partial")
            self.assertEqual([a["sample_index"] for a in report["attempts"]], [0])
            self.assertEqual(report["attempts"][0]["returncode"], 7)
            self.assertEqual(report["unstarted_indices"], [1, 2, 3, 4])
            self.assertFalse((root / "result/sample-01-session").exists())

    def test_successful_children_remain_separate_and_output_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, report, command = self.invoke(root, 0)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(report["status"], "sessions_completed")
            self.assertEqual([a["sample_index"] for a in report["attempts"]], list(range(5)))
            self.assertEqual(len({a["session_directory"] for a in report["attempts"]}), 5)
            self.assertEqual(report["unstarted_indices"], [])
            before = (root / "result/batch.json").read_bytes()
            duplicate = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertEqual((root / "result/batch.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
