from __future__ import annotations
from dataclasses import dataclass
@dataclass(frozen=True)
class ReliabilityEvidence:
    support_n:int; uncertainty:float; support_distance:float=0.0; constituent_disagreement:float=0.0; stable_blocks:bool=True

def tier(e:ReliabilityEvidence)->str:
    if e.support_n<128 or e.support_distance>0.10 or not e.stable_blocks:return "UNSUPPORTED"
    if e.support_n>=512 and e.uncertainty<=0.025 and e.constituent_disagreement<=0.08:return "HIGH"
    if e.support_n>=256 and e.uncertainty<=0.045 and e.constituent_disagreement<=0.15:return "MEDIUM"
    return "LOW"

def staking_probability(actionable:float, anchor:float, reliability:str, uncertainty:float)->float:
    haircut={"HIGH":1.0,"MEDIUM":.70,"LOW":.35,"UNSUPPORTED":0.0}[reliability]
    uncertainty_factor=max(0.0,1.0-min(1.0,uncertainty/0.10))
    return anchor + haircut*uncertainty_factor*(actionable-anchor)
