# P13: fixed candidate development comparison

The fixed candidate succeeded on **7/20** development missions versus **6/20** for the released model. Three missions changed to success, two changed to failure and fifteen retained their SR outcome. All 20 pairs were valid, with no missing, unscored, unstarted or extra attempts in either arm. The difference is one mission, **+5 percentage points**, on this fixed development group; it does not establish broad or causal improvement.

This is a reduced public report derivative. Full raw logs, host diagnostics, private paths/configuration, original reports, source assets and weights remain separately retained. Video release review and permission are independent of numerical comparison validation.

| Measurement | Released original | Fixed candidate |
|---|---:|---:|
| Planned / observed / valid missions | 20 / 20 / 20 | 20 / 20 / 20 |
| Accepted initial resets | 20 | 20 |
| SR | 6/20 = 30% | 7/20 = 35% |
| OSR, including oracle success | 7/20 = 35% | 9/20 = 45% |
| Upstream collision-flag terminations | 13 | 11 |
| Completed actions / observations | 577 / 597 | 557 / 577 |

SR transitions: eleven both fail, four both succeed, two original-only successes, three candidate-only successes. OSR transitions: nine both fail, five both succeed, two original-only, four candidate-only. The predeclared plan requested no discordant-pair significance test; no post hoc p-value is added.

P13 explicitly reuses the exact valid P08 original baseline and adds twenty fresh candidate attempts. Both arms share the declared target-bearing-assisted task, RPC compatibility repair, separately identified `paused-final-pose-time-v1` reset behavior, 200-action cap and one-observed-attempt limit. All forty retained attempts pass the recorded reset/causal outcome checks. They are separate historical executions, not randomized or synchronized flights. Simulator variability can contribute to differences.

The candidate is the final P12 checkpoint after exactly 25 updates, one exposure to each of the 25 reviewed ordinary source-demonstration rows. Its recorded checkpoint-inventory SHA256 is `c8fdf4cc533e7360282f38cf6b5cc8e3937e005606494b4ba71483155c0619be`. It was fixed before development evaluation and is retained for P14 regardless of this result. No new training, checkpoint selection, failure-label replacement or holdout tuning occurred in P13.

| Declared row | Mission prefix | Original SR → candidate SR | Original actions → candidate actions |
|---:|---|---|---:|
| 1 | `071b894c` | No → No | 37 → 36 |
| 2 | `196334ed` | Yes → No | 58 → 43 |
| 3 | `1b11065c` | No → No | 17 → 41 |
| 4 | `249392f7` | No → No | 2 → 2 |
| 5 | `25620336` | No → No | 20 → 22 |
| 6 | `343f9571` | No → Yes | 16 → 37 |
| 7 | `46106a1d` | No → No | 75 → 23 |
| 8 | `4685a1f7` | No → No | 29 → 13 |
| 9 | `4d0c6483` | Yes → No | 36 → 34 |
| 10 | `52eb0469` | Yes → Yes | 25 → 26 |
| 11 | `5762cc30` | Yes → Yes | 37 → 32 |
| 12 | `6f56bc1b` | No → No | 14 → 7 |
| 13 | `928aab24` | No → No | 23 → 32 |
| 14 | `a04d1fec` | No → No | 18 → 18 |
| 15 | `a45a5217` | No → No | 45 → 28 |
| 16 | `d43dd483` | Yes → Yes | 39 → 35 |
| 17 | `d60e500c` | No → Yes | 9 → 22 |
| 18 | `e319e8e1` | Yes → Yes | 32 → 29 |
| 19 | `f14e7115` | No → No | 17 → 18 |
| 20 | `f42e6ff3` | No → Yes | 28 → 59 |

Every declared mission remains in this table. Rows 2 and 9 regressed in SR; rows 6, 17 and 20 gained SR. Row 9 retains candidate oracle success, which is distinct from SR. No outcome is relabeled from imagery.

The paired-video rule selects the first original-only and first candidate-only SR success in declared order, here rows 2 and 6. All-mission tables remain visible. Image pairs use derived decision indices—the number of preceding completed actions—and separately show each arm's terminal observation when required. Each panel reports its own host elapsed time. Index matching is not time, pose, path or physical-progress alignment. Static editorial holds are not continuous flight playback. See the [paired-video contract](../runbooks/paired_video.md).

The inherited raw candidate-analysis prose contains an inapplicable statement about unchanged released weights and an earlier video rule. Those historical bytes remain preserved; this report instead uses the actual trained-checkpoint contract and separately frozen paired-video rule. Numerical/source accounting and causal checks were validated separately from that stale prose.

Success is benchmark navigation success, not physical touchdown. Upstream collision flags include heuristics; endpoint contact samples/latches do not prove continuous collision-free flight. Fixed correlated missions from one map and unproven overlap with the released weights' complete original training history limit generalization. This development comparison neither proves that the training caused the difference nor establishes a recovery-learning result. The completed [P14 confirmation](P14_HOLDOUT_COMPARISON.md) retained this candidate and reported a mixed holdout result; no model switch occurred.

[Current cycle status](../../PUBLIC_STATUS.md) · [Development preparation](../runbooks/development_comparison_preparation.md) · [Paired comparison contract](../runbooks/navigation_comparison.md) · [Holdout preparation](../runbooks/holdout_comparison_preparation.md)
