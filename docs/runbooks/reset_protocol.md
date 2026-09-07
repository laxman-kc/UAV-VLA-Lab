# Paused final-pose reset candidate

## Actual first candidate and timed follow-up

The real `paused-final-pose-v1` capture run failed both resets. Ground truth and refreshed cached state had zero position/orientation error, but rendered vehicle/camera orientation errors were 1.15777 and 0.17195 radians. Rendered origin errors were 0.19370 and 0.00739 m. All evidence checks and cleanup passed. The candidate is not a validated reset fix.

The separate opt-in `paused-final-pose-time-v1` adds exactly one `simContinueForTime(seconds=0.001)` request after the final pose application and before sensor refresh. It records actual multirotor timestamps before/after and requires pause on return. The requested duration does not establish actual elapsed physics time or a precise frame count. It keeps the same acceptance tolerances and does not add an API reset or change ClockSpeed/controller/model.

This follows a source-level hypothesis: Microsoft's Unreal implementation sets a pending rendered pose, and time-based continuation stops physics before waiting for a render frame. The compiled TravelUAV binary's exact source revision is unknown; only the real camera/ground-truth checks can validate the candidate. [Multirotor rendering implementation](https://github.com/microsoft/AirSim/blob/main/Unreal/Plugins/AirSim/Source/Vehicles/Multirotor/MultirotorPawnSimApi.cpp), [time continuation implementation](https://github.com/microsoft/AirSim/blob/main/Unreal/Plugins/AirSim/Source/SimMode/SimModeWorldBase.cpp).

Actual timed-candidate validation passed two capture resets and all three separate controller probes at unchanged tolerances, including actual camera/vehicle/ground-truth checks and owned-process cleanup. This validates those bounded historical probes. The timed integration was subsequently used in the recorded P08/P13/P14 cycle; a new host still needs its own fresh acceptance. The original no-continuation candidate remains available with its original protocol name; the description below refers to that variant.

`paused-final-pose-v1` is an explicit candidate reset behavior, implemented in
`scripts/reset_protocol.py` and selected only through the simulator probe's
`--reset-protocol` option. Its local tests use synthetic API doubles. Actual P03
capture and P04 controller acceptance runs are required before calling it usable.
It is not installed in the evaluator or published as a validated fix by this
runbook.

The preceding real diagnostics showed exact requested ground truth immediately
after every setter, followed by pose changes during frame advances. All three
tested setter variants still had final orientation errors. Cached state was
collected before the target-spawn frame, so a passing cached-state check could
coexist with an incorrect captured pose. This candidate addresses that reset
ordering; it does not establish the underlying controller/contact/physics cause.

The [pinned environment](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/src/vlnce_src/env_uav.py#L228)
calls `_changeEnv`, `_setTrajectorys`, `_setObjects`, then `update_measurements`.
Its `reset` subsequently calls `get_obs`. The candidate wraps the bound
`changeToNewTrajectorys` method and lets that original sequence finish first.
Before image capture, it performs:

1. `simPause(True)` and a readback confirming pause.
2. `simSetKinematics` with the selected episode's exact starting position and
   quaternion, and all four velocity/acceleration vectors explicitly zero.
3. `simSetVehiclePose` with that same pose, `ignore_collision=True`, while paused.
4. Another pause readback, then the existing `getSensorInfo` function; replace
   the one cached trajectory entry with its actual returned sensor envelope.
5. Refresh distance measurements and return to unchanged `get_obs`.

No additional frame continuation, simulator reset, arming or takeoff is added.
The policy, controller implementation, target placement and ClockSpeed 10 remain
unchanged. This protocol deliberately changes reset ordering and synchronization;
it must have its own name in every manifest and comparison.

The required sensor refresh adds **one** collision-info query per reset beyond
the original path. That query's returned event is retained by the runtime; no
separate collision-clearing query is issued. This changes the observation boundary
of a server collision latch. A false flag is not proof of continuous clearance,
and a true flag may describe an event preceding the final pose application.
The existing contact check is retained; the script does not ignore a failed flag
to make this candidate pass.

Stage `reset_protocol.py` beside the updated `simulator_probe.py`, then run a
fresh [owned session](simulation_session.md). Add the following explicit argument
to the capture command from that runbook:

```sh
--reset-protocol paused-final-pose-v1
```

Use new session/probe output directories. Retain two reset attempts and the
original 0.1 m / 0.05 rad tolerances. If that actual capture gate passes, run the
separate controller probe with `--mode controller` and the same protocol, also
in a fresh session. Do not infer P04 from P03. The option defaults to `upstream`;
that mode observes image requests and strengthens acceptance evidence without
applying the final-pose behavior.

Both modes now retain the actual camera request names and matching response
metadata from the image RPC. They require exactly one scene/client and one
configured vehicle. Acceptance verifies the recorded settings rather than
assuming camera extrinsics: FrontCamera must have explicit zero roll/pitch/yaw,
and DownCamera explicit zero XYZ offset. A different setting fails this bounded
comparison instead of silently assuming a transform convention.

For **both RGB and depth responses**, compare FrontCamera orientation with the
requested vehicle quaternion and DownCamera position with the requested vehicle
position. Also compare them with a separate post-capture ground-truth readback.
Check that readback and `simGetVehiclePose` against the same original tolerances,
and require paused status before/after the readback. The cached-state checks
remain. Actual image timestamps and acquisition intervals are retained; pause
checks do not make multiple RPC calls atomic.

`config.resolved.json` records the protocol name and helper/probe hashes before
measurement. Runtime `reset_protocol.*` events record operations, actual request
mapping, sensor replacement and acceptance values. Each result includes
`camera_reset_measurements`, including raw ground truth, vehicle pose, verified
extrinsics, source capture, settings hash and separate checks. No camera frames,
states, timestamps or outcomes are synthesized.

Execution or a successful RPC return is not the acceptance criterion. All
existing probe checks and the added actual-camera/ground-truth checks must pass.
A failed candidate run must remain a failed attempt, with its settings and source
hashes preserved. Even a P03 pass would show bounded reset/capture correctness;
it would not establish controller calibration, collision-free navigation or an
improvement in the learned model.

## Optional evaluator integration of the timed candidate

The patcher now copies `scripts/reset_protocol.py` byte for byte to
`_vla_lab_reset.py` beside the evaluator hooks and records its SHA256 in
`vla_lab_patch_manifest.json`. This copy does not activate the candidate. The
no-continuation `paused-final-pose-v1` variant remains probe-only. The evaluator's
default `upstream` mode installs no reset helper and issues no extra acceptance
queries.

Apply the patcher to a separate checkout at the pinned revision, preserving the
checkout used for earlier recorded runtimes. To select the timed behavior,
export both variables to the exclusively owned simulation session. Select a new runtime ID and export its actual receipt/event paths as shown in the [fresh-host runbook](fresh_host.md); these are child-process environment values, not unexported shell variables:

```sh
export VLA_LAB_RESET_PROTOCOL=paused-final-pose-time-v1
export VLA_LAB_RUNTIME_ID=NEW-rpcfix-msgpack112-paused-final-pose-time-v1
```

The runtime ID must explicitly contain the complete reset protocol token; the
previous official-reset ID is rejected. The copied helper must match both SHA256
entries in the patch manifest and be imported from the current checkout. A
missing manifest, unsupported reset name, missing ID or hash mismatch fails
before simulator calls. These checks establish the selected source/configuration;
they do not replace the separate runtime receipt or demonstrate rendering success.
`run.start` retains the existing `aerovla-e37685a-observed-v1` event protocol and
adds `reset_protocol` and `reset_helper_sha256`. Compare results using the distinct
runtime ID.

Base hooks install first. The optional helper then wraps the original trajectory
reset. An outer `env.reset` wrapper waits for the original image capture to return
and invokes the helper's camera/ground-truth acceptance before the return value can
reach model input preparation. It additionally enforces the existing P03 gates:
five RGB images of shape 256×256×3, five depth images of shape 256×256, cached
position/quaternion within 0.1 m / 0.05 rad, an explicit false initial sampled
contact flag, and generated ClockSpeed 10. Pose components must be finite and the
quaternion nonzero. The settings bytes must still match the helper's acceptance
hash. No collision query is added by this outer acceptance wrapper. No exact-zero
post-continuation velocity gate is inferred from the zero-valued setter request.

Every reset records `reset_protocol.evaluator_acceptance` and a corresponding
`reset_acceptance/<attempt>-<ordinal>.json`, including the raw measurements,
individual checks and accepted/rejected status. Any failed check or reset RPC
exception aborts before model preparation. It remains an incomplete attempt,
without a scored `episode.completed` outcome. A previous episode's accepted reset
cannot authorize preparation in a new attempt. The returned observation object is
unchanged on success. Unit tests verify these contracts using synthetic doubles;
policy-loop acceptance still requires the separate real evaluator run.

Each `observation.prepared` now also records `image_write_hash_start_ns`,
`image_write_hash_end_ns` and `image_write_hash_ns`. This interval covers the ten
synchronous PNG encodes/writes and readback SHA256 hashes, including loop
bookkeeping. It excludes model preprocessing, directory creation and event
serialization, and does not imply fsync durability. The original
`prepare_and_record_ns` field retains its earlier meaning and remains present.

At `run.end`, `recording_measurements` records cumulative successful JSONL event
envelope/serialization/write time and separate JSON artifact write/rename time,
with prefix counts. These exclude the final `run.end` serialization, lock wait,
final flush/fsync, image encoding/hashing, RPCs and preprocessing. They measure
specific recording operations on the actual run; they are not total
instrumentation overhead or a counterfactual flight without instrumentation.
An interrupted process that never reaches `run.end` has no final cumulative
measurement and must retain that missing value.
