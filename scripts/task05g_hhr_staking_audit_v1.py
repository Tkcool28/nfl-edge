#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
import polars as pl
from nfl_edge.recommendation.final_selectors_v1 import select_hit_rate
from nfl_edge.recommendation.policy import NO_HIT_RATE_PLAY
from nfl_edge.recommendation.remediation_provenance_v1 import build_candidate_registry, enrich_board_rows
from nfl_edge.recommendation.hhr_staking_audit_v1 import hhr_stake
from nfl_edge.recommendation.staking_v1 import (
    MINIMUM_STAKE_DOLLARS,
    PER_WAGER_BANKROLL_CAP_PCT,
    ROUNDING_QUANTUM_DOLLARS,
    risk_profile,
)

ALL={2020,2021,2022,2023,2024}; SEALED=2025

def key(block):
    s,w=str(block).split('-',1); return int(s),int(w)

def settle(r): return str(r.get('settlement') or '').upper()
def ppu(r): return float(r.get('realized_profit') or 0.0)

def audit_dollar_stake(bankroll, profile, units):
    """Mirror canonical dollar conversion while permitting the HHR-audit 0.25u floor."""
    if float(units) not in {0.25,0.5,0.75,1.0,1.25,1.5}:
        raise ValueError('unexpected HHR audit units')
    b=Decimal(str(bankroll)); selected=risk_profile(profile)
    raw=b*Decimal(str(selected.unit_bankroll_pct))*Decimal(str(float(units)))
    cap=b*Decimal(str(PER_WAGER_BANKROLL_CAP_PCT))
    bounded=min(raw,cap); q=Decimal(str(ROUNDING_QUANTUM_DOLLARS))
    rounded=(bounded/q).to_integral_value(rounding=ROUND_FLOOR)*q
    if rounded < Decimal(str(MINIMUM_STAKE_DOLLARS)): return 0.0
    return float(rounded)

def run(v3, discovery, confirmation, out):
    rows=pl.read_parquet(v3).to_dicts()
    seasons={int(r['season']) for r in rows}
    if seasons != ALL or SEALED in seasons: raise RuntimeError(f'2025 firewall: {sorted(seasons)}')
    prov=pl.concat([pl.read_csv(discovery,infer_schema_length=10000),pl.read_csv(confirmation,infer_schema_length=10000)],how='vertical_relaxed').to_dicts()
    if {int(r['season']) for r in prov} != ALL: raise RuntimeError('unexpected provenance seasons')
    enriched=enrich_board_rows(rows, build_candidate_registry(prov))
    blocks=defaultdict(list)
    for r in enriched: blocks[str(r['block'])].append(r)
    picks=[]
    for block in sorted(blocks,key=key):
        selected=select_hit_rate(blocks[block])
        if selected == NO_HIT_RATE_PLAY: continue
        r=dict(selected); st=hhr_stake(r)
        r.update(block=block,hhr_base_units=st.base_units,hhr_price_pressure=st.price_pressure,hhr_haircut_units=st.haircut_units,hhr_units=st.recommended_units,heavily_juiced=st.heavily_juiced)
        picks.append(r)
    if any(int(r['season'])==SEALED for r in picks): raise RuntimeError('2025 entered HHR picks')
    dist=dict(sorted(Counter(float(r['hhr_units']) for r in picks).items()))
    warnings=[r for r in picks if r['heavily_juiced']]
    by_units={}
    for u in sorted({float(r['hhr_units']) for r in picks}):
        rr=[r for r in picks if float(r['hhr_units'])==u]
        w=sum(settle(r)=='WIN' for r in rr); l=sum(settle(r)=='LOSS' for r in rr); p=sum(settle(r)=='PUSH' for r in rr)
        by_units[str(u)]={'n':len(rr),'wins':w,'losses':l,'pushes':p,'hit_rate':None if w+l==0 else w/(w+l),'flat_profit_units':sum(float(r['hhr_units'])*ppu(r) for r in rr)}
    profiles=[]
    for profile in ['Cautious','Conservative','Normal','Aggressive','Ultra']:
        bank=1000.0; peak=bank; maxdd=0.0; staked=0.0; profit=0.0
        for r in picks:
            stake=audit_dollar_stake(bank,profile,float(r['hhr_units']))
            pnl=stake*ppu(r); bank+=pnl; staked+=stake; profit+=pnl; peak=max(peak,bank); maxdd=max(maxdd,(peak-bank)/peak if peak else 0.0)
        profiles.append({'profile':profile,'ending_bankroll':bank,'profit':profit,'total_staked':staked,'max_drawdown_pct':maxdd})
    score={'version':'task05g_hhr_staking_audit_v1','seasons':sorted(ALL),'sealed_not_run':[SEALED],'hhr_selected_count':len(picks),'unit_distribution':dist,'heavily_juiced_count':len(warnings),'heavily_juiced_rate':len(warnings)/len(picks) if picks else None,'pressure_min':min(float(r['hhr_price_pressure']) for r in picks),'pressure_median':float(pl.Series([float(r['hhr_price_pressure']) for r in picks]).median()),'pressure_max':max(float(r['hhr_price_pressure']) for r in picks),'by_units':by_units,'profiles':profiles,'invariants':{'all_selected_hhr_positive_units':all(float(r['hhr_units'])>0 for r in picks),'selector_result_count_matches_frozen_hhr':len(picks)==81,'no_2025':True}}
    out.mkdir(parents=True,exist_ok=True)
    (out/'scorecard.json').write_text(json.dumps(score,indent=2,sort_keys=True)+'\n')
    pl.DataFrame(picks).sort('block').write_csv(out/'hhr_rows.csv')
    if warnings: pl.DataFrame(warnings).sort('block').write_csv(out/'heavily_juiced_rows.csv')
    pl.DataFrame(profiles).write_csv(out/'profile_summary.csv')

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--v3-candidates',type=Path,required=True); p.add_argument('--discovery',type=Path,default=Path('reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv')); p.add_argument('--confirmation',type=Path,default=Path('reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv')); p.add_argument('--out',type=Path,required=True); a=p.parse_args(); run(a.v3_candidates,a.discovery,a.confirmation,a.out)
