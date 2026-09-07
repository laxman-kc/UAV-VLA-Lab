#!/usr/bin/env python3
"""Retrospective P07 validation; no signaling, GPU calls or source-evidence edits."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import summarize_navigation as nav

IDENTITY_FIELDS = ("pid", "pgid", "session_id", "starttime_ticks", "boot_id", "uid", "argv", "cwd", "exe")


class Validation:
    def __init__(self):
        self.checks, self.files, self.changed_during_reads = [], {}, set()

    def check(self, name, truth, detail=None):
        self.checks.append({"id": name, "status": "unknown" if truth is None else "pass" if truth else "fail", "detail": detail})

    def fields(self, name, data, required, predicate):
        if not isinstance(data, dict) or any(k not in data for k in required):
            self.check(name, None, "Required fields unavailable: " + ", ".join(required))
        else:
            try:
                self.check(name, bool(predicate(data)))
            except (TypeError, ValueError, KeyError) as exc:
                self.check(name, False, str(exc))

    def record(self, path):
        path = Path(path).resolve()
        result = {"path": str(path), "sha256": nav.sha256(path), "bytes": path.stat().st_size}
        if str(path) in self.files and self.files[str(path)] != result:
            self.changed_during_reads.add(str(path))
        self.files.setdefault(str(path), result)
        return result

    def read(self, path, label, lines=False):
        try:
            self.record(path)
            data = Path(path).read_bytes()
            reject = lambda s: (_ for _ in ()).throw(ValueError("Nonfinite JSON: " + s))
            if lines:
                if not data or not data.endswith(b"\n"):
                    raise ValueError("Missing or unfinished final JSONL line")
                values = [json.loads(line, parse_constant=reject) for line in data.splitlines()]
                if any(not isinstance(v, dict) for v in values):
                    raise ValueError("Events must be objects")
                return [{**v, "_source_line": i} for i, v in enumerate(values, 1)]
            value = json.loads(data, parse_constant=reject)
            if not isinstance(value, dict):
                raise ValueError("Expected an object")
            return value
        except FileNotFoundError:
            self.check(label + ".available", None, str(path))
        except (OSError, ValueError) as exc:
            self.check(label + ".readable", False, str(exc))
        return None

    def hash_record(self, path, record, label):
        if not isinstance(record, dict) or not all(k in record for k in ("sha256", "bytes")):
            self.check(label, None, "Source hash/size unavailable")
            return
        try:
            actual = self.record(path)
            self.check(label, actual["sha256"] == record["sha256"] and actual["bytes"] == record["bytes"])
        except FileNotFoundError:
            self.check(label, None, "Referenced artifact missing")
        except OSError as exc:
            self.check(label, False, str(exc))

    def prefix(self, path, record, label):
        if not isinstance(record, dict) or not all(k in record for k in
                ("bytes_read", "sha256_of_bytes_read", "unfinished_line_bytes", "complete_lines_read")):
            self.check(label, None, "Consumed-prefix receipt unavailable")
            return None
        try:
            size = record["bytes_read"]
            if type(size) is not int or size <= 0:
                raise ValueError("Invalid prefix size")
            with Path(path).open("rb") as stream:
                data = stream.read(size)
            ok = (len(data) == size and hashlib.sha256(data).hexdigest() == record["sha256_of_bytes_read"] and
                  record["unfinished_line_bytes"] == 0 and data.endswith(b"\n") and
                  len(data.splitlines()) == record["complete_lines_read"])
            self.check(label, ok)
            return [json.loads(line) for line in data.splitlines()] if ok else None
        except FileNotFoundError:
            self.check(label, None, "Prefix source missing")
        except (OSError, ValueError) as exc:
            self.check(label, False, str(exc))
        return None


def one(events, kind, field="event_type"):
    rows = [e for e in (events or []) if e.get(field) == kind]
    return rows[0] if len(rows) == 1 else None


def lifecycle(v, root, label, interrupted):
    session = v.read(root / "report.json", label + ".session")
    supervisor = v.read(root / "command/report.json", label + ".supervisor")
    se = v.read(root / "command/events.jsonl", label + ".supervisor_events", True)
    le = v.read(root / "lifecycle.jsonl", label + ".lifecycle", True)
    if supervisor:
        v.fields(label + ".command_cleanup", supervisor, ["root_process_alive_at_end", "process_group_exists_at_end"],
                 lambda s: s["root_process_alive_at_end"] is False and s["process_group_exists_at_end"] is False)
        v.fields(label + ".command_exit", supervisor, ["termination_reason", "child_returncode", "supervisor_exit_code", "status"],
                 lambda s: s["termination_reason"] == "natural_exit" and
                 (s["child_returncode"] in (-2, 130) and s["supervisor_exit_code"] == 130 and s["status"] == "exited_with_error"
                  if interrupted else s["child_returncode"] == s["supervisor_exit_code"] == 0 and s["status"] == "exited_successfully"))
        v.fields(label + ".no_command_force_kill", supervisor, ["signals_sent"],
                 lambda s: isinstance(s["signals_sent"], list) and all(x.get("signal") != "SIGKILL" for x in s["signals_sent"]))
        for name in ("stdout", "stderr", "events"):
            v.hash_record(root / "command" / (name + (".jsonl" if name == "events" else ".log")),
                          supervisor.get(name), label + ".command_" + name + "_integrity")
        v.fields(label + ".supervisor_finished_event", one(se, "process.finished", "event"),
                 ["child_returncode", "root_process_alive", "process_group_exists"],
                 lambda e: e["child_returncode"] == supervisor.get("child_returncode") and
                 e["root_process_alive"] is False and e["process_group_exists"] is False)
    if session:
        v.fields(label + ".manager_ready_and_owned", session, ["manager_pid", "manager_pgid", "readiness"],
                 lambda s: type(s["manager_pid"]) is int and s["manager_pid"] == s["manager_pgid"] and
                 s["readiness"].get("tcp_accepted") is True and s["readiness"].get("listener_pids") == [s["manager_pid"]])
        cleanup = session.get("cleanup")
        v.fields(label + ".manager_cleanup", cleanup,
                 ["complete", "manager_group_visible", "inspection_succeeded", "errors", "final_process_evidence", "manager_returncode"],
                 lambda c: c["complete"] is True and c["manager_group_visible"] is False and c["inspection_succeeded"] is True and
                 c["errors"] == [] and c["manager_returncode"] is not None and
                 c["final_process_evidence"].get("processes") == [] and c["final_process_evidence"].get("escaped_observed_descendants") == [])
        v.fields(label + ".session_exit", session,
                 ["session_returncode", "status", "command_child_returncode", "command_supervisor_returncode"],
                 lambda s: s["session_returncode"] == (130 if interrupted else 0) and
                 s["status"] == ("command_failed" if interrupted else "command_succeeded") and supervisor is not None and
                 s["command_child_returncode"] == supervisor.get("child_returncode") and s["command_supervisor_returncode"] == supervisor.get("supervisor_exit_code"))
        v.check(label + ".no_session_errors", not any(k in session for k in ("error", "settings_copy_error", "manager_exit_before_cleanup")))
        event = one(le, "manager.cleanup", "event")
        v.check(label + ".manager_cleanup_event_matches", None if event is None else
                all(event.get(k) == value for k, value in (cleanup or {}).items()))
        v.fields(label + ".cleanup_signals_own_manager", cleanup, ["signals"],
                 lambda c: all(item.get("pgid") == session.get("manager_pgid") for item in c["signals"]))
        artifacts = session.get("artifacts")
        records = [r for r in (artifacts or []) if str(r.get("path", "")).endswith("/command/report.json")]
        if len(records) == 1:
            remote_root = Path(records[0]["path"]).parent.parent
            for i, record in enumerate(artifacts):
                try:
                    relative = Path(record["path"]).relative_to(remote_root)
                    v.hash_record(nav.strict_relative(root, relative.as_posix()), record, label + f".artifact_{i}_integrity")
                except (ValueError, KeyError) as exc:
                    v.check(label + f".artifact_{i}_integrity", False, str(exc))
        else:
            v.check(label + ".session_artifact_mapping", None, "No unique command/report.json artifact")
    return {"session": session, "supervisor": supervisor, "supervisor_events": se}


def experiment(v, root, label, interrupted, expected_runtime, count):
    events = v.read(root / "events.jsonl", label + ".navigation", True)
    if events is None:
        return {"events": None}
    start, episode, end = one(events, "run.start"), one(events, "episode.start"), one(events, "run.end")
    v.check(label + ".single_run_attempt_with_terminal_trace", all((start, episode, end)) and events[0] is start and events[-1] is end)
    if not all((start, episode, end)):
        return {"events": events}
    v.check(label + ".event_identity_order", all(e.get("event_id") == i and e.get("run_id") == start.get("run_id")
            for i, e in enumerate(events, 1)) and all(type(e.get("host_monotonic_ns")) is int for e in events) and
            all(a["host_monotonic_ns"] <= b["host_monotonic_ns"] for a, b in zip(events, events[1:])))
    v.check(label + ".expected_protocol_runtime", start.get("protocol") == nav.PROTOCOL and start.get("runtime_id") == expected_runtime)
    v.fields(label + ".hook_cleanup", end, ["status", "cleanup_errors"],
             lambda e: e["status"] == ("interrupted" if interrupted else "completed") and e["cleanup_errors"] == [])
    attempt = [e for e in events if e.get("attempt_id") == episode.get("attempt_id")]
    v.check(label + ".no_foreign_attempt", all(e.get("attempt_id") in (None, episode.get("attempt_id")) for e in events))
    actions = [e for e in attempt if e.get("event_type") == "action.completed"]
    v.check(label + ".completed_action_scope", len(actions) == count if interrupted else len(actions) > 0,
            {"completed_actions": len(actions), "expected_interrupted_count": count})
    errors = nav.check_images(attempt, root, v)
    v.check(label + ".image_integrity", not errors, errors)
    by_id, capture_errors = {e.get("event_id"): e for e in events}, []
    for event in attempt:
        if event.get("event_type") == "observation.prepared":
            captured = by_id.get(event.get("image_capture_event_id"), {})
            if not (captured.get("event_type") == "images.received" and captured.get("attempt_id") == event.get("attempt_id") and
                    captured.get("event_id", float("inf")) < event["event_id"] and len(captured.get("responses", [])) == 10):
                capture_errors.append(event["event_id"])
    v.check(label + ".observation_capture_links", not capture_errors, capture_errors)
    sequential_errors = []
    previous_command = None
    for done in actions:
        requested = by_id.get(done.get("command_event_id"), {})
        observed = by_id.get(requested.get("observation_event_id"), {})
        captured = by_id.get(observed.get("image_capture_event_id"), {})
        earlier = [e for e in attempt if e.get("event_type") == "observation.prepared" and e["event_id"] < requested.get("event_id", -1)]
        if (not earlier or earlier[-1].get("event_id") != observed.get("event_id") or
                captured.get("command_event_id") != previous_command):
            sequential_errors.append(done["event_id"])
        previous_command = done.get("command_event_id")
    v.check(label + ".completed_actions_use_current_observation", not sequential_errors, sequential_errors)
    terminal = one(attempt, "episode.interrupted" if interrupted else "episode.completed")
    v.check(label + ".terminal_kind", terminal is not None and not any(e.get("event_type") ==
            ("episode.completed" if interrupted else "episode.interrupted") for e in attempt))
    pending = []
    if interrupted:
        partial = v.read(root / "partial" / f"{episode['attempt_id']}.json", label + ".partial")
        v.check(label + ".partial_matches_interruption", None if partial is None or terminal is None else
                partial.get("status") == "interrupted" and partial.get("error_type") == "KeyboardInterrupt" and
                all(terminal.get(k) == value for k, value in partial.items()) and
                all(partial.get(k) == episode.get(k) for k in ("attempt_id", "episode_id", "map_name")))
        v.check(label + ".no_completed_outcome", not list((root / "outcomes").glob("*.json")))
        if actions:
            boundary = actions[-1]
            errors = nav.check_event_links([e for e in attempt if e["event_id"] <= boundary["event_id"]], episode, boundary, None)
            v.check(label + ".completed_causal_prefix", not errors, errors)
            pending = [{"event_id": e["event_id"], "event_type": e["event_type"]} for e in attempt
                       if e["event_id"] > boundary["event_id"] and e["event_type"] in
                       ("observation.prepared", "prompt.prepared", "policy.generated", "policy.decoded", "action.requested")]
    else:
        outcome = v.read(root / "outcomes" / f"{episode['attempt_id']}.json", label + ".outcome")
        if terminal is not None and outcome is not None:
            errors = nav.check_event_links([e for e in attempt if e["event_id"] <= terminal["event_id"]], episode, terminal, outcome)
            errors += nav.validate_outcome(outcome, terminal, episode, start.get("max_actions", 0))
            v.check(label + ".completed_chain_and_outcome", not errors, errors)
        v.check(label + ".no_partial_outcome", not list((root / "partial").glob("*.json")))
    return {"events": events, "start": start, "episode": episode, "end": end, "terminal": terminal, "actions": actions, "pending_tail": pending}


def validate(options):
    v = Validation()
    v.record(__file__)
    v.record(nav.__file__)
    aroot, broot = Path(options.interrupted_evidence).resolve(), Path(options.restart_evidence).resolve()
    asession, bsession, hroot = Path(options.interrupted_session).resolve(), Path(options.restart_session).resolve(), Path(options.interruption).resolve()
    roots = [aroot, broot, asession, bsession, hroot]
    v.check("fresh_distinct_roots", len(set(roots)) == 5 and not aroot.is_relative_to(broot) and not broot.is_relative_to(aroot))
    a = experiment(v, aroot, "interrupted", True, options.expected_runtime_id, options.expected_completed_actions)
    b = experiment(v, broot, "restart", False, options.expected_runtime_id, options.expected_completed_actions)
    sa, sb = lifecycle(v, asession, "interrupted", True), lifecycle(v, bsession, "restart", False)
    helper, journal = v.read(hroot / "report.json", "helper.report"), v.read(hroot / "events.jsonl", "helper.events", True)
    hashes = v.read(hroot / "checksums.json", "helper.checksums")
    if hashes:
        for name in ("report.json", "events.jsonl"):
            v.check("helper." + name + "_hash", None if name not in hashes or not (hroot / name).exists() else nav.sha256(hroot / name) == hashes[name])
    if helper:
        v.fields("helper.one_kernel_accepted_SIGINT", helper,
                 ["status", "dry_run", "signal_attempted", "signal_count", "signal_result", "event_type", "after_count", "observed_trigger_count"],
                 lambda h: h["status"] == "sigint_requested" and h["dry_run"] is False and h["signal_attempted"] is True and h["signal_count"] == 1 and
                 h["signal_result"] == "kernel_accepted_request" and h["event_type"] == "action.completed" and h["after_count"] == h["observed_trigger_count"] == options.expected_completed_actions)
        prefix = v.prefix(aroot / "events.jsonl", helper.get("navigation_evidence_prefix"), "helper.navigation_prefix")
        v.prefix(asession / "command/events.jsonl", helper.get("supervisor_evidence_prefix"), "helper.supervisor_prefix")
        if prefix is not None:
            trigger, completed = helper.get("trigger", {}), [e for e in prefix if e.get("event_type") == "action.completed"]
            v.check("helper.actual_trigger_boundary", len(completed) == options.expected_completed_actions and bool(completed) and
                    all(completed[-1].get(k) == value for k, value in trigger.items()) and
                    not any(e.get("event_type") in ("episode.completed", "episode.interrupted", "run.end") for e in prefix))
        bindings = (("recorded_navigation_run_start", a.get("start")),
                    ("recorded_episode_start", a.get("episode")),
                    ("supervisor_starting", one(sa["supervisor_events"], "run.starting", "event")),
                    ("supervisor_spawned", one(sa["supervisor_events"], "process.spawned", "event")))
        for name, actual in bindings:
            v.check("helper." + name + "_binding", None if actual is None or helper.get(name) is None else
                    helper[name] == {k: value for k, value in actual.items() if k != "_source_line"})
        v.fields("helper.expected_runtime", helper, ["expected_runtime_id"],
                 lambda h: h["expected_runtime_id"] == options.expected_runtime_id)
        identities = [helper.get("verified_identity"), helper.get("final_identity_check"),
                      (sa["supervisor"] or {}).get("process_identity_at_spawn"),
                      (one(sa["supervisor_events"], "process.spawned", "event") or {}).get("process_identity")]
        if all(isinstance(i, dict) and all(k in i for k in IDENTITY_FIELDS) for i in identities):
            ident, signal = identities[0], helper.get("signal_request", {})
            v.check("helper.identity_and_signal_target", all(all(i[k] == ident[k] for k in IDENTITY_FIELDS) for i in identities[1:]) and
                    ident["pid"] == ident["pgid"] == ident["session_id"] and signal.get("pgid") == ident["pgid"] and
                    signal.get("signal") == "SIGINT" and signal.get("signal_number") == 2 and (a.get("start") or {}).get("process_id") == ident["pid"])
        else:
            v.check("helper.identity_and_signal_target", None, "Original/final/supervisor identity unavailable")
        signals = [e for e in (journal or []) if e.get("event") == "signal.requested"]
        v.check("helper.signal_journal_binding", None if journal is None else len(signals) == 1 and
                all(signals[0].get(k) == value for k, value in helper.get("signal_request", {}).items()))
        manager_pgid = (sa["session"] or {}).get("manager_pgid")
        v.check("helper.did_not_target_manager", None if manager_pgid is None else
                helper.get("signal_request", {}).get("pgid") != manager_pgid)
        terminal, sent_ns = a.get("terminal"), helper.get("signal_request", {}).get("host_monotonic_ns")
        v.check("interrupted.partial_after_signal", None if terminal is None or type(sent_ns) is not int else
                terminal.get("host_monotonic_ns", -1) >= sent_ns and (a.get("end") or {}).get("error_type") == "KeyboardInterrupt")
    if a.get("start") and b.get("start"):
        x, y, ae, be = a["start"], b["start"], a["episode"], b["episode"]
        v.check("restart.new_run_and_attempt", x.get("run_id") != y.get("run_id") and ae.get("attempt_id") != be.get("attempt_id"))
        config_keys = ("protocol", "runtime_id", "model_path", "base_model_path", "patch_manifest", "runtime_receipt", "max_actions")
        v.check("restart.same_recorded_configuration", None if any(x.get(k) is None or y.get(k) is None for k in config_keys)
                else all(x[k] == y[k] for k in config_keys))
        v.check("restart.same_episode_normal_initialization", all(ae.get(k) == be.get(k) for k in
                ("episode_id", "map_name", "instruction", "initial_reference_state", "target_position")) and one(b["events"], "scene.connected") is not None)
        if sa["supervisor"] and sb["supervisor"]:
            first, second = sa["supervisor"].get("process_identity_at_spawn"), sb["supervisor"].get("process_identity_at_spawn")
            fields = ("boot_id", "pid", "starttime_ticks")
            v.check("restart.fresh_process_identity", None if not isinstance(first, dict) or not isinstance(second, dict) or any(k not in first or k not in second for k in fields)
                    else any(first[k] != second[k] for k in fields) and second.get("pid") == y.get("process_id"))
        if sa["session"] and sb["session"]:
            try:
                v.check("restart.after_prior_session_finished", nav.instant(sb["session"].get("started_at_utc")) >= nav.instant(sa["session"].get("finished_at_utc")))
            except ValueError as exc:
                v.check("restart.after_prior_session_finished", None, str(exc))
    inventory = getattr(options, "transfer_inventory", None)
    if inventory:
        inventory_root = Path(options.transfer_root).resolve()
        try:
            v.record(inventory)
            entries = {}
            for line in Path(inventory).read_text().splitlines():
                match = re.fullmatch(r"([a-f0-9]{64})  (.+)", line)
                if not match:
                    raise ValueError("Expected sha256sum lines with relative paths")
                path = nav.strict_relative(inventory_root, match[2])
                if str(path) in entries:
                    raise ValueError("Duplicate inventory member")
                entries[str(path)] = match[1]
                actual = v.record(path)
                v.check("transfer." + match[2], actual["sha256"] == match[1])
            required = {name for name in v.files if any(Path(name).is_relative_to(root) for root in roots)}
            v.check("transfer.covers_consumed_evidence", required <= set(entries), sorted(required - set(entries)))
        except FileNotFoundError as exc:
            v.check("transfer.available", None, str(exc))
        except (OSError, ValueError) as exc:
            v.check("transfer.readable_and_mapped", False, str(exc))
    changed = sorted(v.changed_during_reads | {name for name, item in v.files.items() if not Path(name).exists() or nav.sha256(name) != item["sha256"]})
    v.check("sources_unchanged_during_validation", not changed, changed)
    states = {c["status"] for c in v.checks}
    return {"schema_version": "vla.restart-validation.v1", "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "status": "failed" if "fail" in states else "unknown" if "unknown" in states else "passed", "checks": v.checks,
            "inputs": list(v.files.values()), "validator_sha256": nav.sha256(__file__), "causal_validator_sha256": nav.sha256(nav.__file__),
            "interrupted_completed_actions": len(a.get("actions", [])) if a.get("events") is not None else None,
            "interrupted_pending_tail": a.get("pending_tail"), "restart_completed_actions": len(b.get("actions", [])) if b.get("events") is not None else None,
            "interrupted_navigation_score": None,
            "limitations": ["Retrospective recorded evidence only; no live process inventory or signaling.",
                "Event-prefix check and signal delivery are not atomic; pending tail is retained.",
                "Recorded process/group/ancestry cleanup cannot exclude unsampled escaped descendants.",
                "Image hashes/links are checked; visual replay and recording-overhead measurement are separate P07 requirements.",
                "Recorded runtime/model identity does not rehash remote weights or establish identical physics state.",
                "Fresh normal initialization is not exact state resumption or learned flight recovery."]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("interrupted-evidence", "interrupted-session", "interruption", "restart-evidence", "restart-session"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--expected-runtime-id", required=True)
    p.add_argument("--expected-completed-actions", type=int, default=2)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--transfer-inventory", type=Path, help="Optional independent sha256sum file from the source host")
    p.add_argument("--transfer-root", type=Path, help="Explicit local root for inventory-relative paths; no historical path rewriting")
    o = p.parse_args()
    source_roots = (o.interrupted_evidence, o.interrupted_session, o.interruption, o.restart_evidence, o.restart_session)
    if (bool(o.transfer_inventory) != bool(o.transfer_root) or o.expected_completed_actions < 1 or not o.expected_runtime_id or o.output.exists() or
            any(o.output.resolve().is_relative_to(root.resolve()) for root in source_roots)):
        p.error("Use a positive count, frozen runtime ID and new output path")
    result = validate(o)
    o.output.parent.mkdir(parents=True, exist_ok=True)
    with o.output.open("x") as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"status": result["status"], "checks": len(result["checks"]), "output": str(o.output.resolve())}))
    return 0 if result["status"] == "passed" else 2 if result["status"] == "unknown" else 1


if __name__ == "__main__":
    raise SystemExit(main())
