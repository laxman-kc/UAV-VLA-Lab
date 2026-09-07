# Predeclared paired comparison: P13 and P14

`scripts/compare_navigation.py` compares two existing `vla.baseline-reset-analysis.v1` JSON outputs. It reads the declared small metadata sidecars, checks their hashes and re-derives trial selection from every recorded attempt. It does not run a policy, load a checkpoint, read raw events or inspect/render pixels. Only bounded `.json` inputs and the declared `analyze_baseline.py` source are read; each input is limited to 128 MiB.

The implementation is covered by synthetic contract and artifact-integrity tests. No candidate evaluation, paired experiment, holdout result or adaptation improvement was produced by implementing it. The existing P08 trial-accounting structure was also read successfully, without creating a comparison against invented candidate outcomes.

## Freeze the comparison before candidate evaluation

Create a new immutable paired-plan JSON before starting the candidate's simulation session. Both evaluation-plan documents and checkpoint contracts must already exist and be hash-pinned in it. The plan must list the entire frozen development group for P13, or the entire frozen holdout group for P14, in exactly the same mission order as both evaluation plans. Trial IDs may differ between arms; `(map_name, episode_id)` is the pairing key. Each arm must assign every trial to exactly one declared session.

The shared execution configuration includes every navigation configuration field except `checkpoint_id` and `model_path`. The tool compares all remaining fields, including task mode, event protocol, runtime identity, reset behavior/helper hash, recorded-runtime requirement and action budget. Both arms must use the exact same runtime receipt, its declared code inventory, the frozen split and the episode-row digest. The source split and runtime receipt must identify the same upstream code revision. Reset-helper and hook hashes must appear in each analysis's recorded source inventory.

The retry contract is exactly `first_valid_attempt` with **one observed attempt per trial**. Infrastructure failures do not permit an undeclared replacement. Additional attempts or unplanned missions reject the comparison contract. An invalid or unstarted planned trial remains in output with null outcomes and cannot contribute to a matched pair.

P08 reuse is opt-in. For an existing original development run, the paired plan must contain its exact completed analysis SHA-256 in `reuse_existing_analysis_sha256`. All protocol, source, ordered-mission and retry checks still apply; a matching model name alone is insufficient. The tool never locates or chooses a baseline automatically. A fresh original run uses null for that field. Candidate reuse is rejected. **P14 requires both arms to start after the paired plan freezes**, with the candidate already fixed; no historical holdout reuse or holdout-based candidate selection is permitted.

The example below is a schema guide only. Placeholder hashes and identifiers are deliberately not accepted as actual provenance. It is not a frozen experiment plan or permission/label attestation. Replace every placeholder using recorded metadata; do not manufacture dates or digests.

```json
{
  "schema_version": "vla.paired-navigation-plan.v1",
  "plan_id": "<new-plan-id>",
  "frozen_at_utc": "<actual-time-with-timezone>",
  "phase": "P13",
  "purpose": "development_comparison",
  "split_group": "development",
  "holdout_used_for_selection": false,
  "automatic_checkpoint_selection": false,
  "exact_discordant_test": false,
  "missions": [{"map_name": "<map>", "episode_id": "<episode>"}],
  "shared_contract": {
    "configuration": {
      "task_mode": "<exact-existing-task-mode>",
      "protocol": "<exact-event-protocol>",
      "runtime_id": "<same-recorded-runtime>",
      "require_recorded_runtime_id": true,
      "reset_protocol": "<same-reset-protocol>",
      "reset_helper_sha256": "<sha256>",
      "max_actions": 200
    },
    "retry_policy": {"selection": "first_valid_attempt", "max_attempts_per_trial": 1},
    "split": {"path": "metadata/frozen-split.json", "sha256": "<sha256>"},
    "runtime_receipt": {"path": "metadata/runtime.json", "sha256": "<sha256>"},
    "episode_rows_sha256": "<sha256>",
    "analyzer_source": {"path": "metadata/analyze_baseline.py", "sha256": "<sha256>"}
  },
  "arms": {
    "original": {
      "navigation_plan": {"path": "metadata/original-plan.json", "sha256": "<sha256>"},
      "checkpoint_contract": {"path": "metadata/original-checkpoint.json", "sha256": "<sha256>"},
      "reuse_existing_analysis_sha256": "<exact-existing-development-analysis-sha256-or-null>",
      "session_reports": [{
        "session_id": "<declared-original-session-id>",
        "path": "receipts/original-session.json",
        "analysis_source_path": "<exact-source-path-recorded-by-the-analysis>"
      }]
    },
    "candidate": {
      "navigation_plan": {"path": "metadata/candidate-plan.json", "sha256": "<sha256>"},
      "checkpoint_contract": {"path": "metadata/candidate-checkpoint.json", "sha256": "<sha256>"},
      "reuse_existing_analysis_sha256": null,
      "session_reports": [{
        "session_id": "<declared-candidate-session-id>",
        "path": "receipts/candidate-session.json",
        "analysis_source_path": "<exact-source-path-recorded-by-the-analysis>"
      }]
    }
  }
}
```

For P14 use `phase: P14`, `purpose: holdout_confirmation`, `split_group: holdout` and null reuse fields. The mission list must contain the full frozen group, not just the single schematic entry. Retain any additional existing configuration fields in the shared contract; removing an arm-specific controller or policy option to force equality is a protocol mismatch, not a valid comparison.

All paths in the paired plan resolve relative to that plan unless absolute. Session-report output paths are declared before execution but their future hashes are not invented. On comparison, each completed `vla.simulation-session.v1` report's actual bytes must match the exact `analysis_source_path` record in its arm's source inventory. The session start must follow its navigation-plan freeze; finish must precede the analysis generation time. Observed attempt start times must fall within that session. This works even when the copied receipt path differs from its recorded source path.

The paired plan itself and both actual analysis JSONs are hashed when read, and every input is checked again before output. Post-run analysis hashes are recorded as results; the future candidate-analysis digest is not predeclared. Hashes/timestamps are local provenance and ordering checks, not independent trusted timestamps or proof that a JSON was honestly produced by the declared analyzer. The comparator does not rerun the baseline analyzer or hash its full raw-data inventory again.

## Checkpoint contract

Each arm's metadata document uses `schema_version: vla.comparison-checkpoint.v1` with these required fields:

| Field | Contract |
|---|---|
| `frozen_at_utc` | Actual timestamp no later than the paired-plan freeze. |
| `checkpoint_id`, `model_path` | Must match the analyzed navigation configuration exactly. |
| `base_manifest_sha256` | Same frozen base identity in both arms. |
| `artifact_manifest_sha256` | Actual model/artifact inventory identity; must differ between arms. |
| `model_files` | Nonempty unique relative file paths, each with a positive integer `bytes` and SHA-256; copy actual recorded inventory values. |
| `holdout_used_for_training_or_selection` | Must be false. This is a declared provenance condition, not independently provable from results JSON. |
| `source_kind` | `released` for original, `trained` for candidate. |
| Candidate-only fields | `parent_checkpoint_id` matching original, `training_split: train`, `supervision_mode: reviewed-expert`, and actual `training_manifest_sha256`. |

This small contract references the real parent, dataset/training and model inventories; it does not turn unknown labels into expert truth. The P10-only `published-reference-mechanics` mode is explicitly rejected as a P13/P14 adapted candidate. No remote weights are opened or independently verified by this tool. Keep the original manifests available for the broader review.

## Run and interpret

```sh
python scripts/compare_navigation.py \
  --plan comparison/paired-plan.json \
  --original baseline/analysis.json \
  --candidate candidate/analysis.json \
  --output comparisons/new-comparison
```

The output must not exist. Contract violations return **1** without comparison output. Valid contracts with any unmatched, invalid or unstarted pairs produce the complete accounting and return **2**. Return **0** means every planned pair was valid; it never means the candidate is useful or approved.

`comparison.json` retains every planned trial, both complete attempt lists, exact input/source hashes, own-arm valid denominators, matched-pair success/OSR and the transition table. `trials.csv` contains one row per declared mission in frozen order; unavailable outcome cells are blank. `REPORT.md` explains the denominators and limits. `checksums.sha256` covers those three outputs.

For matched valid pairs only, binary outcomes produce four transitions: both fail, original-only success, candidate-only success, and both succeed. The paired mean difference is `(candidate successes − original successes) / matched valid pairs`. Original and candidate SR in this section use the same denominator. Own-arm SR is separately labeled and must not be directly subtracted when the valid sets differ. Zero matched pairs produce null rates, difference and p-value.

If predeclared, the optional descriptive exact value conditions on discordant pairs: with `g` candidate-only and `l` original-only successes, it is `min(1, 2 × sum(C(g+l, k), k=0..min(g,l)) / 2^(g+l))`. With valid pairs but zero discordances it is 1. It is not a causal test, a multiple-comparison correction or a guarantee of independent samples. Fixed small same-map groups, correlated behavior, missingness and unresolved overlap with prior model training limit interpretation. No threshold triggers checkpoint selection, training completion or a claim of improvement.

Upstream success remains navigation success, not physical touchdown. The tool retains raw endpoint-contact fields and upstream heuristic-collision flags without equating them. The output includes private source paths and detailed attempt records; publication requires a separate reviewed public subset.
