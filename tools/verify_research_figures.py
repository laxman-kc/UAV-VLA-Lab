"""Read-only integrity gate for the public study's recorded figure outputs.

This binds existing images to their declared source bytes; it does not authenticate
the author of a replaceable manifest or rerender the images to prove authorship.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from render_research_figures import DEFAULT_FIGURES, DEFAULT_STUDY, ROOT, read_json, validate

OUTPUTS = {f"{name}.{extension}" for name in ("outcome-rates", "paired-transitions", "training-fit")
           for extension in ("svg", "png", "pdf")}
REQUIRED_INPUTS = {"results/episodes.csv", "results/paired.csv", "results/training-steps.csv",
                   "dataset/membership.csv", "results/aggregate.json", "results/training-summary.json",
                   "configs/training.json", "configs/protocol.json", "configs/model-identities.json",
                   "source-catalog.json"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def contained_file(root, relative):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("Figure receipt requires a portable relative file path")
    parts = PurePosixPath(relative)
    if parts.is_absolute() or any(part in (".", "..", "") for part in relative.split("/")) or parts.as_posix() != relative:
        raise ValueError("Figure receipt path escapes its declared root")
    cursor = Path(root).resolve()
    for part in parts.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("Figure receipt may not follow a symlink")
    if not cursor.is_file():
        raise ValueError("Missing figure receipt member: " + relative)
    return cursor


def verify_inventory(root, records, expected_names, label):
    if not isinstance(records, list):
        raise ValueError(label + " inventory must be a list")
    names = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {"file", "bytes", "sha256"}:
            raise ValueError("Malformed " + label + " receipt")
        path = contained_file(root, record["file"])
        names.append(record["file"])
        if type(record["bytes"]) is not int or record["bytes"] <= 0 or not isinstance(record["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"]):
            raise ValueError("Invalid " + label + " size/hash receipt")
        if path.stat().st_size != record["bytes"] or digest(path) != record["sha256"]:
            raise ValueError(label + " bytes differ from figure provenance: " + record["file"])
    if len(names) != len(set(names)) or set(names) != expected_names:
        raise ValueError(label + " inventory is incomplete, duplicated or unexpected")


def verify_figure_provenance(study=None, figures=None):
    study = Path(DEFAULT_STUDY if study is None else study).resolve()
    figures = Path(DEFAULT_FIGURES if figures is None else figures).resolve()
    manifest_path = contained_file(figures, "figure-provenance.json")
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != "uav-vla-lab.research-figures.v1":
        raise ValueError("Unsupported figure provenance schema")
    renderer = manifest.get("renderer", {})
    if renderer.get("file") != "tools/render_research_figures.py":
        raise ValueError("Figure provenance must name the actual public figure renderer")
    if digest(ROOT / renderer["file"]) != renderer.get("sha256"):
        raise ValueError("Figure renderer differs from recorded provenance; regenerate the figures")
    records = manifest.get("inputs")
    if not isinstance(records, list) or not all(isinstance(record, dict) and isinstance(record.get("file"), str) for record in records):
        raise ValueError("Malformed study input inventory")
    expected_inputs = {record["file"] for record in records}
    # Later publication receipts are not plotting inputs. Every recorded input
    # must still match, and all files consumed by numeric validation must be bound.
    if not REQUIRED_INPUTS.issubset(expected_inputs):
        raise ValueError("Figure provenance omits a required numeric study input")
    verify_inventory(study, manifest.get("inputs"), expected_inputs, "Study input")
    verify_inventory(figures, manifest.get("outputs"), OUTPUTS, "Figure output")
    checked, *_ = validate(study)
    if json.dumps(checked, sort_keys=True, allow_nan=False) != json.dumps(manifest.get("validation"), sort_keys=True, allow_nan=False):
        raise ValueError("Figure validation receipt differs from current public numeric results")
    return {"schema_version": "uav-vla-lab.figure-verification.v1", "status": "passed",
            "figure_provenance_sha256": digest(manifest_path),
            "figure_renderer_sha256": renderer["sha256"],
            "verifier": {"file": "tools/verify_research_figures.py", "sha256": digest(__file__)},
            "inputs_verified": len(expected_inputs), "outputs_verified": len(OUTPUTS),
            "numeric_validation": checked,
            "scope": "Current public inputs, recorded renderer identity, figure-file integrity and numeric consistency; not manifest authorship or new visual review."}
