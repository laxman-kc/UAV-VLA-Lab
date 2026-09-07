# Audit publisher reference-label alignment

`scripts/audit_reference_alignment.py` independently checks whether unchanged prepared publisher labels agree with recorded poses separated by five consecutive numeric raw-log identifiers. This is a source and numerical audit. It does not launch a simulator, load a policy, train, rewrite labels, approve an expert, or certify recovery behavior.

The audit applies this explicit hypothesis to every prepared row:

```text
d = R(q_i).inv().apply(p_(i+5) - p_i)
fwd = d.x
down = d.z
yaw = (R(q_i).inv() * R(q_(i+5))).as_euler('zyx')[0]
```

The implementation uses the configured NumPy/SciPy environment and records package versions. Quaternions are supplied as xyzw; SciPy normalizes them, and their original norms remain in the report. The absolute residual tolerance is fixed at `1e-9` for each of the three label components. A mismatch is preserved as a rejection. The auditor does not search for a better offset, alter a row, or select replacements by residual.

The reference provenance comes from the [pinned publisher JSON](https://huggingface.co/XuPeng23/AerialVLA/resolve/196f2f3253b69df6e90ac10b6ae041c7b3a9569e/aerovla_train_dataset.json) and the [pinned official training split](https://huggingface.co/datasets/wangxiangyu0814/TravelUAV_data_json/resolve/5a1ed4c99d3e7bb2b35fa34135910cb7687fc831/data/uav_dataset/trainset.json). Both complete files must match the recorded hashes. Every prepared row must equal its exact publisher source index and canonical row hash, belong to the frozen official/project training split, and preserve its current image/state file identities. The original five-row preparation remains an unmodified historical artifact.

## Run the existing five-row audit

Supply current absolute paths explicitly. Historical absolute paths inside the preparation manifest are retained; their hashes and sizes bind each supplied local equivalent. Placeholders below are not host configuration.

```sh
python scripts/audit_reference_alignment.py \
  --data-json /absolute/prepared-five/published_rows.json \
  --dataset-root /absolute/dataset_raw \
  --reference-manifest /absolute/prepared-five/reference_manifest.json \
  --published-manifest /absolute/aerovla_train_dataset.json \
  --official-train-json /absolute/official-trainset.json \
  --frozen-split /absolute/modern_city_map_v1.json \
  --audit-report /absolute/published-training-audit.json \
  --upstream /absolute/pinned/AeroVLA \
  --output-dir /absolute/new-reference-alignment-audit
```

The output directory must be new. The auditor verifies the exact source pins, original reader/trainer, wrapper and controller source bytes; only the previously documented cancellation propagation rewrite is accepted. It records its own code and imported preparer helper. The plan-free source audit does not authorize collection or training.

Each current row must have both original terminal flags false, finite labels inside the reader's ranges, a numeric six-digit PNG filename, the actual current and future front/down images, and all six raw log files `i` through `i+5`. Each log's `frame` must match its filename. This establishes five consecutive **record increments**. No timestamp values or physical duration are synthesized. If a raw timestamp field exists it is retained without inferring its units; `physical_horizon_seconds` remains null.

For a separately prepared twenty-row extension, pass `--expected-count 20` and `--excluded-prior-manifest /absolute/prepared-five/reference_manifest.json`. The explicit `vla.published-reference-extension.v1` schema must bind the same pinned sources, prepared rows, sample/current/future file records, and an exclusion receipt for the five prior mission identities. The auditor checks no mission overlap. Preparation chooses the extension before this audit; no alignment result can change its selected rows. The existing P10 five-row preparer/validator is not repurposed for this extension.

## Interpret the result

`report.json` contains exact source/path mappings, unchanged row identities, all six raw-log hashes, actual current/future poses and paired-image hashes, per-axis residuals, and every failure. It separately reports body-frame lateral displacement, relative pitch/roll, and both continuous and quantized nominal-controller displacement residuals.

That distinction matters because the [released controller](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/airsim_plugin/AirVLNSimulatorClientTool_AeroVLA.py#L299) uses its cached absolute `zyx` yaw plus the action delta, rotates first, then translates in world NED; decoded yaw magnitude at least 0.25 suppresses forward translation. A source body-frame x/z difference with omitted y and relative tilt is therefore not generally the same displacement as the controller's nominal command. The [reader's quantization](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/src/aerovla_dataset.py) introduces another difference. The auditor executes only the pinned pure codec methods to report that difference; it never executes motion. Nominal residuals are diagnostics, not hidden label-selection gates or measured flight errors.

Exit zero means all prepared rows passed this measured alignment audit. Exit 2 means at least one row was rejected; exit 1 means provenance or audit execution failed. `approval` remains `not_asserted` in every case. Numerical agreement supports the stated formula for the observed rows; it does not prove the publisher's original generator code, alignment of every released label, clock duration, optimality, collision-free reference paths, or which examples trained the released weights.

Any later dataset approval requires a separate, hash-linked review of the actual observations and alignment evidence, the retained omitted-component/controller differences, nonterminal meaning, and intended ordinary-demonstration use. It must describe its reviewer accurately. These source demonstrations must not be presented as newly collected model-failure corrections or human-certified expertise. The [training contract](training.md) remains unchanged.

The evidence video should show the actual current and future image pairs, record IDs, measured published/inferred triples and residuals. Display them as disclosed recorded observation holds. Missing time metadata precludes claiming real-time or uninterrupted flight playback.
