# UAV-VLA-Lab

**Status: implementation started.** Brev access and implementation through the planned phases are authorized. Phase results are recorded only after execution and validation. Level 1 is excluded.

This project implements simulated UAV navigation and adaptation using the released AeroVLA policy and compiled TravelUAV environments. The Mac is the operator workstation; NVIDIA Brev `vla01` runs the model and simulator.

- [Execution status and measured host specifications](docs/STATUS.md)

- [Implementation plan: small MVP phases](docs/IMPLEMENTATION_PLAN.md)
- [System design: architecture, stack, interfaces, source findings](docs/SYSTEM_DESIGN.md)
- [Delivery standard: documentation, reports, video, evidence](docs/DELIVERY_STANDARD.md)
- [Reusable phase template](docs/templates/PHASE_PLAN.md)
- [Reusable report template](docs/templates/REPORT.md)

The initial route reproduces the released AeroVLA goal-bearing-assisted task. Three real recorded observation pairs have passed offline inference on the L40. This result does not establish closed-loop navigation success. Phase reports and verified media are published incrementally through GitHub releases.

Source code lives in `scripts/`, fixed inputs in `configs/`, and operating instructions in `docs/runbooks/`. Large assets, checkpoints, raw runs and release bundles remain outside source Git. Their revisions and hashes are recorded in each phase's evidence.
