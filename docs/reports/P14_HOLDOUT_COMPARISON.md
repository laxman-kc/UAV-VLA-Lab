# P14: fixed candidate holdout comparison

The fixed candidate succeeded on **4/10** holdout missions versus **3/10** for the released model, but oracle success fell from **6/10 to 5/10**. Two missions gained SR, one regressed and seven retained their SR outcome. All ten pairs were valid, with one observed attempt per mission in each fresh arm and no missing, unscored, unstarted or extra navigation attempts. This is a mixed small same-map result, not evidence of broad or causal improvement.

This reduced public derivative preserves the scientific counts and operational chronology. Full raw logs, source images, host diagnostics, private paths/configuration, original reports and weights remain separately retained. Numerical validation and video-publication permission are distinct.

| Measurement | Released original | Fixed candidate |
|---|---:|---:|
| Planned / observed / valid missions | 10 / 10 / 10 | 10 / 10 / 10 |
| Accepted initial resets | 10 | 10 |
| SR | 3/10 = 30% | 4/10 = 40% |
| OSR, including oracle success | 6/10 = 60% | 5/10 = 50% |
| Upstream collision-flag terminations | 4 | 5 |
| Completed actions / observations | 278 / 288 | 253 / 263 |

SR transitions: five both fail, two both succeed, one original-only success and two candidate-only successes. OSR transitions: two both fail, three both succeed, three original-only and two candidate-only. The plan requested no discordant-pair significance test; no post hoc p-value is added.

Both arms executed fresh after the holdout freeze, unlike P13's explicit historical P08 original reuse. Both used the same declared target-bearing-assisted task, RPC compatibility repair, separately identified `paused-final-pose-time-v1` reset behavior, source/runtime contract, ordered ten-mission cohort, 200-action cap and one-observed-attempt limit. All twenty actual attempts passed recorded reset and causal outcome checks; owned-process cleanup completed. These separate executions were not synchronized or randomized flights.

The candidate is the same fixed final P12 checkpoint evaluated in P13: 25 updates, one exposure to each of the 25 reviewed ordinary source-demonstration rows. Its recorded checkpoint-inventory SHA256 is `c8fdf4cc533e7360282f38cf6b5cc8e3937e005606494b4ba71483155c0619be`. The prior rule required retaining it regardless of the development result. P14 did not train, select a different checkpoint, replace failure labels or tune on holdout outcomes.

## Preserved infrastructure failure and chronology

The original holdout protocol froze at **06:21:24 UTC on 7 September 2026**, after the P13 result was reported. The first candidate physical launch failed at port preflight before a manager, evaluator command or navigation directory existed. Its complete failure receipt and independent absence check remain retained. It contributed **one failed infrastructure launch and zero navigation attempts**.

A separately dated amendment at **06:53:37 UTC** changed only the candidate physical session receipt paths and their dependent bindings. The original protocol/editorial freeze, logical session/trial IDs, ordered missions, models, runtime, evidence destination and one-attempt cap remained unchanged. The candidate's first actual execution began at **06:55:42 UTC**, after that amendment. The original arm was not rerun. Completion validation separately checked path, chronology, configuration and source identity; the comparison then independently checked navigation validity. Thus there were three physical launches but only twenty actual navigation attempts across the two arms.

## Every declared pair

| Declared row | Mission prefix | Original SR → candidate SR | Original OSR → candidate OSR | Original actions → candidate actions |
|---:|---|---|---|---:|
| 1 | `8daaf47b` | Yes → Yes | Yes → Yes | 37 → 45 |
| 2 | `44f9a56c` | No → Yes | No → Yes | 9 → 34 |
| 3 | `71108556` | No → No | No → Yes | 35 → 25 |
| 4 | `7eda8e52` | No → No | Yes → No | 21 → 3 |
| 5 | `3738e6c6` | No → No | No → No | 20 → 18 |
| 6 | `611630c3` | Yes → Yes | Yes → Yes | 63 → 59 |
| 7 | `6452f234` | No → No | No → No | 10 → 11 |
| 8 | `1f90a8a5` | No → Yes | Yes → Yes | 18 → 23 |
| 9 | `8285681c` | Yes → No | Yes → No | 27 → 23 |
| 10 | `ecdd2a97` | No → No | Yes → No | 38 → 12 |

Rows 2 and 8 gained SR; row 9 regressed. For OSR, rows 2 and 3 gained while rows 4, 9 and 10 regressed. Every declared mission remains in the table, and no outcome was relabeled from imagery.

The predeclared video rule selects the first original-only and candidate-only SR success in declared order, here rows 9 and 2, while retaining all ten outcomes in tables. Paired frames use derived decision indices—the number of preceding completed actions—and separately show terminal observations when required. Each arm retains its own host elapsed time. Index matching is not time, pose, path or physical-progress alignment. Display holds are editorial, not continuous flight playback. The operational amendment bridge preserves this rule. See the [paired-video contract](../runbooks/paired_video.md) and [no-start amendment accounting](../runbooks/unstarted_session_amendment.md).

The inherited raw analyzer still contains inapplicable P08 prose about unchanged weights and an older video rule. Those original bytes remain preserved; this report follows the actual checkpoint contracts, completed comparison and separately frozen P14 editorial rule. A later validation-only video-helper update strengthened canonical-rule/source checks; its date and diff remain recorded without changing the frozen selection.

Success and OSR follow upstream target-navigation conventions. LAND is not physical touchdown. Collision flags include heuristics; endpoint samples/latches are incomplete contact measurements and do not establish continuously collision-free motion. Ten correlated missions from one map, unproven overlap with the released weights' complete original training history, and unmeasured repeat-run variance limit interpretation. No new failure-correction, recovery-learning, physical-UAV or generalized landing capability is established.

The full cycle therefore reports completed engineering and mixed descriptive navigation results: development SR 6/20 → 7/20; holdout SR 3/10 → 4/10; holdout OSR 6/10 → 5/10. Further training or evaluation would require a separately declared experiment.

[Current cycle status](../research/technical-report.md) · [14-phase completion index](../STATUS.md) · [Holdout preparation](../runbooks/holdout_comparison_preparation.md) · [Paired comparison contract](../runbooks/navigation_comparison.md)
