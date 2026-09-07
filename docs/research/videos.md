# Video evidence

The videos show recorded observations, demonstration review, training results, and paired comparisons. They use saved images and result tables with disclosed static display holds. They are evidence presentations rather than continuous or synchronized flight recordings.

## Completed study

| Video | What it shows |
|---|---|
| [Development baseline](https://github.com/laxman-kc/UAV-VLA-Lab/releases/download/simulation-training-evaluation-v2/p08-development-baseline.mp4) | The original policy's complete development outcome table and sampled observations. |
| [Reviewed demonstrations](https://github.com/laxman-kc/UAV-VLA-Lab/releases/download/simulation-training-evaluation-v2/p09-reviewed-reference-examples.mp4) | Five source examples and the interpretation of their labels. |
| [Training mechanics](https://github.com/laxman-kc/UAV-VLA-Lab/releases/download/simulation-training-evaluation-v2/p10-reviewed-training-mechanics.mp4) | One-update training, fixed-row checks, and save/reload evidence. |
| [Dataset expansion](https://github.com/laxman-kc/UAV-VLA-Lab/releases/download/simulation-training-evaluation-v2/p11-reference-dataset-expansion.mp4) | Twenty additional published examples under the declared selection rule. |
| [Fixed-candidate training](https://github.com/laxman-kc/UAV-VLA-Lab/releases/download/simulation-training-evaluation-v2/p12-fixed-adapter-training.mp4) | All 25 updates and the identity of the candidate used in both comparisons. |
| [Development comparison](https://github.com/laxman-kc/UAV-VLA-Lab/releases/download/simulation-training-evaluation-v2/p13-development-comparison.mp4) | All 20 paired results, including gains and regressions. |
| [Holdout comparison](https://github.com/laxman-kc/UAV-VLA-Lab/releases/download/simulation-training-evaluation-v2/p14-holdout-comparison.mp4) | All 10 paired results and selected observations from both arms. |

All seven files are published in [Training and paired evaluation evidence](https://github.com/laxman-kc/UAV-VLA-Lab/releases/tag/simulation-training-evaluation-v2). Their uploaded sizes and SHA256 digests match the [publication receipt](../../experiments/simulation-sft-v1/video-publication-v2.json).

The paired videos use a fixed selection rule and retain gains and regressions. Each arm has its own timing and decision indices. Read the [complete results](results.md) and [method](technical-report.md) alongside the selected frames.

## Earlier execution and diagnostic evidence

| Evidence | What it helps inspect |
|---|---|
| [Reset history and timed-reset acceptance](https://github.com/laxman-kc/UAV-VLA-Lab/releases/download/simulation-mvp-evidence-v1/p03-reset-history-and-timed-pass.mp4) | Why an apparently running simulator still needs camera/state checks. |
| [Controller historical failure](https://github.com/laxman-kc/UAV-VLA-Lab/releases/download/simulation-mvp-evidence-v1/p04-controller-historical-failure.mp4) | An earlier failed control acceptance, retained with its context. |
| [Controller timed-reset acceptance](https://github.com/laxman-kc/UAV-VLA-Lab/releases/download/simulation-mvp-evidence-v1/p04-controller-timed-reset-pass.mp4) | Isolated heading, horizontal and vertical movement checks. |
| [Official reference diagnostic](https://github.com/laxman-kc/UAV-VLA-Lab/releases/download/simulation-mvp-evidence-v1/p06-official-reference-diagnostic.mp4) | A released-policy execution and its diagnostic evidence. |
| [Instrumented original-reset episode](https://github.com/laxman-kc/UAV-VLA-Lab/releases/download/simulation-mvp-evidence-v1/p06-original-reset-instrumented-demo.mp4) | The connection between saved observations and action records. |
| [Interruption and fresh restart](https://github.com/laxman-kc/UAV-VLA-Lab/releases/download/simulation-mvp-evidence-v1/p07-interruption-and-fresh-restart.mp4) | Owned process shutdown and a separately started attempt. |
| [Recording supplement](https://github.com/laxman-kc/UAV-VLA-Lab/releases/download/simulation-mvp-evidence-v1/p07-interruption-restart-recording-supplement.mp4) | The bounded direct recording-cost measurement and its limitations. |
| [Five published reference examples](https://github.com/laxman-kc/UAV-VLA-Lab/releases/download/simulation-mvp-evidence-v1/p10-five-published-reference-examples.mp4) | Early demonstration-SFT mechanics and source-example evidence. |

The eight uploaded files are available in [Simulation MVP evidence v1](https://github.com/laxman-kc/UAV-VLA-Lab/releases/tag/simulation-mvp-evidence-v1).

