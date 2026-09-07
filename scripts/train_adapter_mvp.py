#!/usr/bin/env python3
"""Continue a verified AeroVLA PEFT adapter; never create supervision or fresh LoRA.

Contract validation uses the standard library. Actual execution requires the
recorded CUDA/PyTorch/Transformers/PEFT runtime and the pinned upstream checkout.
An optimizer update is an engineering result, not evidence of useful learning.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import gc
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import random
import shutil
import sys
import time
import traceback


UPSTREAM_COMMIT = "e37685afb8953d1f5a09155d7255960cee1bfd9d"
UPSTREAM_FILES = {
    "src/aerovla_dataset.py": "55f2804162f4992eb481cda68b971edca833841a3fe5170560a8878ddb6916f7",
    "src/train_aerovla.py": "5bde78d405c6153d89440d0c81acae5e0be9ca67cb9843141827ddd7a19d6ec2",
}
LABEL_BOUNDS = {"fwd": (0.0, 5.0), "down": (-5.0, 5.0), "yaw": (-1.1, 1.1)}
EXPERT_SOURCES = {"human_expert", "audited_reference_expert", "approved_controller_expert"}


class ContractError(ValueError):
    pass


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def file_record(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size}


def contained(root, relative):
    if not isinstance(relative, str) or not relative:
        raise ContractError("A nonempty relative file path is required")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
        raise ContractError(f"Path escapes its declared root: {relative}")
    path = (Path(root) / relative).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ContractError(f"Path escapes its declared root: {relative}")
    return path


def verify_record(record, root, expected_path=None):
    if not isinstance(record, dict) or not record.get("sha256"):
        raise ContractError("File evidence requires path and SHA256")
    path = contained(root, record.get("path"))
    if expected_path is not None and path != Path(expected_path).resolve():
        raise ContractError(f"Evidence references a different file: {record.get('path')}")
    if not path.is_file() or digest(path) != record["sha256"]:
        raise ContractError(f"Missing or changed evidence bytes: {record.get('path')}")
    if "bytes" in record and path.stat().st_size != record["bytes"]:
        raise ContractError(f"Evidence size mismatch: {record['path']}")
    return path


def require_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"Missing explicit {field}")


def validate_dataset(data_json, dataset_root, manifest_path):
    """Recheck declared provenance and split membership; do not approve labels."""
    manifest_path, dataset_root = Path(manifest_path), Path(dataset_root)
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != "vla.training-dataset.v1" or manifest.get("status") != "validated":
        raise ContractError("Dataset requires a vla.training-dataset.v1 manifest with status=validated")
    verify_record(manifest.get("data_json"), manifest_path.parent, data_json)
    split_path = verify_record(manifest.get("split_manifest"), manifest_path.parent)
    split = read_json(split_path)
    if split.get("schema_version") != "vla.splits.v1" or not split.get("frozen_at_utc"):
        raise ContractError("A frozen vla.splits.v1 manifest is required")
    groups = split.get("groups", {})
    if not all(isinstance(groups.get(name), list) for name in ("train", "development", "holdout")):
        raise ContractError("Split must declare train, development and holdout membership")
    seen = set()
    for name, members in groups.items():
        if not isinstance(members, list) or len(set(members)) != len(members) or seen.intersection(members):
            raise ContractError(f"Duplicate or overlapping split membership: {name}")
        for member in members:
            if str(PurePosixPath(member)) != member or len(PurePosixPath(member).parts) != 3 or not member.endswith("/merged_data.json"):
                raise ContractError("Split IDs must be Map/episode/merged_data.json")
            contained(dataset_root, member)
        seen.update(members)
    policy = manifest.get("label_policy", {})
    if policy.get("source_kind") not in EXPERT_SOURCES:
        raise ContractError("Expert provenance must be explicit; model predictions are not expert labels")
    if policy.get("action_units") != {"fwd": "m", "down": "m", "yaw": "rad"}:
        raise ContractError("Upstream physical action labels require fwd/down metres and yaw radians")
    for field in ("source_description", "action_frame", "action_horizon", "stop_semantics", "temporal_alignment"):
        require_text(policy.get(field), f"label_policy.{field}")
    approval = manifest.get("approval", {})
    if approval.get("status") != "approved":
        raise ContractError("Dataset has no recorded expert review approval")
    for field in ("reviewer", "reviewed_at_utc"):
        require_text(approval.get(field), f"approval.{field}")
    verify_record(approval.get("evidence"), manifest_path.parent)
    rows = read_json(data_json)
    records = manifest.get("samples")
    if not isinstance(rows, list) or not rows or not isinstance(records, list) or len(records) != len(rows):
        raise ContractError("Every nonempty training row needs exactly one manifest sample")
    ids, image_pairs = set(), set()
    for index, (row, record) in enumerate(zip(rows, records)):
        if not isinstance(row, dict) or record.get("row_index") != index or record.get("row_sha256") != canonical_hash(row):
            raise ContractError(f"Sample row identity mismatch at index {index}")
        sample_id = record.get("sample_id")
        require_text(sample_id, "sample_id")
        if sample_id in ids:
            raise ContractError("Duplicate sample ID")
        ids.add(sample_id)
        trajectory, filename = row.get("traj_rel_dir"), row.get("img_name")
        if not isinstance(trajectory, str) or len(PurePosixPath(trajectory).parts) != 2:
            raise ContractError("traj_rel_dir must be Map/episode")
        if not isinstance(filename, str) or PurePosixPath(filename).name != filename or Path(filename).suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise ContractError("img_name must identify one saved PNG/JPEG filename")
        episode = trajectory + "/merged_data.json"
        if record.get("episode_id") != episode or record.get("split") != "train" or episode not in groups["train"]:
            raise ContractError(f"Training sample is outside its attested train split: {sample_id}")
        require_text(row.get("instruction"), "instruction")
        if any(type(row.get(key)) is not bool for key in ("is_last_step", "is_penultimate")):
            raise ContractError("Stop flags must be explicit booleans from reviewed labels")
        labels = row.get("label", {})
        if set(labels) != set(LABEL_BOUNDS):
            raise ContractError("label must contain exactly fwd/down/yaw")
        for axis, (low, high) in LABEL_BOUNDS.items():
            value = labels[axis]
            if type(value) not in (float, int) or not math.isfinite(value) or not low <= value <= high:
                raise ContractError(f"Invalid {axis} label; refusing upstream silent clipping")
        pair = (trajectory, filename)
        if pair in image_pairs:
            raise ContractError("Duplicate observation pair in training data")
        image_pairs.add(pair)
        for camera, folder in (("front", "frontcamera"), ("down", "downcamera")):
            expected = contained(dataset_root, f"{trajectory}/{folder}/{filename}")
            verify_record(record.get("images", {}).get(camera), dataset_root, expected)
        sources = record.get("source_evidence")
        if not isinstance(sources, list) or not sources:
            raise ContractError("Every label needs source evidence, including its temporal/state provenance")
        for evidence in sources:
            verify_record(evidence, dataset_root)
    return {"status": "passed", "sample_count": len(rows), "sample_ids": [r["sample_id"] for r in records],
            "episode_ids": sorted({r["episode_id"] for r in records}),
            "data_json": file_record(data_json), "dataset_manifest": file_record(manifest_path),
            "split_manifest": file_record(split_path), "approval": approval, "label_policy": policy,
            "limitation": "Hashes and declarations are checked; this program does not establish that expert labels are correct."}


def validate_parent(base_root, adapter_root, manifest_path):
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != "vla.adapter-parent.v1" or manifest.get("preserve_projector") is not True:
        raise ContractError("Parent manifest must explicitly require projector preservation")
    require_text(manifest.get("checkpoint_id"), "parent checkpoint_id")
    result = {"manifest": file_record(manifest_path), "checkpoint_id": manifest["checkpoint_id"]}
    for label, root in (("base", Path(base_root)), ("adapter", Path(adapter_root))):
        declaration = manifest.get(label, {})
        require_text(declaration.get("identity"), f"parent {label} identity")
        records = declaration.get("files")
        if not isinstance(records, list) or not records:
            raise ContractError(f"Missing {label} file inventory")
        expected = set()
        for record in records:
            path = verify_record(record, root)
            if path in expected:
                raise ContractError(f"Duplicate parent file: {path.name}")
            expected.add(path)
        actual = {p.resolve() for p in root.rglob("*") if p.is_file() and ".cache" not in p.parts}
        if actual != expected:
            raise ContractError(f"{label} inventory differs from parent manifest; no unlisted model/code files allowed")
        result[label] = declaration
    config = read_json(Path(adapter_root) / "adapter_config.json")
    if config.get("peft_type") != "LORA" or config.get("task_type") != "CAUSAL_LM" or config.get("bias") != "none":
        raise ContractError("Expected the released causal-LM LoRA adapter with bias=none")
    if config.get("modules_to_save") != ["projector"]:
        raise ContractError("Adapter must contain modules_to_save=['projector']")
    if not (Path(adapter_root) / "adapter_model.safetensors").is_file():
        raise ContractError("An existing adapter_model.safetensors is required; no fresh LoRA or pickle fallback")
    if not (Path(base_root) / "config.json").is_file():
        raise ContractError("Base model config is missing")
    result["adapter_config"] = config
    return result


def validate_upstream(root):
    result = {"reference_commit": UPSTREAM_COMMIT, "files": []}
    for name, expected in UPSTREAM_FILES.items():
        record = file_record(Path(root) / name)
        if record["sha256"] != expected:
            raise ContractError(f"Pinned upstream code hash differs: {name}")
        result["files"].append(record)
    return result


def import_upstream(root, tokenizer, processor, torch):
    dataset_path = Path(root) / "src/aerovla_dataset.py"
    module_spec = importlib.util.spec_from_file_location("pinned_aerovla_training_dataset", dataset_path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    # The published collator is local to main(). Execute only its verified AST,
    # never train_aerovla.main(), which creates a fresh LoRA configuration.
    trainer_path = Path(root) / "src/train_aerovla.py"
    tree = ast.parse(trainer_path.read_text(encoding="utf-8"))
    candidates = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "data_collator"]
    if len(candidates) != 1:
        raise ContractError("Pinned trainer must contain exactly one data_collator")
    scope = {"torch": torch, "tokenizer": tokenizer}
    exec(compile(ast.Module(body=candidates, type_ignores=[]), str(trainer_path), "exec"), scope)
    return module.AeroVLADataset, scope["data_collator"]


def check_token_boundary(full_ids, prompt_ids, labels, attention):
    if len(full_ids) > 2048:
        raise ContractError("Sample exceeds upstream 2048-token limit; refusing target truncation")
    n = len(prompt_ids)
    if full_ids[:n] != prompt_ids:
        raise ContractError("Prompt/action token boundary differs; upstream masking needs explicit review")
    if n >= len(full_ids) or len(labels) != len(attention):
        raise ContractError("No supervised action tokens remain")
    if any(value != -100 for value in labels[:n]):
        raise ContractError("Prompt tokens were not fully masked")
    if any(label != -100 for label, keep in zip(labels, attention) if not keep):
        raise ContractError("Padding tokens were not fully masked")
    if labels[n:len(full_ids)] != full_ids[n:]:
        raise ContractError("Action/EOS supervision differs from the untruncated target")


def audited_collator(original, tokenizer):
    def collate(features):
        batch = original(features)
        for i, feature in enumerate(features):
            full = tokenizer(feature["text"], add_special_tokens=True, truncation=False)["input_ids"]
            prompt = tokenizer(feature["prompt_only"], add_special_tokens=True, truncation=False)["input_ids"]
            check_token_boundary(full, prompt, batch["labels"][i].tolist(), batch["attention_mask"][i].tolist())
        return batch
    return collate


def parameter_group(name):
    if ".lora_A." in name or ".lora_B." in name:
        return "lora"
    if ".projector.modules_to_save.default." in name:
        return "projector"
    return None


def check_trainable_names(names):
    groups = {"lora": [], "projector": []}
    for name in names:
        group = parameter_group(name)
        if group is None:
            raise ContractError(f"Unexpected trainable base tensor: {name}")
        groups[group].append(name)
    if not all(groups.values()):
        raise ContractError("Both released LoRA and saved projector tensors must be trainable")
    return groups


def tensor_hash(tensor):
    import torch
    value = tensor.detach().cpu().contiguous()
    header = json.dumps({"shape": list(value.shape), "dtype": str(value.dtype)}, sort_keys=True).encode()
    return hashlib.sha256(header + value.view(torch.uint8).numpy().tobytes()).hexdigest()


def adapter_hashes(model):
    from peft import get_peft_model_state_dict
    return {name: {"sha256": tensor_hash(value), "shape": list(value.shape), "dtype": str(value.dtype)}
            for name, value in get_peft_model_state_dict(model).items()}


def check_weight_changes(before, after):
    if set(before) != set(after):
        raise ContractError("Adapter tensor inventory changed unexpectedly")
    changed = [name for name in before if before[name]["sha256"] != after[name]["sha256"]]
    if not any("lora_" in name for name in changed) or not any(".projector." in name for name in changed):
        raise ContractError("Optimizer did not change both LoRA and projector weights")
    return {"changed_tensor_count": len(changed), "total_tensor_count": len(before), "changed_tensors": changed}


def load_model(base, adapter, trainable, tokenizer_size):
    import torch
    from transformers import AutoModelForVision2Seq
    from peft import PeftModel, get_peft_model_state_dict, set_peft_model_state_dict
    from safetensors.torch import load_file
    model = AutoModelForVision2Seq.from_pretrained(str(base), torch_dtype=torch.bfloat16,
        trust_remote_code=True, local_files_only=True, device_map={"": 0}, low_cpu_mem_usage=True)
    original_embeddings = model.get_input_embeddings().num_embeddings
    if tokenizer_size > original_embeddings:
        raise ContractError("Tokenizer requires new embedding rows; refusing random initialization")
    # Both pinned training and inference code resize to the base tokenizer length.
    # Shrinking unused padded rows preserves retained weights; adding rows is barred.
    if tokenizer_size != original_embeddings:
        model.resize_token_embeddings(tokenizer_size)
    model = PeftModel.from_pretrained(model, str(adapter), is_trainable=trainable, local_files_only=True)
    model._training_embedding_contract = {"base_rows": original_embeddings, "tokenizer_rows": tokenizer_size,
        "behavior": "Pinned upstream resize to base tokenizer length; only equal size or shrink is permitted"}
    # Preserve parent FP32 values: PEFT initially copies into destination dtypes.
    # Reapply the *same* existing state after casting only adapter/projector copies.
    for name, parameter in model.named_parameters():
        if parameter_group(name):
            parameter.data = parameter.data.float()
    parent = load_file(str(Path(adapter) / "adapter_model.safetensors"), device="cpu")
    set_peft_model_state_dict(model, parent)
    loaded = get_peft_model_state_dict(model)
    if set(parent) != set(loaded):
        raise ContractError("Loaded adapter/projector key inventory differs from the existing checkpoint")
    for name, expected in parent.items():
        actual = loaded[name].detach().cpu()
        if not torch.isfinite(actual).all().item() or not torch.equal(actual, expected.to(actual.dtype)):
            raise ContractError(f"Parent adapter/projector tensor was not preserved: {name}")
    del parent, loaded
    if not trainable:
        model.requires_grad_(False)
    model.config.use_cache = False
    return model


def memory():
    import torch
    free, total = torch.cuda.mem_get_info()
    return {"free_bytes": free, "total_bytes": total, "allocated_bytes": torch.cuda.memory_allocated(),
            "reserved_bytes": torch.cuda.memory_reserved(), "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved()}


def prediction_snapshot(model, batch):
    """Teacher-forced logits on one fixed real batch; no navigation metric."""
    import torch
    model.eval()
    torch.cuda.synchronize()
    start = time.perf_counter()
    with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
        output = model(**batch)
        # OpenVLA inserts image patches: its output length can exceed text length.
        # Keep the final token distribution, whose position is unambiguous.
        logits = output.logits[:, -1, :].float().cpu().contiguous()
        loss = float(output.loss.detach().float().cpu())
    torch.cuda.synchronize()
    if not math.isfinite(loss) or not torch.isfinite(logits).all().item():
        raise ContractError("Nonfinite fixed-batch inference output")
    return {"loss": loss, "elapsed_seconds": time.perf_counter() - start,
            "last_token_logits_sha256": tensor_hash(logits), "logits_shape": list(logits.shape),
            "argmax_token_ids": logits.argmax(dim=-1).tolist(), "teacher_forced": True}, logits


def run_training(options, report):
    if shutil.disk_usage(options.output).free < options.min_free_gib * 1024 ** 3:
        raise ContractError("Operational free-space reserve is unavailable before model loading")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import numpy as np
    import torch
    from transformers import AutoTokenizer, AutoProcessor
    from safetensors.torch import save_file
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1 or not torch.cuda.is_bf16_supported():
        raise ContractError("This runner requires exactly one visible BF16-capable CUDA GPU")
    if int(os.environ.get("WORLD_SIZE", "1")) != 1:
        raise ContractError("Distributed launches are not supported")
    random.seed(options.seed)
    np.random.seed(options.seed)
    torch.manual_seed(options.seed)
    torch.cuda.manual_seed_all(options.seed)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    report["runtime"] = {"python": sys.version, "torch_cuda": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0), "seed": options.seed,
        "packages": {name: importlib.metadata.version(name) for name in ("torch", "transformers", "peft", "safetensors", "numpy", "Pillow")},
        "precision": "Frozen base BF16; LoRA and projector parameters/optimizer FP32; CUDA BF16 autocast",
        "determinism": "Seeded sampling and RNG; bitwise training reproducibility is not guaranteed across CUDA kernels or hosts"}
    torch.cuda.reset_peak_memory_stats()
    tokenizer = AutoTokenizer.from_pretrained(str(options.base_model), trust_remote_code=True, local_files_only=True)
    processor = AutoProcessor.from_pretrained(str(options.base_model), trust_remote_code=True, local_files_only=True)
    if tokenizer.eos_token is None:
        raise ContractError("Tokenizer EOS is missing; refusing to invent or add tokens")
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    if tokenizer.padding_side != "right":
        raise ContractError("Pinned collator masks prompt prefixes and requires right padding")
    Dataset, original_collator = import_upstream(options.upstream, tokenizer, processor, torch)
    collate = audited_collator(original_collator, tokenizer)
    dataset = Dataset(str(options.dataset_root), str(options.data_json), tokenizer, processor)
    # Validate all masks before allocating the 7B model; no label text is rewritten.
    for index in range(len(dataset)):
        collate([dataset[index]])
    model = load_model(options.base_model, options.adapter, trainable=True, tokenizer_size=len(tokenizer))
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    trainable = [(name, p) for name, p in model.named_parameters() if p.requires_grad]
    groups = check_trainable_names([name for name, _ in trainable])
    audit = [{"name": name, "shape": list(p.shape), "parameters": p.numel(), "dtype": str(p.dtype),
              "group": parameter_group(name)} for name, p in trainable]
    write_json(options.output / "trainable-tensors.json", audit)
    before = adapter_hashes(model)
    write_json(options.output / "adapter-before.json", before)
    fixed = {key: value.to("cuda") for key, value in collate([dataset[0]]).items()}
    report["prediction_before"], before_logits = prediction_snapshot(model, fixed)
    save_file({"last_token_logits": before_logits}, str(options.output / "prediction-before.safetensors"))
    del before_logits
    report["model_loaded"] = {"parent_values_preserved": True, "memory": memory(),
                              "embedding_contract": model._training_embedding_contract,
                              "trainable_parameters": sum(p.numel() for _, p in trainable),
                              "trainable_tensor_count": len(trainable), "groups": {k: len(v) for k, v in groups.items()}}
    report["stage"] = "optimizer_steps"
    write_json(options.output / "report.json", report)
    optimizer = torch.optim.AdamW([p for _, p in trainable], lr=options.learning_rate,
                                  betas=(0.9, 0.999), eps=1e-8,
                                  weight_decay=options.weight_decay, foreach=False)
    sampler = random.Random(options.seed)
    order, cursor, epochs = [], 0, 0
    training_start = time.perf_counter()
    checkpoint = options.output / "checkpoint"
    with (options.output / "steps.jsonl").open("x", encoding="utf-8") as log:
        for step in range(1, options.steps + 1):
            if options.max_wall_seconds is not None and time.perf_counter() - training_start >= options.max_wall_seconds:
                raise ContractError("Declared wall-time limit reached before the next optimizer step")
            if shutil.disk_usage(options.output).free < options.min_free_gib * 1024 ** 3:
                raise ContractError("Operational free-space reserve reached")
            model.train()
            optimizer.zero_grad(set_to_none=True)
            torch.cuda.reset_peak_memory_stats()
            torch.cuda.synchronize()
            started = time.perf_counter()
            micro_losses, indices = [], []
            for _ in range(options.gradient_accumulation):
                batch_indices = []
                for _ in range(options.batch_size):
                    if cursor == len(order):
                        order = list(range(len(dataset)))
                        sampler.shuffle(order)
                        cursor = 0
                        epochs += 1
                    batch_indices.append(order[cursor])
                    cursor += 1
                batch = {key: value.to("cuda") for key, value in collate([dataset[i] for i in batch_indices]).items()}
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    output = model(**batch)
                    loss = output.loss
                if not torch.isfinite(loss).item():
                    raise ContractError("Nonfinite loss; optimizer step was not applied")
                micro_losses.append(float(loss.detach().float().cpu()))
                (loss / options.gradient_accumulation).backward()
                indices.extend(batch_indices)
                del batch, loss, output
            missing = [name for name, p in trainable if p.grad is None]
            if missing:
                raise ContractError(f"Intended trainable tensors received no gradient: {missing}")
            if not torch.stack([torch.isfinite(p.grad).all() for _, p in trainable]).all().item():
                raise ContractError("Nonfinite adapter/projector gradient; optimizer step was not applied")
            norm = torch.nn.utils.clip_grad_norm_([p for _, p in trainable], options.max_grad_norm, error_if_nonfinite=True)
            if float(norm) == 0:
                raise ContractError("All intended gradients are zero; refusing an ineffective optimizer step")
            optimizer.step()
            if not torch.stack([torch.isfinite(p).all() for _, p in trainable]).all().item():
                raise ContractError("Optimizer produced a nonfinite trainable tensor")
            torch.cuda.synchronize()
            item = {"recorded_at_utc": now(), "optimizer_step": step, "microbatch_losses": micro_losses,
                    "mean_microbatch_loss": sum(micro_losses) / len(micro_losses),
                    "loss_weighting": "Mean of microbatch losses, matching upstream accumulation; not token-count weighting",
                    "gradient_norm_before_clip": float(norm), "all_trainable_gradients_present_finite": True,
                    "learning_rate": optimizer.param_groups[0]["lr"], "sample_indices": indices,
                    "sample_ids": [report["dataset"]["sample_ids"][i] for i in indices],
                    "completed_sample_exposures": step * options.batch_size * options.gradient_accumulation,
                    "sampling_epoch_started": epochs, "elapsed_seconds": time.perf_counter() - started, "memory": memory()}
            log.write(json.dumps(item, allow_nan=False) + "\n")
            log.flush()
            report["completed_optimizer_steps"] = step
            write_json(options.output / "report.json", report)
            print(json.dumps(item, allow_nan=False), flush=True)
    optimizer.zero_grad(set_to_none=True)
    after = adapter_hashes(model)
    report["weight_changes"] = check_weight_changes(before, after)
    write_json(options.output / "adapter-after.json", after)
    report["prediction_after"], expected_logits = prediction_snapshot(model, fixed)
    save_file({"last_token_logits": expected_logits}, str(options.output / "prediction-after.safetensors"))
    model.save_pretrained(str(checkpoint), safe_serialization=True, save_embedding_layers=False)
    tokenizer.save_pretrained(str(checkpoint))
    processor.save_pretrained(str(checkpoint))
    report["training_elapsed_seconds"] = time.perf_counter() - training_start
    report["stage"] = "unload_then_reload"
    # No second 7B model until all live training/optimizer references are dropped.
    del optimizer, trainable, model, fixed
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.synchronize()
    report["after_training_model_unload"] = memory()
    write_json(options.output / "report.json", report)
    reloaded = load_model(options.base_model, checkpoint, trainable=False, tokenizer_size=len(tokenizer))
    reload_hashes = adapter_hashes(reloaded)
    if reload_hashes != after:
        raise ContractError("Save/reload changed an adapter or projector tensor")
    fixed_reload = {key: value.to("cuda") for key, value in collate([dataset[0]]).items()}
    report["prediction_reloaded"], actual_logits = prediction_snapshot(reloaded, fixed_reload)
    maximum_error = float((expected_logits - actual_logits).abs().max())
    numeric_match = torch.allclose(expected_logits, actual_logits, atol=options.reload_atol, rtol=options.reload_rtol)
    loss_match = math.isclose(report["prediction_after"]["loss"], report["prediction_reloaded"]["loss"],
                             abs_tol=options.reload_atol, rel_tol=options.reload_rtol)
    report["reload_validation"] = {"exact_adapter_and_projector_hashes_match": True,
        "last_token_logits_allclose": numeric_match, "loss_isclose": loss_match,
        "last_token_logits_max_absolute_error": maximum_error, "atol": options.reload_atol, "rtol": options.reload_rtol,
        "scope": "Fixed first training sample, teacher-forced loss and final-position full-vocabulary logits; no navigation evaluation"}
    save_file({"last_token_logits": actual_logits}, str(options.output / "prediction-reloaded.safetensors"))
    if not numeric_match or not loss_match:
        raise ContractError("Reloaded fixed-batch numerics differ beyond the predeclared tolerance")
    report["reload_memory"] = memory()
    del reloaded, fixed_reload, expected_logits, actual_logits
    gc.collect()
    torch.cuda.empty_cache()
    report["status"] = "passed"
    report["stage"] = "complete"
    report["completed_at_utc"] = now()
    report["checkpoint_files"] = [file_record(path) for path in sorted(checkpoint.iterdir()) if path.is_file()]
    report["research_claim"] = "No claim that learning or navigation improved. This candidate requires separate development evaluation."
    write_json(options.output / "report.json", report)
    write_json(options.output / "checkpoint-manifest.json", {"schema_version": "vla.training-checkpoint.v1",
        "status": "mechanics_verified", "phase": options.phase, "parent": report["parent"], "dataset": report["dataset"],
        "config": report["config"], "code": report["code"], "optimizer_steps": options.steps,
        "projector_preserved_and_saved": True, "checkpoint_files": report["checkpoint_files"],
        "reload_validation": report["reload_validation"], "selection_rule": options.selection_rule,
        "resume_support": "Adapter continuation only; optimizer/RNG resume state is not saved", "research_claim": report["research_claim"]})


def validate_options(options):
    for field in ("steps", "batch_size", "gradient_accumulation"):
        if getattr(options, field) < 1:
            raise ContractError(f"{field} must be positive")
    if options.phase == "P10" and options.steps != 1:
        raise ContractError("P10 requires exactly one optimizer step")
    if not 0 <= options.seed <= 2 ** 32 - 1:
        raise ContractError("seed must be an unsigned 32-bit integer")
    for field in ("learning_rate", "max_grad_norm", "min_free_gib"):
        if not math.isfinite(getattr(options, field)) or getattr(options, field) <= 0:
            raise ContractError(f"{field} must be finite and positive")
    for field in ("weight_decay", "reload_atol", "reload_rtol"):
        if not math.isfinite(getattr(options, field)) or getattr(options, field) < 0:
            raise ContractError(f"{field} must be finite and nonnegative")
    if options.max_wall_seconds is not None and (not math.isfinite(options.max_wall_seconds) or options.max_wall_seconds <= 0):
        raise ContractError("max_wall_seconds must be positive")


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    for flag in ("base-model", "adapter", "parent-manifest", "data-json", "dataset-root", "dataset-manifest", "upstream", "output"):
        result.add_argument("--" + flag, type=Path, required=True)
    result.add_argument("--phase", choices=("P10", "P12"), required=True)
    result.add_argument("--steps", type=int, default=1)
    result.add_argument("--learning-rate", type=float, required=True)
    result.add_argument("--batch-size", type=int, default=1)
    result.add_argument("--gradient-accumulation", type=int, default=1)
    result.add_argument("--seed", type=int, required=True)
    result.add_argument("--weight-decay", type=float, default=0.03)
    result.add_argument("--max-grad-norm", type=float, default=1.0)
    result.add_argument("--min-free-gib", type=float, default=60.0)
    result.add_argument("--max-wall-seconds", type=float)
    result.add_argument("--reload-atol", type=float, default=1e-5)
    result.add_argument("--reload-rtol", type=float, default=1e-5)
    result.add_argument("--selection-rule", choices=("fixed_final_step_candidate",), default="fixed_final_step_candidate")
    result.add_argument("--validate-only", action="store_true", help="Hash and validate contracts; do not import ML libraries or train")
    return result


def main(argv=None):
    options = parser().parse_args(argv)
    validate_options(options)
    for key, value in vars(options).items():
        if isinstance(value, Path):
            setattr(options, key, value.resolve())
    report = {"schema_version": "vla.training-run.v1", "started_at_utc": now(), "status": "running",
              "phase": options.phase, "stage": "contract_validation", "completed_optimizer_steps": 0,
              "config": {key: str(value) if isinstance(value, Path) else value for key, value in vars(options).items()},
              "limitations": ["No expert labels are created, inferred, or approved by this runner.",
                  "Fixed final-step candidate; no best-checkpoint or holdout-based selection.",
                  "Constant learning rate, AdamW, no scheduler, no resume state, and zero data-loader workers.",
                  "Recorded step timing includes data reading, diagnostic synchronization and gradient auditing.",
                  "Simulator must be stopped by the execution owner before launch; this runner never kills other processes."]}
    report["config"]["algorithm"] = {"optimizer": "torch.optim.AdamW", "betas": [0.9, 0.999], "eps": 1e-8,
        "foreach": False, "scheduler": None, "gradient_checkpointing": True, "use_reentrant": False,
        "frozen_base_dtype": "bfloat16", "trainable_parameter_dtype": "float32", "autocast_dtype": "bfloat16",
        "max_sequence_length": 2048, "dataloader_workers": 0,
        "sampling": "Seeded shuffle of all training row indices, repeat at epoch boundary; no dropping or automatic labels",
        "checkpoint_cadence": "Only final configured optimizer step; intermediate steps remain in the log",
        "effective_batch_examples": options.batch_size * options.gradient_accumulation}
    report["dataset"] = validate_dataset(options.data_json, options.dataset_root, options.dataset_manifest)
    report["parent"] = validate_parent(options.base_model, options.adapter, options.parent_manifest)
    report["code"] = {"runner": file_record(__file__), "upstream": validate_upstream(options.upstream)}
    report["config_sha256"] = canonical_hash(report["config"])
    if options.validate_only:
        report.update(status="contracts_validated", stage="execution_not_run")
        print(json.dumps(report, indent=2, allow_nan=False))
        return 0
    if options.output.exists():
        raise ContractError("Output already exists; use a new run directory, never overwrite a prior attempt")
    options.output.mkdir(parents=True)
    write_json(options.output / "report.json", report)
    write_json(options.output / "config.resolved.json", report["config"])
    try:
        run_training(options, report)
    except BaseException as exc:
        report.update(status="failed", failed_at_utc=now(), error={"type": type(exc).__name__, "message": str(exc)})
        write_json(options.output / "report.json", report)
        (options.output / "failure.traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    print(json.dumps({"status": report["status"], "optimizer_steps": report["completed_optimizer_steps"],
                      "output": str(options.output), "research_claim": report["research_claim"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
