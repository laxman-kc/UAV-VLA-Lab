"""Synthetic evidence fixtures exercise rejection paths; no model/simulator claims."""
import copy
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import analyze_baseline as a


def fixture():
    events = []
    context = dict(run_id="test-run", attempt_id="test-attempt", map_name="test-map", episode_id="test-episode")
    def emit(kind, **values):
        event = dict(context, event_id=len(events)+1, event_type=kind, host_monotonic_ns=(len(events)+1)*100, **values)
        events.append(event)
        return event
    reference = dict(position=[0., 0., 0.], orientation=[0., 0., 0., 1.])
    structured = dict(position=dict(x_val=0., y_val=0., z_val=0.), orientation=dict(x_val=0., y_val=0., z_val=0., w_val=1.))
    state = dict(reference, collision=dict(has_collided=False), timestamp=10)
    start = emit("episode.start", initial_reference_state=reference)
    emit("reset_protocol.begin", protocol=a.PROTOCOL,source_sha256="helper",reset_ordinal=1)
    emit("reset_protocol.timed_continuation", requested_seconds=.001, before_state=dict(timestamp=10), after_state=dict(timestamp=1000010))
    emit("reset_protocol.sensor_refresh")
    requests, responses = [], []
    for camera in ("FrontCamera", "LeftCamera", "RightCamera", "RearCamera", "DownCamera"):
        for modality in (0, 2):
            requests.append(dict(camera_name=camera, image_type=modality))
            responses.append(dict(image_type=modality, width=256, height=256, time_stamp=10,
                                  camera_position=copy.deepcopy(structured["position"]), camera_orientation=copy.deepcopy(structured["orientation"])))
    original = emit("images.received", responses=responses)
    capture = dict(requests=requests, responses=responses, attempt_id="test-attempt", reset_ordinal=1)
    captured = emit("reset_protocol.image_capture", **{k:v for k,v in capture.items() if k != "attempt_id"})
    capture["event_id"] = captured["event_id"]
    for method, response in (("simIsPause", True), ("simGetGroundTruthKinematics", structured), ("simGetVehiclePose", structured), ("simIsPause", True)):
        request = emit("reset_protocol.call", method=method)
        emit("reset_protocol.call_returned", method=method, request_event_id=request["event_id"], response=response, call_start_ns=1, call_return_ns=2)
    cameras = dict(FrontCamera=dict(Roll=0, Pitch=0, Yaw=0), DownCamera=dict(X=0,Y=0,Z=0))
    settings = dict(ClockSpeed=10, Vehicles=dict(Drone1=dict(Cameras=cameras)))
    comparisons = []
    for name in ("FrontCamera", "DownCamera"):
        for modality in (0, 2):
            values = dict(orientation_error_rad=0.,groundtruth_orientation_difference_rad=0.) if name=="FrontCamera" else dict(position_error_m=0.,groundtruth_position_difference_m=0.)
            comparisons.append(dict(camera=name, image_type=modality, timestamp=10, **values))
    camera = dict(protocol=a.PROTOCOL, source_sha256="helper", settings_sha256="settings",
                  position_tolerance_m=.1, orientation_tolerance_rad=.05,
                  checks={name:True for name in a.CAMERA_CHECKS},
                  verified_extrinsics=dict(front=cameras["FrontCamera"], down=cameras["DownCamera"]),
                  ground_truth=structured, vehicle_pose=structured,
                  groundtruth_errors=dict(position_error_m=0., orientation_error_rad=0.),
                  vehicle_pose_errors=dict(position_error_m=0., orientation_error_rad=0.),
                  capture=capture, capture_event_id=captured["event_id"], camera_comparisons=comparisons)
    emit("reset_protocol.acceptance", **camera)
    cache = dict(initial_state=state, reset_position_error_m=0., reset_orientation_error_rad=0., checks={name:True for name in a.CACHE_CHECKS})
    accepted = emit("reset_protocol.evaluator_acceptance", protocol=a.PROTOCOL,source_sha256="helper", gate_passed=True,status="accepted",reset_ordinal=1,
                    position_tolerance_m=.1,orientation_tolerance_rad=.05,checks={name:True for name in a.ALL_CHECKS},camera_reset_measurements=camera,cached_reset_measurements=cache)
    emit("observation.prepared", sensors=dict(state=state),image_capture_event_id=original["event_id"])
    emit("prompt.prepared")
    payload = {k:v for k,v in accepted.items() if k not in {"event_type", "host_monotonic_ns", "run_id"}}
    return events, start, settings, payload


class ResetAuditTests(unittest.TestCase):
    def setUp(self):
        self.events, self.start, self.settings, self.payload = fixture()

    def audit(self):
        return a.audit_attempt(self.events, self.start, self.settings, "settings", self.payload, "helper")

    def event(self, kind):
        return next(e for e in self.events if e["event_type"] == kind)

    def test_valid_accepted_chain(self):
        result = self.audit()
        self.assertTrue(result["accepted_reset_evidence"], result["errors"])
        self.assertEqual(result["recorded_simulator_delta_seconds"], .001)

    def test_missing_duplicate_and_late_acceptance_rejected(self):
        for mutation in ("missing", "duplicate", "late"):
            with self.subTest(mutation=mutation):
                self.setUp()
                accepted = self.event("reset_protocol.evaluator_acceptance")
                if mutation == "missing": self.events.remove(accepted)
                elif mutation == "duplicate": self.events.append(copy.deepcopy(accepted))
                else: accepted["event_id"] = self.event("observation.prepared")["event_id"] + 1
                self.assertFalse(self.audit()["accepted_reset_evidence"])

    def test_true_flag_cannot_hide_bad_groundtruth(self):
        self.payload["camera_reset_measurements"]["ground_truth"]["position"]["x_val"] = .2
        self.assertFalse(self.audit()["accepted_reset_evidence"])

    def test_true_flag_cannot_hide_wrong_camera_pose(self):
        self.payload["camera_reset_measurements"]["capture"]["responses"][-1]["camera_position"]["z_val"] = .2
        self.assertFalse(self.audit()["accepted_reset_evidence"])

    def test_true_flag_cannot_hide_unpaused_readback(self):
        returned = [e for e in self.events if e["event_type"] == "reset_protocol.call_returned"]
        returned[-1]["response"] = False
        self.assertFalse(self.audit()["accepted_reset_evidence"])

    def test_wrong_first_input_settings_hash_and_nonboolean_check_rejected(self):
        for mutation in ("input", "settings", "hash", "boolean", "payload", "source", "context"):
            with self.subTest(mutation=mutation):
                self.setUp()
                if mutation == "input": self.event("observation.prepared")["image_capture_event_id"] = -1
                elif mutation == "settings": self.settings["ClockSpeed"] = 1
                elif mutation == "hash": self.payload["camera_reset_measurements"]["settings_sha256"] = "different"
                elif mutation == "boolean": self.payload["checks"]["upstream_clock_speed_10"] = 1
                elif mutation == "payload": self.payload = {}
                elif mutation == "source": self.payload["source_sha256"] = "other"
                else: self.event("prompt.prepared")["episode_id"] = "other"
                self.assertFalse(self.audit()["accepted_reset_evidence"])

    def test_nonfinite_zero_quaternion_and_boolean_pose_rejected(self):
        for value in (float("nan"), True, float("inf")):
            with self.subTest(value=value):
                self.setUp()
                self.payload["cached_reset_measurements"]["initial_state"]["position"][0] = value
                self.assertFalse(self.audit()["accepted_reset_evidence"])
        self.setUp()
        self.payload["cached_reset_measurements"]["initial_state"]["orientation"][:] = [0.,0.,0.,0.]
        self.assertFalse(self.audit()["accepted_reset_evidence"])

    def test_rejected_reset_never_scores(self):
        self.event("reset_protocol.evaluator_acceptance")["status"] = "rejected"
        self.assertEqual(self.audit()["status"], "reset_rejected")


class AccountingTests(unittest.TestCase):
    def attempt(self, trial, aid, order, valid=True, success=False):
        return dict(trial_id=trial,attempt_id=aid,raw_attempt_id=aid,session_id="session",session_order=1,start_event_id=order,
                    navigation_attempt_observed=True,joint_valid=valid,joint_status="valid" if valid else "invalid",
                    raw_outcome=dict(upstream_flags=dict(success=success,oracle_success=False,collisions=False),step=2,
                                     distance_to_target_m=1.,termination_reason="success" if success else "max_actions"))

    def test_all_twenty_denominators_and_no_replacement_for_invalid_first(self):
        plan=dict(retry_policy=dict(max_attempts_per_trial=1),trials=[dict(trial_id=f"t{i}") for i in range(20)])
        attempts=[self.attempt("t0","bad",1,False),self.attempt("t0","later-good",2,True,True),self.attempt("t1","failure",3)]
        rows=a.combine_trials(plan,attempts)
        self.assertEqual(len(rows),20)
        self.assertEqual(rows[0]["status"],"unscored_observed_trial")
        self.assertIsNone(rows[0]["upstream_success"])
        self.assertEqual(rows[0]["attempts_beyond_cap"],1)
        self.assertIs(rows[1]["upstream_success"],False)
        self.assertEqual(sum(r["status"]=="unstarted_trial" for r in rows),18)

    def test_video_uses_execution_order_and_predeclared_lower_middle(self):
        attempts=[self.attempt("t0","second-success",10,True,True),self.attempt("t1","first-success",1,True,True),self.attempt("t2","failure",5)]
        rows=[dict(selected_session_id="session",selected_attempt_id=a["attempt_id"]) for a in attempts]
        events=[]
        for attempt in attempts:
            for i in range(4):
                events.append(dict(event_type="observation.prepared",attempt_id=attempt["attempt_id"],event_id=100+i,images=[]))
        selection=a.video_selection(rows,attempts,{"session":events},{"session":pathlib.Path('/test')})
        self.assertEqual([c["attempt_id"] for c in selection["categories"]],["first-success","failure"])
        self.assertEqual([o["ordinal_one_based"] for o in selection["categories"][0]["observations"]],[1,2,4])

    def test_wilson_and_missing_are_explicit(self):
        self.assertIsNone(a.proportion(0,0)["value"])
        result=a.proportion(10,20)
        self.assertAlmostEqual(result["wilson_95"][0],.2992980081982123)
        self.assertAlmostEqual(result["wilson_95"][1],.7007019918017877)
        self.assertEqual(a.stats([None,1,3,float('nan')])["missing_or_invalid_count"],2)

    def test_path_maps_respect_component_boundaries(self):
        mappings=[(pathlib.Path('/remote/run'),pathlib.Path('/local/copied'))]
        self.assertEqual(a.remap('/remote/run/events.jsonl',mappings),pathlib.Path('/local/copied/events.jsonl'))
        self.assertEqual(a.remap('/remote/run2/events.jsonl',mappings),pathlib.Path('/remote/run2/events.jsonl'))

    def test_changed_source_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=pathlib.Path(directory)/'source.json';path.write_text('{}')
            source=a.Sources([]);record=source.record(path);path.write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError,'hash/size mismatch'):
                source.record(path,record)


class RunIdentityTests(unittest.TestCase):
    def fixture(self):
        config=dict(protocol="aerovla-e37685a-observed-v1",runtime_id="runtime",model_path="model",max_actions=200,
                    reset_protocol=a.PROTOCOL,reset_helper_sha256="helper")
        plan=dict(configuration=config,source_plan=dict(runtime_receipt_sha256="receipt"))
        receipt=dict(runtime_id="runtime",reset_protocol=a.PROTOCOL,
                     code={"reset_protocol.py":dict(sha256="helper"),"_aerovla_runtime_hooks.py":dict(sha256="hook")})
        run=dict(config,batch_size=1,runtime_receipt=dict(sha256="receipt",content=receipt),
                 patch_manifest=dict(optional_reset_protocols={a.PROTOCOL:dict(helper="_vla_lab_reset.py",sha256="helper",acceptance_before_model_preparation=True)},
                                     files={"_vla_lab_runtime.py":dict(sha256="hook"),"_vla_lab_reset.py":dict(sha256="helper")}))
        installed=[dict(source_sha256="helper",protocol=a.PROTOCOL)]
        return run,installed,plan,receipt

    def test_matching_source_and_receipt_chain(self):
        self.assertEqual(a.audit_run(*self.fixture(),"receipt","helper","hook"),[])

    def test_runtime_receipt_helper_hook_and_guard_mismatches_rejected(self):
        for field in ("runtime", "receipt", "helper", "hook", "guard", "model", "install"):
            with self.subTest(field=field):
                run,installed,plan,receipt=self.fixture()
                if field=="runtime": run["runtime_id"]="other"
                elif field=="receipt": run["runtime_receipt"]["sha256"]="other"
                elif field=="helper": run["patch_manifest"]["files"]["_vla_lab_reset.py"]["sha256"]="other"
                elif field=="hook": run["patch_manifest"]["files"]["_vla_lab_runtime.py"]["sha256"]="other"
                elif field=="guard": run["patch_manifest"]["optional_reset_protocols"][a.PROTOCOL]["acceptance_before_model_preparation"]=False
                elif field=="model": run["model_path"]="candidate"
                else: installed.append(copy.deepcopy(installed[0]))
                self.assertTrue(a.audit_run(run,installed,plan,receipt,"receipt","helper","hook"))


class AnalysisIntegrationTests(unittest.TestCase):
    def test_partial_batch_keeps_valid_outcome_and_all_planned_denominators(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            base=pathlib.Path(directory);root=base/'run'/'evidence';root.mkdir(parents=True)
            session=base/'session';session.mkdir()
            helper=base/'helper.py';helper.write_text('# synthetic helper identity\n')
            hook=base/'hook.py';hook.write_text('# synthetic guard identity\n')
            helper_sha,hook_sha=a.sha256(helper),a.sha256(hook)
            run,installed,plan,receipt=RunIdentityTests().fixture()
            def replace_values(value):
                if isinstance(value,dict): return {k:replace_values(v) for k,v in value.items()}
                if isinstance(value,list): return [replace_values(v) for v in value]
                if value == 'helper': return helper_sha
                if value == 'hook': return hook_sha
                return value
            identities=replace_values(dict(run=run,installed=installed,plan=plan,receipt=receipt))
            run,installed,plan,receipt=(identities[k] for k in ('run','installed','plan','receipt'))
            receipt_path=base/'receipt.json';a.write_json(receipt_path,receipt)
            receipt_sha=a.sha256(receipt_path);plan['source_plan']['runtime_receipt_sha256']=receipt_sha
            run['runtime_receipt']=dict(sha256=receipt_sha,content=receipt)
            events,start,settings,payload=fixture()
            # Independent JSON copies avoid mutating the shared fixture references twice.
            events=json.loads(json.dumps(events).replace('"helper"',json.dumps(helper_sha)))
            def shift(value):
                if isinstance(value,list): return [shift(v) for v in value]
                if isinstance(value,dict):
                    return {k:(v+2 if (k=='event_id' or k.endswith('_event_id')) and type(v) is int else shift(v)) for k,v in value.items()}
                return value
            events=shift(events)
            for event in events: event['host_monotonic_ns']+=200
            run.update(event_id=1,event_type='run.start',run_id='test-run',wall_time_utc='2021-01-01T00:00:00+00:00')
            installed[0].update(event_id=2,event_type='reset_protocol.installed',run_id='test-run')
            events=[run,installed[0],*events]
            settings_path=session/'settings'/'30001'/'settings.json';settings_path.parent.mkdir(parents=True);a.write_json(settings_path,settings)
            settings_sha=a.sha256(settings_path)
            for event in events:
                if event['event_type']=='reset_protocol.acceptance': event['settings_sha256']=settings_sha
                if event['event_type']=='reset_protocol.evaluator_acceptance': event['camera_reset_measurements']['settings_sha256']=settings_sha
            accepted=next(e for e in events if e['event_type']=='reset_protocol.evaluator_acceptance')
            payload={k:v for k,v in accepted.items() if k not in {'event_type','host_monotonic_ns','run_id'}}
            payload_path=root/'reset_acceptance'/'test-attempt-1.json';payload_path.parent.mkdir();a.write_json(payload_path,payload)
            event_path=root/'events.jsonl';event_path.write_text(''.join(json.dumps(e)+'\n' for e in events))
            plan.update(schema_version='vla.navigation-plan.v1',plan_id='synthetic-partial',frozen_at_utc='2020-01-01T00:00:00+00:00',
                        retry_policy=dict(selection='first_valid_attempt',max_attempts_per_trial=1),
                        trials=[dict(trial_id=f't{i}',map_name='test-map',episode_id=f'episode-{i}') for i in range(20)],
                        sessions=[dict(session_id='session',order=1,trial_ids=[f't{i}' for i in range(20)],
                                       evidence_dir=str(root),supervisor_report=str(session/'command-report.json'),session_report=str(session/'report.json'))])
            plan['trials'][0]['episode_id']='test-episode'
            plan['configuration'].update(checkpoint_id='original',task_mode='synthetic-test')
            plan_path=base/'plan.json';a.write_json(plan_path,plan)
            record=lambda path:dict(path=str(path),bytes=path.stat().st_size,sha256=a.sha256(path))
            attempt=AccountingTests().attempt('t0','test-attempt',3,True,True)
            attempt.update(status='valid_navigation_outcome',within_declared_attempt_cap=True,run_id='test-run')
            summary=dict(schema_version='vla.navigation-summary.v1',plan=plan,plan_source=record(plan_path),
                         source_consistency_errors=[],source_files=[record(plan_path),record(event_path)],attempts=[attempt],
                         sessions=[dict(session_id='session',supervisor_report={},simulation_session_report=dict(artifacts=[record(settings_path)]))])
            summary_path=base/'summary.json';a.write_json(summary_path,summary)
            args=SimpleNamespace(path_map=[],plan=plan_path,navigation_summary=summary_path,runtime_receipt=receipt_path,reset_helper=helper,runtime_hook=hook)
            result,selection=a.analyze(args)
            self.assertEqual(result['source_errors'],[])
            self.assertEqual(result['session_reset_audits'][0]['errors'],[])
            self.assertEqual(result['attempts'][0]['reset_audit']['errors'],[])
            self.assertEqual(result['aggregate']['valid_scored_trials'],1)
            self.assertEqual(result['aggregate']['unstarted_trials'],19)
            self.assertEqual(len(selection['all_trial_table']),20)
            self.assertEqual(selection['categories'][1]['status'],'category_absent')
            event_path.write_text(event_path.read_text()+'{}\n')
            result,_=a.analyze(args)
            self.assertTrue(result['source_errors'])
            self.assertEqual(result['aggregate']['valid_scored_trials'],0)


if __name__=='__main__':
    unittest.main()
