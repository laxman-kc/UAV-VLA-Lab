# A failed launch before navigation starts

A failed manager-port preflight is an infrastructure launch, not a navigation attempt. The P14 path amendment supports only the exact recorded failure before any manager or supervised command was started. It requires the complete failed-session artifact ledger, its lifecycle, all port checks, and a separate timestamped remote observation that the unchanged navigation evidence destination does not exist. A missing or empty copied local directory alone is insufficient.

Run `scripts/prepare_unstarted_session_amendment.py prepare --help` for its explicit paths. The output is a fresh derived bundle. The original paired/navigation/editorial files are preserved byte-for-byte, as is the complete failed physical session. Only the candidate supervisor/session receipt paths and their dependent hashes change. Its logical session/trial IDs, evidence destination, model, runtime, ordered missions and one-observed-attempt cap remain unchanged.

The original `frozen_at_utc` retains its meaning as the protocol/editorial freeze. It is not the creation time of the derived path-bound files. `amendment.json` records the actual later candidate-only amendment time. The original arm remains the same already executed post-freeze run. The failure is separately counted as one infrastructure launch and zero navigation attempts; it is never represented as a navigation failure or quietly erased.

After the replacement physical session completes, run:

```sh
python3 -B scripts/prepare_unstarted_session_amendment.py validate-completed \
  --amendment AMENDMENT_BUNDLE/amendment.json \
  --session-report ACTUAL_REPLACEMENT_SESSION/report.json \
  --output NEW_COMPLETION_VALIDATION.json
```

This gate requires the actual replacement start to follow the amendment and the replacement command/config/source identities to match the failed launch exactly. It does not decide navigation validity or success. Run the unchanged analyzer with the derived candidate navigation plan, preserve the original analysis, and run the unchanged comparator against the derived paired plan. Retain the amendment and completion validation beside the numerical report. Never bypass the original or candidate chronology checks.

The frozen P14 video plan still binds the original paired-plan digest. The external wrapper `scripts/prepare_amended_paired_video.py` bridges that original freeze to the strictly derived path binding. Its `request` subcommand requires the amendment and actual completion validation, verifies the exact allowed differences, then invokes the unchanged paired-video helper with the derived metadata copy. It adds a hash-bound bridge receipt; the original frozen editorial bytes remain unchanged. The wrapper's `render` subcommand repeats all bridge and causal checks before opening the selected PNGs. Both commands expose explicit paths with `--help`.

Neither helper starts the simulator, loads a model, reads holdout outcome files to choose a checkpoint, increases an attempt budget, repairs labels, changes ports or relaxes the runtime. If a manager/command/navigation start is recorded, any artifact is missing, the destination was not independently observed absent, or the exact path/chronology contract fails, this amendment is inapplicable. Preserve and report the incomplete experiment instead of silently replacing it.
