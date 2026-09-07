# Navigation evaluation accounting

`scripts/summarize_navigation.py` reads an explicit trial plan and actual recorded
evidence. It creates a per-episode CSV, every attempt record, conditional metrics,
and a Markdown report. It does not run the simulator, choose episodes, synthesize
outcomes, or convert a successful process exit into navigation success.

Use a separate plan for each checkpoint and runtime. For P08, include all 20
development episodes from the frozen project split, including episodes that
never start. Training, demonstration and holdout episodes must remain in their
declared groups. This tool accounts the supplied plan; it does not independently
certify split membership or that the loaded model bytes match a checkpoint name.

## Freeze the plan before execution

Create and preserve the plan, episode-selection JSON, split manifest, checkpoint
manifest and runtime manifest before the first run. Record the plan hash in the
execution receipt. `frozen_at_utc` is the actual time the plan was frozen. The
summarizer compares that declaration with the recorded run-start time; it cannot
prove that a supplied timestamp was not backdated. A Git commit or independently
stored pre-run receipt provides the separate provenance.

The following is a structural template, not an executable plan or result. Replace
every placeholder with declared paths and identities. The example budget of 200
actions and two observed attempts is illustrative; freeze the actual chosen
values before execution. Paths may be absolute or relative to the plan file.

```json
{
  "schema_version": "vla.navigation-plan.v1",
  "plan_id": "<unique checkpoint-runtime-split plan ID>",
  "frozen_at_utc": "<actual ISO8601 UTC time before execution>",
  "configuration": {
    "checkpoint_id": "<verified checkpoint manifest identity>",
    "model_path": "<exact string passed as evaluator model_path>",
    "runtime_id": "<runtime manifest identity>",
    "require_recorded_runtime_id": true,
    "task_mode": "<declared benchmark-guided task mode>",
    "protocol": "aerovla-e37685a-observed-v1",
    "max_actions": 200
  },
  "retry_policy": {
    "selection": "first_valid_attempt",
    "max_attempts_per_trial": 2
  },
  "trials": [
    {
      "trial_id": "<unique trial ID>",
      "map_name": "<exact hook map_name>",
      "episode_id": "<exact hook episode_id>"
    }
  ],
  "sessions": [
    {
      "session_id": "<unique session ID>",
      "order": 1,
      "trial_ids": ["<unique trial ID>"],
      "evidence_dir": "<actual hook evidence directory>",
      "supervisor_report": "<actual session>/command/report.json",
      "session_report": "<actual session>/report.json"
    }
  ]
}
```

The plan permits each `(map_name, episode_id)` once for its one checkpoint.
Trial/map/episode identifiers are nonempty path components, not trajectory paths.
Each session has a unique positive `order` and explicitly names the planned
trials it was intended to run. An empty or absent `sessions` list is supported
when accounting for a plan that has not started. Sessions may point to expected
files that are absent; that absence remains visible.

Predeclare expected session slots, including retry slots, when practical. Preserve
the original frozen plan and any later operational amendments. Do not remove
unsuccessful sessions, backdate amendments, change the policy/episode selection
after viewing outcomes, or reuse an earlier runtime identity for altered reset
behavior. Keep the manifest and execution receipts alongside the summary.

`runtime_id` is required in the plan. New P08 plans require the same value in
`run.start`; `require_recorded_runtime_id` defaults to `true`. The explicit legacy
override `false` permits an older event stream without the field and reports
`runtime_identity_recorded: false`. A recorded differing value always fails the
gate. This compatibility setting does not permit a different source protocol.
Runtime IDs are labels whose source/package hashes need the separate manifest.

## Prepare a complete frozen evaluation group

`scripts/prepare_evaluation_batch.py` selects an entire existing `development`
or `holdout` membership from the original upstream map evaluation JSON. The
current `modern_city_map_v1.json` declares 20 development and 10 holdout episodes.
The selector derives these counts from the frozen manifest; it does not hardcode
a subset, choose a checkpoint/runtime, or execute an experiment.

With the real paths substituted, prepare the development group as follows:

```sh
python /actual/project/scripts/prepare_evaluation_batch.py \
  --split /actual/AeroVLA/data/uav_dataset/seen_valset_splits/ModernCityMap.json \
  --frozen-split /actual/project/configs/splits/modern_city_map_v1.json \
  --group development \
  --dataset-root /actual/dataset_raw \
  --metadata-root /actual/AeroVLA/data/meta \
  --output-dir /actual/new/development-selection
```

For the holdout phase, use `--group holdout` and a fresh output directory. The
selector reads only the original evaluation row array, frozen membership and
required JSON metadata. It calls the existing `select_and_validate` function from
the sibling `prepare_aerovla_episode.py` for every selected episode, checking the
same merged trajectory initial-state shape, mark/target metadata, instruction
parser format, descriptions and spawn-area availability. No image file is
opened, decoded or rendered, including holdout pixels. Instructions and poses
checked internally are not copied into the selection manifest.

The source evaluation hash, row count and unique-episode count must match frozen
`sources.seen`. All five frozen groups must be explicit, disjoint, duplicate-free
and consistent with their counts. Demo/development/holdout/unassigned membership
must exactly partition the source evaluation episodes; training membership must
not overlap. Every selected episode retains **all original rows in their source
order**, including any extra original row fields. Duplicate trajectory/frame rows,
missing episodes, invalid metadata, source changes during validation, noncanonical
paths and metadata symlinks outside their declared root fail before selection
outputs are created. Metadata is never invented, repaired or silently omitted.

The output directory must be new. It receives `episodes.json`,
`selection_manifest.json`, the exact bytes of `frozen_split.snapshot.json`, and
`checksums.json`. The manifest records the actual creation time separately from
the frozen split time, source hashes, original row indices, per-episode row hashes
and unique loader identities. Checksums cover every other output file. This is a
selection artifact, not navigation evidence or an assertion that the simulator
can load every episode.

Pass the resulting `episodes.json` as the evaluator's `--eval_json_path`. Keep
`--batchSize 1` for the current instrumented protocol: a multi-episode input file
means sequential episodes in one invocation, not simultaneous model inference.
The inspected loader deduplicates trajectory paths, so the number of loaded
episodes is the number of selected unique trajectories, not the frame-row count.
It first sorts unique paths, then normally groups same-map episodes by reference
length. The manifest reports both projected orders from metadata; actual hook
event order remains the execution evidence.

Use a fresh empty evaluator save directory. The upstream loader skips episode
IDs already represented there, which could silently reduce actual coverage of a
reused directory. Use the existing `./dataset_raw/` launch convention described
in the integration runbook. The batch selector supplies metadata; the separate
frozen navigation plan must still name every selected trial, intended session,
checkpoint/runtime identity and operational bounds. Compare actual
`run.start.episode_count` and episode-start records against the entire group.

Focused verification uses temporary synthetic metadata only:

```sh
python3 -m unittest discover -s tests -p test_evaluation_batch.py -v
python3 -m py_compile scripts/prepare_evaluation_batch.py
```

## Evidence contract

The hook evidence directory is the actual `VLA_LAB_EVENT_DIR` or the evaluator's
actual `_vla_lab` directory. It is not the supervisor's own event directory and
is not inferred from the simulation-session output. Expected inputs are:

```text
hook-evidence/
  events.jsonl
  observations/<attempt-id>/<observation-number>/*.png
  outcomes/<attempt-id>.json
  partial/<attempt-id>.json       # when interruption was recorded
session/
  report.json                    # optional session-report declaration
  command/report.json            # required path declaration, may be missing
```

The analyzer supports the inspected `aerovla-e37685a-observed-v1` event protocol,
with hook event `schema_version: 1`, batch size one, and matching `model_path`,
`max_actions`, and runtime identity. Its accepted supervisor and session report
schemas are `vla.supervised_run.v1` and `vla.simulation-session.v1`. Reports retain
their original fields, including child, supervisor and session exit codes.
Report absence/schema errors remain explicit; lifecycle completeness is distinct
from an already recorded, otherwise valid navigation outcome.

A selected navigation outcome requires all of the following:

- A recorded episode start assigned to that session, a unique run/attempt
  identity, and one matching completed event and outcome file.
- All six explicit upstream boolean flags, a finite nonnegative target distance,
  and a terminal loop index inside the declared action budget. The outcome file
  and event must agree; success must satisfy the inspected stop/distance rules.
- The same-attempt observation → prompt → generation → decode → requested
  action → completed action links in their recorded order. The requested action
  must equal its decode. The terminal stop flag must equal the last decode.
- Recorded model output and image evidence. Every referenced image must be
  contained within the hook directory and match its recorded SHA256; both policy
  RGB views must exist. This is a byte-integrity check, not image decoding or
  visual review.
- Complete action/observation counts consistent with the inspected loop: terminal
  loop index `t` equals completed actions, with `t + 1` prepared observations.
  A model-free probe or a zero-generation terminal record is not scored by this
  model-navigation contract.

The script retains malformed JSONL lines, partial JSONs, missing files, raw flags,
nonfinite values and original outcome bodies in the summary. Nonfinite numbers
are preserved as explicit `invalid_nonfinite_number` objects so output JSON stays
standard. A malformed line inside an attempt invalidates it. A trailing malformed
line after a complete validated episode remains an error without erasing that
earlier outcome. Copied evidence declared twice is rejected for both copies.

Sources are hashed and then checked again for changes before selection. If an
observed source changes while summarizing, navigation scores are withheld; rerun
against stable evidence. Output sources are read-only and never repaired. Only
the fresh requested output directory is written.

## Attempts, retries and denominators

An observed navigation attempt means an actual hook `episode.start`, not manager
readiness, scene launch, or physical movement. A reset error after episode start
is therefore an interrupted attempt even if the vehicle never moved. A manager
startup failure creates a declared-session-slot record with
`navigation_attempt_observed: false`; it does not consume the observed-attempt
cap. The separate planned session list and session process issues expose these
startup failures. Keep wall-time/session bounds in the execution configuration.

Sessions are ordered by the frozen `order`, then by recorded episode-start order.
The first valid completed outcome **within the declared observed-attempt cap** is
selected, including a valid navigation failure. A later success cannot replace
it. Valid outcomes beyond the cap remain visible and unscored; excess retries and
retries after a valid outcome are reported as deviations. Missing evidence is
never treated as a zero or a failed navigation outcome.

`trials.csv` contains every planned trial, its observed attempt count, distinct
declared session slots, valid attempts, selected attempt, flags, target distance,
and mechanically supported categories. `attempts.jsonl` also includes unassigned
starts, orphan outcome files, and planned session slots without a recorded start.
Use `navigation_attempt_observed` to distinguish actual starts from these other
accounting records. `selected_valid_trials / planned_unique_episode_trials` is
coverage; publish it beside every conditional navigation rate.

| Metric | Numerator | Denominator |
|---|---|---|
| Upstream SR | Selected `success == true` | Selected valid unique planned trials |
| Upstream OSR | Selected `success OR oracle_success` | Same selected valid trials |
| Upstream collision-flag rate | Selected `collisions == true` | Same selected valid trials |
| Terminal endpoint contact rate | Explicit terminal `has_collided == true` | Selected valid trials with known terminal contact boolean |
| Any recorded endpoint contact rate | At least one recorded endpoint reports contact | Selected valid trials whose sampled status is decidable |

For sampled contact, any `true` establishes a recorded contact. `false` requires
all recorded endpoint contact values to be explicit `false`; otherwise the
trial's sampled contact result is unavailable. This never establishes that no
contact occurred between samples. The five duplicate endpoint records returned
by one action contribute only the last endpoint record, not five independent
observations. Observation/action/outcome records can still refer to the same
physical timestamp, and their counts are labeled as records.

The report provides a descriptive 95% Wilson binomial interval only for metrics
with at least two known selected unique trials. A one-trial result is a count.
Same-map fixed trials, dependencies between episodes and exclusions caused by
invalid runs limit statistical generalization. These intervals do not establish
learning improvement or significance of a checkpoint comparison.

A crash before a completed outcome receives no score. A later crash, interrupted
subsequent episode, or cleanup failure does not erase an earlier independently
validated completed episode. The session failure remains reported beside it.

## Meaning of the upstream flags

The pinned loop calls its termination check before the next action. Upstream
success requires a model stop while within 20 metres of the spawned target and
without the `early_end` flag, subject to the upstream done gating. The result is
a navigation criterion, not a verified physical landing. OSR includes success as
well as the separate oracle flag because upstream directory-prefix counting does
so. See the pinned [evaluation loop](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/src/vlnce_src/eval_aerovla.py)
and [termination/metric state](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/src/vlnce_src/closeloop_util.py).

The upstream collision flag can include depth checking, more than 15 stuck
updates with horizontal displacement below 0.05 metres, or the upstream target
distance sequence heuristic. It is reported separately from simulator contact.
The summarizer only names a stuck-threshold category when the actual recorded
counter supports it; it does not invent obstacle, perception, control, or planning
causes. Categories may overlap. A separate inspection of trajectory/images and
causal evidence is required to diagnose failure mechanisms.

`distance_to_spawned_target_m` is exactly the recorded hook target-distance value.
It is not labeled upstream NE: the pinned upstream metric script instead compares
the final reference trajectory point. SPL also requires a separately audited
complete trajectory/reference-path contract and is not computed here. See the
pinned [metric implementation](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/utils/metric.py)
and [environment action/state handling](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/src/vlnce_src/env_uav.py).

Host generate-call return durations are summarized where the hook provides valid
timestamps. They are not CUDA-synchronized GPU timings, total episode wall time,
or real-time flight frequency. Video playback timing and visual review belong to
the release evidence contract, not these conditional metrics.

## Build and inspect a summary

With real paths substituted and completed evidence copied or stable locally:

```sh
python3 scripts/summarize_navigation.py \
  --plan /actual/frozen/navigation-plan.json \
  --output /actual/new/navigation-summary
```

The command prints accounting counts. Its zero exit means the summary was built;
inspect valid coverage, all unscored trial rows, source/report errors and retry
deviations before treating it as an evaluation result. Invalid/missing evidence
does not prevent an honest partial report. An invalid plan or existing output
directory fails instead of overwriting earlier evidence.

Outputs are `REPORT.md`, `summary.json`, `aggregate.json`, `trials.csv`,
`attempts.jsonl`, `plan.snapshot.json`, `configuration.json`, `source-files.json`
and `checksums.json`. The last file hashes every other output file. It is not a
signature or external attestation; retain its hash in the phase release manifest
when sealing a reviewed release. `source-files.json` contains read paths, byte
sizes and SHA256 values; no source image or log is fabricated or copied into a
synthetic result. Review and share only the intended evidence bundle.

## Local verification

```sh
python3 -m unittest discover -s tests -p test_navigation_summary.py -v
python3 -m py_compile scripts/summarize_navigation.py
```

The tests use temporary synthetic event/image-byte fixtures. They cover missing
and interrupted trials, conditional denominators, non-contact collision flags,
first-valid retry selection and caps, copied/shifted/malformed evidence, runtime
identity, source changes, output hashes and complete CSV accounting. Passing
these tests is software verification, not a model or simulator result.
