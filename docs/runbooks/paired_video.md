# P13/P14 paired evidence video

`scripts/prepare_paired_video.py` prepares a bounded presentation from an existing accepted P13 development or P14 confirmation comparison. It performs no inference, simulation, training, checkpoint selection or additional policy evaluation. The P14 mode reads only the supplied completed comparison evidence after the holdout execution. Its tests use synthetic metadata to check the selection and causal-index contracts; they are not experimental results.

The actual editorial rule was frozen before candidate outcomes were inspected. Its immutable v2 file is `data-local/release-specs/p13-video-selection-plan-v2.json`, SHA256 `a3b6ab1396d25a5c73ef6b7dd76829f510a27d7d7356bbc865d6720284a80c33`, recorded at `2026-09-07T06:05:54.294819+00:00`. The earlier v1 is retained: read-only baseline inspection showed that observations have no literal loop-index field, so v2 specifies the causal derivation explicitly. Category and mission selection did not change.

All planned missions appear in declared order: 20 for this P13 comparison, 10 for a separately frozen P14 confirmation. The image categories are the first original-only SR success and first candidate-only SR success. Missing categories are stated explicitly. Only when both are absent does the first matched valid pair with the same SR outcome become the fallback. Unscored trials remain unavailable in the table and cannot supply a favorable substitute. OSR does not select clips.

For each selected attempt, the helper rechecks the existing observation→prompt→generation→decode→request→completion links. A decision index is the number of completed actions before that observation. Indices must be unique and contiguous, beginning at zero, and the final index must equal the audited terminal index. From the exact common indices it selects the first, lower middle and last, deduplicating if necessary. If terminal indices differ, a separate pair shows each arm's actual final observation with its own index.

First copy the completed comparison, both analyses and both complete event logs. The candidate PNG corpus is not needed yet. Run the request stage with exact existing paths:

```sh
python3 scripts/prepare_paired_video.py request \
  --selection-plan data-local/release-specs/p13-video-selection-plan-v2.json \
  --paired-plan data-local/p13-paired-development-v1/paired-plan.json \
  --comparison <actual-comparison.json> \
  --original-analysis data-local/p08-development-analysis-v1/analysis.json \
  --candidate-analysis <actual-candidate-analysis.json> \
  --original-events data-local/p08-development-v1/evidence/events.jsonl \
  --candidate-events <actual-candidate-events.jsonl> \
  --output <fresh-request-directory>
```

The request stage re-runs the small metadata comparison contract and compares its substantive output fields. It binds each full event log to the source inventory in its existing analysis. It writes `request.json`, the exact selected PNG paths/hashes, and complete selected-attempt event chains. This is not a second complete simulator/image/reset audit. The comparator's and analyzer's actual receipts remain necessary.

Copy only the requested candidate files, preserving their paths relative to the candidate evidence root. Obtain an independent transfer inventory from the execution host. Then use the existing bundled Python with Pillow:

```sh
python3 scripts/prepare_paired_video.py render \
  --request <request-directory>/request.json \
  --original-evidence-root data-local/p08-development-v1/evidence \
  --candidate-evidence-root <copied-candidate-evidence-root> \
  --font /System/Library/Fonts/Menlo.ttc \
  --output <fresh-figure-directory>
```

Before decoding any pixels, the renderer rechecks all bound metadata/event bytes and independently re-derives the request selection. Changed requests, source files or renderer source are rejected. It then verifies selected PNG hashes. It creates 770×440 technical figures: derived introduction/table/absence cards and original-left/candidate-right front-camera pairs. Camera content is resized with preserved aspect ratio; no scene retouching occurs. The population receipt preserves both original file hashes, source dimensions, panel rectangles, exact observation IDs, state timestamps and own-arm host elapsed times. Host elapsed time includes that arm's reset/setup interval after its actual episode-start event. It is not camera elapsed time or synchronized flight time. Actual camera timestamps are retained from the linked capture and unique matching FrontCamera Scene request/response record. Missing times stay unavailable; the composed pair has no single camera timestamp and never substitutes state or host timestamps.

`video.json` supplies events to the existing release builder. The 5-row table pages each hold for 10 seconds; paired images hold for 6 seconds. Captions identify derived tables and index alignment. The population includes all trial/attempt accounting even though only a bounded subset of images is shown. Keep actual requested/applied controller actions in their event chains; the composite figure is not itself an action record.

Rendering does not finalize the phase artifact. Review every actual encoded static segment, verify source/panel mapping and readability, run the full-frame/timing checks, then provide a truthful named static-segment review to the existing builder. Do not claim continuous playback or publish the private provenance bundle automatically. Every output path must be fresh; failed or superseded drafts remain distinct.

The supported `table`, `clip_selection` and `mapping` fields are pinned by canonical JSON digest `ff0d8610683498f25f822ca8010a4ff85e60a3152ae2995ec03ba5aa091b84e9`; see [the supported rule](../../configs/video/paired-static-rule-v1.json). Editing those fields is rejected rather than silently applying another selection. Requests also bind the imported comparison and causal-check source files. The helper supports a separately frozen P14 confirmation rule with the same presentation semantics; the comparator still enforces fresh post-freeze execution for both holdout arms.
