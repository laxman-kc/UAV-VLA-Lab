#!/usr/bin/env python3
"""Select bounded P13/P14 evidence from an existing comparison; never evaluate policies.

`request` reads metadata/events only and lists exact PNGs to copy. `render` verifies
those PNGs and produces explicitly derived table/cards and two-panel technical
figures for the existing release builder. Neither operation approves a result.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import compare_navigation as comparison_contract
from summarize_navigation import check_event_links

SUPPORTED_RULE_SHA256 = 'ff0d8610683498f25f822ca8010a4ff85e60a3152ae2995ec03ba5aa091b84e9'


def validate_rule(plan):
    rule={k:plan.get(k) for k in ('table','clip_selection','mapping')}
    digest=hashlib.sha256(json.dumps(rule,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    require(digest==SUPPORTED_RULE_SHA256,'Unsupported editorial rule; frozen rule fields differ from implemented semantics')


def require(value, message):
    if not value:
        raise ValueError(message)


def record(path):
    path = Path(path).resolve()
    return {"path": str(path), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def read(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 128*1024*1024,
            "Input must be a bounded regular file")
    return comparison_contract.json_bytes(path.read_bytes())


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False)+"\n")


def safe_relative(value):
    require(isinstance(value, str) and "\\" not in value, "Invalid image path")
    p = PurePosixPath(value)
    require(p.parts and not p.is_absolute() and ".." not in p.parts, "Unsafe image path")
    return p


def choose(rows):
    """Outcome categories use SR only, in already validated declared order."""
    chosen, absent = [], []
    for label, flags in (("original_only_success", (True, False)),
                         ("candidate_only_success", (False, True))):
        row = next((r for r in rows if r["matched_valid_pair"] and
                    (r["original_upstream_success"], r["candidate_upstream_success"]) == flags), None)
        if row is None:
            absent.append(label)
        else:
            chosen.append({"category": label, "trial": row})
    if not chosen:
        row = next((r for r in rows if r["matched_valid_pair"] and
                    r["original_upstream_success"] == r["candidate_upstream_success"]), None)
        if row:
            chosen.append({"category": "first_same_sr_outcome_fallback", "trial": row})
    return chosen, absent


def selected_indices(first, second):
    common = sorted(set(first) & set(second))
    return list(dict.fromkeys(common[i] for i in (0, (len(common)-1)//2, len(common)-1))) if common else []


def load_events(path):
    require(Path(path).stat().st_size <= 128*1024*1024, "Event input exceeds bound")
    groups, identifiers = {}, set()
    with Path(path).open() as f:
        for line_number, line in enumerate(f, 1):
            event = comparison_contract.json_bytes(line)
            key = (event.get("run_id"), event.get("event_id"))
            require(type(key[1]) is int and key not in identifiers, "Missing or duplicate event identifier")
            identifiers.add(key)
            event["_source_line"] = line_number
            if event.get("attempt_id"):
                groups.setdefault(event["attempt_id"], []).append(event)
    return groups


def attempt_observations(events, attempt):
    starts = [e for e in events if e["event_type"] == "episode.start"]
    ends = [e for e in events if e["event_type"] == "episode.completed"]
    require(len(starts) == len(ends) == 1, "Selected attempt must have one start/completion")
    start, end = starts[0], ends[0]
    require(start["event_id"] == attempt["start_event_id"], "Attempt start differs from analyzed attempt")
    require(all(e.get(k) == start.get(k) for e in events for k in
                ("run_id", "map_name", "episode_id", "attempt_id")), "Event attempt context differs")
    # The released recorder retains the final attempt context on run cleanup.
    # Preserve those records, but do not count them as navigation observations.
    outside = [e for e in events if not start['_source_line'] <= e['_source_line'] <= end['_source_line']]
    require(all(e['_source_line'] > end['_source_line'] and e['event_type'] in
                {'cleanup.scenes_closed', 'run.end'} for e in outside), "Unexpected event outside attempt boundary")
    events = [e for e in events if start['_source_line'] <= e['_source_line'] <= end['_source_line']]
    require(not check_event_links(events, start, end, attempt["raw_outcome"]), "Selected causal event chain is invalid")
    require(all(end.get(k) == v for k, v in attempt["raw_outcome"].items()), "Terminal event differs from audited outcome")
    by_id = {e['event_id']: e for e in events}
    result, completed, last_id = {}, 0, -1
    for e in events:
        require(e["event_id"] > last_id, "Events are not in strict source order")
        last_id = e["event_id"]
        if e["event_type"] == "action.completed":
            completed += 1
        elif e["event_type"] == "observation.prepared":
            require(completed == len(result), "Observation indices are duplicated or noncontiguous")
            front = [i for i in e["images"] if i.get("camera") == "front" and i.get("modality") == "rgb"]
            require(len(front) == 1, "Exactly one actual front RGB reference is required")
            safe_relative(front[0]["path"])
            require(comparison_contract.hash_value(front[0].get("sha256")), "Image digest missing")
            origin, now = start.get("host_monotonic_ns"), e.get("host_monotonic_ns")
            elapsed = (now-origin)/1e9 if type(origin) is int and type(now) is int and now >= origin else None
            capture, front_response, request_mapping = None, None, None
            if e.get('image_capture_event_id') is not None:
                capture = by_id.get(e['image_capture_event_id'])
                require(capture and capture['event_type']=='images.received' and capture['event_id']<e['event_id'],
                        'Observation capture link is invalid')
                matches = [c for c in events if c['event_type']=='reset_protocol.image_capture' and
                           capture['event_id'] < c['event_id'] < e['event_id'] and c.get('responses')==capture.get('responses')]
                require(len(matches)==1, 'Unique recorded camera request/response mapping is required')
                request_mapping=matches[0]
                requests,responses=request_mapping['requests'],request_mapping['responses']
                require(len(requests)==len(responses)==10, 'Expected the actual ten-camera/modality responses')
                fronts=[response for request,response in zip(requests,responses) if
                        request.get('camera_name')=='FrontCamera' and request.get('image_type')==0]
                require(len(fronts)==1 and fronts[0].get('image_type')==0,'Front RGB response mapping is ambiguous')
                front_response=fronts[0]
            camera_time=front_response.get('time_stamp') if front_response else None
            result[completed] = {"decision_index": completed, "index_derivation": "completed actions preceding observation",
                "observation_event_id": e["event_id"], "run_id": e["run_id"], "attempt_id": e["attempt_id"],
                "episode_id": e["episode_id"], "map_name": e["map_name"], "image": front[0],
                "host_elapsed_since_episode_start_seconds": elapsed, "host_monotonic_ns": now,
                "wall_time_utc": e.get("wall_time_utc"), "camera_timestamp": camera_time,
                "camera_timestamp_note": "Actual linked FrontCamera Scene response when available; never inferred from state or host time",
                "image_capture_event": capture, "camera_request_mapping_event": request_mapping,
                "front_camera_response": front_response,
                "state_timestamp": e.get("sensors", {}).get("state", {}).get("timestamp"),
                "state_position": e.get("sensors", {}).get("state", {}).get("position"),
                "sampled_endpoint_contact": e.get("sensors", {}).get("state", {}).get("collision", {}).get("has_collided"),
                "is_terminal_observation": completed == attempt["raw_outcome"]["step"]}
    require(result and completed == len(result)-1 == attempt["raw_outcome"]["step"], "Terminal observation index mismatch")
    return result


def request(args, persist=True):
    paths = [args.selection_plan, args.paired_plan, args.comparison, args.original_analysis,
             args.candidate_analysis, args.original_events, args.candidate_events]
    bindings = [record(p) for p in paths]
    plan, paired, comparison = read(args.selection_plan), read(args.paired_plan), read(args.comparison)
    validate_rule(plan)
    require(plan["schema_version"] == "vla.paired-video-selection-plan.v1" and plan["phase"] == paired["phase"] and paired["phase"] in {'P13', 'P14'},
            "This helper supports explicitly frozen P13 development or P14 confirmation videos")
    require(plan["candidate_outcomes_inspected_before_freeze"] is False, "Outcome-blind selection declaration missing")
    require(plan["paired_plan"]["sha256"] == record(args.paired_plan)["sha256"], "Video plan pins different paired plan")
    require(plan["missions"] == paired["missions"], "Video/paired ordered missions differ")
    require(comparison_contract.instant(plan["frozen_at_utc"]) < comparison_contract.instant(comparison["generated_at_utc"]),
            "Video plan must precede the completed comparison")
    # Recompute the small comparator contract; no new raw-image/model evaluation.
    checked = comparison_contract.compare(args.paired_plan, args.original_analysis, args.candidate_analysis)
    for key in ("schema_version", "plan_id", "plan_sha256", "phase", "split_group", "contract_status", "selection_decision",
                "planned_pairs", "matched_valid_pairs", "unmatched_or_invalid_pairs", "arm_counts", "success",
                "oracle_success", "trials", "arms", "attempts"):
        require(checked[key] == comparison[key], "Copied comparison differs from rechecked metadata: "+key)
    analyses = {role: read(getattr(args, role+"_analysis")) for role in ("original", "candidate")}
    groups = {}
    for role in analyses:
        path = getattr(args, role+"_events"); rec = record(path)
        require(any(r["sha256"] == rec["sha256"] and r["bytes"] == rec["bytes"] for r in analyses[role]["source_files"]),
                "Event bytes are not represented in the analyzed source inventory")
        groups[role] = load_events(path)
    chosen, absent = choose(comparison["trials"])
    pairs, requested, chains = [], {}, {"original": {}, "candidate": {}}
    for choice in chosen:
        row = choice["trial"]; observations = {}
        for role in groups:
            attempt_id = row[role+"_selected_attempt_id"]
            matches = [a for a in analyses[role]["attempts"] if a.get("attempt_id") == attempt_id and
                       a.get("session_id") == row[role+"_selected_session_id"]]
            require(len(matches) == 1 and matches[0]["joint_valid"] is True, "Selected attempt lacks valid audit")
            ev = groups[role].get(attempt_id, [])
            observations[role] = attempt_observations(ev, matches[0])
            chains[role][attempt_id] = ev
        common = selected_indices(observations["original"], observations["candidate"])
        indices = [(i, i, "common_derived_decision_index") for i in common]
        final = tuple(max(observations[role]) for role in ("original", "candidate"))
        if common and final != (common[-1], common[-1]):
            indices.append((*final, "separate_terminal_observations"))
        for old, new, alignment in indices:
            panels = {role: observations[role][i] for role, i in (("original", old), ("candidate", new))}
            pairs.append({"id": f"mission-{row['ordinal']:02d}-{len(pairs)+1:02d}", "category": choice["category"],
                          "trial": row, "alignment": alignment, "panels": panels})
            for role, panel in panels.items():
                image = panel["image"];key = (role, image["path"])
                require(key not in requested or requested[key]["sha256"] == image["sha256"], "Conflicting selected image")
                requested[key] = {"arm": role, "relative_path": image["path"], "sha256": image["sha256"]}
    require(bindings == [record(p) for p in paths], "Input mutated during selection")
    result = {"schema_version": "vla.paired-video-request.v1", "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "selection_plan": plan, "source_bindings": bindings, "comparison": comparison, "selected_categories": chosen,
              "absent_categories": absent, "pairs": pairs, "requested_images": list(requested.values()),
              "renderer_source": record(__file__), "supported_editorial_rule_sha256":SUPPORTED_RULE_SHA256,
              "causal_contract_source":record(check_event_links.__code__.co_filename),
              "comparison_contract_source":record(comparison_contract.__file__),
              "limitation": "Metadata/causal checks only; no selected pixels read or visual review attested."}
    if not persist:
        return result
    require(not args.output.exists(), "Output must be fresh");args.output.mkdir(parents=True)
    for role, attempts in chains.items():
        for ident, events in attempts.items():
            write(args.output/f"{role}-{ident}-events.json", events)
    write(args.output/"request.json", result)
    print(json.dumps({"request": str(args.output/"request.json"), "pairs": len(pairs), "png_files": len(requested), "absent": absent}))


def verify_request(r):
    """Re-derive selection from bound metadata/events before decoding any pixels."""
    names=('selection_plan','paired_plan','comparison','original_analysis','candidate_analysis','original_events','candidate_events')
    require(len(r['source_bindings'])==len(names),'Request source bindings are incomplete')
    args=SimpleNamespace(**{name:Path(rec['path']) for name,rec in zip(names,r['source_bindings'])})
    for rec in r['source_bindings']:
        require(record(rec['path'])==rec,'Request source bytes changed before render')
    expected=request(args,persist=False)
    for key in expected:
        if key!='generated_at_utc':
            require(r.get(key)==expected[key],'Request selection/provenance differs from re-derived evidence: '+key)


def render(args):
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    request_record = record(args.request);r = read(args.request)
    require(r["schema_version"] == "vla.paired-video-request.v1", "Unsupported image request")
    verify_request(r)
    require(not args.output.exists(), "Output must be fresh")
    font = Path(args.font);require(font.is_file(), "Explicit existing font file required")
    fonts = {size: ImageFont.truetype(str(font), size) for size in (16, 18, 20, 24)}
    image_records, decoded = {}, {}
    for item in r["requested_images"]:
        root = getattr(args, item["arm"]+"_evidence_root").resolve()
        path = root / safe_relative(item["relative_path"])
        require(path.resolve().is_relative_to(root) and not path.is_symlink(), "Selected image escapes evidence root")
        rec = record(path);require(rec["sha256"] == item["sha256"], "Selected image SHA256 mismatch")
        with Image.open(path) as image:
            require(image.format == "PNG" and getattr(image, "n_frames", 1) == 1, "Only actual single PNGs supported")
            decoded[(item["arm"], item["relative_path"])] = image.convert("RGB")
        image_records[(item["arm"], item["relative_path"])] = rec
    args.output.mkdir(parents=True);events=[];figures=[]
    def canvas():
        image=Image.new("RGB", (770,440), "#101827");return image, ImageDraw.Draw(image)
    def text(draw,xy,value,size=18,color="#e2e8f0"):
        require(draw.textlength(value,font=fonts[size]) <= 750-xy[0], "Figure line exceeds width")
        draw.text(xy,value,font=fonts[size],fill=color)
    def save(image,ident,seconds,caption,kind,metadata):
        path=args.output/(ident+".png");image.save(path,"PNG")
        rec=record(path);figures.append({"id":ident,"kind":kind,"image":rec,**metadata})
        events.append({"id":ident,"source":str(path.resolve()),"display_seconds":seconds,"caption":caption,
            "run_id":r["comparison"]["phase"]+" paired comparison", "attempt_id":"paired; see source mapping", "observation_id":ident,
            "camera":"derived comparison table" if kind != "paired_front_rgb" else "front RGB pair",
            "checkpoint_id":"original | P12 candidate", "mission_id":metadata.get("mission_prefix", "all declared missions"),
            "map_id":metadata.get('map_name', ' / '.join(sorted({row['map_name'] for row in r['comparison']['trials']}))),
            "task_mode":"index alignment; editorial holds", "camera_timestamp":None,
            "requested_action":None,"applied_action":None,"termination_reason":None})
    image,d=canvas()
    for y,line in enumerate((r["comparison"]["phase"]+" / FIXED PAIRED COMPARISON", f"All {len(r['comparison']['trials'])} planned pairs remain in the table.",
                            "Original left / candidate right.", "Matched by derived decision index, not flight time.",
                            "Each panel shows its own host elapsed time.", "Static holds; no synchronized-flight claim.")):
        text(d,(12,25+y*55),line,20 if y==0 else 18)
    save(image,"intro",6,"Derived comparison guide. Actual camera pairs follow the declared selection rule.","derived_card",{})
    rows=r["comparison"]["trials"]
    def fmt(value, precision=None):
        if value is None:return "NA"
        if type(value) is bool:return "Y" if value else "N"
        return f"{value:.{precision}f}" if precision is not None else str(value)
    for offset in range(0,len(rows),5):
        image,d=canvas();text(d,(10,12),f"ALL PLANNED PAIRS / {offset+1}-{min(offset+5,len(rows))} OF {len(rows)}",20)
        text(d,(10,50),"Mission      SR O/C  OSR O/C  Step O/C   Distance m O/C",18)
        for i,row in enumerate(rows[offset:offset+5]):
            pair=lambda field,p=None:fmt(row['original_'+field],p)+"/"+fmt(row['candidate_'+field],p)
            line=f"{row['ordinal']:02d} {row['episode_id'][:8]}  {pair('upstream_success'):<7} {pair('upstream_osr_success'):<8} {pair('terminal_loop_index'):<10} {pair('distance_to_spawned_target_m',2)}"
            text(d,(10,94+i*53),line,18)
        text(d,(10,377),"O=original; C=candidate; NA=unavailable, never failure.",18)
        text(d,(10,405),"Derived result table. Distances rounded; exact values in JSON.",16)
        save(image,f"all-pairs-{offset//5+1}",10,"All planned pairs in declared order. SR is upstream navigation success; OSR includes oracle.","derived_table",{"rows":rows[offset:offset+5]})
    for category in r["absent_categories"]:
        image,d=canvas();text(d,(10,90),"ABSENT CATEGORY",24)
        text(d,(10,155),category.replace('_',' '),20)
        text(d,(10,220),"No matched valid pair in this category.",18)
        text(d,(10,265),"No favorable substitute was selected.",18)
        save(image,"absent-"+category,4,"Explicit absent category under the frozen SR selection rule.","derived_card",{})
    if not r["pairs"]:
        image,d=canvas();text(d,(10,140),"No eligible paired image indices are available.",20)
        save(image,"no-paired-imagery",4,"Missing or invalid image pairing is retained as unavailable.","derived_card",{})
    for pair in r["pairs"]:
        image,d=canvas();placements={};row=pair["trial"]
        for role,x in (("original",5),("candidate",395)):
            panel=pair["panels"][role];source=decoded[(role,panel["image"]["path"])];fit=ImageOps.contain(source,(365,320),Image.Resampling.BICUBIC)
            rect=(x+(365-fit.width)//2,60+(320-fit.height)//2);image.paste(fit,rect)
            text(d,(x,5),role.upper()+f" / index {panel['decision_index']}",18)
            elapsed=panel['host_elapsed_since_episode_start_seconds'];clock="unavailable" if elapsed is None else f"{elapsed:.3f}s"
            text(d,(x,30),"Own host elapsed: "+clock,16)
            text(d,(x,386),"Terminal view: "+fmt(panel['is_terminal_observation']),16)
            placements[role]={"source":image_records[(role,panel["image"]["path"])],"source_dimensions":list(source.size),
                              "rectangle_xywh":[*rect,fit.width,fit.height],"filter":"Pillow BICUBIC; aspect ratio preserved",**panel}
        text(d,(5,416),"Different flight paths and elapsed times; static 6-second hold.",16)
        caption=("Separate final observations; each arm's own terminal decision index is shown." if pair['alignment']=='separate_terminal_observations' else "Same derived decision index. Images are not time-synchronized or pose-matched.")
        save(image,pair['id'],6,caption,"paired_front_rgb",{"mission_prefix":row['episode_id'][:12],"map_name":row['map_name'],"category":pair['category'],"alignment":pair['alignment'],"panels":placements})
    require(request_record==record(args.request),"Request changed during rendering")
    for rec in image_records.values():require(record(rec['path'])==rec,"Source PNG changed during rendering")
    population={"schema_version":"vla.paired-figure-population.v1","request":request_record,"all_planned_trials":rows,
                "complete_attempts":r['comparison']['attempts'],"selected_figures":figures,"font":record(font),
                "renderer_source":record(__file__),"visual_review_status":"not_reviewed","image_content":"Deterministic technical figures, not camera-original files. Both original input PNG hashes and panel rectangles are retained."}
    write(args.output/'population.json',population)
    write(args.output/'video.json',{'kind':'observations','fps':10,'population_ref':str((args.output/'population.json').resolve()),
          'selection_rule':'Frozen '+r['comparison']['phase']+' paired video rule; derived table/cards plus original/candidate genuine front PNG technical pairs. Static holds and derived index alignment; no synchronized flight.', 'events':events})
    print(json.dumps({'output':str(args.output),'figures':len(figures),'duration_seconds':sum(e['display_seconds'] for e in events)}))


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='mode',required=True)
    req=sub.add_parser('request')
    for name in ('selection-plan','paired-plan','comparison','original-analysis','candidate-analysis','original-events','candidate-events','output'):
        req.add_argument('--'+name,type=Path,required=True)
    render_parser=sub.add_parser('render')
    for name in ('request','original-evidence-root','candidate-evidence-root','font','output'):
        render_parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    try:(request if args.mode=='request' else render)(args)
    except (OSError,ValueError,KeyError,TypeError) as exc:parser.exit(1,'Paired video rejected: '+str(exc)+'\n')


if __name__=='__main__':main()
