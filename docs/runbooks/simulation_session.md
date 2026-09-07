# Owned simulation sessions

`scripts/run_simulation_session.py` starts one exclusively owned, pinned
TravelUAV scene manager, waits for its actual localhost listener, runs one command
through the existing `supervise_run.py` supervisor, and then cleans up its manager
process group. The runner is locally tested with synthetic processes. It does not
establish that a real map, sensor, controller or model works until an actual run.

## Preconditions and command

Use the prepared Linux runtime and verified environment assets. The manager
source must match the inspected AeroVLA commit
`e37685afb8953d1f5a09155d7255960cee1bfd9d`. Its SHA256 is enforced before launch.
`lsof` and `ps` must be available. The upstream manager interpolates executable and
settings paths into shell commands, so its checkout and environment-root paths
must contain only letters, digits, underscores, slashes, periods and hyphens.

Resolve the following placeholders to real paths before running. There must be
no separately running manager on the selected port. Both output directories must
be fresh. The example's 240-second command bound and 180-second probe bound leave
room for the probe's own cleanup; they are declared operational settings.

```sh
python /path/to/UAV-VLA-Lab/scripts/run_simulation_session.py \
  --upstream /actual/AeroVLA \
  --env-root /actual/envs \
  --cwd /actual/AeroVLA \
  --output /actual/new/p03-session \
  --manager-port 30000 --gpus 0 \
  --port-cooldown-seconds 60 \
  --readiness-timeout-seconds 60 \
  --command-timeout-seconds 240 \
  -- python /path/to/UAV-VLA-Lab/scripts/simulator_probe.py \
     --mode capture --upstream /actual/AeroVLA \
     --episode-json /actual/selection/episode.json \
     --dataset-root /actual/dataset_raw \
     --output-dir /actual/new/p03-probe \
     --simulator-port 30000 --gpu-id 0 \
     --scene-manager-exclusive --max-wall-seconds 180
```

The manager uses this runner's interpreter by default; `--manager-python` selects
another installed interpreter explicitly. Arguments following `--` are passed as
an argv list, without shell parsing by the wrapper. Use the actual evaluator or
other command there for later phases. The wrapper sets
`VLA_LAB_SCENE_MANAGER_EXCLUSIVE=1` while running that command and records this
override. It does not infer the navigation evidence directory: declare the actual
`VLA_LAB_EVENT_DIR` or evaluator save path in the trial manifest.

## Ownership, readiness and bounded cleanup

Before spawning anything, sequential localhost bind checks cover the manager
port and all 1,000 candidate scene ports used by the pinned manager. The sockets
are closed immediately. This is a snapshot, not an operating-system reservation;
keep the complete range exclusively assigned to this session until it ends.
The pinned manager's own RPC implementation retains port-based scene cleanup.
The wrapper does not call those helpers, `pkill`, or `close_scenes`.

For sequential restarts, `--port-cooldown-seconds` defaults to 60 and accepts
0–60 seconds; zero requests one preflight without retries. A strict bind can
return `EADDRINUSE` after a clean shutdown because TCP connections remain in
`TIME_WAIT`. [Tornado 4.5.3 sets `SO_REUSEADDR` on Unix](https://github.com/tornadoweb/tornado/blob/v4.5.3/tornado/netutil.py),
but enabling reuse in preflight could also admit another bound, non-listening
socket. The runner therefore keeps strict binds. It repeats a failed scan only
when every bind error is `EADDRINUSE` and a bounded `lsof` check of the complete
port range observes no live listener. That absence is not labeled proof of
`TIME_WAIT`. An observed listener, unrecognized/failed listener inspection or
different bind error aborts immediately. A persistent bound socket still fails.
Nothing is connected to or killed by this cooldown check.

Every scan and listener result is retained in `port-preflight-attempts/`; the
summary includes their hashes, statuses and retry count, and lifecycle events
record each attempt. The cooldown bounds retries; one in-progress bind scan and
the listener inspection (at most two seconds, reduced to the remaining budget)
can add observation overhead. Manager readiness and command timeout budgets
start separately after preflight succeeds. If the range stays occupied when the
cooldown expires, no manager or workload starts. Keep that failed session evidence
and use a fresh output directory for a later restart; do not erase it or kill an
unknown socket owner to make the check pass.

The manager starts with `start_new_session=True`. Readiness requires both a real
TCP connection to `127.0.0.1` and an `lsof` listener PID matching that spawned
manager. A TCP-ready manager is not evidence of a ready map or model. Manager
readiness has its own timeout; the workload's independent timeout starts only
when it is launched. Individual inventory/listener commands have short bounded
timeouts, so process observation can add a small amount to a readiness boundary.

The existing command supervisor runs in the wrapper process and creates a
separate session/process group for the workload. It handles workload timeout,
signals, logging and remaining descendants according to its own runbook. After
it returns, this wrapper sends TERM only to the manager PGID it created, waits
`--manager-grace-seconds` (default 5), then sends KILL to that same group if still
visible and waits `--kill-wait-seconds` (default 2). No unrelated PID or port is
used as a kill target. The inspected manager's shell-launched scenes inherit its
group. Observed descendants that escape that group are recorded and cause cleanup
to remain incomplete; the wrapper does not silently kill a different group.

Process ancestry/group snapshots are sampled about once per second, with process
start identity retained to avoid treating observed PID reuse as the same child.
They contain no process environment or command-line dumps. A descendant that
escapes between snapshots may be missed. Visible zombies or uninterruptible tasks
are reported as incomplete cleanup rather than certified absent. SIGKILL of the
wrapper cannot guarantee finalization; inspect the owned-PGID evidence before any
manual intervention. Normal TERM/INT is handled by the current lifecycle owner.

## Evidence and exit interpretation

```text
session/
  config.resolved.json
  port-preflight.json
  port-preflight-attempts/0001.json
  lifecycle.jsonl
  manager.stdout.log
  manager.stderr.log
  settings-before.json
  settings-copied.json
  settings/<port>/settings.json
  report.json
  command/
    events.jsonl
    stdout.log
    stderr.log
    report.json
```

The wrapper copies new or changed settings files after shutdown, including their
source/copy hashes. A settings file is configuration evidence, not a fabricated
observation. The upstream manager discards native scene stdout; this wrapper
retains manager and workload output but cannot reconstruct that discarded output.

`report.json` uses `vla.simulation-session.v1`. `command_child_returncode` retains
the workload's actual child code; `command_supervisor_returncode` and its alias
`command_returncode` retain the existing supervisor's normalized outcome.
`command_termination_reason` points to natural exit, timeout or interruption.
`session_returncode` is the wrapper outcome. A nonzero command outcome is
preserved even if manager cleanup also fails. Command success becomes exit 1 if
the manager exited prematurely, cleanup is incomplete or settings evidence could
not be copied. Manager readiness timeout exits 124; other startup failures exit 1.

Inspect `cleanup.complete`, group visibility and final process evidence along
with the nested command report. A successful shell command is not a navigation
success. A manager startup failure does not mean a mission was attempted. Later
trial summaries must explicitly map planned trials, launched attempts, session
reports and genuine navigation outcome records; do not infer missing launches.

## Local verification

```sh
python3 -m unittest discover -s tests -p test_simulation_session.py -v
```

The tests cover real server-side `TIME_WAIT` (confirmed through the operating
system's socket table), successful reuse-bind/listen in that state, and bounded
failure of the strict preflight while the connection remains. They do not wait
for the kernel's complete `TIME_WAIT` lifetime or claim to measure it. Additional
socket tests cover a reusable live listener that aborts without cooldown, a
conflicting bound but non-listening socket, and a successful evidenced retry once
that bound socket closes. They also cover
observed escaped descendants/PID reuse, bounded signaling of only the owned
manager group, and an actual synthetic localhost manager around a failing
command. Socket fixtures require local loopback access. These fixtures never
count as simulator or model evidence.
