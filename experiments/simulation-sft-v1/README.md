# simulation-sft-v1

One recorded ModernCityMap evaluation/adaptation study within UAV-VLA-Lab. The original development results are reused; candidate development and both holdout arms are recorded separately. One fixed candidate, 25 unchanged reviewed publisher examples, 25 updates, 30 paired mission identities and 60 scored attempts. Results are mixed. [Technical report](../../docs/research/technical-report.md).

| File | Content |
|---|---|
| `results/episodes.csv` | All 60 scored attempts: mission/arm, SR/OSR, distance, termination, sampled contact, accepted reset, action/observation counts and host generation intervals |
| `results/paired.csv` | All 30 paired outcomes in declared mission order |
| `results/aggregate.json` | Per-arm totals and all SR/OSR paired transitions |
| `results/timing.json` | Recorded aggregate host intervals with their scope |
| `results/training-steps.csv` | All 25 actual updates and sample exposures |
| `results/training-summary.json` | Fixed-row before/after/reload, trainable counts and checkpoint-file hashes |
| `dataset/membership.csv` | Training mission/source row identities and hashes; no copied labels/instructions/pixels |
| `configs/` | Historical effective protocol, hyperparameters and model identities; no live host paths |
| `source-catalog.json` | Exact selected sealed-source hashes; full source bytes remain private |
| `artifacts.json` | Explicit public, included and unavailable artifact states |
| `video-publication-v2.json` | Verified published names, sizes, hashes and URLs for seven study recordings |

`oracle_success` represents the recorded upstream OSR predicate, including ordinary success. `upstream_collision_flag` is not the same signal as endpoint contact. `terminal_loop_index` is retained as an upstream index; `actions_completed` is the independently counted number of linked completion events. Host generation intervals are neither pure CUDA latency nor simulated elapsed seconds. Missing values would mean unavailable, not zero; this cohort has no missing valid pairs.

To recompute public counts and check disjoint membership, run `python3 tools/render_research_figures.py --check` from the repository root. To regenerate SVG/PNG/PDF charts with Matplotlib, run the same tool without `--check`. [Reproduction guide](../../docs/research/reproduce.md).

The source export uses strict selected-field transcriptions and reconciles all counts against the sealed summaries. It preserves the failed holdout startup as zero navigation attempts, without adding it to scored outcomes. It does not republish raw images, logs, private reviews or weights; hashes do not imply public access to those artifacts. No significance test or aggregate across the two different cohorts is reported.
