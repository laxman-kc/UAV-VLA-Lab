# Phase delivery standard

**Status: proposed project standard. No phase evidence or videos exist yet.**

This standard applies to every MVP in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). It defines how completed work will be demonstrated and reproduced. Its files are created from actual implementation evidence; templates are never presented as completed reports.

## 1. Definition of a completed release

A phase is complete when its working entry point has run, its stated acceptance checks have evidence, and its documentation, report and video agree with that evidence. Write the exact command after the implementation exists; proposed CLI names are not executable instructions today.

Each phase plan contains one capability, explicit exclusions, prerequisites, measurable acceptance criteria, bounded workload and evidence requirements. Record scope changes before running revised checks. Keep the release ID distinct from its phase ID so a correction or later batch can have a new immutable release.

Use separate status fields:

- **Engineering:** planned, running, passed, failed, or blocked, with evidence and reasons.
- **Research:** not applicable, pilot only, no demonstrated improvement, or the specific supported result.
- **Artifacts:** incomplete or verified, with a check result for each required file.

A model can fail a navigation mission while the loop-integration MVP passes. A software crash can demonstrate interruption handling, but cannot be counted as a valid mission outcome. Do not overwrite failed attempts with successful retries.

Well-documented artifacts that support their stated claims and can be reused are established research-delivery objectives. The bundle below is our project implementation of those objectives, not an assertion of ACM certification. [ACM CCS artifact guidance](https://sigsac.hosting.acm.org/ccs/CCS2025/call-for-artifacts/).

## 2. Required documentation and report

| File | Required contents |
|---|---|
| `README.md` | Capability delivered, status, quick reproduction entry point, report/video links, limitations |
| `RUNBOOK.md` | Actual prerequisites, install/run commands, expected observable outputs, artifact locations, interruption handling, cleanup and known fixes |
| `REPORT.md` | Objective, method, configuration, acceptance evidence, measured results, failures, interpretation, limitations and next decision |
| `report.html` | Readable rendering of the same report with linked figures and evidence; no divergent results |
| `manifest.json` | Release/phase IDs, source and patch revisions, models/data/protocol/configuration hashes, actual host inventory, artifact inventory and statuses |
| `config.resolved.yaml` | All effective experimental settings, with secrets excluded; unresolved values prohibit dependent execution |
| `evidence/checks.json` | Each acceptance criterion, pass/fail/not-applicable result, timestamp and evidence reference |
| `evidence/runs.csv` | Planned trial IDs, actual attempts, outcome and reason; mark non-episode phases appropriately |
| `checksums.sha256` | Integrity hashes for packaged files, excluding this checksum file itself |

Reports distinguish measured quantities, source facts, proposed decisions and unavailable values. Never fill unknown measurements with zero. For experiments, show planned trials, started trials, valid outcomes, infrastructure failures, invalid outputs and all retry attempts. State every denominator and exclusion rule.

Record model-weight identity separately from execution-protocol identity. An original-weight run with changed clocks, parsing or control is not an exact upstream reproduction. State whether evaluation data is held out only from this project's adaptation or is also known to be disjoint from upstream model training; unresolved upstream exposure stays unknown.

Resource tables include actual GPU/CPU/RAM, elapsed time, peak memory and artifact bytes where relevant. Give measured latency distributions rather than claiming a fixed control frequency. Evaluation reports retain per-mission rows and describe uncertainty and its limits. The final report makes no larger claim than its test scope supports. [NeurIPS paper checklist](https://neurips.cc/public/guides/PaperChecklist).

Keep documentation compact: a short result page plus detailed evidence references. Charts show units, sample counts, protocol/checkpoint identities and data provenance. Use the same layout and vocabulary throughout all phases.

## 3. Video evidence standard

### Content and presentation

Use **real evidence from the phase**. P01/P02 can show the actual diagnostic/validator terminal and report. P03/P04 show simulator captures and scripted movement. P05 shows offline inference. P06 onward can show recorded closed-loop observations. Training phases show actual logs, plots and checkpoint checks.

The proposed format is an MP4 with readable text, captions and an approximately one-to-three-minute editorial target. Choose a compatible H.264 encoder after inspecting the installed FFmpeg build; record its actual version and settings. Preserve original camera aspect ratios and color interpretation. A polished output layout does not increase the resolution or information content of source frames. Narration is optional.

Suggested sequence:

1. Identify the phase, release, capability and evidence type.
2. Demonstrate the actual workflow or recorded episode.
3. Show the acceptance result and measured outcome.
4. State the main limitation and link to the full report/evidence.

For policy demonstrations, display the map/mission, checkpoint, task/goal-information mode, observation ID, requested action, applied action and termination reason where available. Explain missing fields. A scripted-controller clip is labeled scripted; it is not a policy demonstration. No generated or illustrative footage is presented as an experiment.

### Time and frame provenance

The inspected upstream action path unpauses the simulator and does not re-pause before subsequent inference. Its endpoint sensor record is duplicated; duplication is not a set of independent samples. Raw timestamps and logging overhead therefore matter. [Pinned AeroVLA client](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/airsim_plugin/AirVLNSimulatorClientTool_AeroVLA.py).

Prefer encoding from saved observations after the GPU experiment. This avoids adding video-encoding work to its GPU load, while still measuring the overhead of observation recording itself. Preserve raw images separately from the rendered video.

For each displayed source frame, `frames.csv` records source path/hash, run/episode/attempt/observation IDs, available camera/simulator/host times and output presentation time. A source screen capture may instead use a clip-to-log time mapping. Never substitute a nearby state timestamp for a missing camera timestamp.

The video states its timeline: wall time, simulator time, or sampled observations with assigned display durations. If capture timing is unavailable, explicitly label it **“sampled observations; elapsed timing unavailable.”** Declare repeated holds, omitted frames, gaps, cuts and speed changes. Video playback FPS does not establish camera sampling rate, policy frequency or simulator speed. FFmpeg's image-sequence input timing is assigned by its input settings. [FFmpeg format documentation](https://ffmpeg.org/ffmpeg-formats.html).

A visual replay means inspection of saved observations. A simulator re-render from poses is a visualization and must be labeled as such; it does not prove exact reproduction of physics/controller state.

Side-by-side comparisons declare their alignment axis: simulator time, host elapsed time, or decision index. Display each run's own elapsed time when available and disclose any holds or cuts used for alignment. Matched decision indices do not demonstrate equal elapsed-time performance.

### Selection and validation

Before selecting final clips, save a rule in `video/selection.json`. A suitable default is the first valid completed trial and first failure under the recorded trial order, if available; for comparisons, include changed-outcome cases and disclose their selection. An interrupted attempt can be shown as interrupted. Report the full trial population even when the video is short.

Validate the encoded file programmatically and visually. A metadata probe alone is insufficient. Confirm dimensions, duration, decoding, captions, source-frame mapping and consistency with report results. Review the full concise final cut, including its beginning, transitions and end. For a silent video composed entirely of static terminal-log evidence segments, an alternative is to visually inspect a decoded representative of every mapped segment, retain the inspected evidence and its hashes, verify every encoded frame against its reviewed segment reference within fixed recorded reconstruction tolerances, and check all encoded frame timestamps plus complete decoding. Record this as `all_static_segments`, with exact event coverage and the video SHA256; do not claim continuous playback. This alternative does not apply to flight footage or observation videos, whose changing content requires full-video review.

The following are command templates to run from a real release directory once its video exists:

```sh
ffprobe -v error -count_frames -show_format -show_streams -of json video/demo.mp4 > video/ffprobe.json
ffmpeg -v error -xerror -i video/demo.mp4 -f null - 2>video/decode.log
```

Save return codes as well as output, and resolve errors before artifact verification. ffprobe provides machine-readable format/stream information and frame counts for these checks. [ffprobe documentation](https://ffmpeg.org/ffprobe.html).

## 4. Storage, integrity and handoff

Keep source-controlled docs/configs separate from large assets and runtime results. Persist large files to the mount verified in P01; do not assume every temporary directory survives instance lifecycle events. NVIDIA describes different persistence behavior for stopping and deleting an instance, so record the actual instance/storage arrangement used. [Brev GPU-instance documentation](https://docs.nvidia.com/brev/concepts/gpu-instances).

Large external artifacts may be referenced rather than copied into every release, provided their manifest contains stable locations, byte sizes, hashes and required access instructions. Avoid duplicating base weights for each phase. Export selected reports/videos to the Mac, verify their hashes after transfer, and record what remains remote.

Finalize manifests and reports before calculating package hashes. Never include credentials in exported commands or configuration. Later changes receive a new release ID. Every handoff says what exists, what passed, what failed, what remains pending, and which exact command reproduces the demonstrated capability.

## 5. Templates

- [Phase plan](templates/PHASE_PLAN.md)
- [Release README](templates/RELEASE_README.md)
- [Report](templates/REPORT.md)
- [Runbook](templates/RUNBOOK.md)
- [Video plan](templates/VIDEO_PLAN.md)
- [Manifest example](templates/release-manifest.example.json)

The example JSON deliberately contains null unknowns. It is a template, not a valid completed release manifest. Runtime validation will require the applicable provenance and evidence fields before marking a release verified.
