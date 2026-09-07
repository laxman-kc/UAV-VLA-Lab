# Bounded command supervision

Use `scripts/supervise_run.py` to give one command a wall-clock limit and preserve its actual stdout, stderr, arguments and lifecycle. This tool supervises a command; it does not establish that an experiment or phase passed.

```sh
python scripts/supervise_run.py \
  --cwd "$AEROVLA_CHECKOUT" \
  --output /home/shadeform/vla-data/runs/p06-supervision-attempt-001 \
  --timeout-seconds 900 \
  --grace-seconds 15 \
  --poll-gpu \
  -- python src/vlnce_src/eval_aerovla.py YOUR_REVIEWED_ARGUMENTS
```

Replace the command and its arguments with the reviewed run command. The command is passed directly as an argv array, without shell evaluation; shell functions, variable expansion inside arguments, and pipelines require an explicitly invoked shell. The child receives closed stdin. The output directory must be new; an existing attempt is never overwritten. Argument values and command output are recorded, so do not pass credentials as command arguments. Environment variables are inherited for execution but are not dumped into evidence.

The child starts in a new session/process group. The supervisor sends SIGTERM to that group when the wall-clock timeout expires or the supervisor receives SIGINT/SIGTERM. If the group remains after the grace period, it sends SIGKILL. A repeated interrupt requests immediate escalation. Cleanup is bounded by up to two additional seconds after SIGKILL. A process in an uninterruptible kernel state or a zombie can remain visible; the report states that explicitly. It does not claim that SIGKILL guaranteed disappearance.

If the root command exits naturally while descendants remain in its group, those descendants also receive bounded cleanup, which is recorded separately from the child's natural exit status. Commands that intentionally daemonize into a new process group leave this supervisor's ownership; do not use that behavior for an experiment expected to be fully supervised. An independently started scene manager outside the created process group is never targeted. If an evaluator itself issues shutdown calls to an external manager, those are the evaluator's behavior, not supervisor group signaling.

`stdout.log` and `stderr.log` contain actual unmodified output. `events.jsonl` records spawn, periodic observations, interruption/timeout, signals and termination. `report.json` records the root PID/group ID, raw child return code, final process/group visibility, supervisor status, command duration and hashes of the evidence files. A root process observed as alive does not prove that its simulator or model is making progress.

With `--poll-gpu`, the supervisor queries `nvidia-smi` approximately every five seconds while the command is running. Values are **host-wide totals for each GPU**, including other workloads; they are not this command's GPU allocation or utilization. A missing/failing GPU query is recorded and disables subsequent GPU queries. If psutil is already installed, CPU percentage and resident memory describe only the root command process and exclude descendants; no dependency is installed automatically. CPU percentage may exceed 100 for multiple cores, and the first sample is left null. Polling adds some overhead and is diagnostic rather than precise profiling.

The supervisor returns the child's natural nonnegative exit code, or 128 plus its terminating signal. Supervisor timeout returns 124; SIGINT returns 130; SIGTERM returns 143. Failure to start a missing command returns 127. An otherwise successful command with a process group still visible after bounded cleanup returns 1 with `cleanup_incomplete`. Use `report.json` to distinguish these cases from a child that independently returned the same integer. No success code by itself passes P06: inspect the evaluator artifacts and phase acceptance gates separately.

Run the bounded local lifecycle checks with:

```sh
python -m unittest discover -s tests -p 'test_supervise_run.py' -v
```

These checks exercise real small local Python subprocesses, failures, timeouts, forced termination, SIGINT/SIGTERM and an unrelated process. They are not simulator or model evidence.
