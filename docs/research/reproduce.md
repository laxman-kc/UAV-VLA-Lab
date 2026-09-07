# Check the results and redraw the figures

Start with the [results](results.md) and [comparison videos](videos.md). The [experiment folder](../../experiments/simulation-sft-v1/README.md) contains the public numbers behind them.

From the repository root, check the tables:

```bash
python3 tools/render_research_figures.py --check
```

This checks 60 recorded attempts, 30 mission pairs and 25 training updates. It verifies the reported totals, separate mission groups, paired outcomes and training-example order. It reads the public tables without writing files.

To redraw the three figures:

```bash
python3 tools/render_research_figures.py
```

The tool writes SVG, PNG and PDF chart files under `docs/assets/figures/simulation-sft-v1/`. The [figure record](../assets/figures/simulation-sft-v1/figure-provenance.json) lists the input files, drawing code, library versions and output hashes. A hash is a file fingerprint used to detect changed bytes. Different fonts or library versions can change image bytes without changing the plotted numbers.

## What these checks establish

They reproduce the public arithmetic and figures. They do not rerun a flight, replay the full raw observations, or prove that a trained model is generally better.

For the method, read the [study note](technical-report.md), [training settings](../../experiments/simulation-sft-v1/configs/training.json), [model identities](../../experiments/simulation-sft-v1/configs/model-identities.json), and [evaluation protocol](../../experiments/simulation-sft-v1/configs/protocol.json). Repeating an experiment with changed code, data or model files needs a separate result record.

The public tables were exported from retained source evidence. `tools/export_simulation_study.py` can repeat that export for researchers with those original bundles. The [source catalog](../../experiments/simulation-sft-v1/source-catalog.json) identifies them, but their hashes do not provide access to files that are not public.

## Recordings and downloads

The [video guide](videos.md) links the published observations, demonstration reviews, training records and comparisons. The [artifact catalog](../../experiments/simulation-sft-v1/artifacts.json) separates available downloads from private raw evidence and model files.

Videos show selected saved observations or excerpts, held on screen for readability. Paired views match selected decision indices and use each run's own timing; they are not continuous or synchronized flights.
