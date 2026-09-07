# About the trained model

The “After training” model is the released AeroVLA model with additional training on 25 published examples. It uses the OpenVLA base. Training updated its adapter—the trainable additions to the main model—and its image projector, which connects visual features to the language model. The main model stayed fixed.

This is a continuation of an existing model, not a newly pretrained model. The [identity record](../../experiments/simulation-sft-v1/configs/model-identities.json) names the exact original releases and saved files. The same final trained model was used in both comparisons.

## How it was trained

Each of the 25 examples was used once, giving 25 updates. Training started directly from the released adapter, not from the earlier one-update test. Evaluation used the final configured update, without choosing a model based on evaluation results.

The [training settings](../../experiments/simulation-sft-v1/configs/training.json) record the optimizer, learning rate, seed, numeric precision and other details. The [dataset note](dataset-card.md) explains where the examples came from and what their action labels mean.

All 454 intended parameter arrays changed. Saving and reloading preserved the adapter and image-projector parameters and matched the checked training example's output. The [training summary](../../experiments/simulation-sft-v1/results/training-summary.json) records exact values and file fingerprints. This check does not measure performance on unseen examples. The saved files also do not include the full optimizer and random-state information needed to resume interrupted training exactly.

## What it can support

The model is a research example for this specific simulated navigation task. Successful stops increased from 6/20 to 7/20 in development and from 3/10 to 4/10 in the final test. Final-test target-area visits decreased from 6/10 to 5/10. Both groups include regressions. [Results and score definitions](results.md).

The task supplies target-direction hints, uses one map and has a documented modified reset procedure. The evidence does not establish reliable real-world flight, general navigation improvement, or recovery from new failures. The training set has no positive stop examples.

## Availability and terms

[Training and comparison recordings](videos.md), code and numeric results are public. The trained parameter files remain private; the videos do not make those files downloadable.

Model and dataset terms are separate from the project's code license. OpenVLA retains Llama-2-derived obligations, and TravelUAV contains noncommercial data terms whose scope across hosted archives needs clarification. See [third-party terms](../../THIRD_PARTY_NOTICES.md) and the [artifact catalog](../../experiments/simulation-sft-v1/artifacts.json).
