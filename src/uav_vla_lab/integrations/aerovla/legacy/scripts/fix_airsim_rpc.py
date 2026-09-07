#!/usr/bin/env python3
"""Apply the pinned AeroVLA RPC troubleshooting repair in an isolated venv.

Run only after all simulator/model jobs using this environment have stopped.
The original reference run and package freeze must be preserved separately.
"""
import argparse
import datetime
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

ZIP_SHA = "c0d7df3fe91271ea052384ca7150c7f6730eeed63672168d08a0f27946322197"
GUIDE_SHA = "88cfd77f284cee8166ec972cc74bc0950482e07ebdaa114ea6a8435ffa772c4c"
OLD = "self.client = msgpackrpc.Client(msgpackrpc.Address(ip, port), timeout = timeout_value, pack_encoding = 'utf-8', unpack_encoding = 'utf-8')"
NEW = "self.client = msgpackrpc.Client(msgpackrpc.Address(ip, port), timeout = timeout_value)"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sys.prefix == sys.base_prefix:
        raise SystemExit("Refusing to change a non-venv interpreter")
    archive = args.upstream.resolve() / "msgpack-rpc-python-fix-msgpack-dep.zip"
    guide = args.upstream.resolve() / "docs/assets/troubleshooting.md"
    if sha(archive) != ZIP_SHA or sha(guide) != GUIDE_SHA:
        raise SystemExit("RPC repair archive or guide differs from the reviewed pinned source")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": "vla.rpc-repair.v1", "status": "running",
              "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "interpreter": sys.executable, "archive_sha256": ZIP_SHA, "guide_sha256": GUIDE_SHA,
              "runtime_id": "aerovla-official-rpcfix-msgpack112-v1", "commands": [],
              "scope": "Published dependency/encoding repair; no change to clocks, reset, controller, parser or model weights",
              "deviation_from_guide": "Use --no-deps for fixed RPC and AirSim installs to preserve already validated pinned dependencies; install msgpack 1.1.2 explicitly"}
    def save():
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    def run(name, argv):
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=600)
        log = args.output / (name + ".log")
        log.write_text(result.stdout)
        report["commands"].append({"name": name, "argv": argv, "returncode": result.returncode,
                                   "log": log.name, "sha256": sha(log)})
        save()
        if result.returncode:
            raise RuntimeError(f"{name} failed; see retained log")
    pip = [sys.executable, "-m", "pip"]
    save()
    try:
        run("freeze-before", pip + ["freeze"])
        distribution = importlib.metadata.distribution("airsim")
        old_client = Path(distribution.locate_file("airsim/client.py"))
        report["original_client_sha256"] = sha(old_client)
        (args.output / "airsim-client.before.py").write_bytes(old_client.read_bytes())
        run("uninstall", pip + ["uninstall", "-y", "msgpack-python", "msgpack", "msgpack-rpc-python", "airsim", "tornado"])
        run("install-tornado", pip + ["install", "tornado==4.5.3"])
        run("install-fixed-rpc", pip + ["install", "--no-deps", str(archive)])
        run("install-airsim", pip + ["install", "--no-deps", "--no-build-isolation", "airsim==1.8.1"])
        run("install-msgpack", pip + ["install", "--force-reinstall", "msgpack==1.1.2"])
        client = Path(importlib.metadata.distribution("airsim").locate_file("airsim/client.py"))
        source = client.read_text()
        if source.count(OLD) != 1:
            raise RuntimeError("Installed AirSim client does not contain exactly the reviewed encoding line")
        revised = source.replace(OLD, NEW)
        compile(revised, str(client), "exec")
        client.write_text(revised)
        report["client_patch"] = {"file": str(client), "before_sha256": hashlib.sha256(source.encode()).hexdigest(),
                                  "after_sha256": sha(client), "removed": OLD, "replacement": NEW}
        (args.output / "airsim-client.after.py").write_bytes(client.read_bytes())
        run("pip-check", pip + ["check"])
        run("imports", [sys.executable, "-c", "import json,airsim,msgpack,msgpackrpc,tornado; assert msgpack.__version__=='1.1.2'; assert msgpack.Packer.__module__=='msgpack._cmsgpack'; print(json.dumps({'msgpack':msgpack.__version__,'packer':msgpack.Packer.__module__,'airsim_import':True,'msgpackrpc_import':True,'tornado':tornado.version}))"])
        run("freeze-after", pip + ["freeze"])
        report["status"] = "passed"
        report["limitation"] = "Import/dependency checks passed; actual RPC latency and simulator behavior require a new measured run"
    except BaseException as exc:
        report["status"] = "failed"
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        report["finished_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save()
    print(json.dumps({"status": report["status"], "report": str(args.output / 'report.json')}))


if __name__ == "__main__":
    main()
