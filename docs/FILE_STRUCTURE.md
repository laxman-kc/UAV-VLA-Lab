# Implemented file structure

Updated during execution on 7 September 2026 UTC. Files listed here are implemented entry points; their presence does not imply that every associated phase has passed. Consult [public results and limits](../PUBLIC_STATUS.md) for actual results. The tree distinguishes reusable source from private operational artifacts; listed private configuration files are not part of this public overlay.

```text
UAV-VLA-Lab/
  README.md
  configs/
    host.json                            # private operational instance
    assets/modern_city_map.json           # private operational manifest
    splits/modern_city_map_v1.json         # private frozen membership
    experiments/                         # private dated execution plans
    video/paired-static-rule-v1.json       # supported evidence-video selection rule
  scripts/
    host_probe.py, runtime_probe.py        # actual host/runtime evidence
    bootstrap_brev.sh, activate_runtime.sh
    download_assets.py, download_models.py
    prepare_assets.py                     # asset verification and metadata
    prepare_simulator_bundle.sh
    prepare_aerovla_episode.py            # strict single-episode selection
    prepare_evaluation_batch.py           # frozen cohort selection
    fix_airsim_rpc.py                     # recorded official transport repair
    patch_aerovla_runtime.py              # guarded reversible upstream patch
    _aerovla_runtime_hooks.py             # causal observation/policy/action log
    supervise_run.py                     # bounded owned workload process group
    run_simulation_session.py             # scene-manager lifecycle and evidence
    simulator_probe.py                   # real capture/controller acceptance
    reset_diagnostic.py, reset_protocol.py
    offline_policy_probe.py
    interrupt_after_event.py              # verified owned-run interruption
    summarize_navigation.py              # all-trial accounting and metrics
    analyze_baseline.py                   # independent reset/outcome audit
    compare_navigation.py                 # predeclared paired comparison
    prepare_development_comparison.py      # bind fixed candidate and original reuse
    prepare_holdout_comparison.py          # freeze two fresh holdout arms
    prepare_paired_video.py                # declared paired evidence image selection
    prepare_unstarted_session_amendment.py # pre-navigation receipt-path amendment
    prepare_amended_paired_video.py        # explicit frozen-rule amendment bridge
    audit_published_training.py            # read-only published-label audit
    prepare_published_reference.py         # unchanged historical five-row rule
    prepare_reference_extension.py         # twenty new training missions
    audit_reference_alignment.py           # source pose/action projection audit
    build_reviewed_reference_dataset.py    # package existing qualified reviews
    train_adapter_mvp.py                  # continuation/save/reload mechanics
    collect_heading_corrections.py         # deferred unexecuted prototype
    run_heading_batch.py                  # bounded prototype collection driver
    build_release.py                     # report, media and integrity bundles
  tests/                                 # focused contracts and lifecycle tests
  docs/
    SYSTEM_DESIGN.md, IMPLEMENTATION_PLAN.md
    DELIVERY_STANDARD.md, STATUS.md, FILE_STRUCTURE.md
    REFERENCE_ALIGNMENT_DECISION.md        # scoped demonstration-SFT decision
    reports/                             # selected reduced public findings; full private evidence separate
    runbooks/                            # setup, run, recover and verify
    templates/                           # common phase/release documents
  third_party/                           # ignored pinned upstream worktrees
  data-local/                            # ignored selected copied evidence
  releases/<phase>/<release-id>/          # ignored finalized report/video bundles
```

On Brev, the separate data root contains `assets/` (archives, models, raw episodes and compiled scenes), `manifests/` (pinned selections and plans), `setup/` (runtime receipts), `venvs/` and `runs/`. A simulation run has separate scene-session evidence and evaluator evidence. The exact directories, source hashes, runtime identity and selection are stored in its configuration and manifest.

Source Git excludes raw datasets, model weights, caches, generated video and full private diagnostic evidence. A release's checksum manifest ties reports and sampled video frames to their original files. Public publication has its own current status; a local finalized bundle is not evidence that an upload occurred.

Comparison entry points: [development preparation](runbooks/development_comparison_preparation.md), [holdout preparation](runbooks/holdout_comparison_preparation.md), [comparison contract](runbooks/navigation_comparison.md), and [paired-video evidence](runbooks/paired_video.md). Presence of a helper is not proof that its experiment completed.

A [no-start operational amendment](runbooks/unstarted_session_amendment.md) preserves the original protocol/editorial freeze and separately records any later candidate-only physical receipt-path redirect. It does not permit a new navigation attempt or change the frozen candidate.

Current completion and evidence: [14-phase completion index](STATUS.md), [reduced P13 comparison](reports/P13_DEVELOPMENT_COMPARISON.md) and [reduced P14 comparison](reports/P14_HOLDOUT_COMPARISON.md).
