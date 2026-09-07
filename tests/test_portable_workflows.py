"""CPU fixtures verify portability and contracts, not simulator/training results."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from uav_vla_lab.datasets.snapshots import validate_intent, target
from uav_vla_lab.evaluation.context import evaluation_context, scope_limitations
from uav_vla_lab.integrations.aerovla.compat import legacy_script, verify_snapshot
from uav_vla_lab.runtime.environment import selected_environment, TIMED_RESET


def functions(path):
    return {x.name: ast.dump(x, include_attributes=False) for x in ast.parse(path.read_text()).body if isinstance(x, (ast.FunctionDef, ast.ClassDef))}


class ExtractionTests(unittest.TestCase):
    def test_snapshot_and_generated_sources_match(self):
        self.assertGreater(len(verify_snapshot()["files"]), 30)
        subprocess.run([sys.executable, str(ROOT / "scripts/sync_workflow_resources.py"), "--check"], cwd=ROOT, check=True, capture_output=True)

    def test_legacy_lookup_refuses_escape(self):
        for value in ("../train_adapter_mvp", "train_adapter_mvp.py", "missing", "/tmp/a"):
            with self.subTest(value=value), self.assertRaises(ValueError): legacy_script(value)

    def test_snapshot_tampering_fails_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "script.py").write_text("changed")
            (root / "snapshot.json").write_text(json.dumps({"schema_version": "uav-vla.legacy-source-snapshot.v1", "files": [{"path": "script.py", "bytes": 3, "sha256": hashlib.sha256(b"old").hexdigest()}]}))
            with self.assertRaisesRegex(ValueError, "changed"): verify_snapshot(root)

    def test_native_numerical_helpers_are_ast_identical(self):
        for original_path, native_path, excluded in (("analyze_baseline.py", "analyze_baseline.py", {"main", "analyze", "report_markdown"}), ("summarize_navigation.py", "navigation.py", {"main"})):
            original = functions(ROOT / "scripts" / original_path)
            native = functions(ROOT / "src/uav_vla_lab/evaluation" / native_path)
            for name in set(original) - excluded:
                with self.subTest(name=name): self.assertEqual(original[name], native[name])

    def test_dataset_and_training_mechanics_are_ast_identical(self):
        original = functions(ROOT / "scripts/train_adapter_mvp.py")
        contract = functions(ROOT / "src/uav_vla_lab/datasets/reviewed.py")
        native = functions(ROOT / "src/uav_vla_lab/training/runner.py")
        for name in contract: self.assertEqual(original[name], contract[name])
        for name in ("run_training", "validate_parent", "validate_upstream", "load_model", "check_weight_changes", "check_token_boundary", "validate_options"):
            self.assertEqual(original[name], native[name])

    def test_native_analysis_executes_real_synthetic_accounting_fixture(self):
        from uav_vla_lab.evaluation import analyze_baseline as native
        spec = importlib.util.spec_from_file_location("native_analysis_fixture", ROOT / "tests/test_baseline_analysis.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        module.a = native
        module.AnalysisIntegrationTests().test_partial_batch_keeps_valid_outcome_and_all_planned_denominators()

    def test_native_reviewed_dataset_executes_retained_contract_fixtures(self):
        from uav_vla_lab.training import runner
        spec = importlib.util.spec_from_file_location("native_dataset_fixture", ROOT / "tests/test_training_contract.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        module.training = runner
        fixture = module.TrainingContractTests()
        fixture.test_complete_contract_preserves_provenance_without_claiming_expert_correctness()
        fixture.test_changed_image_or_row_cannot_reuse_old_validation()
        fixture.test_no_self_labeling_unreviewed_data_or_silent_label_clipping()


class ContextTests(unittest.TestCase):
    def test_candidate_holdout_never_claims_released_baseline(self):
        context = evaluation_context({"trials": [{"split": "holdout"}], "configuration": {"checkpoint_id": "synthetic-candidate"}}, "candidate")
        self.assertEqual((context["role"], context["split"]), ("candidate", "holdout"))
        self.assertNotIn("Released model weights are unchanged", " ".join(scope_limitations(context)))

    def test_no_inferred_development_or_original(self):
        context = evaluation_context({"trials": [{}], "configuration": {}})
        self.assertEqual((context["split"], context["role"]), ("unspecified", "unspecified"))
        self.assertEqual(context["split_basis"], "unrecorded")

    def test_contradictory_split_or_role_rejected(self):
        for plan, role, split in (({"trials": [{"split": "holdout"}]}, "candidate", "development"), ({"model_role": "original"}, "candidate", None), ({"trials": [{"split": "holdout"}, {"split": "development"}]}, "original", None), ({"trials": [{"split": "holdout"}, {}]}, "original", None), ({"model_role": "invented"}, "unspecified", None)):
            with self.assertRaises(ValueError): evaluation_context(plan, role, split)


class RuntimeTests(unittest.TestCase):
    def test_explicit_exports_and_reset_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); receipt = root / "r.json"; name = "fresh-" + TIMED_RESET
            receipt.write_text(json.dumps({"runtime_id": name, "reset_protocol": TIMED_RESET}))
            values = selected_environment(data_root=root, python=Path(sys.executable).resolve(), reset_protocol=TIMED_RESET, runtime_id=name, receipt=receipt, evidence=root / "new", inherited={"KEEP": "yes"})
            self.assertEqual(values["VLA_LAB_RESET_PROTOCOL"], TIMED_RESET)
            self.assertEqual(values["VLA_LAB_RUNTIME_ID"], name)
            self.assertEqual(values["KEEP"], "yes")
            self.assertNotIn("VLA_LAB_SCENE_MANAGER_EXCLUSIVE", values)
            with self.assertRaises(ValueError): selected_environment(data_root=root, python=Path(sys.executable).resolve(), reset_protocol=TIMED_RESET, runtime_id="old-upstream", receipt=receipt, evidence=root / "new")

    def test_used_evidence_and_receipt_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); receipt = root / "r.json"; receipt.write_text(json.dumps({"runtime_id": "one", "reset_protocol": "upstream"}))
            for evidence, name in ((root, "one"), (root / "new", "two")):
                with self.assertRaises(ValueError): selected_environment(data_root=root, python=Path(sys.executable).resolve(), reset_protocol="upstream", runtime_id=name, receipt=receipt, evidence=evidence)

    def test_shell_syntax_and_noninstalling_help(self):
        for path in (ROOT / "src/uav_vla_lab/runtime/resources").glob("*.sh"):
            subprocess.run(["bash", "-n", str(path)], check=True, capture_output=True)
        result = subprocess.run(["bash", str(ROOT / "src/uav_vla_lab/runtime/resources/bootstrap.sh"), "--help"], check=True, capture_output=True, text=True)
        self.assertIn("--apply", result.stdout)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.intent = {"schema_version": "uav-vla.snapshot-intent.v1", "files": [{"repository": "publisher/model", "revision": "a"*40, "filename": "config.json", "relative_path": "model/config.json", "bytes": 2, "sha256": hashlib.sha256(b"{}").hexdigest()}]}

    def test_pinned_revision_and_derived_url(self):
        self.assertIn("/resolve/" + "a"*40 + "/config.json", validate_intent(self.intent)[0]["url"])
        for revision in ("main", "latest", "abc123", "A"*40):
            value = copy.deepcopy(self.intent); value["files"][0]["revision"] = revision
            with self.assertRaises(ValueError): validate_intent(value)

    def test_traversal_duplicates_url_override_rejected(self):
        for field, value in (("relative_path", "../escape"), ("filename", "/escape"), ("filename", "."), ("bytes", True), ("url", "https://example.com/file")):
            intent = copy.deepcopy(self.intent); intent["files"][0][field] = value
            with self.assertRaises(ValueError): validate_intent(intent)
        self.intent["files"].append(copy.deepcopy(self.intent["files"][0]))
        with self.assertRaises(ValueError): validate_intent(self.intent)

    def test_symlink_destination_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); (root / "outside").mkdir(); (root / "link").symlink_to(root / "outside")
            with self.assertRaises(ValueError): target(root, "link/weights")

    def test_all19_actual_model_inventory_files_are_pinned(self):
        values = validate_intent(json.loads((ROOT / "configs/assets/released_models_v1.json").read_text()))
        self.assertEqual(len(values), 19)
        self.assertEqual({v["revision"] for v in values}, {"47a0ec7fc4ec123775a391911046cf33cf9ed83f", "196f2f3253b69df6e90ac10b6ae041c7b3a9569e"})


if __name__ == "__main__": unittest.main()
