#!/usr/bin/env python3
"""Validate public numeric evidence and regenerate the three study figures.

--check is standard-library only and writes nothing. Rendering needs matplotlib.
No private evidence, model, simulator, credentials or network are accessed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STUDY = ROOT / "experiments/simulation-sft-v1"
DEFAULT_FIGURES = ROOT / "docs/assets/figures/simulation-sft-v1"
SIZES = {"development": 20, "holdout": 10}
METRICS = {"success": "successes", "oracle_success": "oracle_successes"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    def invalid(value):
        raise ValueError("Non-finite JSON: " + value)
    return json.loads(path.read_text(), parse_constant=invalid)


def rows(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def flag(value):
    require(value in ("True", "False"), "Expected a literal CSV boolean")
    return value == "True"


def transitions(pairs, metric):
    counts = {"both_failure": 0, "original_only_success": 0, "candidate_only_success": 0, "both_success": 0}
    labels = {(False, False): "both_failure", (True, False): "original_only_success",
              (False, True): "candidate_only_success", (True, True): "both_success"}
    for row in pairs:
        counts[labels[flag(row["original_" + metric]), flag(row["candidate_" + metric])]] += 1
    return counts


def validate(study):
    episodes = rows(study / "results/episodes.csv")
    pairs = rows(study / "results/paired.csv")
    steps = rows(study / "results/training-steps.csv")
    members = rows(study / "dataset/membership.csv")
    aggregate = read_json(study / "results/aggregate.json")
    summary = read_json(study / "results/training-summary.json")
    config = read_json(study / "configs/training.json")
    protocol = read_json(study / "configs/protocol.json")
    identities = read_json(study / "configs/model-identities.json")
    catalog = read_json(study / "source-catalog.json")
    sources = {r["id"]: r for r in catalog["sources"]}
    require(len(sources) == len(catalog["sources"]), "Duplicate source identifiers")
    require(all(len(s["sha256"]) == 64 and all(c in "0123456789abcdef" for c in s["sha256"]) and
                type(s["bytes"]) is int and s["bytes"] > 0 for s in sources.values()), "Malformed source receipts")
    require(identities["candidate_manifest_sha256"] == sources["candidate-checkpoint-manifest"]["sha256"], "Candidate identity differs")
    require(len(episodes) == 60 and len(pairs) == 30, "Study count differs")
    groups = []
    for cohort, n in SIZES.items():
        paired = [r for r in pairs if r["cohort"] == cohort]
        require(len(paired) == n and [int(r["mission_ordinal"]) for r in paired] == list(range(1, n + 1)), "Paired order differs")
        groups.append({r["episode_id"] for r in paired})
        require(len(groups[-1]) == n, "Repeated paired mission")
        for role in ("original", "candidate"):
            arm = [r for r in episodes if (r["cohort"], r["arm"]) == (cohort, role)]
            expected = aggregate["cohorts"][cohort][role]
            require(len(arm) == n and {r["episode_id"] for r in arm} == groups[-1], "Arm membership differs")
            require(all(flag(r["valid"]) and flag(r["accepted_reset"]) and int(r["observed_attempts"]) == 1 for r in arm), "Unscored/retried row")
            denominators = {"trials": len(arm), "valid_trials": sum(flag(r["valid"]) for r in arm),
                            "observed_attempts": sum(int(r["observed_attempts"]) for r in arm),
                            "accepted_resets": sum(flag(r["accepted_reset"]) for r in arm)}
            require(all(type(expected[k]) is int and expected[k] == v for k, v in denominators.items()),
                    "Aggregate denominator differs")
            for field, key in METRICS.items():
                require(sum(flag(r[field]) for r in arm) == expected[key], "Metric count differs")
            for key in ("actions_completed", "observations_recorded", "policy_outputs_recorded"):
                require(sum(int(r[key]) for r in arm) == expected[key], "Trace count differs")
            require(sum(flag(r["any_sampled_endpoint_contact"]) for r in arm) == expected["any_sampled_endpoint_contact"] and
                    sum(flag(r["upstream_collision_flag"]) for r in arm) == expected["upstream_collision_flag"], "Contact/flag counts differ")
            for row in arm:
                require(int(row["observations_recorded"]) == int(row["actions_completed"]) + 1 and
                        int(row["policy_outputs_recorded"]) == int(row["actions_completed"]), "Causal counts differ")
                require(row["analysis_source_id"] in sources and row["comparison_source_id"] in sources, "Unbound result")
                require(math.isfinite(float(row["final_target_distance_m"])) and float(row["final_target_distance_m"]) >= 0, "Invalid distance")
                match = next(p for p in paired if p["episode_id"] == row["episode_id"])
                require(all(row[k] == match[role + "_" + k] for k in METRICS), "Paired flags disagree")
        for metric, key in (("success", "paired_sr_transitions"), ("oracle_success", "paired_osr_transitions")):
            require(transitions(paired, metric) == aggregate["cohorts"][cohort][key], "Transition counts differ")
        require(all(int(r["sr_difference_candidate_minus_original"]) ==
                    int(flag(r["candidate_success"])) - int(flag(r["original_success"])) for r in paired), "Paired difference differs")
    train_ids = {r["episode_id"] for r in members}
    require(len(members) == len(train_ids) == len(steps) == 25 and
            not groups[0] & groups[1] and not train_ids & (groups[0] | groups[1]), "Dataset count/split differs")
    require([int(s["optimizer_step"]) for s in steps] == list(range(1, 26)), "Training steps missing")
    expected_order = list(range(25)); random.Random(config["seed"]).shuffle(expected_order)
    require([int(s["training_row_index"]) for s in steps] == expected_order, "Exposure permutation differs")
    by_index = {int(r["training_row_index"]): r for r in members}
    for i, step in enumerate(steps, 1):
        require(step["sample_id"] == by_index[int(step["training_row_index"])]["sample_id"] and
                int(step["completed_sample_exposures"]) == i, "Exposure identity differs")
        require(all(math.isfinite(float(step[k])) and float(step[k]) >= 0 for k in
                    ("microbatch_loss", "gradient_norm_before_clip", "learning_rate", "recorded_step_seconds")), "Invalid step value")
    require(summary["optimizer_steps"] == summary["sample_exposures"] == 25 and
            summary["fixed_row_exposed_at_step"] == expected_order.index(0) + 1 == 11, "Training summary differs")
    reload = summary["reload_validation"]
    loss_values = [summary["fixed_row_loss"][k] for k in ("before", "after", "reloaded")]
    reload_values = [reload[k] for k in ("last_token_logits_max_absolute_error", "atol", "rtol")]
    require(all(type(value) in (int, float) and math.isfinite(value) and value >= 0
                for value in loss_values + reload_values), "Invalid loss/reload numeric value")
    require(all(reload[k] is True for k in ("exact_adapter_and_projector_hashes_match",
                "last_token_logits_allclose", "loss_isclose")) and
            summary["fixed_row_loss"]["after"] == summary["fixed_row_loss"]["reloaded"] and
            reload["last_token_logits_max_absolute_error"] == 0, "Historical exact reload differs")
    require(protocol["max_actions"] == 200 and protocol["failed_launch_navigation_attempts"] == 0, "Protocol differs")
    result = {"status": "public_numeric_consistency_passed", "episode_rows": len(episodes), "paired_rows": len(pairs),
              "training_steps": len(steps), "training_missions": len(members),
              "total_recorded_actions": sum(int(r["actions_completed"]) for r in episodes),
              "total_recorded_observations": sum(int(r["observations_recorded"]) for r in episodes),
              "source_receipts": len(sources),
              "scope": "Recomputed public tables, membership, counts and identities; private raw causal traces are not replayed"}
    return result, aggregate, pairs, steps, summary


def render(study, output):
    result, aggregate, pairs, steps, summary = validate(study)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import PIL

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 13,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titleweight": "bold", "axes.titlesize": 14,
                         "axes.labelsize": 12, "xtick.labelsize": 12, "ytick.labelsize": 12,
                         "axes.labelcolor": "#334155",
                         "text.color": "#0f172a", "svg.fonttype": "none", "svg.hashsalt": "uav-vla-simulation-sft-v1"})
    output.mkdir(parents=True, exist_ok=True)
    files = []

    def save(fig, name):
        for extension in ("svg", "png", "pdf"):
            path = output / (name + "." + extension)
            metadata = {"Date": None} if extension == "svg" else (
                {"CreationDate": None, "ModDate": None, "Creator": "UAV-VLA-Lab"} if extension == "pdf" else {})
            fig.savefig(path, dpi=180, facecolor="white", metadata=metadata)
            files.append({"file": path.name, "sha256": sha(path), "bytes": path.stat().st_size})
        plt.close(fig)

    colors = {"original": "#2563eb", "candidate": "#d97706"}
    role_labels = {"original": "Before training", "candidate": "After training"}
    cohort_labels = {"development": "Development", "holdout": "Final test"}
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.4))
    for ax, (cohort, n) in zip(axes, SIZES.items()):
        for role, offset in (("original", -.19), ("candidate", .19)):
            values = [aggregate["cohorts"][cohort][role][k] for k in ("successes", "oracle_successes")]
            positions = np.arange(2) + offset
            ax.bar(positions, [100 * v / n for v in values], width=.34, color=colors[role], label=role_labels[role])
            for x, count in zip(positions, values):
                ax.text(x, 100 * count / n + 2, f"{count}/{n}\n{100*count/n:.0f}%", ha="center", va="bottom", fontsize=12)
        ax.set(xticks=[0, 1], xticklabels=["Successful stop", "Reached target area"],
               ylim=(0, 100), title=f"{cohort_labels[cohort]} · {n} missions", ylabel="Missions (%)")
        ax.tick_params(axis="x", length=0, pad=10)
        ax.grid(axis="y", alpha=.18); ax.set_axisbelow(True)
    fig.suptitle("Navigation before and after training", fontsize=19, fontweight="bold", y=.97)
    fig.legend(*axes[0].get_legend_handles_labels(), frameon=False, loc="upper center",
               bbox_to_anchor=(.5, .91), ncol=2)
    fig.tight_layout(rect=(0, .015, 1, .83)); save(fig, "outcome-rates")

    categories = [("both_failure", "Neither succeeded", "#64748b"), ("both_success", "Both succeeded", "#2563eb"),
                  ("original_only_success", "Worse after training", "#be123c"), ("candidate_only_success", "Better after training", "#0f766e")]
    fig, ax = plt.subplots(figsize=(12, 5.8))
    names, values = [], []
    for cohort, n in SIZES.items():
        for metric, label in (("SR", "Successful stop"), ("OSR", "Reached target area")):
            names.append(f"{cohort_labels[cohort]} · {n} missions\n{label}")
            values.append((aggregate["cohorts"][cohort][f"paired_{metric.lower()}_transitions"], n))
    left = np.zeros(4)
    for key, label, color in categories:
        widths = [100 * counts[key] / n for counts, n in values]
        ax.barh(range(4), widths, left=left, color=color, height=.6, label=label)
        for i, ((counts, _), w) in enumerate(zip(values, widths)):
            if counts[key]: ax.text(left[i] + w / 2, i, str(counts[key]), color="white", ha="center", va="center", fontweight="bold")
        left += widths
    ax.set(yticks=range(4), yticklabels=names, xlim=(0, 100), xlabel="Share of missions (%)")
    ax.tick_params(axis="y", length=0, pad=12)
    ax.invert_yaxis()
    fig.legend(*ax.get_legend_handles_labels(), loc="lower center", bbox_to_anchor=(.5, .025),
               ncol=2, frameon=False, columnspacing=2.5)
    fig.suptitle("Changes on the same missions", fontsize=19, fontweight="bold", y=.97)
    fig.text(.5, .885, "Numbers inside bars are mission counts", ha="center", fontsize=12, color="#475569")
    fig.subplots_adjust(left=.30, right=.975, bottom=.26, top=.81); save(fig, "paired-transitions")

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.4), gridspec_kw={"width_ratios": [1.6, 1]})
    x = [int(s["optimizer_step"]) for s in steps]
    y = [float(s["microbatch_loss"]) for s in steps]
    axes[0].bar(x, y, color=[colors["candidate"] if i == 11 else "#94a3b8" for i in x], width=.8)
    axes[0].set(xlim=(.3, 25.7), ylim=(0, .7), xticks=[1, 5, 10, 15, 20, 25],
                xlabel="Training step", ylabel="Loss", title="Each step uses a different example")
    axes[0].text(11, y[10] + .025, "Example 0", ha="center", color="#92400e", fontsize=11)
    fixed = [summary["fixed_row_loss"][k] for k in ("before", "after", "reloaded")]
    fixed_bars = axes[1].bar(range(3), fixed, color=[colors["original"], colors["candidate"], colors["candidate"]], width=.62)
    fixed_bars[2].set_hatch("//")
    fixed_bars[2].set_edgecolor("#92400e")
    axes[1].set(xticks=range(3), xticklabels=["Before\ntraining", "After\ntraining", "Reloaded"],
                ylim=(0, .7), ylabel="Loss", title="Same example: before and after")
    axes[1].tick_params(axis="x", length=0, pad=10)
    for i, value in enumerate(fixed): axes[1].text(i, value + .02, f"{value:.4f}", ha="center")
    for ax in axes: ax.grid(axis="y", alpha=.18); ax.set_axisbelow(True)
    fig.suptitle("Training loss (lower is better)", fontsize=19, fontweight="bold", y=.97)
    fig.tight_layout(rect=(0, .02, 1, .89), w_pad=2.5); save(fig, "training-fit")
    inputs = [{"file": str(p.relative_to(study)), "bytes": p.stat().st_size, "sha256": sha(p)}
              for p in sorted(study.rglob("*")) if p.is_file() and p.suffix in ("csv", ".csv", ".json")]
    provenance = {"schema_version": "uav-vla-lab.research-figures.v1", "validation": result,
                  "renderer": {"file": "tools/render_research_figures.py", "sha256": sha(Path(__file__))},
                  "versions": {"matplotlib": matplotlib.__version__, "numpy": np.__version__, "Pillow": PIL.__version__},
                  "inputs": inputs, "outputs": files,
                  "scope": "Exact public numeric data, standard plotting; no generated scene images, no error bars or significance claims"}
    (output / "figure-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, default=DEFAULT_STUDY)
    parser.add_argument("--output", type=Path, default=DEFAULT_FIGURES)
    parser.add_argument("--check", action="store_true", help="Validate public tables without plotting or writing files")
    args = parser.parse_args()
    if args.check:
        print(json.dumps(validate(args.study)[0]))
    else:
        render(args.study, args.output)


if __name__ == "__main__":
    main()
