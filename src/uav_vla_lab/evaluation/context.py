"""Report context separated from frozen numerical scoring and reset gates."""
from __future__ import annotations


def evaluation_context(plan: dict, role: str = "unspecified", split: str | None = None) -> dict:
    if role not in {"original", "candidate", "unspecified"}:
        raise ValueError("Explicit original, candidate or unspecified role required")
    trials = plan.get("trials", [])
    split_values = [t["split"] for t in trials if "split" in t]
    if split_values and len(split_values) != len(trials) and "split_group" not in plan:
        raise ValueError("Partial trial split declarations cannot label a whole cohort")
    if "split_group" in plan:
        split_values.append(plan["split_group"])
    if any(value not in ("demo", "development", "holdout") for value in split_values):
        raise ValueError("Unsupported frozen evaluation split declaration")
    declared = set(split_values)
    if len(declared) > 1:
        raise ValueError("Mixed split declarations cannot label a single-cohort report")
    recorded_split = next(iter(declared), None)
    if split is not None and recorded_split is not None and split != recorded_split:
        raise ValueError("Requested split contradicts the frozen plan")
    if split is not None and split not in {"demo", "development", "holdout"}:
        raise ValueError("Unsupported evaluation split")
    declared_role = plan.get("model_role", plan.get("configuration", {}).get("model_role"))
    if declared_role is not None and declared_role not in ("original", "candidate", "unspecified"):
        raise ValueError("Unsupported frozen model role")
    if declared_role is not None and role != "unspecified" and role != declared_role:
        raise ValueError("Requested role contradicts the frozen plan")
    return {"role": declared_role or role, "split": recorded_split or split or "unspecified",
            "role_basis": "frozen_plan" if declared_role else "caller_declaration" if role != "unspecified" else "unrecorded",
            "split_basis": "frozen_plan" if recorded_split else "caller_declaration" if split else "unrecorded",
            "checkpoint_id": plan.get("configuration", {}).get("checkpoint_id"),
            "limitation": "Display context does not establish split membership or checkpoint provenance; the paired-plan validator checks those contracts."}


def scope_limitations(context: dict) -> list[str]:
    return [f"Descriptive {context['split']} evaluation of the declared {context['role']} arm under its named runtime/reset protocol; not a reproduction of an untouched evaluator.",
            "This single-arm analysis does not establish improvement, causality or an unseen-scene result. Checkpoint identity is retained from the frozen plan; no claim of unchanged released weights is inferred.",
            "Project split membership does not establish absence from the released model's prior training; that overlap remains unresolved."]
