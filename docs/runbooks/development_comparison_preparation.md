# Prepare P13 from a completed P12 candidate

`scripts/prepare_development_comparison.py` creates a new P13 metadata bundle only after the actual reviewed-expert P12 run has completed and its final checkpoint has passed reload checks. It reads bounded JSON and declared Python source. It never opens model weights, raw events or images, starts simulation, chooses a checkpoint, or writes evaluation results.

The current cycle uses the **same fixed final P12 candidate regardless of P13 outcome**. P13 may show improvement, no change or regression. Report that result before freezing P14. P14 then tests the unchanged candidate against the released original under a separate holdout plan, with both arms newly executed after that plan freezes. There is no best-of selection, model switch or promise of improvement. This is the fixed-candidate rule recorded in the [current public scope](../research/technical-report.md); the helper also binds it to the actual candidate contract hash in `paired-plan.json` before P13.

## Inputs and invocation

The caller supplies actual P12 `checkpoint-manifest.json` and completed `report.json`, the exact reviewed training `dataset_manifest.json`, and the released parent manifest used by that run. P10 mechanics receipts, validate-only runs, partial runs, failed reloads and unreviewed datasets are rejected. The helper checks recorded adapter/projector preservation, positive completed final-step budget, parent identity, dataset bytes and frozen train membership. It does not independently reread remote weight bytes or prove that supplied metadata was produced by its declared code; retain the actual training and file-transfer evidence.

```sh
python3 scripts/prepare_development_comparison.py \
  --request /absolute/path/p13-preparation-request.json \
  --p12-checkpoint-manifest /absolute/path/actual-p12/checkpoint-manifest.json \
  --p12-report /absolute/path/actual-p12/report.json \
  --training-dataset-manifest /absolute/path/actual-p11/dataset_manifest.json \
  --released-parent-manifest /absolute/path/released-parent.json \
  --output /absolute/path/new-p13-preparation
```

The output must not exist. All referenced metadata must be real, regular files. The request's relative references resolve against the request directory; absolute references are supported. Each `SHA256_OF_...` below is a schematic placeholder that must be replaced with the actual digest. It is not an executable or frozen experiment configuration.

```json
{
  "schema_version": "vla.development-comparison-preparation.v1",
  "plan_id": "p13-development-comparison-v1",
  "candidate_plan_id": "p13-candidate-navigation-v1",
  "candidate_trial_prefix": "p13-candidate",
  "holdout_used_for_training_or_selection": false,
  "automatic_checkpoint_selection": false,
  "exact_discordant_test": true,
  "original_navigation_plan": {"path": "/actual/p08-plan.json", "sha256": "SHA256_OF_PLAN"},
  "original_analysis": {"path": "/actual/p08-analysis.json", "sha256": "SHA256_OF_ANALYSIS"},
  "frozen_split": {"path": "/actual/frozen-split.json", "sha256": "SHA256_OF_SPLIT"},
  "runtime_receipt": {"path": "/actual/runtime-receipt.json", "sha256": "SHA256_OF_RUNTIME"},
  "episode_selection": {"path": "/actual/selection_manifest.json", "sha256": "SHA256_OF_SELECTION"},
  "episode_rows": {"path": "/actual/episodes.json", "sha256": "SHA256_OF_EPISODES"},
  "analyzer_source": {"path": "/actual/analyze_baseline.py", "sha256": "SHA256_OF_ANALYZER_SOURCE"},
  "original_session_reports": [{
    "session_id": "p08-development-session-v1",
    "path": "/actual/copied-p08-session/report.json",
    "sha256": "SHA256_OF_SESSION_REPORT",
    "analysis_source_path": "/exact/path/recorded/in/analysis/inventory/report.json"
  }],
  "candidate_wall_limit_seconds": 3600,
  "candidate_session": {
    "session_id": "p13-candidate-session-v1",
    "evidence_dir": "/chosen/host/runs/p13-candidate-v1/evidence",
    "supervisor_report": "/chosen/host/runs/p13-candidate-session-v1/command/report.json",
    "session_report": "/chosen/host/runs/p13-candidate-session-v1/report.json",
    "comparison_report_path": "/chosen/local/future-session/report.json",
    "analysis_source_path": "/chosen/local/future-session/report.json"
  }
}
```

The wall bound and future destinations above are examples, not inferred deployment choices. Declare the intended values. `comparison_report_path` is the future receipt path that the comparator will read; `analysis_source_path` is the exact path string that its matching candidate analysis must record in `source_files`. They may differ when copied host metadata retains original paths. The original receipt has an actual digest now; the future receipt has none yet. Do not rewrite historical analysis paths to make copied files appear original. Use the explicit mapping.

## Exact P08 reuse and outputs

The original input is the reset-aware `vla.baseline-reset-analysis.v1` analysis, not the older navigation summary. Its actual plan, runtime, episode rows and split must agree by hash. The helper recomputes all trial/attempt accounting through the existing comparator, checks reset-session audit membership and session chronology, and requires the entire frozen development group. The original plan is copied byte-for-byte. Candidate planned mission order follows that original plan; observed upstream length-grouped execution order can differ. Pairing is by `(map_name, episode_id)` and all attempts remain accounted for.

Only `checkpoint_id` and `model_path` change in the shared execution configuration. The runtime receipt, controller/reset protocol and helper hashes, action budget, source split, ordered mission membership, episode rows and one-observed-attempt policy remain identical. The named future candidate session covers the full group. Its actual execution must start strictly after the new paired plan freezes; candidate reuse is prohibited.

The fresh output contains:

- `paired-plan.json`: actual freeze timestamp, exact original-analysis reuse hash, both checkpoint/navigation contracts, future session mapping and fixed P14 rule.
- `metadata/`: exact input bytes and source snapshots, released/base inventories derived from the actual parent receipt, candidate inventory derived from the actual P12 receipt, and the two checkpoint contracts. Recorded remote paths remain provenance.
- `readiness.json`: recomputed original accounting and explicit `metadata_prepared_evaluation_not_run` status. Full comparator validation is deferred until actual candidate analysis/session receipts exist.
- `checksums.json`: hashes of every other emitted file.

Keep the bundle immutable after it freezes. A bad input or changed protocol needs a newly named preparation; never patch the old plan after observing results. Preserve partial output if a write-time failure occurs. A metadata readiness pass is not a navigation result, independent trusted timestamp, proof of no prior holdout access, or confirmation that remote weights have remained unchanged.

After the actual candidate run, use the pinned analyzer under the same protocol, retain its source inventory and session receipt, then invoke [the comparison runbook](navigation_comparison.md) against `paired-plan.json` and both real analyses. Invalid/unstarted trials stay null. Report all valid-pair denominators and unmatched trials, alongside the original historical-reuse limitation. This helper neither reruns raw reset validation nor isolates causality or timing effects from the historical baseline.

## P14 follow-on, after P13 is reported

No P14 plan is created by this helper. Once P13 outcomes have been reported, retain the exact same candidate checkpoint contract bytes/hash bound by `predeclared_P14_rule` and the same final P12 artifact. Record the actual P13 comparison/report hash as provenance for the chronology; it must not become a selection rule.

Prepare the entire already frozen holdout group without changing its membership. Declare two new navigation plans and future sessions with matched runtime, reset/controller settings, retry cap and ordered missions. Create a new paired plan with `phase: P14`, `split_group: holdout`, `purpose: holdout_confirmation` and null reuse fields for both arms. Both sessions must start after that new paired freeze. The original P08 execution cannot serve as holdout evidence. Use the comparator's documented schema and retain the unchanged candidate contract hash; no candidate change may be justified by P13 or holdout outcomes in this fixed cycle.

A regression is a reportable engineering result. If a later development cycle changes the model after seeing holdout outcomes, those missions become development material for that later cycle; do not call them untouched confirmation for the revised model.

## Tests

```sh
python3 -m unittest discover -s tests -p test_development_comparison_preparation.py -v
python3 -m unittest discover -s tests -p test_navigation_comparison.py -v
```

These are explicitly synthetic metadata tests. They cover exact ordered-plan preservation despite differing observed order, immutable reuse binding, rejection of P10/incomplete/non-final training, reviewed train membership, saved-file path/identity checks, invalid baseline accounting/reset sessions, changed hashes, receipt chronology and explicit historical/future path mapping. They do not generate experimental evidence.
