# Reference-target alignment investigation

Recorded 7 September 2026, after the frozen P08 baseline and before further adaptation. This is a dated design decision, not an approved dataset or a completed training result.

The first training mechanics experiment used five unchanged published examples. At that time, their physical coordinate frame and temporal alignment had not been independently established. Those historical receipts remain unchanged.

Direct inspection of the corresponding raw training states now gives an exact numerical match for all three label components in all five examples. For current record `i` and future record `i+5`, with world positions `p` and xyzw orientations `q`, the observed relationship is:

```text
body_delta = Rotation(q_i).inverse() * (p_(i+5) - p_i)
label.forward = body_delta.x
label.down    = body_delta.z
label.yaw     = (Rotation(q_i).inverse() * Rotation(q_(i+5))).as_euler("zyx")[0]
```

All fifteen component residuals were zero in the initial SciPy calculation. The new audit fixes an absolute comparison tolerance of `1e-9`, checks all six consecutive raw record identities, and hashes the source images, states and publisher rows. The original five examples are discovery cases. A separately selected increment of twenty will test this relationship without selecting on its residuals.

The raw files contain frame indices and state poses, with no elapsed-time timestamps. The established interval is five recorded index increments. It is not five seconds, a fixed simulation duration, or the duration of one controller invocation. Exact agreement on selected examples does not establish the publisher's unreleased generator implementation for every row.

The representation discards body lateral translation and relative roll/pitch. The released executor also approximates the represented motion: it rotates first, then interprets forward motion along the new heading and vertical motion in world NED. Its large-yaw branch suppresses horizontal translation. The new audit records those omitted components and the resulting geometric discrepancy; it does not claim exact replay of a human path. See the [pinned controller](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/airsim_plugin/AirVLNSimulatorClientTool_AeroVLA.py) and [dataset reader](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/src/aerovla_dataset.py).

The authors describe their training source as expert demonstrations and their objective as behavior cloning. That is source attribution, not a claim that this project independently certified a human expert or optimal navigation. Our review must verify the selected data's bytes, frame alignment, instruction provenance, images, bounds and split isolation. [AeroVLA paper, sections 3.5 and 4.1–4.2](https://arxiv.org/html/2603.14363v1).

The immediate adaptation arm will use ordinary published demonstration targets only if the mechanical audit and independent sample review pass. It continues the exact-stack route. It does not claim newly collected model-failure corrections, learned recovery, new human supervision or improvement. P09's deliverable is therefore explicitly scoped to an audited supervised reference dataset; P11 versions that dataset; P12–P14 test one bounded candidate under the existing navigation protocol. The original model remains the comparison arm.

The separately prelocked heading-restoration prototype remains unapproved and unexecuted. Its controller objective is not exposed by the retained navigation prompt, so a successful heading maneuver alone would not establish a correct navigation training label. The prototype and its frozen plan are retained as research work, with no accepted samples or execution claim.

No trainer approval gate is removed. A new `audited_reference_expert` manifest requires a named, dated independent agent review, exact evidence hashes and explicit scope. Human approval or expertise is not asserted by an agent review. Any failed audit or rejected sample remains visible; neither labels nor tolerances are changed to manufacture a passing dataset.
