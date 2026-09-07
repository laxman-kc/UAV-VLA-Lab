# Audited adaptation of a released UAV policy in simulation

**UAV-VLA-Lab · simulation-sft-v1 · experiment completed 7 September 2026**

This study connects a released UAV policy to a recorded simulator workflow, audits a small set of publisher demonstrations, continues the released adapter, and compares one fixed candidate against the original. It demonstrates a complete experimental pipeline. Navigation results are mixed: the candidate gains one SR success in each cohort, while holdout oracle success decreases by one mission.

![Original and candidate SR and OSR, with exact mission counts](../assets/figures/simulation-sft-v1/outcome-rates.svg)

The public record contains [all 60 scored episode rows](../../experiments/simulation-sft-v1/results/episodes.csv), [30 paired comparisons](../../experiments/simulation-sft-v1/results/paired.csv), and [all 25 optimizer steps](../../experiments/simulation-sft-v1/results/training-steps.csv). These are selected numeric fields from retained sealed evidence. Readers can recompute the results and figures from the public tables; the raw observations, logs, reviews and checkpoint bytes are not included. [Reproduction and availability](reproduce.md).

## Research question and contribution

Can a small, auditable supervised continuation of a released UAV adapter produce a usable candidate whose navigation changes can be measured without losing failures, changing the evaluation cohort, or confusing training fit with navigation quality?

The contribution is an integrated research workflow, with four concrete uses:

1. **Diagnose integration before evaluating policy quality.** Camera/state acceptance and isolated movement probes expose reset/controller faults that a success-rate table alone would conceal.
2. **Trace a navigation decision.** Recorded observations, prompts, policy output, decoded actions, controller requests and completion events support causal ordering checks and explicit incomplete-attempt accounting.
3. **Audit adaptation inputs and mechanics.** Source-label geometry, sample membership, exact weight identities, intended trainable tensors, and save/unload/reload checks make a small training run inspectable.
4. **Compare the fixed candidate transparently.** Every planned pair, gain, regression, oracle outcome and infrastructure failure retains its declared role.

This work integrates and evaluates existing components. It does not introduce a new foundation model or establish a new state-of-the-art navigation method. The released policy comes from [AeroVLA](https://github.com/XuPeng23/AeroVLA), its base from [OpenVLA](https://github.com/openvla/openvla), and the simulator/data from [TravelUAV](https://github.com/prince687028/TravelUAV).

## Task and execution protocol

The task is official benchmark **target-bearing-assisted navigation** in **ModernCityMap**. The policy receives front/down visual inputs and the benchmark-derived directional prompting. It is not an instruction-only experiment with hidden goal coordinates. Upstream action tokens encode forward/down displacement and yaw; their inspected ranges are `[0,5] m`, `[-5,5] m` and `[-1.1,1.1] rad`. The execution controller's rotation and translation conventions are preserved. `LAND` is a stopping token; the observed outcome does not certify physical touchdown.

The implementation pins AeroVLA commit `e37685afb8953d1f5a09155d7255960cee1bfd9d`. Early reset variants failed camera/state acceptance. The final evaluation uses the separately named `paused-final-pose-time-v1` reset protocol plus the recorded RPC repair. It retains `ClockSpeed=10`, requests a 0.001-second reset continuation, and checks the actual captured pose before policy input. Requested and realized simulator time can differ. Reset acceptance uses unchanged 0.1 m position and 0.05 rad orientation tolerances; it does not assert exact-zero velocity.

Two reset/capture attempts and three isolated heading/horizontal/vertical probes passed. All 60 scored study attempts also passed the independent reset and navigation audits. That bounded evidence supports this execution protocol; it is not a general simulator-reliability certification or a reproduction using the untouched released evaluator. [Historical protocol and code hashes](../../experiments/simulation-sft-v1/configs/protocol.json), [reset implementation history](../runbooks/reset_protocol.md).

## Demonstrations and supervised continuation

The training corpus contains **25 unchanged publisher rows from 25 training missions**: five alignment-discovery examples followed by twenty examples selected separately under a declared source/schema/file rule. These missions are disjoint from the project's twenty development and ten holdout missions.

For the audited examples, forward/down labels equal the x/z components of `R(q_i)^−1 (p_(i+5) − p_i)`; yaw is the first ZYX Euler component of `R(q_i)^−1 R(q_(i+5))`. The numerical audit tolerance is `1e-9`. All six record identities from `i` through `i+5` were retained. **Five record increments do not establish five physical seconds.** Lateral displacement and relative pitch/roll are omitted. Quantization, rotate-before-translate execution and the controller's large-yaw branch can differ materially from the source path.

Qualified reviews were performed by named Codex agents and retained privately. This is ordinary published-demonstration SFT, not human certification, optimal-navigation supervision, newly collected failure corrections, or exact replay of the source trajectory. Every row has both stop flags false; the corpus has no positive `LAND` targets. The separate heading-restoration prototype remained unapproved and unexecuted because its privileged objective was absent from the retained navigation prompt. [Dataset card](dataset-card.md).

The candidate starts from the released adapter and its saved projector, **not the one-update mechanics checkpoint**. Training freezes the BF16 base, uses FP32 trainable parameters/state with BF16 autocast, and continues the existing LoRA/projector through the pinned reader and collator. AdamW uses learning rate `2e-5`, seed `100`, batch/accumulation `1/1`, weight decay `0.03`, gradient clipping `1.0`, and no scheduler. The fixed budget is 25 optimizer updates: one seeded shuffled exposure to every row, with no best-checkpoint search. [Effective historical settings](../../experiments/simulation-sft-v1/configs/training.json).

All 454 intended tensors changed. The fixed training row-0 loss decreased from `0.48068147897720337` to `0.04631422460079193`; the reloaded loss was identical and the recorded maximum logit difference was zero. Row 0 itself was trained at update 11. These checks establish training fit and checkpoint integrity, not held-out accuracy. Exact optimizer/RNG-state resume is unsupported. [Model card](model-card.md).

![All optimizer-step losses and the separate fixed-training-row before/after/reload check](../assets/figures/simulation-sft-v1/training-fit.svg)

## Evaluation design and results

Each arm permits one observed attempt per mission and at most 200 actions. The original development arm is the explicitly reused twenty-mission baseline; candidate development is a later execution. Holdout runs both ten-mission arms fresh after its frozen plan. The same final P12 candidate is retained regardless of development outcomes. The holdout plan was created after development results were known, under the predeclared fixed-candidate rule; no holdout checkpoint selection occurred.

One candidate holdout infrastructure launch failed during port preflight, before manager, command or navigation startup. A dated path-only amendment preceded the first actual candidate navigation launch. It changed receipt destinations, not the cohort, runtime, candidate or attempt limit. The failed launch therefore contributes **zero navigation attempts**; it is still a retained infrastructure failure. [Accounting contract](../runbooks/unstarted_session_amendment.md).

| Cohort | Valid pairs | Original SR | Candidate SR | Original OSR | Candidate OSR |
|---|---:|---:|---:|---:|---:|
| Development | 20/20 | 6/20 (30%) | 7/20 (35%) | 7/20 (35%) | 9/20 (45%) |
| Holdout | 10/10 | 3/10 (30%) | 4/10 (40%) | 6/10 (60%) | 5/10 (50%) |

SR and OSR retain the recorded upstream navigation flags and conventions. Upstream collision flags include heuristics and are distinct from sampled endpoint contact. No invalid, missing or unstarted navigation result was converted to a failure; all thirty pairs are valid.

![All paired SR and OSR gains, regressions and unchanged outcomes](../assets/figures/simulation-sft-v1/paired-transitions.svg)

Development SR has three gains, two regressions, eleven both-fail and four both-success pairs. Holdout SR has two gains, one regression, five both-fail and two both-success pairs. Reporting the net increase alone would hide these reversals and the decrease in holdout OSR. [Complete results and timing](results.md).

Across the four arm executions, the retained records contain **1,665 completed actions and 1,725 observations**. Each scored attempt has one more observation than completed actions. The source export reconciles these counts against the sealed causal-validation summaries. Public numeric consistency checks do not replay the private raw traces.

## Interpretation and limitations

The useful result is an operational, auditable adaptation-and-comparison workflow plus an honestly bounded mixed study. It enables others to inspect the experiment, check metric arithmetic, understand failure accounting, and reproduce a new run with compatible assets. The evidence does not establish that the candidate is generally better.

- One map and small fixed cohorts limit generalization. Each mission has one observed attempt per arm; repeat-run variance is unmeasured.
- Project split separation does not establish that the released model never saw these missions during prior training.
- Historical development-baseline reuse and nonrandomized execution order do not isolate a causal training effect. No significance test is reported; the figures add no inferred uncertainty bars.
- Target-bearing assistance, the changed reset protocol and upstream stopping conventions limit comparisons with other protocols and physical UAV behavior.
- Omitted source-motion components and unknown label timing constrain how the demonstration labels should be interpreted. No new recovery-learning or positive-stop result is supported.
- Host timing includes its stated load, data, controller and logging costs; sampled/end-point measurements are not continuous monitoring or pure model benchmarks.
- Private traces, source pixels, reviews and checkpoint bytes remain outside the public distribution. Hashes support identity checks but do not give readers access to absent bytes.

The historical analyzer emitted development/original-only prose even when reused for later arms. This report derives cohort/model wording from the actual comparison context; it does not rewrite the sealed analyzer outputs. Future code or protocol changes need new source identities and new experiment records.

## Artifacts and next useful work

The [study record](../../experiments/simulation-sft-v1/README.md) groups results, method settings, identities and availability under this one project. The [reproduction guide](reproduce.md) regenerates figures and validates the public arithmetic. Earlier diagnostic media are available in the existing GitHub release. The seven study recordings are published in [Simulation training and evaluation v2](https://github.com/laxman-kc/UAV-VLA-Lab/releases/tag/simulation-training-evaluation-v2); their names, sizes and SHA256 digests match the [publication receipt](../../experiments/simulation-sft-v1/video-publication-v2.json). They present saved observations, excerpts and figures with editorial holds, not continuous flights. The P12 adapter is not offered as a public download.

The next research questions are whether the observed differences persist across repeated runs and additional maps, and whether task-consistent corrections and positive stop examples improve navigation. Those require a new declared dataset/protocol and fresh evidence. They are future experiments, not conclusions of this study.
