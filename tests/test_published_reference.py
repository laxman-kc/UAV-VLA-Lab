"""Synthetic pinned-provenance fixtures; no published data, GPU or real labels used."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / "scripts" / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


reference = load("prepare_published_reference")
training = load("train_adapter_mvp")


class PublishedReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.raw, self.upstream = self.root / "raw", self.root / "upstream"
        self.source, self.official, self.split, self.audit = [self.root / name for name in ("published.json", "official.json", "splits.json", "audit.json")]
        self.output = self.root / "reference-output"
        self.rows, official_rows, episodes = [], [], []
        for number in range(6):
            trajectory = f"FixtureMap/train-{number}"
            episodes.append(trajectory + "/merged_data.json")
            official_rows.append({"json": episodes[-1], "frame": 1})
            for frame in (1, 2):
                name = f"{frame:06d}.png"
                self.rows.append({"traj_rel_dir": trajectory, "img_name": name, "instruction": "Synthetic fixture instruction",
                    "label": {"fwd": float(frame), "down": 0.0, "yaw": 0.1},
                    "is_last_step": frame == 2, "is_penultimate": frame == 1})
                for folder in ("frontcamera", "downcamera"):
                    path = self.raw / trajectory / folder / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(f"Synthetic fixture pixels: {number}/{frame}/{folder}".encode())
                self.write(self.raw / trajectory / "log" / f"{frame:06d}.json", {"synthetic_state_fixture": True})
        rejected = copy.deepcopy(self.rows[0])
        rejected.update(img_name="000003.png", label={"fwd": 6.0, "down": 0.0, "yaw": 0.0})
        self.rows.append(rejected)
        for folder in ("frontcamera", "downcamera"):
            (self.raw / rejected["traj_rel_dir"] / folder / rejected["img_name"]).write_bytes(b"synthetic out-of-range row pixels")
        self.write(self.source, self.rows)
        self.write(self.official, official_rows)
        self.published = {**reference.PUBLISHED, "sha256": reference.digest(self.source), "bytes": self.source.stat().st_size}
        self.official_identity = {**reference.OFFICIAL_TRAIN, "sha256": reference.digest(self.official)}
        self.frozen = {"schema_version": "vla.splits.v1", "split_id": "synthetic-published-reference-split",
            "frozen_at_utc": "2020-01-01T00:00:00+00:00", "map_id": "FixtureMap", "upstream_code_revision": reference.UPSTREAM_REVISION,
            "groups": {"train": episodes, "development": ["FixtureMap/development/merged_data.json"],
                "holdout": ["FixtureMap/holdout/merged_data.json"], "demo": ["FixtureMap/demo/merged_data.json"], "unassigned": []},
            "sources": {"train": {**self.official_identity, "map_rows": 6, "unique_map_episodes": 6}}}
        self.frozen["counts"] = {key: len(value) for key, value in self.frozen["groups"].items()}
        self.write(self.split, self.frozen)
        self.audit_value = {"schema_version": "vla.published-training-audit.v1", "status": "audit_completed_not_label_approval",
            "source": self.published, "split_sha256": reference.digest(self.split), "rows": len(self.rows),
            "project_overlap": {key: {"published_rows": len(self.rows) if key == "train" else 0,
                "represented_episodes": 6 if key == "train" else 0, "declared_episodes": len(value)} for key, value in self.frozen["groups"].items()},
            "selected_map_file_and_schema_audit": {"rows": len(self.rows)}}
        self.write(self.audit, self.audit_value)
        hashes = {}
        for relative in reference.UPSTREAM_FILES:
            path = self.upstream / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Synthetic code identity fixture; not the real upstream reader.\n")
            hashes[relative] = reference.digest(path)
        for name, value in (("PUBLISHED", self.published), ("OFFICIAL_TRAIN", self.official_identity), ("UPSTREAM_FILES", hashes)):
            patcher = patch.object(reference, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def prepare(self, opt_in=True):
        return reference.prepare(self.source, self.official, self.split, self.audit, self.raw, self.upstream, self.output, opt_in=opt_in)

    def validate(self):
        return reference.validate_for_mechanics(self.output / "published_rows.json", self.raw, self.output / "reference_manifest.json")

    def refresh_pins_for_fixture(self):
        self.write(self.source, self.rows)
        self.published.update(sha256=reference.digest(self.source), bytes=self.source.stat().st_size)
        self.audit_value.update(source=self.published, rows=len(self.rows))
        self.audit_value["project_overlap"]["train"]["published_rows"] = len(self.rows)
        self.audit_value["selected_map_file_and_schema_audit"]["rows"] = len(self.rows)
        self.write(self.audit, self.audit_value)

    def test_exact_five_from_separate_train_episodes_with_original_targets_and_no_approval(self):
        manifest = self.prepare()
        exported = reference.read_json(self.output / "published_rows.json")
        self.assertEqual(len(exported), 5)
        self.assertEqual(len({row["traj_rel_dir"] for row in exported}), 5)
        for sample, row in zip(manifest["samples"], exported):
            self.assertEqual(row, self.rows[sample["source_row_index"]])
            self.assertEqual(sample["source_row_sha256"], reference.canonical_hash(row))
            self.assertIsNotNone(sample["state_file"])
        self.assertEqual(manifest["approval"], {"status": "not_asserted"})
        self.assertFalse(manifest["p09_expert_correction_complete"])
        self.assertIsNone(manifest["label_policy"]["physical_action_horizon"]["value"])
        self.assertFalse(manifest["reader_semantics"]["executed_here"])
        validated = self.validate()
        self.assertEqual(validated["supervision_mode"], "published-reference-mechanics")
        self.assertEqual(validated["sample_count"], 5)

    def test_preparation_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(ValueError, "opt-in"):
            self.prepare(opt_in=False)
        self.assertFalse(self.output.exists())

    def test_out_of_range_rows_are_rejected_without_clipping(self):
        original_bytes = self.source.read_bytes()
        manifest = self.prepare()
        rejections = reference.read_json(self.output / "rejected_rows.json")
        self.assertEqual(rejections[0]["source_row_index"], 12)
        self.assertIn("invalid_or_out_of_range_fwd", rejections[0]["reasons"])
        self.assertEqual(manifest["selection"]["rejected_training_rows"], 1)
        self.assertTrue(all(row["label"]["fwd"] <= 5 for row in reference.read_json(self.output / "published_rows.json")))
        self.assertEqual(self.source.read_bytes(), original_bytes)

    def test_selection_is_deterministic_without_pixel_content_or_terminal_balance_tuning(self):
        first = self.prepare()
        self.output = self.root / "second"
        second = self.prepare()
        self.assertEqual(first["samples"], second["samples"])
        self.assertEqual(first["selection"], second["selection"])
        self.assertFalse(second["selection"]["pixel_content_used_for_selection"])
        self.assertFalse(second["selection"]["uses_model_outputs_or_evaluation_outcomes"])

    def test_unpinned_source_official_split_or_reader_cannot_be_used(self):
        for name, path in (("source", self.source), ("official", self.official), ("reader", self.upstream / "src/aerovla_dataset.py")):
            with self.subTest(name=name):
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                with self.assertRaisesRegex(ValueError, "pinned|SHA256|hash"):
                    self.prepare()
                path.write_bytes(original)
                self.assertFalse(self.output.exists())

    def test_split_overlap_and_nonofficial_train_membership_are_rejected(self):
        original = copy.deepcopy(self.frozen)
        for error in ("overlap", "outside_official"):
            with self.subTest(error=error):
                self.frozen = copy.deepcopy(original)
                if error == "overlap":
                    self.frozen["groups"]["holdout"] = [self.frozen["groups"]["train"][0]]
                else:
                    self.frozen["groups"]["train"][0] = "FixtureMap/not-official/merged_data.json"
                self.write(self.split, self.frozen)
                with self.assertRaisesRegex(ValueError, "overlapping|official map"):
                    self.prepare()
                self.assertFalse(self.output.exists())

    def test_rewritten_rows_and_changed_images_cannot_pass_mechanics_validation(self):
        manifest = self.prepare()
        image = self.raw / manifest["samples"][0]["images"]["front"]["path"]
        original = image.read_bytes()
        image.write_bytes(b"changed synthetic pixels")
        with self.assertRaisesRegex(ValueError, "recomputed pinned evidence"):
            self.validate()
        image.write_bytes(original)
        rows = reference.read_json(self.output / "published_rows.json")
        rows[0]["label"]["fwd"] = 4.0
        self.write(self.output / "published_rows.json", rows)
        manifest["data_json"] = reference.file_record(self.output / "published_rows.json", self.output)
        self.write(self.output / "reference_manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "unchanged deterministically"):
            self.validate()

    def test_claimed_expert_approval_or_invented_horizon_is_rejected(self):
        manifest = self.prepare()
        original = copy.deepcopy(manifest)
        for field in ("approval", "horizon"):
            with self.subTest(field=field):
                manifest = copy.deepcopy(original)
                if field == "approval":
                    manifest["approval"]["status"] = "approved"
                else:
                    manifest["label_policy"]["physical_action_horizon"] = {"status": "known", "value": "invented interval"}
                self.write(self.output / "reference_manifest.json", manifest)
                with self.assertRaisesRegex(ValueError, "approval|horizon"):
                    self.validate()

    def test_duplicate_image_rows_and_missing_views_do_not_become_eligible(self):
        self.rows.append(copy.deepcopy(self.rows[0]))
        self.refresh_pins_for_fixture()
        missing = self.raw / "FixtureMap/train-1/downcamera/000001.png"
        missing.unlink()
        manifest = self.prepare()
        reasons = manifest["selection"]["rejection_reason_counts"]
        self.assertEqual(reasons["duplicate_published_image_pair"], 2)
        self.assertEqual(reasons["missing_down_image"], 1)
        self.assertEqual(manifest["sample_count"], 5)

    def test_published_evaluation_overlap_is_rejected_without_opening_its_pixels(self):
        row = copy.deepcopy(self.rows[0])
        row["traj_rel_dir"] = "FixtureMap/holdout"
        self.rows.append(row)
        self.refresh_pins_for_fixture()
        self.audit_value["project_overlap"]["train"]["published_rows"] -= 1
        self.audit_value["project_overlap"]["holdout"].update(published_rows=1, represented_episodes=1)
        self.write(self.audit, self.audit_value)
        real_open = Path.open

        def guarded(path, *args, **kwargs):
            if "holdout" in path.parts:
                raise AssertionError("No holdout pixel/state file may be opened")
            return real_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded), self.assertRaisesRegex(ValueError, "overlap project evaluation"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_fewer_than_five_eligible_episodes_does_not_duplicate_or_fill_samples(self):
        for row in self.rows:
            if row["traj_rel_dir"] in ("FixtureMap/train-4", "FixtureMap/train-5"):
                row["label"]["yaw"] = 4.0
        self.refresh_pins_for_fixture()
        with self.assertRaisesRegex(ValueError, "five distinct"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_hashes_and_frozen_snapshot_are_preserved_and_output_cannot_be_reused(self):
        self.prepare()
        self.assertEqual((self.output / "splits.json").read_bytes(), self.split.read_bytes())
        hashes = reference.read_json(self.output / "checksums.json")
        self.assertEqual(set(hashes), {"published_rows.json", "splits.json", "rejected_rows.json", "reference_manifest.json"})
        for name, expected in hashes.items():
            self.assertEqual(reference.digest(self.output / name), expected)
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_training_mode_is_explicit_p10_only_and_does_not_relax_expert_default(self):
        self.prepare()
        options = types.SimpleNamespace(data_json=self.output / "published_rows.json", dataset_root=self.raw,
            dataset_manifest=self.output / "reference_manifest.json", phase="P10", steps=1,
            supervision_mode="published-reference-mechanics")
        with patch.object(training, "load_reference_contract", return_value=reference):
            result = training.validate_supervision(options)
            self.assertEqual(result["allowed_phase"], "P10")
            options.phase = "P12"
            with self.assertRaisesRegex(training.ContractError, "P10-only"):
                training.validate_supervision(options)
        options.phase, options.supervision_mode = "P10", "reviewed-expert"
        with self.assertRaisesRegex(training.ContractError, "vla.training-dataset.v1"):
            training.validate_supervision(options)
        self.assertEqual(training.parser().get_default("supervision_mode"), "reviewed-expert")


if __name__ == "__main__":
    unittest.main()
