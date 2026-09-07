# Contributing

Contributions can improve the analysis, clarify the report, fix a reproducibility issue, or extend the experiment. Open a focused issue or pull request describing the problem, the change, and the evidence supporting it.

For research changes:

- Declare the data split, candidate-selection rule, stopping criteria, attempt limits, and metric definitions before evaluation.
- Retain gains, regressions, incomplete runs, and startup failures.
- Keep a numerical source and provenance record for every chart. Describe video timing and selection rules.
- Give new experiments a new identifier. Preserve the published `simulation-sft-v1` record and its original source hashes.
- Distinguish training fit, simulator navigation, source-derived labels, and physical UAV behavior.

For code changes, run the relevant tests and report what was checked. Keep optional workflow dependencies isolated and preserve the recorded observation/action conventions. Remove credentials and private machine details from shared logs.

Contributions must be material you are entitled to share under the applicable license. Upstream notices remain applicable. Follow the [code of conduct](CODE_OF_CONDUCT.md).
