"""Deterministic CPU kinematics and inspectable reports, explicitly synthetic."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import json
import math
from pathlib import Path
import shutil

from . import __version__
from .config import ContractError, exact_keys, parse_json, read_json, validate_replay, write_json
from .provenance import file_record, sha256, verify_record


DISCLOSURE = ("Synthetic mathematical point replay; no camera images, learned policy, "
              "simulator, collision model, physical timing or navigation-success claim.")
RULE = "Rotate yaw first, then translate body-forward in XY and down in Z; one logical index per action."
MEMBERS = {"input.json", "config.json", "events.jsonl", "metrics.json", "REPORT.md", "report.html", "trace.svg"}
SOURCE_MEMBERS = ("__init__.py", "config.py", "provenance.py", "replay.py")


def producer_receipt():
    package = Path(__file__).parent
    return {"package": "uav-vla-lab", "version": __version__,
            "source_files": [file_record(package / name, relative_to=package) for name in SOURCE_MEMBERS]}


def calculate(spec):
    validate_replay(spec)
    state = {key: float(value) for key, value in spec["initial_state"].items()}
    events = [{"event_id": 1, "event_type": "state", "step": 0, "state": state.copy()}]
    distance = 0.0
    for step, action in enumerate(spec["actions"], 1):
        prior = events[-1]["event_id"]
        request = len(events) + 1
        events.append({"event_id": request, "event_type": "action", "step": step,
                       "source_state_event_id": prior, "action": action})
        state["yaw"] = math.atan2(math.sin(state["yaw"] + action["yaw_delta"]),
                                  math.cos(state["yaw"] + action["yaw_delta"]))
        state["x"] += action["forward"] * math.cos(state["yaw"])
        state["y"] += action["forward"] * math.sin(state["yaw"])
        state["z"] += action["down"]
        distance += math.hypot(action["forward"], action["down"])
        events.append({"event_id": len(events) + 1, "event_type": "state", "step": step,
                       "action_event_id": request, "state": state.copy()})
    metrics = {"schema_version": "vla.synthetic-metrics.v1", "source_kind": "synthetic",
               "action_count": len(spec["actions"]), "state_count": len(spec["actions"]) + 1,
               "logical_path_length_metres": distance, "final_state": state,
               "navigation_success": None, "physical_elapsed_seconds": None}
    return events, metrics


def trace_svg(events):
    points = [event["state"] for event in events if event["event_type"] == "state"]
    xs, ys = [point["x"] for point in points], [point["y"] for point in points]
    scale = 300 / max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    coords = [(70 + (point["x"] - min(xs)) * scale, 390 - (point["y"] - min(ys)) * scale) for point in points]
    polyline = " ".join(f"{x:.3f},{y:.3f}" for x, y in coords)
    grouped = {}
    for index, (x, y) in enumerate(coords):
        grouped.setdefault((round(x, 3), round(y, 3)), []).append(str(index))
    labels = "".join(f'<circle cx="{x:.3f}" cy="{y:.3f}" r="4" fill="#116677"/>'
                     f'<text x="{x + 7:.3f}" y="{y - 7:.3f}">{",".join(indices)}</text>'
                     for (x, y), indices in grouped.items())
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 470" role="img" '
            f'aria-label="Synthetic XY path; labels are logical step indices">'
            f'<rect width="640" height="470" fill="#f6f8fa"/>'
            f'<g font-family="sans-serif" font-size="15" fill="#25313d">'
            f'<text x="24" y="30">SYNTHETIC CPU REPLAY — XY projection</text>'
            f'<text x="24" y="54">No simulator, policy, physical time or flight outcome</text>'
            f'<polyline points="{polyline}" fill="none" stroke="#116677" stroke-width="3"/>'
            f'{labels}<text x="24" y="446">+X →   +Y ↑   Numbers: logical action indices</text></g></svg>\n')


def report_text(spec, metrics, input_hash):
    state = metrics["final_state"]
    description = escape(spec["description"])
    summary = (f"{metrics['action_count']} logical actions; {metrics['state_count']} states; "
               f"mathematical path length {metrics['logical_path_length_metres']:.6f} m.")
    markdown = (f"# Synthetic replay: {spec['example_id']}\n\n{DISCLOSURE}\n\n"
                f"{description}\n\n{summary}\n\n"
                f"Final state: `{json.dumps(state, sort_keys=True)}`.\n\n"
                f"Transition rule: {RULE}\n\n"
                f"[XY trace](trace.svg) · [Events](events.jsonl) · [Metrics](metrics.json) · "
                f"[Input](input.json) · [Configuration](config.json)\n\n"
                f"Input SHA256: `{input_hash}`.\n\n"
                "Integrity checks detect changes relative to this bundle's manifest; they do not authenticate its author.\n")
    html = (f'<!doctype html><html lang="en"><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>Synthetic replay: {spec["example_id"]}</title>'
            f'<style>body{{max-width:900px;margin:3rem auto;padding:0 1rem;font:17px/1.6 system-ui;color:#24313d}}'
            f'aside{{background:#fff1cf;padding:1rem}}img{{width:100%}}code{{overflow-wrap:anywhere}}</style>'
            f'<h1>Synthetic replay: {spec["example_id"]}</h1><aside>{DISCLOSURE}</aside>'
            f'<p>{description}</p><p>{summary}</p>'
            f'<img src="trace.svg" alt="Synthetic XY path, labeled by logical action index">'
            f'<p>Final state: <code>{escape(json.dumps(state, sort_keys=True))}</code></p><p>{RULE}</p>'
            f'<p><a href="events.jsonl">Events</a> · <a href="metrics.json">Metrics</a> · '
            f'<a href="input.json">Input</a> · <a href="config.json">Configuration</a></p>'
            f'<p>Input SHA256: <code>{input_hash}</code></p>'
            f'<p>Manifest agreement verifies integrity, not authorship or real flight.</p></html>\n')
    return markdown, html


def run_replay(input_path, output):
    input_path, output = Path(input_path), Path(output)
    spec = validate_replay(read_json(input_path))
    events, metrics = calculate(spec)
    input_hash = sha256(input_path)
    # Validate all input before creating an attempt. Existing attempts are immutable.
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(input_path, output / "input.json")
    write_json(output / "config.json", {"schema_version": "vla.synthetic-config.v1",
               "source_kind": "synthetic", "example_id": spec["example_id"],
               "coordinate_frame": spec["coordinate_frame"], "transition_rule": RULE,
               "input_sha256": input_hash})
    (output / "events.jsonl").write_text("".join(json.dumps(event, allow_nan=False) + "\n" for event in events), encoding="utf-8")
    write_json(output / "metrics.json", metrics)
    (output / "trace.svg").write_text(trace_svg(events), encoding="utf-8")
    markdown, html = report_text(spec, metrics, input_hash)
    (output / "REPORT.md").write_text(markdown, encoding="utf-8")
    (output / "report.html").write_text(html, encoding="utf-8")
    manifest = {"schema_version": "vla.replay-bundle.v1", "source_kind": "synthetic",
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "producer": producer_receipt(),
                "disclosure": DISCLOSURE,
                "files": [file_record(output / name, relative_to=output) for name in sorted(MEMBERS)]}
    write_json(output / "manifest.json", manifest)
    return verify_bundle(output)


def verify_bundle(root):
    root = Path(root)
    if (root / "manifest.json").is_symlink():
        raise ContractError("Manifest must not be a symlink")
    manifest = read_json(root / "manifest.json")
    exact_keys(manifest, {"schema_version", "source_kind", "created_at_utc", "producer", "disclosure", "files"}, "manifest")
    if manifest["schema_version"] != "vla.replay-bundle.v1" or manifest["source_kind"] != "synthetic" or manifest["disclosure"] != DISCLOSURE:
        raise ContractError("Not a supported, explicitly synthetic replay bundle")
    if manifest["producer"] != producer_receipt():
        raise ContractError("Producer source differs from this installation; use the recorded implementation to verify this replay")
    try:
        timestamp = datetime.fromisoformat(manifest["created_at_utc"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Timezone required")
    except (AttributeError, TypeError, ValueError) as exc:
        raise ContractError("Manifest creation time must be timezone-aware ISO 8601") from exc
    if not isinstance(manifest["files"], list):
        raise ContractError("Manifest files must be a list")
    paths = [record.get("path") for record in manifest["files"] if isinstance(record, dict)]
    if len(paths) != len(MEMBERS) or set(paths) != MEMBERS:
        raise ContractError("Replay bundle inventory is incomplete or duplicated")
    for record in manifest["files"]:
        verify_record(root, record)
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() or path.is_symlink()}
    if actual != MEMBERS | {"manifest.json"}:
        raise ContractError("Unexpected or missing files in replay bundle")
    spec = validate_replay(read_json(root / "input.json"))
    expected_events, expected_metrics = calculate(spec)
    actual_events = [parse_json(line, "event JSONL") for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    canonical = lambda value: json.dumps(value, sort_keys=True, allow_nan=False)
    if canonical(actual_events) != canonical(expected_events) or canonical(read_json(root / "metrics.json")) != canonical(expected_metrics):
        raise ContractError("Events or metrics contradict the recorded synthetic input")
    input_hash = sha256(root / "input.json")
    expected_config = {"schema_version": "vla.synthetic-config.v1", "source_kind": "synthetic",
                       "example_id": spec["example_id"], "coordinate_frame": spec["coordinate_frame"],
                       "transition_rule": RULE, "input_sha256": input_hash}
    if read_json(root / "config.json") != expected_config:
        raise ContractError("Configuration contradicts the source input")
    expected_markdown, expected_html = report_text(spec, expected_metrics, input_hash)
    for name, expected in (("REPORT.md", expected_markdown), ("report.html", expected_html), ("trace.svg", trace_svg(expected_events))):
        if (root / name).read_text(encoding="utf-8") != expected:
            raise ContractError(f"Report contradicts the replay: {name}")
    return {"status": "verified", "source_kind": "synthetic", "files_verified": len(MEMBERS),
            "metrics": expected_metrics, "disclosure": DISCLOSURE,
            "integrity_scope": "Self-contained file integrity and synthetic replay consistency; not source authenticity."}
