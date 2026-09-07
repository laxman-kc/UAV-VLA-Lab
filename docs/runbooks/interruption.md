# P07 observed interruption and fresh restart

`scripts/interrupt_after_event.py` watches one existing supervised evaluator and
sends one `SIGINT` request to its verified owned process group after the declared
number of recorded events. The P07 setting is `action.completed` with count 2.
It does not launch or alter the evaluator, signal the scene manager, or perform
cleanup. Keep the simulation session and command supervisor responsible for
their own groups, timeouts, cleanup and actual return-code reports.

This is an interruption/restart engineering test. It does not establish that a
policy can resume its hidden state mid-episode or that navigation improved.

## Preconditions and plan

Use fresh session, evaluator evidence and helper output directories. Freeze the
P07 runtime ID, model identity, episode, action/command bounds and interruption
count in the execution plan. The current helper accepts only the inspected
`aerovla-e37685a-observed-v1` protocol and requires the planned `runtime_id` in the
hook `run.start`.

The updated supervisor must be deployed before the run. Its `process.spawned`
event now includes the original Linux process identity: PID, PGID, session ID,
start ticks, kernel boot ID, user ID, full argv, working directory and executable.
This is recorded immediately after the supervisor's `Popen`. It does not read the
process environment. A capture error is explicitly recorded without changing
ordinary supervision; this helper refuses to signal without the original
identity. Older supervisor evidence is therefore insufficient for live P07.

The hook `run.start` must record `process_id=os.getpid()` as well as `runtime_id`
and its actual `sys.argv`. P07 runs the evaluator directly through Python. The
hook argv must be a suffix of the recorded process argv. A wrapper that changes
process identity or argv, or a Python module invocation with different script
argv, is rejected rather than inferred equivalent. Launch the helper as a
separate process outside the evaluator's group, on the same Linux host and user.
Both scripts require the sibling `supervise_run.py` file to remain available.

Start the watcher before the evaluator reaches its second completed action.
Expected event files may not exist yet; it waits within its declared hard bound.
Use the actual supervisor JSONL path and actual `VLA_LAB_EVENT_DIR`, not the
simulation-session lifecycle file or a guessed evidence directory.

```sh
python /actual/project/scripts/interrupt_after_event.py \
  --supervisor-events /actual/p07-session/command/events.jsonl \
  --experiment-events /actual/p07-evaluator/_vla_lab/events.jsonl \
  --output /actual/new/p07-interrupt-helper \
  --runtime-id ACTUAL_FROZEN_RUNTIME_ID \
  --event-type action.completed \
  --after-count 2 \
  --timeout-seconds 600
```

Replace the paths, runtime ID and wall-time bound with the real execution plan.
The example 600-second helper bound is an operational example, not a measured
runtime prediction. Keep the owning command/session timeout long enough for the
evaluator's actual cleanup. The helper's default poll period is 0.02 seconds and
can be set between 0.001 and 1 second with `--poll-seconds`.

The allowlist is `action.completed`, `policy.generated`, and `policy.decoded`.
There is no `policy.completed` event. `action.completed` means the upstream action
call returned; `policy.generated` means model generation returned and its output
was recorded; `policy.decoded` means the upstream parser returned its action/stop
values. These are different boundaries. The report names the exact selected one.

`--dry-run` executes the same live identity and event gates but sends no signal.
A dry run does not establish interruption or cleanup, and does not freeze the
evaluator while a later real helper starts. It may consume the opportunity to
observe the declared count; use a separate planned attempt when necessary.

## Signal gate and timing

The helper follows one append-only inode for each JSONL input. File replacement,
truncation, malformed JSON, missing/duplicate event identity, mixed runs,
different runtime, and more than one observed episode cause refusal. It consumes
the entire currently available prefix before deciding. An unfinished last line
withholds signaling because that line could be a terminal event.

Before signaling, it compares the live Linux identity to the supervisor's
recorded identity, including boot ID and start ticks to detect PID reuse. The
target must be the recorded process/session leader, must belong to the current
user, and must match the original argv, cwd and executable. Its experiment stream
must identify that same PID. A pidfd provides an additional original-process exit
guard, and the identity is checked again immediately before the one signal call.

If a completed/interrupted episode, `run.end`, supervisor stopping, prior signal,
or process completion is already observed, no signal is sent. If more than the
declared number of trigger events has been recorded, the helper reports
`trigger_count_already_exceeded`; it does not interrupt at a later count and
mislabel it as the requested boundary. A refused or failed signal is never retried.

The observed prefix is the timing claim: exactly N matching events were recorded
at the final event check. The evaluator can advance between that check and kernel
delivery, so the receipt does not promise that execution stopped atomically at N.
Inspect the subsequent hook stream and partial outcome to establish what actually
happened. The signal request's UTC and host-monotonic timestamps are retained.

Likewise, a live `/proc` identity check and numeric `os.killpg` are separate kernel
operations. The helper reports this limitation and does not claim a race-free
atomic group signal. Linux provides PIDFD process-group signaling beginning with
6.9; the earlier recorded host kernel is 6.8. This helper uses the existing
runtime's checked PGID signaling and does not change the host kernel. See the
Linux [pidfd signal documentation](https://man7.org/linux/man-pages/man2/pidfd_send_signal.2.html).

## Actual outcomes and restart

Outputs are `report.json`, the helper's timestamped `events.jsonl`, and
`checksums.json`. The report preserves the consumed input-prefix hashes and byte
counts, recorded process/run identities, observed trigger count, run/attempt/event
IDs, exact signal arguments, time, result and any refusal. It contains process
command/host identity evidence; retain it locally with the intended phase bundle
while publication is on hold. It never exports process environment variables.

| Status | Meaning |
|---|---|
| `sigint_requested` | Kernel accepted the helper's one request; interruption/cleanup still require subsequent evidence |
| `dry_run_validated_no_signal` | Live gates passed, no signal sent |
| `already_ended_or_stopping` | Terminal or lifecycle stopping evidence was observed; no signal sent |
| `trigger_count_already_exceeded` | The watcher arrived too late for the declared count; no signal sent |
| `timed_out_without_signal` | The bounded trigger/identity opportunity did not complete; exit 124 |
| `identity_or_evidence_rejected` | Source/process binding failed or a read/identity error occurred; no signal retry |
| `signal_request_failed` | The one signal call returned an error; no retry |
| `helper_interrupted_without_retry` | The helper itself received an interrupt; inspect `signal_attempted` to see whether the one request had begun |

After the helper returns, wait for the real command and simulation-session
reports. Confirm an actual hook `episode.interrupted` and corresponding
`partial/<attempt-id>.json`, retain the full event/log sequence, and inspect the
owned group cleanup evidence. Absence of a partial artifact remains a failed
evidence check; the helper never creates it. A valid terminal outcome that
occurred before signal delivery is retained as such, not recast as interrupted.

For restart, create a fresh supervisor/session output and fresh hook evidence
directory, keeping the original interrupted run intact. Run the same frozen
checkpoint/runtime and intended episode under the new attempt identity, then
validate the fresh attempt's actual observations/actions and outcome. This is a
fresh attempt from the evaluator's normal initialization, not in-place state
resumption. Include both session slots in the navigation plan with explicit retry
selection; an interrupted trial receives no navigation score.

## Local verification

```sh
python3 -m unittest discover -s tests -p test_interrupt_after_event.py -v
python3 -m unittest discover -s tests -p test_supervise_run.py -v
python3 -m py_compile scripts/interrupt_after_event.py scripts/supervise_run.py
```

Identity/event tests use synthetic temporary fixtures and mocked signal calls.
They check PID reuse, command/group mismatch, final-gate changes, run binding,
late/terminal events, truncated/partial streams, timeout, one signal only, and
receipt hashes. The real `/proc` identity test runs only on Linux. The supervisor
suite runs actual local subprocess lifecycle checks. None of these tests is a
real P07 simulator interruption or restart result.
