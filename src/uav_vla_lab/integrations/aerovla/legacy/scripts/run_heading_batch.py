#!/usr/bin/env python3
"""Run one frozen heading-collection phase serially, with no implicit retries.

Each sample has its own existing scene/session supervisor. This driver does not
approve candidate labels or turn process completion into an acceptance result.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def record(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def save(path, value):
    data = json.dumps(value, indent=2, allow_nan=False) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(data)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("P09", "P11"), required=True)
    for name in ("plan", "source-split", "split-manifest", "upstream", "dataset-root", "env-root", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--manager-port", type=int, default=30000)
    parser.add_argument("--command-timeout-seconds", type=int, default=150)
    options = parser.parse_args()
    if not 1024 <= options.manager_port <= 64535 or not 1 <= options.command_timeout_seconds <= 600:
        parser.error("Port or bounded per-sample command timeout is invalid")
    plan = json.loads(options.plan.read_text())
    samples = plan.get("samples", [])
    indices = [i for i, sample in enumerate(samples) if sample.get("phase") == options.phase]
    expected = list(range(5)) if options.phase == "P09" else list(range(5, 25))
    if plan.get("schema_version") != "vla.heading-correction-plan.v1" or len(samples) != 25 or indices != expected:
        parser.error("Phase must be the exact first-five or next-twenty frozen sample group")
    scripts = Path(__file__).resolve().parent
    source_records = [record(p) for p in (options.plan, options.source_split, options.split_manifest,
                     Path(__file__), scripts / "collect_heading_corrections.py", scripts / "run_simulation_session.py")]
    if source_records[1]["sha256"] != plan["source_split_sha256"] or source_records[2]["sha256"] != plan["split_manifest_sha256"]:
        parser.error("Plan source hashes do not match the supplied training metadata and split")
    options.output = options.output.resolve()
    options.output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": "vla.heading-collection-batch.v1", "phase": options.phase,
              "started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "status": "running",
              "planned_indices": indices, "sources": source_records, "attempts": [],
              "policy": "One invocation per planned sample, sequential fresh owned sessions, no retries or replacement. Label acceptance/review remains separate."}
    save(options.output / "batch.json", report)
    failure = None
    try:
        for index in indices:
            sample_output = options.output / f"sample-{index:02d}"
            session_output = options.output / f"sample-{index:02d}-session"
            command = [sys.executable, str(scripts / "run_simulation_session.py"),
                       "--upstream", str(options.upstream.resolve()),
                       "--env-root", str(options.env_root.resolve()),
                       "--cwd", str(options.upstream.resolve()), "--output", str(session_output),
                       "--manager-port", str(options.manager_port), "--gpus", "0",
                       "--readiness-timeout-seconds", "60", "--command-timeout-seconds", str(options.command_timeout_seconds),
                       "--poll-gpu", "--", sys.executable, str(scripts / "collect_heading_corrections.py"),
                       "--upstream", str(options.upstream.resolve()), "--dataset-root", str(options.dataset_root.resolve()),
                       "--source-split", str(options.source_split.resolve()), "--split-manifest", str(options.split_manifest.resolve()),
                       "--plan", str(options.plan.resolve()), "--sample-index", str(index),
                       "--output-dir", str(sample_output), "--simulator-port", str(options.manager_port),
                       "--gpu-id", "0", "--scene-manager-exclusive"]
            attempt = {"sample_index": index, "sample_id": samples[index]["sample_id"],
                       "started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "command": command,
                       "session_directory": str(session_output), "candidate_directory": str(sample_output)}
            report["attempts"].append(attempt)
            save(options.output / "batch.json", report)
            result = subprocess.run(command, check=False)
            attempt["returncode"] = result.returncode
            attempt["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
            session_report = session_output / "report.json"
            if session_report.is_file():
                attempt["session_report"] = record(session_report)
            save(options.output / "batch.json", report)
            print(json.dumps({"sample_index": index, "session_returncode": result.returncode,
                              "note": "Process return is not expert label approval"}), flush=True)
            # A failed/partial session needs an explicit audit before another
            # launch. Preserve every unstarted plan row; never retry implicitly.
            if result.returncode != 0:
                failure = f"Sample {index} session returned {result.returncode}; remaining samples not started"
                break
    except BaseException as exc:
        failure = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["status"] = "sessions_completed" if failure is None and len(report["attempts"]) == len(indices) else "partial"
        report["error"] = failure
        report["unstarted_indices"] = [i for i in indices if i not in {r["sample_index"] for r in report["attempts"]}]
        report["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        save(options.output / "batch.json", report)
    return 0 if report["status"] == "sessions_completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
