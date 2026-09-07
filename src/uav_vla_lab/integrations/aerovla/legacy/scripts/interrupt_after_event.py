#!/usr/bin/env python3
"""Send one SIGINT to a verified supervised evaluator after N observed events.

This helper observes an existing owned run. It neither launches an evaluator nor
cleans up processes; the simulation-session/supervisor lifecycle retains that job.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import select
import signal
import sys
import time


_SPEC = importlib.util.spec_from_file_location("_vla_supervisor_identity", Path(__file__).with_name("supervise_run.py"))
_SUPERVISOR = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SUPERVISOR)
linux_process_identity = _SUPERVISOR.linux_process_identity
PROTOCOL = "aerovla-e37685a-observed-v1"
TRIGGERS = ("action.completed", "policy.generated", "policy.decoded")
IDENTITY_FIELDS = ("pid", "pgid", "session_id", "starttime_ticks", "boot_id", "uid", "argv", "cwd", "exe")


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


class RefuseInterrupt(RuntimeError):
    pass


def reject_constant(value):
    raise ValueError(f"Nonfinite JSON number: {value}")


class EventTail:
    """Follow one append-only JSONL inode; do not parse an unfinished last line."""
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.handle = None
        self.identity = None
        self.buffer = b""
        self.byte_count = self.line_count = 0
        self.digest = hashlib.sha256()

    def read(self):
        if self.handle is None:
            try:
                self.handle = self.path.open("rb")
            except FileNotFoundError:
                return []
            value = os.fstat(self.handle.fileno())
            self.identity = (value.st_dev, value.st_ino)
        value = self.path.stat()
        if (value.st_dev, value.st_ino) != self.identity or value.st_size < self.byte_count:
            raise RefuseInterrupt(f"Evidence file was replaced or truncated: {self.path}")
        data = self.handle.read(4 * 1024 * 1024)
        self.digest.update(data)
        self.byte_count += len(data)
        self.buffer += data
        if len(self.buffer) > 16 * 1024 * 1024 and b"\n" not in self.buffer:
            raise RefuseInterrupt("Evidence JSONL line exceeds the 16 MiB observation bound")
        lines = self.buffer.split(b"\n")
        self.buffer = lines.pop()
        result = []
        for line in lines:
            self.line_count += 1
            if len(line) > 16 * 1024 * 1024:
                raise RefuseInterrupt("Evidence JSONL line exceeds the 16 MiB observation bound")
            try:
                value = json.loads(line, parse_constant=reject_constant)
                if not isinstance(value, dict):
                    raise ValueError("Expected an event object")
            except (ValueError, UnicodeError) as exc:
                raise RefuseInterrupt(f"Malformed evidence at {self.path}:{self.line_count}: {exc}") from exc
            result.append(value)
        return result

    def snapshot(self):
        return {"path": str(self.path), "device_inode": list(self.identity) if self.identity else None,
                "bytes_read": self.byte_count, "complete_lines_read": self.line_count,
                "sha256_of_bytes_read": self.digest.hexdigest(), "unfinished_line_bytes": len(self.buffer),
                "scope": "Exact consumed file prefix; the active source may subsequently append more evidence"}

    def close(self):
        if self.handle:
            self.handle.close()


def verified_identity(starting, spawned, current):
    if not isinstance(starting, dict) or not isinstance(spawned, dict):
        raise RefuseInterrupt("Supervisor starting/spawn evidence is incomplete")
    pid, pgid = spawned.get("pid"), spawned.get("pgid")
    if type(pid) is not int or pid <= 1 or pgid != pid or spawned.get("root_process_alive") is not True:
        raise RefuseInterrupt("Supervisor did not record a live owned process-group leader")
    recorded = spawned.get("process_identity")
    if spawned.get("identity_error") is not None or not isinstance(recorded, dict):
        raise RefuseInterrupt("Supervisor did not capture the original Linux process identity")
    if any(field not in recorded for field in IDENTITY_FIELDS):
        raise RefuseInterrupt("Recorded process identity is incomplete")
    if any(type(recorded[key]) is not int for key in ("pid", "pgid", "session_id", "starttime_ticks", "uid")):
        raise RefuseInterrupt("Recorded numeric identity fields are malformed")
    if recorded["pid"] != pid or recorded["pgid"] != pgid or recorded["session_id"] != pid or recorded["starttime_ticks"] <= 0:
        raise RefuseInterrupt("Recorded target is not the supervisor-created process/session leader")
    if any(not isinstance(recorded[key], str) or not recorded[key] for key in ("boot_id", "exe", "cwd")) or recorded["uid"] != os.getuid():
        raise RefuseInterrupt("Recorded boot/executable/user identity is invalid for this helper")
    if not isinstance(starting.get("argv"), list) or not starting["argv"] or any(not isinstance(value, str) for value in starting["argv"]) or recorded["argv"] != starting["argv"]:
        raise RefuseInterrupt("Spawned command line differs from the declared supervised command")
    if recorded["cwd"] != starting.get("cwd"):
        raise RefuseInterrupt("Spawned working directory differs from the supervised declaration")
    if not isinstance(current, dict) or any(current.get(field) != recorded[field] for field in IDENTITY_FIELDS):
        raise RefuseInterrupt("Live PID/group/starttime/boot/user/command identity differs from the recorded process")
    if current.get("state") in ("Z", "X", "x"):
        raise RefuseInterrupt("Target process has already ended")
    if pid == os.getpid() or pgid == os.getpgrp():
        raise RefuseInterrupt("Refusing to signal the helper or its own process group")
    return recorded


class ObservedRun:
    def __init__(self, event_type, after_count, expected_runtime_id):
        self.event_type, self.after_count = event_type, after_count
        self.expected_runtime_id = expected_runtime_id
        self.starting = self.spawned = self.run_start = self.episode_start = None
        self.supervisor_ended = self.navigation_ended = None
        self.event_id = self.count = 0
        self.trigger = None

    def supervisor(self, events):
        for event in events:
            kind = event.get("event")
            if not isinstance(kind, str) or not kind:
                raise RefuseInterrupt("Malformed supervisor event type")
            if kind == "run.starting":
                if self.starting is not None:
                    raise RefuseInterrupt("More than one supervised run was observed")
                self.starting = event
            elif kind == "process.spawned":
                if self.starting is None or self.spawned is not None:
                    raise RefuseInterrupt("Missing starting event or multiple process spawns")
                self.spawned = event
            elif kind in ("stop.requested", "signal.sent", "process.finished", "run.finished", "supervisor.error"):
                self.supervisor_ended = event

    def navigation(self, events):
        for event in events:
            kind, identifier = event.get("event_type"), event.get("event_id")
            if event.get("schema_version") != 1 or not isinstance(kind, str) or not kind or type(identifier) is not int or identifier != self.event_id + 1:
                raise RefuseInterrupt("Malformed, duplicate or unordered navigation event identity")
            self.event_id = identifier
            if kind == "run.start":
                if self.run_start is not None or not isinstance(event.get("run_id"), str) or not event["run_id"]:
                    raise RefuseInterrupt("Missing or repeated navigation run identity")
                if event.get("protocol") != PROTOCOL or event.get("runtime_id") != self.expected_runtime_id:
                    raise RefuseInterrupt("Navigation source protocol/runtime differs from this interruption plan")
                self.run_start = event
            elif self.run_start is None or event.get("run_id") != self.run_start["run_id"]:
                raise RefuseInterrupt("Navigation evidence starts without run.start or mixes run IDs")
            if kind == "episode.start":
                if self.episode_start is not None:
                    raise RefuseInterrupt("More than one episode was observed before interruption")
                if not isinstance(event.get("attempt_id"), str) or not event["attempt_id"]:
                    raise RefuseInterrupt("Episode lacks an attempt identity")
                self.episode_start = event
            if kind in ("episode.completed", "episode.interrupted", "run.end"):
                self.navigation_ended = event
            if kind == self.event_type:
                if self.episode_start is None or any(event.get(key) != self.episode_start.get(key) for key in ("attempt_id", "episode_id", "map_name")):
                    raise RefuseInterrupt("Trigger event does not belong to the observed episode")
                self.count += 1
                self.trigger = {key: event.get(key) for key in ("event_type", "event_id", "run_id", "attempt_id", "episode_id", "map_name",
                                "wall_time_utc", "host_monotonic_ns", "command_event_id", "policy_event_id", "observation_event_id")}

    def decision(self):
        if self.supervisor_ended or self.navigation_ended:
            return "already_ended_or_stopping"
        if self.count > self.after_count:
            return "trigger_count_already_exceeded"
        if self.count == self.after_count:
            return "trigger_observed"
        return "waiting"

    def bind_navigation(self, identity):
        if self.run_start is None or self.run_start.get("process_id") != identity["pid"]:
            raise RefuseInterrupt("Navigation run.start does not identify the supervised evaluator PID")
        argv = self.run_start.get("argv")
        if not isinstance(argv, list) or not argv or len(argv) >= len(identity["argv"]) or identity["argv"][-len(argv):] != argv:
            raise RefuseInterrupt("Navigation argv is not the recorded direct Python evaluator command suffix")


def pidfd_alive(descriptor):
    poller = select.poll()
    poller.register(descriptor, select.POLLIN | select.POLLHUP | select.POLLERR)
    return not poller.poll(0)


def interrupt(options):
    output = options.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    deadline = started + options.timeout_seconds
    report = {"schema_version": "vla.interrupt-after-event.v1", "started_at_utc": utc_now(), "status": "waiting",
              "event_type": options.event_type, "after_count": options.after_count, "expected_runtime_id": options.runtime_id,
              "timeout_seconds": options.timeout_seconds, "poll_seconds": options.poll_seconds, "dry_run": options.dry_run,
              "signal_attempted": False, "signal_result": None, "signal_count": 0,
              "ownership_scope": "One SIGINT request to the supervisor-created evaluator PGID only; no manager or independent process cleanup",
              "timing_scope": "Trigger count is the last observed evidence prefix at the final check; the evaluator can advance before signal delivery",
              "identity_scope": "Linux boot ID/start ticks and command identity are rechecked immediately before numeric PGID signaling; this check and killpg are not one atomic kernel operation"}
    supervisor_tail, navigation_tail = EventTail(options.supervisor_events), EventTail(options.experiment_events)
    observed = ObservedRun(options.event_type, options.after_count, options.runtime_id)
    descriptor = None
    initial_identity = None
    returncode = 1
    journal = (output / "events.jsonl").open("x", encoding="utf-8", buffering=1)

    def emit(kind, **fields):
        journal.write(json.dumps({"event": kind, "utc": utc_now(), "elapsed_seconds": time.monotonic() - started, **fields}, allow_nan=False) + "\n")

    def drain():
        # Consume the entire currently available prefix, including batches >4 MiB,
        # so a delayed watcher never treats the Nth event of N+1 as an exact trigger.
        for tail, consume in ((supervisor_tail, observed.supervisor), (navigation_tail, observed.navigation)):
            while True:
                before = tail.byte_count
                consume(tail.read())
                if tail.byte_count - before < 4 * 1024 * 1024:
                    break
                if time.monotonic() >= deadline:
                    raise RefuseInterrupt("Deadline reached while draining the evidence prefix")

    try:
        emit("watch.started", supervisor_events=str(supervisor_tail.path), experiment_events=str(navigation_tail.path))
        while True:
            if time.monotonic() >= deadline:
                report["status"], returncode = "timed_out_without_signal", 124
                break
            drain()
            decision = observed.decision()
            if decision in ("already_ended_or_stopping", "trigger_count_already_exceeded"):
                report["status"] = decision
                break
            if observed.spawned is not None:
                if initial_identity is None:
                    current = linux_process_identity(observed.spawned.get("pid"))
                    initial_identity = verified_identity(observed.starting, observed.spawned, current)
                    if not hasattr(os, "pidfd_open"):
                        raise RefuseInterrupt("Linux pidfd_open is required for the additional process-exit guard")
                    descriptor = os.pidfd_open(initial_identity["pid"], 0)
                    verified_identity(observed.starting, observed.spawned, linux_process_identity(initial_identity["pid"]))
                    report["verified_identity"] = initial_identity
                    emit("target.verified", pid=initial_identity["pid"], pgid=initial_identity["pgid"],
                         boot_id=initial_identity["boot_id"], starttime_ticks=initial_identity["starttime_ticks"])
                if not pidfd_alive(descriptor):
                    raise RefuseInterrupt("Original evaluator has exited; its PID is not a current target")
            if decision == "trigger_observed":
                if initial_identity is None:
                    raise RefuseInterrupt("Trigger arrived without recorded supervisor process ownership")
                observed.bind_navigation(initial_identity)
                current = linux_process_identity(initial_identity["pid"])
                verified_identity(observed.starting, observed.spawned, current)
                drain()
                decision = observed.decision()
                if decision != "trigger_observed":
                    report["status"] = decision
                    break
                if supervisor_tail.buffer or navigation_tail.buffer:
                    # A partial line might be a terminal event. Wait for its actual
                    # completion instead of signaling against ambiguous evidence.
                    time.sleep(min(options.poll_seconds, max(0.0, deadline - time.monotonic())))
                    continue
                observed.bind_navigation(initial_identity)
                current = linux_process_identity(initial_identity["pid"])
                verified_identity(observed.starting, observed.spawned, current)
                if not pidfd_alive(descriptor):
                    raise RefuseInterrupt("Evaluator exited before the final signal gate")
                if time.monotonic() >= deadline:
                    report["status"], returncode = "timed_out_without_signal", 124
                    break
                report["final_identity_check"] = current
                report["trigger_observed_at_utc"] = utc_now()
                report["trigger"] = observed.trigger
                emit("trigger.verified", count=observed.count, trigger=observed.trigger)
                if options.dry_run:
                    report["status"], returncode = "dry_run_validated_no_signal", 0
                else:
                    report["signal_attempted"] = True
                    report["signal_count"] = 1
                    report["signal_request"] = {"function": "os.killpg", "pgid": initial_identity["pgid"], "signal": "SIGINT",
                                                "signal_number": int(signal.SIGINT), "utc": utc_now(), "host_monotonic_ns": time.monotonic_ns()}
                    emit("signal.requested", **report["signal_request"])
                    try:
                        os.killpg(initial_identity["pgid"], signal.SIGINT)
                    except OSError as exc:
                        report["status"], report["signal_result"] = "signal_request_failed", f"{type(exc).__name__}: {exc}"
                    else:
                        report["status"], report["signal_result"], returncode = "sigint_requested", "kernel_accepted_request", 0
                    report["signal_returned_at_utc"] = utc_now()
                break
            time.sleep(min(options.poll_seconds, max(0.0, deadline - time.monotonic())))
    except (Exception, KeyboardInterrupt) as exc:
        report["status"] = "helper_interrupted_without_retry" if isinstance(exc, KeyboardInterrupt) else "identity_or_evidence_rejected"
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        report.update(observed_trigger_count=observed.count, observed_trigger=observed.trigger,
                      supervisor_starting=observed.starting, supervisor_spawned=observed.spawned,
                      recorded_navigation_run_start=observed.run_start, recorded_episode_start=observed.episode_start,
                      observed_supervisor_terminal=observed.supervisor_ended, observed_navigation_terminal=observed.navigation_ended,
                      supervisor_evidence_prefix=supervisor_tail.snapshot(), navigation_evidence_prefix=navigation_tail.snapshot(),
                      finished_at_utc=utc_now(), elapsed_seconds=time.monotonic() - started, returncode=returncode)
        emit("watch.finished", status=report["status"], returncode=returncode, observed_trigger_count=observed.count,
             signal_attempted=report["signal_attempted"])
        journal.close()
        supervisor_tail.close()
        navigation_tail.close()
        if descriptor is not None:
            os.close(descriptor)
        (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(output.iterdir()) if path.is_file()}
        (output / "checksums.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--supervisor-events", type=Path, required=True)
    parser.add_argument("--experiment-events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-id", required=True)
    parser.add_argument("--event-type", choices=TRIGGERS, default="action.completed")
    parser.add_argument("--after-count", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--poll-seconds", type=float, default=0.02)
    parser.add_argument("--dry-run", action="store_true")
    options = parser.parse_args()
    if not options.runtime_id or options.after_count < 1:
        parser.error("A runtime ID and positive trigger count are required")
    if not math.isfinite(options.timeout_seconds) or options.timeout_seconds <= 0 or not math.isfinite(options.poll_seconds) or not 0.001 <= options.poll_seconds <= 1:
        parser.error("Timeout must be finite and positive; poll interval must be 0.001–1 seconds")
    if not sys.platform.startswith("linux"):
        parser.error("This live interruption helper requires Linux /proc and pidfd support")
    report = interrupt(options)
    print(json.dumps({"status": report["status"], "signal_attempted": report["signal_attempted"],
                      "observed_trigger_count": report["observed_trigger_count"], "report": str(options.output.resolve() / "report.json")}))
    return report["returncode"]


if __name__ == "__main__":
    raise SystemExit(main())
