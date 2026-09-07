#!/usr/bin/env python3
"""Own one pinned TravelUAV scene manager around a bounded supervised command.

Only the manager process group created here is signaled by this wrapper. The
existing command supervisor owns a separate workload group. Port availability is
a preflight snapshot, not a reservation; the upstream manager itself is unchanged.
"""
from __future__ import annotations

import argparse
import errno
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import supervise_run


SERVER_RELATIVE = "airsim_plugin/AirVLNSimulatorServerTool.py"
SERVER_SHA256 = "bcc5d134315ed656a01d3b87fe2ad5729e0eb905b77e63a7969957fbf3e9199f"
SCENE_PORT_COUNT = 1000


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def sha(path):
    return supervise_run.file_record(Path(path))["sha256"]


def port_preflight(manager_port):
    checks = []
    for port in range(manager_port, manager_port + SCENE_PORT_COUNT + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
                checks.append({"port": port, "available_to_bind": True})
            except OSError as exc:
                checks.append({"port": port, "available_to_bind": False, "errno": exc.errno, "error": str(exc)})
    return {"checked_at_utc": supervise_run.utc_now(), "address": "127.0.0.1", "checks": checks,
            "passed": all(item["available_to_bind"] for item in checks),
            "scope": "Sequential bind checks; sockets are closed immediately. This is not a port reservation."}


def preflight_with_cooldown(manager_port, lsof, cooldown_seconds, root, evidence, retry_interval=1.0):
    """Keep strict binds; wait only for an unclassified EADDRINUSE to clear.

    SO_REUSEADDR can coexist with another bound non-listening socket, so its
    successful bind is not enough evidence that this dedicated range is free.
    Empty lsof output does not prove TIME_WAIT; persistent conflicts still fail.
    """
    if not math.isfinite(cooldown_seconds) or not 0 <= cooldown_seconds <= 60:
        raise ValueError("Port cooldown must be between 0 and 60 seconds")
    if not math.isfinite(retry_interval) or retry_interval <= 0:
        raise ValueError("Port retry interval must be positive")
    started = time.monotonic()
    deadline = started + cooldown_seconds
    attempts = []
    directory = root / "port-preflight-attempts"
    directory.mkdir()
    while True:
        check = port_preflight(manager_port)
        # Range-wide observation also detects listeners bound to other addresses.
        argv = [lsof, "-nP", f"-iTCP:{manager_port}-{manager_port + SCENE_PORT_COUNT}",
                "-sTCP:LISTEN", "-Fp"]
        remaining = deadline - time.monotonic()
        timeout = min(2.0, max(0.001, remaining)) if cooldown_seconds else 2.0
        inspection = {"argv": argv, "timeout_seconds": timeout, "listener_pids": [], "succeeded": False}
        try:
            result = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
            inspection.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
            lines = result.stdout.splitlines()
            pids = {int(line[1:]) for line in lines if re.fullmatch(r"p[0-9]+", line)}
            # lsof includes file-descriptor records even when only -Fp is requested.
            if (result.returncode in (0, 1) and not result.stderr.strip() and
                    all(re.fullmatch(r"[pf][0-9]+", line) for line in lines) and
                    ((result.returncode == 0) == bool(pids)) and (not lines or bool(pids))):
                inspection.update(succeeded=True, listener_pids=sorted(pids))
        except (OSError, subprocess.TimeoutExpired) as exc:
            inspection["error"] = str(exc)
        check["listener_inspection"] = inspection
        failures = [item for item in check["checks"] if not item["available_to_bind"]]
        if not inspection["succeeded"]:
            status = "listener_inspection_failed"
        elif inspection["listener_pids"]:
            status = "live_listener_observed"
        elif not failures:
            status = "available"
        elif any(item.get("errno") != errno.EADDRINUSE for item in failures):
            status = "non_retryable_bind_error"
        elif time.monotonic() >= deadline:
            status = "cooldown_expired"
        else:
            status = "address_in_use_without_observed_listener"
        check.update(passed=status == "available", status=status, attempt=len(attempts) + 1,
                     elapsed_seconds=time.monotonic() - started)
        relative = f"port-preflight-attempts/{len(attempts) + 1:04d}.json"
        write_json(root / relative, check)
        attempts.append({"attempt": check["attempt"], "status": status, "path": relative,
                         "sha256": sha(root / relative), "elapsed_seconds": check["elapsed_seconds"]})
        summary = {**check, "cooldown_seconds": cooldown_seconds, "retry_interval_seconds": retry_interval,
                   "attempts": attempts, "retry_count": len(attempts) - 1,
                   "policy": "Strict binds without SO_REUSEADDR; observed listeners and inspection failures abort. Only EADDRINUSE without an observed listener is retried, not classified as TIME_WAIT.",
                   "timing_limit": "Cooldown bounds retries; one in-progress bind scan and bounded listener inspection can add overhead."}
        write_json(root / "port-preflight.json", summary)
        evidence.emit("ports.preflight_attempt", **attempts[-1], passed=check["passed"],
                      failed_ports=[item["port"] for item in failures], listener_pids=inspection["listener_pids"])
        if status != "address_in_use_without_observed_listener":
            return summary
        time.sleep(min(retry_interval, max(0, deadline - time.monotonic())))
        if time.monotonic() >= deadline:
            summary.update(status="cooldown_expired", passed=False, elapsed_seconds=time.monotonic() - started)
            write_json(root / "port-preflight.json", summary)
            evidence.emit("ports.preflight_finished", status=summary["status"], passed=False,
                          retry_count=summary["retry_count"], elapsed_seconds=summary["elapsed_seconds"])
            return summary


def process_table():
    result = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid=,stat=,lstart="], text=True,
                            capture_output=True, timeout=2, check=False)
    if result.returncode:
        raise RuntimeError(f"Process inventory failed: {result.stderr.strip()}")
    rows = []
    for line in result.stdout.splitlines():
        fields = line.split(None, 4)
        if len(fields) != 5:
            raise RuntimeError("Process inventory returned an unrecognized row")
        rows.append({"pid": int(fields[0]), "ppid": int(fields[1]), "pgid": int(fields[2]),
                     "state": fields[3], "started": fields[4]})
    return rows


def listener_pids(port, lsof):
    result = subprocess.run([lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"],
                            text=True, capture_output=True, timeout=2, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Listener ownership check failed: {result.stderr.strip()}")
    return sorted({int(line[1:]) for line in result.stdout.splitlines() if re.fullmatch(r"p[0-9]+", line)})


class Evidence:
    def __init__(self, root):
        self.stream = (root / "lifecycle.jsonl").open("x", buffering=1)
        self.lock = threading.Lock()

    def emit(self, event, **values):
        with self.lock:
            self.stream.write(json.dumps({"event": event, "utc": supervise_run.utc_now(),
                                          "monotonic_ns": time.monotonic_ns(), **values}, allow_nan=False) + "\n")


class OwnedProcesses:
    """Record manager-group members and observed descendants, including escapes."""
    def __init__(self, manager_pid):
        self.manager_pid = manager_pid
        self.identities = {}

    def snapshot(self):
        rows = process_table()
        by_pid = {row["pid"]: row for row in rows}
        owned = {row["pid"] for row in rows if row["pgid"] == self.manager_pid}
        owned.update(pid for pid, started in self.identities.items()
                     if pid in by_pid and by_pid[pid]["started"] == started)
        while True:
            children = {row["pid"] for row in rows if row["ppid"] in owned}
            if children <= owned:
                break
            owned.update(children)
        selected = [by_pid[pid] for pid in sorted(owned) if pid in by_pid]
        for row in selected:
            self.identities[row["pid"]] = row["started"]
        return {"observed_at_utc": supervise_run.utc_now(), "manager_pgid": self.manager_pid,
                "processes": selected,
                "escaped_observed_descendants": [row for row in selected if row["pgid"] != self.manager_pid],
                "coverage": "Sampled process ancestry and group membership; a process escaping between samples may be missed."}


def settings_inventory(upstream, manager_port):
    rows = {}
    for port in range(manager_port + 1, manager_port + SCENE_PORT_COUNT + 1):
        path = upstream / "airsim_plugin/settings" / str(port) / "settings.json"
        if path.is_file():
            rows[str(port)] = {"path": str(path), "sha256": sha(path), "mtime_ns": path.stat().st_mtime_ns}
    return rows


def cleanup_manager(manager, owned, evidence, grace_seconds, kill_wait_seconds):
    result = {"signals": [], "errors": []}

    def send(signum):
        try:
            os.killpg(manager.pid, signum)
            status = "sent"
        except ProcessLookupError:
            status = "already_absent"
        except OSError as exc:
            status = "error"
            result["errors"].append(str(exc))
        event = {"pgid": manager.pid, "signal": signal.Signals(signum).name, "status": status}
        result["signals"].append(event)
        evidence.emit("manager.signal", **event)

    # Reap the group leader before testing killpg(0), so its zombie is not
    # mistaken for a live manager. Other visible zombies remain a recorded limit.
    manager.poll()
    if supervise_run.group_alive(manager.pid):
        send(signal.SIGTERM)
        deadline = time.monotonic() + grace_seconds
        while time.monotonic() < deadline and supervise_run.group_alive(manager.pid):
            manager.poll()
            time.sleep(0.05)
        manager.poll()
        if supervise_run.group_alive(manager.pid):
            send(signal.SIGKILL)
            deadline = time.monotonic() + kill_wait_seconds
            while time.monotonic() < deadline and supervise_run.group_alive(manager.pid):
                manager.poll()
                time.sleep(0.05)
    result["manager_returncode"] = manager.poll()
    result["manager_group_visible"] = supervise_run.group_alive(manager.pid)
    try:
        result["final_process_evidence"] = owned.snapshot()
        result["inspection_succeeded"] = True
    except Exception as exc:
        result["inspection_succeeded"] = False
        result["errors"].append(str(exc))
    result["complete"] = (not result["manager_group_visible"] and result["manager_returncode"] is not None and
                          result["inspection_succeeded"] and not result["final_process_evidence"]["processes"] and not result["errors"])
    result["scope"] = "Only this session's manager PGID was signaled. Escaped descendants are recorded, not killed by PID or port."
    evidence.emit("manager.cleanup", **result)
    return result


def run(options):
    root = options.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    evidence = Evidence(root)
    report = {"schema_version": "vla.simulation-session.v1", "started_at_utc": supervise_run.utc_now(),
              "status": "starting", "command_returncode": None, "session_returncode": 1,
              "ownership": "New manager process group; existing supervisor owns a separate command process group",
              "limitations": ["Port preflight is a snapshot; do not run another service in this dedicated range during the session.",
                  "Pinned upstream scene RPCs retain their own port-based cleanup. This wrapper never calls pkill, port-kill helpers or close_scenes.",
                  "Process evidence is sampled; unobserved descendants that escape their group cannot be certified absent.",
                  "The upstream manager discards native scene stdout; manager and command output are retained here."]}
    manager = owned = sampler = None
    stop_sampling = threading.Event()
    received = {"signal": None}
    previous = {}
    exit_code = 1
    before_settings = {}

    def interrupted(signum, frame):
        received["signal"] = signum
        raise SystemExit(128 + signum)

    def sample():
        while not stop_sampling.is_set():
            try:
                evidence.emit("manager.process_sample", **owned.snapshot())
            except Exception as exc:
                evidence.emit("manager.process_sample_failed", error=str(exc))
            stop_sampling.wait(1.0)

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, interrupted)
        upstream = options.upstream.resolve()
        server = upstream / SERVER_RELATIVE
        if sha(server) != SERVER_SHA256:
            raise ValueError("Manager source differs from the pinned inspected source")
        for path in (upstream, options.env_root.resolve()):
            if not re.fullmatch(r"[A-Za-z0-9_./-]+", str(path)):
                raise ValueError("Upstream manager shell interpolation requires paths without whitespace or shell metacharacters")
        lsof = shutil.which("lsof")
        if not lsof:
            raise RuntimeError("lsof is required to verify the manager actually owns its ready TCP listener")
        manager_command = [str(options.manager_python), "-u", str(server), "--gpus", options.gpus,
                           "--port", str(options.manager_port), "--root_path", str(options.env_root.resolve())]
        report["config"] = {"manager_argv": manager_command, "command_argv": options.command, "cwd": str(options.cwd.resolve()),
                            "manager_port": options.manager_port, "scene_ports": [options.manager_port + 1, options.manager_port + SCENE_PORT_COUNT],
                            "port_cooldown_seconds": options.port_cooldown_seconds,
                            "readiness_timeout_seconds": options.readiness_timeout_seconds,
                            "command_timeout_seconds": options.command_timeout_seconds, "command_grace_seconds": options.command_grace_seconds,
                            "manager_grace_seconds": options.manager_grace_seconds, "kill_wait_seconds": options.kill_wait_seconds,
                            "command_environment_override": {"VLA_LAB_SCENE_MANAGER_EXCLUSIVE": "1"}}
        report["code"] = {"runner": supervise_run.file_record(Path(__file__).resolve()),
                          "supervisor": supervise_run.file_record(Path(supervise_run.__file__).resolve()),
                          "manager": supervise_run.file_record(server)}
        write_json(root / "config.resolved.json", report["config"])
        check = preflight_with_cooldown(options.manager_port, lsof, options.port_cooldown_seconds, root, evidence)
        if not check["passed"]:
            raise RuntimeError("Manager/scene port preflight failed; no manager was started")
        before_settings = settings_inventory(upstream, options.manager_port)
        write_json(root / "settings-before.json", before_settings)
        with (root / "manager.stdout.log").open("xb") as stdout, (root / "manager.stderr.log").open("xb") as stderr:
            manager = subprocess.Popen(manager_command, cwd=upstream, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, start_new_session=True)
            owned = OwnedProcesses(manager.pid)
            report.update(manager_pid=manager.pid, manager_pgid=manager.pid)
            evidence.emit("manager.spawned", argv=manager_command, pid=manager.pid, pgid=manager.pid)
            sampler = threading.Thread(target=sample, name="owned-manager-evidence", daemon=True)
            sampler.start()
            deadline = time.monotonic() + options.readiness_timeout_seconds
            while True:
                if manager.poll() is not None:
                    raise RuntimeError(f"Manager exited before readiness: {manager.returncode}")
                if time.monotonic() >= deadline:
                    report["status"] = "manager_readiness_timeout"
                    raise TimeoutError("Manager did not become ready within its independent readiness budget")
                connected = False
                try:
                    with socket.create_connection(("127.0.0.1", options.manager_port), timeout=0.25):
                        connected = True
                except OSError:
                    pass
                if connected:
                    listeners = listener_pids(options.manager_port, lsof)
                    if listeners == [manager.pid]:
                        report["readiness"] = {"tcp_accepted": True, "listener_pids": listeners,
                                               "confirmed_at_utc": supervise_run.utc_now(), "scope": "TCP/listener ownership only; scene and model readiness are separate checks"}
                        evidence.emit("manager.ready", **report["readiness"])
                        break
                    if listeners and manager.pid not in listeners:
                        raise RuntimeError("Ready port belongs to another process; it will not be signaled")
                time.sleep(0.05)
            report["status"] = "command_running"
            write_json(root / "report.json", report)
            old_exclusive = os.environ.get("VLA_LAB_SCENE_MANAGER_EXCLUSIVE")
            os.environ["VLA_LAB_SCENE_MANAGER_EXCLUSIVE"] = "1"
            try:
                exit_code = supervise_run.supervise(SimpleNamespace(output=root / "command", cwd=options.cwd,
                    timeout_seconds=options.command_timeout_seconds, grace_seconds=options.command_grace_seconds,
                    poll_gpu=options.poll_gpu, command=options.command))
            finally:
                if old_exclusive is None:
                    os.environ.pop("VLA_LAB_SCENE_MANAGER_EXCLUSIVE", None)
                else:
                    os.environ["VLA_LAB_SCENE_MANAGER_EXCLUSIVE"] = old_exclusive
            report["command_returncode"] = exit_code
            report["command_supervisor_returncode"] = exit_code
            command_report = json.loads((root / "command/report.json").read_text())
            report["command_child_returncode"] = command_report.get("child_returncode")
            report["command_termination_reason"] = command_report.get("termination_reason")
            report["status"] = "command_succeeded" if exit_code == 0 else "command_failed"
            if manager.poll() is not None:
                report["manager_exit_before_cleanup"] = manager.returncode
                if exit_code == 0:
                    exit_code, report["status"] = 1, "manager_exited_early"
    except BaseException as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        if received["signal"]:
            exit_code, report["status"] = 128 + received["signal"], "interrupted"
        elif isinstance(exc, TimeoutError):
            exit_code = 124
        else:
            exit_code, report["status"] = 1, "session_error"
        evidence.emit("session.error", **report["error"])
    finally:
        # Repeated terminal signals must not skip owned-group cleanup. The command
        # supervisor has already restored these handlers before returning here.
        for signum in previous:
            signal.signal(signum, lambda signum, frame: evidence.emit("signal.during_cleanup", signal=signum))
        stop_sampling.set()
        if sampler is not None:
            sampler.join(timeout=3)
        if manager is not None:
            try:
                report["cleanup"] = cleanup_manager(manager, owned, evidence, options.manager_grace_seconds, options.kill_wait_seconds)
            except BaseException as exc:
                report["cleanup"] = {"complete": False, "error": str(exc)}
        else:
            report["cleanup"] = {"complete": True, "scope": "No manager process was started"}
        try:
            after = settings_inventory(options.upstream.resolve(), options.manager_port) if manager is not None else {}
            copied = []
            for port, item in after.items():
                if before_settings.get(port) != item:
                    target = root / "settings" / port / "settings.json"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(item["path"], target)
                    copied.append({"port": int(port), "source": item, "copy": supervise_run.file_record(target),
                                   "scope": "New or changed settings-file bytes/mtime since preflight"})
            write_json(root / "settings-copied.json", copied)
        except Exception as exc:
            report["settings_copy_error"] = str(exc)
        if exit_code == 0 and (not report["cleanup"]["complete"] or report.get("settings_copy_error")):
            exit_code, report["status"] = 1, "cleanup_or_evidence_incomplete"
        report.update(session_returncode=exit_code, finished_at_utc=supervise_run.utc_now())
        evidence.emit("session.finished", status=report["status"], returncode=exit_code)
        evidence.stream.close()
        report["artifacts"] = [supervise_run.file_record(path) for path in sorted(root.rglob("*")) if path.is_file() and path != root / "report.json"]
        write_json(root / "report.json", report)
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    print(json.dumps({"status": report["status"], "returncode": exit_code, "report": str(root / "report.json")}))
    return exit_code


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    for name in ("upstream", "env-root", "cwd", "output"):
        result.add_argument("--" + name, type=Path, required=True)
    result.add_argument("--manager-python", default=sys.executable, help="Interpreter for the pinned manager; defaults to this process interpreter")
    result.add_argument("--manager-port", type=int, default=30000)
    result.add_argument("--gpus", default="0")
    result.add_argument("--port-cooldown-seconds", type=float, default=60,
                        help="Retry strict EADDRINUSE preflight only without observed listeners; 0 disables retries, maximum 60")
    result.add_argument("--readiness-timeout-seconds", type=float, default=60)
    result.add_argument("--command-timeout-seconds", type=float, required=True)
    result.add_argument("--command-grace-seconds", type=float, default=10)
    result.add_argument("--manager-grace-seconds", type=float, default=5)
    result.add_argument("--kill-wait-seconds", type=float, default=2)
    result.add_argument("--poll-gpu", action="store_true")
    result.add_argument("command", nargs=argparse.REMAINDER)
    return result


def main():
    cli = parser()
    options = cli.parse_args()
    if options.command[:1] == ["--"]:
        options.command = options.command[1:]
    if not options.command:
        cli.error("Supply an executable and separate arguments after --")
    if not 1024 <= options.manager_port <= 65535 - SCENE_PORT_COUNT:
        cli.error("Manager port must leave room for all 1000 upstream scene ports")
    if not re.fullmatch(r"[0-9]+(?:,[0-9]+)*", options.gpus):
        cli.error("--gpus must be nonnegative comma-separated GPU IDs")
    for name in ("port_cooldown_seconds", "readiness_timeout_seconds", "command_timeout_seconds", "command_grace_seconds", "manager_grace_seconds", "kill_wait_seconds"):
        value = getattr(options, name)
        if not math.isfinite(value) or value < 0 or (name.endswith("timeout_seconds") and value == 0):
            cli.error(f"Invalid duration: {name}")
    if options.port_cooldown_seconds > 60:
        cli.error("Port cooldown cannot exceed 60 seconds")
    for path in (options.upstream, options.env_root, options.cwd):
        if not path.is_dir():
            cli.error(f"Required directory does not exist: {path}")
    return run(options)


if __name__ == "__main__":
    raise SystemExit(main())
