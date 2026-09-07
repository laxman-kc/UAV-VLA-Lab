# Privileged heading-restoration collection — deferred prototype

**Status:** unapproved and unexecuted prototype, not the source of the completed P09/P11 datasets. The current adaptation uses reviewed ordinary source demonstrations; see the [scope decision](../REFERENCE_ALIGNMENT_DECISION.md) and [verified status](../research/dataset-card.md). No heading-correction sample or simulator result is claimed.

`scripts/collect_heading_corrections.py` implements the separately named `privileged-heading-restoration-v1` teacher. It is a model-free, one-action collection entry point. It does not approve labels, invoke the trainer, change the evaluation runtime, or assert human review. Source inspection and synthetic tests establish an implemented contract; actual simulator evidence must establish which samples satisfy it.

The retained private prototype plan predeclares 25 unique official/frozen training missions by a declared hash rule, in an initial five and an increment of twenty. It is excluded from this public overlay and was never executed. Its alternating signed 0.5-radian perturbations and numerical gates were specified before any proposed collection. No outcome-based replacement or silent retry is allowed. An infrastructure abort before a sample starts requires a recorded operational amendment. Every failed gate or interrupted sample remains part of the report.

## Meaning of the teacher

The privileged goal is the recorded mission's initial heading. The collector adds the fixed perturbation to the initial quaternion's extrinsic `zyx` yaw, preserving that decomposition's roll/pitch and the original position. It changes a deep copy of the in-memory single-mission batch; raw logs, merged metadata, `env.data`, and evaluation source remain intact. The exact original first raw log must agree with the merged initial pose. Near-level reference and captured start poses are required; the geometry is compared to the installed upstream SciPy convention at execution.

After a real perturbed reset passes the existing timed-reset camera/ground-truth gates, the teacher computes the wrapped difference between the original reference yaw and the captured cached yaw. Forward and down are zero. The continuous triple passes through the exact pinned dataset quantizer and wrapper parser; the resulting decoded triple is the command actually executed. Both values and the token bins are retained. The exported reader row contains the continuous target so the reader reproduces those exact bins; re-quantizing decoded floating-point values can move a boundary by one bin.

This is controlled heading restoration under privileged supervision. It does not establish that the reference heading is optimal for the language-navigation instruction, positive route progress, general model-failure recovery, collision-free motion, or an independently certified human expert. If later collected and independently accepted, five samples would establish only a small correction-data pipeline and narrow controller behavior. They do not establish general teacher quality or policy improvement.

## Coordinate and time contract

The [pinned controller](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/airsim_plugin/AirVLNSimulatorClientTool_AeroVLA.py#L299) reads `Rotation.from_quat(cached_xyzw).as_euler('zyx')[0]` and adds decoded yaw. Its horizontal displacement uses the new heading; positive down is NED down. For the enforced decoded yaw magnitude at least 0.25 radians, it executes a joined rotation with a three-second timeout and five-degree margin, a joined move-to-current-altitude with velocity 2 and three-second timeout, and a joined 0.5-second zero-velocity brake. No positive forward displacement is requested. One label covers this entire variable-duration macro, not a fixed control tick.

The macro still unpauses the simulator and preserves ClockSpeed 10. Immediately after its return, collection explicitly pauses, reads `getSensorInfo` once, refreshes the cached endpoint, and captures actual paired images. The additional sensor read includes a collision-latch query; its raw response and the earlier controller endpoint response are both retained and both must report no contact. The elapsed host gap to the post-action image return is recorded. Simulator image/state timestamps remain distinct from host timing. Paused sequential readbacks do not become atomic observations, and ClockSpeed does not justify blindly converting wall time to physical time.

The [pinned dataset reader](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/src/aerovla_dataset.py) floors 99 bins across forward `[0,5]` m, down `[-5,5]` m, and yaw `[-1.1,1.1]` rad. Its front/down RGB images become two 224-by-224 BICUBIC panels, front above down. The [pinned parser and stop rule](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/src/model_wrapper/aerovla_wrapper_ui.py#L194) recognize LAND or a near-zero triple. These samples have nonzero yaw and both terminal flags false. Ending collection after one action is not a LAND label, and this dataset provides no positive stop examples.

The prompt uses the unchanged wrapper's semantic target bearing from the actual pre-action cached pose and official target lookup, plus the original parsed benchmark object description. The bearing is privileged benchmark information. The original recorded pose is teacher information; it is not falsely claimed to be visible as an explicit numerical goal in the model input.

TravelUAV's [official waypoint teacher](https://github.com/prince687028/TravelUAV/blob/5cc26e9a4a55b9c788e918f7c3bb2dc5076a85e6/utils/env_utils_uav.py#L90) finds the closest future reference-path point from a monotonically advancing index, inserts one-metre straight-line recovery points while farther than 1.5 metres, and returns seven points padded at the endpoint. [Its DAgger collector](https://github.com/prince687028/TravelUAV/blob/5cc26e9a4a55b9c788e918f7c3bb2dc5076a85e6/src/vlnce_src/dagger.py) can select those privileged paths. Those seven-waypoint actions do not establish AeroVLA's publisher-label horizon and are not silently substituted for this new, explicitly defined yaw-restoration contract.

## Invocation

First audit all prelocked source metadata without launching a scene or loading a model. Use absolute paths from the actual acquisition receipts; placeholders below are not executable host configuration.

```sh
python scripts/collect_heading_corrections.py \
  --upstream /absolute/pinned/AeroVLA \
  --dataset-root /absolute/dataset_raw \
  --source-split /absolute/official-trainset.json \
  --split-manifest /absolute/modern_city_map_v1.json \
  --plan /absolute/heading-corrections-v1.json \
  --output-dir /absolute/new-metadata-preflight \
  --scene-manager-exclusive --validate-only --preflight-all
```

This verifies both manifest hashes, all 25 train identities, source/merged/raw initial-state agreement, the real target lookup and a starting target distance strictly greater than 25 metres, prompt compatibility, and near-level geometry. It records all preflight failures. It does not establish simulator reset feasibility.

For actual collection, launch **one fresh owned scene-manager session per sample**, wrapping the same command with `scripts/run_simulation_session.py` and its supervisor as in the [simulator runbook](simulation_session.md). Omit `--validate-only --preflight-all`, add `--sample-index 0` through `24`, and provide the reserved manager port with `--simulator-port`. The collector requires the recorded patched runtime with the timed-reset helper declared in its manifest. Its upstream `dataset_raw` symlink must resolve to the supplied dataset root. No model path is required. An explicit collection runtime ID is emitted while preserving the parent runtime receipt.

The collector checks reset translation at 0.1 m and quaternion rotation at 0.05 rad, original/actual start roll and pitch at 0.10 rad, fresh final ground-truth and front-camera heading restoration at 0.15 rad, strict heading-error reduction, horizontal and vertical drift at 0.35 m, and sampled endpoint contact false. Down-camera displacement is independently measured from response metadata. Final camera/ground-truth/cache alignment and target distance outside the 20-metre terminal radius also pass. No threshold is loosened on a failed observation.

Exit zero means source-only validation succeeded or the one actual candidate met its mechanical/evidence gates. Actual rejected gates return 2; exceptions return 1; timeout and interruption preserve their exit codes where available. The external session receipt must independently demonstrate process/port cleanup; the collector's own close receipt alone is insufficient.

## Output and expert review

Each new sample directory contains `config.resolved.json`, the exact plan and original selection, `selection_manifest.json`, `result.json`, and `evidence/events.jsonl` with original observations and complete action/reset records. `result.json` distinguishes `candidate_eligible` from `approval: not_asserted`. All rejected and partial evidence is retained.

Only mechanically eligible samples get `candidate/candidate_rows.json`, `candidate/Map/episode/frontcamera/000000.png`, the corresponding `downcamera` file, and `source.json`. Images are byte-identical copies of the pre-action recorded observations; the source event ID, original file hashes, requested continuous label, actual bins, decoded execution, mission identity, and unapproved status remain linked. Use that `candidate` directory as the temporary reader root. No approved training manifest is generated.

Before an `approved_controller_expert` dataset exists, a separately recorded reviewer must inspect every actual pair and its post-action evidence; verify the frozen train identity and unchanged source; independently recompute bins, heading and drift; inspect both contact samples and the action order; verify session cleanup; report every rejection; and state this narrow teacher's limitations. A review performed by a Codex agent must identify that agent and must not imply human approval. Then, and only then, a separate exporter may construct the existing [training manifest](training.md) with a hash-linked actual review. Collection code does not relax the trainer gate.

The phase video must show the real perturbed and restored observations with the requested/decoded action and measured result. Static holds must be disclosed as observation evidence, never uninterrupted flight footage. Source-only preflight and unit tests are not simulator or expert evidence.
