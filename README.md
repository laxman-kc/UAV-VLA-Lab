# UAV-VLA-Lab

This project implements simulated UAV navigation and adaptation using the released AeroVLA policy and compiled TravelUAV environments. The operator workstation controls a remote model and simulator runtime. Level 1 is excluded.

**Current verified capabilities and limits:** [PUBLIC_STATUS.md](PUBLIC_STATUS.md). It records the bounded results, historical reset failures, the separate timed-reset runtime, and the incomplete expert-correction and adaptation gates.

- [Implementation plan: small MVP phases](docs/IMPLEMENTATION_PLAN.md)
- [System design: architecture, stack, interfaces, source findings](docs/SYSTEM_DESIGN.md)
- [Delivery standard: documentation, reports, video, evidence](docs/DELIVERY_STANDARD.md)
- [Reusable phase template](docs/templates/PHASE_PLAN.md)
- [Reusable report template](docs/templates/REPORT.md)

The released task uses benchmark target-bearing information. Demonstration navigation success does not establish physical touchdown or general navigation reliability. A one-update published-reference experiment verifies training mechanics; it does not demonstrate improved behavior or complete the expert-correction phase.

Source code lives in `scripts/`, declared inputs in `configs/`, and operating instructions in `docs/runbooks/`. Large assets, checkpoints, raw runs and private diagnostic bundles remain outside this source update. The reviewed public overlay and separately screened MP4 hashes are described in [REVIEW.md](REVIEW.md) and [VIDEO_AUDIT.md](VIDEO_AUDIT.md).
