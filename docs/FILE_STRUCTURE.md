# Repository contents

UAV-VLA-Lab is one research project. The code, recorded experiment, report, figures and videos describe the same simulation-SFT study.

```text
UAV-VLA-Lab/
  README.md                         # Research question, main results and links
  src/uav_vla_lab/                   # Reusable experiment and evidence code
  scripts/                          # Recorded workflow implementations and helpers
  tests/                            # Data, execution and evidence contract checks
  configs/                          # Reusable asset, split and reporting settings
  experiments/simulation-sft-v1/
    configs/                        # Executed protocol, training settings, model identities
    dataset/membership.csv          # 25 training mission/source-row identities
    results/                        # 60 episodes, 30 pairs, 25 updates and exact totals
    source-catalog.json             # Hashes of retained source evidence
    artifacts.json                  # Available artifacts and their actual URLs
    video-publication-v2.json       # Verified seven-video publication receipt
  docs/
    research/                       # Technical report, results, model/data cards and videos
    assets/figures/simulation-sft-v1/ # SVG, PNG and PDF figures with provenance
    reports/                        # Selected historical evidence summaries
    runbooks/                       # Detailed method and reproduction procedures
    history/                        # Earlier evidence and publication context
  tools/                            # Numeric export, chart, report and video generation
  pyproject.toml                    # Project metadata and dependencies
  CITATION.cff                      # Software citation
  LICENSE, THIRD_PARTY_NOTICES.md   # Project and upstream terms
```

Start with the [technical report](research/technical-report.md), its [downloadable PDF](research/report.pdf), and the [recorded results](research/results.md). The [experiment directory](../experiments/simulation-sft-v1/README.md) contains the numeric data behind the figures. The [video record](research/videos.md) links the published recordings. MP4 recordings are distributed as release assets, with their exact URLs in that record.

`src/uav_vla_lab/` contains the reusable package. Some established workflows remain in `scripts/` and a hash-checked compatibility snapshot inside the package. Generated extractions retain explicit source identities; moving code into a package does not make a historical experiment a new execution.

Full observations, private reviews, model weights and complete sealed evidence bundles are retained separately. The public numeric tables and selected recordings do not provide those complete raw artifacts. Their availability is stated in the [artifact catalog](../experiments/simulation-sft-v1/artifacts.json).

Earlier P01–P14 labels identify supporting evidence from this study. They are not separate projects. Archived publication manifests describe their recorded snapshot; see the [history index](history/index.md) before interpreting their hashes or review status as current.
