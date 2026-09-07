"""Synthetic bounded metadata tests; no real holdout/model/pixel/result access."""
import copy
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_holdout_comparison as p
from test_navigation_comparison import Fixture, stamp


class HoldoutFixture:
    def __init__(self, root):
        self.root=Path(root); self.f=Fixture(root); f=self.f
        (self.root/"metadata").mkdir()
        self.holdout=[f"SyntheticMap/h{i}/merged_data.json" for i in (4,1,9,0,2,3,5,6,7,8)]
        f.split.update(map_id="SyntheticMap", split_id="synthetic-complete-split", sources={"seen":{"sha256":"8"*64}})
        f.split["groups"].update(train=["SyntheticMap/train/merged_data.json"], holdout=self.holdout, demo=[], unassigned=[])
        f.split["counts"]={k:len(v) for k,v in f.split["groups"].items()}
        f.write("split.json",f.split)
        self.dataset=dict(schema_version="vla.training-dataset.v1",status="validated",sample_count=1,approval={"status":"approved"},
                          split_manifest=self.record("split.json"),samples=[dict(episode_id="SyntheticMap/train/merged_data.json",split="train")])
        f.write("metadata/training_dataset_manifest.json",self.dataset)
        f.checkpoints["candidate"]["training_manifest_sha256"]=self.record("metadata/training_dataset_manifest.json")["sha256"]
        f.plan["predeclared_P14_rule"]={"policy":p.FIXED_P14_POLICY,"candidate_checkpoint_contract_sha256":None}
        for role in ("original","candidate"):
            f.navs[role]["sessions"][0].update(evidence_dir=f"/historical/{role}/evidence",supervisor_report=f"/historical/{role}/command/report.json",session_report=f"/historical/{role}/report.json")
        f.save()
        f.plan["predeclared_P14_rule"]["candidate_checkpoint_contract_sha256"]=self.record("candidate-checkpoint.json")["sha256"]
        f.write("paired.json",f.plan)
        self.result=f.run()
        self.save_result()
        self.rows=[dict(json=ep,frame=frame) for ep in sorted(self.holdout) for frame in (0,5)]
        f.write("holdout-rows.json",self.rows)
        episodes=[]
        for i,ep in enumerate(sorted(self.holdout)):
            key=ep.split('/')
            selected=[r for r in self.rows if r['json']==ep]
            episodes.append(dict(map_name=key[0],episode_id=key[1],json=ep,metadata_validated=True,
                                 loader_identity=dict(map_name=key[0],seq_name=key[1],merged_json_relative=ep),
                                 original_row_count=2,preserved_rows_canonical_sha256=p.canonical(selected),source_row_indices=[i*2,i*2+1]))
        self.selection=dict(schema_version="vla.evaluation-batch.v1",kind="complete_frozen_evaluation_group_selection",group="holdout",execution_performed=False,
            created_at_utc=stamp(10),split_id=f.split["split_id"],split_frozen_at_utc=stamp(0),map_name="SyntheticMap",unique_episodes=10,
            selected_trajectories_in_frozen_order=self.holdout,checks={k:True for k in p.SELECTION_CHECKS},
            holdout_access=dict(pixel_files_opened=False,pixel_files_rendered=False),
            outputs={"episodes.json":self.record("holdout-rows.json"),"frozen_split.snapshot.json":self.record("split.json")},
            frozen_split_source=self.record("split.json"),original_evaluation_source={"sha256":"8"*64},original_row_count=20,
            preserved_rows_canonical_sha256=p.canonical(self.rows),episodes=episodes,selected_source_row_indices=list(range(20)))
        f.write("holdout-selection.json",self.selection)
        self.request=dict(schema_version=p.REQUEST_SCHEMA,p13_paired_plan=self.record("paired.json"),p13_comparison_result=self.record("comparison.json"),
            p13_report=self.record("REPORT.md"),holdout_selection=self.record("holdout-selection.json"),holdout_episode_rows=self.record("holdout-rows.json"),
            p13_reported_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),p13_reported_before_p14=True,p13_result_used_for_selection=False,
            automatic_checkpoint_selection=False,holdout_used_for_training_or_selection=False,fresh_empty_remote_evidence_directories=True,
            plan_id="p14-synthetic-confirmation",wall_limit_seconds=100,arms={})
        for role in ("original","candidate"):
            self.request["arms"][role]=dict(plan_id=f"new-{role}-plan",trial_prefix=f"new-{role}-trial",session_id=f"new-{role}-session",
                evidence_dir=f"/future/{role}/evidence",supervisor_report=f"/future/{role}/command/report.json",session_report=f"/future/{role}/report.json",
                comparison_report_path=str(self.root/f"future-{role}-report.json"),analysis_source_path=f"/future/{role}/report.json")
        self.save_request()

    def record(self,name):
        path=self.root/name
        return dict(path=str(path),sha256=p.comparator.digest(path),bytes=path.stat().st_size)

    def save_result(self):
        self.f.write("comparison.json",self.result)
        self.f.write("REPORT.md",p.comparator.markdown(self.result).encode())

    def save_request(self):
        self.f.write("request.json",self.request)

    def refresh(self,key,name):
        self.request[key]=self.record(name);self.save_request()

    def prepare(self):
        return p.prepare(self.root/"request.json",self.root/"p14")


class HoldoutPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.f=HoldoutFixture(self.temp.name)

    def test_fresh_ten_pairs_exact_contract_bytes_order_and_hashes(self):
        old={r:(self.f.root/f"{r}-checkpoint.json").read_bytes() for r in ("original","candidate")}
        result=self.f.prepare();out=self.f.root/"p14"
        plan=json.loads((out/"paired-plan.json").read_text())
        self.assertEqual(result["planned_pairs"],10);self.assertEqual(result["planned_fresh_attempts"],20)
        self.assertEqual([m["episode_id"] for m in plan["missions"]],[x.split('/')[1] for x in self.f.holdout])
        self.assertEqual(plan["shared_contract"]["configuration"],self.f.f.config)
        self.assertEqual(plan["exact_discordant_test"],self.f.f.plan["exact_discordant_test"])
        for role in ("original","candidate"):
            self.assertEqual((out/f"metadata/{role}-checkpoint.json").read_bytes(),old[role])
            self.assertIsNone(plan["arms"][role]["reuse_existing_analysis_sha256"])
            nav=json.loads((out/plan["arms"][role]["navigation_plan"]["path"]).read_text())
            self.assertEqual(len(nav["trials"]),10)
            self.assertEqual([p.comparator.mission(t) for t in nav["trials"]],[p.comparator.mission(m) for m in plan["missions"]])
            self.assertEqual(p.comparator.configuration(nav["configuration"]),self.f.f.config)
            self.assertEqual(nav["retry_policy"]["max_attempts_per_trial"],1)
            self.assertLessEqual(p.comparator.instant(nav["frozen_at_utc"]),p.comparator.instant(plan["frozen_at_utc"]))
        for name,sha in json.loads((out/"checksums.json").read_text()).items():self.assertEqual(p.comparator.digest(out/name),sha)
        self.assertFalse(any(Path(r["path"]).suffix not in ('.json','.py','.md') for r in result['input_sources']))
        self.assertFalse(result['images_read']);self.assertFalse(result['model_files_read']);self.assertFalse(result['evaluation_executed'])
        self.assertFalse((self.f.root/'future-original-report.json').exists())
        with self.assertRaisesRegex(ValueError,'new'):self.f.prepare()

    def test_missing_incomplete_or_not_reported_p13_rejected_before_output(self):
        for kind in ('missing','incomplete','reported_false','future_report','early_report','selected'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as d:
                f=HoldoutFixture(d)
                if kind=='missing':(f.root/'comparison.json').unlink()
                if kind=='incomplete':f.result['contract_status']='pending'
                if kind=='selected':f.result['selection_decision']='candidate_wins'
                if kind in ('incomplete','selected'):
                    f.save_result();f.refresh('p13_comparison_result','comparison.json');f.refresh('p13_report','REPORT.md')
                if kind=='reported_false':f.request['p13_reported_before_p14']=False
                if kind=='future_report':f.request['p13_reported_at_utc']='2999-01-01T00:00:00+00:00'
                if kind=='early_report':f.request['p13_reported_at_utc']=stamp(5)
                f.save_request()
                with self.assertRaises((ValueError,KeyError)):f.prepare()
                self.assertFalse((f.root/'p14').exists())

    def test_exact_report_and_hash_binding_required(self):
        with (self.f.root/'REPORT.md').open('a') as f:f.write('Edited interpretation')
        self.f.refresh('p13_report','REPORT.md')
        with self.assertRaisesRegex(ValueError,'complete comparator'):self.f.prepare()
        self.f.save_result();self.f.refresh('p13_report','REPORT.md')
        self.f.result['plan_sha256']='0'*64;self.f.save_result();self.f.refresh('p13_comparison_result','comparison.json');self.f.refresh('p13_report','REPORT.md')
        with self.assertRaisesRegex(ValueError,'exact paired plan'):self.f.prepare()

    def test_changed_candidate_or_fixed_rule_rejected(self):
        self.f.f.checkpoints['candidate']['model_path']='/different/candidate'
        self.f.f.write('candidate-checkpoint.json',self.f.f.checkpoints['candidate'])
        with self.assertRaisesRegex(ValueError,'SHA256'):self.f.prepare()
        # Even an internally rewritten P13 candidate cannot bypass the previously
        # declared fixed rule. The original comparison binds the original bytes.
        self.f.f.plan['predeclared_P14_rule']['policy']='Choose whichever model scores better'
        self.f.f.write('paired.json',self.f.f.plan);self.f.refresh('p13_paired_plan','paired.json')
        with self.assertRaises(ValueError):self.f.prepare()

    def test_holdout_subset_overlap_and_metadata_gate_rejected(self):
        for kind in ('subset','gate','pixel','wrong_group','duplicates'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
                f=HoldoutFixture(d)
                if kind=='subset':f.selection['selected_trajectories_in_frozen_order']=f.holdout[:-1]
                if kind=='gate':f.selection['checks']['existing_episode_metadata_checks_passed']=False
                if kind=='pixel':f.selection['holdout_access']['pixel_files_opened']=True
                if kind=='wrong_group':f.selection['group']='development'
                if kind=='duplicates':f.selection['episodes'][0]['source_row_indices']=[0,0]
                f.f.write('holdout-selection.json',f.selection);f.refresh('holdout_selection','holdout-selection.json')
                with self.assertRaises(ValueError):f.prepare()
                self.assertFalse((f.root/'p14').exists())

    def test_training_holdout_overlap_rejected_even_with_rebound_contract(self):
        f=self.f
        f.dataset['samples'][0]['episode_id']=f.holdout[0];f.f.write('metadata/training_dataset_manifest.json',f.dataset)
        candidate=f.f.checkpoints['candidate'];candidate['training_manifest_sha256']=f.record('metadata/training_dataset_manifest.json')['sha256']
        f.f.write('candidate-checkpoint.json',candidate)
        record=f.record('candidate-checkpoint.json')
        f.f.plan['arms']['candidate']['checkpoint_contract']['sha256']=record['sha256']
        f.f.plan['predeclared_P14_rule']['candidate_checkpoint_contract_sha256']=record['sha256']
        f.f.write('paired.json',f.f.plan)
        f.result['plan_sha256']=f.record('paired.json')['sha256'];f.result['arms']['candidate']['checkpoint_contract_sha256']=record['sha256']
        for i,r in enumerate(f.result['input_sources']):
            if Path(r['path']).name=='candidate-checkpoint.json':f.result['input_sources'][i]=record
            if Path(r['path']).name=='paired.json':f.result['input_sources'][i]=f.record('paired.json')
        f.save_result();f.refresh('p13_paired_plan','paired.json');f.refresh('p13_comparison_result','comparison.json');f.refresh('p13_report','REPORT.md')
        with self.assertRaisesRegex(ValueError,'training overlaps'):f.prepare()

    def test_reused_paths_sessions_or_configuration_override_rejected(self):
        for kind in ('exists','old','same','nested','session','override','used_for_selection'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
                f=HoldoutFixture(d);a=f.request['arms']
                if kind=='exists':Path(a['original']['comparison_report_path']).write_text('not read')
                if kind=='old':a['original']['evidence_dir']='/historical/original/evidence'
                if kind=='same':a['candidate']['evidence_dir']=a['original']['evidence_dir']
                if kind=='nested':a['candidate']['evidence_dir']=a['original']['evidence_dir']+'/nested'
                if kind=='session':a['original']['session_id']='original-session'
                if kind=='override':f.request['configuration']={'max_actions':1}
                if kind=='used_for_selection':f.request['p13_result_used_for_selection']=True
                f.save_request()
                with self.assertRaises(ValueError):f.prepare()

    def test_result_scores_do_not_control_candidate(self):
        f=self.f
        f.result['success']['paired_mean_difference_candidate_minus_original']=-1.0
        f.result['success']['original_sr']=1.0;f.result['success']['candidate_sr']=0.0
        # Explicit synthetic perturbation proves this helper's chronology-only
        # use; it is not a newly validated experiment or metric recomputation.
        f.save_result();f.refresh('p13_comparison_result','comparison.json');f.refresh('p13_report','REPORT.md')
        result=f.prepare()
        self.assertEqual(result['candidate_checkpoint_contract_sha256'],f.record('candidate-checkpoint.json')['sha256'])

    def test_inputs_changed_during_copy_fail_closed(self):
        original=p.Inputs.read;count={'split':0}
        def mutate(reader,path,expected=None):
            resolved=Path(path)
            if resolved.name=='split.json':
                count['split']+=1
                if count['split']==3:
                    with resolved.open('a') as handle:handle.write(' ')
            return original(reader,path,expected)
        with mock.patch.object(p.Inputs,'read',mutate):
            with self.assertRaisesRegex(ValueError,'SHA256'):self.f.prepare()
        self.assertFalse((self.f.root/'p14/readiness.json').exists())

    def test_generated_plans_pass_full_comparator_with_synthetic_fresh_results(self):
        self.f.prepare();out=self.f.root/'p14'
        plan=json.loads((out/'paired-plan.json').read_text())
        start=p.comparator.instant(plan['frozen_at_utc'])+dt.timedelta(seconds=1)
        finish=start+dt.timedelta(seconds=1)
        analyses={}
        for role in ('original','candidate'):
            arm=plan['arms'][role]
            nav_path=out/arm['navigation_plan']['path'];nav=json.loads(nav_path.read_text())
            session_id=nav['sessions'][0]['session_id'];report_path=Path(arm['session_reports'][0]['path'])
            report_path.write_text(json.dumps(dict(schema_version='vla.simulation-session.v1',started_at_utc=start.isoformat(),finished_at_utc=finish.isoformat())))
            a=copy.deepcopy(self.f.f.analyses[role]);template_row=a['trials'][0];template_attempt=a['attempts'][0]
            a.update(plan_id=nav['plan_id'],plan_sha256=p.comparator.digest(nav_path),configuration=nav['configuration'],generated_at_utc=finish.isoformat(),
                     session_reset_audits=[dict(session_id=session_id,errors=[])],trials=[],attempts=[])
            for i,trial in enumerate(nav['trials']):
                attempt_id=f'{role}-synthetic-fresh-{i}'
                a['trials'].append({**template_row,**trial,'selected_attempt_id':attempt_id,'selected_session_id':session_id})
                a['attempts'].append({**template_attempt,**trial,'attempt_id':attempt_id,'session_id':session_id,'start_event_id':i+1,'start_wall_time_utc':start.isoformat()})
            runtime_path=out/plan['shared_contract']['runtime_receipt']['path']
            a['source_files']=[dict(path=str(path),bytes=path.stat().st_size,sha256=p.comparator.digest(path)) for path in (nav_path,runtime_path)]
            a['source_files'].append(dict(path=arm['session_reports'][0]['analysis_source_path'],bytes=report_path.stat().st_size,sha256=p.comparator.digest(report_path)))
            a['source_files'].extend(dict(path=str(self.f.root/name),sha256=record['sha256'],bytes=1) for name,record in self.f.f.receipt['code'].items())
            self.f.f.analyses[role]=a;self.f.f.count(role)
            path=self.f.root/f'fresh-{role}-analysis.json';path.write_text(json.dumps(a));analyses[role]=path
        result=p.comparator.compare(out/'paired-plan.json',analyses['original'],analyses['candidate'])
        self.assertEqual(result['planned_pairs'],10);self.assertEqual(result['matched_valid_pairs'],10)
        self.assertEqual(result['phase'],'P14')
        self.assertTrue(all(result['arms'][r]['reused_original_analysis'] is False for r in ('original','candidate')))


if __name__=='__main__':unittest.main()
