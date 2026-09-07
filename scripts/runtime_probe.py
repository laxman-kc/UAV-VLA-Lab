#!/usr/bin/env python3
"""Exercise imports and a genuine GPU operation, preserving readiness evidence."""
import argparse
import datetime
import importlib
import json
import pathlib
import time


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',required=True)
    args=p.parse_args()
    result={'recorded_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'imports':{}}
    for name in ['torch','torchvision','transformers','peft','accelerate','timm','airsim','msgpackrpc','cv2','numpy','scipy','numba','attr','tensorboard','tkinter']:
        try:
            module=importlib.import_module(name)
            result['imports'][name]={'ok':True,'version':getattr(module,'__version__',None)}
        except Exception as exc:
            result['imports'][name]={'ok':False,'error':repr(exc)}
    try:
        import torch
        torch.cuda.reset_peak_memory_stats()
        start=time.monotonic()
        x=torch.ones((128,128),device='cuda',dtype=torch.bfloat16)
        y=x@x
        torch.cuda.synchronize()
        result['cuda']={'ok':bool(torch.all(y==128).item()),'torch':torch.__version__,'runtime':torch.version.cuda,'gpu':torch.cuda.get_device_name(0),'bf16_supported':torch.cuda.is_bf16_supported(),'seconds':time.monotonic()-start,'peak_allocated_bytes':torch.cuda.max_memory_allocated(),'result_mean':y.float().mean().item()}
    except Exception as exc:
        result['cuda']={'ok':False,'error':repr(exc)}
    result['passed']=all(item['ok'] for item in result['imports'].values()) and result['cuda']['ok']
    out=pathlib.Path(args.output)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['passed'] else 1)


if __name__=='__main__': main()
