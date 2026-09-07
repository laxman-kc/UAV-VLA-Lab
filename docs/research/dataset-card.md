# Audited publisher-demonstration subset

**Study:** `simulation-sft-v1` · **Size:** 25 rows from 25 ModernCityMap train missions · **Public content:** membership/identity metadata, not the raw dataset or private review records.

The source is the publisher's `aerovla_train_dataset.json` at [AerialVLA revision `196f2f3`](https://huggingface.co/XuPeng23/AerialVLA/tree/196f2f3253b69df6e90ac10b6ae041c7b3a9569e), paired with TravelUAV images and state records. Labels and instructions were retained unchanged. The first five examples were used to discover the source alignment; twenty subsequent examples were selected under a separate declared source/schema/file rule and reviewed under the fixed interpretation. No model-outcome or alignment-residual selection was used for those additions.

The [membership table](../../experiments/simulation-sft-v1/dataset/membership.csv) gives the training row index, source sample/mission identity, original publisher row index and canonical row hash. All 25 training missions are disjoint from the 20 development and 10 holdout mission identities in this project. That separation does not establish the released model's complete prior-training history.

## Label interpretation

For a current record `i`, the source-forward and source-down labels correspond to the x/z components of `R(q_i)^−1 (p_(i+5) − p_i)`. Yaw corresponds to the first ZYX Euler component of `R(q_i)^−1 R(q_(i+5))`. The fixed audit tolerance is `1e-9`; six contiguous numeric raw records are checked for each example. Current/future front/down images and state hashes are retained privately.

The horizon is **five recorded index increments**, with physical elapsed seconds unknown. Image/state acquisition simultaneity is not established. Source-body y translation and relative pitch/roll are discarded. The actual controller's rotation-first translation, quantization and large-yaw behavior can differ from the source displacement. Label alignment does not establish exact controller replay, obstacle avoidance or an optimal policy.

Every example has `is_last_step=false` and `is_penultimate=false`. There are **zero positive LAND/stop targets**. The subset is ordinary projected demonstration supervision, not newly collected model-failure corrections or learned recovery data.

## Review, use and limitations

Named Codex agents performed the qualified source/image reviews; this is not human expert certification. The private package validates unchanged row hashes, accepted reviews, split membership and the trainer input contract. Public metadata transcribes those identities but does not provide the private approvals or pixels for independent semantic re-review.

All rows were exposed to the optimizer once in the fixed training run. The data is useful for investigating a small continuation and its failure modes. Twenty-five selected rows from one map do not establish broad coverage, independent navigation strategies or adequate stop supervision. The separate heading-restoration prototype is excluded from this corpus.

## Rights and public availability

The source downloads remain with [AerialVLA](https://huggingface.co/XuPeng23/AerialVLA), [TravelUAV raw data](https://huggingface.co/datasets/wangxiangyu0814/TravelUAV), and [TravelUAV metadata](https://huggingface.co/datasets/wangxiangyu0814/TravelUAV_data_json). The public repository does not mirror their images, instruction/label rows, raw state logs, compiled environments, or private reviews.

TravelUAV contains a nested [CC BY-NC 4.0 data license](https://github.com/prince687028/TravelUAV/blob/5cc26e9a4a55b9c788e918f7c3bb2dc5076a85e6/Model/LLaMA-UAV/DATA_LICENSE), while exact scope across its separately hosted archives needs clarification. This card does not relicense third-party data under the project code license. [Availability catalog](../../experiments/simulation-sft-v1/artifacts.json).
