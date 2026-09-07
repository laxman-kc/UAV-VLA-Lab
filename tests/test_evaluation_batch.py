"""Synthetic metadata fixtures only; never real evaluation or holdout pixels."""
import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("prepare_evaluation_batch", Path(__file__).resolve().parents[1] / "scripts/prepare_evaluation_batch.py")
batch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch)


class EvaluationBatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.raw, self.meta = self.root / "dataset_raw", self.root / "meta"
        self.original, self.frozen_path = self.root / "original.json", self.root / "frozen.json"
        self.output = self.root / "batch-output"
        self.rows = [
            {"json": self.trajectory("dev-a"), "frame": 3, "retained_extra": [1, 2]},
            {"json": self.trajectory("holdout-a"), "frame": 1},
            {"json": self.trajectory("dev-b"), "frame": 1},
            {"json": self.trajectory("dev-a"), "frame": 7, "retained_extra": {"unchanged": True}},
            {"json": self.trajectory("demo-a"), "frame": 1},
            {"json": self.trajectory("unassigned-a"), "frame": 1},
        ]
        self.frozen = {"schema_version": "vla.splits.v1", "split_id": "synthetic-split",
            "frozen_at_utc": "2020-01-01T00:00:00+00:00", "map_id": "FixtureMap",
            "upstream_code_revision": batch.PINNED_REVISION,
            "groups": {"train": [self.trajectory("train-a")], "development": [self.trajectory("dev-b"), self.trajectory("dev-a")],
                "holdout": [self.trajectory("holdout-a")], "demo": [self.trajectory("demo-a")],
                "unassigned": [self.trajectory("unassigned-a")]}}
        self.write(self.meta / "object_description.json", [])
        self.write(self.meta / "map_spawnarea_info.json", {"FixtureMap": [[0] * 18]})
        for name, length in (("dev-a", 3), ("dev-b", 1), ("holdout-a", 2)):
            directory = self.raw / "FixtureMap" / name
            self.write(directory / "merged_data.json", {
                "trajectory_raw_detailed": [{"position": [0, 0, -2], "orientation": [0, 0, 0, 1]}] * length,
                "conversations": [{"value": f"Target is 5 degrees from you. SYNTHETIC_{name}_INSTRUCTION. Please control the UAV."}]})
            self.write(directory / "mark.json", {"object_name": "synthetic", "target": {"position": [1, 2, 3]}})
            self.write(directory / "object_description.json", {})
            pixels = directory / "frontcamera"
            pixels.mkdir()
            (pixels / "never-open.png").write_bytes(b"synthetic forbidden pixel access sentinel")
        self.save()

    @staticmethod
    def trajectory(episode):
        return f"FixtureMap/{episode}/merged_data.json"

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def save(self, refresh_counts=True):
        self.write(self.original, self.rows)
        if refresh_counts:
            self.frozen["counts"] = {name: len(values) for name, values in self.frozen["groups"].items()}
        self.frozen["sources"] = {"seen": {"file": "original upstream fixture", "sha256": batch.file_record(self.original)["sha256"],
            "rows": len(self.rows), "unique_episodes": len({row["json"] for row in self.rows})}}
        self.write(self.frozen_path, self.frozen)

    def prepare(self, group="development"):
        return batch.prepare_batch(self.original, self.frozen_path, group, self.raw, self.meta, self.output)

    def test_entire_group_reuses_existing_checks_and_preserves_rows_and_loader_identity(self):
        with patch.object(batch._SELECTOR, "select_and_validate", wraps=batch._SELECTOR.select_and_validate) as selector:
            manifest = self.prepare()
        self.assertEqual(selector.call_count, 2)
        self.assertEqual(json.loads((self.output / "episodes.json").read_text()), [self.rows[0], self.rows[2], self.rows[3]])
        self.assertEqual(manifest["selected_source_row_indices"], [0, 2, 3])
        self.assertEqual(manifest["unique_episodes"], 2)
        self.assertEqual(manifest["original_row_count"], 3)
        self.assertEqual(manifest["selected_trajectories_in_frozen_order"], self.frozen["groups"]["development"])
        self.assertEqual(manifest["loader_semantics"]["path_sorted_episode_order"], ["dev-a", "dev-b"])
        self.assertEqual(manifest["loader_semantics"]["default_same_map_length_grouped_episode_order"], ["dev-b", "dev-a"])
        self.assertEqual({item["loader_identity"]["seq_name"] for item in manifest["episodes"]}, {"dev-a", "dev-b"})
        self.assertFalse(manifest["execution_performed"])
        self.assertNotIn("runtime_id", manifest)
        self.assertNotIn("checkpoint_id", manifest)

    def test_holdout_selection_reads_only_metadata_and_does_not_publish_instruction_or_pose(self):
        opened = []
        real_open = Path.open

        def guarded(path, *args, **kwargs):
            opened.append(path.resolve())
            if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                raise AssertionError("Pixel file must never be opened by batch selection")
            return real_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded):
            manifest = self.prepare("holdout")
        self.assertEqual(manifest["unique_episodes"], 1)
        self.assertFalse(manifest["holdout_access"]["pixel_files_opened"])
        encoded = json.dumps(manifest)
        self.assertNotIn("SYNTHETIC_holdout-a_INSTRUCTION", encoded)
        self.assertNotIn('"position"', encoded)
        self.assertTrue(any(path.name == "mark.json" for path in opened))
        self.assertFalse(any("dev-a" in str(path) or "dev-b" in str(path) for path in opened))

    def test_frozen_overlap_duplicate_membership_and_wrong_counts_are_rejected(self):
        original = copy.deepcopy(self.frozen)
        for invalid in ("overlap", "duplicate", "count"):
            with self.subTest(invalid=invalid):
                self.frozen = copy.deepcopy(original)
                if invalid == "overlap":
                    self.frozen["groups"]["holdout"].append(self.trajectory("dev-a"))
                elif invalid == "duplicate":
                    self.frozen["groups"]["development"].append(self.trajectory("dev-a"))
                self.save()
                if invalid == "count":
                    self.frozen["counts"]["development"] = 999
                    self.write(self.frozen_path, self.frozen)
                with self.assertRaisesRegex(ValueError, "overlap|Duplicate|count"):
                    self.prepare()
                self.assertFalse(self.output.exists())

    def test_missing_or_undeclared_original_episode_is_not_silently_selected(self):
        self.rows = [row for row in self.rows if row["json"] != self.trajectory("dev-b")]
        self.save()
        with self.assertRaisesRegex(ValueError, "partition differs"):
            self.prepare()
        self.rows.append({"json": self.trajectory("undeclared"), "frame": 1})
        self.save()
        with self.assertRaisesRegex(ValueError, "partition differs"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_changed_original_source_cannot_reuse_frozen_hash(self):
        self.rows[0]["retained_extra"].append(3)
        self.write(self.original, self.rows)
        with self.assertRaisesRegex(ValueError, "SHA256"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_repeated_frame_rows_are_rejected_instead_of_deduplicated(self):
        self.rows.append(copy.deepcopy(self.rows[0]))
        self.save()
        with self.assertRaisesRegex(ValueError, "duplicate trajectory/frame"):
            self.prepare()

    def test_missing_or_invalid_original_metadata_is_never_created_or_repaired(self):
        path = self.raw / "FixtureMap/dev-a/mark.json"
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.prepare()
        self.assertFalse(path.exists())
        self.assertFalse(self.output.exists())
        self.write(path, {"object_name": "synthetic", "target": {"position": [1, 2, 3]}})
        merged = self.raw / self.trajectory("dev-a")
        data = json.loads(merged.read_text())
        data["conversations"][0]["value"] = "Does not satisfy the inspected parser."
        self.write(merged, data)
        with self.assertRaisesRegex(ValueError, "prompt parser"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_only_whole_development_or_holdout_groups_are_supported(self):
        for group in ("train", "demo", "unassigned", "custom"):
            with self.subTest(group=group), self.assertRaisesRegex(ValueError, "entire development or holdout"):
                self.prepare(group)
        self.assertFalse(self.output.exists())

    def test_bad_canonical_paths_and_loader_rewriting_are_rejected(self):
        for value in ("/FixtureMap/dev-a/merged_data.json", "FixtureMap/../merged_data.json",
                      "FixtureMap//dev-a/merged_data.json", "FixtureMap/dev-a/wrong.json", "FixtureMap/data6-episode/merged_data.json"):
            with self.subTest(path=value), self.assertRaises(ValueError):
                batch.trajectory_path(value, "FixtureMap")

    def test_metadata_symlink_may_not_escape_declared_root(self):
        path = self.raw / "FixtureMap/dev-a/mark.json"
        source = self.root / "outside-mark.json"
        source.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(source)
        with self.assertRaisesRegex(ValueError, "symlink escapes"):
            self.prepare()

    def test_mid_validation_source_change_is_detected_before_outputs(self):
        original = batch._SELECTOR.select_and_validate

        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            path = self.raw / "FixtureMap/dev-a/object_description.json"
            path.write_text('{"changed_during_validation":true}')
            return result

        with patch.object(batch._SELECTOR, "select_and_validate", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "changed"):
                self.prepare()
        self.assertFalse(self.output.exists())

    def test_future_frozen_time_is_rejected(self):
        self.frozen["frozen_at_utc"] = "2999-01-01T00:00:00+00:00"
        self.save()
        with self.assertRaisesRegex(ValueError, "actual prior"):
            self.prepare()

    def test_hashes_frozen_snapshot_actual_created_time_and_source_bytes_are_preserved(self):
        before = {path: path.read_bytes() for path in (self.original, self.frozen_path)}
        started = dt.datetime.now(dt.timezone.utc)
        manifest = self.prepare()
        finished = dt.datetime.now(dt.timezone.utc)
        created = dt.datetime.fromisoformat(manifest["created_at_utc"])
        self.assertLessEqual(started, created)
        self.assertLessEqual(created, finished)
        self.assertEqual((self.output / "frozen_split.snapshot.json").read_bytes(), before[self.frozen_path])
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        hashes = json.loads((self.output / "checksums.json").read_text())
        self.assertEqual(set(hashes), {"episodes.json", "frozen_split.snapshot.json", "selection_manifest.json"})
        for name, digest in hashes.items():
            self.assertEqual(batch.file_record(self.output / name)["sha256"], digest)
        with self.assertRaises(FileExistsError):
            self.prepare()


if __name__ == "__main__":
    unittest.main()
