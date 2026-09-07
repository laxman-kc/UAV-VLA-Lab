# UAV-VLA-Lab

**Understanding how a vision-language-action model navigates a simulated drone—and what changes after a small training run.**

[Results and charts](docs/research/results.md) · [Watch the comparisons](docs/research/videos.md) · [How the study was done](docs/research/technical-report.md) · [Experiment data](experiments/simulation-sft-v1/)

## What this project does

A vision-language-action model uses images and text to choose a movement. In this project, [AeroVLA](https://github.com/XuPeng23/AeroVLA) controls a drone in the [TravelUAV](https://github.com/prince687028/TravelUAV) simulator. It reads camera images and a direction prompt, predicts an action, and receives new images after the drone moves. This repeated observe–act cycle is called **closed-loop navigation**.

UAV-VLA-Lab brings the experiment into one place: the code, training records, before-and-after comparisons, charts, and selected videos. The aim is to understand what the model actually did, including missions with better and worse outcomes after training.

## The research question

**Can a small amount of training on published examples improve an existing drone-navigation model?**

The released AeroVLA model received **25 training updates using 25 published demonstration examples**. The original and trained versions were then compared on the same missions:

| Part of the study | What happened |
|---|---|
| Training | Each of the 25 examples was used once. |
| Development comparison | Both model versions were evaluated on 20 missions. The original model's earlier recorded results were reused. |
| Final comparison | Both versions ran on 10 separate missions, with new runs for each version. |

The trained version was fixed before either comparison; it was not replaced after seeing the scores. Each version had one attempt per mission. This produced **60 recorded runs across 30 comparison missions**.

In the charts, **before training** means the released, already pretrained model. **After training** means that model after the additional training described here. “Final test” is called “holdout” in the data files.

## Findings

![Navigation results before and after the additional training](docs/assets/figures/simulation-sft-v1/outcome-rates.png)

The chart shows two different outcomes:

- **Successful stop:** the benchmark accepted the model's stop near the target. This does not mean a physical landing.
- **Reached target area:** the model got near the target at a recorded action endpoint, or completed a successful stop. A run can earn this result and still fail later.

The target-area rule uses a 20-metre distance threshold. The [method note](docs/research/technical-report.md) explains the exact boundary and stop conditions.

| Comparison | Successful stops: before → after | Reached target area: before → after |
|---|---:|---:|
| Development — 20 missions | 6 → 7 | 7 → 9 |
| Final test — 10 missions | 3 → 4 | 6 → 5 |

**The result is mixed.** The trained model finished one more mission successfully in each comparison. But on the final test, it reached the target area on one fewer mission.

Looking at the same missions makes the trade-off clearer: three development missions failed before training and succeeded afterwards, while two changed in the opposite direction. On the final test, there were two improvements and one regression. [See the full comparison](docs/research/results.md).

## Watch what changed

Two short comparisons show one mission that improved and one that became worse. Labels show the recorded mission outcome; the images are selected stills from separate runs, not continuous or synchronized flight.

### Development comparison · 20 seconds

Across 20 missions, successful stops increased from **6 to 7**, with three improvements and two regressions.

https://github.com/user-attachments/assets/f95f5cc2-7a31-4e4b-84c8-57827091a7d0

### Final-test comparison · 20 seconds

Across 10 separate missions, successful stops increased from **3 to 4**, while target-area reach fell from **6 to 5**. The result is mixed.

https://github.com/user-attachments/assets/0d76712b-0403-4ffc-bc35-808975b1e683

[About the videos and original recordings](docs/research/videos.md).

## Why this is useful

For someone studying drone-navigation models, an overall score is only a starting point. This project lets you:

- **Find the trade-offs.** Check which missions improved and which became worse after training.
- **Connect training to evaluation.** Trace the examples and training updates to the exact model used in both comparisons.
- **Check the reported results.** Recalculate the charts from the published tables and inspect selected observations in the videos.
- **Build on a documented experiment.** Use the existing method and source code as a reference for a separately recorded follow-up study.

This is a small study on **one simulated map**. These results do not establish improvement on other maps or performance on physical drones. The benchmark also provides target-direction information; this is not navigation from an unrestricted natural-language instruction alone.

## Explore the research

| Resource | What it contains |
|---|---|
| [Results](docs/research/results.md) | Three charts with plain-language explanations. |
| [Method](docs/research/technical-report.md) | Training, comparison design, scoring, and limitations. |
| [Experiment data](experiments/simulation-sft-v1/README.md) | All 60 run results, 30 paired comparisons, and 25 training updates. |
| [Model notes](docs/research/model-card.md) · [Dataset notes](docs/research/dataset-card.md) | Where the model and examples came from, and what is unavailable. |
| [Source code](src/uav_vla_lab/) · [File structure](docs/FILE_STRUCTURE.md) | The shared implementation and where to find each part. |

The policy method comes from AeroVLA, built on [OpenVLA](https://github.com/openvla/openvla); TravelUAV supplies the simulation and data. This project's contribution is the combined experiment and its inspectable results.

Project-owned code is [Apache-2.0](LICENSE). Upstream code, models, and datasets retain their own [terms](THIRD_PARTY_NOTICES.md). See [CITATION.cff](CITATION.cff) to cite the project and [CONTRIBUTING.md](CONTRIBUTING.md) to contribute.
