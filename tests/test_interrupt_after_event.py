"""Synthetic event/identity fixtures, never real experiment interruption evidence."""
import argparse
import contextlib
import copy
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("interrupt_after_event", Path(__file__).resolve().parents[1] / "scripts/interrupt_after_event.py")
watcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watcher)


class InterruptionContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.identity = {"pid": 900001, "pgid": 900001, "session_id": 900001, "starttime_ticks": 123456,
            "boot_id": "synthetic-boot-id", "uid": os.getuid(), "argv": ["/fixture/python", "/fixture/evaluator.py"],
            "cwd": str(self.root), "exe": "/fixture/python", "state": "S"}
        self.supervisor = [{"event": "run.starting", "argv": self.identity["argv"], "cwd": str(self.root)},
            {"event": "process.spawned", "pid": 900001, "pgid": 900001, "root_process_alive": True,
             "process_identity": self.identity, "identity_error": None}]
        self.navigation = []
        self.event("run.start", protocol=watcher.PROTOCOL, runtime_id="synthetic-runtime", process_id=900001,
                   argv=["/fixture/evaluator.py"])
        self.event("episode.start")
        self.event("action.completed", command_event_id=101)
        self.event("action.completed", command_event_id=102)
        self.options = argparse.Namespace(supervisor_events=self.root / "supervisor.jsonl",
            experiment_events=self.root / "navigation.jsonl", output=self.root / "interruption-output",
            runtime_id="synthetic-runtime", event_type="action.completed", after_count=2,
            timeout_seconds=0.1, poll_seconds=0.001, dry_run=False)

    def event(self, kind, **fields):
        self.navigation.append({"schema_version": 1, "event_type": kind, "event_id": len(self.navigation) + 1,
            "run_id": "synthetic-run", "attempt_id": "synthetic-attempt", "map_name": "FixtureMap", "episode_id": "fixture-episode",
            "wall_time_utc": "2026-01-01T00:00:00+00:00", "host_monotonic_ns": len(self.navigation) + 1, **fields})

    def write(self):
        for path, events in ((self.options.supervisor_events, self.supervisor), (self.options.experiment_events, self.navigation)):
            path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")

    def run_helper(self, *, current=None, pidfd_alive=True, kill_error=None):
        self.write()
        with contextlib.ExitStack() as stack:
            live = stack.enter_context(patch.object(watcher, "linux_process_identity", return_value=current or self.identity))
            stack.enter_context(patch.object(watcher.os, "pidfd_open", create=True, return_value=999999))
            stack.enter_context(patch.object(watcher.os, "close"))
            stack.enter_context(patch.object(watcher, "pidfd_alive", return_value=pidfd_alive))
            kill = stack.enter_context(patch.object(watcher.os, "killpg", side_effect=kill_error))
            report = watcher.interrupt(self.options)
            return report, kill, live

    def test_exact_observed_action_count_requests_one_owned_sigint_and_preserves_receipt(self):
        report, kill, live = self.run_helper()
        self.assertEqual(report["status"], "sigint_requested")
        kill.assert_called_once_with(900001, signal.SIGINT)
        self.assertGreaterEqual(live.call_count, 4)
        self.assertEqual(report["signal_count"], 1)
        self.assertEqual(report["trigger"]["event_id"], 4)
        self.assertEqual(report["trigger"]["run_id"], "synthetic-run")
        self.assertEqual(report["observed_trigger_count"], 2)
        self.assertIn("before signal delivery", report["timing_scope"])
        self.assertIn("not one atomic", report["identity_scope"])
        hashes = json.loads((self.options.output / "checksums.json").read_text())
        for name, expected in hashes.items():
            self.assertEqual(watcher.hashlib.sha256((self.options.output / name).read_bytes()).hexdigest(), expected)

    def test_late_watcher_does_not_interrupt_after_more_than_requested_events(self):
        self.event("action.completed", command_event_id=103)
        report, kill, _ = self.run_helper()
        self.assertEqual(report["status"], "trigger_count_already_exceeded")
        self.assertEqual(report["observed_trigger_count"], 3)
        kill.assert_not_called()

    def test_terminal_navigation_or_supervisor_event_prevents_signal(self):
        for kind in ("episode.completed", "episode.interrupted", "run.end", "supervisor_finished"):
            with self.subTest(kind=kind):
                self.options.output = self.root / kind
                if kind == "supervisor_finished":
                    self.supervisor.append({"event": "process.finished", "child_returncode": 0})
                else:
                    self.event(kind)
                report, kill, _ = self.run_helper()
                self.assertEqual(report["status"], "already_ended_or_stopping")
                kill.assert_not_called()
                if kind == "supervisor_finished":
                    self.supervisor.pop()
                else:
                    self.navigation.pop()

    def test_reused_pid_changed_command_or_group_is_rejected_without_signal(self):
        for field, changed in (("starttime_ticks", 123457), ("boot_id", "different-boot"),
                               ("pgid", 900002), ("session_id", 900002), ("argv", ["unrelated-command"]),
                               ("exe", "/unrelated/python"), ("cwd", "/unrelated")):
            with self.subTest(field=field):
                self.options.output = self.root / field
                current = {**self.identity, field: changed}
                report, kill, _ = self.run_helper(current=current)
                self.assertEqual(report["status"], "identity_or_evidence_rejected")
                kill.assert_not_called()

    def test_missing_spawn_identity_and_unbound_experiment_process_fail_closed(self):
        self.supervisor[-1]["process_identity"] = None
        report, kill, _ = self.run_helper()
        self.assertEqual(report["status"], "identity_or_evidence_rejected")
        kill.assert_not_called()
        self.supervisor[-1]["process_identity"] = self.identity
        self.navigation[0]["process_id"] = 900002
        self.options.output = self.root / "unbound-pid"
        report, kill, _ = self.run_helper()
        self.assertIn("supervised evaluator PID", report["error"]["message"])
        kill.assert_not_called()

    def test_pidfd_exit_guard_and_dry_run_never_signal(self):
        report, kill, _ = self.run_helper(pidfd_alive=False)
        self.assertEqual(report["status"], "identity_or_evidence_rejected")
        kill.assert_not_called()
        self.options.output = self.root / "dry-run"
        self.options.dry_run = True
        report, kill, _ = self.run_helper()
        self.assertEqual(report["status"], "dry_run_validated_no_signal")
        self.assertEqual(report["signal_count"], 0)
        kill.assert_not_called()

    def test_signal_error_is_not_retried(self):
        report, kill, _ = self.run_helper(kill_error=ProcessLookupError("synthetic disappearance"))
        self.assertEqual(report["status"], "signal_request_failed")
        self.assertEqual(report["signal_count"], 1)
        self.assertNotEqual(report["returncode"], 0)
        kill.assert_called_once()

    def test_new_terminal_or_changed_identity_at_final_gate_prevents_signal(self):
        for change in ("terminal", "identity"):
            with self.subTest(change=change):
                self.options.output = self.root / ("final-" + change)
                self.write()
                calls = 0

                def live(pid):
                    nonlocal calls
                    calls += 1
                    if change == "terminal" and calls == 3:
                        event = {**self.navigation[-1], "event_id": 5, "event_type": "episode.completed"}
                        with self.options.experiment_events.open("a") as handle:
                            handle.write(json.dumps(event) + "\n")
                    return {**self.identity, "starttime_ticks": 999} if change == "identity" and calls == 4 else self.identity

                with patch.object(watcher, "linux_process_identity", side_effect=live), \
                        patch.object(watcher.os, "pidfd_open", create=True, return_value=999999), \
                        patch.object(watcher.os, "close"), patch.object(watcher, "pidfd_alive", return_value=True), \
                        patch.object(watcher.os, "killpg") as kill:
                    report = watcher.interrupt(self.options)
                kill.assert_not_called()
                self.assertEqual(report["status"], "already_ended_or_stopping" if change == "terminal" else "identity_or_evidence_rejected")

    def test_missing_stream_times_out_without_signal_or_invented_events(self):
        self.supervisor, self.navigation = [], []
        report, kill, _ = self.run_helper()
        self.assertEqual(report["status"], "timed_out_without_signal")
        self.assertEqual(report["returncode"], 124)
        self.assertEqual(report["observed_trigger_count"], 0)
        self.assertIsNone(report["recorded_navigation_run_start"])
        kill.assert_not_called()

    def test_mixed_runtime_runid_event_sequence_or_episode_mapping_is_rejected(self):
        alterations = [(0, "runtime_id", "different-runtime"), (3, "run_id", "different-run"),
                       (3, "event_id", 7), (3, "attempt_id", "different-attempt")]
        original = copy.deepcopy(self.navigation)
        for index, field, value in alterations:
            with self.subTest(field=field):
                self.navigation = copy.deepcopy(original)
                self.navigation[index][field] = value
                self.options.output = self.root / field
                report, kill, _ = self.run_helper()
                self.assertEqual(report["status"], "identity_or_evidence_rejected")
                kill.assert_not_called()

    def test_file_tailer_waits_for_complete_json_and_rejects_replacement(self):
        path = self.root / "tail.jsonl"
        path.write_bytes(b'{"event":"first"}\n{"eve')
        tail = watcher.EventTail(path)
        self.addCleanup(tail.close)
        self.assertEqual(tail.read(), [{"event": "first"}])
        self.assertGreater(tail.snapshot()["unfinished_line_bytes"], 0)
        with path.open("ab") as handle:
            handle.write(b'nt":"second"}\n')
        self.assertEqual(tail.read(), [{"event": "second"}])
        replacement = self.root / "replacement"
        replacement.write_text('{"event":"replacement"}\n')
        replacement.replace(path)
        with self.assertRaisesRegex(watcher.RefuseInterrupt, "replaced or truncated"):
            tail.read()

    def test_incomplete_terminal_line_withholds_signal_until_timeout(self):
        self.write()
        with self.options.experiment_events.open("a") as handle:
            handle.write('{"event_type":"episode.completed"')
        with patch.object(watcher, "linux_process_identity", return_value=self.identity), \
                patch.object(watcher.os, "pidfd_open", create=True, return_value=999999), \
                patch.object(watcher.os, "close"), patch.object(watcher, "pidfd_alive", return_value=True), \
                patch.object(watcher.os, "killpg") as kill:
            report = watcher.interrupt(self.options)
        self.assertEqual(report["status"], "timed_out_without_signal")
        self.assertGreater(report["navigation_evidence_prefix"]["unfinished_line_bytes"], 0)
        kill.assert_not_called()

    def test_output_directory_cannot_be_reused(self):
        self.run_helper()
        with self.assertRaises(FileExistsError):
            self.run_helper()


class LinuxIdentityTests(unittest.TestCase):
    def test_proc_snapshot_parses_starttime_and_rejects_changed_identity(self):
        pid = 900001

        def stat(start):
            fields = ["S", "1", str(pid), str(pid)] + ["0"] * 15 + [str(start)]
            return f"{pid} (synthetic ) name) " + " ".join(fields)

        for changed in (False, True):
            values = iter([stat(123), stat(124 if changed else 123)])

            def text(path, *args, **kwargs):
                if str(path).endswith("/stat"):
                    return next(values)
                if str(path).endswith("/status"):
                    return f"Uid:\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\n"
                return "synthetic-boot\n"

            with self.subTest(changed=changed), patch.object(watcher._SUPERVISOR.sys, "platform", "linux"), \
                    patch.object(Path, "read_text", text), patch.object(Path, "read_bytes", return_value=b"/python\0/script.py\0"), \
                    patch.object(watcher._SUPERVISOR.os, "readlink", side_effect=lambda path: "/fixture" if str(path).endswith("/cwd") else "/python"):
                if changed:
                    with self.assertRaisesRegex(RuntimeError, "changed during"):
                        watcher._SUPERVISOR.linux_process_identity(pid)
                else:
                    identity = watcher._SUPERVISOR.linux_process_identity(pid)
                    self.assertEqual(identity["starttime_ticks"], 123)
                    self.assertEqual(identity["argv"], ["/python", "/script.py"])
                    self.assertEqual(identity["session_id"], pid)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Real /proc identity requires Linux")
    def test_real_linux_identity_matches_spawned_local_process(self):
        command = [sys.executable, "-c", "import time; time.sleep(5)"]
        child = subprocess.Popen(command, start_new_session=True)
        try:
            identity = watcher.linux_process_identity(child.pid)
            self.assertEqual(identity["pid"], child.pid)
            self.assertEqual(identity["pgid"], child.pid)
            self.assertEqual(identity["session_id"], child.pid)
            self.assertEqual(identity["argv"], command)
            self.assertGreater(identity["starttime_ticks"], 0)
        finally:
            child.terminate()
            child.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
