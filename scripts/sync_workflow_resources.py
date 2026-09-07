#!/usr/bin/env python3
"""Check/generate installed compatibility resources and native extractions.

Retained historical Python scripts are the source of truth in this migration.
Native extraction rules below are reviewed deltas. Do not independently edit the
generated numerical engines. Root shell entrypoints forward to portable package
resources; obsolete host-specific shell files are not distributed in the snapshot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src/uav_vla_lab"


def generated_modules() -> dict[str, str]:
    nav = (ROOT / "scripts/summarize_navigation.py").read_text()
    nav = nav.replace("def main():", "def main(argv=None):").replace("parser.parse_args()", "parser.parse_args(argv)")
    base = (ROOT / "scripts/analyze_baseline.py").read_text()
    base = base.replace("import summarize_navigation as nav", "from . import navigation as nav")
    dependency_hashes = {"navigation.py": hashlib.sha256(nav.encode()).hexdigest(),
                         "context.py": hashlib.sha256((PACKAGE / "evaluation/context.py").read_bytes()).hexdigest()}
    base = base.replace('PROTOCOL = "paused-final-pose-time-v1"', 'NATIVE_DEPENDENCY_SHA256 = ' + repr(dependency_hashes) + '\n\nPROTOCOL = "paused-final-pose-time-v1"')
    base = base.replace('def analyze(args):\n', 'def analyze(args):\n    for dependency, expected in NATIVE_DEPENDENCY_SHA256.items():\n        if sha256(Path(__file__).with_name(dependency)) != expected:\n            raise ValueError("Native analyzer dependency differs from hash-bound source: " + dependency)\n')
    base = base.replace("P08 analysis requires", "Reset analysis requires")
    base = base.replace("# Only declared development session and run roots; no dataset/holdout traversal.", "# Only declared session and run roots; no dataset traversal.")
    base = base.replace("def main():", "def main(argv=None):").replace("args = parser.parse_args()", "args = parser.parse_args(argv)")
    base = base.replace("    limitations = [\n", '    from .context import evaluation_context, scope_limitations\n    context = evaluation_context(plan, getattr(args, "role", "unspecified"), getattr(args, "split", None))\n    limitations = scope_limitations(context) + [\n', 1)
    old_scope = ["Descriptive evaluation of the frozen development missions in one map under a named changed-reset protocol; not a reproduction of the untouched released evaluator.",
                 "Released model weights are unchanged. No trained candidate, improvement, causal comparison or unseen-scene claim.",
                 "The development split is project-defined; overlap with the released model's prior training is unresolved. These missions are not established as unseen to that model."]
    for line in old_scope:
        needle = '        "' + line + '",\n'
        assert needle in base, "Historical context changed; review the extraction rule"
        base = base.replace(needle, "")
    base = base.replace("No holdout pixels are loaded. Video selections are editorial static samples under the frozen execution-order rule; the complete trace remains in source evidence.",
                        "This analysis reads metadata and events, not image pixels. Its video-selection.json is a descriptive execution-order suggestion; it does not replace a separately frozen paired editorial rule.")
    base = base.replace('"plan_id": plan["plan_id"], "plan_sha256":', '"evaluation_context": context, "plan_id": plan["plan_id"], "plan_sha256":')
    base = base.replace('    result = {"schema_version": "vla.baseline-reset-analysis.v1",',
                        '    from . import context as context_module\n    implementation_files = [sources.record(p) for p in (Path(__file__), Path(nav.__file__), Path(context_module.__file__))]\n    implementation = {"engine": "uav-vla.native-analysis.v1", "source_files": implementation_files, "scope": "Generated native numerical engine with explicit role/split prose; these are actual new source hashes, never historical analyzer hashes."}\n    result = {"implementation": implementation, "schema_version": "vla.baseline-reset-analysis.v1",')
    base = base.replace('    lines = ["# Development baseline with independently audited reset evidence", "",',
                        '    context = result.get("evaluation_context", {"split": "unspecified", "role": "unspecified"})\n    lines = [f"# {context[\'split\'].capitalize()} {context[\'role\']} evaluation with audited reset evidence", "",')
    base = base.replace('    args = parser.parse_args(argv)', '    parser.add_argument("--role", choices=("original", "candidate", "unspecified"), default="unspecified")\n    parser.add_argument("--split", choices=("demo", "development", "holdout"), help="Must match any frozen split declaration; otherwise retained as caller display context")\n    args = parser.parse_args(argv)')
    trainer = (ROOT / "scripts/train_adapter_mvp.py").read_text()
    contract_start = trainer.index("class ContractError")
    contract_end = trainer.index("def load_reference_contract")
    contract = ('"""Generated standard-library reviewed-dataset contract; no labels are created.\n\nSource: scripts/train_adapter_mvp.py. Regenerate with sync_workflow_resources.py.\n"""\nfrom __future__ import annotations\nimport datetime as dt\nimport hashlib\nimport json\nimport math\nfrom pathlib import Path, PurePosixPath\n\n'
                + trainer[trainer.index("LABEL_BOUNDS ="):contract_end])
    imports = "from uav_vla_lab.datasets import reviewed as dataset_contract\nfrom uav_vla_lab.datasets.reviewed import (ContractError, now, read_json, write_json, digest, canonical_hash, file_record, contained, verify_record, require_text, validate_dataset)\n\n\n"
    trainer = trainer[:contract_start] + imports + trainer[contract_end:]
    trainer = trainer.replace('Path(__file__).with_name("prepare_published_reference.py")', 'legacy_script("prepare_published_reference")')
    trainer = trainer.replace("import traceback\n", "import traceback\n\nfrom uav_vla_lab.integrations.aerovla.compat import legacy_script\n")
    trainer = trainer.replace('"runner": file_record(__file__), "upstream":', '"runner": file_record(__file__), "dataset_contract": file_record(dataset_contract.__file__), "upstream":')
    return {"evaluation/navigation.py": nav, "evaluation/analyze_baseline.py": base, "training/runner.py": trainer, "datasets/reviewed.py": contract}


def expected_files() -> dict[Path, bytes]:
    legacy = PACKAGE / "integrations/aerovla/legacy"
    manifest = json.loads((legacy / "snapshot.json").read_text())
    result = {}
    for record in manifest["files"]:
        relative = record["path"]
        if relative.endswith(".sh"):
            raise ValueError("Obsolete shell entrypoints must not be included in the compatibility snapshot")
        data = (ROOT / relative).read_bytes()
        result[legacy / relative] = data
        if hashlib.sha256(data).hexdigest() != record["sha256"] or len(data) != record["bytes"]:
            raise ValueError("Frozen historical source changed: " + relative + "; use a new explicitly versioned integration")
    for relative, data in generated_modules().items():
        compile(data, relative, "exec")
        result[PACKAGE / relative] = data.encode()
    result[PACKAGE / "runtime/resources/requirements-locked.txt"] = (ROOT / "environments/aerovla-linux-cu118/requirements-locked.txt").read_bytes()
    for name in ("released_models_v1.json", "modern_city_map.json"):
        result[PACKAGE / "datasets/resources" / name] = (ROOT / "configs/assets" / name).read_bytes()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    differences = []
    for destination, data in expected_files().items():
        if args.check:
            if not destination.exists() or destination.read_bytes() != data:
                differences.append(str(destination.relative_to(ROOT)))
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
    if differences:
        raise SystemExit("Generated workflow sources differ: " + ", ".join(differences))
    print("Workflow sources/resources checked" if args.check else "Workflow sources/resources regenerated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
