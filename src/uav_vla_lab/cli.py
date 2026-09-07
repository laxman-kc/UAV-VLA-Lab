"""One CLI, with lightweight core commands and lazy research workflows."""

from __future__ import annotations

import argparse
from importlib import resources, util
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import sys

from . import __version__
from .config import ContractError


def _emit(value):
    print(json.dumps(value, indent=2, allow_nan=False))


def doctor(args):
    optional = {}
    for name in ("torch", "transformers", "peft", "airsim", "PIL"):
        # Presence is not an import, CUDA, ABI, model, rendering or simulator test.
        try:
            optional[name] = util.find_spec(name) is not None
        except (ImportError, ValueError):
            optional[name] = False
    try:
        installed = version("uav-vla-lab")
    except PackageNotFoundError:
        installed = None
    result = {"schema_version": "vla.core-doctor.v1", "status": "ready" if sys.version_info >= (3, 10) else "unsupported_python",
              "core": {"python": platform.python_version(), "platform": sys.platform,
                       "package_version": __version__, "installed_distribution_version": installed},
              "optional_module_presence": optional,
              "scope": "CPU core only. Optional modules were located, not imported or validated; GPU, assets and simulator readiness are not checked."}
    if args.json:
        _emit(result)
    else:
        print(f"CPU core: {result['status']} — UAV-VLA-Lab {__version__}, Python {platform.python_version()}")
        print(result["scope"])
    return 0 if result["status"] == "ready" else 1


def replay_command(args):
    from .replay import run_replay
    result = run_replay(args.input, args.output)
    _emit({**result, "report": str((Path(args.output) / "report.html").resolve())})
    return 0


def demo_command(args):
    from .replay import run_replay
    resource = resources.files("uav_vla_lab").joinpath("data/synthetic-replay.json")
    with resources.as_file(resource) as fixture:
        result = run_replay(fixture, args.output)
    _emit({**result, "report": str((Path(args.output) / "report.html").resolve())})
    return 0


def verify_command(args):
    from .replay import verify_bundle
    result = verify_bundle(args.bundle)
    _emit({**result, "report": str((Path(args.bundle) / "report.html").resolve())})
    return 0


def parser():
    result = argparse.ArgumentParser(prog="uav-vla", description="UAV-VLA-Lab research workflows. Core commands require no GPU or simulator.")
    result.add_argument("--version", action="version", version=f"uav-vla {__version__}")
    commands = result.add_subparsers(dest="command", required=True)
    command = commands.add_parser("doctor", help="Inspect CPU core and optional module presence without loading models")
    command.add_argument("--json", action="store_true", help="Print the machine-readable diagnostic")
    command.set_defaults(func=doctor)
    command = commands.add_parser("demo", help="Replay the bundled synthetic CPU example and build its report")
    command.add_argument("--output", type=Path, required=True, help="New output directory; existing attempts are never overwritten")
    command.set_defaults(func=demo_command)
    command = commands.add_parser("replay", help="Replay a vla.synthetic-replay.v1 JSON input (not a simulator trace)")
    command.add_argument("input", type=Path)
    command.add_argument("--output", type=Path, required=True)
    command.set_defaults(func=replay_command)
    command = commands.add_parser("verify", help="Check replay bundle integrity and recompute its synthetic semantics")
    command.add_argument("bundle", type=Path)
    command.set_defaults(func=verify_command)
    if util.find_spec("uav_vla_lab.workflows") is not None:
        from .workflows import register_commands
        register_commands(commands)
    return result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv and util.find_spec("uav_vla_lab.workflows") is not None:
            from .workflows import dispatch, handles
            if handles(argv[0]):
                return dispatch(argv)
        args = parser().parse_args(argv)
        return args.func(args)
    except (ValueError, OSError) as exc:
        print(f"uav-vla: {exc}", file=sys.stderr)
        return 2
