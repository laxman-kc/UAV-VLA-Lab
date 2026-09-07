# Reset readback diagnostic

`scripts/reset_diagnostic.py` investigates a failed pose/capture gate. It loads
the genuine prepared one-episode selection and model-free upstream environment,
then executes one original `env.reset`. It never loads a policy or requests a
flight action. Synthetic tests verify wrapper behavior; actual simulator results
must come from separately recorded executions.

Use this after the unchanged reference and documented RPC repair/capture retry.
It does not replace either baseline. Each variant requires its own fresh owned
scene-manager session and fresh output paths. Do not run all variants in a reused
scene: controller state, collision history and cold-start timing would differ.

| Required `--variant` | Deliberate change |
|---|---|
| `pose` | Preserve the original Pose object and `ignore_collision=True`; add readbacks. |
| `full-zero` | On all three setter passes, replace Pose with a complete KinematicsState containing the same position/quaternion and explicit zero linear/angular velocity and acceleration. |
| `reset-full-zero` | Call the simulator's reset API exactly once before the first setter, then use full-zero on all three passes. Do not rearm or take off. |

These are named diagnostic protocols, not established fixes. Even `pose` is not
timing-equivalent to the baseline: added readbacks take time, and physics may
advance between queries when unpaused. No additional pause is inserted. The
upstream three set/continue-one-frame/pause passes and target-spawn frame are
retained. ClockSpeed remains 10. The script changes no upstream source file,
existing probe, runtime hook or scene setting.

Run under the [owned session lifecycle](simulation_session.md). Resolve every
placeholder to an actual path and use a new output name for each variant. The
diagnostic imports `simulator_probe.py`; keep those scripts in the same directory.

```sh
python /path/to/UAV-VLA-Lab/scripts/run_simulation_session.py \
  --upstream /actual/AeroVLA --env-root /actual/envs \
  --cwd /actual/AeroVLA --output /actual/new/reset-pose-session \
  --manager-port 30000 --gpus 0 \
  --readiness-timeout-seconds 60 --command-timeout-seconds 240 \
  -- python /path/to/UAV-VLA-Lab/scripts/reset_diagnostic.py \
     --variant pose --upstream /actual/AeroVLA \
     --episode-json /actual/selection/episode.json \
     --dataset-root /actual/dataset_raw \
     --output-dir /actual/new/reset-pose-diagnostic \
     --simulator-port 30000 --gpu-id 0 \
     --scene-manager-exclusive --max-wall-seconds 180
```

The 180-second alarm is the diagnostic's wall bound, including scene launch.
The 240-second supervisor bound permits cleanup before forced group termination.
The diagnostic itself does not start or kill the manager. The session wrapper
owns cleanup of the processes it starts. A diagnostic alarm is not a guarantee
that blocked native/RPC worker threads stop immediately; inspect supervisor and
session cleanup evidence.

The script verifies installed integration-file hashes and requires one selected
trajectory. It wraps only newly connected clients. Raw snapshots are acquired
at scene connection and before/after setting kinematics, frame continuation,
pause, target spawning and image capture. The API-reset variant also records
readback immediately after that reset. Each snapshot reads, in order:

1. `simIsPause`.
2. `simGetGroundTruthKinematics`.
3. `getMultirotorState`, including its raw estimated kinematics and timestamp.
4. `simGetVehiclePose`.
5. `getImuData`, including its own timestamp.
6. `isApiControlEnabled`.
7. `simIsPause` again.

The empty vehicle and IMU names preserve the same API defaults as the upstream
setter/sensors. Responses keep their original API field names, including named
quaternion xyzw fields. Each query has separate monotonic start/return times;
these calls are not an atomic snapshot. Ground-truth/pose replies without a
simulator timestamp do not receive an invented one. Unexpected nonfinite numeric
values remain explicit tagged values and cannot generate a valid pose comparison.

The script wraps the *existing* upstream `simGetCollisionInfo` response to retain
all fields. It does not add a collision query. The runtime may record the same
returned response in another event, but that does not create another API call.
Interpret the collision timestamp/object/normal/penetration fields together; a
flag is not proof of current contact, and server latch semantics remain dependent
on the compiled binary.

`config.resolved.json` records protocol/source hashes before measurement.
`evidence/events.jsonl` contains ordered raw acquisitions and the original runtime
evidence. `report.json` preserves the snapshots, final cached observation sensors,
call counts, read errors and cleanup outcome. Final images use the runtime's
actual observation exporter. Compare ground truth, cached state and camera pose
at their own acquisition times, rather than treating them as simultaneous.

Exit 0 means the diagnostic captured the expected three setters, four frame
advances, one existing collision response, expected API-reset count, complete
readbacks and successful cleanup. It does **not** mean the reset gate passed:
`reset_gate_passed` remains null. Per-snapshot pose comparisons retain the original
0.1 m / 0.05 rad thresholds as descriptive checks; they do not change P03's result.
Exit 1 retains incomplete protocol/readback/cleanup evidence, 124 denotes the
internal deadline, and 130 denotes KeyboardInterrupt when caught. The outer
supervisor remains authoritative about actual process exit and forced cleanup.

Look first for whether immediate post-set ground truth reaches the requested
pose, then whether drift begins at frame advance, target spawning, image capture
or the subsequent cached-state read. Compare API default vehicle behavior and
estimated-versus-ground-truth disagreement before proposing a behavior patch.
The resulting differences are diagnostic observations, not proof of a fix until
a separately recorded capture acceptance run passes under the chosen protocol.
