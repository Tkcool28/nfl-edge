from __future__ import annotations
import numpy as np
from sklearn.linear_model import LogisticRegression
from .contracts import EvaluatorState
from .uncertainty import block_bootstrap_calibration_radius

def fit_global_lambda(model:list[float],market:list[float],y:list[int])->float:
    d=np.asarray(model)-np.asarray(market); r=np.asarray(y)-np.asarray(market); den=float(d@d)
    return 0.0 if den<=1e-12 else float(np.clip((d@r)/den,0.0,1.0))
def _lr(X,y,C=.05):
    m=LogisticRegression(C=C,max_iter=2000,solver="lbfgs").fit(np.asarray(X),np.asarray(y));return float(m.intercept_[0]),[float(v) for v in m.coef_[0]]
def fit_ml_states(rows:list[dict],version:str,config_sha:str)->dict[str,EvaluatorState]:
    usable=[r for r in rows if r.get("qb") is not None and r.get("xgb") is not None and r.get("pin") is not None]
    n=len(usable); avg=[(r["qb"]+r["xgb"])/2 for r in usable]; pin=[r["pin"] for r in usable]; y=[int(r["y"]) for r in usable]
    lam=fit_global_lambda(avg,pin,y) if n else 0.0
    base={"pinnacle":EvaluatorState("moneyline","pinnacle",version,n,{},config_sha256=config_sha),"raw_qbelo":EvaluatorState("moneyline","raw_qbelo",version,n,{},config_sha256=config_sha),"raw_xgb":EvaluatorState("moneyline","raw_xgb",version,n,{},config_sha256=config_sha),"exact_avg":EvaluatorState("moneyline","exact_avg",version,n,{},config_sha256=config_sha)}
    boot=block_bootstrap_calibration_radius([(r["block"],a,r["y"]) for r,a in zip(usable,avg)]) if n else 1.0
    base["global_shrinkage"]=EvaluatorState("moneyline","global_shrinkage",version,n,{"lambda":lam},uncertainty=boot,config_sha256=config_sha)
    pars={"lambda_global":lam}
    for reg,lo,hi in (("low",0,.4),("mid",.4,.6000001),("high",.6000001,1.01)):
      for band in ("small","large"):
        rr=[(a,p,yy) for a,p,yy in zip(avg,pin,y) if lo<=p<hi and ((abs(a-p)<.05)==(band=="small"))]
        local=fit_global_lambda([a for a,_,_ in rr],[p for _,p,_ in rr],[yy for *_,yy in rr]) if len(rr)>=64 else lam
        w=len(rr)/(len(rr)+128);pars[f"lambda_{reg}_{band}"]=w*local+(1-w)*lam
    base["reliability_aware_shrinkage"]=EvaluatorState("moneyline","reliability_aware_shrinkage",version,n,pars,uncertainty=boot,config_sha256=config_sha)
    if n>=128:
      X=[[r["qb"],r["xgb"],r["pin"],abs(r["qb"]-r["xgb"]),((r["qb"]+r["xgb"])/2-r["pin"])] for r in usable];it,co=_lr(X,y)
      base["strong_logistic"]=EvaluatorState("moneyline","strong_logistic",version,n,{"intercept":it,"coef":co},uncertainty=boot,config_sha256=config_sha)
    return base

def fit_point_states(rows:list[dict],market_type:str,version:str,config_sha:str)->dict[str,EvaluatorState]:
    n=len(rows); residual=[float(r["residual"]) for r in rows];sigma=float(np.std(residual,ddof=1)) if n>1 else 14.0
    sigma=max(sigma,1e-6); z=[float(r["delta"])/sigma for r in rows]; y=[int(r["y"]) for r in rows]
    boot=block_bootstrap_calibration_radius([(r["block"],.5,r["y"]) for r in rows]) if n else 1.0
    out={"normal_cdf":EvaluatorState(market_type,"normal_cdf",version,n,{"sigma":sigma},uncertainty=boot,config_sha256=config_sha)}
    if n>=128:
      it,co=_lr([[v] for v in z],y);out["calibrated_normal"]=EvaluatorState(market_type,"calibrated_normal",version,n,{"sigma":sigma,"intercept":it,"slope":co[0]},uncertainty=boot,config_sha256=config_sha)
      X=[[r["delta"],r["market_level"]] for r in rows];it2,co2=_lr(X,y);out["strong_logistic"]=EvaluatorState(market_type,"strong_logistic",version,n,{"sigma":sigma,"intercept":it2,"coef":co2},uncertainty=boot,config_sha256=config_sha)
    return out
