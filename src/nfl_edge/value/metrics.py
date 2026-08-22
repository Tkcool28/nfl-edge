from __future__ import annotations
import numpy as np
from sklearn.linear_model import LogisticRegression

def probability_metrics(rows:list[dict])->dict:
    r=[x for x in rows if x.get("p") is not None and x.get("y") in (0,1)]
    if not r:return {"n":0,"brier":None,"log_loss":None,"calibration_intercept":None,"calibration_slope":None}
    p=np.clip(np.asarray([x["p"] for x in r],float),1e-6,1-1e-6);y=np.asarray([x["y"] for x in r],int)
    b=float(np.mean((p-y)**2));ll=float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))
    if len(set(y.tolist()))<2:return {"n":len(r),"brier":b,"log_loss":ll,"calibration_intercept":None,"calibration_slope":None}
    l=np.log(p/(1-p)).reshape(-1,1);m=LogisticRegression(C=1e6,max_iter=2000).fit(l,y)
    return {"n":len(r),"brier":b,"log_loss":ll,"calibration_intercept":float(m.intercept_[0]),"calibration_slope":float(m.coef_[0][0])}

def reliability_table(rows:list[dict],bins:int=10)->list[dict]:
    out=[]
    for i in range(bins):
      lo,hi=i/bins,(i+1)/bins;rr=[r for r in rows if r.get("p") is not None and lo<=r["p"]<(hi if i<bins-1 else hi+1e-9)]
      if rr:out.append({"bin_lo":lo,"bin_hi":hi,"n":len(rr),"mean_p":sum(r["p"] for r in rr)/len(rr),"hit_rate":sum(r["y"] for r in rr)/len(rr)})
    return out
