# About the 25 training examples

The training set contains 25 unchanged examples from the publisher's [AerialVLA training data](https://huggingface.co/XuPeng23/AerialVLA/tree/196f2f3253b69df6e90ac10b6ae041c7b3a9569e), paired with TravelUAV images and recorded vehicle states. Each example comes from a different ModernCityMap training mission. The instructions and action labels were kept as published.

These 25 missions are separate from the project's 20 development and 10 final-test missions. The final test is called `holdout` in the files. This separation does not establish whether the released model saw these missions during its earlier training. [Membership and source identities](../../experiments/simulation-sft-v1/dataset/membership.csv).

## What the labels mean

An example teaches forward movement, vertical movement and turning. The label review checked the recorded change from state `i` to state `i+5`, expressed relative to the vehicle's starting orientation. The forward and downward components match the published movement labels; the turning component comes from the relative orientation. The [alignment rule](../runbooks/reference_alignment.md) gives the exact equations and the fixed numerical tolerance of `1e-9`.

Those are **five record increments, not five known seconds**. Their elapsed time is unavailable. Sideways movement and changes in pitch and roll are omitted. The simulator controller also rounds and executes actions differently from the recorded source motion. Matching these labels therefore does not reproduce the complete source path or guarantee obstacle avoidance.

None of the 25 examples is labeled as a stop. The set offers **no positive examples of when to issue `LAND`**.

## How the examples were checked

The first five examples helped establish the label interpretation. Twenty more were then selected under a declared source/file rule and checked using that interpretation. They were not chosen because the model succeeded on them or because their alignment error looked favorable.

Codex agents reviewed source images and alignment evidence; this is not human expert certification. These are existing demonstrations, not newly collected corrections to model failures. Each was used once in training. The [original review video](https://github.com/laxman-kc/UAV-VLA-Lab/releases/download/simulation-training-evaluation-v2/p09-reviewed-reference-examples.mp4) is retained with the supporting evidence.

## What is available

The public membership table and [source catalog](../../experiments/simulation-sft-v1/source-catalog.json) identify the examples. Selected images appear in the published recordings. Complete raw image/state files, original label rows and private review records are not included here.

Original assets retain their publisher's terms. TravelUAV includes a [CC BY-NC 4.0 data license](https://github.com/prince687028/TravelUAV/blob/5cc26e9a4a55b9c788e918f7c3bb2dc5076a85e6/Model/LLaMA-UAV/DATA_LICENSE), with archive-scope details still needing clarification. The project code license does not replace those terms. [Artifact availability](../../experiments/simulation-sft-v1/artifacts.json).
