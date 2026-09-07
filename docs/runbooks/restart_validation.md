# P07 retrospective interruption/restart checks

scripts/validate_restart.py reads completed source evidence and writes one new
validation JSON. It never signals a process, calls a simulator/GPU, restarts a job
or edits an input. Keep the sibling summarize_navigation.py: its existing causal
chain and outcome checks are reused and its source hash is recorded.

Run after both owning simulation sessions have finished and their complete
evidence has been copied. Pass the directory containing each hook events.jsonl,
not its parent experiment folder. The session roots contain report.json,
lifecycle.jsonl and command/; the helper root contains its receipt, journal
and checksums. All paths and the frozen runtime ID are explicit:

    python scripts/validate_restart.py \
      --interrupted-evidence /local/first/evidence \
      --interrupted-session /local/first-session \
      --interruption /local/interruption-receipt \
      --restart-evidence /local/restart/evidence \
      --restart-session /local/restart-session \
      --expected-runtime-id ACTUAL_FROZEN_RUNTIME_ID \
      --expected-completed-actions 2 \
      --transfer-inventory /local/source-host-files.sha256 \
      --transfer-root /local/copied-runs \
      --output /local/new/p07-validation.json

The independent transfer inventory is optional; its two arguments must appear
together. It uses ordinary SHA256/relative-path lines from the source host. Paths
are resolved under the explicit local copy root and traversal is rejected. The
validator does not rewrite historical remote paths. Session artifact records
are mapped using their original unique command/report.json root and verified
against the supplied local session root. Helper event-prefix hashes are checked
against the exact original bytes consumed before signaling.

The controlled boundary is two **completed** action calls. The helper receipt
must bind its one kernel-accepted SIGINT request to the supervisor's original and
final process identities, the actual navigation PID, and the recorded two-action
prefix. An actual episode.interrupted, matching KeyboardInterrupt partial file
and later run.end are required. No completed outcome is accepted for that
interrupted attempt. Any pending observation/policy/action-request tail remains
visible; the receipt does not promise atomic signal delivery at event two.
More than two completed actions fails the declared boundary.

Because the helper signals the evaluator group directly, an expected interrupted
slot normally has supervisor termination_reason=natural_exit,
status=exited_with_error, child return −2 or 130, normalized exit 130, and
session command_failed/130. Those labels are not automatically P07 failures.
The validator also requires actual partial preservation, no forced command
SIGKILL, explicit root/group absence, owned manager readiness and matching
manager cleanup evidence. An exit code or helper receipt alone cannot satisfy
these checks.

Restart needs distinct evidence roots, run/attempt IDs and process start identity,
the same recorded runtime/model/source/episode configuration, normal scene
initialization after the prior session finished, a valid completed causal chain,
matching terminal outcome, natural exit zero and complete recorded cleanup.
Every completed action must refer to the current observation; image files are
hash checked and linked to earlier capture events. A terminal navigation outcome
is validated using its actual flags and metrics, rather than inferred from a
directory name. An interrupted attempt receives no navigation score.

Missing files/required fields remain unknown; contradictory evidence is fail.
Overall exit codes are 0 for passed, 1 for failed and 2 for unknown. Outputs must
be new and outside input evidence roots. All consumed file hashes are recorded
and checked again for changes during validation. Validation itself does not
provide a new experiment or an independent trust anchor for self-reported logs.

This check does not establish exact physics/model-state resumption, rehash remote
model weights, exclude unobserved escaped processes, decode or visually review
images/video, or isolate recording overhead. Those remain separate P07 report
and media obligations. prepare_and_record_ns includes upstream preprocessing
and observation export; it must not be relabeled as pure logging overhead.
Comparing a repaired-RPC run with an earlier unrepaired reference also cannot
isolate incremental recording overhead.

Local verification:

    python3 -m unittest discover -s tests -p test_restart_validation.py -v

The fixtures are synthetic files; no simulator, signal or GPU job is run by them.

For a recording-cost supplement, keep the original interruption/restart pair
unchanged and identify the supplemental run's runtime, reset protocol, source
hashes and frozen plan separately. Do not substitute a different-reset run for
the restart input merely to add timing fields: the restart validator deliberately
requires matching configuration between the original pair. Timing assessment is
an additional read-only analysis, not a feature of validate_restart.py.

Bind every image_write_hash_ns value to its recorded start/end interval, its
observation event and all ten image hashes. Check that it is nonnegative and no
larger than that observation's prepare_and_record_ns. Report the batch count,
sum, mean and empirical quantiles with the interpolation convention stated.
The batch includes both RGB and depth PNGs; a batch quantile is not a per-image
quantile. Reconcile run.end's event_count_before_run_end with the actual prior
event count and its JSON artifact count with the recorded files. Aggregate
event/JSON counters provide no per-event duration distribution.

Read the exact matching timer implementation before describing its scope.
The measured image interval covers encoding, writes, readback hashing and loop
bookkeeping; it excludes directory creation and fsync. The event prefix excludes
run.end itself, lock wait and final flush/fsync. Separate upstream end-of-episode
image/state export is also outside these counters. A sum of these components
divided by command elapsed time is an accounting ratio, not total overhead,
policy slowdown or a causal trajectory comparison. Keep those remaining
unknowns explicit even when the bounded direct-component measurement gate
passes. The reduced [verified status](../../PUBLIC_STATUS.md) summarizes the actual P07 supplement. Exact private component measurements and exclusions remain in its retained evidence bundle and are not copied into this public overlay.
