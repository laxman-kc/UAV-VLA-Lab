# Continued AeroVLA adapter training

`scripts/train_adapter_mvp.py` implements P10 training mechanics and a fixed-budget P12 candidate. P10 defaults to one sample, one microbatch and exactly one optimizer update. A changed checkpoint establishes that the training path works; development evaluation must establish whether the candidate is useful.

The runner is implemented and covered by synthetic contract tests. It has **not** yet trained AeroVLA on the Brev host. Actual execution requires an approved supervision source, a validated dataset release and the recorded parent model files. Test fixtures are never dataset or model evidence.

## Required inputs

Use the existing CUDA runtime with one visible BF16-capable GPU. Stop the simulator before launch and record that operational check. The runner does not stop other processes, install packages, download model files or contact the Hub. Use a new output directory for every attempt.

The local base model and released adapter must have complete inventories with SHA256 and size, including their custom Python and configuration files. `--upstream` must contain the exact dataset and trainer source from AeroVLA commit `e37685afb8953d1f5a09155d7255960cee1bfd9d`; both source hashes are enforced by the runner. The base model's custom code is trusted only as the explicitly inventoried local snapshot.

The dataset reader's constructor is `AeroVLADataset(data_root, clean_json_path, tokenizer, processor)`. Its JSON input is an array of rows with `traj_rel_dir`, `img_name`, `instruction`, `label.fwd`, `label.down`, `label.yaw`, `is_last_step` and `is_penultimate`. The reader loads `frontcamera/<img_name>` and `downcamera/<img_name>` inside the trajectory directory, combines the views, and produces `image`, `text`, `prompt_only`. The runner imports that verified reader unchanged. [Pinned dataset reader](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/src/aerovla_dataset.py).

The published collator is nested inside `main()`. The runner extracts and executes only that exact function's AST from the verified trainer. It never invokes the trainer's fresh-LoRA path. A wrapper rejects truncation, a prompt/action token-boundary mismatch, incomplete prompt masking or supervised padding. It does not silently change the target or masking to make a failing sample pass. [Pinned trainer and collator](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/src/train_aerovla.py).

## Dataset manifest contract

The following is a **schema illustration**, with placeholders. It is not an approved dataset. Create a real manifest only from actual reviewed source evidence. File references in `data_json`, `split_manifest` and `approval.evidence` are relative to the manifest's directory. Copy the frozen split/review files into that release directory. Image and per-sample source references are relative to `--dataset-root`. Absolute paths, `..` and escaping symlinks are rejected.

```json
{
  "schema_version": "vla.training-dataset.v1",
  "status": "validated",
  "data_json": {"path": "train.json", "sha256": "<actual SHA256>", "bytes": 0},
  "split_manifest": {"path": "splits.json", "sha256": "<actual SHA256>"},
  "label_policy": {
    "source_kind": "human_expert",
    "source_description": "<actual expert/source and method>",
    "action_units": {"fwd": "m", "down": "m", "yaw": "rad"},
    "action_frame": "<actual coordinate convention>",
    "action_horizon": "<actual interval/horizon specification>",
    "stop_semantics": "<meaning and source of final/penultimate flags>",
    "temporal_alignment": "<how observation, state and subsequent target action align>"
  },
  "approval": {
    "status": "approved",
    "reviewer": "<actual reviewer>",
    "reviewed_at_utc": "<actual review time>",
    "evidence": {"path": "review.json", "sha256": "<actual SHA256>"}
  },
  "samples": [{
    "row_index": 0,
    "row_sha256": "<canonical hash of the complete actual JSON row>",
    "sample_id": "<stable actual sample ID>",
    "episode_id": "Map/episode/merged_data.json",
    "split": "train",
    "images": {
      "front": {"path": "Map/episode/frontcamera/000001.png", "sha256": "<actual SHA256>"},
      "down": {"path": "Map/episode/downcamera/000001.png", "sha256": "<actual SHA256>"}
    },
    "source_evidence": [
      {"path": "Map/episode/log/000001.json", "sha256": "<actual SHA256>"},
      {"path": "Map/episode/reviewed_action.json", "sha256": "<actual SHA256>"}
    ]
  }]
}
```

`source_kind` must be `human_expert`, `audited_reference_expert` or `approved_controller_expert`. This is a provenance declaration backed by the referenced review, not automatic expert certification. Ordinary model predictions cannot be relabeled as expert evidence. The program checks declared provenance and exact bytes; semantic correctness still depends on the review.

The split file uses the existing `vla.splits.v1` schema, with `frozen_at_utc` and `groups.train`, `groups.development`, `groups.holdout`; any additional groups must also remain disjoint. Each entry is `Map/episode/merged_data.json`. Every frame from a training row must belong to a training episode. Duplicate samples, duplicate image pairs, altered row hashes, changed source files and split overlap are rejected. Project split isolation does not establish absence from the released model's original training data.

Canonical row hashes use SHA256 of UTF-8 JSON produced by `json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)`. Whole-file hashes cover the exact saved bytes. Optional `bytes` fields must be the actual size, never the placeholder zero above.

The runner requires finite reviewed physical labels inside the upstream ranges: forward `[0,5]` metres, down `[-5,5]` metres and yaw `[-1.1,1.1]` radians. It rejects out-of-range inputs so the reader's clipping cannot hide invalid labels. Stop flags must be explicit booleans. No labels, missing images, timestamps, stop flags or instructions are invented.

## Parent checkpoint contract

This is another **schema illustration**, not a recorded parent checkpoint:

```json
{
  "schema_version": "vla.adapter-parent.v1",
  "checkpoint_id": "<actual released revision or prior checkpoint ID>",
  "preserve_projector": true,
  "base": {
    "identity": "openvla/openvla-7b@<verified revision>",
    "files": [{"path": "config.json", "sha256": "<actual SHA256>", "bytes": 0}]
  },
  "adapter": {
    "identity": "XuPeng23/AerialVLA@<verified revision>/aero_vla",
    "files": [{"path": "adapter_config.json", "sha256": "<actual SHA256>", "bytes": 0}]
  }
}
```

Both `files` arrays must contain **all** actual files under their respective model roots, excluding `.cache` directories. The short arrays above are incomplete placeholders. Paths are relative to `--base-model` and `--adapter`, respectively. The adapter must have `adapter_model.safetensors`, PEFT type `LORA`, task type `CAUSAL_LM`, `bias: none`, and `modules_to_save: ["projector"]`.

To adapt the existing acquisition receipts, start with `model-files.verified.json`. Each row already records `repository`, `revision`, `relative_path`, `sha256` and `bytes`; `model-download-manifest.json` records repository revisions and folders. Group rows by base/adapter root, strip exactly `openvla-7b/` or `AerialVLA/aero_vla/` from `relative_path`, and retain its hash and size. Derive `identity` from the actual recorded repository/revision. Do not substitute current Hub revisions or omit inventoried custom code. Preserve both original receipts with the phase evidence.

Loading uses `PeftModel.from_pretrained(..., is_trainable=True)` and the existing adapter configuration. There is no new `LoraConfig` or automatic fresh adapter. Only LoRA A/B and the saved projector copy may be trainable. After converting these parameter copies to FP32, the runner reapplies the exact parent safetensor values and verifies every adapter/projector key and value before updating. It freezes the base. This avoids silently losing parent precision when PEFT initially loads into BF16 destination modules. [PEFT 0.11.1 loading and saving implementation](https://github.com/huggingface/peft/blob/v0.11.1/src/peft/peft_model.py), [PEFT adapter state mapping](https://github.com/huggingface/peft/blob/v0.11.1/src/peft/utils/save_and_load.py).

Both the pinned trainer and inference wrapper resize base embeddings to the base tokenizer length. This runner permits equal size or removal of padded unused rows and records the observed dimensions. It rejects adding randomly initialized embedding rows. Missing EOS tokens also fail rather than adding a token. If a pad token is absent, it uses the existing EOS token, as upstream does. [Pinned inference wrapper](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/src/model_wrapper/aerovla_wrapper_ui.py).

## Run and inspect P10

Replace the path and numeric placeholders below with the actual reviewed configuration. Choose the learning rate and seed explicitly. Run `--validate-only` first; it checks contracts without importing ML libraries, creating an output directory or training. It still hashes all parent model files, which takes disk I/O time.

```bash
python scripts/train_adapter_mvp.py \
  --base-model "$VLA_BASE_MODEL" \
  --adapter "$VLA_PARENT_ADAPTER" \
  --parent-manifest "$VLA_PARENT_MANIFEST" \
  --data-json "$VLA_TRAIN_JSON" \
  --dataset-root "$VLA_DATASET_ROOT" \
  --dataset-manifest "$VLA_DATASET_MANIFEST" \
  --upstream "$VLA_UPSTREAM" \
  --output "$VLA_NEW_TRAINING_RUN" \
  --phase P10 --steps 1 --batch-size 1 --gradient-accumulation 1 \
  --learning-rate "$VLA_LEARNING_RATE" --seed "$VLA_SEED" \
  --validate-only
```

After validation and the simulator/GPU operational check, run the same arguments without `--validate-only`, recording the actual terminal output in the phase evidence. The default operational disk reserve is 60 GiB. The runner requires a new directory, exactly one visible CUDA GPU and BF16 support. An SSH disconnect does not establish completion; inspect `report.json` and the durable remote session before starting another attempt.

The runtime first checks the actual reader/collator output for every approved sample. It then enables gradient checkpointing with `use_reentrant=False`, keeps the frozen base in BF16, and uses BF16 autocast with FP32 trainable parameters and AdamW state. It records all trainable names, shapes and dtypes. Every optimizer step requires finite loss, present/finite gradients for every intended trainable tensor, a nonzero overall gradient norm, and finite resulting weights. Gradient accumulation divides each microbatch loss by the configured accumulation count, matching the reference method. Microbatch loss means are not token-weighted estimates.

After the budget, both LoRA and projector must contain changed tensor hashes. The runner saves the adapter/projector, tokenizer and processor, removes training/optimizer/model references, collects garbage and clears the CUDA cache. Only then does it load another base-plus-candidate model for inference. Exact saved adapter/projector hashes must match. Teacher-forced loss and the final-position full-vocabulary logits on the fixed first training sample are recorded before training, after training and after reload. Reload comparisons use the predeclared absolute and relative tolerances (both default `1e-5`). These are serialization/numerical checks, not generated navigation success or improvement metrics.

Inspect `report.json`, `trainable-tensors.json`, `adapter-before.json`, `adapter-after.json`, `steps.jsonl`, the three `prediction-*.safetensors`, and `checkpoint-manifest.json`. The step log contains actual sample IDs and exposure counts, losses, gradient norms, synchronized elapsed times and GPU memory. The successful checkpoint manifest records parent, dataset, config and code hashes; `mechanics_verified` means only that the stated engineering checks passed. A failure preserves the partial report and traceback and does not produce a successful manifest.

## P12 fixed budget and failure handling

Use a separate run directory, `--phase P12`, and a positive explicit `--steps` value chosen from P10 measurements. Set batch size, accumulation, learning rate and seed before launch. The effective example batch is `batch_size × gradient_accumulation` on the one GPU. Row order is shuffled from the seed and repeats at dataset boundaries; exact sampled row IDs and repeats are logged. Small datasets therefore may be revisited many times, which is exposure rather than new supervision.

This runner saves one fixed final-step candidate. It uses a constant learning rate, AdamW betas `(0.9,0.999)`, epsilon `1e-8`, default weight decay `0.03`, default clipping norm `1`, and zero loader workers. These are explicit implementation settings, not an optimality claim. It does not inspect development or holdout outcomes and does not select the best checkpoint. P13 evaluates the candidate under the frozen development protocol. Add `--max-wall-seconds` to stop before the next step once the declared wall budget is exhausted; an in-flight step is allowed to finish.

An out-of-memory error, nonfinite value, missing gradient, exhausted storage reserve or failed reload stops the attempt. No automatic batch reduction, retry, changed precision, changed learning rate or fresh LoRA initialization occurs. Use the report to revise a subsequent predeclared configuration in a new run directory. This implementation saves adapter continuation artifacts, not optimizer/scheduler/RNG resume state; it must not be described as an exact interrupted-run resume.

Run the contract tests locally with:

```bash
python3 -m unittest discover -s tests -p test_training_contract.py -v
```

These tests cover identity changes, leakage, provenance gates, label bounds, loss boundaries, intended trainables and bounded configuration. GPU loading, actual gradients, memory feasibility and save/reload numerics remain required execution checks on the real authorized data and model.
