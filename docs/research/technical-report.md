# How the study was done

The study tested whether a small amount of extra training on published demonstrations would help an existing model navigate in simulation. The result was mixed: successful stops increased by one mission in each comparison, but fewer final-test missions reached the target area. [See the results](results.md) or [watch the comparisons](videos.md).

## The task and training

The experiment used [AeroVLA](https://github.com/XuPeng23/AeroVLA), built on [OpenVLA](https://github.com/openvla/openvla), with [TravelUAV](https://github.com/prince687028/TravelUAV) data and simulation. Everything ran in one environment, ModernCityMap. The model received front/down camera views and directional hints calculated from the target position. It therefore had more information than images and a destination description alone.

Training used 25 unchanged published examples from 25 missions. Each example was used once, for 25 model updates. Training updated the released model's adapter and image projector while keeping the main model fixed. An adapter is a set of trainable additions to the model; the image projector connects visual features to the language model. The final saved model was chosen in advance, without selecting among several versions after seeing the results. [Training settings](../../experiments/simulation-sft-v1/configs/training.json).

Codex agents checked the source images and action-label alignment. These were existing demonstrations, not newly collected corrections to the model's mistakes. Their motion labels span five recorded index increments, with elapsed time unknown. None teaches the model to stop. [Dataset details](dataset-card.md).

## What the scores mean

**Successful stop (SR)** means the evaluator accepted the model's stop signal at a recorded distance of at most 20 metres from the target. The attempt must still be active, with no earlier premature-stop flag. `LAND` is the model's stop signal; this does not demonstrate physical touchdown.

**Reached the target area (OSR, upstream “oracle success”)** includes those successful stops, plus attempts where at least one reported action endpoint was strictly less than 20 metres from the target. That flag stays set even if the attempt later fails. Distances are three-dimensional distances to the target point; the code checks returned action endpoints, not every moment along a flight.

These definitions follow the pinned upstream [stop check](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/src/vlnce_src/closeloop_util.py#L201-L215), [endpoint check](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/src/vlnce_src/env_uav.py#L446-L449), [20-metre threshold](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/utils/env_utils_uav.py#L26), and [metric counting](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/utils/metric.py#L170-L179).

## How the models were compared

Both model versions were evaluated on 20 development missions and 10 final-test missions. The data calls the final test `holdout`. All three mission groups are separate within this project; earlier exposure during the released model's training is unknown.

Each model had one recorded attempt per mission, capped at 200 actions. Development reused the recorded original baseline. Both final-test runs were fresh. The final-test plan was written after development results were known, but the already-fixed trained model was retained.

Simulator communication was repaired and the reset procedure changed after initial camera/state checks failed. All 60 scored attempts passed the recorded reset and event-order checks. This is an explicitly modified execution protocol. One failed startup launched no navigation and remains a separate infrastructure failure. [Protocol and source identities](../../experiments/simulation-sft-v1/configs/protocol.json).

## What this contributes

The useful output is a small, checkable case study: all 30 paired outcomes, training records, and videos showing gains and regressions. One map and one attempt per model leave repeatability and wider performance unresolved. The study does not establish that training caused a general improvement. [Model details](model-card.md) · [Public data and reproduction](reproduce.md).
