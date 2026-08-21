#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
import polars as pl, yaml
from nfl_edge.market_data.matching import _NAME_TO_ABBR
from nfl_edge.value.contracts import GameState,NormalizedOffer
from nfl_edge.value.evaluators import evaluate_offer
from nfl_edge.value.fitting import fit_ml_states,fit_point_states
from nfl_edge.value.market_math import proportional_no_vig,shop_moneyline,shop_spread,shop_total
from nfl_edge.value.metrics import probability_metrics,reliability_table
ROOT=Path(__file__).resolve().parents[1]
DEV=[2020,2021,2022,2023,2024]; SEALED={2025}; VERSION="market_evaluator_v1"

def cfg_load(path:Path):
    raw=path.read_bytes();cfg=yaml.safe_load(raw);return cfg,hashlib.sha256(raw).hexdigest()
def season_from_gid(gid:str)->int:return int(str(gid).split("_",1)[0])
def assert_not_sealed_seasons(seasons)->None:
    bad=SEALED.intersection({int(s) for s in seasons})
    if bad:raise RuntimeError(f"SEALED season requested before materialization: {sorted(bad)}")
def _safe_scan(path:Path, cols:list[str])->pl.LazyFrame:
    return pl.scan_parquet(path).select(cols).filter(pl.col("season").is_in(DEV))
def _grade_ml(side,hs,as_):return int((hs>as_) if side=="home" else (as_>hs))
def _grade_sp(side,line,hs,as_):
    m=(hs-as_) if side=="home" else (as_-hs);v=m+line;return None if abs(v)<1e-9 else int(v>0)
def _grade_total(side,line,hs,as_):
    v=(hs+as_-line) if side=="over" else (line-hs-as_);return None if abs(v)<1e-9 else int(v>0)
def _block_key(season,week):return f"{int(season):04d}-{str(week).zfill(2)}"

def build_inputs(root:Path):
    qe=_safe_scan(root/"data/modeling/development_v1/qb_elo_predictions_2018_2024.parquet",["game_id","season","week","predicted_home_win_probability"]).rename({"predicted_home_win_probability":"qbelo_home"})
    xb=_safe_scan(root/"data/modeling/development_v1/chronology_corrected/xgboost_candidate_predictions_2018_2024.parquet",["candidate_id","game_id","season","week","warmup","prediction_probability"]).filter(pl.col("candidate_id")=="conservative").with_columns(pl.when(pl.col("warmup")).then(None).otherwise(pl.col("prediction_probability")).alias("xgb_home")).select(["game_id","xgb_home"])
    em=_safe_scan(root/"data/modeling/development_v1/expected_margin_predictions_2018_2024.parquet",["candidate_id","game_id","season","week","expected_home_margin"]).filter(pl.col("candidate_id")=="stable").select(["game_id","expected_home_margin"])
    r4=pl.scan_parquet(root/"reports/task05d/task05d_ridge_predictions.parquet").select(["candidate_id","game_id","season","week","predicted_total"]).filter((pl.col("candidate_id")=="R4") & pl.col("season").is_in(DEV)).select(["game_id","predicted_total"])
    out=_safe_scan(root/"data/frozen/games/games_2018_2025.parquet",["game_id","season","home_score","away_score"])
    df=qe.join(xb,on="game_id",how="left").join(em,on="game_id",how="left").join(r4,on="game_id",how="left").join(out,on=["game_id","season"],how="inner").collect()
    assert_not_sealed_seasons(df["season"].unique().to_list())
    return {r["game_id"]:r for r in df.to_dicts()}

def build_market(root:Path,games:dict):
    cg=pl.read_parquet(root/"data/market_data/canonical/canonical_games.parquet").filter(pl.col("game_id").is_in(list(games))).select(["game_id","home_abbr","away_abbr"])
    sides={r["game_id"]:(r["home_abbr"],r["away_abbr"]) for r in cg.to_dicts()}
    bm=pl.read_parquet(root/"data/market_data/canonical/canonical_book_market.parquet").filter(pl.col("game_id").is_in(list(games)))
    idx={}
    for r in bm.to_dicts():
        book=r.get("bookmaker_key");mk=r.get("market_key");gid=r.get("game_id")
        if book not in {"draftkings","fanduel","pinnacle"} or mk not in {"h2h","spreads","totals"}:continue
        if mk=="totals":side=str(r.get("outcome_name","")).strip().lower()
        else:
            ab=_NAME_TO_ABBR.get(str(r.get("outcome_name","")).strip()); h,a=sides.get(gid,(None,None));side="home" if ab==h else "away" if ab==a else None
        if side is None:continue
        mt={"h2h":"moneyline","spreads":"spread","totals":"total"}[mk]
        try:o=NormalizedOffer(mt,side,book,int(r["american_price"]),None if mt=="moneyline" else float(r["point"]),str(r.get("snapshot_utc") or r.get("snapshot_timestamp_utc") or r.get("commence_time") or ""))
        except Exception:continue
        idx.setdefault((gid,mt,side,book),[]).append(o)
    return idx

def _best(idx,gid,mt,side,books=("draftkings","fanduel")):
    xs=[o for b in books for o in idx.get((gid,mt,side,b),[])]
    return shop_moneyline(xs) if mt=="moneyline" else shop_spread(xs) if mt=="spread" else shop_total(side,xs)
def _pin(idx,gid,mt,side):
    xs=idx.get((gid,mt,side,"pinnacle"),[])
    if not xs:return None
    return shop_moneyline(xs) if mt=="moneyline" else shop_spread(xs) if mt=="spread" else shop_total(side,xs)

def materialize_training(games,idx,prior_gids):
    ml=[];spr=[];tot=[]
    for gid in prior_gids:
      g=games[gid];block=_block_key(g["season"],g["week"]);hs,as_=g["home_score"],g["away_score"]
      ph,pa=_pin(idx,gid,"moneyline","home"),_pin(idx,gid,"moneyline","away")
      if ph and pa and g["qbelo_home"] is not None and g["xgb_home"] is not None:
        p_home,_=proportional_no_vig(ph.price_american,pa.price_american);ml.append({"block":block,"qb":float(g["qbelo_home"]),"xgb":float(g["xgb_home"]),"pin":p_home,"y":_grade_ml("home",hs,as_)})
      for side in ("home","away"):
        o=_best(idx,gid,"spread",side)
        if o and g["expected_home_margin"] is not None:
          y=_grade_sp(side,float(o.line),hs,as_)
          if y is not None:
            sm=float(g["expected_home_margin"]) if side=="home" else -float(g["expected_home_margin"]);res=(hs-as_-float(g["expected_home_margin"])) if side=="home" else (as_-hs+float(g["expected_home_margin"]))
            spr.append({"block":block,"delta":sm+float(o.line),"market_level":abs(float(o.line)),"residual":res,"y":y})
      residual_total=(hs+as_)-float(g["predicted_total"]) if g["predicted_total"] is not None else None
      if residual_total is not None:
       for side in ("over","under"):
        o=_best(idx,gid,"total",side)
        if o:
          y=_grade_total(side,float(o.line),hs,as_)
          if y is not None:
            d=(float(g["predicted_total"])-float(o.line)) if side=="over" else (float(o.line)-float(g["predicted_total"]));tot.append({"block":block,"delta":d,"market_level":float(o.line),"residual":residual_total,"y":y})
    return ml,spr,tot

def run(root:Path,cfg_path:Path,out:Path):
    cfg,cfg_sha=cfg_load(cfg_path)
    games=build_inputs(root);idx=build_market(root,games)
    blocks=sorted({(_block_key(g["season"],g["week"]),gid) for gid,g in games.items()}); ordered_blocks=sorted({b for b,_ in blocks})
    metrics_rows={"moneyline":{},"spread":{},"total":{}}
    for block in ordered_blocks:
      current=[gid for b,gid in blocks if b==block];prior=[gid for b,gid in blocks if b<block]
      mltr,sptr,tottr=materialize_training(games,idx,prior)
      states={"moneyline":fit_ml_states(mltr,VERSION,cfg_sha),"spread":fit_point_states(sptr,"spread",VERSION,cfg_sha),"total":fit_point_states(tottr,"total",VERSION,cfg_sha)}
      for gid in current:
        g=games[gid];gs=GameState(gid,int(g["season"]),str(g["week"]),None,g["qbelo_home"],g["xgb_home"],g["expected_home_margin"],g["predicted_total"]);hs,as_=g["home_score"],g["away_score"]
        ph,pa=_pin(idx,gid,"moneyline","home"),_pin(idx,gid,"moneyline","away")
        if ph and pa:
          pinh,pina=proportional_no_vig(ph.price_american,pa.price_american)
          for side,pin,y in (("home",pinh,_grade_ml("home",hs,as_)),("away",pina,_grade_ml("away",hs,as_))):
            o=_best(idx,gid,"moneyline",side)
            if o:
              for fam,st in states["moneyline"].items():
                rr=evaluate_offer(gs,o,st,pinnacle_no_vig_selected=pin);metrics_rows["moneyline"].setdefault(fam,[]).append({"block":block,"p":rr.actionable_probability,"y":y,"ev":rr.expected_value,"price":o.price_american,"reliability":rr.reliability})
        for mt,sides in (("spread",("home","away")),("total",("over","under"))):
          for side in sides:
            o=_best(idx,gid,mt,side)
            if not o:continue
            y=_grade_sp(side,float(o.line),hs,as_) if mt=="spread" else _grade_total(side,float(o.line),hs,as_)
            if y is None:continue
            for fam,st in states[mt].items():
              rr=evaluate_offer(gs,o,st);metrics_rows[mt].setdefault(fam,[]).append({"block":block,"p":rr.actionable_probability,"y":y,"ev":rr.expected_value,"price":o.price_american,"reliability":rr.reliability})
    score={};selected={};complexity={"moneyline":["pinnacle","raw_qbelo","raw_xgb","exact_avg","global_shrinkage","reliability_aware_shrinkage","strong_logistic"],"spread":["normal_cdf","calibrated_normal","strong_logistic"],"total":["normal_cdf","calibrated_normal","strong_logistic"]}
    for mt,fams in metrics_rows.items():
      score[mt]={fam:{**probability_metrics(rows),"reliability_table":reliability_table(rows)} for fam,rows in fams.items()}
      avail=[(fam,m) for fam,m in score[mt].items() if m["brier"] is not None]
      if not avail:selected[mt]=None;continue
      best=min(avail,key=lambda x:(x[1]["brier"],x[1]["log_loss"]));tolb=float(cfg["selection_rule"]["simplicity_tolerance_brier"]);toll=float(cfg["selection_rule"]["simplicity_tolerance_logloss"])
      selected[mt]=next((fam for fam in complexity[mt] if fam in score[mt] and score[mt][fam]["brier"] is not None and score[mt][fam]["brier"]<=best[1]["brier"]+tolb and score[mt][fam]["log_loss"]<=best[1]["log_loss"]+toll),best[0])
    out.mkdir(parents=True,exist_ok=True)
    safe={"evaluator_version":VERSION,"config_sha256":cfg_sha,"development_seasons":DEV,"sealed_seasons":[2025],"chronology":"expanding prior season-week blocks only","selected":selected,"metrics":score}
    (out/"scorecard.json").write_text(json.dumps(safe,indent=2));(out/"provenance.json").write_text(json.dumps({k:safe[k] for k in ["evaluator_version","config_sha256","development_seasons","sealed_seasons","chronology"]},indent=2))
    lines=["# Market Evaluator V1 OOS Scorecard","",f"Config SHA-256: `{cfg_sha}`","",f"Selected: `{selected}`","","2020–2024 expanding season-week OOS. 2025 sealed."]
    (out/"scorecard.md").write_text("\n".join(lines)+"\n");print(json.dumps(selected,indent=2))
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--config",default=str(ROOT/"config/market_evaluator_v1.yaml"));p.add_argument("--out",default=str(ROOT/"reports/value_evaluator_v1"));a=p.parse_args();run(ROOT,Path(a.config),Path(a.out))
