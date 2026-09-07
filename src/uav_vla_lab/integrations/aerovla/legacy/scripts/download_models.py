#!/usr/bin/env python3
"""Resolve public model revisions once and download a complete pinned runtime snapshot."""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import pathlib
import subprocess
import urllib.request


def get_json(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',required=True)
    args=p.parse_args()
    root=pathlib.Path(args.root)
    root.mkdir(parents=True,exist_ok=True)
    manifest_path=root/'model-download-manifest.json'
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text())
    else:
        manifest={'resolved_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'repositories':[],'files':[]}
        for repo,folder,prefix in [('openvla/openvla-7b','openvla-7b',None),('XuPeng23/AerialVLA','AerialVLA','aero_vla/')]:
            info=get_json('https://huggingface.co/api/models/'+repo)
            revision=info['sha']
            manifest['repositories'].append({'repository':repo,'revision':revision,'folder':folder})
            for item in info['siblings']:
                name=item['rfilename']
                if prefix and not name.startswith(prefix): continue
                if name.startswith('.') or name.endswith(('.png','.jpg','.gif','.mp4')): continue
                manifest['files'].append({'repository':repo,'revision':revision,'relative_path':folder+'/'+name,'url':'https://huggingface.co/'+repo+'/resolve/'+revision+'/'+name})
        manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    def download(item):
        target=root/item['relative_path']
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            partial=target.with_name(target.name+'.partial')
            print('Downloading '+item['relative_path'],flush=True)
            subprocess.run(['curl','--fail','--location','--silent','--show-error','--continue-at','-','--retry','4','--connect-timeout','30','--max-time','3600','--output',str(partial),item['url']],check=True)
            partial.rename(target)
        return {**item,'bytes':target.stat().st_size,'sha256':digest(target)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(download,manifest['files']))
    (root/'model-files.verified.json').write_text(json.dumps(results,indent=2)+'\n')
    print('Model snapshots downloaded and locally hashed.',flush=True)


if __name__=='__main__': main()
