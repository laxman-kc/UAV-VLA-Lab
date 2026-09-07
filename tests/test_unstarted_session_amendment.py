"""Synthetic metadata fixtures only; no experiment or production result claims."""
import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import prepare_unstarted_session_amendment as amendment


class AmendmentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.plan={'phase':'P14','split_group':'holdout','frozen_at_utc':'2026-01-01T00:00:00+00:00',
          'shared_contract':{'retry_policy':{'selection':'first_valid_attempt','max_attempts_per_trial':1}},
          'arms':{'original':{'unchanged':'original'},'candidate':{'reuse_existing_analysis_sha256':None,
            'navigation_plan':{'path':'metadata/candidate-navigation-plan.json','sha256':'a'*64},
            'session_reports':[{'session_id':'logical-slot','path':str(self.root/'v1/report.json'),'analysis_source_path':'/runs/v1/report.json'}]}}}
        self.nav={'frozen_at_utc':'2026-01-01T00:00:00+00:00','configuration':{'checkpoint_id':'fixed','runtime':'fixed'},
          'trials':[{'trial_id':'one'}],'retry_policy':copy.deepcopy(self.plan['shared_contract']['retry_policy']),
          'sessions':[{'session_id':'logical-slot','evidence_dir':'/runs/navigation/evidence','trial_ids':['one'],
            'supervisor_report':'/runs/v1/command/report.json','session_report':'/runs/v1/report.json'}]}
    def tearDown(self):self.temp.cleanup()
    def test_only_receipt_paths_change(self):
        before=copy.deepcopy((self.plan,self.nav));nav,plan=amendment.derive(self.plan,self.nav,'/runs/v2',self.root/'v2/report.json')
        expectednav=copy.deepcopy(self.nav);expectedplan=copy.deepcopy(self.plan)
        expectednav['sessions'][0]['supervisor_report']='/runs/v2/command/report.json';expectednav['sessions'][0]['session_report']='/runs/v2/report.json'
        expectedplan['arms']['candidate']['session_reports'][0]['path']=str(self.root/'v2/report.json');expectedplan['arms']['candidate']['session_reports'][0]['analysis_source_path']='/runs/v2/report.json'
        self.assertEqual((nav,plan),(expectednav,expectedplan));self.assertEqual((self.plan,self.nav),before)
    def test_forbids_same_or_nonsibling_physical_directory(self):
        for root in ('/runs/v1','/other/v2','relative/v2','/runs/../v2'):
            with self.subTest(root=root),self.assertRaises(ValueError):amendment.derive(self.plan,self.nav,root,self.root/'v2/report.json')
    def test_forbids_observed_attempt_cap_change(self):
        self.nav['retry_policy']['max_attempts_per_trial']=2
        with self.assertRaises(ValueError):amendment.derive(self.plan,self.nav,'/runs/v2',self.root/'v2/report.json')
    def test_forbids_existing_new_local_report(self):
        p=self.root/'v2/report.json';p.parent.mkdir();p.write_text('{}')
        with self.assertRaises(ValueError):amendment.derive(self.plan,self.nav,'/runs/v2',p)
    def failure_fixture(self):
        root=self.root/'failed';root.mkdir()
        def write(name,d):
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d));return p
        scan=write('port-preflight-attempts/0001.json',{'listener_inspection':{'succeeded':True,'listener_pids':[]}})
        preflight={'passed':False,'status':'cooldown_expired','retry_count':0,'attempts':[{'path':'port-preflight-attempts/0001.json','sha256':amendment.record(scan)['sha256']}]}
        write('port-preflight.json',preflight);write('config.resolved.json',{'command_argv':['unchanged']})
        events=[{'event':'ports.preflight_attempt','utc':'2026-01-01T00:00:01+00:00','monotonic_ns':1},
          {'event':'session.error','utc':'2026-01-01T00:00:02+00:00','monotonic_ns':2},
          {'event':'session.finished','utc':'2026-01-01T00:00:03+00:00','monotonic_ns':3,'status':'session_error','returncode':1}]
        (root/'lifecycle.jsonl').write_text('\n'.join(json.dumps(e) for e in events)+'\n')
        artifacts=[]
        for p in sorted(root.rglob('*')):
            if p.is_file():
                r=amendment.record(p);r['path']='/runs/v1/'+p.relative_to(root).as_posix();artifacts.append(r)
        report={'schema_version':'vla.simulation-session.v1','status':'session_error','error':amendment.ERROR,
          'session_returncode':1,'command_returncode':None,'cleanup':{'complete':True,'scope':'No manager process was started'},
          'started_at_utc':'2026-01-01T00:00:00+00:00','finished_at_utc':'2026-01-01T00:00:03+00:00',
          'config':{'command_argv':['unchanged']},'artifacts':artifacts}
        write('report.json',report)
        absence=self.root/'absence.json';absence.write_text(json.dumps({'schema_version':'vla.navigation-evidence-absence.v1',
          'observed_at_utc':'2026-01-01T00:00:04+00:00','evidence_dir':'/runs/navigation/evidence','exists':False,'file_count':0,
          'failed_session_report_sha256':amendment.record(root/'report.json')['sha256']}))
        return root,absence
    def test_complete_no_start_proof(self):
        root,absence=self.failure_fixture();proof=amendment.failure_proof(root,'/runs/v1/report.json',absence,'/runs/navigation/evidence')
        self.assertEqual(proof['navigation_attempts_observed'],0);self.assertFalse(proof['command_started'])
    def test_rejects_command_launch_even_with_error(self):
        root,absence=self.failure_fixture();p=root/'report.json';d=json.loads(p.read_text());d['command_returncode']=1;p.write_text(json.dumps(d))
        with self.assertRaises(ValueError):amendment.failure_proof(root,'/runs/v1/report.json',absence,'/runs/navigation/evidence')
    def test_rejects_unlisted_evidence_file(self):
        root,absence=self.failure_fixture();(root/'unexpected.txt').write_text('evidence')
        with self.assertRaises(ValueError):amendment.failure_proof(root,'/runs/v1/report.json',absence,'/runs/navigation/evidence')
    def test_rejects_positive_or_stale_absence(self):
        for change in ({'exists':True},{'file_count':1},{'observed_at_utc':'2025-01-01T00:00:00+00:00'}):
            with self.subTest(change=change):
                with tempfile.TemporaryDirectory() as t:
                    previous=self.root;self.root=Path(t);root,absence=self.failure_fixture();self.root=previous
                    d=json.loads(absence.read_text());d.update(change);absence.write_text(json.dumps(d))
                    with self.assertRaises(ValueError):amendment.failure_proof(root,'/runs/v1/report.json',absence,'/runs/navigation/evidence')

if __name__=='__main__':unittest.main()
