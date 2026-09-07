# Simulation results

The fixed candidate gains one SR success in each cohort, with regressions in both and lower holdout OSR. All planned pairs are reported. [Method and interpretation](technical-report.md).

![SR and OSR with exact denominators](../assets/figures/simulation-sft-v1/outcome-rates.svg)

| Cohort | Original SR | Candidate SR | SR difference | Original OSR | Candidate OSR | OSR difference |
|---|---:|---:|---:|---:|---:|---:|
| Development, 20 pairs | 6/20 | 7/20 | +5 percentage points | 7/20 | 9/20 | +10 percentage points |
| Holdout, 10 pairs | 3/10 | 4/10 | +10 percentage points | 6/10 | 5/10 | −10 percentage points |

The original development results are reused from the frozen baseline. Both holdout arms are fresh. The same final candidate is used throughout; no selection is based on these results. Counts are descriptive, with no significance test or repeat-run uncertainty estimate.

| Cohort / metric | Both fail | Both succeed | Candidate regressions | Candidate gains |
|---|---:|---:|---:|---:|
| Development SR | 11 | 4 | 2 | 3 |
| Development OSR | 9 | 5 | 2 | 4 |
| Holdout SR | 5 | 2 | 1 | 2 |
| Holdout OSR | 2 | 3 | 3 | 2 |

![All paired transitions](../assets/figures/simulation-sft-v1/paired-transitions.svg)

## Episode and trace accounting

| Cohort / arm | Scored attempts | Accepted resets | Completed actions | Recorded observations | Any sampled endpoint contact | Upstream collision flag |
|---|---:|---:|---:|---:|---:|---:|
| Development original | 20 | 20 | 577 | 597 | 9 | 13 |
| Development candidate | 20 | 20 | 557 | 577 | 6 | 13 |
| Holdout original | 10 | 10 | 278 | 288 | 5 | 7 |
| Holdout candidate | 10 | 10 | 253 | 263 | 2 | 5 |

These are 60 unique recorded attempts across 30 paired mission identities; the twenty reused original development attempts are counted once. All have valid navigation and reset evidence. The separate failed holdout infrastructure launch is retained as zero navigation attempts. There are no extra, invalid or missing scored pairs.

Upstream collision flags include heuristics, while contact is a sampled/latching endpoint signal. These columns are not interchangeable and cannot establish collision-free paths. Action totals depend on the trajectory and termination; fewer actions do not by themselves establish efficiency.

## Measured host timing

| Cohort / arm | Whole command (s) | Generation intervals | Mean generation interval (s) | Median generation interval (s) |
|---|---:|---:|---:|---:|
| Development original | 846.930 | 577 | 0.444322 | 0.439276 |
| Development candidate | 820.384 | 557 | 0.447779 | 0.444340 |
| Holdout original | 449.236 | 278 | 0.454584 | 0.448071 |
| Holdout candidate | 410.418 | 253 | 0.450806 | 0.442710 |

Whole-command duration includes startup, execution and shutdown. Generation measures the recorded host call-return interval; it is not an isolated measurement of model-compute time. Different action counts, trajectories and termination points prevent interpreting total command times as a policy speedup. [Full numeric timing scopes](../../experiments/simulation-sft-v1/results/timing.json).

## Training observations

All 25 updates used different reviewed rows; the fixed row-0 check is a training example exposed at update 11. Its teacher-forced loss changed from `0.48068147897720337` to `0.04631422460079193`, and remained identical after reload. All 454 intended tensors changed. There is no held-out loss series.

![Training-step losses and fixed-row reload](../assets/figures/simulation-sft-v1/training-fit.svg)

## Downloadable numeric record

- [Episode rows](../../experiments/simulation-sft-v1/results/episodes.csv): all 60 outcomes, distances, contact flags and trace counts.
- [Paired rows](../../experiments/simulation-sft-v1/results/paired.csv): all 30 paired SR/OSR outcomes in declared mission order.
- [Training steps](../../experiments/simulation-sft-v1/results/training-steps.csv): all 25 row exposures, losses, gradients and recorded step times.
- [Aggregate data](../../experiments/simulation-sft-v1/results/aggregate.json), [training summary](../../experiments/simulation-sft-v1/results/training-summary.json), [source hash catalog](../../experiments/simulation-sft-v1/source-catalog.json).
- [Figure provenance](../assets/figures/simulation-sft-v1/figure-provenance.json): exact inputs, renderer, versions and SVG/PNG/PDF hashes.

Public tables are selected-field transcriptions checked against sealed source bytes. They permit numeric reanalysis and figure reproduction. Full raw-trace verification requires retained private artifacts; it is not implied by the public checksum catalog.

The seven study recordings are published in [Simulation training and evaluation v2](https://github.com/laxman-kc/UAV-VLA-Lab/releases/tag/simulation-training-evaluation-v2). [Exact artifact URLs and hashes](../../experiments/simulation-sft-v1/artifacts.json) distinguish the public clips from retained full traces. The recordings use editorial holds and selected observations, not continuous or synchronized flight.
