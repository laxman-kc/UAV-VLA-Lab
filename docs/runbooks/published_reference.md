# Published-reference preparation and P10 mechanics

This is a narrow reproduction path for the existing all-phase implementation
scope. It prepares five unchanged publisher-provided examples from separate
official training episodes, then permits P10's one-update/save/reload engineering
check through an explicit supervision mode. It does not certify expert actions,
construct recovery corrections, complete P09, or permit this reference mode in
P12. The user's outstanding correction-source decision remains separate.

## What the present evidence establishes

The recorded `published-training-audit-v1.json` found 410,450 published rows. For
ModernCityMap, 13,715 rows represent the 594 frozen official training episodes;
the audit found no published rows in the project's demo, development, holdout or
unassigned groups. It found 766 invalid/out-of-range labels under the strict
training bounds. Its filename checks found both policy views available for the
selected map. These are source-membership/schema/file-existence findings, not
image review, action correctness or a record of which rows trained the released
weights. Preparation rechecks the relevant actual source and file identities.

The author repository instructs users to obtain this training JSON from its
Hugging Face repository. The pinned reader consumes the supplied numeric labels
and terminal flags directly. The inspected source does not expose an input field
that specifies the physical action horizon. The constructor takes the data root,
JSON path, tokenizer and processor. [Pinned author instructions](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/README.md),
[pinned dataset reader](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/src/aerovla_dataset.py).

An unknown physical horizon therefore does not prevent the computational check
of loading these exact targets, evaluating the original loss, receiving finite
gradients, changing intended weights and preserving them through save/reload.
This is an inference from the reader/training interface, not evidence about how
the publisher originally generated physically correct actions. Do not infer that
horizon from the controller's variable execution duration or adjacent filenames.
The artifact records the physical horizon/frame as unknown.

P09 still needs an expert/correction source, defined coordinate frame and horizon,
observation/state/action alignment, stop semantics and review of actual labels.
Original policy outputs do not acquire expert status because their run succeeded
or because they were saved with an outcome. The pasted research proposal's
failure → expert correction loop remains a later data-construction task.

## Required existing local source files

`scripts/prepare_published_reference.py` performs no downloads or GPU work. Supply
these already acquired files and an existing raw-data root:

| Source | Required identity |
|---|---|
| Publisher training manifest | `XuPeng23/AerialVLA`, revision `196f2f3253b69df6e90ac10b6ae041c7b3a9569e`, `aerovla_train_dataset.json`; 257,288,037 bytes; SHA256 `1c1e32787cedb096fe5df2511e5bf3cc81901b8a30d261df73ebcb800c868a67` |
| Official TravelUAV training split | `wangxiangyu0814/TravelUAV_data_json`, revision `5a1ed4c99d3e7bb2b35fa34135910cb7687fc831`, `data/uav_dataset/trainset.json`; SHA256 `5c1c82df9f3b2b351499bcbcce7af02e17445e9e931f5569d546aefd4ce5eb8c` |
| Frozen project split | Existing `vla.splits.v1` manifest whose exact SHA256 is referenced by the published audit |
| Published audit | `vla.published-training-audit.v1`, status `audit_completed_not_label_approval`, matching source identities and memberships |
| Original reader and trainer | AeroVLA commit `e37685afb8953d1f5a09155d7255960cee1bfd9d`; the same two exact file hashes enforced by the training runner |
| Raw observations | Existing `frontcamera/<img_name>` and `downcamera/<img_name>` for eligible official training rows |

The publisher's immutable file identity is linked in the generated manifest to
its [pinned release file](https://huggingface.co/XuPeng23/AerialVLA/blob/196f2f3253b69df6e90ac10b6ae041c7b3a9569e/aerovla_train_dataset.json).
The program enforces the actual source bytes rather than relying on a current
branch name or assuming that a download succeeded.

## Opt-in preparation

Resolve every placeholder to the actual existing file/directory. The output must
be new; the opt-in chooses published-reference preparation, not expert approval.

```sh
python /actual/project/scripts/prepare_published_reference.py \
  --source /actual/aerovla_train_dataset.json \
  --official-train-json /actual/original/trainset.json \
  --frozen-split /actual/project/configs/splits/modern_city_map_v1.json \
  --audit-report /actual/published-training-audit/report.json \
  --dataset-root /actual/dataset_raw \
  --upstream /actual/AeroVLA \
  --output-dir /actual/new/published-reference-five \
  --opt-in-published-reference-preparation
```

The selector verifies that frozen train membership exactly equals the selected
map's membership in the actual original official training split. All project
groups must be disjoint. It scans publisher membership to check the recorded
audit, then inspects labels and file availability only for frozen training rows.
It never reads or hashes evaluation/holdout image or state files.

Eligible rows must retain the exact publisher schema, a nonempty instruction,
explicit boolean terminal flags, finite labels within forward `[0,5]`, down
`[-5,5]`, yaw `[-1.1,1.1]`, canonical contained paths, both original policy image
files, and a nonduplicated image pair. Invalid rows are rejected and counted by
reason. No label is clipped, repaired, generated or substituted.

Selection is deterministic under the recorded rule
`aerovla-published-reference-five-v1`: rank eligible official train episode IDs by
the documented SHA256 key, take five distinct episodes, then choose each
episode's minimum-ranked eligible image filename. It uses no model outputs,
development/holdout outcomes, pixel contents, terminal balancing or manual
selection. Fewer than five eligible episodes causes failure rather than
duplicating examples or fabricating replacements.

Only the ten selected image files are read for content hashes; they are not
decoded or rendered here. If a selected image has an existing same-stem
`log/<stem>.json`, its hash is recorded as optional provenance. That filename
correspondence is not proof of the action's time interval or label/state alignment.
The original dataset reader itself does not use that log file.

Outputs are `published_rows.json`, `reference_manifest.json`, `splits.json`,
`rejected_rows.json` and `checksums.json`. Each selected row is exactly equal to its
original publisher row and records the original zero-based source index and
canonical hash. All source, selected image/state, code and output hashes are
preserved. The manifest uses `vla.published-reference-preparation.v1` with status
`prepared_published_reference_not_expert_approved`; `approval.status` is
`not_asserted`, and `p09_expert_correction_complete` is `false`.

The original reader will resize RGB front/down views to 224×224, put front above
down, quantize each bounded scalar using 99 bins, and append `LAND` if either
terminal flag is true. It then appends the tokenizer EOS. Preparation preserves
these reader inputs; it does not execute or replace the reader/processor. Actual
image decoding, tokenizer/collator boundaries and absence of target truncation
are checked during the real P10 run.

## Explicit P10 mode

Use the parent checkpoint and operational checks in the [training runbook](training.md).
Supply `published_rows.json` as `--data-json` and `reference_manifest.json` as
`--dataset-manifest`, plus:

```sh
--phase P10 --steps 1 \
--supervision-mode published-reference-mechanics \
--batch-size 1 --gradient-accumulation 1
```

First add `--validate-only` to the otherwise complete training command. The
validator rechecks authoritative source bytes, exact official train membership,
deterministic selection, unchanged rows, image hashes, rejection accounting and
the explicit unknown-horizon/no-expert-approval scope. Changing the prepared file
hash alone cannot authorize altered rows. The current actual source files must
remain available for this revalidation. No ML libraries or GPU work are invoked
by contract-only validation, although hashing/parsing the existing source JSON
requires disk I/O and host memory.

After recording the parent files, seed, learning rate and operational state, the
real P10 run continues the released adapter/projector, checks one optimizer
update and reloads it through the existing separate-model lifecycle. All five
examples receive actual reader/collator validation; batch size one and one
accumulation microbatch use one seeded sample for the optimizer update. The
report records that actual exposure. A five-row prepared dataset is not five
optimizer updates or evidence of learning improvement.

The default remains `--supervision-mode reviewed-expert`, which rejects this
reference schema. `--phase P12 --supervision-mode published-reference-mechanics`
is rejected. The checkpoint report preserves its narrow P10 purpose, unknown
physical horizon and incomplete P09 correction status. Ordinary source-level
execution authorization does not become an invented human/expert approval field.

## Paths to completing actual correction data

- A documented publisher-label construction method could support a separately
  reviewed reference-expert contract if its frame, horizon, state alignment and
  stop meanings are established. File membership alone is insufficient.
- Human corrections can use actual training-mission observations/state, with
  explicitly defined action duration/frame and a recorded review of each target.
- A separately selected and validated controller can produce supervised targets
  under an explicit controller-expert contract. Its rollout and control horizon
  must be recorded; neither current policy actions nor inferred displacements
  are silently promoted to that role.

These alternatives resolve the existing correction-source gate. They are not
selected or approved by this preparation script, and this narrow P10 path does
not expand P11/P12 dataset scope.

## Focused software checks

```sh
python3 -m unittest discover -s tests -p test_published_reference.py -v
python3 -m unittest discover -s tests -p test_training_contract.py -v
python3 -m py_compile scripts/prepare_published_reference.py scripts/train_adapter_mvp.py
```

The tests use synthetic source pins and temporary file bytes, including invalid
labels. They verify provenance, deterministic five-episode selection, unchanged
targets, rejection behavior, hashes, scope declarations and P10/P12 mode gates.
They neither prepare a real publisher subset nor execute model training.
