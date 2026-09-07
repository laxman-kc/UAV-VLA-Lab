#!/usr/bin/env python3
"""Redirect one never-started P14 candidate launch without changing its protocol.

The original protocol/editorial freeze remains immutable. A separately dated
amendment changes only physical receipt paths for its existing logical session
slot. No model, simulator, outcome, camera image or network access occurs.
"""
import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys

import compare_navigation as contract

SCHEMA = 'vla.unstarted-session-path-amendment.v1'
ERROR = {'type': 'RuntimeError', 'message': 'Manager/scene port preflight failed; no manager was started'}
ALLOWED_EVENTS = {'ports.preflight_attempt', 'ports.preflight_finished', 'session.error', 'session.finished'}


def need(value, message):
    if not value:
        raise ValueError(message)


def read(path):
    return contract.json_bytes(Path(path).read_bytes())


def record(path):
    p = Path(path).resolve()
    need(p.is_file() and not p.is_symlink(), 'Expected a regular nonsymlink file')
    raw = p.read_bytes()
    return dict(path=str(p), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def write(path, value):
    with Path(path).open('x') as f:
        f.write(json.dumps(value, indent=2, allow_nan=False) + '\n')


def check_record(path, expected):
    actual = record(path)
    need(actual['sha256'] == expected['sha256'] and actual['bytes'] == expected['bytes'], 'File record differs: ' + str(path))
    return actual


def failure_proof(directory, expected_remote_report, absence_path, evidence_dir):
    """Check the full copied source ledger, lifecycle and independent absence receipt."""
    directory = Path(directory).resolve()
    report_path = directory / 'report.json'; report = read(report_path)
    need(report.get('schema_version') == 'vla.simulation-session.v1' and report.get('status') == 'session_error', 'Expected failed physical launch receipt')
    need(report.get('error') == ERROR and report.get('session_returncode') == 1, 'Failure must be the exact pre-manager port preflight error')
    need('command_returncode' in report and report['command_returncode'] is None, 'A command may have started')
    need(all(k not in report for k in ('manager_pid', 'manager_pgid', 'readiness', 'command_child_returncode', 'command_supervisor_returncode', 'command_termination_reason')), 'Manager or command launch fields are present')
    need(report.get('cleanup') == {'complete': True, 'scope': 'No manager process was started'}, 'No-manager cleanup proof differs')
    start, finish = contract.instant(report['started_at_utc']), contract.instant(report['finished_at_utc'])
    need(start < finish <= dt.datetime.now(dt.timezone.utc), 'Failed launch chronology is invalid')
    remote_root = PurePosixPath(expected_remote_report).parent
    records, names = [], set()
    for item in report.get('artifacts', []):
        remote = PurePosixPath(item['path'])
        need(remote.is_absolute() and '..' not in remote.parts, 'Unsafe recorded artifact path')
        try:
            relative = remote.relative_to(remote_root)
        except ValueError as exc:
            raise ValueError('Artifact is outside the failed physical session') from exc
        need(relative.as_posix() not in names and 'command' not in relative.parts, 'Duplicate artifact or command artifact exists')
        need(not relative.name.startswith('manager.'), 'Manager output artifact exists')
        names.add(relative.as_posix())
        records.append(check_record(directory / Path(relative.as_posix()), item))
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    need(actual == names | {'report.json'}, 'Failed session has unlisted/missing artifacts')
    need({'lifecycle.jsonl', 'port-preflight.json', 'config.resolved.json'}.issubset(names), 'Required failure evidence is missing')
    events = [contract.json_bytes(line) for line in (directory / 'lifecycle.jsonl').read_bytes().splitlines()]
    need(events and all(e.get('event') in ALLOWED_EVENTS for e in events), 'Lifecycle contains a launch or unsupported event')
    need(sum(e['event'] == 'session.error' for e in events) == sum(e['event'] == 'session.finished' for e in events) == 1, 'Expected one terminal error and finish')
    need(events[-1]['event'] == 'session.finished' and events[-1]['status'] == 'session_error' and events[-1]['returncode'] == 1, 'Terminal lifecycle disagrees')
    need(all(contract.instant(e['utc']) >= start for e in events), 'Lifecycle predates physical session')
    need(all(a['monotonic_ns'] < b['monotonic_ns'] for a, b in zip(events, events[1:])), 'Lifecycle order differs')
    preflight = read(directory / 'port-preflight.json')
    need(preflight.get('passed') is False and preflight.get('status') == 'cooldown_expired', 'This amendment only supports the recorded expired preflight cooldown')
    need(preflight.get('attempts') and preflight.get('retry_count') == len(preflight['attempts']) - 1, 'Preflight retry ledger differs')
    need(sum(e['event'] == 'ports.preflight_attempt' for e in events) == len(preflight['attempts']), 'Preflight lifecycle/attempt count differs')
    for attempt in preflight.get('attempts', []):
        p = directory / attempt['path']
        need(record(p)['sha256'] == attempt['sha256'], 'Preflight attempt digest differs')
        scan = read(p)
        need(scan.get('listener_inspection', {}).get('succeeded') is True and scan['listener_inspection']['listener_pids'] == [], 'Listener observation is not empty and reliable')
    need(read(directory / 'config.resolved.json') == report['config'], 'Recorded resolved command/config differs')
    absence = read(absence_path)
    need(absence.get('schema_version') == 'vla.navigation-evidence-absence.v1', 'Explicit remote filesystem absence receipt required')
    need(absence.get('evidence_dir') == evidence_dir and absence.get('exists') is False and type(absence.get('file_count')) is int and absence['file_count'] == 0, 'Navigation destination is not recorded absent')
    need(absence.get('failed_session_report_sha256') == record(report_path)['sha256'], 'Absence receipt references another failed launch')
    need(finish <= contract.instant(absence['observed_at_utc']) <= dt.datetime.now(dt.timezone.utc), 'Absence check must follow failed launch')
    return dict(failed_session_report=record(report_path), failed_session_artifacts=records,
                absence_receipt=record(absence_path), physical_launch_started_at=report['started_at_utc'],
                physical_launch_finished_at=report['finished_at_utc'],
                navigation_attempts_observed=0, manager_started=False, command_started=False,
                preflight_attempts=len(preflight.get('attempts', [])), cooldown_seconds=preflight.get('cooldown_seconds'),
                lifecycle_event_count=len(events), proof_scope='Complete copied wrapper ledger/lifecycle plus a separately timestamped remote filesystem absence observation; no navigation outcome is read.')


def derive(base_plan, base_nav, new_root, new_local_report):
    """Return exact path-only changes. Logical IDs and both original clocks stay fixed."""
    need(base_plan.get('phase') == 'P14' and base_plan.get('split_group') == 'holdout', 'Only P14 holdout launch remediation is supported')
    need(len(base_nav['sessions']) == len(base_plan['arms']['candidate']['session_reports']) == 1, 'Only one original candidate logical session slot is supported')
    need(base_plan['shared_contract']['retry_policy'] == base_nav['retry_policy'] == {'selection':'first_valid_attempt','max_attempts_per_trial':1}, 'One observed attempt cap must stay fixed')
    need(base_plan['arms']['candidate']['reuse_existing_analysis_sha256'] is None, 'No candidate reuse allowed')
    root = PurePosixPath(new_root); old = PurePosixPath(base_nav['sessions'][0]['session_report']).parent
    need(root.is_absolute() and '..' not in root.parts and root.parent == old.parent and root != old, 'New physical session must be a different sibling directory')
    local = Path(new_local_report)
    need(local.is_absolute() and local.name == 'report.json' and str(local) != base_plan['arms']['candidate']['session_reports'][0]['path'], 'New local report must be explicit and different')
    need(not local.exists(), 'New local report path is already populated')
    nav, plan = copy.deepcopy(base_nav), copy.deepcopy(base_plan)
    nav['sessions'][0]['supervisor_report'] = str(root / 'command/report.json')
    nav['sessions'][0]['session_report'] = str(root / 'report.json')
    plan['arms']['candidate']['session_reports'][0]['path'] = str(local)
    plan['arms']['candidate']['session_reports'][0]['analysis_source_path'] = str(root / 'report.json')
    return nav, plan


def prepare(args):
    source = args.paired_bundle.resolve(); out = args.output.resolve()
    need(not out.exists(), 'Output must be new')
    base_path = source / 'paired-plan.json'; base = read(base_path)
    nav_path = source / base['arms']['candidate']['navigation_plan']['path']; nav = read(nav_path)
    need(record(nav_path)['sha256'] == base['arms']['candidate']['navigation_plan']['sha256'], 'Original candidate navigation hash differs')
    old_slot = nav['sessions'][0]
    need(base['arms']['candidate']['session_reports'][0]['analysis_source_path'] == old_slot['session_report'], 'Original candidate receipt mapping differs')
    proof = failure_proof(args.failed_session, old_slot['session_report'], args.absence_receipt, old_slot['evidence_dir'])
    need(contract.instant(base['frozen_at_utc']) < contract.instant(proof['physical_launch_started_at']), 'Failed launch predates original frozen protocol')
    effective_nav, effective_plan = derive(base, nav, args.new_session_root, args.new_local_report)
    editorial = read(args.selection_plan)
    need(editorial['phase'] == 'P14' and editorial['paired_plan']['sha256'] == record(base_path)['sha256'], 'Original editorial plan does not bind the original P14 plan')
    sources = [record(p) for p in sorted(source.rglob('*')) if p.is_file()]
    created = dt.datetime.now(dt.timezone.utc).isoformat()
    need(contract.instant(created) > contract.instant(read(args.absence_receipt)['observed_at_utc']), 'Amendment must follow actual absence observation')
    out.mkdir(parents=True)
    shutil.copytree(source / 'metadata', out / 'metadata')
    originals = out / 'originals'; originals.mkdir()
    shutil.copyfile(base_path, originals / 'paired-plan.json')
    shutil.copyfile(nav_path, originals / 'candidate-navigation-plan.json')
    shutil.copyfile(args.selection_plan, originals / 'video-selection-plan.json')
    shutil.copytree(args.failed_session, out / 'preflight-failure/session')
    shutil.copyfile(args.absence_receipt, out / 'preflight-failure/absence.json')
    target_nav = out / base['arms']['candidate']['navigation_plan']['path']
    target_nav.unlink(); write(target_nav, effective_nav)
    effective_plan['arms']['candidate']['navigation_plan']['sha256'] = record(target_nav)['sha256']
    write(out / 'paired-plan.json', effective_plan)
    effective_video = copy.deepcopy(editorial)
    effective_video['paired_plan'] = record(out / 'paired-plan.json')
    write(out / 'video-selection-plan.json', effective_video)
    amendment = dict(schema_version=SCHEMA, created_at_utc=created, amendment_kind='candidate_physical_receipt_paths_only',
      protocol_frozen_at_utc=base['frozen_at_utc'], original_paired_plan=record(originals/'paired-plan.json'),
      original_candidate_navigation_plan=record(originals/'candidate-navigation-plan.json'),
      original_editorial_plan=record(originals/'video-selection-plan.json'),
      effective_paired_plan=record(out/'paired-plan.json'), effective_candidate_navigation_plan=record(target_nav),
      effective_editorial_plan=record(out/'video-selection-plan.json'),
      failed_session=record(out/'preflight-failure/session/report.json'), absence_receipt=record(out/'preflight-failure/absence.json'),
      logical_session_id=old_slot['session_id'], failed_physical_session_root=str(PurePosixPath(old_slot['session_report']).parent),
      next_physical_session_root=args.new_session_root, next_local_report=str(args.new_local_report),
      no_start_proof=proof, original_input_sources=sources, amendment_source=record(__file__),
      changes=['candidate navigation supervisor_report path','candidate navigation session_report path',
               'paired candidate local report path','paired candidate analysis_source_path',
               'derived navigation SHA256 and paired video-plan binding'],
      unchanged=['original arm bytes and receipts','protocol/editorial frozen_at_utc','logical session and trial IDs','evidence destination',
                 'checkpoint/runtime/configuration/command','ordered holdout membership','selection source and one observed attempt cap'],
      accounting=dict(failed_infrastructure_launches=1, failed_launch_navigation_attempts=0, additional_navigation_attempts_authorized=0,
                      interpretation='One previously declared initial navigation execution remains unstarted. The failed infrastructure launch is retained separately, not scored as a navigation failure or counted as a mission retry.'),
      chronology='The retained frozen_at_utc is the original protocol/editorial freeze, not the creation time of these derived path-bound bytes. This separately dated candidate-only amendment must precede the first actual replacement session start. The original arm is not rerun or reclassified as reused.',
      completion_gate='Run validate-completed with the actual replacement report before accepting paired results. It requires start after this amendment and exact unchanged command/config/source identity.',
      outcome_files_or_pixels_read=False, simulator_executed=False,
      decision_scope='The candidate, protocol, cohort and editorial choices were frozen earlier. This amendment is triggered solely by a proven pre-navigation infrastructure failure; no original-arm summary is used to choose or replace any mission/checkpoint.')
    write(out/'amendment.json',amendment)
    validate_bundle(out/'amendment.json')
    print(json.dumps(dict(amendment=record(out/'amendment.json'), paired_plan=record(out/'paired-plan.json'), candidate_navigation_plan=record(target_nav),
                         selection_plan=record(out/'video-selection-plan.json'), candidate_started=False),indent=2))


def validate_bundle(amendment_path):
    amendment=read(amendment_path)
    need(amendment.get('schema_version')==SCHEMA, 'Unsupported amendment')
    docs={}
    for key in ('original_paired_plan','original_candidate_navigation_plan','original_editorial_plan','effective_paired_plan','effective_candidate_navigation_plan','effective_editorial_plan','failed_session','absence_receipt'):
        check_record(amendment[key]['path'],amendment[key]);docs[key]=read(amendment[key]['path'])
    base,nav=docs['original_paired_plan'],docs['original_candidate_navigation_plan']
    # The future report can now exist: derive's freshness check applies only at preparation.
    newnav,newplan=derive_values(base,nav,amendment['next_physical_session_root'],amendment['next_local_report'])
    newplan['arms']['candidate']['navigation_plan']['sha256']=amendment['effective_candidate_navigation_plan']['sha256']
    need(newnav==docs['effective_candidate_navigation_plan'] and newplan==docs['effective_paired_plan'], 'Amendment changed fields beyond allowed paths')
    newvideo=copy.deepcopy(docs['original_editorial_plan']);newvideo['paired_plan']=amendment['effective_paired_plan']
    need(newvideo==docs['effective_editorial_plan'], 'Editorial rule or freeze changed')
    proof=failure_proof(Path(amendment['failed_session']['path']).parent,nav['sessions'][0]['session_report'],amendment['absence_receipt']['path'],nav['sessions'][0]['evidence_dir'])
    created=contract.instant(amendment['created_at_utc'])
    need(contract.instant(base['frozen_at_utc'])<contract.instant(proof['physical_launch_started_at'])<contract.instant(proof['physical_launch_finished_at'])<=contract.instant(docs['absence_receipt']['observed_at_utc'])<created<=dt.datetime.now(dt.timezone.utc),'Amendment chronology differs')
    return amendment,docs


def derive_values(base,nav,root,local):
    # Pure reconstruction deliberately avoids requiring an absent post-run report.
    newnav,newplan=copy.deepcopy(nav),copy.deepcopy(base)
    newnav['sessions'][0]['supervisor_report']=str(PurePosixPath(root)/'command/report.json')
    newnav['sessions'][0]['session_report']=str(PurePosixPath(root)/'report.json')
    newplan['arms']['candidate']['session_reports'][0]['path']=str(local)
    newplan['arms']['candidate']['session_reports'][0]['analysis_source_path']=str(PurePosixPath(root)/'report.json')
    return newnav,newplan


def validate_completed(args):
    amendment,docs=validate_bundle(args.amendment)
    report=read(args.session_report)
    need(Path(args.session_report).resolve()==Path(amendment['next_local_report']).resolve(),'Actual replacement receipt path differs')
    need(report.get('schema_version')=='vla.simulation-session.v1','Actual completed replacement session report required')
    need(contract.instant(amendment['created_at_utc'])<contract.instant(report['started_at_utc'])<contract.instant(report['finished_at_utc'])<=dt.datetime.now(dt.timezone.utc),'Replacement session did not start after amendment')
    failed=docs['failed_session']
    need(report['config']==failed['config'] and report['code']==failed['code'],'Replacement command/config/runner/source differs')
    result=dict(schema_version='vla.unstarted-session-completion-validation.v1',created_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                status='passed_path_and_chronology_contract',amendment=record(args.amendment),session_report=record(args.session_report),
                session_status=report['status'],session_returncode=report['session_returncode'],failed_physical_launch_navigation_attempts=0,
                interpretation='Path-only launch chronology and source identity passed. Navigation validity/success remain exclusively the analyzer/comparator responsibility; no score is inferred here.')
    write(args.output,result);print(json.dumps(result,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='mode',required=True)
    p=sub.add_parser('prepare')
    for name in ('paired-bundle','failed-session','absence-receipt','new-local-report','selection-plan','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--new-session-root',required=True)
    v=sub.add_parser('validate-completed')
    for name in ('amendment','session-report','output'):v.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    prepare(args) if args.mode=='prepare' else validate_completed(args)


if __name__=='__main__':main()
