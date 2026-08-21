from __future__ import annotations
import random

def block_bootstrap_calibration_radius(rows:list[tuple[str,float,int]], replicates:int=1000, seed:int=20260820, quantile:float=.90)->float:
    """Season-week block bootstrap of absolute mean calibration gap."""
    if not rows:return 1.0
    blocks={}
    for b,p,y in rows:blocks.setdefault(str(b),[]).append((p,y))
    keys=list(blocks)
    if len(keys)<2:return 0.10
    rng=random.Random(seed); vals=[]
    for _ in range(replicates):
        sample=[]
        for _ in keys: sample.extend(blocks[rng.choice(keys)])
        vals.append(abs(sum(p-y for p,y in sample)/len(sample)))
    vals.sort(); idx=min(len(vals)-1,max(0,int(round((len(vals)-1)*quantile))))
    return float(vals[idx])
