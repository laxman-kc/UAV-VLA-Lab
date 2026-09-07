# Installed research workflows

Install the built wheel or `pip install .` before using these commands. They work
from an unrelated directory: no working checkout, inherited `PYTHONPATH`, model
download or GPU import is required for help and contract-only commands.

| Installed command | Implementation and purpose |
|---|---|
| `uav-vla assets` | Preserved asset verify/validate/convert engine; bundled pinned map/split defaults |
| `uav-vla dataset snapshot` | Native acquisition requiring explicit immutable revisions, sizes and SHA256 values |
| `uav-vla dataset episode` / `batch` | Preserved official metadata selectors |
| `uav-vla dataset reference` / `extension` / `alignment` / `reviewed` | Preserved source, alignment and reviewed-dataset preparation contracts |
| `uav-vla integration patch` / `probe` / `offline` | Pinned upstream instrumentation, actual simulator probes and offline inference |
| `uav-vla simulate` | Preserved owned scene-manager/workload lifecycle |
| `uav-vla train` | Native training runner and standard-library reviewed-dataset validator |
| `uav-vla evaluate summarize` / `baseline` | Native navigation accounting/reset audit; explicit role/split report context |
| `uav-vla compare` | Preserved paired numerical comparison and chronology checks |
| `uav-vla workflow development` / `holdout` / `amend-unstarted` | Preserved predeclaration and narrow no-start-amendment contracts |
| `uav-vla report build` / `paired` / `amended-paired` | Preserved release and static evidence-video engines |

Each command accepts its existing arguments directly, for example
`uav-vla train --help` and `uav-vla simulate --help`. The `--` separator inside
`simulate` still separates the owned workload argv; the CLI preserves it.
The [fresh-host recipe](fresh_host.md) covers the separate GPU environment.

This is an incremental modular extraction, with an explicit compatibility
engine. Native dataset validation lives in `uav_vla_lab.datasets.reviewed`;
the continued-adapter loop in `training.runner`; navigation/reset analysis in
`evaluation.navigation` and `evaluation.analyze_baseline`; context in
`evaluation.context`; runtime selection/acquisition have separate modules.
Training imports PyTorch/PEFT only when execution reaches the GPU operation.
`--validate-only` still validates real dataset, parent and upstream manifests.
It does not generate missing labels or approvals.

The retained Python scripts are the migration source of truth. Run
`python scripts/sync_workflow_resources.py --check` to verify the generated native
engines and byte-identical compatibility copies; run it without `--check` only to
regenerate reviewed extraction rules. The snapshot manifest refuses changes to
historical source identities. Historical shell copies are archival only; installed
runtime commands use the portable shell resources. Any scientific behavior change
needs a separately versioned integration and new experiment declaration.

The native analyzer keeps every numerical/reset/accounting function unchanged.
Its actual source is `evaluation/analyze_baseline.py`, with a **new source hash**.
It embeds and checks the hashes of `navigation.py` and `context.py` before
analysis, then records all three files in `implementation` and `source_files`.
Use that actual analyzer file and hash in new paired plans; its contractual
basename remains compatible with the existing plan preparers. A changed native
dependency changes the generated analyzer hash. Never substitute the historical
script's hash or silently mix native and historical producers in a frozen plan.

```sh
uav-vla evaluate baseline --role candidate --split holdout \
  --plan /actual/frozen/candidate-navigation.json \
  --navigation-summary /actual/summary/summary.json \
  --runtime-receipt /actual/runtime.json \
  --reset-helper /actual/AeroVLA/_vla_lab_reset.py \
  --runtime-hook /actual/AeroVLA/_vla_lab_runtime.py \
  --output /actual/new/candidate-analysis
```

Role/split values are display declarations unless the frozen plan contains them;
contradictions are rejected. They do not establish checkpoint provenance or
membership. Full-group membership and paired identity remain the comparator's
job. The native report no longer assumes development, an original released model,
or a paired-video editorial rule. `video-selection.json` remains a descriptive
single-arm suggestion; use the separately frozen paired selection plan for media.

For an exact historical command use `uav-vla legacy run SCRIPT_BASENAME ...`.
This route intentionally retains old report wording and old command behavior.
In particular, the historical model downloader can resolve a current revision;
new acquisition should use the explicit pinned snapshot command above.
Compatibility checksums are source identity checks, not execution attestation.

The completed cycle's sealed evidence, source hashes, checkpoint identities,
reset tolerance, source-label semantics and result denominators are not rewritten
by this refactor. CPU tests establish package and contract behavior; they do not
revalidate GPU inference, graphics, simulator timing, training or navigation.
