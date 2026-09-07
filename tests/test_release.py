"""Integrity and causal media-mapping tests; generated fixtures are not phase evidence."""

import csv
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


MODULE = Path(__file__).resolve().parents[1] / "scripts/build_release.py"
module_spec = importlib.util.spec_from_file_location("build_release", MODULE)
release = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="release-test-")
        self.root = Path(self.temporary.name)
        self.out = self.root / "output"
        self.log = self.root / "check.log"
        self.log.write_text("TEST FIXTURE ONLY\nGPU inventory is unavailable in this test.\nNo remote workload was executed.\n", encoding="utf-8")
        release.write_json(self.root / "inventory.json", {"fixture": True, "gpu": None})
        release.write_json(self.root / "checks.json", {"checks": [{
            "id": "fixture", "criterion": "Fixture integrity, not host readiness",
            "result": "pass", "timestamp": "2026-09-07T00:00:00Z", "evidence": ["check.log"],
        }]})
        (self.root / "config.yaml").write_text("fixture: true\nremote_execution: false\n", encoding="utf-8")
        self.spec = {
            "phase_id": "TEST", "release_id": "fixture-only", "title": "Generator test fixture",
            "objective": "Verify packaging; no experimental result.", "engineering_status": "passed",
            "research_status": "not_applicable", "inventory": "inventory.json", "checks": "checks.json",
            "resolved_config": "config.yaml", "commands": ["python3 -m unittest discover -s tests"],
            "non_episode_phase": True, "source": {"project_commit": "test-fixture-not-a-real-revision"},
            "limitations": ["All input is explicitly identified as test-fixture evidence."],
            "measurements": {"gpu_peak_bytes": None}, "unknowns": ["Real host capacity not measured."],
            "video": {"kind": "terminal_log", "fps": 10, "selection_rule": "Entire three-line test fixture",
                      "events": [{"id": "fixture-a", "source": "check.log", "first_line": 1, "last_line": 2,
                                  "display_seconds": 0.3, "caption": "Test fixture, not research evidence."},
                                 {"id": "fixture-b", "source": "check.log", "first_line": 3, "last_line": 3,
                                  "display_seconds": 0.2, "caption": "No remote execution."}]},
        }

    def tearDown(self):
        self.temporary.cleanup()

    def build(self, render=False):
        release.write_json(self.root / "spec.json", self.spec)
        return release.build_release(self.root / "spec.json", self.out, render)

    def reseal_hashes_for_mapping_test(self):
        # Deliberately recompute integrity hashes: semantic mapping validation must
        # still reject inconsistent IDs/timestamps, beyond detecting file edits.
        saved = release.read_json(self.out / "evidence/release-spec.json")
        release.write_manifest_and_hashes(self.out, saved)

    def static_fixture_review(self):
        # These decoded files and attestations test the gate, never human review.
        selection = release.read_json(self.out / "video/selection.json")
        review = {"reviewer": "synthetic unit-test fixture", "timestamp": "2026-09-07T00:00:00Z",
                  "notes": "Synthetic gate test; no phase evidence or actual visual-review claim.",
                  "video_sha256": release.sha256(self.out / "video/demo.mp4"), "status": "passed",
                  "review_kind": "all_static_segments", "reviewed_entire_video": False,
                  "reviewed_all_static_segments": True, "frame_mapping_verified": True,
                  "segments": [], "review_evidence": []}
        if selection["kind"] == "observations":
            review.update(observation_source_mapping_verified=True, static_holds_only=True)
        for index, event in enumerate(selection["events"]):
            frame = event["start_frame"]
            path = self.root / f"decoded-{index}.png"
            result = subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-y", "-i", str(self.out / "video/demo.mp4"),
                                     "-vf", f"select=eq(n\\,{frame})", "-frames:v", "1", str(path)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            digest = release.sha256(path)
            review["review_evidence"].append({"id": event["id"], "path": str(path), "sha256": digest})
            review["segments"].append({"event_id": event["id"], "output_frame": frame,
                                       "decoded_frame": str(path), "decoded_frame_sha256": digest,
                                       "review_evidence_ids": [event["id"]]})
        return review

    def test_static_review_requires_complete_unique_coverage_and_correct_kind(self):
        self.build()
        selection = release.read_json(self.out / "video/selection.json")
        review = {"reviewer": "fixture", "timestamp": "fixture", "notes": "Fixture only", "video_sha256": "a" * 64,
                  "status": "passed", "review_kind": "all_static_segments", "reviewed_entire_video": False,
                  "reviewed_all_static_segments": True, "frame_mapping_verified": True,
                  "review_evidence": [{"id": "sheet", "path": "fixture.png", "sha256": "b" * 64}],
                  "segments": [{"event_id": "fixture-a", "output_frame": 0, "decoded_frame": "fixture.png",
                                "decoded_frame_sha256": "b" * 64, "review_evidence_ids": ["sheet"]}]}
        with self.assertRaisesRegex(release.ReleaseError, "every selection event"):
            release.validate_review_coverage(review, selection, "a" * 64)
        review["segments"].append(dict(review["segments"][0]))
        with self.assertRaisesRegex(release.ReleaseError, "every selection event"):
            release.validate_review_coverage(review, selection, "a" * 64)
        selection["kind"] = "observations"
        with self.assertRaisesRegex(release.ReleaseError, "explicit source-mapping"):
            release.validate_review_coverage(review, selection, "a" * 64)

    def observation_fixture(self, duration=0.3):
        from PIL import Image
        Image.new("RGB", (80, 40), "#123456").save(self.root / "fixture.png")
        (self.root / "population.csv").write_text("attempt_id,outcome\ntest-1,fixture_only\n")
        self.spec["video"] = {"kind": "observations", "selection_rule": "Only synthetic unit-test image",
                              "population_ref": "population.csv", "fps": 10,
                              "events": [{"id": "image-fixture", "source": "fixture.png", "display_seconds": duration,
                                          "run_id": "test", "attempt_id": "test-1", "observation_id": "test-obs-1",
                                          "camera": "synthetic-fixture", "caption": "Synthetic test image; not simulator footage."}]}

    @unittest.skipUnless(importlib.util.find_spec("PIL") and shutil.which("ffmpeg") and shutil.which("ffprobe"), "Pillow/FFmpeg optional integration prerequisites")
    def test_static_observations_require_origin_mapping_and_seal_without_playback(self):
        self.observation_fixture()
        self.build(render=True)
        selection = release.read_json(self.out / "video/selection.json")
        review = self.static_fixture_review()
        review["observation_source_mapping_verified"] = False
        with self.assertRaisesRegex(release.ReleaseError, "explicit source-mapping"):
            release.validate_static_video(self.out, review, self.root)
        review["observation_source_mapping_verified"] = True
        selection["disclosure"] = "Unrecorded continuous flight"
        with self.assertRaisesRegex(release.ReleaseError, "editorial-hold disclosure"):
            release.validate_review_coverage(review, selection, review["video_sha256"])
        release.write_json(self.root / "review.json", review)
        self.assertEqual(release.finalize_release(self.out, self.root / "review.json")["artifact_status"], "verified")
        proof = release.read_json(self.out / "video/static-content-validation.json")
        self.assertEqual(proof["frames_compared"], 3)
        self.assertEqual(proof["observation_static_origin"]["method"], "exact_reencode_of_builder_static_slides_v1")
        self.assertFalse(release.read_json(self.out / "video/visual-review.json")["reviewed_entire_video"])
        proof["observation_static_origin"]["events"][0]["source_sha256"] = "0" * 64
        release.write_json(self.out / "video/static-content-validation.json", proof)
        saved = release.read_json(self.out / "evidence/release-spec.json")
        release.write_manifest_and_hashes(self.out, saved, "verified")
        with self.assertRaisesRegex(release.ReleaseError, "bound to every original source"):
            release.verify_release(self.out)

    @unittest.skipUnless(importlib.util.find_spec("PIL") and shutil.which("ffmpeg") and shutil.which("ffprobe"), "Pillow/FFmpeg optional integration prerequisites")
    def test_static_observations_reject_dynamic_frame_even_with_an_additional_reference(self):
        from PIL import Image
        self.observation_fixture()
        self.build(render=True)
        selection = release.read_json(self.out / "video/selection.json")
        with Image.open(self.out / selection["events"][0]["slide"]) as image:
            original = image.convert("RGB").tobytes()
        pixels = original + Image.new("RGB", (1280, 720), "#dd00dd").tobytes() + original
        command = release.static_encoding_command(shutil.which("ffmpeg"), 10)
        result = subprocess.run(command, cwd=self.out, input=pixels, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        review = self.static_fixture_review()
        additional = self.root / "dynamic-reference.png"
        result = subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-y", "-i", str(self.out / "video/demo.mp4"),
                                 "-vf", "select=eq(n\\,1)", "-frames:v", "1", str(additional)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        digest = release.sha256(additional)
        review["review_evidence"].append({"id": "dynamic", "path": str(additional), "sha256": digest})
        review["segments"][0]["additional_frames"] = [{"output_frame": 1, "decoded_frame": str(additional),
                                                       "decoded_frame_sha256": digest, "review_evidence_ids": ["dynamic"]}]
        with self.assertRaisesRegex(release.ReleaseError, "arbitrary dynamic footage"):
            release.validate_static_video(self.out, review, self.root)

    def test_portable_bundle_retains_unknowns_and_truthful_status(self):
        result = self.build()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["artifact_status"], "incomplete")
        manifest = release.read_json(self.out / "manifest.json")
        self.assertIsNone(manifest["video"]["file"])
        self.assertIsNone(release.read_json(self.out / "evidence/host-inventory.json")["gpu"])
        self.assertIn('"gpu_peak_bytes": null', (self.out / "REPORT.md").read_text())
        shutil.rmtree(self.root / "does-not-exist", ignore_errors=True)
        self.log.unlink()
        self.assertEqual(release.verify_release(self.out)["status"], "passed")

    def test_tamper_or_extra_file_is_rejected(self):
        self.build()
        (self.out / "REPORT.md").write_text("Unrecorded success claim", encoding="utf-8")
        with self.assertRaisesRegex(release.ReleaseError, "Integrity mismatch"):
            release.verify_release(self.out)

    def test_explicit_line_ranges_and_exact_output_frame_mapping(self):
        self.build()
        with (self.out / "video/frames.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([row["event_id"] for row in rows], ["fixture-a"] * 3 + ["fixture-b"] * 2)
        self.assertEqual([row["output_frame"] for row in rows], list(map(str, range(5))))
        self.assertEqual(rows[-1]["output_pts_seconds"], "0.400000000")
        selection = release.read_json(self.out / "video/selection.json")
        self.assertEqual(selection["duration_seconds"], 0.5)
        self.assertEqual(selection["events"][1]["first_line"], 3)
        self.assertIsNone(selection["events"][0]["camera_timestamp"])
        self.assertIn("not live screen capture", selection["disclosure"])

    def test_mapping_cannot_substitute_nearby_timestamp(self):
        self.build()
        path = self.out / "video/frames.csv"
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            fields, rows = reader.fieldnames, list(reader)
        rows[0]["camera_timestamp"] = "invented-from-host-time"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        self.reseal_hashes_for_mapping_test()
        with self.assertRaisesRegex(release.ReleaseError, "provenance mismatch"):
            release.verify_release(self.out)

    def test_bad_excerpt_and_fractional_frame_duration_rejected(self):
        self.spec["video"]["events"][0]["last_line"] = 99
        with self.assertRaisesRegex(release.ReleaseError, "line selection"):
            self.build()
        self.assertTrue((self.out / "BUILD_FAILED.json").exists())
        self.assertFalse((self.out / "manifest.json").exists())
        with self.assertRaises(release.ReleaseError):
            release.event_frame_count(0.15, 10)

    def test_pass_cannot_hide_failed_check(self):
        checks = release.read_json(self.root / "checks.json")
        checks["checks"][0]["result"] = "fail"
        release.write_json(self.root / "checks.json", checks)
        with self.assertRaisesRegex(release.ReleaseError, "conflicts"):
            self.build()

    def test_no_execution_html_injection_or_credential_export(self):
        self.spec["commands"] = ["touch /tmp/THIS_COMMAND_MUST_NEVER_RUN"]
        self.spec["findings"] = [{"kind": "unavailable", "text": "<script>alert('x')</script>"}]
        self.build()
        page = (self.out / "report.html").read_text()
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("THIS_COMMAND_MUST_NEVER_RUN", (self.out / "REPORT.md").read_text())
        with self.assertRaisesRegex(release.ReleaseError, "Possible credential"):
            release.check_no_secrets('api_key="do-not-export-this-value"', "fixture")

    def test_no_overwrite_or_path_escape(self):
        self.build()
        with self.assertRaisesRegex(release.ReleaseError, "already exists"):
            self.build()
        with self.assertRaisesRegex(release.ReleaseError, "Non-portable"):
            release.packaged_file(self.out, "../check.log")
        (self.out / "symlink").symlink_to(self.log)
        with self.assertRaisesRegex(release.ReleaseError, "Symlink"):
            release.verify_release(self.out)

    @unittest.skipUnless(importlib.util.find_spec("PIL") and shutil.which("ffmpeg") and shutil.which("ffprobe"), "Pillow/FFmpeg optional integration prerequisites")
    def test_actual_video_decode_and_hash_bound_review(self):
        result = self.build(render=True)
        self.assertEqual(result["artifact_status"], "incomplete")
        validation = release.read_json(self.out / "video/validation.json")
        self.assertTrue(all(validation["checks"].values()))
        self.assertEqual(validation["visual_review"]["status"], "not_run")
        # Fixture attestation tests binding semantics only; no actual phase is
        # declared visually reviewed by this test.
        review = {"reviewer": "unit-test fixture", "timestamp": "2026-09-07T00:00:00Z",
                  "notes": "Synthetic test of hash binding; not an experimental visual review.",
                  "video_sha256": "0" * 64, "status": "passed", "reviewed_entire_video": True}
        release.write_json(self.root / "review.json", review)
        with self.assertRaisesRegex(release.ReleaseError, "different video"):
            release.finalize_release(self.out, self.root / "review.json")
        review["video_sha256"] = validation["video_sha256"]
        release.write_json(self.root / "review.json", review)
        self.assertEqual(release.finalize_release(self.out, self.root / "review.json")["artifact_status"], "verified")
        with self.assertRaisesRegex(release.ReleaseError, "already sealed"):
            release.finalize_release(self.out, self.root / "review.json")

    @unittest.skipUnless(importlib.util.find_spec("PIL") and shutil.which("ffmpeg") and shutil.which("ffprobe"), "Pillow/FFmpeg optional integration prerequisites")
    def test_static_review_seals_full_frame_coverage_without_playback_claim(self):
        self.build(render=True)
        review = self.static_fixture_review()
        additional = self.root / "additional.png"
        result = subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-y", "-i", str(self.out / "video/demo.mp4"),
                                 "-vf", "select=eq(n\\,1)", "-frames:v", "1", str(additional)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        digest = release.sha256(additional)
        review["review_evidence"].append({"id": "extra", "path": str(additional), "sha256": digest})
        review["segments"][0]["additional_frames"] = [{"output_frame": 1, "decoded_frame": str(additional),
                                                       "decoded_frame_sha256": digest, "review_evidence_ids": ["extra"]}]
        release.write_json(self.root / "review.json", review)
        self.assertEqual(release.finalize_release(self.out, self.root / "review.json")["artifact_status"], "verified")
        stored = release.read_json(self.out / "video/visual-review.json")
        self.assertIs(stored["reviewed_entire_video"], False)
        proof = release.read_json(self.out / "video/static-content-validation.json")
        self.assertEqual(proof["frames_compared"], 5)
        self.assertEqual(proof["segments"][0]["additional_references"][0]["pixels_matched"], True)
        self.assertEqual(proof["encoded_frame_pts_seconds"], [0.0, 0.1, 0.2, 0.3, 0.4])
        self.assertIn("Continuous playback was not attested", (self.out / "REPORT.md").read_text())
        proof["segments"][0]["frames_compared"] = 1
        release.write_json(self.out / "video/static-content-validation.json", proof)
        spec = release.read_json(self.out / "evidence/release-spec.json")
        release.write_manifest_and_hashes(self.out, spec, "verified")
        with self.assertRaisesRegex(release.ReleaseError, "full-segment comparison"):
            release.verify_release(self.out)

    @unittest.skipUnless(importlib.util.find_spec("PIL") and shutil.which("ffmpeg") and shutil.which("ffprobe"), "Pillow/FFmpeg optional integration prerequisites")
    def test_static_review_rejects_unreviewed_frame_inside_a_segment(self):
        from PIL import Image
        self.build(render=True)
        # Replace the generated test video with a five-frame fixture having a
        # different middle frame; representative frames 0 and 3 remain genuine.
        selection = release.read_json(self.out / "video/selection.json")
        pixels = []
        for index, event in enumerate(selection["events"]):
            with Image.open(self.out / event["slide"]) as opened:
                raw = opened.convert("RGB").tobytes()
            pixels.extend([raw] * event["frame_count"])
        pixels[1] = Image.new("RGB", (1280, 720), "#dd00dd").tobytes()
        result = subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-y", "-f", "rawvideo", "-pixel_format", "rgb24",
                                 "-video_size", "1280x720", "-framerate", "10", "-i", "pipe:0", "-an", "-c:v", "libx264",
                                 "-crf", "20", "-pix_fmt", "yuv420p", str(self.out / "video/demo.mp4")],
                                input=b"".join(pixels), capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        review = self.static_fixture_review()
        with self.assertRaisesRegex(release.ReleaseError, "Unreviewed changing content"):
            release.validate_static_video(self.out, review, self.root)

    @unittest.skipUnless(importlib.util.find_spec("PIL") and shutil.which("ffmpeg") and shutil.which("ffprobe"), "Pillow/FFmpeg optional integration prerequisites")
    def test_observation_replay_retains_source_dimensions_and_identity(self):
        from PIL import Image
        Image.new("RGB", (80, 40), "#123456").save(self.root / "fixture.png")
        (self.root / "population.csv").write_text("attempt_id,outcome\ntest-1,fixture_only\n")
        self.spec["video"] = {"kind": "observations", "selection_rule": "Only synthetic unit-test image",
                              "population_ref": "population.csv", "fps": 10,
                              "events": [{"id": "image-fixture", "source": "fixture.png", "display_seconds": 0.2,
                                          "run_id": "test", "attempt_id": "test-1", "observation_id": "test-obs-1",
                                          "camera": "synthetic-fixture", "caption": "Synthetic test image; not simulator footage."}]}
        self.build(render=True)
        selection = release.read_json(self.out / "video/selection.json")
        self.assertEqual(selection["events"][0]["source_dimensions"], [80, 40])
        self.assertIn("elapsed timing unavailable", selection["disclosure"])
        self.assertIsNone(selection["events"][0]["camera_timestamp"])
        self.assertEqual(release.verify_release(self.out)["status"], "passed")


if __name__ == "__main__":
    unittest.main()
