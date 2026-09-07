"""Synthetic bridge-integrity fixtures; no navigation or image evidence is made."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import prepare_amended_paired_video as bridge
import prepare_unstarted_session_amendment as amendment


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def fixture(self):
        ap=self.root/'amendment.json';ap.write_text('{}')
        report=self.root/'report.json';r={'schema_version':'vla.simulation-session.v1',
          'started_at_utc':'2026-01-02T00:00:00+00:00','finished_at_utc':'2026-01-02T00:00:01+00:00',
          'config':{'command_argv':['fixed']},'code':{'sha256':'a'*64},'status':'command_succeeded','session_returncode':0}
        report.write_text(json.dumps(r))
        a={'created_at_utc':'2026-01-01T23:59:00+00:00','next_local_report':str(report)}
        docs={'failed_session':{'config':copy.deepcopy(r['config']),'code':copy.deepcopy(r['code'])}}
        c=self.root/'completion.json';completion={'schema_version':'vla.unstarted-session-completion-validation.v1',
          'status':'passed_path_and_chronology_contract','amendment':bridge.ref(ap),'session_report':bridge.ref(report),
          'created_at_utc':'2026-01-02T00:00:02+00:00'}
        c.write_text(json.dumps(completion));return ap,report,c,a,docs
    def test_completion_requires_actual_later_start(self):
        ap,r,c,a,docs=self.fixture()
        with patch.object(amendment,'validate_bundle',return_value=(a,docs)):
            bridge.validate_completion(ap,c)
            a['created_at_utc']='2026-01-02T00:00:00+00:00'
            with self.assertRaisesRegex(ValueError,'chronology'):bridge.validate_completion(ap,c)
    def test_changed_command_rejected(self):
        ap,r,c,a,docs=self.fixture();docs['failed_session']['config']['command_argv']=['different']
        with patch.object(amendment,'validate_bundle',return_value=(a,docs)),self.assertRaisesRegex(ValueError,'config'):
            bridge.validate_completion(ap,c)
    def test_changed_actual_report_rejected_by_hash(self):
        ap,r,c,a,docs=self.fixture();r.write_text('{}')
        with patch.object(amendment,'validate_bundle',return_value=(a,docs)),self.assertRaisesRegex(ValueError,'record'):
            bridge.validate_completion(ap,c)
    def test_render_checks_bridge_before_any_pixel_operation(self):
        p=self.root/'request.json';p.write_text('{}');args=SimpleNamespace(request=p)
        with patch.object(bridge,'verify_bridge',side_effect=ValueError('no proof')),patch.object(bridge.video,'render') as render:
            with self.assertRaisesRegex(ValueError,'no proof'):bridge.render(args)
            render.assert_not_called()
    def test_existing_verifier_does_not_silently_substitute_for_bridge(self):
        with self.assertRaisesRegex(ValueError,'missing'):bridge.verify_bridge({})

if __name__=='__main__':unittest.main()
