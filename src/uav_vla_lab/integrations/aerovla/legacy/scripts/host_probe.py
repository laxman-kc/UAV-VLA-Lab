#!/usr/bin/env python3
"""Collect bounded, credential-free Linux host readiness evidence."""
import argparse
import datetime
import json
import os
import pathlib
import platform
import shutil
import subprocess


def command(args):
    try:
        p = subprocess.run(args, text=True, capture_output=True, timeout=30)
        return {"argv": args, "returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"argv": args, "returncode": None, "error": str(exc)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--data-root", required=True)
    args = parser.parse_args()
    data_root = pathlib.Path(args.data_root)
    data_root.mkdir(parents=True, exist_ok=True)
    commands = {
        "gpu": ["nvidia-smi", "--query-gpu=name,uuid,memory.total,memory.free,driver_version", "--format=csv,noheader"],
        "cpu": ["lscpu"],
        "memory": ["free", "-b"],
        "filesystem": ["findmnt", "-T", str(data_root), "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"],
        "python": ["python3", "--version"],
        "cuda_toolkit": ["nvcc", "--version"],
        "graphics_libraries": ["bash", "-lc", "ldconfig -p | rg 'lib(vulkan|EGL|GLX|nvidia|GL\\.so)'"],
        "ffmpeg": ["ffmpeg", "-version"],
        "sudo_noninteractive": ["sudo", "-n", "true"],
    }
    raw = {}
    for path in ["/etc/os-release", "/proc/meminfo", "/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/cpu.max"]:
        p = pathlib.Path(path)
        raw[path] = p.read_text() if p.exists() else None
    disk = shutil.disk_usage(data_root)
    inventory = {
        "recorded_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "platform": platform.platform(), "architecture": platform.machine(),
        "cpu_count": os.cpu_count(), "cpu_affinity_count": len(os.sched_getaffinity(0)),
        "data_root": str(data_root.resolve()),
        "disk_bytes": {"total": disk.total, "used": disk.used, "free": disk.free},
        "raw_system_files": raw,
        "checks": {name: command(argv) for name, argv in commands.items()},
        "persistence": {"backing_mount_observed": True, "stop_resume_tested": False,
                        "note": "Filesystem inventory is not a lifecycle persistence test."},
    }
    out = pathlib.Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(inventory, indent=2) + "\n")
    print(json.dumps(inventory, indent=2))


if __name__ == "__main__":
    main()
