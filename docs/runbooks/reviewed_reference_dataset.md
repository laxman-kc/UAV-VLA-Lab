# Package reviewed source demonstrations

`scripts/build_reviewed_reference_dataset.py` packages unchanged publisher examples only when every row is accepted by a passing alignment audit and an existing named independent review. The program checks and copies evidence; it performs no semantic approval, simulator run, model inference, training, or publication. It leaves the original P10 preparation and trainer contract unchanged.

P09 requires one complete five-row original part. P11 requires that original five-row part followed by one complete twenty-row extension. The extension must bind and exclude the original five mission identities. Repeated missions/sample IDs, missing or rejected rows, substituted labels, changed evidence, incomplete reviews, and silent replacements fail packaging.

## Prepare explicit part receipts

Each `--part` points to a JSON document with schema `vla.reviewed-reference-part.v1`. Four required keys, `data_json`, `reference_manifest`, `alignment_report`, and `independent_review`, each contain an actual file record with `path`, `sha256`, and `bytes`. Paths may be absolute current paths or relative to the part document. Historical paths inside the original receipts are preserved; the explicit part maps their exact bytes to current files.

The optional `review_evidence` array supplies the same file records for the named review's supporting calculation, source, inventory, and preserved prior-review files. It becomes required whenever those supporting files are not already covered by the four main inputs or the copied raw/image evidence. Every `independent_review.evidence` hash must be covered. No missing review source is silently treated as available.

The independent review must already have schema `vla.reference-expert-review.v1`, status `approved`, source kind `audited_reference_expert`, an explicit reviewer and timezone-aware review time, `human_review: false`, and a nonempty `qualified_scope`. Its `inputs` must bind the exact prepared data, preparation manifest and alignment report. Every `accepted_samples` entry must identify the exact sample ID, original publisher source-row index, row hash and mission, with `accepted: true`. The review must occur after its actual preparation/alignment inputs and before package assembly. A pending review, mechanical gate alone, or unanswered user question cannot supply approval.

The [alignment audit](reference_alignment.md) must pass for every prepared row using the fixed five-record offset and `1e-9` absolute tolerance. The packager rechecks each row's original hash/source index, finite bounds and false stop flags, frozen training membership, all six raw state hashes/frame IDs, exact endpoint poses, current/future image hashes and per-axis residual declarations. It does not load SciPy or a model to repeat the audit; the immutable audit and named review remain the source of the numerical and semantic conclusions.

## Build and validate

Use actual absolute paths, a dedicated raw-assets root and a new output directory:

```sh
python scripts/build_reviewed_reference_dataset.py \
  --part /absolute/five-reviewed-part.json \
  --dataset-root /absolute/recorded-reference-assets \
  --frozen-split /absolute/modern_city_map_v1.json \
  --phase P09 \
  --output /absolute/new-p09-reviewed-reference-dataset
```

For P11, supply two `--part` arguments in order: original five, then the twenty-row extension; use `--phase P11`. That union preserves the exact first five rows and adds twenty distinct training missions. Any failed input remains in the original preparation/audit report; the packager cannot hide a rejection by dropping its row.

The result contains `train.json`, `dataset_manifest.json`, `splits.json`, `approval_receipt.json`, `training_contract_validation.json`, `packaging_report.json`, and `checksums.json`. `assets/Map/episode` holds the original current and future front/down PNGs, all six raw logs and `source-provenance.json`. `evidence/part-NN` retains exact copies of each preparation, row file, alignment, named review, part receipt and supporting evidence. `implementation` preserves the packager and imported validation helpers used for the build.

The trainer-compatible manifest is `vla.training-dataset.v1` with source kind `audited_reference_expert`. Its approval receipt is explicitly derived from the existing named reviews; assembly creates no new semantic endorsement. The packager calls the unchanged `train_adapter_mvp.validate_dataset` using `train.json`, `assets`, and `dataset_manifest.json`, without loading model libraries. The actual returned receipt is saved. All source bytes are rechecked after copy. A failure preserves the new directory/report and invalidates any manifest already written. Existing directories are never overwritten.

These hashes and new-output rules make the assembled revision auditable; they do not authenticate a reviewer's identity cryptographically or prevent later filesystem changes. Subsequent consumers must verify the retained checksums and trainer contract again.

## Preserve the qualified meaning

These rows are ordinary published projected demonstrations. Forward/down encode source-body x/z displacement, yaw encodes relative quaternion `zyx` yaw, and the horizon is five consecutive raw record increments. Physical elapsed seconds remain unknown. Body lateral motion and relative pitch/roll are omitted; the audit retains them along with differences from the controller's rotate-before-translate, large-yaw and quantized nominal behavior.

Both original stop flags remain false. The corpus supplies no positive LAND examples. Review does not establish physical touchdown, optimal navigation, continuous collision-free execution, exact controller equivalence, new model-failure corrections, human certification, or policy improvement. The dataset card and phase video must carry this scope. Videos should use the actual recorded current/future images with disclosed observation holds and unavailable time fields, without inventing model outputs, commands or flight execution.
