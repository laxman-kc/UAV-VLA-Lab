#!/usr/bin/env python3
"""Run the pinned AeroVLA wrapper on three genuine recorded image/state pairs.

This script imports no simulator client or evaluator and sends no flight commands.
The default is a real CUDA inference probe; --validate-only checks input provenance.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import datetime
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

PINNED_REVISION = "e37685afb8953d1f5a09155d7255960cee1bfd9d"
SOURCE_HASHES = {
    "src/model_wrapper/aerovla_wrapper_ui.py": "1e18357cedf0af5b36ccf4078373417d7e2b7d084487cb2b81282db3a008f3e8",
    "src/vlnce_src/env_uav.py": "9399f0d474f8376664c2c1abbb5c6b136d59080070c3b9798556f75fec8c1b4c",
}


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def file_record(path):
    path = Path(path).resolve()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path)}


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def contained(root, relative):
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts:
        raise ValueError("Input trajectory path must be relative and cannot contain '..'")
    result = (root / str(posix)).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError("Input trajectory escapes dataset root")
    return result


def validate_state(state):
    for key, count in (("position", 3), ("orientation", 4)):
        values = state[key]
        if not isinstance(values, list) or len(values) != count:
            raise ValueError(f"Raw state {key} must be a {count}-element array")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in values):
            raise ValueError(f"Raw state {key} must contain finite numbers")
    if sum(x * x for x in state["orientation"]) == 0:
        raise ValueError("Raw state quaternion cannot be zero")
    return {"position": state["position"], "orientation": state["orientation"]}


def selected_trajectory(selection):
    if isinstance(selection, list):
        paths = {row["json"] for row in selection}
    elif selection.get("kind") == "genuine_upstream_episode_selection":
        paths = {f"{selection['map_name']}/{selection['episode_id']}/merged_data.json"}
    elif selection.get("schema_version") == "vla.splits.v1":
        paths = set(selection["groups"]["demo"])
    else:
        raise ValueError("Use episode.json, selection_manifest.json, or a locked split with one demo")
    if len(paths) != 1:
        raise ValueError("Offline probe requires exactly one selected trajectory")
    relative = PurePosixPath(next(iter(paths)))
    if len(relative.parts) != 3 or relative.name != "merged_data.json" or ".." in relative.parts or relative.is_absolute():
        raise ValueError("Expected Map/episode/merged_data.json")
    return relative


def cancellation_only(source):
    return re.sub(r"(?m)^([ \t]*)except:[ \t]*$", lambda match:
                  match[1] + "except (KeyboardInterrupt, SystemExit):\n" + match[1] +
                  "    raise\n" + match[1] + "except:", source)


def verify_sources(upstream):
    revision = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    if revision != PINNED_REVISION:
        raise ValueError(f"Unexpected AeroVLA revision: {revision}")
    records = []
    for relative, expected in SOURCE_HASHES.items():
        path = upstream / relative
        current = path.read_text()
        backup = path.with_suffix(".py.vla-lab-original")
        original = backup.read_text() if backup.exists() else current
        if hashlib.sha256(original.encode()).hexdigest() != expected:
            raise ValueError(f"Unreviewed source: {relative}")
        if current not in (original, cancellation_only(original)):
            raise ValueError(f"Unreviewed source modification: {relative}")
        records.append({**file_record(path), "pinned_original_sha256": expected,
                        "cancellation_propagation_only": current != original})
    records.append(file_record(upstream / "src/model_wrapper/base_model.py"))
    return records


def lookup_target(upstream, map_name, mark):
    """Execute only the source-verified pure lookup function, never import env_uav."""
    import numpy as np
    source = upstream / "src/vlnce_src/env_uav.py"
    tree = ast.parse(source.read_text())
    definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "find_closest_area"]
    if len(definitions) != 1:
        raise ValueError("Cannot isolate the pinned target lookup")
    namespace = {"np": np}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(source), "exec"), namespace)
    spawn_path = upstream / "data/meta/map_spawnarea_info.json"
    areas = read_json(spawn_path)[map_name]
    marked_position = mark["target"]["position"]
    if len(marked_position) != 3 or not all(math.isfinite(float(x)) for x in marked_position):
        raise ValueError("Invalid marked target position")
    nearest, area = namespace["find_closest_area"](marked_position, areas)
    if area is None:
        raise ValueError("No upstream-compatible spawn area")
    return {
        "source": file_record(spawn_path), "lookup": "pinned env_uav.find_closest_area; first nearest eligible area",
        "marked_position": marked_position, "marked_asset_name": mark["object_name"],
        "nearest_area_center": nearest, "area_index": next(i for i, item in enumerate(areas) if item is area),
        "selected_area": area, "target_position": area[9:12],
        "asset_name": area[16], "object_quaternion_xyzw": [area[13], area[14], area[15], area[12]],
        "object_scale": area[17],
        "task": "official benchmark known target-position-derived direction; not unknown-target navigation",
    }


def prepare_recorded_inputs(dataset_root, selection_path):
    relative = selected_trajectory(read_json(selection_path))
    merged_path = contained(dataset_root, str(relative))
    trajectory_dir = merged_path.parent
    merged = read_json(merged_path)
    mark_path, descriptions_path = trajectory_dir / "mark.json", trajectory_dir / "object_description.json"
    mark, descriptions = read_json(mark_path), read_json(descriptions_path)
    instruction = merged["conversations"][0]["value"]
    if "degrees from you." not in instruction or " Please control" not in instruction:
        raise ValueError("Original merged instruction does not satisfy the pinned prompt parser")
    logs = sorted((trajectory_dir / "log").glob("*.json"))
    detailed = merged["trajectory_raw_detailed"]
    if len(logs) != len(detailed):
        raise ValueError("Merged detailed trajectory is not aligned with the sorted raw logs")
    indices, filtered = merged["index"], merged["trajectory_raw"]
    if len(indices) != len(filtered) or len(set(indices)) != len(indices):
        raise ValueError("Merged image indices are ambiguous or misaligned")
    filtered_by_id = dict(zip(indices, filtered))
    candidates = []
    for ordinal, path in enumerate(logs):
        frame_id = int(path.stem)
        front = trajectory_dir / "frontcamera" / f"{path.stem}.png"
        down = trajectory_dir / "downcamera" / f"{path.stem}.png"
        if frame_id in filtered_by_id and front.is_file() and down.is_file():
            candidates.append((ordinal, frame_id, path, front, down))
    if len(candidates) < 3:
        raise ValueError("Need at least three complete original front/down/log pairs")
    frames = []
    for sample_ordinal, candidate_index in enumerate((0, len(candidates) // 2, len(candidates) - 1)):
        ordinal, frame_id, path, front, down = candidates[candidate_index]
        log = read_json(path)
        state = validate_state(log["sensors"]["state"])
        if state != validate_state(detailed[ordinal]) or state != validate_state(filtered_by_id[frame_id]):
            raise ValueError(f"Original raw state disagrees with merged metadata for frame {frame_id}")
        frames.append({
            "sample_ordinal": sample_ordinal, "frame_id": frame_id, "raw_log_ordinal": ordinal,
            "state": state, "sensors": log["sensors"],
            "source_files": {"log": file_record(path), "front": file_record(front), "down": file_record(down)},
            "alignment": "Matched by original filename stem and verified against both merged raw state arrays; camera response timestamps are unavailable here",
            "timestamp_claim": "Frame index is not elapsed simulation time; no synthetic timestamp or action label assigned",
        })
    provenance = {
        "trajectory": str(relative), "map_name": relative.parts[0], "episode_id": relative.parts[1],
        "instruction": instruction, "object_descriptions": descriptions,
        "instruction_provenance": "Verbatim merged_data.json conversations[0].value; this may have been generated by the recorded TravelUAV converter",
        "source_files": [file_record(path) for path in (selection_path, merged_path, mark_path, descriptions_path)],
        "frame_selection": "First, middle (floor N/2), and last complete front/down/log pair in sorted raw logs, also present in merged index",
        "eligible_pair_count": len(candidates), "frames": frames,
    }
    return provenance, mark


def parse_diagnostic(text):
    """Report strict training-target validity separately from permissive upstream parsing."""
    suffix = text.split("Action:")[-1]
    normalized = suffix.replace("</s>", "").replace("<pad>", "").strip()
    match = re.fullmatch(r"([0-9]{2}) ([0-9]{2}) ([0-9]{2})( LAND)?", normalized)
    numbers = [int(item) for item in re.findall(r"\d+", suffix)]
    valid = bool(match and all(0 <= int(match[i]) <= 98 for i in (1, 2, 3)))
    return {
        "strict_valid": valid, "grammar": "Two-digit bins 00..98 separated by single spaces, optionally followed by ' LAND'; terminal </s>/<pad> ignored",
        "output_after_last_action_marker": suffix, "normalized_output": normalized,
        "numeric_substrings": numbers, "upstream_selected_last_three_bins": numbers[-3:] if len(numbers) >= 3 else None,
        "upstream_numeric_default_to_zero": len(numbers) < 3,
        "upstream_clamps_selected_bins": len(numbers) >= 3 and any(x > 98 for x in numbers[-3:]),
        "upstream_land_substring_anywhere": "LAND" in text,
        "diagnostic_only": "Does not modify the wrapper action or stop result",
    }


def model_identity(root):
    if not root.is_dir():
        raise ValueError(f"Model directory is missing: {root}")
    files = [file_record(path) for path in sorted(root.rglob("*")) if path.is_file() and ".cache" not in path.parts]
    if not files:
        raise ValueError(f"Model directory is empty: {root}")
    receipt_path = next((parent / "model-files.verified.json" for parent in root.parents
                         if (parent / "model-files.verified.json").exists()), None)
    result = {"directory": str(root), "files": files, "download_receipt": None, "repositories": []}
    if receipt_path:
        expected = {str((receipt_path.parent / item["relative_path"]).resolve()): item for item in read_json(receipt_path)}
        for record in files:
            entry = expected.get(record["path"])
            if entry is None or entry["sha256"] != record["sha256"] or entry["bytes"] != record["bytes"]:
                raise ValueError(f"Model file differs from local download receipt: {record['path']}")
        result["download_receipt"] = file_record(receipt_path)
        result["repositories"] = sorted({(expected[item["path"]]["repository"], expected[item["path"]]["revision"]) for item in files})
    return result


class TokenizerRecorder:
    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.prompts = []

    def __getattr__(self, name):
        return getattr(self.wrapped, name)

    def __call__(self, prompts, *args, **kwargs):
        self.prompts = list(prompts)
        return self.wrapped(prompts, *args, **kwargs)


class ProcessorRecorder:
    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.mosaic = None

    def __getattr__(self, name):
        return getattr(self.wrapped, name)

    def __call__(self, *args, **kwargs):
        self.mosaic = kwargs["images"].copy()
        return self.wrapped(*args, **kwargs)


def tensor_info(tensor):
    return {"shape": list(tensor.shape), "dtype": str(tensor.dtype), "device": str(tensor.device)}


def run_probe(options, report):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    report["models"] = {"base": model_identity(options.base_model), "adapter": model_identity(options.adapter)}
    import cv2
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("This P05 acceptance probe requires the intended CUDA host")
    report["runtime"] = {
        "python": sys.version, "cuda_runtime": torch.version.cuda,
        "device": torch.cuda.get_device_name(), "gpu_total_bytes": torch.cuda.get_device_properties(0).total_memory,
        "packages": {name: importlib.metadata.version(name) for name in
                     ("torch", "transformers", "peft", "numpy", "Pillow", "scipy")},
        "hf_hub_offline": True, "transformers_offline": True,
    }
    sys.path.insert(0, str(options.upstream))
    from src.model_wrapper.aerovla_wrapper_ui import AerialVLAWrapper
    previous_cwd = Path.cwd()
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter_ns()
    with tempfile.TemporaryDirectory(prefix="aerovla-offline-") as directory:
        (Path(directory) / "openvla-7b").symlink_to(options.base_model, target_is_directory=True)
        try:
            os.chdir(directory)
            wrapper = AerialVLAWrapper(SimpleNamespace(model_path=str(options.adapter)), SimpleNamespace())
        finally:
            os.chdir(previous_cwd)
    torch.cuda.synchronize()
    report["model_load"] = {"elapsed_ns": time.perf_counter_ns() - started,
                            "gpu_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                            "gpu_peak_reserved_bytes": torch.cuda.max_memory_reserved(),
                            "model_dtype": str(wrapper.model.dtype),
                            "base_path_method": "Temporary cwd symlink ./openvla-7b; pinned wrapper source unchanged"}
    wrapper.tokenizer = TokenizerRecorder(wrapper.tokenizer)
    wrapper.image_processor = ProcessorRecorder(wrapper.image_processor)
    report["samples"] = []
    for frame in report["input"]["frames"]:
        folder = options.output / "observations" / f"{frame['sample_ordinal']:02d}-{frame['frame_id']:06d}"
        folder.mkdir(parents=True)
        images, saved = {}, {}
        for camera in ("front", "down"):
            path = Path(frame["source_files"][camera]["path"])
            value = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if value is None or value.ndim != 3 or value.shape[2] != 3:
                raise ValueError(f"Cannot decode genuine {camera} image: {path}")
            images[camera] = value
            destination = folder / f"{camera}.png"
            shutil.copyfile(path, destination)
            saved[camera] = {**file_record(destination), "relative_path": str(destination.relative_to(options.output)),
                             "decoded_shape": list(value.shape), "decoded_dtype": str(value.dtype)}
        write_json(folder / "raw_state.json", frame["sensors"])
        episode = [[{"sensors": frame["sensors"], "rgb": [images["front"], None, None, None, images["down"]]}]]
        torch.cuda.synchronize()
        prepare_start = time.perf_counter_ns()
        inputs, rotations = wrapper.prepare_inputs(episode, [report["target"]["target_position"]], [report["input"]["instruction"]])
        torch.cuda.synchronize()
        preparation_ns = time.perf_counter_ns() - prepare_start
        mosaic_path = folder / "wrapper_mosaic.png"
        wrapper.image_processor.mosaic.save(mosaic_path)
        input_ids = inputs["input_ids"][0].detach().cpu().tolist()
        generated = {}
        original_generate = wrapper.model.generate

        def record_generation(*args, **kwargs):
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
            begin = time.perf_counter_ns()
            result = original_generate(*args, **kwargs)
            torch.cuda.synchronize()
            generated["latency_ns"] = time.perf_counter_ns() - begin
            generated["gpu_peak_allocated_bytes"] = torch.cuda.max_memory_allocated()
            generated["gpu_peak_reserved_bytes"] = torch.cuda.max_memory_reserved()
            copy_start = time.perf_counter_ns()
            generated["token_ids"] = result.detach().cpu().tolist()
            generated["token_copy_ns"] = time.perf_counter_ns() - copy_start
            generated["tensor"] = tensor_info(result)
            generated["settings"] = {key: kwargs[key] for key in ("max_new_tokens", "do_sample", "eos_token_id")}
            return result

        wrapper.model.generate = record_generation
        try:
            run_start = time.perf_counter_ns()
            actions, stop_flags = wrapper.run(inputs, episode, rotations)
            torch.cuda.synchronize()
            run_ns = time.perf_counter_ns() - run_start
        finally:
            wrapper.model.generate = original_generate
        tokens = generated["token_ids"][0]
        raw_text = wrapper.tokenizer.decode(tokens, skip_special_tokens=False)
        includes_prompt = tokens[:len(input_ids)] == input_ids
        generated["raw_text"] = raw_text
        generated["includes_input_prefix"] = includes_prompt
        generated["completion_token_ids"] = tokens[len(input_ids):] if includes_prompt else tokens
        generated["completion_text"] = wrapper.tokenizer.decode(generated["completion_token_ids"], skip_special_tokens=False)
        sample = {
            "sample_ordinal": frame["sample_ordinal"], "frame_id": frame["frame_id"],
            "source_files": frame["source_files"], "state": frame["state"], "images": saved,
            "mosaic": {**file_record(mosaic_path), "relative_path": str(mosaic_path.relative_to(options.output)),
                       "size_wh": list(wrapper.image_processor.mosaic.size)},
            "camera_slots": ["front", None, None, None, "down"],
            "prompt": wrapper.tokenizer.prompts[0], "input_token_ids": input_ids,
            "input_tensors": {key: tensor_info(value) for key, value in inputs.items()},
            "generation": generated, "upstream_action": actions[0], "upstream_stop": bool(stop_flags[0]),
            "action_units": {"fwd": "metres", "down": "metres", "yaw": "radians"},
            "parse_diagnostic": parse_diagnostic(raw_text), "prepare_ns": preparation_ns,
            "wrapper_run_including_recording_ns": run_ns,
            "timing_note": "One sequential inference; no warmup, first sample may include lazy initialization. CUDA synchronized generation timing excludes CPU token copy and file encoding",
        }
        report["samples"].append(sample)
        write_json(options.output / "report.json", report)
        print(json.dumps({"sample": frame["sample_ordinal"], "frame_id": frame["frame_id"],
                          "strict_parse_valid": sample["parse_diagnostic"]["strict_valid"],
                          "action": actions[0], "stop": bool(stop_flags[0]),
                          "latency_seconds": generated["latency_ns"] / 1e9}), flush=True)
    report["acceptance"] = {
        "three_genuine_pairs_completed": len(report["samples"]) == 3,
        "all_strict_parses_valid": all(item["parse_diagnostic"]["strict_valid"] for item in report["samples"]),
        "simulator_commands_sent": 0,
        "navigation_success_tested": False,
    }
    report["status"] = "passed" if report["acceptance"]["all_strict_parses_valid"] else "completed_with_invalid_generation"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("upstream", "dataset-root", "episode-selection", "base-model", "adapter", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true", help="Check source/data/target mapping; no model load and no P05 acceptance claim")
    options = parser.parse_args()
    for name in ("upstream", "dataset_root", "episode_selection", "base_model", "adapter", "output"):
        setattr(options, name, getattr(options, name).resolve())
    options.output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": "vla.offline_policy_probe.v1", "phase": "P05", "status": "running",
              "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "upstream_revision": PINNED_REVISION, "probe_source": file_record(Path(__file__)),
              "mode": "input_validation_only" if options.validate_only else "real_offline_model_inference",
              "evidence_scope": "Recorded dataset observations; no simulated flight, no expert action label, no navigation metric",
              "argv": sys.argv, "simulator_commands_sent": 0}
    exit_code = 0
    try:
        report["upstream_sources"] = verify_sources(options.upstream)
        provenance, mark = prepare_recorded_inputs(options.dataset_root, options.episode_selection)
        report["input"] = provenance
        report["target"] = lookup_target(options.upstream, provenance["map_name"], mark)
        write_json(options.output / "report.json", report)
        if options.validate_only:
            report["status"] = "inputs_validated_model_not_run"
        else:
            with (options.output / "model_stdout.log").open("x") as stdout:
                with contextlib.redirect_stdout(stdout):
                    run_probe(options, report)
            if report["status"] != "passed":
                exit_code = 2
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        exit_code = 1
        raise
    finally:
        report["finished_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        write_json(options.output / "report.json", report)
        print(json.dumps({"status": report["status"], "report": str(options.output / "report.json")}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
