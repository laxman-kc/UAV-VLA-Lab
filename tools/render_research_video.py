#!/usr/bin/env python3
"""Render a silent 72-second overview from public study charts and numeric evidence."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import textwrap

from verify_research_figures import verify_figure_provenance

ROOT=Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(output):
    figure_verification = verify_figure_provenance()
    checked = figure_verification['numeric_validation']
    from PIL import Image, ImageDraw, ImageFont
    import matplotlib
    from render_research_figures import DEFAULT_STUDY
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('FFmpeg and ffprobe are required')
    output.mkdir(parents=True,exist_ok=True)
    fonts=Path(matplotlib.get_data_path())/'fonts/ttf'
    def font(size,bold=False): return ImageFont.truetype(str(fonts/('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')),size)
    navy='#102c3b';teal='#087e83';gray='#526874';paper='#fcfcfa'
    scenes=[
      ('UAV-VLA-Lab',None,['A complete, inspectable UAV policy experiment.','25 published demonstrations. One fixed adapted candidate.','20 development pairs + 10 holdout pairs.'], 'AeroVLA policy / TravelUAV simulation / ordinary demonstration SFT'),
      ('What changed after adaptation?','outcome-rates',['One additional navigation success in each cohort.','Holdout oracle success decreased by one mission.'], 'Exact counts from the completed study; small, correlated, single-map cohorts.'),
      ('Keep gains and regressions visible','paired-transitions',['The paired record includes all 30 missions.'], 'Net success changes alone would hide policy reversals and oracle-success regressions.'),
      ('Training fit is a separate measurement','training-fit',['25 updates; one exposure per source row; exact saved-checkpoint reload.'], 'Training-row loss is not held-out accuracy or navigation quality.'),
      ('Why this workflow is useful',None,['Check reset, camera and controller behavior before scoring.','Trace the parent, data, updates and evaluated checkpoint.','Retain failed starts, all attempts and paired outcomes.','Recompute the results from their public numerical sources.'], f"{checked['total_recorded_actions']:,} completed actions and {checked['total_recorded_observations']:,} observations reconcile in the retained scored runs."),
      ('Inspect. Reproduce. Extend.',None,['Read the technical report and model/data cards.','Download the 60 episode rows, 30 pairs and 25 update rows.','Inspect the charts, report, and recorded gains and regressions.','Declare a new protocol before collecting new results.'], 'github.com/laxman-kc/UAV-VLA-Lab')]
    records=[];inputs=[]
    for i,(title,chart,lines,note) in enumerate(scenes,1):
        im=Image.new('RGB',(1920,1080),paper);d=ImageDraw.Draw(im)
        d.rectangle((0,0,1920,14),fill=teal)
        d.text((100,61),'UAV-VLA-LAB / RESEARCH RECORD',font=font(23,True),fill=teal)
        d.text((100,110),title,font=font(53,True),fill=navy)
        if chart:
            p=ROOT/'docs/assets/figures/simulation-sft-v1'/f'{chart}.png';inputs.append(p)
            with Image.open(p) as raw:
                picture=raw.convert('RGB');picture.thumbnail((1720,650),Image.Resampling.LANCZOS)
            im.paste(picture,((1920-picture.width)//2,201))
            y=877
            for text in lines:
                d.text((100,y),text,font=font(25,True),fill=navy);y+=39
        else:
            y=295
            for text in lines:
                d.rounded_rectangle((100,y+5,111,y+39),radius=4,fill=teal)
                d.text((139,y),text,font=font(34),fill=navy);y+=123
        d.text((100,963),note,font=font(22),fill=gray)
        d.line((100,1007,1820,1007),fill='#dbe4e5',width=2)
        d.text((100,1026),'STATIC RESEARCH EXPLANATION / NO NEW FLIGHT FOOTAGE / NO AUDIO',font=font(18),fill=gray)
        d.text((1730,1026),f'{i} / {len(scenes)}',font=font(18),fill=gray)
        path=output/f'scene-{i:02}.png';im.save(path)
        records.append({'scene':i,'title':title,'start_seconds':(i-1)*12,'nominal_duration_seconds':12,'frame':path.name,'sha256':digest(path)})
    concat=output/'scenes.ffconcat'
    concat.write_text('ffconcat version 1.0\n'+''.join(f"file '{r['frame']}'\nduration 12\n" for r in records)+f"file '{records[-1]['frame']}'\n")
    video=output/'research-overview.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','concat','-safe','1','-i',str(concat.resolve()),'-t','72','-r','25','-c:v','libx264','-preset','medium','-tune','stillimage','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',str(video.resolve())],check=True)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(video)]))
    streams=probe['streams']; v=next(s for s in streams if s['codec_type']=='video')
    if len(streams)!=1 or v['width']!=1920 or v['height']!=1080 or abs(float(probe['format']['duration'])-72)>0.05:
        raise ValueError('Unexpected overview media properties')
    subprocess.run(['ffmpeg','-v','error','-i',str(video),'-f','null','-'],check=True)
    inputs += [DEFAULT_STUDY/'results/aggregate.json',DEFAULT_STUDY/'results/training-summary.json']
    manifest={'schema_version':'uav-vla-lab.research-overview.v1','scope':'Silent static chart/text explanation of existing public numeric research evidence; no new model, simulator or flight execution',
      'selection':'Six predeclared explanatory scenes, nominal12seconds each; no selective flight footage', 'numeric_validation':checked,
      'figure_verification':figure_verification,
      'renderer':{'file':'tools/render_research_video.py','sha256':digest(Path(__file__))},
      'sources':[{'file':p.relative_to(ROOT).as_posix(),'sha256':digest(p)} for p in inputs], 'scenes':records,
      'output':{'file':video.name,'bytes':video.stat().st_size,'sha256':digest(video),'nominal_duration_seconds':72,'duration_seconds':float(probe['format']['duration']),'frame_count':int(v['nb_frames']),'width':1920,'height':1080,'audio':False},
      'technical_checks':['ffprobe dimensions/duration/audio contract passed','full FFmpeg decode passed'],'visual_review':'Pending inspection of actual rendered scene PNGs and sampled encoded frames'}
    (output/'overview-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest['output']))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'output/media')
    build(p.parse_args().output)
