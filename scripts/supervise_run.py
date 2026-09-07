#!/usr/bin/env python3
"""Run one bounded command and preserve its real output and lifecycle evidence.

Only the new process group created for this command is signaled. This script does
not discover, terminate, or claim ownership of an independently started manager.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def group_alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def file_record(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def linux_process_identity(pid):
    """Read a Linux root-process identity without reading its environment.

    Start ticks + boot ID distinguish a reused PID. Re-reading stat bounds the
    snapshot to one process identity; argv/cwd/exe changes are checked by callers.
    """
    if not sys.platform.startswith("linux"):
        raise RuntimeError("Linux /proc process identity is unavailable on this platform")
    if type(pid) is not int or pid <= 1:
        raise ValueError("Process identity requires a PID greater than one")
    root = Path("/proc") / str(pid)

    def read_stat():
        raw = (root / "stat").read_text()
        prefix, separator, remainder = raw.rpartition(") ")
        if not separator or int(prefix.split("(", 1)[0].strip()) != pid:
            raise ValueError("Malformed process stat identity")
        fields = remainder.split()
        return {"pid": pid, "pgid": int(fields[2]), "session_id": int(fields[3]),
                "starttime_ticks": int(fields[19]), "state": fields[0]}

    before = read_stat()
    argv_bytes = (root / "cmdline").read_bytes()
    argv = [part.decode("utf-8") for part in argv_bytes.rstrip(b"\0").split(b"\0")] if argv_bytes else []
    uid_line = next(line for line in (root / "status").read_text().splitlines() if line.startswith("Uid:"))
    identity = {**before, "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "uid": int(uid_line.split()[1]), "argv": argv,
        "cwd": os.readlink(root / "cwd"), "exe": os.readlink(root / "exe")}
    after = read_stat()
    if any(before[key] != after[key] for key in ("pid", "pgid", "session_id", "starttime_ticks")):
        raise RuntimeError("Process identity changed during its snapshot")
    if after["state"] in ("Z", "X", "x"):
        raise RuntimeError("Process is no longer a live signaling target")
    identity["state"] = after["state"]
    return identity


class Recorder:
    def __init__(self, root):
        self.stream = (root / "events.jsonl").open("x", buffering=1)
        self.started = time.monotonic()

    def emit(self, event, **values):
        self.stream.write(json.dumps({"event": event, "utc": utc_now(),
                                      "elapsed_seconds": time.monotonic() - self.started, **values}, allow_nan=False) + "\n")


def gpu_sample(timeout):
    """Read aggregate device metrics. These are not per-process attribution."""
    command = ["nvidia-smi", "--query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=timeout, check=False)
        if result.returncode:
            return {"available": False, "returncode": result.returncode, "error": result.stderr.strip()}
        columns = ("index", "uuid", "name", "utilization_percent", "memory_used_mib", "memory_total_mib")
        devices = [dict(zip(columns, [cell.strip() for cell in row])) for row in csv.reader(io.StringIO(result.stdout))]
        return {"available": True, "scope": "Host-wide totals for each GPU; includes other workloads", "devices": devices}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"available": False, "error": str(error)}


def supervise(options):
    root = options.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    recorder = Recorder(root)
    report = {
        "schema_version": "vla.supervised_run.v1", "started_at_utc": utc_now(), "status": "starting",
        "argv": options.command, "cwd": str(options.cwd.resolve()), "supervisor_pid": os.getpid(),
        "timeout_seconds": options.timeout_seconds, "grace_seconds": options.grace_seconds,
        "ownership": "Only the process group created with start_new_session=True for this command",
        "environment_recorded": False, "gpu_sampling_requested": options.poll_gpu,
        "monitoring_note": "Optional GPU queries and psutil sampling add supervisor overhead; no per-process GPU attribution",
        "process_pid": None, "process_group_id": None, "child_returncode": None,
        "termination_reason": None, "signals_sent": [],
    }
    requested = {"signal": None, "count": 0}

    def handle(signum, _frame):
        requested["signal"] = requested["signal"] or signum
        requested["count"] += 1

    previous_handlers = {signum: signal.signal(signum, handle) for signum in (signal.SIGINT, signal.SIGTERM)}
    process = None
    return_code = 1

    def send_owned(signum, cause):
        if process is None:
            return
        try:
            os.killpg(process.pid, signum)
            result = "sent"
        except ProcessLookupError:
            result = "already_absent"
        except OSError as error:
            result = f"error: {error}"
        entry = {"signal": signal.Signals(signum).name, "process_group_id": process.pid,
                 "cause": cause, "result": result, "utc": utc_now()}
        report["signals_sent"].append(entry)
        recorder.emit("signal.sent", **entry)

    stdout_path, stderr_path = root / "stdout.log", root / "stderr.log"
    try:
        recorder.emit("run.starting", argv=options.command, cwd=report["cwd"],
                      timeout_seconds=options.timeout_seconds, grace_seconds=options.grace_seconds)
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            if requested["signal"]:
                report["termination_reason"] = "interrupted_before_spawn"
                report["status"] = "interrupted"
                return_code = 128 + requested["signal"]
            else:
                start = time.monotonic()
                process = subprocess.Popen(options.command, cwd=options.cwd, stdout=stdout, stderr=stderr,
                                           stdin=subprocess.DEVNULL, start_new_session=True)
                report.update(process_pid=process.pid, process_group_id=process.pid, status="running")
                try:
                    identity, identity_error = linux_process_identity(process.pid), None
                except Exception as error:
                    identity, identity_error = None, f"{type(error).__name__}: {error}"
                report["process_identity_at_spawn"] = identity
                report["process_identity_error"] = identity_error
                recorder.emit("process.spawned", pid=process.pid, pgid=process.pid, root_process_alive=process.poll() is None,
                              process_identity=identity, identity_error=identity_error)
                ps_process = None
                try:
                    import psutil
                    ps_process = psutil.Process(process.pid)
                    ps_process.cpu_percent(interval=None)
                    report["psutil"] = {"available": True, "version": psutil.__version__,
                                         "scope": "Root command process only; descendants excluded", "cpu_percent_note": "May exceed 100 for multiple cores"}
                except ImportError:
                    report["psutil"] = {"available": False, "reason": "Optional package is not installed"}
                except Exception as error:
                    report["psutil"] = {"available": False, "reason": str(error)}
                deadline = start + options.timeout_seconds
                stop_deadline = None
                killed = False
                next_sample = time.monotonic()
                gpu_enabled = options.poll_gpu
                first_cpu_sample = True
                while True:
                    now = time.monotonic()
                    child_code = process.poll()
                    alive = child_code is None
                    if report["termination_reason"] is None:
                        if requested["signal"]:
                            report["termination_reason"] = "interrupted"
                            report["received_signal"] = signal.Signals(requested["signal"]).name
                        elif child_code is not None:
                            report["termination_reason"] = "natural_exit"
                        elif now >= deadline:
                            report["termination_reason"] = "timeout"
                        if report["termination_reason"]:
                            recorder.emit("stop.requested", reason=report["termination_reason"],
                                          received_signal=report.get("received_signal"), child_returncode=child_code,
                                          root_process_alive=alive, process_group_exists=group_alive(process.pid))
                            if report["termination_reason"] != "natural_exit" or group_alive(process.pid):
                                send_owned(signal.SIGTERM, report["termination_reason"] if alive else "remaining_descendants_after_root_exit")
                                stop_deadline = now + options.grace_seconds
                            else:
                                break
                    if report["termination_reason"]:
                        if not alive and not group_alive(process.pid):
                            break
                        if not killed and (now >= stop_deadline or requested["count"] > 1):
                            send_owned(signal.SIGKILL, "grace_expired" if requested["count"] <= 1 else "repeated_interrupt")
                            killed = True
                            # A zombie or uninterruptible kernel task may still appear in killpg(0).
                            # Bound supervisor cleanup; report remaining visibility honestly.
                            stop_deadline = now + 2.0
                        elif killed and now >= stop_deadline:
                            break
                    elif now >= next_sample:
                        sample = {"root_process_alive": alive, "process_group_exists": group_alive(process.pid)}
                        if ps_process is not None:
                            try:
                                cpu_percent = ps_process.cpu_percent(interval=None)
                                sample["root_process_cpu_percent"] = None if first_cpu_sample else cpu_percent
                                sample["root_process_rss_bytes"] = ps_process.memory_info().rss
                                first_cpu_sample = False
                            except Exception as error:
                                sample["psutil_error"] = str(error)
                                ps_process = None
                        remaining = deadline - time.monotonic()
                        if gpu_enabled and remaining > 0.05:
                            sample["gpu"] = gpu_sample(min(2.0, remaining))
                            gpu_enabled = sample["gpu"]["available"]
                        recorder.emit("monitor.sampled", **sample)
                        next_sample = time.monotonic() + 5.0
                    time.sleep(0.05)
                report["child_returncode"] = process.poll()
                report["root_process_alive_at_end"] = process.poll() is None
                report["process_group_exists_at_end"] = group_alive(process.pid)
                report["command_elapsed_seconds"] = time.monotonic() - start
                reason = report["termination_reason"]
                if reason == "timeout":
                    report["status"], return_code = "timed_out", 124
                elif reason == "interrupted":
                    report["status"], return_code = "interrupted", 128 + requested["signal"]
                else:
                    code = report["child_returncode"]
                    report["status"] = "exited_successfully" if code == 0 else "exited_with_error"
                    return_code = code if code is not None and code >= 0 else 128 - code if code is not None else 1
                if report["root_process_alive_at_end"] or report["process_group_exists_at_end"]:
                    report["cleanup_note"] = "Process group remains visible after bounded cleanup; it may contain zombies or uninterruptible tasks. No external process group was signaled."
                    if return_code == 0:
                        report["status"], return_code = "cleanup_incomplete", 1
                recorder.emit("process.finished", child_returncode=report["child_returncode"], status=report["status"],
                              root_process_alive=report["root_process_alive_at_end"], process_group_exists=report["process_group_exists_at_end"])
    except BaseException as error:
        report["status"] = "supervisor_error"
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        recorder.emit("supervisor.error", **report["error"])
        return_code = 127 if isinstance(error, FileNotFoundError) else 1
        if process is not None and group_alive(process.pid):
            send_owned(signal.SIGTERM, "supervisor_error")
            until = time.monotonic() + options.grace_seconds
            while time.monotonic() < until and group_alive(process.pid):
                process.poll()
                time.sleep(0.05)
            if group_alive(process.pid):
                send_owned(signal.SIGKILL, "supervisor_error_grace_expired")
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
    finally:
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)
        if process is not None:
            report["child_returncode"] = process.poll()
            report["root_process_alive_at_end"] = process.poll() is None
            report["process_group_exists_at_end"] = group_alive(process.pid)
        report["finished_at_utc"] = utc_now()
        report["supervisor_exit_code"] = return_code
        report["stdout"] = file_record(stdout_path) if stdout_path.exists() else None
        report["stderr"] = file_record(stderr_path) if stderr_path.exists() else None
        recorder.emit("run.finished", status=report["status"], supervisor_exit_code=return_code)
        recorder.stream.close()
        report["events"] = file_record(root / "events.jsonl")
        temporary = root / "report.json.tmp"
        temporary.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        temporary.replace(root / "report.json")
        print(json.dumps({"status": report["status"], "supervisor_exit_code": return_code, "report": str(root / "report.json")}))
    return return_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--grace-seconds", type=float, default=10.0)
    parser.add_argument("--poll-gpu", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    if options.command[:1] == ["--"]:
        options.command = options.command[1:]
    if not options.command:
        parser.error("A command is required after --")
    if not (0 < options.timeout_seconds < float("inf")) or not (0 <= options.grace_seconds < float("inf")):
        parser.error("Timeout must be finite and positive; grace must be finite and nonnegative")
    if not options.cwd.is_dir():
        parser.error("--cwd must be an existing directory")
    return supervise(options)


if __name__ == "__main__":
    raise SystemExit(main())
