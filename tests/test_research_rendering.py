"""A valid numeric table must not legitimize stale or substituted chart files."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import verify_research_figures as verification
import render_research_video as video
import render_technical_report as report


class FigureSourceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.study = self.root / "study"
        self.figures = self.root / "figures"
        shutil.copytree(ROOT / "experiments/simulation-sft-v1", self.study)
        shutil.copytree(ROOT / "docs/assets/figures/simulation-sft-v1", self.figures)

    def verify(self):
        return verification.verify_figure_provenance(self.study, self.figures)

    def manifest(self, mutation):
        path = self.figures / "figure-provenance.json"
        value = json.loads(path.read_text())
        mutation(value)
        path.write_text(json.dumps(value))

    def test_existing_public_figures_bind_all_source_bytes(self):
        checked = self.verify()
        self.assertEqual(checked["status"], "passed")
        self.assertEqual(checked["outputs_verified"], 9)
        self.assertEqual(checked["numeric_validation"]["episode_rows"], 60)

    def test_still_valid_tables_cannot_reuse_stale_input_receipts(self):
        # Whitespace preserves every numeric result but changes the declared input.
        path = self.study / "results/timing.json"
        path.write_text(path.read_text() + " ")
        with self.assertRaisesRegex(ValueError, "Study input bytes differ"):
            self.verify()

    def test_later_nonplotting_publication_record_does_not_invalidate_charts(self):
        (self.study / "additional-publication-receipt.json").write_text('{"purpose":"Publication metadata, not a plotted input"}')
        self.assertEqual(self.verify()["status"], "passed")

    def test_numeric_input_cannot_be_omitted_from_provenance(self):
        self.manifest(lambda value: value.update(inputs=[record for record in value["inputs"]
                                                       if record["file"] != "results/episodes.csv"]))
        with self.assertRaisesRegex(ValueError, "omits a required"):
            self.verify()

    def test_replaced_chart_rejected_by_both_renderers_before_output(self):
        (self.figures / "outcome-rates.png").write_bytes(b"A substituted image, not the reviewed chart")
        with patch.object(verification, "DEFAULT_STUDY", self.study), patch.object(verification, "DEFAULT_FIGURES", self.figures):
            for name, renderer in (("video", video), ("report.pdf", report)):
                destination = self.root / name
                with self.subTest(renderer=name), self.assertRaisesRegex(ValueError, "Figure output bytes differ"):
                    renderer.build(destination)
                self.assertFalse(destination.exists())

    def test_missing_and_duplicate_chart_receipts_rejected(self):
        self.manifest(lambda value: value["outputs"].pop())
        with self.assertRaisesRegex(ValueError, "inventory is incomplete"):
            self.verify()
        self.manifest(lambda value: value["outputs"].append(value["outputs"][0]))
        with self.assertRaisesRegex(ValueError, "inventory is incomplete"):
            self.verify()

    def test_modified_renderer_or_numeric_receipt_rejected(self):
        original = (self.figures / "figure-provenance.json").read_bytes()
        self.manifest(lambda value: value["renderer"].update(sha256="0" * 64))
        with self.assertRaisesRegex(ValueError, "Figure renderer differs"):
            self.verify()
        (self.figures / "figure-provenance.json").write_bytes(original)
        self.manifest(lambda value: value["validation"].update(total_recorded_actions=1))
        with self.assertRaisesRegex(ValueError, "validation receipt differs"):
            self.verify()

    def test_receipt_cannot_read_outside_figure_root(self):
        self.manifest(lambda value: value["outputs"][0].update(file="../outside.svg"))
        with self.assertRaisesRegex(ValueError, "path escapes"):
            self.verify()


class ReportLinkTests(unittest.TestCase):
    def test_relative_query_and_fragment_remain_url_components(self):
        link = report.repository_link("reproduce.md?plain=1#reports-figures-and-video-availability")
        self.assertEqual(link, "https://github.com/laxman-kc/UAV-VLA-Lab/blob/main/docs/research/reproduce.md?plain=1#reports-figures-and-video-availability")
        self.assertTrue(report.repository_link("#limitations").endswith("technical-report.md#limitations"))
        self.assertEqual(report.repository_link("https://example.org/paper#section"), "https://example.org/paper#section")

    def test_relative_link_escape_rejected(self):
        with self.assertRaisesRegex(ValueError, "escapes repository"):
            report.repository_link("../../../../private.txt#section")


if __name__ == "__main__":
    unittest.main()
