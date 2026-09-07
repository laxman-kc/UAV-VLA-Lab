"""Real local subprocess lifecycle tests; no simulator/model experiment claims."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/supervise_run.py"


@unittest.skipUnless(os.name == "posix", "Supervisor uses POSIX process groups")
class SupervisorTests(unittest.TestCase):
    def arguments(self, root, code, timeout=3, grace=0.1):
        return [sys.executable, str(SCRIPT), "--cwd", str(root), "--output", str(root / "attempt"),
                "--timeout-seconds", str(timeout), "--grace-seconds", str(grace), "--",
                sys.executable, "-c", code]

    def test_success_preserves_exact_streams_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self.arguments(root, "import sys;print('actual stdout');print('actual stderr',file=sys.stderr)")
            result = subprocess.run(args, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((root / "attempt/report.json").read_text())
            self.assertEqual(report["status"], "exited_successfully")
            self.assertEqual(report["child_returncode"], 0)
            self.assertIn("process_identity_at_spawn", report)
            self.assertIn("process_identity_error", report)
            spawned = next(json.loads(line) for line in (root / "attempt/events.jsonl").read_text().splitlines()
                           if json.loads(line).get("event") == "process.spawned")
            self.assertEqual(spawned["process_identity"], report["process_identity_at_spawn"])
            if not sys.platform.startswith("linux"):
                self.assertIsNone(spawned["process_identity"])
                self.assertIn("unavailable", spawned["identity_error"])
            self.assertEqual((root / "attempt/stdout.log").read_text(), "actual stdout\n")
            self.assertEqual((root / "attempt/stderr.log").read_text(), "actual stderr\n")
            original = (root / "attempt/report.json").read_bytes()
            duplicate = subprocess.run(args, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertEqual((root / "attempt/report.json").read_bytes(), original)

    def test_child_failure_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = subprocess.run(self.arguments(root, "raise SystemExit(7)"), capture_output=True, timeout=10)
            report = json.loads((root / "attempt/report.json").read_text())
            self.assertEqual(result.returncode, 7)
            self.assertEqual(report["status"], "exited_with_error")
            self.assertEqual(report["termination_reason"], "natural_exit")

    def test_timeout_terminates_owned_group_and_preserves_outside_process(self):
        outside = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], start_new_session=True)
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                result = subprocess.run(self.arguments(root, "import time;print('real child',flush=True);time.sleep(30)", timeout=0.25),
                                        capture_output=True, timeout=10)
                report = json.loads((root / "attempt/report.json").read_text())
                self.assertEqual(result.returncode, 124)
                self.assertEqual(report["status"], "timed_out")
                self.assertEqual(report["signals_sent"][0]["signal"], "SIGTERM")
                self.assertFalse(report["root_process_alive_at_end"])
                self.assertIsNone(outside.poll())
                self.assertTrue(all(event["process_group_id"] == report["process_pid"] for event in report["signals_sent"]))
        finally:
            outside.terminate()
            outside.wait(timeout=5)

    def test_ignored_term_escalates_to_kill(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print('ready',flush=True);time.sleep(30)"
            result = subprocess.run(self.arguments(root, code, timeout=0.4), capture_output=True, timeout=10)
            report = json.loads((root / "attempt/report.json").read_text())
            self.assertEqual(result.returncode, 124)
            self.assertEqual([entry["signal"] for entry in report["signals_sent"]], ["SIGTERM", "SIGKILL"])
            self.assertEqual(report["child_returncode"], -signal.SIGKILL)

    def test_interrupt_cleanup_and_exit_status(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=signum), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                child = subprocess.Popen(self.arguments(root, "import time;print('ready',flush=True);time.sleep(30)"),
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 5
                    stdout_path = root / "attempt/stdout.log"
                    while time.monotonic() < deadline:
                        if stdout_path.exists() and "ready" in stdout_path.read_text():
                            break
                        time.sleep(0.02)
                    else:
                        self.fail("Child did not start within test bound")
                    child.send_signal(signum)
                    stdout, stderr = child.communicate(timeout=10)
                    report = json.loads((root / "attempt/report.json").read_text())
                    self.assertEqual(child.returncode, 128 + signum, stderr)
                    self.assertEqual(report["status"], "interrupted")
                    self.assertEqual(report["received_signal"], signal.Signals(signum).name)
                    self.assertFalse(report["root_process_alive_at_end"])
                finally:
                    if child.poll() is None:
                        child.send_signal(signal.SIGTERM)
                        child.communicate(timeout=10)

    def test_missing_command_is_an_explicit_failed_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self.arguments(root, "unused")
            args[-3:] = [str(root / "missing-command")]
            result = subprocess.run(args, capture_output=True, timeout=10)
            report = json.loads((root / "attempt/report.json").read_text())
            self.assertEqual(result.returncode, 127)
            self.assertEqual(report["status"], "supervisor_error")
            self.assertEqual(report["error"]["type"], "FileNotFoundError")
            self.assertIsNone(report["process_pid"])


if __name__ == "__main__":
    unittest.main()
