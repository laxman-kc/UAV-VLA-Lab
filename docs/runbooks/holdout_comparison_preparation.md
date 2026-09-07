# Prepare the fixed P14 holdout confirmation

`scripts/prepare_holdout_comparison.py` creates two fresh navigation plans and a paired plan only after the actual P13 comparison and its complete generated report exist. It copies both P13 checkpoint contracts byte-for-byte and enforces the P14 rule frozen in P13: use the same final P12 candidate regardless of the development result. It makes no checkpoint selection or usefulness decision.

This is metadata preparation. The helper does not connect to a host, open weights or image files, read a holdout outcome, start an evaluator, or generate an analysis result. Do not invoke it for the real experiment until P13 has actually been reported to the user. Synthetic tests use temporary fixture files only.

## Inputs and chronology

Use the completed bundle from [P13 preparation](development_comparison_preparation.md), its actual `comparison.json`, and the adjacent unedited comparator-generated `REPORT.md`. The request pins all three by SHA256. The helper checks the report content against the exact comparator source version and matches the result's plan, navigation and checkpoint hashes to the supplied P13 bundle. Both passing and unfavorable P13 scores leave the P14 checkpoint unchanged; missing or invalid P13 trials are not converted into failures or used to select a model here.

`p13_reported_at_utc` records when the result was actually reported. It must follow comparison generation and precede helper execution. The accompanying delivery declaration is supplied by the caller; it is not independent proof of message delivery or trusted timestamping.

The P13 bundle must retain its relative metadata references, including `metadata/training_dataset_manifest.json`. Its digest must equal the candidate contract's training-manifest digest. The complete frozen train/development/holdout/demo/unassigned memberships must be disjoint, and every candidate training row must remain in train.

The holdout selection must come from `prepare_evaluation_batch.py --group holdout`. Supply its unchanged selection manifest and `episodes.json`; this helper checks the full ten-mission group, frozen order, both byte hashes, canonical row hashes, loader identities, original-row ledger and original metadata gates. It does not reopen the full source evaluation list, raw mission metadata or pixels. All original selected frame rows remain in the batch, while each unique mission receives exactly one planned trial in each arm.

## Request shape

The following describes input fields only. The placeholder hashes/times are not execution evidence and must not be used to freeze a real plan.

```json
{
  "schema_version": "vla.holdout-comparison-preparation.v1",
  "p13_paired_plan": {"path": "p13/paired-plan.json", "sha256": "ACTUAL_SHA256"},
  "p13_comparison_result": {"path": "p13-comparison/comparison.json", "sha256": "ACTUAL_SHA256"},
  "p13_report": {"path": "p13-comparison/REPORT.md", "sha256": "ACTUAL_SHA256"},
  "holdout_selection": {"path": "holdout-selection/selection_manifest.json", "sha256": "ACTUAL_SHA256"},
  "holdout_episode_rows": {"path": "holdout-selection/episodes.json", "sha256": "ACTUAL_SHA256"},
  "p13_reported_at_utc": "ACTUAL_TIME_WITH_TIMEZONE",
  "p13_reported_before_p14": true,
  "p13_result_used_for_selection": false,
  "automatic_checkpoint_selection": false,
  "holdout_used_for_training_or_selection": false,
  "fresh_empty_remote_evidence_directories": true,
  "plan_id": "p14-paired-holdout-v1",
  "wall_limit_seconds": 14400,
  "arms": {
    "original": {
      "plan_id": "p14-original-navigation-v1",
      "trial_prefix": "p14-original-trial",
      "session_id": "p14-original-session-v1",
      "evidence_dir": "/remote/new-original/evidence",
      "supervisor_report": "/remote/new-original/command/report.json",
      "session_report": "/remote/new-original/report.json",
      "comparison_report_path": "/local/future-original/report.json",
      "analysis_source_path": "/remote/new-original/report.json"
    },
    "candidate": {
      "plan_id": "p14-candidate-navigation-v1",
      "trial_prefix": "p14-candidate-trial",
      "session_id": "p14-candidate-session-v1",
      "evidence_dir": "/remote/new-candidate/evidence",
      "supervisor_report": "/remote/new-candidate/command/report.json",
      "session_report": "/remote/new-candidate/report.json",
      "comparison_report_path": "/local/future-candidate/report.json",
      "analysis_source_path": "/remote/new-candidate/report.json"
    }
  }
}
```

Resolve the request's input references relative to the request file. Future arm paths must be explicit canonical absolute paths, with unique identifiers and no overlap between evaluator evidence directories or prior P13 evidence. `comparison_report_path` is the future local copy read by the comparator; it must not exist when preparing. `analysis_source_path` is the exact remote session-report path that the future analyzer will record, and must equal `session_report`. The helper does not rewrite historical source paths or invent future receipt hashes/timestamps. Remote directory emptiness must be checked by the execution owner; the helper records that declaration without a connection.

The wall limit shown above is an example, not a measured duration. Choose and record the actual bounded session limit. It applies equally to both fresh arms. The entire P13 shared configuration—including task, observed protocol, reset helper hash, runtime ID and action budget—is preserved; the descriptive exact-test choice is inherited too. Model identities come only from the unchanged checkpoint contracts. Unknown request fields or configuration/checkpoint overrides are rejected.

## Prepare and execute separately

After recording the actual P13 report delivery:

```sh
python3 -B scripts/prepare_holdout_comparison.py \
  --request /path/to/actual-p14-request.json \
  --output /path/to/new-p14-metadata
```

The fresh output contains `paired-plan.json`, two navigation plans, both unchanged checkpoint contracts, copied runtime/split/analyzer/training metadata, the exact P13 comparison/report, the request, source snapshots, `readiness.json` and `checksums.json`. The plan declares ten paired missions and twenty fresh attempts, with `reuse_existing_analysis_sha256: null` for both arms. It does not include a P14 result. An error may leave an incomplete output directory; preserve it and use a new versioned path after correcting the cause.

Use the existing session lifecycle and recorded runtime without modifying their behavior. Both actual sessions must start after the paired plan's freeze time. Once both complete, run the unchanged [paired comparator](navigation_comparison.md) with their actual reset-aware analyses and local session-report copies. Its full validation remains deferred until those real receipts exist; preparation does not create synthetic substitutes.

```sh
python3 -B -m unittest discover -s tests -p test_holdout_comparison_preparation.py -v
```

The tests cover exact checkpoint copying, frozen mission ordering, complete membership, report chronology/content, training overlap, source mutation, fresh destinations and compatibility with the full comparator using explicitly synthetic completed-arm fixtures. They do not establish that any real holdout evaluation occurred. Output retains private input paths and requires a separate review before public export.
