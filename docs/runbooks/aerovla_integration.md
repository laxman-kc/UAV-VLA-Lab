# One genuine AeroVLA episode: integration runbook

This integration is for the inspected upstream commit
`e37685afb8953d1f5a09155d7255960cee1bfd9d`. It does not fabricate episode metadata,
labels, observations or model outcomes. Local unit tests use explicitly synthetic
fixtures; they are not evidence of remote execution.

## What remains unchanged

The policy's prompt, target-position-derived hint, numerical decoding (including
the malformed-output-to-zero fallback), motion branching, stopping criterion,
five-view capture and simulator clock/pause calls retain upstream behavior.
Broad exception handlers receive explicit cancellation guards so SIGTERM/SIGINT
can propagate into finalization instead of being swallowed by startup retries or
parser fallback. Ordinary exception handling retains its original behavior.
The installed protocol is named `aerovla-e37685a-observed-v1`: synchronous logging
adds overhead while the simulator can advance during inference. Do not describe
this as a byte-for-byte timing reproduction of the uninstrumented baseline.

## Required actual assets

- Base model with tokenizer/processor/custom code at `./openvla-7b` in the checkout.
- Released `aero_vla` adapter; pass its real path through `--model_path`.
- Selected compiled map bundle and shared assets, matching the scene manager's
  executable mapping. The manager needs its actual `--root_path`.
- Original split rows and each selected trajectory's `merged_data.json`, `mark.json`
  and `object_description.json`; the repository's `data/meta` JSON files.
- Working installed upstream dependencies, compatible GPU/graphics libraries,
  and a dedicated scene-manager port. The upstream requirements omit some imports;
  use the host/dependency inventory before this runbook.

Evaluation obtains RGB/depth from the simulator, so prerecorded training images
are not read by this evaluator. Creating merged metadata from raw trajectories is
a separate verified preprocessing step, not performed by the selector.

Use a `dataset_raw` symlink in the checkout if the assets live elsewhere. Launch
with `--dataset_path ./dataset_raw/`: this upstream loader strips a leading slash
when storing trajectory directories, making an absolute dataset path unreliable
for its final `object_description.json` copy. Run from the checkout directory.

## Inspect and select the episode

The following placeholders must be resolved to real paths/IDs. These commands do
not authorize choosing invented metadata when a source file is missing.

```sh
python /path/to/UAV-VLA-Lab/scripts/prepare_aerovla_episode.py \
  --split /path/to/AeroVLA/data/uav_dataset/seen_valset_splits/SELECTED_MAP.json --list

python /path/to/UAV-VLA-Lab/scripts/prepare_aerovla_episode.py \
  --split /path/to/AeroVLA/data/uav_dataset/seen_valset_splits/SELECTED_MAP.json \
  --episode-id ACTUAL_EPISODE_ID \
  --dataset-root /actual/persistent/dataset_raw \
  --metadata-root /path/to/AeroVLA/data/meta \
  --output-dir /actual/new/episode_selection
```

The selector keeps every genuine source row for exactly one trajectory, validates
required metadata and the original instruction format, and records source hashes.
The output directory contains `episode.json` and `selection_manifest.json`. It
does not assert that the binary, model or GPU are ready.

## Apply the inspected integration patch

```sh
python /path/to/UAV-VLA-Lab/scripts/patch_aerovla_runtime.py --checkout /path/to/AeroVLA
python /path/to/UAV-VLA-Lab/scripts/patch_aerovla_runtime.py --checkout /path/to/AeroVLA --apply
```

Default operation prints a diff. `--apply` verifies the exact inspected evaluator
and six protocol source files, keeps `.py.vla-lab-original` backups of changed
files, installs `_vla_lab_runtime.py`, and writes `vla_lab_patch_manifest.json`.
It refuses unreviewed modifications. Reapplying the same integration is allowed.
Restore the saved files to run uninstrumented;
the hook file is inactive unless the patched entrypoint imports it.

## Run with a dedicated scene manager

Start the manager in a separate supervised terminal/process. Save its PID and log.
Use real paths and a verified unused port. `30000` is the upstream default; this
manager may only serve the current run because `close_scenes` closes all its scenes.

```sh
python /path/to/AeroVLA/airsim_plugin/AirVLNSimulatorServerTool.py \
  --gpus 0 --port 30000 --root_path /actual/persistent/envs
```

Then, from the upstream checkout, run this command with real artifact locations:

```sh
VLA_LAB_SCENE_MANAGER_EXCLUSIVE=1 \
VLA_LAB_EVENT_DIR=/actual/new/attempt/evidence \
CUDA_VISIBLE_DEVICES=0 python -u src/vlnce_src/eval_aerovla.py \
  --run_type eval --name AerialVLA_OneEpisode \
  --gpu_id 0 --simulator_tool_port 30000 --DDP_MASTER_PORT 20001 \
  --batchSize 1 --maxWaypoints 200 \
  --dataset_path ./dataset_raw/ \
  --eval_save_path /actual/new/attempt/upstream_results \
  --model_path /actual/persistent/models/aero_vla \
  --eval_json_path /actual/new/episode_selection/episode.json \
  --map_spawn_area_json_path ./data/meta/map_spawnarea_info.json \
  --object_name_json_path ./data/meta/object_description.json
```

`maxWaypoints=200` retains the inspected shell's action bound; select and record
another bound only as an explicit experiment setting. This does not bound asset
loading or repeated scene startup failures. The run supervisor must enforce a
separate wall-time budget and send SIGTERM for graceful interruption before any
forced kill. SIGTERM/SIGINT enter cleanup; SIGKILL cannot flush or clean up.

The existing shell's invalid `DDP_MASTER_PORT=80005` is avoided. The valid port
shown is still a placeholder until checked against the actual host. The manager
must be stopped by its owning supervisor after the evaluator; the integration
closes its scenes and AirSim connections but does not kill the manager process.

## Evidence and outcome interpretation

```text
attempt/
  upstream_results/                   # unchanged upstream episode output
  evidence/
    events.jsonl                      # incrementally flushed causal records
    observations/<attempt-id>/<n>/     # actual five RGB and five depth PNGs
    outcomes/<attempt-id>.json         # upstream reached termination
    partial/<attempt-id>.json          # interruption, never a completed outcome
```

Events include original instructions, actual prompts, token IDs/raw text,
upstream decoded actions/stop flags, actual AirSim call arguments, cached endpoint
state/IMU, available image-response timestamps, and monotonic timing boundaries.
The RGB PNG convention follows upstream OpenCV output. Depth PNGs preserve the
upstream clipped/scaled uint8 representation, not full floating-point depth.

An asynchronous controller event records RPC dispatch/return; `action.completed`
records return after the unchanged executor joins its futures. Five returned
sensor records repeat one endpoint. They are not five physical samples. Image
timestamps and cached state timestamps remain distinct rather than being aligned
by invention. Sampled endpoint contact is not continuous collision monitoring.

Structured outcomes retain all upstream flags and its displayed precedence:
success, oracle success, collision flag, early end, other/step limit. The collision
flag combines proximity/stuck/progress heuristics. Success is the upstream
navigation criterion, not physical touchdown. A model stop may not immediately
end a far-from-target episode under upstream rules.

The event log refuses overwriting a prior run: choose a fresh evidence directory
for each attempt. Inspect `run.end`, cleanup errors and expected episode count;
do not equate a generated output file with a passed acceptance gate. Infrastructure
errors and interrupted attempts are separate from navigation failures.

## P03/P04 simulator probes without a model

Use the same real episode selection, dataset symlink, patched checkout and
dedicated manager. No VLA model is loaded by this script. It imports the upstream
environment and invokes its reset and controller directly. Run capture first,
inspect its acceptance gate, and then run controller mode into a fresh directory:

```sh
python /path/to/UAV-VLA-Lab/scripts/simulator_probe.py \
  --mode capture --upstream /path/to/AeroVLA \
  --episode-json /actual/episode_selection/episode.json \
  --dataset-root /actual/persistent/dataset_raw \
  --output-dir /actual/new/p03_capture \
  --gpu-id 0 --simulator-port 30000 --scene-manager-exclusive

python /path/to/UAV-VLA-Lab/scripts/simulator_probe.py \
  --mode controller --upstream /path/to/AeroVLA \
  --episode-json /actual/episode_selection/episode.json \
  --dataset-root /actual/persistent/dataset_raw \
  --output-dir /actual/new/p04_controller \
  --gpu-id 0 --simulator-port 30000 --scene-manager-exclusive
```

Capture mode proposes two independent resets of the same selected mission.
Controller mode proposes three separate resets, each followed by one isolated
command: yaw `+0.5 rad`, forward `2 m`, or down `-1 m` (upward in the upstream NED
coordinates). The full actions, per-axis numerical tolerances, reset tolerances
and scope are saved in `config.resolved.json` **before** measurement. They are
engineering acceptance settings, not reported results or statistical adequacy
claims. `--probe-config` accepts an array with the same schema as
`DEFAULT_PROBES` in the script; choose any changed tolerances before rerunning and
retain both attempts. Proposed reset tolerances are `0.1 m` position and `0.05 rad`
full quaternion rotation distance, overridable through the two explicit CLI flags.

Each reset uses actual trajectory metadata and the upstream target spawn call.
The checks require a nonempty object name returned by the actual spawn RPC;
this is not a separate geometric proof of object placement. Capture checks retain
all five RGB/depth views, available image timestamps and state/IMU timestamps.
Controller checks compare measured endpoint movement with the released executor's
heading convention, inspect sampled endpoint contact, and retain exact RPC calls.
ClockSpeed must equal the generated upstream value `10`. These scripted movements
do not measure learned navigation or establish continuous collision-free flight.

The output includes `results.json`, `checks.json`, `REPORT.md`, the premeasurement
configuration and `evidence/` logs/PNGs. Exit `0` means all configured checks and
scene cleanup passed; a valid check failure exits `1`; the internal deadline
exits `124`. The default active-work deadline is `180` wall seconds, followed by
cleanup (up to the RPC timeout, plus helper-worker shutdown). Keep an outer
supervisor deadline with cleanup grace. The owning supervisor still stops the
manager process and verifies no scene process survived. Simulator execution and
rendering of evidence video must occur on the prepared host; the local unit
fixtures establish neither.

## Local checks

```sh
python -m unittest discover -s tests -p test_aerovla_integration.py -v
```

These checks validate patch guarding, preservation of return objects/action
arguments, outcome precedence, non-overwriting logs and source-row/metadata
validation. Actual dependency imports, model loading, images, controller motion
and complete cleanup still require the real Brev simulator/model run.
