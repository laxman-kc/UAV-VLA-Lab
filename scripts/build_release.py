#!/usr/bin/env python3
"""Package actual phase evidence; optionally render a disclosed evidence replay.

Reports and integrity verification use only Python's standard library. Video
rendering additionally needs Pillow, ffmpeg with libx264, and ffprobe. No command
from an input specification is executed. See docs/runbooks/releases.md.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import html
import io
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap


VERSION = "1"
ENGINEERING = {"planned", "running", "passed", "failed", "blocked"}
CHECK_RESULTS = {"pass", "fail", "not_applicable", "blocked", "not_run"}
DISCLOSURES = {
    "terminal_log": "Recorded log excerpts; editorial holds; not live screen capture.",
    "observations": "Sampled observations; assigned display durations, not real-time playback.",
}
# Fixed acceptance bounds for decoded repetitions of a reviewed decoded frame.
# These permit minor H.264 reconstruction variation, not unreviewed motion.
STATIC_FRAME_TOLERANCES = {"mean_absolute_channel_error": 1.0,
                           "fraction_channels_error_over_16": 0.0001}
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\b(?:hf_|ghp_|github_pat_|sk-)[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\b(?:authorization\s*[:=]\s*bearer)\s+[A-Za-z0-9._~-]{12,}"),
    re.compile(r'''(?i)["']?(?:password|api_key|access_token|secret_key|client_secret)["']?\s*[:=]\s*["']?([^\s,"';}]+)'''),
]


class ReleaseError(ValueError):
    """An invalid input or unverifiable artifact; never an experiment outcome."""


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def check_no_secrets(text, label):
    """Reject common credential forms; this is not an exhaustive privacy audit."""
    for pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            if match.lastindex and match.group(1).lower() in {"null", "none", "unknown", "redacted", "[redacted]", "<redacted>"}:
                continue
            raise ReleaseError(f"Possible credential in {label}; supply a reviewed, sanitized export (value not printed)")


def read_json(path):
    text = Path(path).read_text(encoding="utf-8")
    check_no_secrets(text, Path(path).name)
    try:
        return json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ReleaseError(f"Non-finite JSON number: {value}")))
    except json.JSONDecodeError as exc:
        raise ReleaseError(f"Invalid JSON in {Path(path).name}: line {exc.lineno}") from exc


def existing_file(value, base):
    if not isinstance(value, str) or not value:
        raise ReleaseError("Expected an explicit input file path")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = Path(base) / candidate
    if not candidate.is_file():
        raise ReleaseError(f"Missing input file: {candidate}")
    return candidate.resolve()


def packaged_file(root, value):
    """Resolve a portable bundle member without permitting traversal/symlinks."""
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise ReleaseError(f"Non-portable artifact path: {value}")
    root = Path(root).resolve()
    current = root
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            raise ReleaseError(f"Symlink is not a packaged artifact: {value}")
    if not current.is_file():
        raise ReleaseError(f"Missing packaged artifact: {value}")
    return current


def copy_evidence(source, out, target=None):
    source = Path(source)
    data = source.read_bytes()
    if source.suffix.lower() in {".json", ".jsonl", ".csv", ".txt", ".log", ".yaml", ".yml", ".md", ".sh"}:
        check_no_secrets(data.decode("utf-8"), source.name)
    digest = hashlib.sha256(data).hexdigest()
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", source.name)
    relative = target or f"evidence/inputs/{digest[:16]}-{name}"
    destination = Path(out) / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and sha256(destination) != digest:
        raise ReleaseError(f"Conflicting packaged evidence: {relative}")
    destination.write_bytes(data)
    return relative


def normalize_checks(raw, base, out):
    checks = raw.get("checks") if isinstance(raw, dict) else raw
    if not isinstance(checks, list) or not checks:
        raise ReleaseError("Checks must be a nonempty JSON list, or an object containing checks")
    normalized = []
    seen = set()
    for index, item in enumerate(checks):
        if not isinstance(item, dict):
            raise ReleaseError("Each check must be an object")
        check_id = str(item.get("id", f"check-{index + 1}"))
        if check_id in seen:
            raise ReleaseError(f"Duplicate check ID: {check_id}")
        seen.add(check_id)
        result = item.get("result", item.get("status"))
        result = {"passed": "pass", "failed": "fail", "not applicable": "not_applicable"}.get(result, result)
        if result not in CHECK_RESULTS:
            raise ReleaseError(f"Invalid check result for {check_id}: {result}")
        refs = item.get("evidence", item.get("evidence_refs", []))
        refs = [refs] if isinstance(refs, str) else refs
        if not isinstance(refs, list):
            raise ReleaseError(f"Evidence references must be paths: {check_id}")
        timestamp = item.get("timestamp", item.get("timestamp_utc"))
        if result in {"pass", "fail"} and (not refs or not timestamp):
            raise ReleaseError(f"Measured check {check_id} needs timestamp and evidence")
        normalized.append({
            "id": check_id, "criterion": item.get("criterion", item.get("name", check_id)),
            "result": result, "timestamp": timestamp,
            "evidence": [copy_evidence(existing_file(ref, base), out) for ref in refs],
            "reason": item.get("reason", item.get("detail", "")),
        })
    return normalized


def srt_time(seconds, separator=","):
    millis = round(float(seconds) * 1000)
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    seconds, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def event_frame_count(seconds, fps):
    try:
        count = Decimal(str(seconds)) * fps
    except (InvalidOperation, TypeError) as exc:
        raise ReleaseError("Invalid display_seconds") from exc
    if not count.is_finite() or count <= 0 or count != count.to_integral_value():
        raise ReleaseError("display_seconds must be positive and represent a whole number of output frames")
    return int(count)


def prepare_video(video, base, out):
    if not isinstance(video, dict) or video.get("kind") not in DISCLOSURES:
        raise ReleaseError("video.kind must be terminal_log or observations")
    if not video.get("selection_rule") or not video.get("events"):
        raise ReleaseError("Video requires an explicit selection_rule and actual events")
    fps = video.get("fps", 10)
    if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 60:
        raise ReleaseError("Video fps must be an integer from 1 to 60")
    events, cursor, seen = [], 0, set()
    for index, original in enumerate(video["events"]):
        event = dict(original)
        event_id = str(event.get("id", f"event-{index + 1}"))
        if event_id in seen:
            raise ReleaseError(f"Duplicate video event ID: {event_id}")
        seen.add(event_id)
        count = event_frame_count(event.get("display_seconds"), fps)
        if not isinstance(event.get("caption"), str) or not event["caption"].strip():
            raise ReleaseError(f"Video event needs an explicit caption: {event_id}")
        source = existing_file(event.get("source"), base)
        source_ref = copy_evidence(source, out)
        row = {key: event.get(key) for key in (
            "run_id", "episode_id", "attempt_id", "observation_id", "camera", "camera_timestamp",
            "simulator_timestamp", "host_timestamp", "checkpoint_id", "map_id", "mission_id",
            "task_mode", "requested_action", "applied_action", "termination_reason", "caption",
        )}
        row.update(id=event_id, source=source_ref, source_sha256=sha256(source), start_frame=cursor,
                   frame_count=count, end_frame_exclusive=cursor + count,
                   output_start_seconds=cursor / fps, output_end_seconds=(cursor + count) / fps,
                   display_seconds=count / fps)
        if video["kind"] == "terminal_log":
            text = source.read_text(encoding="utf-8")
            check_no_secrets(text, source.name)
            lines = text.splitlines(keepends=True)
            first, last = event.get("first_line", 1), event.get("last_line", len(lines))
            if any(isinstance(n, bool) or not isinstance(n, int) for n in (first, last)) or not 1 <= first <= last <= len(lines):
                raise ReleaseError(f"Invalid inclusive log line selection: {event_id}")
            excerpt = "".join(lines[first - 1:last])
            excerpt_ref = f"video/excerpts/{index:04d}.txt"
            (Path(out) / excerpt_ref).parent.mkdir(parents=True, exist_ok=True)
            (Path(out) / excerpt_ref).write_text(excerpt, encoding="utf-8")
            row.update(first_line=first, last_line=last, excerpt=excerpt_ref,
                       excerpt_sha256=sha256(Path(out) / excerpt_ref))
        else:
            for key in ("run_id", "attempt_id", "observation_id", "camera"):
                if not row[key]:
                    raise ReleaseError(f"Observation event {event_id} needs {key}")
            # Native saved PNG/JPEG files are RGB images; no raw BGR reinterpretation.
            if source.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                raise ReleaseError("Observations must be saved PNG/JPEG images")
        events.append(row)
        cursor += count
    population = video.get("population_ref")
    if video["kind"] == "observations" and not population:
        raise ReleaseError("Observation selection requires population_ref for the complete attempt population")
    selection = {
        "kind": video["kind"], "rule": video["selection_rule"],
        "population_ref": copy_evidence(existing_file(population, base), out) if population else None,
        "timeline_domain": "editorial_display_time", "fps": fps, "frame_count": cursor,
        "duration_seconds": cursor / fps, "disclosure": DISCLOSURES[video["kind"]],
        "timing_limitations": [
            "Display durations are assigned; source timestamps are retained without interpolation.",
            "Every event is held for its mapped output frames. Cuts occur between selected events.",
            "Omitted observations/log lines are described by the selection rule and source ranges.",
            "Playback FPS does not establish camera rate, policy frequency, or simulator speed.",
            "Missing camera timestamps stay null; host/simulator timestamps do not replace them.",
        ],
        "events": events,
    }
    if video["kind"] == "observations" and any(e["camera_timestamp"] is None for e in events):
        selection["disclosure"] = "Sampled observations; elapsed timing unavailable. Editorial holds, not real-time."
        selection["timing_limitations"].append("Sampled observations; elapsed timing unavailable for frames without camera timestamps.")
    write_json(Path(out) / "video/selection.json", selection)
    return selection


def write_mapping_and_captions(out, selection):
    fields = ["output_frame", "output_pts_seconds", "event_id", "source", "source_sha256",
              "excerpt_sha256", "first_line", "last_line", "run_id", "episode_id", "attempt_id",
              "observation_id", "camera", "camera_timestamp", "simulator_timestamp", "host_timestamp"]
    with (Path(out) / "video/frames.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for event in selection["events"]:
            for frame in range(event["start_frame"], event["end_frame_exclusive"]):
                row = {key: event.get(key) for key in fields}
                row.update(output_frame=frame, output_pts_seconds=f"{frame / selection['fps']:.9f}", event_id=event["id"])
                writer.writerow(row)
    srt, vtt = [], ["WEBVTT\n"]
    for index, event in enumerate(selection["events"], 1):
        caption = event["caption"].replace("\r", " ").strip()
        caption += "\n" + selection["disclosure"]
        srt.append(f"{index}\n{srt_time(event['output_start_seconds'])} --> {srt_time(event['output_end_seconds'])}\n{caption}\n")
        vtt.append(f"{srt_time(event['output_start_seconds'], '.')} --> {srt_time(event['output_end_seconds'], '.')}\n{html.escape(caption)}\n")
    (Path(out) / "video/captions.srt").write_text("\n".join(srt), encoding="utf-8")
    (Path(out) / "video/captions.vtt").write_text("\n".join(vtt), encoding="utf-8")


def load_fonts(font_file=None):
    try:
        from PIL import ImageFont
    except ImportError as exc:
        raise ReleaseError("Video rendering requires Pillow; reports and --verify do not") from exc
    candidates = [font_file] if font_file else [
        "/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationMono-Regular.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return ({size: ImageFont.truetype(candidate, size) for size in (18, 20, 24, 30, 34)},
                    {"file": Path(candidate).name, "sha256": sha256(candidate)})
    return ({size: ImageFont.load_default(size=size) for size in (18, 20, 24, 30, 34)}, {"file": "Pillow default", "sha256": None})


def wrapped(draw, text, font, width):
    lines = []
    for paragraph in str(text).splitlines() or [""]:
        current = ""
        # Preserve the source characters, wrapping rather than truncating long words.
        for character in paragraph.expandtabs(4):
            if current and draw.textlength(current + character, font=font) > width:
                lines.append(current)
                current = ""
            current += character
        lines.append(current)
    return lines


def render_slide(out, spec, selection, event, fonts, destination):
    from PIL import Image, ImageDraw, ImageOps

    canvas = Image.new("RGB", (1280, 720), "#101827")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 1280, 8), fill="#55d6be")
    title = f"{spec['phase_id']} / {spec['release_id']}"
    draw.text((40, 23), title, fill="#55d6be", font=fonts[24])
    title_lines = wrapped(draw, spec["title"], fonts[30], 1190)
    if len(title_lines) > 1:
        raise ReleaseError("Video title too long; use a concise title, objective belongs in report")
    draw.text((40, 60), title_lines[0], fill="white", font=fonts[30])
    draw.text((40, 106), selection["disclosure"], fill="#cbd5e1", font=fonts[18])
    if selection["kind"] == "terminal_log":
        excerpt = (Path(out) / event["excerpt"]).read_text(encoding="utf-8")
        # No terminal emulation: ANSI is not rendered as control codes or animation.
        text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", excerpt)
        text = "".join(c if c in "\n\r\t" or ord(c) >= 32 else "�" for c in text)
        lines = wrapped(draw, text, fonts[20], 1160)
        if len(lines) > 16:
            raise ReleaseError(f"Log event {event['id']} exceeds 16 rendered lines; split it into explicit events")
        draw.rounded_rectangle((32, 145, 1248, 590), radius=10, fill="#060c15", outline="#364152")
        source_label = f"{Path(event['source']).name} | source lines {event['first_line']}–{event['last_line']}"
        draw.text((52, 158), source_label, fill="#94a3b8", font=fonts[18])
        for index, line in enumerate(lines):
            draw.text((52, 192 + index * 24), line, fill="#e2e8f0", font=fonts[20])
    else:
        with Image.open(Path(out) / event["source"]) as original:
            if getattr(original, "n_frames", 1) != 1:
                raise ReleaseError("Animated observations are not supported")
            image = original.convert("RGB")
            event["source_dimensions"] = list(image.size)
            event["color_handling"] = "Decoded saved image to RGB; aspect ratio preserved; no enhancement"
            fitted = ImageOps.contain(image, (770, 440), method=Image.Resampling.BICUBIC)
            canvas.paste(fitted, (34 + (770 - fitted.width) // 2, 145 + (440 - fitted.height) // 2))
        details = [f"Map: {event['map_id'] or 'unavailable'}", f"Mission: {event['mission_id'] or event['episode_id'] or 'unavailable'}",
                   f"Attempt: {event['attempt_id']}", f"Observation: {event['observation_id']}", f"Camera: {event['camera']}",
                   f"Checkpoint: {event['checkpoint_id'] or 'unavailable'}", f"Task: {event['task_mode'] or 'unavailable'}",
                   f"Camera time: {event['camera_timestamp'] if event['camera_timestamp'] is not None else 'unavailable'}",
                   f"Requested: {json.dumps(event['requested_action'])}", f"Applied: {json.dumps(event['applied_action'])}",
                   f"Termination: {event['termination_reason'] or 'unavailable'}"]
        lines = wrapped(draw, "\n".join(details), fonts[18], 420)
        if len(lines) > 20:
            raise ReleaseError(f"Observation {event['id']} has too much telemetry for readable video; shorten IDs/caption")
        for index, line in enumerate(lines):
            draw.text((830, 145 + index * 22), line, fill="#e2e8f0", font=fonts[18])
    caption_lines = wrapped(draw, event["caption"], fonts[20], 1190)
    if len(caption_lines) > 3:
        raise ReleaseError(f"Caption too long for event {event['id']}")
    for index, line in enumerate(caption_lines):
        draw.text((40, 605 + index * 24), line, fill="white", font=fonts[20])
    draw.text((40, 687), f"Event {event['id']} · assigned hold {event['display_seconds']:g}s · full evidence: report.html",
              fill="#94a3b8", font=fonts[18])
    canvas.save(destination, "PNG")
    return canvas.tobytes()


def execute(command, cwd=None):
    return subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def render_video(out, spec, selection, font_file=None):
    out = Path(out)
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise ReleaseError("Video rendering requires ffmpeg and ffprobe on PATH")
    encoders = execute([ffmpeg, "-hide_banner", "-encoders"])
    if encoders.returncode or not re.search(r"\blibx264\b", encoders.stdout):
        raise ReleaseError("This renderer requires FFmpeg's libx264 encoder")
    fonts, font_info = load_fonts(font_file)
    version = execute([ffmpeg, "-version"])
    (out / "video/encoder-version.txt").write_text(version.stdout + version.stderr, encoding="utf-8")
    (out / "video/slides").mkdir()
    command = [ffmpeg, "-hide_banner", "-y", "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", "1280x720",
               "-framerate", str(selection["fps"]), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-threads", "2", "video/demo.mp4"]
    with (out / "video/encode.log").open("wb") as log:
        process = subprocess.Popen(command, cwd=out, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
        try:
            for index, event in enumerate(selection["events"]):
                slide = out / f"video/slides/{index:04d}.png"
                pixels = render_slide(out, spec, selection, event, fonts, slide)
                event["slide"] = slide.relative_to(out).as_posix()
                event["slide_sha256"] = sha256(slide)
                for _ in range(event["frame_count"]):
                    process.stdin.write(pixels)
            process.stdin.close()
            returncode = process.wait()
        except BaseException:
            process.kill()
            process.wait()
            raise
    if returncode:
        raise ReleaseError(f"FFmpeg encoding failed ({returncode}); inspect video/encode.log")
    write_json(out / "video/selection.json", selection)
    probe_command = [ffprobe, "-v", "error", "-count_frames", "-show_format", "-show_streams", "-of", "json", "video/demo.mp4"]
    probe = execute(probe_command, out)
    (out / "video/ffprobe.json").write_text(probe.stdout, encoding="utf-8")
    (out / "video/ffprobe.log").write_text(probe.stderr, encoding="utf-8")
    decode_command = [ffmpeg, "-v", "error", "-xerror", "-i", "video/demo.mp4", "-f", "null", "-"]
    decoded = execute(decode_command, out)
    (out / "video/decode.log").write_text(decoded.stderr, encoding="utf-8")
    if probe.returncode or decoded.returncode:
        raise ReleaseError("Encoded video failed probe/decode validation; evidence retained")
    metadata = json.loads(probe.stdout)
    stream = next((stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "video"), {})
    checks = {
        "codec_h264": stream.get("codec_name") == "h264",
        "dimensions_1280x720": (stream.get("width"), stream.get("height")) == (1280, 720),
        "frame_count_matches_mapping": int(stream.get("nb_read_frames", -1)) == selection["frame_count"],
        "duration_matches_mapping": abs(float(metadata.get("format", {}).get("duration", -1)) - selection["duration_seconds"]) <= 1 / selection["fps"],
        "full_decode_passed": decoded.returncode == 0,
    }
    validation = {"timestamp": utc_now(), "programmatic_status": "passed" if all(checks.values()) else "failed",
                  "checks": checks, "encode_returncode": returncode, "probe_returncode": probe.returncode,
                  "decode_returncode": decoded.returncode, "commands": [command, probe_command, decode_command],
                  "font": font_info, "video_sha256": sha256(out / "video/demo.mp4"),
                  "visual_review": {"status": "not_run", "reason": "Requires actual review tied to video SHA256"}}
    write_json(out / "video/validation.json", validation)
    if not all(checks.values()):
        raise ReleaseError("Video metadata disagrees with event mapping; inspect video/validation.json")
    return validation


def md_value(value):
    if value is None:
        return "Unavailable"
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(markdown):
    """Small safe rendering of this generator's Markdown; no raw HTML execution."""
    blocks, paragraph, code, in_code, table = [], [], [], False, []

    def inline(text):
        escaped = html.escape(text)
        def link(match):
            label, target = match.group(1), html.unescape(match.group(2))
            if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target) and not target.startswith(("https://", "http://")):
                return label
            return f'<a href="{html.escape(target, quote=True)}">{label}</a>'
        return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, escaped)

    def flush():
        if paragraph:
            blocks.append("<p>" + inline(" ".join(paragraph)) + "</p>")
            paragraph.clear()
        if table:
            rows = []
            for index, line in enumerate(table):
                if re.match(r"^\|?\s*:?-", line):
                    continue
                cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
                tag = "th" if index == 0 else "td"
                rows.append("<tr>" + "".join(f"<{tag}>" + inline(c.strip().replace("\\|", "|")) + f"</{tag}>" for c in cells) + "</tr>")
            blocks.append("<table>" + "".join(rows) + "</table>")
            table.clear()

    for line in markdown.splitlines():
        if line.startswith("```"):
            flush()
            if in_code:
                blocks.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
                code.clear()
            in_code = not in_code
        elif in_code:
            code.append(line)
        elif line.startswith("|"):
            if paragraph:
                blocks.append("<p>" + inline(" ".join(paragraph)) + "</p>")
                paragraph.clear()
            table.append(line)
        elif line.startswith("#"):
            flush()
            level = min(len(line) - len(line.lstrip("#")), 6)
            blocks.append(f"<h{level}>" + inline(line[level:].strip()) + f"</h{level}>")
        elif not line.strip():
            flush()
        elif line.startswith("- "):
            flush()
            blocks.append("<p class=bullet>• " + inline(line[2:]) + "</p>")
        else:
            paragraph.append(line)
    flush()
    return "\n".join(blocks)


def create_reports(out, spec, checks, artifact_status):
    out = Path(out)
    rows = ["| Criterion | Result | Evidence | Reason |", "|---|---|---|---|"]
    for check in checks:
        refs = ", ".join(f"[{Path(ref).name}]({ref})" for ref in check["evidence"]) or "Unavailable"
        rows.append(f"| {md_value(check['criterion'])} | {check['result']} | {refs} | {md_value(check['reason'])} |")
    findings = []
    for finding in spec.get("findings", []):
        if not isinstance(finding, dict) or finding.get("kind") not in {"measured", "source_fact", "interpretation", "proposed", "unavailable"}:
            raise ReleaseError("Findings require kind (measured/source_fact/interpretation/proposed/unavailable) and text")
        findings.append(f"- {finding['kind']}: {finding.get('text', '')}")
    limits = [f"- {item}" for item in spec.get("limitations", [])]
    limits += [f"- Unknown: {item}" for item in spec.get("unknowns", [])]
    selection_path = out / "video/selection.json"
    video_text = "Video was not rendered; artifact verification remains incomplete."
    if selection_path.exists():
        selection = read_json(selection_path)
        video_text = selection["disclosure"] + "\n\n" + "\n".join(f"- {item}" for item in selection["timing_limitations"])
        video_text += "\n\n[Selection and original timing](video/selection.json) · [Output-frame mapping](video/frames.csv) · [Captions](video/captions.srt)"
        if (out / "video/demo.mp4").exists():
            video_text += " · [Evidence video](video/demo.mp4) · [Video validation](video/validation.json)"
        review_path = out / "video/visual-review.json"
        if review_path.exists():
            review = read_json(review_path)
            method = ("Every static evidence segment was visually inspected; all encoded frames and their timing were checked programmatically. Continuous playback was not attested."
                      if review.get("review_kind") == "all_static_segments" else "The reviewer attested reviewing the entire video.")
            video_text += "\n\n" + method + " [Review method, coverage and evidence](video/visual-review.json)"
    measurements = json.dumps(spec.get("measurements", {"status": "unavailable", "reason": "No measurements supplied"}), indent=2, ensure_ascii=False)
    source = json.dumps(spec.get("source", {}), indent=2, ensure_ascii=False)
    report = f"""# {spec['phase_id']} — {spec['title']}

Release: {spec['release_id']}. Generated: {spec['created_at_utc']}.

Engineering: {spec['engineering_status']}. Research: {spec['research_status']}. Artifacts: {artifact_status}.

## Objective and scope

{spec['objective']}

## Method and provenance

{spec.get('method', 'Method is documented by the supplied reproduction commands and source evidence.')}

```json
{source}
```

[Host inventory](evidence/host-inventory.json) · [Resolved configuration](config.resolved.yaml) · [Release manifest](manifest.json) · [Runbook](RUNBOOK.md)

## Acceptance evidence

{chr(10).join(rows)}

[Machine-readable checks](evidence/checks.json) · [Attempt accounting](evidence/runs.csv)

## Measurements

Null values are unavailable, not zero. Measurements below are supplied evidence; this renderer does not infer experiment success.

```json
{measurements}
```

## Findings

{chr(10).join(findings) or 'No additional findings supplied.'}

## Limitations and unknowns

{chr(10).join(limits) or 'No limitations supplied; this omission must be reviewed before release verification.'}

## Media and reproducibility

{video_text}

The video is an editorial replay of packaged evidence. It is not proof of unrecorded actions or a real-time screen recording. Raw evidence remains separately hashed. Programmatic integrity does not verify the scientific truth of supplied claims.

## Next decision

{spec.get('next_decision', 'Unavailable — no next decision supplied.')}
"""
    (out / "REPORT.md").write_text(report, encoding="utf-8")
    player = ""
    if (out / "video/demo.mp4").exists():
        player = '<video controls preload="metadata"><source src="video/demo.mp4" type="video/mp4"><track kind="captions" src="video/captions.vtt" srclang="en" label="Evidence captions" default></video>'
    page = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>""" + html.escape(spec["title"]) + """</title><style>
body{font:17px/1.65 system-ui,sans-serif;margin:0;background:#f4f6f9;color:#192338}main{max-width:1080px;margin:40px auto;background:white;padding:42px;border-top:6px solid #157d73}h1{font-size:2rem;line-height:1.2}h2{margin-top:2rem;color:#125d56}a{color:#075e99}pre{overflow:auto;white-space:pre-wrap;background:#101827;color:#edf2fa;padding:20px;border-radius:6px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;vertical-align:top;border-bottom:1px solid #d8dfe8;padding:10px;overflow-wrap:anywhere}video{width:100%;background:#101827;margin-top:20px}.bullet{margin:.4rem 0}@media(max-width:700px){main{margin:0;padding:22px}table{display:block;overflow:auto}}
</style><main>""" + render_markdown(report) + player + "</main></html>\n"
    (out / "report.html").write_text(page, encoding="utf-8")
    commands = spec["commands"]
    command_text = "\n\n".join(f"```sh\n{command}\n```" for command in commands)
    runbook = f"# {spec['release_id']} runbook\n\n## Prerequisites\n\n" + "\n".join(f"- {item}" for item in spec.get("prerequisites", []))
    runbook += f"\n\n## Recorded reproduction commands\n\nCommands are supplied by the experiment owner; the packaging tool did not execute them.\n\n{command_text}\n\n## Expected evidence\n\nInspect evidence/checks.json and the linked raw files. Do not treat an exit code alone as a mission outcome.\n\n## Interruption and cleanup\n\n{spec.get('interruption_handling', 'Not supplied; consult the phase runbook before executing.') }\n\n{spec.get('cleanup', 'No cleanup command supplied.')}\n\n## Artifact verification\n\n```sh\npython3 scripts/build_release.py --verify <release-directory>\n```\n\n[Report](REPORT.md) · [Manifest](manifest.json)\n"
    (out / "RUNBOOK.md").write_text(runbook, encoding="utf-8")
    (out / "README.md").write_text(f"# {spec['phase_id']} — {spec['title']}\n\nRelease: {spec['release_id']}\n\nEngineering: {spec['engineering_status']}. Research: {spec['research_status']}. Artifacts: {artifact_status}.\n\n{spec['objective']}\n\n[Report](REPORT.md) · [Browsable report](report.html) · [Runbook](RUNBOOK.md) · [Manifest](manifest.json)\n\n{video_text.split(chr(10))[0]}\n\nLimitations: {'; '.join(spec.get('limitations', [])) or 'Not supplied'}\n", encoding="utf-8")


def file_inventory(out, exclude=()):
    inventory = []
    for path in sorted(Path(out).rglob("*")):
        if path.is_symlink():
            raise ReleaseError(f"Symlinks cannot be sealed: {path.name}")
        if path.is_file():
            relative = path.relative_to(out).as_posix()
            if relative not in exclude:
                inventory.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)})
    return inventory


def write_manifest_and_hashes(out, spec, status="incomplete"):
    out = Path(out)
    video = read_json(out / "video/selection.json") if (out / "video/selection.json").exists() else {}
    manifest = {
        "schema_version": VERSION, "is_template": False, "phase_id": spec["phase_id"], "release_id": spec["release_id"],
        "generator": {"file": "scripts/build_release.py", "sha256": sha256(__file__), "python_version": sys.version},
        "created_at_utc": spec["created_at_utc"], "engineering_status": spec["engineering_status"],
        "research_status": spec["research_status"], "artifact_status": status, "source": spec.get("source", {}),
        "host_inventory_ref": "evidence/host-inventory.json", "resolved_config_sha256": sha256(out / "config.resolved.yaml"),
        "acceptance_checks_ref": "evidence/checks.json", "workload": spec.get("workload"),
        "video": {"file": "video/demo.mp4" if (out / "video/demo.mp4").exists() else None,
                  "evidence_type": video.get("kind"), "selection_manifest_ref": "video/selection.json" if video else None,
                  "frame_or_clip_mapping_ref": "video/frames.csv" if video else None,
                  "timeline_domain": video.get("timeline_domain"),
                  "validation_ref": "video/validation.json" if (out / "video/validation.json").exists() else None},
        "unknowns": spec.get("unknowns", []), "limitations": spec.get("limitations", []),
        "artifact_inventory_exclusions": ["manifest.json", "checksums.sha256"],
        "notes": ["Manifest is hashed by checksums.sha256. The checksum file cannot hash itself.",
                  "Hashes detect changes; they are not signatures or proof of scientific correctness."],
        "artifacts": file_inventory(out, {"manifest.json", "checksums.sha256"}),
    }
    write_json(out / "manifest.json", manifest)
    hashes = file_inventory(out, {"checksums.sha256"})
    (out / "checksums.sha256").write_text("".join(f"{row['sha256']}  {row['path']}\n" for row in hashes), encoding="utf-8")


def validate_review_coverage(review, selection, video_hash):
    required = ("reviewer", "timestamp", "notes", "video_sha256")
    if any(not isinstance(review.get(key), str) or not review[key].strip() for key in required) or review.get("status") != "passed":
        raise ReleaseError("Review needs reviewer, timestamp, notes, video hash and status=passed")
    if review["video_sha256"] != video_hash:
        raise ReleaseError("Visual review is for a different video")
    kind = review.get("review_kind", "full_video")  # Preserve existing full-playback attestations.
    if kind == "full_video":
        if review.get("reviewed_entire_video") is not True:
            raise ReleaseError("Full-video review requires reviewed_entire_video=true")
        return kind
    if kind != "all_static_segments" or selection["kind"] != "terminal_log":
        raise ReleaseError("all_static_segments review is restricted to terminal_log videos")
    if (review.get("reviewed_entire_video") is not False or review.get("reviewed_all_static_segments") is not True or
            review.get("frame_mapping_verified") is not True):
        raise ReleaseError("Static review must declare complete segment/mapping review and reviewed_entire_video=false")
    evidence = review.get("review_evidence", [])
    if not isinstance(evidence, list) or not evidence or any(not isinstance(item, dict) for item in evidence):
        raise ReleaseError("Static review requires the actual inspected review evidence and hashes")
    evidence_ids = [item.get("id") for item in evidence]
    if any(not isinstance(value, str) or not value for value in evidence_ids) or len(set(evidence_ids)) != len(evidence_ids):
        raise ReleaseError("Review evidence IDs must be nonempty and unique")
    for item in evidence:
        if not isinstance(item.get("path"), str) or not re.fullmatch(r"[a-f0-9]{64}", str(item.get("sha256", ""))):
            raise ReleaseError("Review evidence requires a file path and SHA256")
    segments = review.get("segments", [])
    expected = {event["id"]: event for event in selection["events"]}
    if (not isinstance(segments, list) or any(not isinstance(item, dict) for item in segments) or
            len(segments) != len(expected) or {item.get("event_id") for item in segments} != set(expected)):
        raise ReleaseError("Static review must cover every selection event ID exactly once")
    for segment in segments:
        event = expected[segment["event_id"]]
        additional = segment.get("additional_frames", [])
        if not isinstance(additional, list) or any(not isinstance(item, dict) for item in additional):
            raise ReleaseError("Additional reviewed frames must be explicit reference objects")
        seen_frames = set()
        for reference in [segment, *additional]:
            frame = reference.get("output_frame")
            refs = reference.get("review_evidence_ids")
            if isinstance(frame, bool) or not isinstance(frame, int) or not event["start_frame"] <= frame < event["end_frame_exclusive"] or frame in seen_frames:
                raise ReleaseError("Reviewed decoded frame falls outside its mapped event or is duplicated")
            seen_frames.add(frame)
            if not isinstance(refs, list) or not refs or not all(ref in evidence_ids for ref in refs):
                raise ReleaseError("Each reference must identify the actual inspected review evidence")
            if not isinstance(reference.get("decoded_frame"), str) or not re.fullmatch(r"[a-f0-9]{64}", str(reference.get("decoded_frame_sha256", ""))):
                raise ReleaseError("Each segment requires a decoded reference frame and SHA256")
    return kind


def validate_static_video(out, review, base):
    selection = read_json(packaged_file(out, "video/selection.json"))
    validate_review_coverage(review, selection, sha256(packaged_file(out, "video/demo.mp4")))
    proof = measure_static_video(out, review["segments"], review["review_evidence"], review["video_sha256"], base)
    if proof["status"] != "passed":
        raise ReleaseError("Unreviewed changing content or excessive reconstruction error: " + json.dumps(proof["failed_frame_checks"][:3]))
    return proof


def measure_static_video(out, segments, review_evidence, expected_video_sha256, base):
    """Decode all video frames; bind reviewed references, intervals and timing.

    This measures pixel coverage only. The named reviewer supplies the visual
    assessment of text, captions and report consistency; no playback is claimed.
    Nothing is written into the release until the complete check passes.
    """
    try:
        from PIL import Image, ImageChops
    except ImportError as exc:
        raise ReleaseError("Static video coverage validation requires Pillow") from exc
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise ReleaseError("Static video coverage validation requires ffmpeg and ffprobe")
    out = Path(out)
    selection = read_json(packaged_file(out, "video/selection.json"))
    video = packaged_file(out, "video/demo.mp4")
    if selection["kind"] != "terminal_log" or sha256(video) != expected_video_sha256:
        raise ReleaseError("Static-content measurement requires the identified terminal-log video")
    for item in review_evidence:
        if sha256(existing_file(item["path"], base)) != item["sha256"]:
            raise ReleaseError("Inspected review evidence hash mismatch")
    references = {}
    for segment in segments:
        references[segment["event_id"]] = []
        for item in [segment, *segment.get("additional_frames", [])]:
            path = existing_file(item["decoded_frame"], base)
            if sha256(path) != item["decoded_frame_sha256"]:
                raise ReleaseError("Decoded reference frame hash mismatch")
            with Image.open(path) as opened:
                if getattr(opened, "n_frames", 1) != 1 or opened.size != (1280, 720):
                    raise ReleaseError("Static review needs single decoded 1280x720 frames")
                reference = opened.convert("RGB")
            references[segment["event_id"]].append((item, reference, reference.tobytes()))
    probe_command = [ffprobe, "-v", "error", "-show_streams", "-show_frames", "-show_entries",
                     "stream=index,codec_type,width,height:frame=media_type,best_effort_timestamp_time", "-of", "json", str(video)]
    probe = execute(probe_command)
    if probe.returncode:
        raise ReleaseError("Static-review frame/timestamp probe failed")
    metadata = json.loads(probe.stdout)
    streams = metadata.get("streams", [])
    if len(streams) != 1 or streams[0].get("codec_type") != "video" or (streams[0].get("width"), streams[0].get("height")) != (1280, 720):
        raise ReleaseError("Static review requires one silent 1280x720 video stream")
    frames = metadata.get("frames", [])
    if len(frames) != selection["frame_count"] or any(
            item.get("media_type") != "video" or not math.isclose(float(item.get("best_effort_timestamp_time", "nan")), index / selection["fps"], abs_tol=1e-6)
            for index, item in enumerate(frames)):
        raise ReleaseError("Encoded frame timestamps/count differ from the reviewed mapping")
    command = [ffmpeg, "-v", "error", "-xerror", "-i", str(video), "-map", "0:v:0", "-fps_mode", "passthrough",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    measurements, failed_frame_checks = [], []
    frame_bytes = 1280 * 720 * 3
    with tempfile.TemporaryFile() as error_log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=error_log)
        try:
            for event in selection["events"]:
                event_references = references[event["id"]]
                segment = event_references[0][0]
                maxima = {key: 0.0 for key in STATIC_FRAME_TOLERANCES}
                cache, matched_references, used_references = {}, set(), {}
                for index in range(event["start_frame"], event["end_frame_exclusive"]):
                    pixels = process.stdout.read(frame_bytes)
                    if len(pixels) != frame_bytes:
                        raise ReleaseError("Incomplete decoded frame during static-content review")
                    for item, _, reference_bytes in event_references:
                        if index == item["output_frame"]:
                            if pixels != reference_bytes:
                                raise ReleaseError("Reviewed reference pixels do not match the stated encoded frame")
                            matched_references.add(index)
                    digest = hashlib.sha256(pixels).hexdigest()
                    if digest not in cache:
                        candidates = []
                        for item, reference, _ in event_references:
                            histogram = ImageChops.difference(reference, Image.frombytes("RGB", (1280, 720), pixels)).histogram()
                            errors = {
                                "mean_absolute_channel_error": sum((index % 256) * count for index, count in enumerate(histogram)) / frame_bytes,
                                "fraction_channels_error_over_16": sum(count for index, count in enumerate(histogram) if index % 256 > 16) / frame_bytes,
                            }
                            candidates.append((errors, item["output_frame"]))
                            if all(errors[key] <= value for key, value in STATIC_FRAME_TOLERANCES.items()):
                                break
                        cache[digest] = min(candidates, key=lambda candidate: max(candidate[0][key] / value for key, value in STATIC_FRAME_TOLERANCES.items()))
                    errors, reference_frame = cache[digest]
                    used_references[reference_frame] = used_references.get(reference_frame, 0) + 1
                    for key, value in errors.items():
                        maxima[key] = max(maxima[key], value)
                        if value > STATIC_FRAME_TOLERANCES[key]:
                            failed_frame_checks.append({"event_id": event["id"], "output_frame": index, "metric": key, "measured": value, "limit": STATIC_FRAME_TOLERANCES[key]})
                measurements.append({"event_id": event["id"], "start_frame": event["start_frame"],
                                     "end_frame_exclusive": event["end_frame_exclusive"], "frames_compared": event["frame_count"],
                                     "reference_output_frame": segment["output_frame"], "reference_file_sha256": segment["decoded_frame_sha256"],
                                     "reference_pixels_matched": segment["output_frame"] in matched_references, "maximum_errors": maxima,
                                     "frames_assigned_to_reference": used_references,
                                     "additional_references": [{"output_frame": item["output_frame"], "file_sha256": item["decoded_frame_sha256"],
                                                                 "pixels_matched": item["output_frame"] in matched_references} for item, _, _ in event_references[1:]]})
            if process.stdout.read(1):
                raise ReleaseError("Encoded file contains frames outside the reviewed mapping")
            process.stdout.close()
            returncode = process.wait()
            error_log.seek(0)
            decode_log = error_log.read().decode("utf-8", errors="replace")
            if returncode:
                raise ReleaseError("Full static-content decode failed")
        except BaseException:
            process.kill()
            process.wait()
            process.stdout.close()
            raise
    return {"schema_version": 1, "method": "every_decoded_rgb_frame_vs_reviewed_segment_reference_v1", "timestamp": utc_now(),
            "status": "failed" if failed_frame_checks else "passed", "failed_frame_checks": failed_frame_checks,
            "video_sha256": sha256(video), "selection_sha256": sha256(out / "video/selection.json"),
            "frames_csv_sha256": sha256(out / "video/frames.csv"), "frame_count": len(frames), "frames_compared": sum(item["frames_compared"] for item in measurements),
            "tolerances": STATIC_FRAME_TOLERANCES, "segments": measurements, "probe_returncode": probe.returncode,
            "decode_returncode": returncode, "decode_log": decode_log, "commands": [probe_command, command],
            "encoded_frame_pts_seconds": [float(item["best_effort_timestamp_time"]) for item in frames],
            "limitations": "Pixel agreement is bounded by the recorded lossy reconstruction tolerances. This programmatic measurement does not itself attest visual review or continuous playback."}


def verify_static_review(out, review, selection):
    proof = read_json(packaged_file(out, review.get("static_content_validation_ref", "")))
    if (proof.get("status") != "passed" or proof.get("video_sha256") != review["video_sha256"] or
            proof.get("selection_sha256") != sha256(packaged_file(out, "video/selection.json")) or
            proof.get("frames_csv_sha256") != sha256(packaged_file(out, "video/frames.csv")) or
            proof.get("frame_count") != selection["frame_count"] or proof.get("frames_compared") != selection["frame_count"] or
            proof.get("decode_returncode") != 0 or proof.get("probe_returncode") != 0 or proof.get("tolerances") != STATIC_FRAME_TOLERANCES or proof.get("failed_frame_checks") or
            proof.get("method") != "every_decoded_rgb_frame_vs_reviewed_segment_reference_v1"):
        raise ReleaseError("Static review coverage is not bound to the complete encoded content and mapping")
    pts = proof.get("encoded_frame_pts_seconds", [])
    if len(pts) != selection["frame_count"] or any(not isinstance(value, (int, float)) or not math.isclose(value, index / selection["fps"], abs_tol=1e-6) for index, value in enumerate(pts)):
        raise ReleaseError("Static review does not cover all encoded presentation timestamps")
    for item in review["review_evidence"]:
        if sha256(packaged_file(out, item["path"])) != item["sha256"]:
            raise ReleaseError("Packaged visual-review evidence hash mismatch")
    proof_segments = {item["event_id"]: item for item in proof.get("segments", [])}
    if len(proof_segments) != len(selection["events"]) or len(proof.get("segments", [])) != len(selection["events"]):
        raise ReleaseError("Static-content validation omits or duplicates a segment")
    events = {event["id"]: event for event in selection["events"]}
    for segment in review["segments"]:
        item = proof_segments.get(segment["event_id"], {})
        event = events[segment["event_id"]]
        if (sha256(packaged_file(out, segment["decoded_frame"])) != segment["decoded_frame_sha256"] or
                item.get("reference_file_sha256") != segment["decoded_frame_sha256"] or
                item.get("reference_output_frame") != segment["output_frame"] or item.get("reference_pixels_matched") is not True or
                any(item.get(key) != event[key] for key in ("start_frame", "end_frame_exclusive")) or item.get("frames_compared") != event["frame_count"] or
                any(not isinstance(item.get("maximum_errors", {}).get(key), (int, float)) or not 0 <= item["maximum_errors"][key] <= value for key, value in STATIC_FRAME_TOLERANCES.items())):
            raise ReleaseError("Static review reference or full-segment comparison mismatch")
        additional = segment.get("additional_frames", [])
        expected_additional = [{"output_frame": ref["output_frame"], "file_sha256": ref["decoded_frame_sha256"], "pixels_matched": True} for ref in additional]
        if item.get("additional_references", []) != expected_additional:
            raise ReleaseError("Additional inspected references disagree with decoded content validation")
        for ref in additional:
            if sha256(packaged_file(out, ref["decoded_frame"])) != ref["decoded_frame_sha256"]:
                raise ReleaseError("Additional inspected reference file hash mismatch")
        assignments = item.get("frames_assigned_to_reference", {})
        allowed = {str(ref["output_frame"]) for ref in [segment, *additional]}
        if set(assignments) - allowed or any(not isinstance(count, int) or count < 1 for count in assignments.values()) or sum(assignments.values()) != event["frame_count"]:
            raise ReleaseError("Decoded frames are not fully assigned to inspected references")


def verify_release(out):
    out = Path(out).resolve()
    for required in ("README.md", "RUNBOOK.md", "REPORT.md", "report.html", "config.resolved.yaml",
                     "evidence/host-inventory.json", "evidence/checks.json", "evidence/runs.csv"):
        packaged_file(out, required)
    manifest = read_json(packaged_file(out, "manifest.json"))
    if manifest["artifact_status"] == "verified" and not manifest["video"]["file"]:
        raise ReleaseError("Verified release is missing video evidence")
    checksums = packaged_file(out, "checksums.sha256").read_text(encoding="utf-8")
    expected = {}
    for line in checksums.splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  (.+)", line)
        if not match or match.group(2) in expected or match.group(2) == "checksums.sha256":
            raise ReleaseError("Invalid or duplicate checksum entry")
        expected[match.group(2)] = match.group(1)
    actual = {row["path"]: row["sha256"] for row in file_inventory(out, {"checksums.sha256"})}
    if actual != expected:
        changed = sorted(set(actual) ^ set(expected) | {path for path in actual.keys() & expected.keys() if actual[path] != expected[path]})
        raise ReleaseError("Integrity mismatch: " + ", ".join(changed))
    inventory = {row["path"]: row for row in manifest["artifacts"]}
    if len(inventory) != len(manifest["artifacts"]) or set(inventory) != set(actual) - {"manifest.json"}:
        raise ReleaseError("Manifest artifact inventory is incomplete or duplicated")
    for relative, row in inventory.items():
        path = packaged_file(out, relative)
        if sha256(path) != row["sha256"] or path.stat().st_size != row["bytes"]:
            raise ReleaseError(f"Manifest hash/size mismatch: {relative}")
    checks = read_json(packaged_file(out, manifest["acceptance_checks_ref"]))["checks"]
    for check in checks:
        for ref in check["evidence"]:
            packaged_file(out, ref)
    if manifest["video"]["selection_manifest_ref"]:
        selection = read_json(packaged_file(out, "video/selection.json"))
        with packaged_file(out, "video/frames.csv").open(encoding="utf-8", newline="") as handle:
            rows = iter(csv.DictReader(handle))
            cursor = 0
            for event in selection["events"]:
                source = packaged_file(out, event["source"])
                if sha256(source) != event["source_sha256"] or event["start_frame"] != cursor:
                    raise ReleaseError("Source hash or event continuity mismatch")
                if event["frame_count"] != event["end_frame_exclusive"] - event["start_frame"]:
                    raise ReleaseError("Inconsistent event frame interval")
                if "excerpt" in event:
                    excerpt = packaged_file(out, event["excerpt"])
                    selected = "".join(source.read_text(encoding="utf-8").splitlines(keepends=True)[event["first_line"]-1:event["last_line"]])
                    if excerpt.read_text(encoding="utf-8") != selected or sha256(excerpt) != event["excerpt_sha256"]:
                        raise ReleaseError("Log excerpt does not match source lines")
                for frame in range(event["start_frame"], event["end_frame_exclusive"]):
                    row = next(rows, None)
                    if row is None or row["output_frame"] != str(frame) or row["event_id"] != event["id"] or row["source_sha256"] != event["source_sha256"] or row["source"] != event["source"]:
                        raise ReleaseError("Video frame-to-source mapping mismatch")
                    if not math.isclose(float(row["output_pts_seconds"]), frame / selection["fps"], abs_tol=1e-8):
                        raise ReleaseError("Video presentation timestamp mismatch")
                    for key in ("excerpt_sha256", "first_line", "last_line", "run_id", "episode_id", "attempt_id",
                                "observation_id", "camera", "camera_timestamp", "simulator_timestamp", "host_timestamp"):
                        expected_value = "" if event.get(key) is None else str(event[key])
                        if row[key] != expected_value:
                            raise ReleaseError(f"Video event provenance mismatch: {key}")
                cursor = event["end_frame_exclusive"]
            if next(rows, None) is not None or cursor != selection["frame_count"]:
                raise ReleaseError("Unexpected video mapping frame count")
        if manifest["video"]["file"]:
            validation = read_json(packaged_file(out, "video/validation.json"))
            if validation["programmatic_status"] != "passed" or validation["video_sha256"] != sha256(packaged_file(out, manifest["video"]["file"])):
                raise ReleaseError("Video validation or hash mismatch")
            if manifest["artifact_status"] == "verified":
                review = validation["visual_review"]
                kind = validate_review_coverage(review, selection, validation["video_sha256"])
                if read_json(packaged_file(out, "video/visual-review.json")) != review:
                    raise ReleaseError("Visual-review records disagree")
                if kind == "all_static_segments":
                    verify_static_review(out, review, selection)
    return {"status": "passed", "artifact_status": manifest["artifact_status"], "files_verified": len(actual),
            "release_id": manifest["release_id"], "note": "Integrity verification; not a new experiment or scientific validation"}


def build_release(spec_path, output, render=False, font_file=None):
    spec_path, out = Path(spec_path).resolve(), Path(output).resolve()
    if out.exists():
        raise ReleaseError("Output directory already exists; choose a new release ID/directory")
    spec = read_json(spec_path)
    for key in ("phase_id", "release_id", "title", "objective", "engineering_status", "research_status", "inventory", "checks", "resolved_config"):
        if not isinstance(spec.get(key), str) or not spec[key].strip():
            raise ReleaseError(f"Missing explicit specification field: {key}")
    for key in ("phase_id", "release_id"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", spec[key]):
            raise ReleaseError(f"Invalid {key}")
    if spec["engineering_status"] not in ENGINEERING:
        raise ReleaseError("Unknown engineering_status")
    if not isinstance(spec.get("commands"), list) or not all(isinstance(command, str) for command in spec["commands"]):
        raise ReleaseError("commands must be a list of recorded command strings (possibly empty for blocked phase)")
    base = spec_path.parent
    inputs = {key: existing_file(spec[key], base) for key in ("inventory", "checks", "resolved_config")}
    read_json(inputs["inventory"])
    raw_checks = read_json(inputs["checks"])
    out.mkdir(parents=True)
    try:
        spec["created_at_utc"] = utc_now()
        copy_evidence(inputs["inventory"], out, "evidence/host-inventory.json")
        copy_evidence(inputs["resolved_config"], out, "config.resolved.yaml")
        copy_evidence(inputs["checks"], out, "evidence/checks.original.json")
        checks = normalize_checks(raw_checks, inputs["checks"].parent, out)
        if spec["engineering_status"] == "passed" and any(check["result"] not in {"pass", "not_applicable"} for check in checks):
            raise ReleaseError("Engineering passed conflicts with non-passing acceptance checks")
        write_json(out / "evidence/checks.json", {"checks": checks})
        if spec.get("runs"):
            copy_evidence(existing_file(spec["runs"], base), out, "evidence/runs.csv")
        elif spec.get("non_episode_phase") is True:
            (out / "evidence/runs.csv").write_text("phase_id,trial_id,attempt_id,outcome,reason\n" + f"{spec['phase_id']},,,not_applicable,Non-episode phase; no mission trials claimed\n", encoding="utf-8")
        else:
            raise ReleaseError("Supply runs.csv or explicitly set non_episode_phase=true")
        for ref in spec.get("attachments", []):
            copy_evidence(existing_file(ref, base), out)
        selection = None
        if spec.get("video"):
            selection = prepare_video(spec["video"], base, out)
            write_mapping_and_captions(out, selection)
            if render:
                render_video(out, spec, selection, font_file)
        elif render:
            raise ReleaseError("--render-video requires video events backed by actual files")
        # Repack paths so the exported specification references only bundled files.
        spec.update(inventory="evidence/host-inventory.json", checks="evidence/checks.json", resolved_config="config.resolved.yaml", runs="evidence/runs.csv")
        spec.pop("attachments", None)
        spec["video"] = selection
        write_json(out / "evidence/release-spec.json", spec)
        create_reports(out, spec, checks, "incomplete")
        write_manifest_and_hashes(out, spec)
        return verify_release(out)
    except BaseException as exc:
        # Retain failed encoding/check evidence, but never leave it looking verified.
        write_json(out / "BUILD_FAILED.json", {"status": "failed", "timestamp": utc_now(), "error_type": type(exc).__name__, "reason": str(exc)})
        raise


def finalize_release(output, review_path):
    out = Path(output).resolve()
    verify_release(out)
    manifest = read_json(out / "manifest.json")
    if manifest["artifact_status"] == "verified":
        raise ReleaseError("Release is already sealed; publish a new release for corrections")
    review = read_json(review_path)
    video = packaged_file(out, "video/demo.mp4")
    selection = read_json(packaged_file(out, "video/selection.json"))
    review["review_kind"] = validate_review_coverage(review, selection, sha256(video))
    spec = read_json(out / "evidence/release-spec.json")
    checks = read_json(out / "evidence/checks.json")["checks"]
    source = spec.get("source", {})
    if not spec.get("limitations") or not (source.get("project_commit") or source.get("working_tree_files")):
        raise ReleaseError("Sealing requires explicit limitations and a project commit or exact working-tree file hashes")
    if review["review_kind"] == "all_static_segments":
        base = Path(review_path).resolve().parent
        proof = validate_static_video(out, review, base)
        for item in review["review_evidence"]:
            item["path"] = copy_evidence(existing_file(item["path"], base), out)
        for segment in review["segments"]:
            for reference in [segment, *segment.get("additional_frames", [])]:
                reference["decoded_frame"] = copy_evidence(existing_file(reference["decoded_frame"], base), out)
        review["static_content_validation_ref"] = "video/static-content-validation.json"
        write_json(out / review["static_content_validation_ref"], proof)
    validation = read_json(out / "video/validation.json")
    validation["visual_review"] = review
    write_json(out / "video/visual-review.json", review)
    write_json(out / "video/validation.json", validation)
    create_reports(out, spec, checks, "verified")
    write_manifest_and_hashes(out, spec, "verified")
    return verify_release(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--spec", type=Path, help="Actual release input JSON; file paths are relative to its directory")
    group.add_argument("--verify", type=Path, help="Verify a packaged draft or sealed release without modifying it")
    group.add_argument("--finalize", type=Path, help="Seal a draft once after an actual video review")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--render-video", action="store_true")
    parser.add_argument("--font-file", type=Path)
    parser.add_argument("--visual-review", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.verify:
            result = verify_release(args.verify)
        elif args.finalize:
            if not args.visual_review:
                parser.error("--finalize requires --visual-review")
            result = finalize_release(args.finalize, args.visual_review)
        else:
            if not args.output:
                parser.error("--spec requires --output")
            result = build_release(args.spec, args.output, args.render_video, args.font_file)
        print(json.dumps(result, indent=2))
        return 0
    except (ReleaseError, OSError, KeyError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
