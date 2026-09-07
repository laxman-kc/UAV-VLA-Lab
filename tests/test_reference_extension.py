"""Synthetic files only. No original pixels, real labels, training or approval."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare_reference_extension as extension

reference = extension.reference


class ReferenceExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw, self.upstream = self.root/"raw", self.root/"upstream"
        self.source, self.official, self.split, self.audit = [self.root/name for name in ("published.json", "official.json", "split.json", "audit.json")]
        self.prior, self.output = self.root/"prior-five", self.root/"extension"
        self.rows, official, episodes = [], [], []
        for i in range(30):
            trajectory = f"FixtureMap/train-{i:02d}"
            episode = trajectory+"/merged_data.json"
            episodes.append(episode)
            official.append(dict(json=episode, frame=1))
            for frame in (1, 2):
                self.rows.append(dict(traj_rel_dir=trajectory, img_name=f"{frame:06d}.png", instruction="Synthetic reference instruction",
                                      label=dict(fwd=1., down=0., yaw=.1), is_last_step=False, is_penultimate=False))
            for frame in range(1, 8):
                for folder in ("frontcamera", "downcamera"):
                    path = self.raw/trajectory/folder/f"{frame:06d}.png"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(f"synthetic non-decodable fixture image {i}/{frame}/{folder}".encode())
                self.write(self.raw/trajectory/"log"/f"{frame:06d}.json", dict(synthetic_unrelated_state=True, arbitrary_value=frame*99))
        self.write(self.source, self.rows)
        self.write(self.official, official)
        self.published = {**reference.PUBLISHED, "sha256": reference.digest(self.source), "bytes": self.source.stat().st_size}
        self.official_pin = {**reference.OFFICIAL_TRAIN, "sha256": reference.digest(self.official)}
        self.frozen = dict(schema_version="vla.splits.v1", split_id="synthetic-extension", map_id="FixtureMap",
                           frozen_at_utc="2020-01-01T00:00:00+00:00", upstream_code_revision=reference.UPSTREAM_REVISION,
                           groups=dict(train=episodes, development=["FixtureMap/dev/merged_data.json"], holdout=["FixtureMap/holdout/merged_data.json"], demo=[]),
                           sources=dict(train={**self.official_pin, "map_rows": 30, "unique_map_episodes": 30}))
        self.frozen["counts"] = {k: len(v) for k, v in self.frozen["groups"].items()}
        self.write(self.split, self.frozen)
        self.audit_value = dict(schema_version="vla.published-training-audit.v1", status="audit_completed_not_label_approval",
                               source=self.published, split_sha256=reference.digest(self.split), rows=len(self.rows),
                               project_overlap={k: dict(published_rows=len(self.rows) if k == "train" else 0, represented_episodes=30 if k == "train" else 0, declared_episodes=len(v)) for k, v in self.frozen["groups"].items()},
                               selected_map_file_and_schema_audit=dict(rows=len(self.rows)))
        self.write(self.audit, self.audit_value)
        source_hashes = {}
        for relative in reference.UPSTREAM_FILES:
            p = self.upstream/relative
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# synthetic source identity, never executed\n")
            source_hashes[relative] = reference.digest(p)
        for name, value in (("PUBLISHED", self.published), ("OFFICIAL_TRAIN", self.official_pin), ("UPSTREAM_FILES", source_hashes)):
            patcher = patch.object(reference, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def refresh(self):
        self.write(self.source, self.rows)
        self.published.update(sha256=reference.digest(self.source), bytes=self.source.stat().st_size)
        self.audit_value.update(source=self.published, rows=len(self.rows))
        self.audit_value["project_overlap"]["train"]["published_rows"] = len(self.rows)
        self.audit_value["selected_map_file_and_schema_audit"]["rows"] = len(self.rows)
        self.write(self.audit, self.audit_value)

    def prepare_prior(self):
        if not self.prior.exists():
            return reference.prepare(self.source, self.official, self.split, self.audit, self.raw, self.upstream, self.prior, opt_in=True)
        return reference.read_json(self.prior/"reference_manifest.json")

    def prepare(self, opt_in=True):
        self.prepare_prior()
        return extension.prepare(self.source, self.official, self.split, self.audit, self.raw, self.upstream,
                                 self.prior/"reference_manifest.json", self.prior/"published_rows.json", self.output, opt_in=opt_in)

    def validate(self):
        return extension.validate_extension(self.output/"published_rows.json", self.raw, self.output/"reference_manifest.json")

    def test_exact_twenty_unchanged_unique_train_episodes_and_all_six_logs(self):
        manifest = self.prepare()
        rows = reference.read_json(self.output/"published_rows.json")
        self.assertEqual(len(rows), 20)
        self.assertEqual(len({r["traj_rel_dir"] for r in rows}), 20)
        self.assertFalse({s["episode_id"] for s in manifest["samples"]} & set(manifest["excluded_episode_ids"]))
        self.assertEqual(len(manifest["excluded_episode_ids"]), 5)
        for row, sample in zip(rows, manifest["samples"]):
            self.assertEqual(row, self.rows[sample["source_row_index"]])
            self.assertEqual(sample["row_sha256"], reference.canonical_hash(row))
            self.assertEqual([r["offset"] for r in sample["state_sequence_files"]], list(range(6)))
            self.assertEqual([r["frame_index"] for r in sample["state_sequence_files"]], list(range(int(Path(row["img_name"]).stem), int(Path(row["img_name"]).stem)+6)))
            for record in [*sample["images"].values(), *sample["future_images"].values(), sample["state_file"], sample["future_state_file"]]:
                self.assertEqual(reference.file_record(self.raw/record["path"], self.raw), record)
        self.assertEqual(manifest["approval"], {"status": "not_asserted"})
        self.assertFalse(manifest["p09_expert_correction_complete"])
        self.assertFalse(manifest["selection"]["uses_alignment_results"])
        self.assertEqual(self.validate()["status"], "passed")

    def test_deterministic_frozen_rank_with_no_alignment_or_image_decode(self):
        first = self.prepare()
        self.output = self.root/"second"
        second = self.prepare()
        self.assertEqual(first["samples"], second["samples"])
        self.assertEqual(first["selection"], second["selection"])
        episodes = sorted(set(self.frozen["groups"]["train"])-set(first["excluded_episode_ids"]), key=lambda e: (extension.rank("episode", e), e))[:20]
        self.assertEqual([s["episode_id"] for s in first["samples"]], episodes)
        # Fixture logs contain no poses and fixture PNGs are deliberately not images.
        # Selection still succeeds because no alignment or decoding filter is applied.
        for sample in first["samples"]:
            chosen = self.rows[sample["source_row_index"]]
            choices = [r for r in self.rows if r["traj_rel_dir"]+"/merged_data.json" == sample["episode_id"]]
            expected = min(choices, key=lambda r: extension.rank("image", sample["episode_id"]+"\n"+r["img_name"]))
            self.assertEqual(chosen, expected)

    def test_opt_in_and_fresh_output_required(self):
        with self.assertRaisesRegex(ValueError, "opt-in"):
            self.prepare(False)
        self.assertFalse(self.output.exists())
        self.prepare()
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_rejections_cover_prior_flags_bounds_missing_future_and_gap(self):
        prior = self.prepare_prior()
        excluded = {s["episode_id"] for s in prior["samples"]}
        remaining = [e for e in self.frozen["groups"]["train"] if e not in excluded]
        # Availability-only changes leave the immutable prior source/rows intact.
        (self.raw/Path(remaining[0]).parent/"log/000003.json").unlink()
        (self.raw/Path(remaining[1]).parent/"downcamera/000006.png").unlink()
        manifest = self.prepare()
        reasons = manifest["selection"]["rejection_reason_counts"]
        self.assertEqual(reasons["excluded_prior_episode"], 10)
        self.assertGreaterEqual(reasons["missing_log_offset_2"], 1)
        self.assertGreaterEqual(reasons["missing_future_down_image"], 1)
        rejected = reference.read_json(self.output/"rejected_rows.json")
        self.assertEqual(len(rejected), manifest["selection"]["rejected_training_rows"])
        row = copy.deepcopy(self.rows[0])
        row.update(is_penultimate=True, label=dict(fwd=99, down=0., yaw=0.))
        errors = extension.extension_reasons(row, self.raw)[0]
        self.assertIn("excluded_true_is_penultimate", errors)
        self.assertIn("invalid_or_out_of_range_fwd", errors)

    def test_numeric_frame_and_contiguous_file_eligibility_only(self):
        row = copy.deepcopy(self.rows[0])
        for name in ("not-a-frame.png", "000001.jpg", "1.png", "000001.PNG", "0000001.png"):
            row["img_name"] = name
            self.assertIn("unsupported_frame_filename_requires_six_digit_png", extension.extension_reasons(row, self.raw)[0])
        row = copy.deepcopy(self.rows[0])
        row["is_last_step"] = 1
        self.assertIn("invalid_terminal_flags", extension.extension_reasons(row, self.raw)[0])

    def test_prior_row_manifest_or_image_tampering_rejected(self):
        prior = self.prepare_prior()
        for field in ("row", "approval", "image"):
            with self.subTest(field=field):
                file = self.prior/("published_rows.json" if field == "row" else "reference_manifest.json")
                if field == "image": file = self.raw/prior["samples"][0]["images"]["front"]["path"]
                original = file.read_bytes()
                if field == "row":
                    rows = reference.read_json(file); rows[0]["label"]["fwd"] = 4.; self.write(file, rows)
                elif field == "approval":
                    value = reference.read_json(file); value["approval"]["status"] = "approved"; self.write(file, value)
                else: file.write_bytes(b"changed prior pixels")
                with self.assertRaises(ValueError): self.prepare()
                self.assertFalse(self.output.exists())
                file.write_bytes(original)

    def test_pinned_inputs_and_future_bytes_cannot_silently_change(self):
        self.prepare_prior()
        original = self.source.read_bytes()
        self.source.write_bytes(original+b" ")
        with self.assertRaisesRegex(ValueError, "pinned"):
            self.prepare()
        self.source.write_bytes(original)
        manifest = self.prepare()
        future = self.raw/manifest["samples"][0]["future_state_file"]["path"]
        future.write_text('{"changed": true}')
        with self.assertRaisesRegex(ValueError, "recomputed"):
            self.validate()

    def test_insufficient_distinct_new_episodes_does_not_create_output(self):
        prior = self.prepare_prior()
        prior_set = {s["episode_id"] for s in prior["samples"]}
        for e in [e for e in self.frozen["groups"]["train"] if e not in prior_set][:6]:
            (self.raw/Path(e).parent/"log/000003.json").unlink()
        with self.assertRaisesRegex(ValueError, "twenty new distinct"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_eval_files_never_opened(self):
        actual_open = Path.open
        def guarded(path, *args, **kwargs):
            if self.raw in path.parents and any(part in {"dev", "holdout"} for part in path.parts):
                raise AssertionError("Evaluation data file was opened")
            return actual_open(path, *args, **kwargs)
        with patch.object(Path, "open", guarded):
            self.assertEqual(self.prepare()["sample_count"], 20)


if __name__ == "__main__":
    unittest.main()
