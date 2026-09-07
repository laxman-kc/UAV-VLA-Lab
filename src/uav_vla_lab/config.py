"""Strict, versioned input contract for the small synthetic CPU example."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path


class ContractError(ValueError):
    """An input or evidence contract failed; never a navigation outcome."""


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(text, label="input"):
    try:
        return json.loads(text,
                          object_pairs_hook=_unique_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              ContractError(f"Non-finite JSON value: {value}")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"Invalid JSON: {label}") from exc


def read_json(path):
    try:
        return parse_json(Path(path).read_text(encoding="utf-8"), Path(path).name)
    except UnicodeError as exc:
        raise ContractError(f"Invalid UTF-8 JSON: {Path(path).name}") from exc


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def exact_keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ContractError(f"{label} requires exactly: {', '.join(sorted(keys))}")


def number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{label} must be a finite number")
    if abs(value) > 1_000_000:
        raise ContractError(f"{label} exceeds the synthetic example's numeric bounds")
    if not math.isfinite(value):
        raise ContractError(f"{label} must be a finite number")
    return float(value)


def validate_replay(value):
    exact_keys(value, {"schema_version", "source_kind", "example_id", "description",
                       "coordinate_frame", "initial_state", "actions"}, "replay input")
    if value["schema_version"] != "vla.synthetic-replay.v1" or value["source_kind"] != "synthetic":
        raise ContractError("Only vla.synthetic-replay.v1 with source_kind=synthetic is supported")
    if value["coordinate_frame"] != "local_ned_metres_yaw_radians":
        raise ContractError("Unsupported coordinate frame")
    if not isinstance(value["example_id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", value["example_id"]):
        raise ContractError("example_id must be a short lowercase identifier")
    if not isinstance(value["description"], str) or not 1 <= len(value["description"]) <= 2000:
        raise ContractError("description must contain 1–2000 characters")
    state = value["initial_state"]
    exact_keys(state, {"x", "y", "z", "yaw"}, "initial_state")
    for key, item in state.items():
        number(item, f"initial_state.{key}")
    actions = value["actions"]
    if not isinstance(actions, list) or not 1 <= len(actions) <= 10_000:
        raise ContractError("actions must contain 1–10000 records")
    for index, action in enumerate(actions):
        exact_keys(action, {"forward", "down", "yaw_delta"}, f"actions[{index}]")
        for key, item in action.items():
            number(item, f"actions[{index}].{key}")
    return value
