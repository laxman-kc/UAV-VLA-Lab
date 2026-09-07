"""Synthetic selection/causal contracts only; no policy outcomes are produced."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import prepare_paired_video as v
from test_navigation_comparison import Fixture


def row(ordinal, old, new, valid=True):
    return dict(ordinal=ordinal, matched_valid_pair=valid,
                original_upstream_success=old, candidate_upstream_success=new)


def causal_fixture(steps=2):
    context=dict(run_id='synthetic-run', map_name='SyntheticMap', episode_id='episode', attempt_id='attempt')
    events=[]
    def emit(kind, **values):
        n=len(events)+1
        event=dict(**context, event_type=kind,event_id=n,_source_line=n,host_monotonic_ns=n*1000000000,
                   wall_time_utc='2026-01-01T00:00:00+00:00', **values)
        events.append(event);return n
    start=emit('episode.start')
    for i in range(steps+1):
        obs=emit('observation.prepared',images=[dict(path=f'observations/a/{i:06d}/front_rgb.png',
                 sha256='a'*64,camera='front',modality='rgb')],sensors={'state':{'timestamp':123,'collision':{'has_collided':False}}})
        emit('prompt.prepared',observation_event_id=obs)
        if i<steps:
            policy=emit('policy.generated',observation_event_id=obs,token_ids=[[1]],raw_text=['synthetic'])
            actions=[dict(fwd=1.,down=0.,yaw=0.)]
            emit('policy.decoded',observation_event_id=obs,policy_event_id=policy,upstream_actions=actions,upstream_stop_flags=[False])
            command=emit('action.requested',observation_event_id=obs,policy_event_id=policy,actions=actions)
            emit('action.completed',command_event_id=command)
    outcome=dict(**context,step=steps,upstream_flags={'predict_dones':False})
    emit('episode.completed',step=steps,upstream_flags={'predict_dones':False})
    return events,dict(start_event_id=start,raw_outcome=outcome)


class SelectionTests(unittest.TestCase):
    def test_first_in_declared_order_not_largest_difference(self):
        rows=[row(1,True,True),row(2,False,True),row(3,True,False),row(4,False,True)]
        picked,absent=v.choose(rows)
        self.assertEqual([p['trial']['ordinal'] for p in picked],[3,2])
        self.assertFalse(absent)

    def test_missing_one_category_never_adds_fallback(self):
        picked,absent=v.choose([row(1,False,False),row(2,False,True)])
        self.assertEqual([p['trial']['ordinal'] for p in picked],[2])
        self.assertEqual(absent,['original_only_success'])

    def test_no_discordances_uses_first_valid_same_outcome(self):
        picked,absent=v.choose([row(1,None,None,False),row(2,False,False),row(3,True,True)])
        self.assertEqual(picked[0]['trial']['ordinal'],2)
        self.assertEqual(len(absent),2)

    def test_invalid_pairs_do_not_become_sr_categories(self):
        picked,absent=v.choose([row(1,True,False,False)])
        self.assertFalse(picked);self.assertEqual(len(absent),2)

    def test_osr_does_not_select_a_video_category(self):
        rows=[{**row(1,False,False),'original_upstream_osr_success':False,'candidate_upstream_osr_success':True}]
        picked,_=v.choose(rows)
        self.assertEqual(picked[0]['category'],'first_same_sr_outcome_fallback')

    def test_first_lower_middle_last_exact_common_index(self):
        self.assertEqual(v.selected_indices(range(10),range(4)),[0,1,3])
        self.assertEqual(v.selected_indices([0,2,4,6,8],[2,4,6]),[2,4,6])
        self.assertEqual(v.selected_indices([0],[0]),[0])
        self.assertEqual(v.selected_indices([0,1],[0,1]),[0,1])
        self.assertEqual(v.selected_indices([0],[1]),[])

    def test_changed_frozen_camera_categories_or_duration_rejected(self):
        rule=v.read(Path(__file__).resolve().parents[1]/'configs/video/paired-static-rule-v1.json')
        v.validate_rule(rule)
        for group,key,value in [('clip_selection','camera','down'),('clip_selection','categories',['candidate only']),
                                ('table','display_seconds_per_slide',2)]:
            changed=copy.deepcopy(rule);changed[group][key]=value
            with self.assertRaisesRegex(ValueError,'Unsupported editorial rule'):v.validate_rule(changed)


class CausalTests(unittest.TestCase):
    def test_derived_index_is_completed_actions_not_event_id(self):
        events,attempt=causal_fixture()
        observations=v.attempt_observations(events,attempt)
        self.assertEqual(list(observations),[0,1,2])
        self.assertEqual(observations[0]['observation_event_id'],2)
        self.assertEqual(observations[0]['host_elapsed_since_episode_start_seconds'],1.)
        self.assertIsNone(observations[0]['camera_timestamp'])
        self.assertEqual(observations[0]['state_timestamp'],123)
        self.assertTrue(observations[2]['is_terminal_observation'])

    def test_extra_unfinished_observation_is_rejected(self):
        events,attempt=causal_fixture()
        observation=copy.deepcopy(events[1]);observation['event_id']=999;events.insert(2,observation)
        with self.assertRaises(ValueError):v.attempt_observations(events,attempt)

    def test_action_to_other_observation_is_rejected(self):
        events,attempt=causal_fixture()
        event=next(e for e in events if e['event_type']=='action.requested');event['observation_event_id']=999
        with self.assertRaises(ValueError):v.attempt_observations(events,attempt)

    def test_terminal_result_mutation_rejected(self):
        events,attempt=causal_fixture();events[-1]['step']=3
        with self.assertRaises(ValueError):v.attempt_observations(events,attempt)

    def test_multiple_front_views_rejected(self):
        events,attempt=causal_fixture();events[1]['images']*=2
        with self.assertRaises(ValueError):v.attempt_observations(events,attempt)

    def test_unsafe_image_path_rejected(self):
        events,attempt=causal_fixture();events[1]['images'][0]['path']='../other.png'
        with self.assertRaises(ValueError):v.attempt_observations(events,attempt)

    def test_post_completion_run_cleanup_is_not_an_observation(self):
        events,attempt=causal_fixture();cleanup=copy.deepcopy(events[-1])
        cleanup.update(event_id=len(events)+1,_source_line=len(events)+1,event_type='cleanup.scenes_closed')
        events.append(cleanup)
        self.assertEqual(list(v.attempt_observations(events,attempt)),[0,1,2])
        cleanup['event_type']='observation.prepared'
        with self.assertRaises(ValueError):v.attempt_observations(events,attempt)

    def test_duplicate_event_id_rejected(self):
        events,_=causal_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'events.jsonl';path.write_text('\n'.join(json.dumps(e) for e in events+events[:1]))
            with self.assertRaises(ValueError):v.load_events(path)


class RequestIntegrationTests(unittest.TestCase):
    def fixture(self, directory):
        root=Path(directory);f=Fixture(root);all_events={}
        for role in ('original','candidate'):
            combined=[]
            for attempt in f.analyses[role]['attempts']:
                events,_=causal_fixture();offset=len(combined)
                attempt['start_event_id']=offset+1
                attempt['raw_outcome']['upstream_flags']['predict_dones']=False
                for e in events:
                    e.update(run_id=role+'-run',map_name=attempt['map_name'],episode_id=attempt['episode_id'],attempt_id=attempt['attempt_id'])
                    for key in ('event_id','_source_line','observation_event_id','policy_event_id','command_event_id'):
                        if key in e:e[key]+=offset
                    if e['event_type']=='episode.completed':e.update(attempt['raw_outcome'])
                combined.extend(events)
            all_events[role]=combined
        f.save()
        for role,events in all_events.items():
            path=root/(role+'-events.jsonl');path.write_text(''.join(json.dumps(e)+'\n' for e in events))
            f.analyses[role]['source_files'].append(v.record(path))
            f.write(role+'.json',f.analyses[role])
        f.plan['arms']['original']['reuse_existing_analysis_sha256']=v.record(root/'original.json')['sha256']
        f.write('paired.json',f.plan);comparison=f.run();f.write('comparison.json',comparison)
        rule=v.read(Path(__file__).resolve().parents[1]/'configs/video/paired-static-rule-v1.json')
        f.write('selection.json',dict(**rule,schema_version='vla.paired-video-selection-plan.v1',phase='P13',
            frozen_at_utc='2026-01-01T05:30:00+00:00',candidate_outcomes_inspected_before_freeze=False,
            paired_plan=v.record(root/'paired.json'),missions=f.plan['missions']))
        return SimpleNamespace(selection_plan=root/'selection.json',paired_plan=root/'paired.json',comparison=root/'comparison.json',
            original_analysis=root/'original.json',candidate_analysis=root/'candidate.json',original_events=root/'original-events.jsonl',
            candidate_events=root/'candidate-events.jsonl',output=root/'request')

    def test_request_runs_metadata_contract_without_reading_pngs(self):
        with tempfile.TemporaryDirectory() as directory:
            args=self.fixture(directory);v.request(args);request=v.read(args.output/'request.json')
            self.assertEqual(len(request['pairs']),6)
            self.assertEqual(len(request['selected_categories']),2)
            self.assertTrue(request['requested_images'])
            self.assertFalse(any(Path(directory).rglob('*.png')))
            v.verify_request(request)
            request['pairs'][0]['alignment']='mutated selection'
            with self.assertRaisesRegex(ValueError,'re-derived evidence'):v.verify_request(request)

    def test_copied_comparison_cannot_change_an_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            args=self.fixture(directory);d=v.read(args.comparison);d['trials'][0]['candidate_upstream_success']=True;v.write(args.comparison,d)
            with self.assertRaisesRegex(ValueError,'Copied comparison differs'):v.request(args)
            self.assertFalse(args.output.exists())

    def test_event_stream_must_match_independent_analysis_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            args=self.fixture(directory);args.candidate_events.write_text(args.candidate_events.read_text()+'\n')
            with self.assertRaisesRegex(ValueError,'Event bytes'):v.request(args)
            self.assertFalse(args.output.exists())


if __name__=='__main__':unittest.main()
