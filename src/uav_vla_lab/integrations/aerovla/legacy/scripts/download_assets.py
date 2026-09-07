#!/usr/bin/env python3
"""Download a pinned manifest with size/hash verification and resumable transfers."""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import pathlib
import shutil
import subprocess
import time


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def download(asset, root):
    destination = root / asset['category'] / asset['filename']
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.stat().st_size == asset['size_bytes'] and sha256(destination) == asset['sha256']:
            return {'file': str(destination), 'status': 'verified_existing', 'bytes': destination.stat().st_size}
        raise RuntimeError(f'Existing final file failed verification: {destination}')
    partial = destination.with_name(destination.name + '.partial')
    started = time.monotonic()
    print(json.dumps({'event':'download_started','file':asset['filename'],'utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}), flush=True)
    subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error', '--continue-at', '-', '--retry', '4', '--connect-timeout', '30', '--max-time', '3600', '--output', str(partial), asset['url']], check=True)
    actual_hash = sha256(partial)
    if partial.stat().st_size != asset['size_bytes'] or actual_hash != asset['sha256']:
        raise RuntimeError(f'Download verification failed: {partial}')
    partial.rename(destination)
    result = {'file': str(destination), 'status': 'verified', 'bytes': destination.stat().st_size, 'sha256': actual_hash, 'seconds': time.monotonic()-started}
    print(json.dumps(result), flush=True)
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--manifest',required=True)
    p.add_argument('--root',required=True)
    p.add_argument('--workers',type=int,default=2)
    p.add_argument('--reserve-gib',type=int,default=60)
    args=p.parse_args()
    root=pathlib.Path(args.root)
    root.mkdir(parents=True,exist_ok=True)
    manifest=json.loads(pathlib.Path(args.manifest).read_text())
    required=sum(x['size_bytes'] for x in manifest['assets'])
    free=shutil.disk_usage(root).free
    if free < required+args.reserve_gib*1024**3:
        raise RuntimeError(f'Insufficient admission capacity: free={free}, downloads={required}, reserveGiB={args.reserve_gib}')
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        results=list(pool.map(lambda a: download(a,root),manifest['assets']))
    (root/'download-results.json').write_text(json.dumps(results,indent=2)+'\n')


if __name__=='__main__': main()
