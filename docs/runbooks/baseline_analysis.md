# Development baseline analysis

Run this after the navigation summarizer has finished and the immutable run/session evidence has been copied locally. The tool reads only the plan's declared development evidence. It does not launch a simulator, load a model, inspect holdout pixels, or alter the navigation summary.

```sh
python3 scripts/analyze_baseline.py \
  --plan configs/experiments/p08-development-timed-reset-v1.json \
  --navigation-summary data-local/p08-development-summary-v1/summary.json \
  --runtime-receipt data-local/timed-reset-runtime-v1.json \
  --reset-helper scripts/reset_protocol.py \
  --runtime-hook scripts/_aerovla_runtime_hooks.py \
  --path-map /path/to/recorded-runs=/path/to/copied-runs \
  --output data-local/p08-development-analysis-v1
```

These are the planned copy locations, not a claim that a batch or its copy has completed. If root uses a different summary destination, supply its actual path. Both path-map prefixes must be absolute; matches respect path-component boundaries. For execution on the original host, omit the mapping and use the actual host paths. Source files must match the frozen hashes; use a retained matching source snapshot if the working code has since changed. Existing output directories are refused.

The output is `analysis.json`, `reset-audits.json`, `trials.csv`, `video-selection.json` and `REPORT.md`. Exit 0 means every planned trial has an eligible navigation outcome and accepted reset evidence, without extra observed attempts or source failures. Exit 2 means a complete analysis was written but that completeness gate did not pass. A navigation failure with valid evidence is a scored outcome and does not itself fail the evidence-completeness gate. Invalid configuration/input that prevents analysis raises an error instead of inventing output.

## Reset audit

For each session, the tool checks the exact frozen plan embedded in the navigation summary, the original summary's source hashes and sizes, the actual runtime receipt, and the helper/hook source hashes. The recorded runtime, model path, action cap, selected reset protocol, patch manifest and pre-input guard must agree. Exactly one helper installation must precede the session's first episode. The frozen timestamp must precede `run.start`.

For each observed attempt, exactly one accepted evaluator reset record must follow `episode.start` and precede its first recorded observation/prompt/policy input. Its separate JSON payload must match the event. The helper's begin, timed continuation, refresh and camera acceptance must belong to that attempt and precede acceptance. The audit independently recalculates cached-state, ground-truth, vehicle-pose, front-camera orientation and down-camera position errors against the recorded initial reference. Actual saved settings must match the acceptance SHA, ClockSpeed 10, and the explicit camera extrinsics. All ten request/response mappings, captured modalities and dimensions are checked. The raw pause/ground-truth/vehicle/pause RPC bracket must substantiate the embedded readback. The first model observation must use the accepted cached state and camera batch.

The numerical pass limits remain **0.1 m position** and **0.05 rad rotation**. Comparing a reported angular-error number with its local recomputation allows up to `1e-7` rad for cross-Python floating summation and near-zero `acos` rounding; the independent pass/fail comparison still uses the original 0.05-rad limit. The continuation request remains 0.001 s; the actual simulator timestamp difference is reported separately. No exact-zero velocity or continuous contact criterion is added.

A valid reset cannot manufacture a navigation outcome. The joint trial table requires both the original navigation validator's eligible outcome and this reset audit. The one-observed-attempt cap is preserved: a later valid attempt cannot replace a first invalid attempt. Missing, rejected or mismatched reset evidence remains unscored. All planned rows remain visible, including unstarted rows. Extra observed attempts and unplanned attempts are reported separately.

This auditor is deliberately conservative with file-level source damage: a hash mismatch or unreadable event stream can prevent scoring otherwise completed navigation records. It does not repair, truncate or reinterpret damaged evidence. Retain the original navigation summary alongside the stricter joint analysis so this exclusion is visible. A cleanup failure after a valid terminal outcome remains a separately reported process fact; it is not silently converted into a navigation failure.

## Reporting and video contract

Success and OSR use the upstream navigation flags conditional on valid joint outcomes. The table retains all planned/observed/valid/unscored/unstarted denominators and raw termination reasons. Successes per planned mission is explicitly completion accounting, not a rate obtained by coding missing outcomes as failures. Wilson 95% intervals are descriptive binomial calculations; the fixed missions, single map, correlated behavior, small sample and unresolved overlap with released-model training prevent broad reliability or unseen-to-model claims. Original released weights under the named changed reset protocol are not a trained candidate or an unchanged upstream reproduction.

Host generate-return, token-copy, action execution and image-write/hash intervals include their valid/missing counts. They are not synchronized CUDA latency or total instrumentation overhead. GPU values are sampled host-wide totals, with sample counts; copied storage is the actual regular-file logical byte count under the declared run/session roots, excluding model/assets and filesystem allocation. Contact reports are endpoint/latch samples; upstream collision flags can also involve heuristic termination. Neither proves continuous collision-free flight. `LAND` supports the upstream navigation-stop criterion, not physical touchdown.

The frozen editorial rule selects the first valid success and first valid non-success in recorded session/event execution order. An absent category stays explicitly absent. It takes the first, middle and final observations; middle is zero-based `floor((N-1)/2)`, with duplicate indices displayed once. Each selected image retains its actual event ID, camera, sensor timestamp, wall timestamp and source hash. The video must also show every planned trial's row. Static holds are labeled sampled observations, not real-time flight footage. The complete mission traces remain in the underlying evidence even when the video shows a subset. Rendering, actual visual review, exhaustive static-frame validation and sealing happen separately through the release builder.

## Validation

```sh
python3 -m unittest discover -s tests -p test_baseline_analysis.py -v
```

The synthetic tests cover false-pass mutations, run/receipt/helper/guard identity, pose/camera/paused-readback mismatch, late/duplicate/missing acceptance, settings and first-observation mismatches, nonfinite data, all-20 accounting, no replacement retry, execution-order video selection, Wilson calculations, source changes and an end-to-end partial-batch analysis. Synthetic fixtures do not establish model performance. A separate read-only retrospective audit of the actual timed-reset P06 demo also matched its recorded source identities and accepted reset evidence; that check is not a P08 baseline result.
