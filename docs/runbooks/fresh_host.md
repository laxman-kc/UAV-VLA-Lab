# Fresh Linux GPU acceptance

This is an executable rebuild/acceptance recipe for the refactored installed
package. The previous GPU host was backed up and deleted. **This new recipe has
not yet passed a fresh GPU run.** CPU package tests are not graphics, inference,
reset or training evidence. Provisioning and deletion remain operator actions.

Use Ubuntu 22.04 x86_64 with Python 3.10 and a graphics-capable NVIDIA GPU. Check
delivered CPU/RAM/free disk and NVIDIA driver/Vulkan visibility rather than using
an advertised listing as an observed inventory. Keep simulation and training
sequential. The declared reserve is 60 GiB in addition to the required new files.
The stack pins, omissions and host-library limits are in the
[environment record](../../environments/aerovla-linux-cu118/README.md).

Build `python -m build --no-isolation` (sdist, then a wheel from its clean source tree) on the development machine and transfer the
wheel to the explicitly selected host. Install it into a small host tool venv.
Run the following in **bash** with real paths replacing `/actual/...`. The pinned
upstream manager uses shell interpolation; upstream and environment asset paths
must use only letters, digits, `_`, `/`, `.` and `-`.

```bash
set -euo pipefail
export VLA_DATA_ROOT=/actual/persistent/vla-data
export VLA_UPSTREAM_ROOT=/actual/persistent/AeroVLA
export VLA_WHEEL=/actual/transferred/uav_vla_lab-0.1.0rc1-py3-none-any.whl
uav-vla runtime bootstrap --data-root "$VLA_DATA_ROOT" \
  --upstream "$VLA_UPSTREAM_ROOT" --wheel "$VLA_WHEEL"
# The preceding command only prints its plan. This applies it on this host:
uav-vla runtime bootstrap --data-root "$VLA_DATA_ROOT" \
  --upstream "$VLA_UPSTREAM_ROOT" --wheel "$VLA_WHEEL" --apply
source "$(uav-vla runtime activate --print-path)"
uav-vla runtime inventory --data-root "$VLA_DATA_ROOT" \
  --output "$VLA_DATA_ROOT/setup/fresh-runtime/host.json"
```

Bootstrap refuses an existing venv/upstream path, installs the pinned code and
dependency family, applies the exact published RPC repair and observation hooks,
then runs import/CUDA and Vulkan commands. It preserves failures/logs. Inspect
`setup/fresh-runtime/runtime-probe.json`, `pip-check.log` and
`vulkan-summary.log`: the Vulkan device must actually be NVIDIA; a software
renderer or CUDA-only result does not pass the graphics gate. No environment
binary or model is launched by bootstrap. An OS/driver mismatch must remain a
failed admission, not silently trigger driver or protocol changes.

Acquire the explicit 19-file model inventory and eight pinned archive parts:

```bash
uav-vla dataset snapshot --intent "$(uav-vla dataset intent models)" \
  --root "$VLA_DATA_ROOT/assets/models"
uav-vla dataset snapshot --intent "$(uav-vla dataset intent models)" \
  --root "$VLA_DATA_ROOT/assets/models" --apply
uav-vla dataset download --manifest "$(uav-vla dataset intent map)" \
  --root "$VLA_DATA_ROOT/assets/archives"
uav-vla runtime extract-simulator
uav-vla assets --report "$VLA_DATA_ROOT/manifests/raw-verified.json" verify \
  --archive-dir "$VLA_DATA_ROOT/assets/archives/dataset_raw" --category dataset_raw
7z t "$VLA_DATA_ROOT/assets/archives/dataset_raw/ModernCityMap.zip"
mkdir -p "$VLA_DATA_ROOT/assets/dataset_raw"
7z x "$VLA_DATA_ROOT/assets/archives/dataset_raw/ModernCityMap.zip" \
  "-o$VLA_DATA_ROOT/assets/dataset_raw"
```

The model intent carries actual recorded SHA256/bytes and immutable revisions;
it does not resolve `main` or latest. Existing mismatched files and a prior final
snapshot receipt are never overwritten. Archives plus declared expansion total
58,228,658,936 bytes before models, cache, temporary joins and new evidence.
Measure free space again before raw extraction. The [asset runbook](assets.md)
describes multipart fallback and the pinned metadata converter. Acquire that
specific converter URL/hash from the map manifest, then:

```bash
uav-vla assets convert --data-root "$VLA_DATA_ROOT" \
  --converter /actual/verified/generate_merged_json.py --seed 100
uav-vla assets --report "$VLA_DATA_ROOT/manifests/demo-validated.json" validate \
  --data-root "$VLA_DATA_ROOT" --groups demo --require-merged
uav-vla dataset episode \
  --split "$VLA_UPSTREAM_ROOT/data/uav_dataset/seen_valset_splits/ModernCityMap.json" \
  --episode-id 23cda8d5-d239-4b15-bcf8-ffdb28a43f07 \
  --dataset-root "$VLA_DATA_ROOT/assets/dataset_raw" \
  --metadata-root "$VLA_UPSTREAM_ROOT/data/meta" \
  --output-dir "$VLA_DATA_ROOT/runs/fresh-demo-selection"
ln -s "$VLA_DATA_ROOT/assets/dataset_raw" "$VLA_UPSTREAM_ROOT/dataset_raw"
ln -s "$VLA_DATA_ROOT/assets/models/openvla-7b" "$VLA_UPSTREAM_ROOT/openvla-7b"
```

Freeze a **new** runtime identity and select its reset explicitly. These are new
source/host receipts, not a reuse of the deleted host's identity:

```bash
export VLA_RUNTIME_ID=fresh-rpcfix-msgpack112-paused-final-pose-time-v1
uav-vla runtime freeze --upstream "$VLA_UPSTREAM_ROOT" \
  --readiness-report "$VLA_DATA_ROOT/setup/fresh-runtime/runtime-probe.json" \
  --runtime-id "$VLA_RUNTIME_ID" --reset-protocol paused-final-pose-time-v1 \
  --output "$VLA_DATA_ROOT/manifests/fresh-runtime.json"
uav-vla runtime env --data-root "$VLA_DATA_ROOT" --python "$VLA_ENV/bin/python" \
  --receipt "$VLA_DATA_ROOT/manifests/fresh-runtime.json" \
  --runtime-id "$VLA_RUNTIME_ID" --reset-protocol paused-final-pose-time-v1 \
  --evidence "$VLA_DATA_ROOT/runs/fresh-policy/evidence" \
  > "$VLA_DATA_ROOT/setup/fresh-runtime/run-env.sh"
source "$VLA_DATA_ROOT/setup/fresh-runtime/run-env.sh"
cd "$VLA_UPSTREAM_ROOT"
uav-vla simulate --upstream "$VLA_UPSTREAM_ROOT" \
  --env-root "$VLA_DATA_ROOT/assets/envs" --cwd "$VLA_UPSTREAM_ROOT" \
  --output "$VLA_DATA_ROOT/runs/fresh-capture-session" \
  --command-timeout-seconds 300 -- \
  uav-vla integration probe --mode capture --upstream "$VLA_UPSTREAM_ROOT" \
  --episode-json "$VLA_DATA_ROOT/runs/fresh-demo-selection/episode.json" \
  --dataset-root "$VLA_DATA_ROOT/assets/dataset_raw" \
  --output-dir "$VLA_DATA_ROOT/runs/fresh-capture" --simulator-port 30000 \
  --gpu-id 0 --scene-manager-exclusive --max-wall-seconds 180 \
  --reset-protocol paused-final-pose-time-v1
```

The capture probe has its own reset flag; the evaluator receives exported reset
environment variables. One does not implicitly select the other. Inspect all
actual camera/ground-truth/cache gates, both resets and owned cleanup. Only then
run the same bounded controller command with `--mode controller` and **new**
session/probe output paths. Keep failed attempts. The acceptance tolerances remain
0.1 m and 0.05 rad; no package-portability success relaxes them.

After cleanup, run `uav-vla integration offline --help` and the
[three-pair offline probe](offline_policy.md) against the same demo/model roots.
Then the [one-episode evaluator command](aerovla_integration.md) can run inside
`uav-vla simulate` with a declared wall-time bound and the exported runtime
receipt/reset/evidence values above. Set a fresh evidence directory for every
actual evaluator attempt. Record the command argv, source/model hashes, actual
gates and complete session report. A generated report alone is not acceptance.

A bounded four-hour fresh-host session can prioritize bootstrap, pinned assets,
capture/controller and offline/one-episode integration as capacity/time permit;
the deadline is an operational cap, not a promise these gates will pass. Stop
starting new work early enough to preserve evidence and verify owned cleanup.
Training `--validate-only` can check restored reviewed data/parent contracts without
GPU execution. An actual one-update mechanics test requires its own explicit
fresh output and declared inputs. Do not resume/overwrite P12 or rerun the study
as part of package acceptance. Copy/hash all new unique results before retirement.
