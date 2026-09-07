# Fixed simulation-SFT candidate

**Artifact identity:** `p12-fixed-final-c8fdf4cc533e7360` · **Study:** `simulation-sft-v1` · **Weights:** retained privately, not currently offered as a public download.

The artifact is a continued released AeroVLA LoRA adapter with its saved projector. It uses the OpenVLA base and the existing three-component UAV action representation. It is not a newly pretrained foundation model. [Exact identities](../../experiments/simulation-sft-v1/configs/model-identities.json).

| Item | Identity |
|---|---|
| Base | `openvla/openvla-7b@47a0ec7fc4ec123775a391911046cf33cf9ed83f` |
| Released adapter | `XuPeng23/AerialVLA@196f2f3253b69df6e90ac10b6ae041c7b3a9569e`, `aero_vla` subfolder |
| Candidate manifest SHA256 | `c8fdf4cc533e7360282f38cf6b5cc8e3937e005606494b4ba71483155c0619be` |
| Adapter weights SHA256 | `cce1d20f9c7e5791ec1815a19cd39a4ff7170e31903fa10a415e13221ba3db85` |
| Adapter weights size | 925,241,648 bytes |

The [training summary](../../experiments/simulation-sft-v1/results/training-summary.json) lists all eleven checkpoint-file identities using filenames and hashes, without the historical host paths. The same candidate contract appears in both comparisons.

## Training and validation

Training continued the released parent directly on 25 unchanged audited publisher examples from 25 train missions. Seed `100`, 25 updates, batch/accumulation `1/1`, AdamW learning rate `2e-5`, weight decay `0.03`, clipping `1.0`, no scheduler, one exposure per row, final-step selection only. Base weights were frozen BF16; trainable LoRA/projector parameters and state were FP32 under BF16 autocast with gradient checkpointing. [Effective settings](../../experiments/simulation-sft-v1/configs/training.json), [data card](dataset-card.md).

All 454 intended tensors changed. Save/unload/reload preserved adapter/projector hashes and matched teacher-forced fixed-row loss/logits; recorded maximum logit error was zero. The fixed row was itself trained. This is a checkpoint-integrity check, not free-running action accuracy or navigation validation. No optimizer/RNG resume state is included.

## Evaluation and intended use

The intended use is inspecting and repeating this bounded simulated navigation experiment with the declared upstream assets and protocol. Development SR is 7/20 versus 6/20 original; holdout SR is 4/10 versus 3/10. Holdout OSR is 5/10 versus 6/10. Both cohorts contain candidate regressions. [Complete results](results.md).

The study uses one map, target-bearing assistance, a named modified reset protocol and small fixed cohorts. Prior-training overlap is unresolved. It does not establish general navigation improvement, instruction-only autonomy, learned recovery, robust stop behavior, exact source-path execution or physical-UAV touchdown. Every training example has false stop flags; there are no positive LAND targets.

## Licensing and availability

Project-owned code and this research workflow use the project's code license. Weight rights are separate: the AerialVLA adapter card declares Apache 2.0, while OpenVLA explicitly retains Llama-2-derived model obligations. TravelUAV also has noncommercial data/weight license files with unresolved archive-scope details. No Apache-only weight license or unrestricted checkpoint release is asserted here. [AerialVLA card](https://huggingface.co/XuPeng23/AerialVLA), [OpenVLA licensing](https://github.com/openvla/openvla#pretrained-vlas), [TravelUAV data license](https://github.com/prince687028/TravelUAV/blob/5cc26e9a4a55b9c788e918f7c3bb2dc5076a85e6/Model/LLaMA-UAV/DATA_LICENSE).

The candidate weights remain retained privately. A Hugging Face publication can be added when its applicable terms and exact payload are resolved; there is no placeholder download link. The current public contribution is the code, method, numeric results, identities and reproduction recipe.

Recorded training and paired-comparison clips are available in [Simulation training and evaluation v2](https://github.com/laxman-kc/UAV-VLA-Lab/releases/tag/simulation-training-evaluation-v2). These are selected evidence presentations with editorial holds; publication of the clips does not publish the checkpoint.
