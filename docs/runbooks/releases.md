# Build a release from recorded evidence

`scripts/build_release.py` packages actual inputs into a portable draft release. It writes matching Markdown and HTML reports, source copies, manifests, hashes, captions and frame mappings. With `--render-video`, it also encodes an MP4 and checks its complete decode. It never executes commands from a specification, launches a simulator, invents observations, infers a research result, or declares an unreviewed video visually valid.

Use this with [the delivery standard](../DELIVERY_STANDARD.md). A valid artifact bundle can document an engineering failure. A successful packaging command is not a successful phase experiment.

## Prerequisites

- Python 3.10 or later for reports and integrity verification; no Python packages are needed for those operations.
- For video: Pillow 10.1 or later, `ffmpeg` with the `libx264` encoder, and `ffprobe` on `PATH`.
- An actual inventory JSON, acceptance-check JSON and resolved configuration file. The configuration may be YAML or JSON, which is also valid YAML.
- Real logs or saved PNG/JPEG camera observations. Review supplied files and command strings for credentials and unrelated private information before packaging. The tool rejects common credential patterns, but does not claim exhaustive secret detection or inspect image contents for secrets.

On the inspected Mac, the bundled runtime has Pillow and the installed FFmpeg has `libx264`:

```sh
/Users/laxmankc/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/build_release.py --spec /absolute/path/release-spec.json --output /absolute/path/new-release-directory --render-video
```

Use the appropriate Python path elsewhere. The ordinary `python3` inspected on this Mac lacks Pillow, but can build reports or verify releases. No automatic installation or driver changes occur.

## Input contract

All paths in a release specification resolve relative to that JSON file. Evidence references inside a checks JSON resolve relative to the checks JSON, not to the release specification. Absolute input paths are accepted; packaged references are relative paths. Package only small evidence and selected observations; large datasets and base models belong in external asset manifests, not `attachments`.

Required specification fields:

| Field | Meaning |
|---|---|
| `phase_id`, `release_id` | Explicit identifiers containing letters, digits, `_`, `-`, or `.` |
| `title`, `objective` | Concise video title and complete capability/scope description |
| `engineering_status` | `planned`, `running`, `passed`, `failed`, or `blocked` |
| `research_status` | Explicit supported conclusion, such as `not_applicable` or `pilot_only` |
| `inventory` | Actual host inventory JSON path; unknown values remain null |
| `checks` | Actual acceptance-check JSON path |
| `resolved_config` | Configuration path with secrets removed |
| `commands` | List of actual reproduction command strings; displayed, never executed |
| `runs` or `non_episode_phase` | Attempt CSV, or explicitly `true` for a phase without missions |

Useful optional fields: `source` (including `project_commit`, upstream and patch identity), `method`, `prerequisites`, `findings`, `measurements`, `workload`, `limitations`, `unknowns`, `interruption_handling`, `cleanup`, `next_decision`, `attachments` and `video`.

Every finding has a `kind` of `measured`, `source_fact`, `interpretation`, `proposed` or `unavailable`, and a `text` value. Measurements and workload counts are copied as supplied; provide units, sample counts, denominators and evidence references. Missing values are not replaced with zero. The tool checks that a claimed engineering pass does not coexist with a failed, blocked or unrun acceptance criterion.

The following is an **input-shape example**, not a populated release or a tested remote command. Replace its paths and content with recorded evidence:

```json
{
  "phase_id": "P01",
  "release_id": "P01-actual-run-id",
  "title": "Host diagnostic evidence",
  "objective": "Document the actual diagnostic and its remaining gates.",
  "engineering_status": "blocked",
  "research_status": "not_applicable",
  "inventory": "host-inventory.json",
  "checks": "checks.json",
  "resolved_config": "config.resolved.yaml",
  "commands": [],
  "non_episode_phase": true,
  "source": {"project_commit": null},
  "limitations": ["Fill this with the actual unsupported or untested scope."],
  "unknowns": [],
  "findings": [],
  "measurements": {"gpu_peak_bytes": null},
  "video": {
    "kind": "terminal_log",
    "fps": 10,
    "selection_rule": "Selected diagnostic ranges; complete original log is packaged.",
    "events": [
      {
        "id": "diagnostic-range-1",
        "source": "host-diagnostic.log",
        "first_line": 1,
        "last_line": 8,
        "display_seconds": 8,
        "caption": "Recorded diagnostic output; consult the checks for the gate status."
      }
    ]
  }
}
```

Checks may be a JSON list or an object with a `checks` list. Each row uses `id`, `criterion`, `result`, `timestamp`, `evidence` and `reason`. Results are `pass`, `fail`, `not_applicable`, `blocked`, or `not_run`. Pass/fail rows require a timestamp and at least one existing evidence file. `passed` and `failed` aliases are normalized. A check can cite the diagnostic log and inventory file; external URLs belong in the report, not in file evidence references.

```json
{
  "checks": [
    {
      "id": "graphics-runtime",
      "criterion": "Graphics runtime verified by a real frame capture",
      "result": "not_run",
      "timestamp": null,
      "evidence": [],
      "reason": "Example schema only; replace with the actual diagnostic outcome."
    }
  ]
}
```

## Log videos and observation replays

P01/P02 log videos display selected lines from supplied real logs. They are labeled **“Recorded log excerpts; editorial holds; not live screen capture.”** Text is not animated to imply execution. The original file hash, inclusive line range and exact excerpt hash remain available. ANSI escape sequences are removed only in the visual rendering; the source/excerpt files preserve original bytes. Tabs expand in the display. Split long excerpts into events: the renderer rejects more than 16 wrapped lines instead of hiding/truncating evidence.

Observation videos use `kind: "observations"` and require `population_ref`, a file describing the complete attempt population and selection context. Each event requires an actual saved PNG/JPEG `source`, `run_id`, `attempt_id`, `observation_id`, `camera`, `display_seconds` and `caption`. Include `episode_id`, `map_id`, `mission_id`, `checkpoint_id`, `task_mode`, `requested_action`, `applied_action`, `termination_reason`, `camera_timestamp`, `simulator_timestamp` and `host_timestamp` where known. Missing fields are displayed as unavailable or retained as null. Do not put a state timestamp into `camera_timestamp` unless it was the camera timestamp actually recorded.

Images are decoded as RGB and fit into the video without changing their aspect ratio. Their original dimensions and hashes are preserved. Resizing for readability is not added source detail. Animated inputs are rejected. This is inspection of saved observations, not simulator re-rendering from poses.

Output timing is always editorial display time. At the chosen integer `fps`, every `display_seconds × fps` must be an integer. Each selected event is held for exactly that many frames. The tool does not interpolate camera timestamps or infer real-world timing from file names or frame order. Missing capture timestamps trigger the visible disclosure **“Sampled observations; elapsed timing unavailable.”** Selection rules must disclose omitted material; every cut is the boundary between mapped events. There are no implicit transitions or undocumented speed changes.

The complete mapping is in `video/frames.csv`: one row for every encoded frame, including its event/source hash, original IDs/timestamps and output presentation time. Captions are burned into each slide and supplied as SRT/VTT sidecars. H.264 output is 1280×720, yuv420p. FFmpeg version, font identity, commands and exit codes are recorded.

## Build, inspect, finalize, verify

Build into a **new directory**. Existing output directories are never overwritten:

```sh
python3 scripts/build_release.py --spec /absolute/path/release-spec.json --output /absolute/path/new-release
```

This creates a report draft and media selection/mapping, if supplied. Add `--render-video` using a Python with Pillow to produce the MP4. An encoding/input failure leaves `BUILD_FAILED.json` and any diagnostic output; that directory is not a completed release. Correct the input and use a new directory.

After rendering, inspect `video/demo.mp4` and `report.html`. Review the whole concise video, including beginning, event transitions and end. Confirm legibility, source ordering, captions, timing disclosure and agreement with results. The generated `video/validation.json` initially records visual review as `not_run`, regardless of successful encoding.

Supply an attestation **only after actual review**:

```json
{
  "reviewer": "actual reviewer identity",
  "timestamp": "actual UTC review timestamp",
  "status": "passed",
  "reviewed_entire_video": true,
  "video_sha256": "actual SHA256 of video/demo.mp4",
  "notes": "Actual observations on legibility, transitions, captions, source identity and report consistency."
}
```

Then finalize the draft once:

```sh
python3 scripts/build_release.py --finalize /absolute/path/new-release --visual-review /absolute/path/visual-review.json
python3 scripts/build_release.py --verify /absolute/path/new-release
```

Finalization rejects an attestation for a different video and requires explicit limitations and source provenance: a `project_commit`, or `source.working_tree_files` with exact source-file hashes when the executed work is not yet committed. Record that distinction and package the matching small source files as attachments. Never attribute uncommitted changes to an older commit. Finalization updates the report, manifest and hashes consistently and seals `artifact_status: verified`. This is the only deliberate in-place transition from draft to sealed release. A sealed release cannot be finalized again; corrections require a new release ID/directory. Engineering/research status remains the supplied outcome and is never upgraded by artifact finalization.

`--verify` checks the full file inventory, hashes/sizes, path confinement, absence of symlinks, evidence references, exact log excerpts, frame/event identities and recorded timestamps. It rejects unlisted additions as well as missing or changed files. It does not re-run the experiment or prove that an attestation is honest. Original video production runs both `ffprobe -count_frames` and a full `ffmpeg -xerror` decode, checking codec, dimensions, duration and mapping frame count.

`manifest.json` inventories all files except itself and `checksums.sha256`; the checksum file includes the manifest and every other packaged file. Hashes provide integrity checks, not authentication or a cryptographic signature. Do not modify a release after copying it to the Mac; run verification again after transfer.

## Validation of the generator

```sh
python3 -m unittest discover -s tests -p test_release.py -v
```

Without Pillow/FFmpeg, media integration tests skip explicitly. Run the same command with a Python containing Pillow to exercise actual H.264 encoding, full decode, image dimension/provenance preservation and hash-bound review. All tests use temporary fixtures labeled as tests; they do not create phase results or claim a remote experiment occurred.
