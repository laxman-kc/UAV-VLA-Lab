"""Synthetic metadata fixtures only; no training, evaluation, model or pixels."""
import copy
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_development_comparison as p
from test_navigation_comparison import Fixture, stamp


class PreparationFixture:
    def __init__(self, root):
        self.root = Path(root)
        self.f = Fixture(root)
        f = self.f
        f.split["groups"]["train"] = ["SyntheticMap/train/merged_data.json"]
        f.split["groups"]["holdout"] = ["SyntheticMap/unopened/merged_data.json"]
        # Planned order deliberately differs from lexical order and observed order.
        f.navs["original"]["trials"].reverse()
        f.analyses["original"]["trials"].reverse()
        f.navs["original"]["configuration"]["model_path"] = "/recorded/released"
        self.episodes = [{"json": "SyntheticMap/"+t["episode_id"]+"/merged_data.json"} for t in f.navs["original"]["trials"]]
        self.parent = dict(schema_version="vla.adapter-parent.v1", preserve_projector=True, checkpoint_id="original",
                           base=dict(identity="synthetic-base", files=[dict(path="model.safetensors", sha256="1"*64, bytes=10)]),
                           adapter=dict(identity="synthetic-parent", files=[dict(path=n, sha256="2"*64, bytes=10) for n in ("adapter_config.json", "adapter_model.safetensors")]))
        self.dataset = dict(schema_version="vla.training-dataset.v1", status="validated", approval=dict(status="approved", reviewer="synthetic fixture"),
                            label_policy=dict(source_kind="audited_reference_expert"), samples=[dict(episode_id="SyntheticMap/train/merged_data.json", split="train")])
        config = dict(phase="P12", supervision_mode="reviewed-expert", validate_only=False, steps=25,
                      selection_rule="fixed_final_step_candidate", output="/recorded/p12", adapter="/recorded/released")
        self.checkpoint = dict(schema_version="vla.training-checkpoint.v1", status="mechanics_verified", phase="P12", config=config,
                               optimizer_steps=25, selection_rule="fixed_final_step_candidate", projector_preserved_and_saved=True,
                               reload_validation={k: True for k in ("exact_adapter_and_projector_hashes_match", "last_token_logits_allclose", "loss_isclose")},
                               checkpoint_files=[dict(path="/recorded/p12/checkpoint/"+n, sha256="3"*64, bytes=10) for n in ("adapter_config.json", "adapter_model.safetensors")],
                               code={"fixture": "not executed"})
        self.run = dict(schema_version="vla.training-run.v1", status="passed", phase="P12", stage="complete",
                        started_at_utc=stamp(8), completed_at_utc=stamp(9), completed_optimizer_steps=25)
        self.request = dict(schema_version=p.REQUEST_SCHEMA, plan_id="synthetic-p13", candidate_plan_id="synthetic-new-plan", candidate_trial_prefix="new",
                            holdout_used_for_training_or_selection=False, automatic_checkpoint_selection=False, exact_discordant_test=True,
                            candidate_wall_limit_seconds=100,
                            candidate_session=dict(session_id="future-session", evidence_dir="/future/evidence", supervisor_report="/future/supervisor/report.json",
                                                   session_report="/future/session/report.json", comparison_report_path=str(self.root/"future-session.json"),
                                                   analysis_source_path="/future/session/report.json"))

    def record(self, name):
        path = self.root/name
        return dict(path=str(path), sha256=p.comparator.digest(path), bytes=path.stat().st_size)

    def save(self):
        f = self.f
        f.save()
        f.write("episodes.json", self.episodes)
        selection = dict(schema_version="vla.evaluation-batch.v1", group="development", execution_performed=False,
                         outputs={"episodes.json": self.record("episodes.json"), "frozen_split.snapshot.json": self.record("split.json")})
        f.write("selection.json", selection)
        f.navs["original"]["source_plan"].update(episode_rows_sha256=self.record("episodes.json")["sha256"], selection_manifest_sha256=self.record("selection.json")["sha256"])
        f.write("original-plan.json", f.navs["original"])
        analysis = f.analyses["original"]
        analysis["configuration"] = copy.deepcopy(f.navs["original"]["configuration"])
        analysis["plan_sha256"] = self.record("original-plan.json")["sha256"]
        for i, record in enumerate(analysis["source_files"]):
            if record["path"] == str(self.root/"original-plan.json"):
                analysis["source_files"][i] = self.record("original-plan.json")
        f.write("original.json", analysis)
        self.dataset["split_manifest"] = self.record("split.json")
        f.write("dataset.json", self.dataset)
        f.write("parent.json", self.parent)
        self.checkpoint["parent"] = dict(manifest=self.record("parent.json"), **{k: copy.deepcopy(self.parent[k]) for k in ("checkpoint_id", "base", "adapter")})
        self.checkpoint["dataset"] = dict(status="passed", supervision_mode="reviewed-expert", dataset_manifest=self.record("dataset.json"),
                                           approval=self.dataset["approval"], label_policy=self.dataset["label_policy"],
                                           sample_count=len(self.dataset["samples"]), episode_ids=[s["episode_id"] for s in self.dataset["samples"]])
        self.run.update({k: copy.deepcopy(self.checkpoint[k]) for k in ("config", "parent", "dataset", "reload_validation", "checkpoint_files", "code")})
        f.write("checkpoint-manifest.json", self.checkpoint)
        f.write("training-report.json", self.run)
        for key, name in dict(original_navigation_plan="original-plan.json", original_analysis="original.json", frozen_split="split.json",
                              runtime_receipt="runtime.json", episode_selection="selection.json", episode_rows="episodes.json", analyzer_source="analyze_baseline.py").items():
            self.request[key] = self.record(name)
        self.request["original_session_reports"] = [dict(session_id="original-session", analysis_source_path=str(self.root/"original-session.json"), **self.record("original-session.json"))]
        f.write("request.json", self.request)

    def prepare(self):
        return p.prepare(*(self.root/name for name in ("request.json", "checkpoint-manifest.json", "training-report.json", "dataset.json", "parent.json", "output")))


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = PreparationFixture(self.temp.name)

    def test_metadata_only_exact_order_and_immutable_reuse(self):
        self.f.save()
        before = (self.f.root/"original-plan.json").read_bytes()
        result = self.f.prepare()
        out = self.f.root/"output"
        plan = json.loads((out/"paired-plan.json").read_text())
        nav = json.loads((out/"metadata/candidate-navigation-plan.json").read_text())
        self.assertEqual((out/"metadata/original_navigation_plan.json").read_bytes(), before)
        self.assertEqual([t["episode_id"] for t in nav["trials"]], ["e2", "e1", "e0"])
        self.assertEqual(nav["configuration"]["model_path"], "/recorded/p12/checkpoint")
        self.assertEqual(p.comparator.configuration(nav["configuration"]), self.f.f.config)
        self.assertEqual(plan["arms"]["original"]["reuse_existing_analysis_sha256"], self.f.record("original.json")["sha256"])
        self.assertIsNone(plan["arms"]["candidate"]["reuse_existing_analysis_sha256"])
        self.assertEqual(result["status"], "metadata_prepared_evaluation_not_run")
        self.assertEqual(result["baseline_reuse_accounting"]["valid_scored_trials"], 3)
        self.assertIn("regardless of P13", plan["predeclared_P14_rule"]["policy"])
        self.assertFalse((self.f.root/"future-session.json").exists())
        self.assertFalse(any(x["path"].endswith("safetensors") for x in result["input_sources"]))
        for name, sha in json.loads((out/"checksums.json").read_text()).items():
            self.assertEqual(p.comparator.digest(out/name), sha)
        with self.assertRaisesRegex(ValueError, "new"):
            self.f.prepare()

    def test_p10_validate_only_incomplete_reload_and_nonfinal_rejected(self):
        for field in ("p10", "validate", "failed", "reload", "selection", "steps"):
            with self.subTest(field=field):
                f = self.f = PreparationFixture(self.temp.name)
                if field == "p10": f.checkpoint["phase"] = "P10"
                if field == "validate": f.checkpoint["config"]["validate_only"] = True
                if field == "failed": f.run["status"] = "failed"
                if field == "reload": f.checkpoint["reload_validation"]["loss_isclose"] = False
                if field == "selection": f.checkpoint["selection_rule"] = "best_loss"
                if field == "steps": f.run["completed_optimizer_steps"] = 24
                f.save()
                with self.assertRaises(ValueError): f.prepare()
                self.assertFalse((f.root/"output").exists())

    def test_training_membership_and_parent_mismatch_rejected(self):
        for field in ("holdout", "unapproved", "parent"):
            with self.subTest(field=field):
                f = self.f = PreparationFixture(self.temp.name)
                if field == "holdout": f.dataset["samples"][0]["episode_id"] = "SyntheticMap/unopened/merged_data.json"
                if field == "unapproved": f.dataset["approval"]["status"] = "unreviewed"
                if field == "parent": f.parent["checkpoint_id"] = "other"
                f.save()
                with self.assertRaises(ValueError): f.prepare()
                self.assertFalse((f.root/"output").exists())

    def test_saved_file_escape_or_missing_adapter_rejected(self):
        for path in ("/different/checkpoint/adapter_model.safetensors", "/recorded/p12/checkpoint/other.bin"):
            self.f.checkpoint["checkpoint_files"][1]["path"] = path
            self.f.save()
            with self.assertRaises(ValueError): self.f.prepare()

    def test_corrupt_baseline_accounting_and_reset_session_rejected(self):
        for field in ("aggregate", "audit", "order"):
            with self.subTest(field=field):
                f = self.f = PreparationFixture(self.temp.name)
                if field == "audit": f.f.analyses["original"]["session_reset_audits"][0]["errors"] = ["rejected"]
                if field == "order": f.f.analyses["original"]["trials"].reverse()
                f.save()
                if field == "aggregate":
                    a = f.f.analyses["original"]
                    a["aggregate"]["valid_scored_trials"] = 999
                    f.f.write("original.json", a)
                    f.request["original_analysis"] = f.record("original.json")
                    f.f.write("request.json", f.request)
                with self.assertRaises(ValueError): f.prepare()

    def test_hash_tampering_and_chronology_rejected(self):
        self.f.save()
        (self.f.root/"runtime.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "SHA256"): self.f.prepare()
        self.f = PreparationFixture(self.temp.name)
        self.f.run["completed_at_utc"] = "2999-01-01T00:00:00+00:00"
        self.f.save()
        with self.assertRaisesRegex(ValueError, "chronology"): self.f.prepare()

    def test_session_mapping_and_undeclared_future_destination_rejected(self):
        self.f.save()
        self.f.request["original_session_reports"][0]["analysis_source_path"] = "/rewritten/history.json"
        self.f.f.write("request.json", self.f.request)
        with self.assertRaisesRegex(ValueError, "inventory"): self.f.prepare()
        self.f.save()
        del self.f.request["candidate_session"]["comparison_report_path"]
        self.f.f.write("request.json", self.f.request)
        with self.assertRaisesRegex(ValueError, "Predeclare"): self.f.prepare()


if __name__ == "__main__":
    unittest.main()
