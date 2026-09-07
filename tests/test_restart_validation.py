"""Synthetic files test P07 validation; no simulator or signal is executed."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import validate_restart as validator


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n")


def lines(path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in events))


def record(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}


def identity(pid):
    return {"pid": pid, "pgid": pid, "session_id": pid, "starttime_ticks": pid * 10,
            "boot_id": "synthetic-boot", "uid": 99, "argv": ["python", "eval.py"], "cwd": "/fixture", "exe": "/python"}


def navigation(root, pid, interrupted):
    events, attempt = [], f"attempt-{pid}"
    def emit(kind, **data):
        event = {"schema_version": 1, "event_id": len(events) + 1, "event_type": kind,
                 "run_id": f"run-{pid}", "host_monotonic_ns": (len(events) + 1) * 10,
                 "wall_time_utc": "2026-09-07T01:00:00+00:00"}
        if events:
            event.update(attempt_id=attempt, episode_id="episode", map_name="map")
        event.update(data)
        events.append(event)
        return event
    start = emit("run.start", process_id=pid, protocol=validator.nav.PROTOCOL, runtime_id="fixture-runtime",
                 model_path="/model", base_model_path="/base", patch_manifest={"source": "fixture"},
                 runtime_receipt={"sha256": "fixture-only"}, max_actions=2, argv=["eval.py"])
    episode = emit("episode.start", instruction="fixture", initial_reference_state={"position": [0, 0, 0]},
                   target_position=[10, 0, 0], source_json="/source")
    emit("scene.connected")
    previous = None
    for step in range(2 if interrupted else 3):
        capture = emit("images.received", command_event_id=previous, responses=[{"time_stamp": 100}] * 10)
        images = []
        for camera in ("front", "down"):
            path = root / "observations" / attempt / f"{step}-{camera}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic hash fixture; not a decoded image")
            images.append({"path": str(path.relative_to(root)), "sha256": record(path)["sha256"], "camera": camera, "modality": "rgb"})
        observation = emit("observation.prepared", image_capture_event_id=capture["event_id"], images=images)
        if step == 2:
            break
        emit("prompt.prepared", observation_event_id=observation["event_id"], exact_prompt=["fixture"])
        generation = emit("policy.generated", observation_event_id=observation["event_id"], token_ids=[[1]], raw_text=["fixture"])
        actions = [{"fwd": 1.0, "down": 0.0, "yaw": 0.0}]
        emit("policy.decoded", observation_event_id=observation["event_id"], policy_event_id=generation["event_id"],
             upstream_actions=actions, upstream_stop_flags=[False])
        requested = emit("action.requested", observation_event_id=observation["event_id"],
                         policy_event_id=generation["event_id"], actions=actions)
        emit("action.completed", command_event_id=requested["event_id"], endpoint_states=[[{}]])
        previous = requested["event_id"]
    prefix = b"".join((json.dumps(e) + "\n").encode() for e in events)
    if interrupted:
        outcome = {"attempt_id": attempt, "episode_id": "episode", "map_name": "map", "status": "interrupted",
                   "error_type": "KeyboardInterrupt", "error": ""}
        emit("episode.interrupted", **outcome)
        write(root / "partial" / f"{attempt}.json", outcome)
    else:
        outcome = {"attempt_id": attempt, "episode_id": "episode", "map_name": "map", "status": "completed", "step": 2,
                   "upstream_flags": {"success": False, "oracle_success": False, "collisions": False, "early_end": False, "dones": True, "predict_dones": False},
                   "termination_reason": "step_limit_or_other_done", "distance_to_target_m": 10, "stuck_counter": 0}
        emit("episode.completed", **outcome)
        write(root / "outcomes" / f"{attempt}.json", outcome)
    emit("cleanup.scenes_closed")
    emit("run.end", status="interrupted" if interrupted else "completed", cleanup_errors=[],
         error_type="KeyboardInterrupt" if interrupted else None)
    lines(root / "events.jsonl", events)
    return events, prefix, start, episode


def session(root, pid, interrupted):
    code, status = (130, "exited_with_error") if interrupted else (0, "exited_successfully")
    ident = identity(pid)
    se = [{"event": "run.starting", "argv": ident["argv"], "cwd": ident["cwd"]},
          {"event": "process.spawned", "pid": pid, "pgid": pid, "root_process_alive": True,
           "process_identity": ident, "identity_error": None},
          {"event": "process.finished", "child_returncode": code, "root_process_alive": False, "process_group_exists": False},
          {"event": "run.finished", "status": status, "supervisor_exit_code": code}]
    lines(root / "command/events.jsonl", se)
    for name in ("stdout", "stderr"):
        (root / "command" / (name + ".log")).write_bytes(b"")
    sup = {"process_identity_at_spawn": ident, "root_process_alive_at_end": False, "process_group_exists_at_end": False,
           "termination_reason": "natural_exit", "child_returncode": code, "supervisor_exit_code": code, "status": status,
           "signals_sent": [], **{name: record(root / "command" / (name + (".jsonl" if name == "events" else ".log"))) for name in ("stdout", "stderr", "events")}}
    write(root / "command/report.json", sup)
    cleanup = {"complete": True, "manager_group_visible": False, "inspection_succeeded": True, "errors": [], "signals": [],
               "final_process_evidence": {"processes": [], "escaped_observed_descendants": []}, "manager_returncode": -15}
    lines(root / "lifecycle.jsonl", [{"event": "manager.cleanup", **cleanup}])
    report = {"cleanup": cleanup, "status": "command_failed" if interrupted else "command_succeeded",
              "manager_pid": pid + 1, "manager_pgid": pid + 1, "readiness": {"tcp_accepted": True, "listener_pids": [pid + 1]},
              "session_returncode": code, "command_child_returncode": code, "command_supervisor_returncode": code,
              "started_at_utc": "2026-09-07T01:00:00Z" if interrupted else "2026-09-07T01:02:00Z",
              "finished_at_utc": "2026-09-07T01:01:00Z" if interrupted else "2026-09-07T01:03:00Z",
              "artifacts": [record(p) for p in sorted(root.rglob("*")) if p.is_file()]}
    write(root / "report.json", report)
    prefix = b"".join((json.dumps(e) + "\n").encode() for e in se[:2])
    return se, prefix


def prefix_record(data):
    return {"bytes_read": len(data), "sha256_of_bytes_read": hashlib.sha256(data).hexdigest(),
            "unfinished_line_bytes": 0, "complete_lines_read": len(data.splitlines())}


class RestartValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        r = Path(self.tmp.name)
        self.o = SimpleNamespace(interrupted_evidence=r / "interrupted", restart_evidence=r / "restart",
            interrupted_session=r / "first-session", restart_session=r / "second-session", interruption=r / "helper",
            expected_runtime_id="fixture-runtime", expected_completed_actions=2)
        events, prefix, start, episode = navigation(self.o.interrupted_evidence, 101, True)
        navigation(self.o.restart_evidence, 201, False)
        se, sprefix = session(self.o.interrupted_session, 101, True)
        session(self.o.restart_session, 201, False)
        trigger = [e for e in events if e["event_type"] == "action.completed"][-1]
        request = {"function": "os.killpg", "pgid": 101, "signal": "SIGINT", "signal_number": 2,
                   "host_monotonic_ns": trigger["host_monotonic_ns"] + 1, "utc": "2026-09-07T01:00:00Z"}
        helper = {"status": "sigint_requested", "dry_run": False, "signal_attempted": True, "signal_count": 1,
                  "signal_result": "kernel_accepted_request", "event_type": "action.completed", "after_count": 2,
                  "observed_trigger_count": 2, "trigger": trigger, "expected_runtime_id": "fixture-runtime",
                  "navigation_evidence_prefix": prefix_record(prefix), "supervisor_evidence_prefix": prefix_record(sprefix),
                  "verified_identity": identity(101), "final_identity_check": identity(101), "signal_request": request,
                  "recorded_navigation_run_start": start, "recorded_episode_start": episode,
                  "supervisor_starting": se[0], "supervisor_spawned": se[1]}
        write(self.o.interruption / "report.json", helper)
        lines(self.o.interruption / "events.jsonl", [{"event": "signal.requested", **request}])
        write(self.o.interruption / "checksums.json", {n: record(self.o.interruption / n)["sha256"] for n in ("report.json", "events.jsonl")})

    def tearDown(self):
        self.tmp.cleanup()

    def check_status(self, result, identifier):
        return next(c["status"] for c in result["checks"] if c["id"] == identifier)

    def test_full_synthetic_evidence_passes_without_signaling(self):
        r = validator.validate(self.o)
        self.assertEqual(r["status"], "passed", [c for c in r["checks"] if c["status"] != "pass"])
        self.assertEqual(r["interrupted_completed_actions"], 2)
        self.assertIsNone(r["interrupted_navigation_score"])

    def test_accepted_helper_without_partial_stays_unknown(self):
        next((self.o.interrupted_evidence / "partial").glob("*.json")).unlink()
        self.assertEqual(validator.validate(self.o)["status"], "unknown")

    def test_visible_command_group_fails_even_with_exit_130(self):
        p = self.o.interrupted_session / "command/report.json"
        r = json.loads(p.read_text()); r["process_group_exists_at_end"] = True; write(p, r)
        result = validator.validate(self.o)
        self.assertEqual(self.check_status(result, "interrupted.command_cleanup"), "fail")

    def test_wrong_prefix_hash_fails(self):
        p = self.o.interruption / "report.json"
        r = json.loads(p.read_text()); r["navigation_evidence_prefix"]["sha256_of_bytes_read"] = "0" * 64; write(p, r)
        self.assertEqual(self.check_status(validator.validate(self.o), "helper.navigation_prefix"), "fail")

    def test_image_tampering_fails(self):
        next((self.o.restart_evidence / "observations").rglob("*.png")).write_bytes(b"changed")
        self.assertEqual(self.check_status(validator.validate(self.o), "restart.image_integrity"), "fail")

    def test_reused_process_identity_fails(self):
        p = self.o.restart_session / "command/report.json"
        r = json.loads(p.read_text()); r["process_identity_at_spawn"] = identity(101); write(p, r)
        self.assertEqual(self.check_status(validator.validate(self.o), "restart.fresh_process_identity"), "fail")

    def test_different_declared_action_boundary_fails(self):
        self.o.expected_completed_actions = 3
        self.assertEqual(self.check_status(validator.validate(self.o), "interrupted.completed_action_scope"), "fail")

    def test_mutation_between_reads_is_retained(self):
        p = Path(self.tmp.name) / "source"
        p.write_text("first"); v = validator.Validation(); v.record(p)
        p.write_text("second"); v.record(p)
        self.assertIn(str(p.resolve()), v.changed_during_reads)

    def test_independent_transfer_inventory_uses_explicit_root(self):
        root = Path(self.tmp.name)
        manifest = root / "inventory.sha256"
        manifest.write_text("".join(record(p)["sha256"] + "  " + str(p.relative_to(root)) + "\n"
                                    for p in sorted(root.rglob("*")) if p.is_file()))
        self.o.transfer_inventory, self.o.transfer_root = manifest, root
        self.assertEqual(validator.validate(self.o)["status"], "passed")
        manifest.write_text(manifest.read_text().replace("  interrupted/", "  ../outside/", 1))
        self.assertEqual(validator.validate(self.o)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
