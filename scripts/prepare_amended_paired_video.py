#!/usr/bin/env python3
"""P14-only external bridge from an immutable editorial freeze to path amendment.

The paired video selector/renderer is unchanged. This wrapper requires the exact
no-start amendment and later replacement-session proof before deriving selection
or reading selected images. It never executes a simulator or changes the rule.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

import prepare_paired_video as video
import prepare_unstarted_session_amendment as amendment

SCHEMA = 'vla.paired-video-amendment-bridge.v1'


def read(p): return amendment.read(p)
def ref(p): return amendment.record(p)
def need(value,message): amendment.need(value,message)


def validate_completion(amendment_path, receipt_path):
    a,docs=amendment.validate_bundle(amendment_path)
    completion=read(receipt_path)
    need(completion.get('schema_version')=='vla.unstarted-session-completion-validation.v1' and
         completion.get('status')=='passed_path_and_chronology_contract','Actual replacement completion validation required')
    need(completion['amendment']==ref(amendment_path),'Completion validation binds another amendment')
    sr=completion['session_report'];amendment.check_record(sr['path'],sr)
    need(str(Path(sr['path']).resolve())==str(Path(a['next_local_report']).resolve()),'Replacement report path differs')
    report=read(sr['path'])
    need(amendment.contract.instant(a['created_at_utc'])<amendment.contract.instant(report['started_at_utc'])<
         amendment.contract.instant(report['finished_at_utc'])<=amendment.contract.instant(completion['created_at_utc'])<=dt.datetime.now(dt.timezone.utc),
         'Replacement start/completion/amendment chronology differs')
    need(report['config']==docs['failed_session']['config'] and report['code']==docs['failed_session']['code'],
         'Replacement command/config/source differs')
    return a,docs,completion


def bridge_expected(amendment_path,completion_path):
    a,docs,completion=validate_completion(amendment_path,completion_path)
    return dict(schema_version=SCHEMA,amendment=ref(amendment_path),completion_validation=ref(completion_path),
      original_frozen_editorial_plan=a['original_editorial_plan'],effective_path_bound_editorial_plan=a['effective_editorial_plan'],
      original_frozen_paired_plan=a['original_paired_plan'],effective_path_bound_paired_plan=a['effective_paired_plan'],
      original_protocol_freeze=a['protocol_frozen_at_utc'],candidate_path_amendment_created_at_utc=a['created_at_utc'],
      candidate_physical_session_start=read(completion['session_report']['path'])['started_at_utc'],
      logical_session_id=a['logical_session_id'],physical_session_directory=a['next_physical_session_root'],
      no_start_receipt=a['failed_session'],failed_physical_launch_navigation_attempts=0,
      editorial_semantics_unchanged=True,original_arm_rerun_or_reuse=False,
      bridge_source=ref(__file__),paired_video_source=ref(video.__file__),amendment_validator_source=ref(amendment.__file__),
      interpretation='The immutable original editorial rule predates evaluation. Only the paired-plan/receipt path binding is derived later under the explicit candidate-only no-start amendment. The original protocol freeze is retained; the replacement candidate must start after the actual amendment. No model, runtime, cohort, ordering, retry cap or clip-selection change is allowed.')


def verify_bridge(request):
    pinned=request.get('external_amendment_bridge')
    need(isinstance(pinned,dict),'Explicit external amendment bridge missing')
    amendment.check_record(pinned['path'],pinned);bridge=read(pinned['path'])
    expected=bridge_expected(bridge['amendment']['path'],bridge['completion_validation']['path'])
    need(bridge==expected,'Bridge provenance or exact path-only proof differs')
    need(request['selection_plan']==read(bridge['effective_path_bound_editorial_plan']['path']),
         'Request is not bound to the exactly derived editorial copy')
    bindings=request['source_bindings']
    need(bindings[0]==bridge['effective_path_bound_editorial_plan'] and bindings[1]==bridge['effective_path_bound_paired_plan'],
         'Request source binding differs from the verified amendment bridge')
    need(request['comparison']['plan_sha256']==bridge['effective_path_bound_paired_plan']['sha256'],
         'Comparison is not bound to the effective plan')
    video.verify_request(request)
    return bridge


def request(args):
    bridge=bridge_expected(args.amendment,args.completion_validation)
    out=args.output.resolve();need(not out.exists(),'Output must be fresh');out.mkdir(parents=True)
    bridge_path=out/'bridge.json';amendment.write(bridge_path,bridge)
    namespace=SimpleNamespace(selection_plan=Path(bridge['effective_path_bound_editorial_plan']['path']),
       paired_plan=Path(bridge['effective_path_bound_paired_plan']['path']),comparison=args.comparison,
       original_analysis=args.original_analysis,candidate_analysis=args.candidate_analysis,
       original_events=args.original_events,candidate_events=args.candidate_events,output=out/'request')
    video.request(namespace)
    request_path=out/'request/request.json';data=read(request_path)
    need('external_amendment_bridge' not in data,'Existing request bridge is unexpected')
    data['external_amendment_bridge']=ref(bridge_path)
    # Add only the explicit external proof; all actual selection/timing fields stay unchanged.
    request_path.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    verify_bridge(data)
    print(json.dumps(dict(request=ref(request_path),bridge=ref(bridge_path),pixels_read=False),indent=2))


def render(args):
    verify_bridge(read(args.request))
    video.render(args)


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='mode',required=True)
    p=sub.add_parser('request')
    for name in ('amendment','completion-validation','comparison','original-analysis','candidate-analysis','original-events','candidate-events','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p=sub.add_parser('render')
    for name in ('request','original-evidence-root','candidate-evidence-root','font','output'):
        p.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();request(args) if args.mode=='request' else render(args)


if __name__=='__main__':main()
