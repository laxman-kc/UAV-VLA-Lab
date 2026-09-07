# P11: twenty new unchanged published references

`scripts/prepare_reference_extension.py` prepares a separate, opt-in set of twenty rows under `vla.published-reference-extension.v1`. The existing five-example P10 preparer, its schema and recorded experiment remain unchanged. This step prepares ordinary publisher-reference examples for subsequent review; it does not train, grant expert approval, complete P09 correction or establish useful learning.

The selection rule is frozen here before actual selection: `aerovla-reference-extension-twenty-v1`. Rank eligible official-training episode paths by ascending hexadecimal `SHA256(rule + "\n" + "episode" + "\n" + episode)`, with episode-string ties. Exclude all five prior episodes in full, then take the first twenty distinct eligible episodes. Within each, choose the minimum `SHA256(rule + "\n" + "image" + "\n" + episode + "\n" + img_name)`, breaking ties by filename and publisher source-row index. No target-alignment result, policy prediction, evaluation outcome or rendered pixel content participates in ranking or eligibility.

Eligibility is deliberately limited to these checks:

- The existing exact publisher row schema, instruction, numeric label bounds and original front/down file presence checks pass.
- Both `is_last_step` and `is_penultimate` are actual boolean false. True terminal flags and malformed flags are recorded as rejections.
- `img_name` matches exactly six ASCII digits followed by lowercase `.png`, matching the independent alignment auditor's supported filename contract. Short/long numeric stems, JPG and uppercase PNG names are rejected before selection.
- Both current and filename-index `i+5` front/down views exist, and all six raw log files `i, i+1, …, i+5` exist. The extension does not parse those logs or inspect their numeric agreement with labels.
- Duplicate publisher image-pair rows are rejected. The row belongs to the full authenticated frozen official training membership and is outside all five prior episodes.

The six-file window is a declared input requirement for the separate alignment audit. Its existence does not by itself establish a physical horizon, label-generation formula, controller correctness or expert/recovery truth. The supplied labels, instructions and flags are never changed, clipped, regenerated or replaced. Serialization formats the selected JSON rows; their parsed values and canonical row hashes remain identical to the authenticated source rows.

## Source and prior-five authentication

The implementation reuses the pinned `PUBLISHED`, `OFFICIAL_TRAIN`, `UPSTREAM_REVISION`, `UPSTREAM_FILES`, `validate_split`, `row_reasons` and `file_record` contracts from the original preparer. It hashes the full publisher manifest and official training JSON, verifies the inspected upstream dataset/trainer source, recomputes exact frozen training membership and split disjointness, and checks the source audit's row counts and every project-overlap count. The source audit must retain `audit_completed_not_label_approval` status.

The prior manifest must retain the original five-reference schema, rule identity, label-policy limits, actual creation time and unasserted approval. Its publisher, official-training, input, data-row and split-snapshot identities must match the supplied sources. Each of the five prior sample rows is checked against its exact publisher source index and canonical hash, with matching sample identity, distinct training episode, current image hashes and any recorded state hash. The original preparer source digest must still match. These checks authenticate the supplied prior example set and its source bytes; they do not rerun the old experiment or infer expert correctness from it.

The tool reads metadata for split membership, and file presence/hash data only for training examples. It never opens evaluation/holdout image or log files. All rejected training rows, including every row from excluded prior episodes, are retained in the ledger with source-row index, episode, filename and reasons. Other-map publisher rows are not new training candidates. No replacement by a manually preferred episode is supported.

## Prepare a new immutable directory

```sh
python scripts/prepare_reference_extension.py \
  --source sources/aerovla_train_dataset.json \
  --official-train-json sources/trainset.json \
  --frozen-split configs/splits/modern_city_map_v1.json \
  --audit-report source-audit.json \
  --dataset-root raw-dataset \
  --upstream pinned-AeroVLA \
  --prior-manifest prior-five/reference_manifest.json \
  --prior-data-json prior-five/published_rows.json \
  --output-dir reference-extension-twenty \
  --opt-in-published-reference-extension
```

Paths above are placeholders, not a recorded command or execution receipt. The explicit opt-in authorizes preparation only and does not assert label approval. The output directory must not exist. Fewer than twenty new eligible episodes, altered provenance, changed prior bytes or a changed source snapshot rejects preparation instead of reducing the sample count or changing the rule.

The output consists of `published_rows.json`, `reference_manifest.json`, `rejected_rows.json`, `splits.json` and `checksums.json`. The manifest has an actual creation time and source/preparer digests. It keeps the original schema-compatible `inputs` records for publisher/official/frozen-split/source-audit, exact publisher and official identities, upstream revision, twenty `samples`, `data_json`, `split_manifest`, and `approval: {"status": "not_asserted"}`. `excluded_prior_manifest`, `excluded_prior_data_json` and `excluded_episode_ids` bind the five-episode exclusion.

Every sample records its row index, publisher source index, source/export canonical hashes, sample ID, episode, training split and ranks. `images` and `future_images` map front/down to relative path/hash/byte records. `state_file` and `future_state_file` are current/`i+5` records. `state_sequence_files` contains all six relative path/hash/byte records plus `frame_index` and `offset`. `filename_offset_for_alignment_audit: 5` is an audit-input declaration, not an inferred physical-time claim.

Source, code, prior-five and selected-file bytes are checked again before writing. `validate_extension(data_json, dataset_root, manifest_path)` recomputes the source/selection, validates all selected file hashes and compares exported rows, exclusion, split snapshot and rejection ledger. Future raw-file additions or removals that change eligibility can change the recomputed selection; preserve the actual dataset snapshot and its rejection ledger.

## Independent audit and subsequent use

After selection is frozen, run the independent alignment auditor on the exact manifest and exported rows, with `--expected-count 20` and the actual excluded prior manifest. Audit failures stay attached to the frozen selection; do not silently remove failed rows or rerank the sample using alignment results. Any revised eligibility rule requires a separately named, dated preparation and preserved earlier evidence.

This preparer performs no image decoding, tokenizer/collator execution, state-value validation, action-delta computation or training. Synthetic tests deliberately use non-image bytes and unrelated state JSON to verify that selection does not depend on decoding or alignment. Real reader/collator readiness, independent alignment findings, source-policy decisions and any subsequent SFT run need their own evidence. The original P10-only training mode is not broadened by creating this manifest, and the reviewed-expert correction gate remains distinct.

Manifests include source paths and file provenance. They are local evidence artifacts and are not automatically approved for public release.
