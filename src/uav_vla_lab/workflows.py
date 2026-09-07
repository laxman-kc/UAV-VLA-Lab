"""Lazy installed workflows; GPU libraries load only in an invoked GPU runner."""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import subprocess

from .integrations.aerovla import compat

GROUPS = {
    "runtime": {"inventory": "host_probe", "probe": "runtime_probe", "repair-rpc": "fix_airsim_rpc", "session": "run_simulation_session", "supervise": "supervise_run", "interrupt": "interrupt_after_event"},
    "integration": {"patch": "patch_aerovla_runtime", "probe": "simulator_probe", "offline": "offline_policy_probe", "reset-diagnostic": "reset_diagnostic"},
    "dataset": {"assets": "prepare_assets", "download": "download_assets", "episode": "prepare_aerovla_episode", "batch": "prepare_evaluation_batch", "audit-published": "audit_published_training", "reference": "prepare_published_reference", "extension": "prepare_reference_extension", "alignment": "audit_reference_alignment", "reviewed": "build_reviewed_reference_dataset"},
    "evaluate": {"compare": "compare_navigation", "restart": "validate_restart"},
    "report": {"build": "build_release", "paired": "prepare_paired_video", "amended-paired": "prepare_amended_paired_video"},
    "workflow": {"development": "prepare_development_comparison", "holdout": "prepare_holdout_comparison", "amend-unstarted": "prepare_unstarted_session_amendment"},
}
NATIVE = {("runtime", "env"): "runtime.environment", ("runtime", "freeze"): "runtime.freeze",
          ("dataset", "snapshot"): "datasets.snapshots", ("evaluate", "summarize"): "evaluation.navigation",
          ("evaluate", "baseline"): "evaluation.analyze_baseline"}
ALIASES = {"assets": ("dataset", "assets"), "simulate": ("runtime", "session"), "compare": ("evaluate", "compare")}


def handles(command: str) -> bool:
    return command in {*GROUPS, *ALIASES, "train", "legacy"}


def register_commands(subparsers) -> None:
    descriptions = {"assets": "Verify/convert pinned asset metadata", "simulate": "Run an owned, bounded simulator session",
                    "train": "Validate or execute continued-adapter training", "compare": "Validate paired checkpoint comparisons",
                    "legacy": "Explicit historical source compatibility commands"}
    for name in [*GROUPS, *ALIASES, "train", "legacy"]:
        parser = subparsers.add_parser(name, add_help=False, help=descriptions.get(name, "Installed " + name + " workflows"))
        parser.add_argument("arguments", nargs=argparse.REMAINDER)
        parser.set_defaults(func=lambda args, command=name: dispatch([command, *args.arguments]))


def _group_help(group: str) -> int:
    names = set(GROUPS[group]) | {name for owner, name in NATIVE if owner == group}
    if group == "runtime":
        names.update(("bootstrap", "activate", "extract-simulator"))
    if group == "dataset":
        names.add("intent")
    print("usage: uav-vla " + group + " COMMAND [arguments]\n\nCommands: " + ", ".join(sorted(names)))
    print("Use COMMAND --help for its exact contract. Compatibility commands retain historical source hashes and scientific behavior.")
    return 0


def dispatch(argv: list[str]) -> int:
    command, *rest = argv
    if command in ALIASES:
        return dispatch([*ALIASES[command], *rest])
    if command == "train":
        from .training.runner import main
        return main(rest)
    if command == "legacy":
        if not rest or rest[0] in ("list", "--help", "-h"):
            manifest = compat.verify_snapshot()
            print(json.dumps({"scope": "Historical source compatibility, not an assertion of current host readiness", "scripts": [r["path"] for r in manifest["files"] if r["path"].endswith(".py")]}, indent=2))
            return 0
        if rest[0] != "run" or len(rest) < 2:
            raise ValueError("Use uav-vla legacy run SCRIPT_BASENAME [arguments]")
        return compat.run(rest[1], rest[2:])
    if command not in GROUPS:
        raise ValueError("Unknown workflow command: " + command)
    if not rest or rest[0] in ("--help", "-h"):
        return _group_help(command)
    action, *arguments = rest
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    if command == "dataset" and action == "intent":
        parser = argparse.ArgumentParser(description="Print the installed pinned model/asset intent path; no download")
        parser.add_argument("name", choices=("models", "map"))
        selected = parser.parse_args(arguments)
        filename = "released_models_v1.json" if selected.name == "models" else "modern_city_map.json"
        print(Path(__file__).parent / "datasets/resources" / filename)
        return 0
    native = NATIVE.get((command, action))
    if native:
        return importlib.import_module("uav_vla_lab." + native).main(arguments)
    if command == "runtime" and action in ("bootstrap", "activate", "extract-simulator"):
        if action == "activate":
            parser = argparse.ArgumentParser(description='Print the activation script; source its path from bash with VLA_DATA_ROOT exported.')
            parser.add_argument("--print-path", action="store_true", required=True)
            parser.parse_args(arguments)
            print(Path(__file__).parent / "runtime/resources/activate.sh")
            return 0
        name = {"bootstrap": "bootstrap.sh", "activate": "activate.sh", "extract-simulator": "extract_simulator.sh"}[action]
        script = Path(__file__).parent / "runtime/resources" / name
        return subprocess.call(["bash", str(script), *arguments])
    script = GROUPS[command].get(action)
    if script is None:
        raise ValueError("Unknown " + command + " workflow: " + action)
    return compat.run(script, arguments)
