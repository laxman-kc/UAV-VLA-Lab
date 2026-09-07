"""Synthetic manager/process fixtures only; never simulator readiness evidence."""
import importlib.util
import errno
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import run_simulation_session as session


class SessionTests(unittest.TestCase):
    def cooldown(self, port, seconds, root, interval=0.05):
        events = []
        evidence = SimpleNamespace(emit=lambda event, **data: events.append({"event": event, **data}))
        with patch.object(session, "SCENE_PORT_COUNT", 0), patch.object(os, "killpg") as kill:
            result = session.preflight_with_cooldown(port, shutil.which("lsof"), seconds, root, evidence, interval)
        kill.assert_not_called()
        return result, events

    def test_preflight_rejects_occupied_port_without_signaling_it(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            with patch.object(session, "SCENE_PORT_COUNT", 0), patch.object(os, "killpg") as kill:
                result = session.port_preflight(port)
            self.assertFalse(result["passed"])
            kill.assert_not_called()
            self.assertEqual(listener.getsockname()[1], port)

    @unittest.skipUnless(shutil.which("lsof"), "Cooldown listener inspection requires lsof")
    def test_live_reusable_listener_aborts_without_cooldown_or_signals(self):
        with tempfile.TemporaryDirectory() as directory, socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            result, events = self.cooldown(port, 5, Path(directory))
            self.assertFalse(result["passed"])
            self.assertEqual(result["status"], "live_listener_observed")
            self.assertEqual(result["retry_count"], 0)
            self.assertIn(os.getpid(), result["listener_inspection"]["listener_pids"])
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                accepted, _ = listener.accept()
                accepted.close()
            self.assertEqual(len(events), 1)

    @unittest.skipUnless(shutil.which("lsof"), "Cooldown listener inspection requires lsof")
    def test_conflicting_bound_socket_is_not_accepted_until_it_closes(self):
        with tempfile.TemporaryDirectory() as directory, socket.socket() as bound:
            bound.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            bound.bind(("127.0.0.1", 0))
            port = bound.getsockname()[1]
            # No listen(): a reusable bind must not be mistaken for a free port.
            result, _ = self.cooldown(port, 0, Path(directory))
            self.assertFalse(result["passed"])
            self.assertFalse(result["checks"][0]["available_to_bind"])
        with tempfile.TemporaryDirectory() as directory, socket.socket() as bound:
            bound.bind(("127.0.0.1", 0))
            port = bound.getsockname()[1]
            timer = threading.Timer(0.4, bound.close)
            timer.start()
            try:
                result, events = self.cooldown(port, 3, Path(directory))
            finally:
                timer.join()
            self.assertTrue(result["passed"])
            self.assertGreaterEqual(result["retry_count"], 1)
            self.assertFalse(json.loads((Path(directory) / result["attempts"][0]["path"]).read_text())["passed"])
            for attempt in result["attempts"]:
                self.assertEqual(session.sha(Path(directory) / attempt["path"]), attempt["sha256"])
            self.assertTrue(events[-1]["passed"])

    @unittest.skipUnless(shutil.which("lsof") and sys.platform in {"linux", "darwin"}, "Real TIME_WAIT fixture requires Linux/macOS and lsof")
    def test_real_time_wait_allows_reuse_but_strict_preflight_stays_bounded(self):
        with socket.socket() as listener, socket.socket() as client:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            client.connect(("127.0.0.1", port))
            accepted, _ = listener.accept()
            accepted.shutdown(socket.SHUT_WR)  # Server actively closes and owns TIME_WAIT.
            self.assertEqual(client.recv(1), b"")
            accepted.close()
        def is_time_wait():
            if sys.platform == "linux":
                return any(row.split()[1].endswith(f":{port:04X}") and row.split()[3] == "06"
                           for row in Path("/proc/net/tcp").read_text().splitlines()[1:])
            text = subprocess.check_output(["netstat", "-an", "-p", "tcp"], text=True, timeout=2)
            return any(f"127.0.0.1.{port}" in row and "TIME_WAIT" in row for row in text.splitlines())
        deadline = time.monotonic() + 1
        while not is_time_wait() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(is_time_wait(), "Fixture did not actually establish server-side TIME_WAIT")
        with socket.socket() as strict:
            with self.assertRaises(OSError) as error:
                strict.bind(("127.0.0.1", port))
            self.assertEqual(error.exception.errno, errno.EADDRINUSE)
        with socket.socket() as reusable:
            reusable.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            reusable.bind(("127.0.0.1", port))
            reusable.listen()  # Matches Unix Tornado bind/listen behavior without changing production policy.
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self.cooldown(port, 0.3, Path(directory), interval=0.3)
            self.assertFalse(result["passed"])
            self.assertEqual(result["status"], "cooldown_expired")
            self.assertTrue(result["listener_inspection"]["succeeded"])
            self.assertEqual(result["listener_inspection"]["listener_pids"], [])
            self.assertLess(result["elapsed_seconds"], 2)
            self.assertTrue((Path(directory) / "port-preflight.json").is_file())

    def test_descendant_snapshot_records_escaped_group_and_rejects_reused_pid(self):
        tracker = session.OwnedProcesses(100)
        rows = [{"pid": 100, "ppid": 1, "pgid": 100, "state": "S", "started": "first"},
                {"pid": 101, "ppid": 100, "pgid": 555, "state": "S", "started": "child"},
                {"pid": 900, "ppid": 1, "pgid": 900, "state": "S", "started": "other"}]
        with patch.object(session, "process_table", return_value=rows):
            first = tracker.snapshot()
        self.assertEqual([p["pid"] for p in first["escaped_observed_descendants"]], [101])
        with patch.object(session, "process_table", return_value=[{**rows[1], "ppid": 1, "started": "replacement"}]):
            self.assertEqual(tracker.snapshot()["processes"], [])

    def test_cleanup_escalates_only_owned_manager_group_and_reports_remaining_visibility(self):
        manager = SimpleNamespace(pid=12345, poll=lambda: 0)
        owned = SimpleNamespace(snapshot=lambda: {"processes": [{"pid": 12346}], "escaped_observed_descendants": []})
        evidence = SimpleNamespace(emit=lambda *args, **kwargs: None)
        with patch.object(session.supervise_run, "group_alive", return_value=True), patch.object(os, "killpg") as kill:
            result = session.cleanup_manager(manager, owned, evidence, 0, 0)
        self.assertEqual(kill.call_args_list, [unittest.mock.call(12345, signal.SIGTERM), unittest.mock.call(12345, signal.SIGKILL)])
        self.assertFalse(result["complete"])

    @unittest.skipUnless(shutil.which("lsof"), "Listener ownership check requires lsof")
    def test_real_synthetic_manager_preserves_command_failure_and_cleans_owned_group(self):
        with tempfile.TemporaryDirectory(prefix="vla-session-fixture-", dir="/private/tmp" if Path("/private/tmp").is_dir() else None) as directory:
            root = Path(directory)
            upstream, envs = root / "upstream", root / "envs"
            server = upstream / session.SERVER_RELATIVE
            server.parent.mkdir(parents=True)
            envs.mkdir()
            server.write_text("import argparse,socket,time\np=argparse.ArgumentParser()\np.add_argument('--gpus')\np.add_argument('--port',type=int)\np.add_argument('--root_path')\na=p.parse_args()\ns=socket.socket()\ns.bind(('127.0.0.1',a.port))\ns.listen()\nprint('SYNTHETIC LISTENER ONLY',flush=True)\nwhile True:\n c,_=s.accept()\n c.close()\n")
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            options = SimpleNamespace(upstream=upstream, env_root=envs, cwd=root, output=root / "evidence",
                manager_python=sys.executable, manager_port=port, gpus="0", readiness_timeout_seconds=5,
                port_cooldown_seconds=0,
                command_timeout_seconds=5, command_grace_seconds=0.2, manager_grace_seconds=0.2,
                kill_wait_seconds=0.2, poll_gpu=False, command=[sys.executable, "-c", "import sys; print('fixture command'); sys.exit(7)"])
            with patch.object(session, "SCENE_PORT_COUNT", 0), patch.object(session, "SERVER_SHA256", session.sha(server)):
                result = session.run(options)
            self.assertEqual(result, 7)
            report = json.loads((options.output / "report.json").read_text())
            self.assertEqual(report["command_child_returncode"], 7)
            self.assertEqual(report["command_supervisor_returncode"], 7)
            self.assertTrue(report["readiness"]["tcp_accepted"])
            self.assertTrue(report["cleanup"]["complete"])
            self.assertFalse(session.supervise_run.group_alive(report["manager_pgid"]))
            self.assertIn("fixture command", (options.output / "command/stdout.log").read_text())


if __name__ == "__main__":
    unittest.main()
