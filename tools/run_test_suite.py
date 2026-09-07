#!/usr/bin/env python3
"""Run required CPU/media contracts, retaining a machine-readable validation report."""
import argparse
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prerequisites = {name: bool(shutil.which(name)) for name in ("ffmpeg", "ffprobe", "lsof")}
    prerequisites["Pillow"] = importlib.util.find_spec("PIL") is not None
    if not all(prerequisites.values()):
        parser.error("Required test prerequisites missing: " + ", ".join(k for k,v in prerequisites.items() if not v))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    allowed = {"Real /proc identity requires Linux"} if sys.platform == "darwin" else set()
    unexpected = [(case.id(), reason) for case, reason in result.skipped if reason not in allowed]
    report = {"schema_version": "uav-vla-lab.test-report.v1", "python": platform.python_version(),
              "platform": sys.platform, "prerequisites": prerequisites, "tests_run": result.testsRun,
              "passed": result.testsRun - len(result.skipped) - len(result.failures) - len(result.errors),
              "failures": [case.id() for case,_ in result.failures], "errors": [case.id() for case,_ in result.errors],
              "skips": [{"test": case.id(), "reason": reason} for case,reason in result.skipped],
              "unexpected_skips": unexpected,
              "status": "passed" if result.wasSuccessful() and not unexpected else "failed",
              "scope": "CPU, media and synthetic lifecycle contracts; no real GPU, simulator or model execution"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["status"] == "passed" else 1

if __name__ == "__main__":
    raise SystemExit(main())
