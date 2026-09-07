"""Synthetic packaging contracts; fixture approvals are never real reviews."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_reviewed_reference_dataset as builder


class ReviewedReferenceTests(unittest.TestCase):
    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2) + "\n")

    def fixture(self, root):
        raw, receipts = root / "raw", root / "receipts"
        receipts.mkdir()
        rows, samples, measured, accepted, episodes = [], [], [], [], []
        for i in range(5):
            trajectory = f"Map/mission-{i}"
            episode = trajectory + "/merged_data.json"
            episodes.append(episode)
            row = {"traj_rel_dir": trajectory, "img_name": "000010.png", "instruction": "<image>\nSynthetic test instruction",
                   "label": {"fwd": .5, "down": 0., "yaw": 0.}, "is_last_step": False, "is_penultimate": False}
            rows.append(row)
            row_hash = builder.source.canonical_hash(row)
            sample_id = f"synthetic-{i}"
            states, logs = [], []
            for frame in range(10, 16):
                state = {"position": [(frame-10)/10, i, -3.], "orientation": [0., 0., 0., 1.]}
                states.append(state)
                path = raw / trajectory / "log" / f"{frame:06d}.json"
                self.write(path, {"frame": frame, "sensors": {"state": state}})
                logs.append(builder.source.file_record(path, raw))
            images = {}
            for stage, frame in (("current", 10), ("future", 15)):
                images[stage] = {}
                for camera, folder in (("front", "frontcamera"), ("down", "downcamera")):
                    path = raw / trajectory / folder / f"{frame:06d}.png"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(f"synthetic-not-real-PNG-{i}-{frame}-{camera}".encode())
                    images[stage][camera] = builder.source.file_record(path, raw)
            identity = {"sample_id": sample_id, "episode_id": episode, "row_sha256": row_hash, "source_row_index": i}
            samples.append({**identity, "row_index": i, "source_row_sha256": row_hash, "split": "train", "images": images["current"], "state_file": logs[0]})
            measured.append({**identity, "alignment_gate_passed": True, "published_label": row["label"], "inferred_label": row["label"],
                             "absolute_residuals": {"fwd": 0., "down": 0., "yaw": 0.}, "current_frame": 10, "future_frame": 15,
                             "consecutive_record_increments": 5, "raw_log_records": logs, "endpoint_images": images,
                             "current_state": states[0], "future_state": states[-1]})
            accepted.append({**identity, "accepted": True})
        split = root / "splits.json"
        self.write(split, {"schema_version": "vla.splits.v1", "upstream_code_revision": builder.source.UPSTREAM_REVISION,
                           "frozen_at_utc": "2020-01-01T00:00:00Z", "map_id": "Map",
                           "groups": {"train": episodes, "development": [], "holdout": [], "demo": []}})
        data = receipts / "rows.json"
        self.write(data, rows)
        prepared = receipts / "prepared.json"
        self.write(prepared, {"schema_version": "vla.published-reference-preparation.v1", "sample_count": 5,
            "publisher": builder.source.PUBLISHED, "official_training_source": builder.source.OFFICIAL_TRAIN,
            "upstream": {"revision": builder.source.UPSTREAM_REVISION}, "created_at_utc": "2020-01-02T00:00:00Z",
            "approval": {"status": "not_asserted"}, "data_json": builder.source.file_record(data),
            "split_manifest": builder.source.file_record(split), "samples": samples})
        audit = receipts / "alignment.json"
        self.write(audit, {"schema_version": builder.alignment.SCHEMA, "status": "alignment_audited_not_approved",
            "approval": "not_asserted", "alignment_gate_passed": True, "record_offset": 5, "tolerance_absolute": 1e-9,
            "expected_count": 5, "finished_at_utc": "2020-01-03T00:00:00Z", "samples": measured,
            "provenance": {"data_json": builder.source.file_record(data), "manifest": builder.source.file_record(prepared),
                           "inputs": {"frozen_split": builder.source.file_record(split),
                                      "published_manifest": {"sha256": builder.source.PUBLISHED["sha256"]},
                                      "official_train_manifest": {"sha256": builder.source.OFFICIAL_TRAIN["sha256"]}}}})
        review = receipts / "review.json"
        self.write(review, {"schema_version": builder.REVIEW_SCHEMA, "status": "approved", "source_kind": "audited_reference_expert",
            "human_review": False, "reviewer": "SYNTHETIC TEST FIXTURE — no actual review", "qualified_scope": "Synthetic contract test only",
            "reviewed_at_utc": "2020-01-04T00:00:00Z", "accepted_samples": accepted,
            "evidence": [builder.source.file_record(audit)],
            "inputs": {"data_json": builder.source.file_record(data), "reference_manifest": builder.source.file_record(prepared),
                       "alignment_report": builder.source.file_record(audit)}})
        part = receipts / "part.json"
        self.write(part, {"schema_version": builder.PART_SCHEMA, "data_json": builder.source.file_record(data),
                         "reference_manifest": builder.source.file_record(prepared), "alignment_report": builder.source.file_record(audit),
                         "independent_review": builder.source.file_record(review)})
        return raw, split, part

    def change_review(self, part, change):
        manifest = builder.source.read_json(part)
        path = Path(manifest["independent_review"]["path"])
        review = builder.source.read_json(path)
        change(review)
        self.write(path, review)
        manifest["independent_review"] = builder.source.file_record(path)
        self.write(part, manifest)

    def test_complete_package_preserves_rows_sources_and_original_training_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, split, part = self.fixture(root)
            result = builder.build([part], raw, split, "P09", root / "out")
            self.assertEqual(result["status"], "packaged_and_contract_validated")
            self.assertEqual(result["sample_count"], 5)
            self.assertFalse(result["semantic_approval_performed_here"])
            self.assertEqual(builder.source.read_json(root / "out/train.json"), builder.source.read_json(root / "receipts/rows.json"))
            self.assertEqual(len(list((root / "out/assets").rglob("*.json"))), 35)
            self.assertEqual(len(list((root / "out/assets").rglob("*.png"))), 20)
            validated = builder.trainer.validate_dataset(root / "out/train.json", root / "out/assets", root / "out/dataset_manifest.json")
            self.assertEqual(validated["status"], "passed")
            self.assertIn("Physical elapsed seconds are unknown", validated["label_policy"]["action_horizon"])

    def test_rejects_missing_semantic_review_without_creating_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, split, part = self.fixture(root)
            self.change_review(part, lambda review: review.update(status="pending"))
            with self.assertRaisesRegex(ValueError, "existing explicit"):
                builder.build([part], raw, split, "P09", root / "out")
            self.assertFalse((root / "out/approval_receipt.json").exists())
            self.assertEqual(builder.source.read_json(root / "out/packaging_report.json")["status"], "packaging_failed")

    def test_rejects_partial_review_and_false_human_claim(self):
        for change in (lambda r: r["accepted_samples"].pop(), lambda r: r.update(human_review=True),
                       lambda r: r["accepted_samples"][0].update(accepted=False)):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                raw, split, part = self.fixture(root)
                self.change_review(part, change)
                with self.assertRaises(ValueError): builder.build([part], raw, split, "P09", root / "out")

    def test_rejects_changed_current_future_image_or_intermediate_state(self):
        for relative in ("frontcamera/000010.png", "downcamera/000015.png", "log/000013.json"):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                raw, split, part = self.fixture(root)
                (raw / "Map/mission-0" / relative).write_bytes(b"changed")
                with self.assertRaises(ValueError): builder.build([part], raw, split, "P09", root / "out")

    def test_rejects_review_that_predates_its_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, split, part = self.fixture(root)
            self.change_review(part, lambda r: r.update(reviewed_at_utc="2020-01-02T00:00:00Z"))
            with self.assertRaisesRegex(ValueError, "Review must follow"):
                builder.build([part], raw, split, "P09", root / "out")

    def test_requires_complete_supporting_review_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, split, part = self.fixture(root)
            extra = root / "independent-calculation.json"
            self.write(extra, {"synthetic": True})
            self.change_review(part, lambda r: r["evidence"].append(builder.source.file_record(extra)))
            with self.assertRaisesRegex(ValueError, "omits supporting"):
                builder.build([part], raw, split, "P09", root / "missing")
            payload = builder.source.read_json(part)
            payload["review_evidence"] = [builder.source.file_record(extra)]
            self.write(part, payload)
            result = builder.build([part], raw, split, "P09", root / "complete")
            self.assertEqual(result["status"], "packaged_and_contract_validated")
            self.assertTrue((root / "complete/evidence/part-00/review-evidence/000-independent-calculation.json").is_file())

    def test_p11_requires_five_plus_twenty_without_overlap(self):
        def part(count, start=0):
            return {"count": count, "candidates": [{"prepared": {"sample_id": str(i), "episode_id": f"Map/{i}/merged_data.json"}} for i in range(start, start+count)]}
        for parts in ([part(5)], [part(5), part(21, 5)], [part(20), part(5)], [part(5), part(20)]):
            with self.assertRaises(ValueError): builder.phase_parts(parts, "P11")

    def test_new_output_required_preserves_previous_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, split, part = self.fixture(root)
            (root / "out").mkdir()
            (root / "out/prior.txt").write_text("keep")
            with self.assertRaises(FileExistsError): builder.build([part], raw, split, "P09", root / "out")
            self.assertEqual((root / "out/prior.txt").read_text(), "keep")

    def test_change_between_validation_and_copy_cannot_replace_reviewed_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, split, part = self.fixture(root)
            original = builder.validate_part
            def mutate_after_validation(*args, **kwargs):
                result = original(*args, **kwargs)
                changed = builder.source.read_json(result["paths"]["independent_review"])
                changed["qualified_scope"] = "Changed after validation"
                self.write(result["paths"]["independent_review"], changed)
                return result
            with mock.patch.object(builder, "validate_part", side_effect=mutate_after_validation):
                with self.assertRaisesRegex(ValueError, "mismatch"):
                    builder.build([part], raw, split, "P09", root / "out")
            self.assertFalse((root / "out/dataset_manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
