# UAV-VLA-Lab

This project implements simulated UAV navigation and adaptation using the released AeroVLA policy and compiled TravelUAV environments. The operator workstation controls a remote model and simulator runtime. Level 1 is excluded.

**Current verified capabilities and limits:** [PUBLIC_STATUS.md](PUBLIC_STATUS.md). It records the completed 14-phase engineering cycle under explicit source-scope amendments, historical reset failures, the separate timed-reset runtime, and both development and holdout comparisons.

- [Implementation plan: small MVP phases](docs/IMPLEMENTATION_PLAN.md)
- [System design: architecture, stack, interfaces, source findings](docs/SYSTEM_DESIGN.md)
- [Implemented file structure](docs/FILE_STRUCTURE.md)
- [14-phase completion and public evidence index](docs/STATUS.md)
- [Reduced P13 development report](docs/reports/P13_DEVELOPMENT_COMPARISON.md)
- [Reduced P14 holdout report](docs/reports/P14_HOLDOUT_COMPARISON.md)
- [Delivery standard: documentation, reports, video, evidence](docs/DELIVERY_STANDARD.md)
- [Reusable phase template](docs/templates/PHASE_PLAN.md)
- [Reusable report template](docs/templates/REPORT.md)

The released task uses benchmark target-bearing information. Demonstration navigation success does not establish physical touchdown or general navigation reliability. The executed training cycle used 25 unchanged published demonstrations after qualified source/agent review, not newly collected failure corrections. The fixed P12 candidate scored 7/20 versus 6/20 on development, with three gains and two regressions. On ten fresh holdout pairs, SR was 4/10 versus 3/10, while OSR fell to 5/10 from 6/10. This is a mixed small same-map pilot, without evidence of broad or causal improvement.

Source code lives in `scripts/`, declared inputs in `configs/`, and operating instructions in `docs/runbooks/`. Large assets, checkpoints, raw runs and private diagnostic bundles remain outside this source update. The reviewed public overlay and separately screened MP4 hashes are described in [REVIEW.md](REVIEW.md) and [VIDEO_AUDIT.md](VIDEO_AUDIT.md).
