"""Synthetic contract fixtures only; these tests are not training or flight evidence."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


MODULE = Path(__file__).resolve().parents[1] / "scripts/train_adapter_mvp.py"
SPEC = importlib.util.spec_from_file_location("train_adapter_mvp", MODULE)
training = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(training)


class TrainingContractTests(unittest.TestCase):
    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")

    def record(self, path, root):
        return {"path": str(path.relative_to(root)), "sha256": training.digest(path), "bytes": path.stat().st_size}

    def fixture(self, root):
        data_root = root / "raw"
        trajectory = "FixtureMap/training-episode"
        for camera in ("frontcamera", "downcamera"):
            path = data_root / trajectory / camera / "000001.png"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"synthetic unit fixture: deliberately not flight image evidence")
        source = data_root / trajectory / "log/000001.json"
        self.write(source, {"synthetic_test_fixture": True, "state": [0, 0, 0]})
        rows = [{"traj_rel_dir": trajectory, "img_name": "000001.png", "instruction": "Synthetic unit test only.",
                 "label": {"fwd": 1.0, "down": 0.0, "yaw": 0.0}, "is_last_step": False, "is_penultimate": False}]
        self.write(root / "train.json", rows)
        self.write(root / "splits.json", {"schema_version": "vla.splits.v1", "frozen_at_utc": "fixture timestamp",
            "groups": {"train": [trajectory + "/merged_data.json"],
                       "development": ["FixtureMap/development-episode/merged_data.json"],
                       "holdout": ["FixtureMap/holdout-episode/merged_data.json"], "demo": []}})
        self.write(root / "review.json", {"synthetic_test_fixture": True, "not_real_approval": True})
        manifest = {"schema_version": "vla.training-dataset.v1", "status": "validated",
            "data_json": self.record(root / "train.json", root), "split_manifest": self.record(root / "splits.json", root),
            "label_policy": {"source_kind": "human_expert", "source_description": "Synthetic contract fixture only",
                "action_units": {"fwd": "m", "down": "m", "yaw": "rad"}, "action_frame": "Fixture frame",
                "action_horizon": "Fixture horizon", "stop_semantics": "Fixture stop", "temporal_alignment": "Fixture mapping"},
            "approval": {"status": "approved", "reviewer": "synthetic fixture", "reviewed_at_utc": "fixture timestamp",
                         "evidence": self.record(root / "review.json", root)},
            "samples": [{"row_index": 0, "row_sha256": training.canonical_hash(rows[0]), "sample_id": "fixture-sample",
                "episode_id": trajectory + "/merged_data.json", "split": "train",
                "images": {camera: self.record(data_root / trajectory / folder / "000001.png", data_root)
                           for camera, folder in (("front", "frontcamera"), ("down", "downcamera"))},
                "source_evidence": [self.record(source, data_root)]}]}
        self.write(root / "manifest.json", manifest)
        return rows, manifest, data_root

    def validate(self, root, manifest=None):
        if manifest is not None:
            self.write(root / "manifest.json", manifest)
        return training.validate_dataset(root / "train.json", root / "raw", root / "manifest.json")

    def update_rows(self, root, rows, manifest):
        self.write(root / "train.json", rows)
        manifest["data_json"] = self.record(root / "train.json", root)
        for row, sample in zip(rows, manifest["samples"]):
            sample["row_sha256"] = training.canonical_hash(row)

    def test_complete_contract_preserves_provenance_without_claiming_expert_correctness(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, manifest, _ = self.fixture(root)
            result = self.validate(root)
            self.assertEqual(result["sample_ids"], ["fixture-sample"])
            self.assertEqual(result["sample_count"], 1)
            self.assertEqual(result["label_policy"], manifest["label_policy"])
            self.assertIn("does not establish", result["limitation"])

    def test_changed_image_or_row_cannot_reuse_old_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows, manifest, data_root = self.fixture(root)
            image = data_root / manifest["samples"][0]["images"]["front"]["path"]
            image.write_bytes(b"different fixture bytes")
            with self.assertRaisesRegex(training.ContractError, "changed evidence"):
                self.validate(root)
            manifest["samples"][0]["images"]["front"] = self.record(image, data_root)
            rows[0]["label"]["fwd"] = 2.0
            self.write(root / "train.json", rows)
            manifest["data_json"] = self.record(root / "train.json", root)
            with self.assertRaisesRegex(training.ContractError, "row identity"):
                self.validate(root, manifest)

    def test_disjoint_episode_splits_and_train_membership_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, manifest, _ = self.fixture(root)
            split = training.read_json(root / "splits.json")
            split["groups"]["holdout"].extend(split["groups"]["train"])
            self.write(root / "splits.json", split)
            manifest["split_manifest"] = self.record(root / "splits.json", root)
            with self.assertRaisesRegex(training.ContractError, "overlapping"):
                self.validate(root, manifest)
            split["groups"]["holdout"] = split["groups"].pop("train")
            split["groups"]["train"] = []
            self.write(root / "splits.json", split)
            manifest["split_manifest"] = self.record(root / "splits.json", root)
            with self.assertRaisesRegex(training.ContractError, "outside.*train split"):
                self.validate(root, manifest)

    def test_no_self_labeling_unreviewed_data_or_silent_label_clipping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows, manifest, _ = self.fixture(root)
            manifest["label_policy"]["source_kind"] = "original_model_prediction"
            with self.assertRaisesRegex(training.ContractError, "not expert labels"):
                self.validate(root, manifest)
            manifest["label_policy"]["source_kind"] = "human_expert"
            manifest["approval"]["status"] = "pending"
            with self.assertRaisesRegex(training.ContractError, "approval"):
                self.validate(root, manifest)
            manifest["approval"]["status"] = "approved"
            for invalid in (5.001, -0.001, True):
                rows[0]["label"]["fwd"] = invalid
                self.update_rows(root, rows, manifest)
                with self.assertRaisesRegex(training.ContractError, "silent clipping"):
                    self.validate(root, manifest)

    def test_temporal_source_and_path_containment_cannot_be_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, manifest, _ = self.fixture(root)
            manifest["samples"][0]["source_evidence"] = []
            with self.assertRaisesRegex(training.ContractError, "temporal/state provenance"):
                self.validate(root, manifest)
            with self.assertRaisesRegex(training.ContractError, "escapes"):
                training.contained(root, "../outside.png")
            (root / "escape").symlink_to(root.parent)
            with self.assertRaisesRegex(training.ContractError, "escapes"):
                training.contained(root, "escape/file.png")

    def test_prompt_padding_and_action_token_boundaries(self):
        training.check_token_boundary([1, 7, 8, 9, 2], [1, 7], [-100, -100, 8, 9, 2, -100], [1, 1, 1, 1, 1, 0])
        with self.assertRaisesRegex(training.ContractError, "boundary differs"):
            training.check_token_boundary([1, 7, 8, 2], [1, 7, 42], [-100, -100, -100, 2], [1, 1, 1, 1])
        with self.assertRaisesRegex(training.ContractError, "Padding"):
            training.check_token_boundary([1, 7, 2], [1], [-100, 7, 2, 0], [1, 1, 1, 0])
        with self.assertRaisesRegex(training.ContractError, "supervision differs"):
            training.check_token_boundary([1, 7, 8, 2], [1], [-100, -100, 8, 2], [1, 1, 1, 1])
        with self.assertRaisesRegex(training.ContractError, "truncation"):
            training.check_token_boundary([1] * 2049, [1], [], [])

    def test_unexpected_base_trainables_or_missing_projector_are_rejected(self):
        intended = ["base_model.model.language_model.q_proj.lora_A.default.weight",
                    "base_model.model.projector.modules_to_save.default.fc1.weight"]
        self.assertEqual(set(training.check_trainable_names(intended)), {"lora", "projector"})
        with self.assertRaisesRegex(training.ContractError, "Unexpected trainable base"):
            training.check_trainable_names(intended + ["base_model.model.language_model.embed_tokens.weight"])
        with self.assertRaisesRegex(training.ContractError, "Both released"):
            training.check_trainable_names(intended[:1])
        before = {"base.model.q.lora_A.weight": {"sha256": "A"}, "base.model.projector.fc1.weight": {"sha256": "B"}}
        after = {"base.model.q.lora_A.weight": {"sha256": "C"}, "base.model.projector.fc1.weight": {"sha256": "D"}}
        self.assertEqual(training.check_weight_changes(before, after)["changed_tensor_count"], 2)
        after["base.model.projector.fc1.weight"] = before["base.model.projector.fc1.weight"]
        with self.assertRaisesRegex(training.ContractError, "did not change both"):
            training.check_weight_changes(before, after)

    def parent_fixture(self, root):
        base, adapter = root / "base", root / "adapter"
        base.mkdir(); adapter.mkdir()
        self.write(base / "config.json", {"synthetic_test_fixture": True})
        self.write(adapter / "adapter_config.json", {"peft_type": "LORA", "task_type": "CAUSAL_LM",
                                                    "bias": "none", "modules_to_save": ["projector"]})
        (adapter / "adapter_model.safetensors").write_bytes(b"synthetic contract bytes; not a real checkpoint")
        manifest = {"schema_version": "vla.adapter-parent.v1", "checkpoint_id": "fixture-only", "preserve_projector": True,
                    **{name: {"identity": "synthetic fixture only", "files": [self.record(p, folder) for p in sorted(folder.iterdir())]}
                       for name, folder in (("base", base), ("adapter", adapter))}}
        self.write(root / "parent.json", manifest)
        return base, adapter, manifest

    def test_parent_snapshot_and_projector_cannot_be_substituted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, adapter, manifest = self.parent_fixture(root)
            training.validate_parent(base, adapter, root / "parent.json")
            (base / "unexpected_model.py").write_text("# synthetic unlisted fixture")
            with self.assertRaisesRegex(training.ContractError, "no unlisted"):
                training.validate_parent(base, adapter, root / "parent.json")
            (base / "unexpected_model.py").unlink()
            manifest["preserve_projector"] = False
            self.write(root / "parent.json", manifest)
            with self.assertRaisesRegex(training.ContractError, "projector preservation"):
                training.validate_parent(base, adapter, root / "parent.json")

    def test_bounded_configuration_has_no_accidental_multi_step_p10(self):
        args = []
        for flag in ("base-model", "adapter", "parent-manifest", "data-json", "dataset-root", "dataset-manifest", "upstream", "output"):
            args.extend(["--" + flag, "/synthetic-not-run"])
        args.extend(["--phase", "P10", "--learning-rate", "0.0002", "--seed", "123"])
        options = training.parser().parse_args(args)
        training.validate_options(options)
        self.assertEqual((options.steps, options.batch_size, options.gradient_accumulation), (1, 1, 1))
        options.steps = 2
        with self.assertRaisesRegex(training.ContractError, "exactly one"):
            training.validate_options(options)
        options.phase = "P12"
        training.validate_options(options)
        options.learning_rate = float("nan")
        with self.assertRaisesRegex(training.ContractError, "finite and positive"):
            training.validate_options(options)

    def test_validate_only_never_starts_training_or_creates_an_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            base, adapter, _ = self.parent_fixture(root)
            upstream_file = root / "upstream/src/fixture.py"
            upstream_file.parent.mkdir(parents=True)
            upstream_file.write_text("# Synthetic hash-gate fixture, never imported.\n")
            arguments = ["--base-model", str(base), "--adapter", str(adapter), "--parent-manifest", str(root / "parent.json"),
                         "--data-json", str(root / "train.json"), "--dataset-root", str(root / "raw"),
                         "--dataset-manifest", str(root / "manifest.json"), "--upstream", str(root / "upstream"),
                         "--output", str(root / "must-not-exist"), "--phase", "P10", "--learning-rate", "0.0002",
                         "--seed", "123", "--validate-only"]
            output = io.StringIO()
            with patch.dict(training.UPSTREAM_FILES, {"src/fixture.py": training.digest(upstream_file)}, clear=True), \
                    patch.object(training, "run_training", side_effect=AssertionError("Training must not run")), \
                    contextlib.redirect_stdout(output):
                self.assertEqual(training.main(arguments), 0)
                self.assertFalse((root / "must-not-exist").exists())
                self.assertEqual(json.loads(output.getvalue())["status"], "contracts_validated")
                upstream_file.write_text("# Changed source bytes.\n")
                with self.assertRaisesRegex(training.ContractError, "upstream code hash differs"):
                    training.main(arguments)


if __name__ == "__main__":
    unittest.main()
