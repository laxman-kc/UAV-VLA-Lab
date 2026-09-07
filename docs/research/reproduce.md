# Reproduce the figures and check the results

The public [experiment record](../../experiments/simulation-sft-v1/README.md) contains the numeric data behind the report. Reanalysis checks these published tables; it does not replay the retained raw observations.

From the repository root:

```bash
python3 tools/render_research_figures.py --check
python3 tools/render_research_figures.py
```

The first command validates **60 episode rows, 30 paired rows, 25 optimizer steps, 25 train missions, 1,665 actions and 1,725 observations**. It checks mission separation, paired outcomes, training exposure order, metric denominators and source identities without writing files.

The second command regenerates SVG, PNG and PDF figures in `docs/assets/figures/simulation-sft-v1/`. It uses Matplotlib. The [figure provenance](../assets/figures/simulation-sft-v1/figure-provenance.json) records exact data hashes, renderer identity, output hashes and library versions. Changes in fonts or rendering libraries can change output bytes while preserving the plotted values. No smoothing, inferred error bars or significance tests are added.

## Method and source evidence

The [protocol](../../experiments/simulation-sft-v1/configs/protocol.json), [model identities](../../experiments/simulation-sft-v1/configs/model-identities.json) and [training settings](../../experiments/simulation-sft-v1/configs/training.json) record the completed experiment. Keep its fixed candidate, mission order, action limit, timed-reset convention and one-observed-attempt accounting explicit in any comparison.

`tools/export_simulation_study.py` produced the public tables from selected sealed sources. Researchers with the retained source bundles can repeat that export:

```bash
python3 tools/export_simulation_study.py --sealed-releases /path/to/retained/releases
```

The exporter verifies selected files against sealed manifests, reconciles the recorded counts, and writes explicit numeric/identity fields. The [source catalog](../../experiments/simulation-sft-v1/source-catalog.json) lists their hashes and availability. It does not copy raw observations, private reviews or checkpoint bytes, and those hashes do not provide access to absent files.

A new simulation or training run needs its own recorded inputs and source identity. The [evaluation](../runbooks/evaluation.md), [training](../runbooks/training.md) and [comparison](../runbooks/navigation_comparison.md) runbooks document the method. Changed code or substituted data/checkpoints must not be presented as an exact replay of this study.

## Reports and recordings

- [Technical report](technical-report.md), [results](results.md), [model card](model-card.md), [dataset card](dataset-card.md).
- [Artifact catalog](../../experiments/simulation-sft-v1/artifacts.json) with exact available URLs and retained-private items.
- Eight earlier diagnostic recordings in [Simulation MVP evidence v1](https://github.com/laxman-kc/UAV-VLA-Lab/releases/tag/simulation-mvp-evidence-v1).
- Seven study recordings in [Simulation training and evaluation v2](https://github.com/laxman-kc/UAV-VLA-Lab/releases/tag/simulation-training-evaluation-v2), with names, sizes and SHA256 digests checked in the [publication receipt](../../experiments/simulation-sft-v1/video-publication-v2.json).

Recordings use saved observations, source excerpts and figures held for editorial durations. Paired views align selected decision indices and separate terminal images; they are not synchronized flights. The overview explains existing results and contains no new simulator footage or experimental measurements.
