#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from collections import defaultdict, Counter
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Any, Mapping
import polars as pl
from nfl_edge.recommendation.final_selectors_v1 import ValueSelectorState, advance_value_state, select_hit_rate, select_balanced, select_value
from nfl_edge.recommendation.policy import NO_HIT_RATE_PLAY, NO_BALANCED_PLAY, NO_VALUE_PLAY
from nfl_edge.recommendation.remediation_provenance_v1 import build_candidate_registry, enrich_board_rows
from nfl_edge.recommendation.hhr_staking_audit_v2 import hhr_stake
from nfl_edge.recommendation.staking_v1 import risk_profile, recommended_units, cap_slate_stakes, MINIMUM_STAKE_DOLLARS, ROUNDING_QUANTUM_DOLLARS, PER_WAGER_BANKROLL_CAP_PCT

ALL={2020,2021,2022,2023,2024}; SEALED=2025
PROFILES=['Cautious','Conservative','Normal','Aggressive','Ultra']
STARTS=[100.0,250.0,500.0,1000.0,2500.0]
LANES=['hit_rate','balanced','value']

def block_key(b):
    s,w=str(b).split('-',1); return int(s),int(w)
def cid(r): return str(r.get('candidate_id') or '|'.join([str(r.get('game_id','')),str(r.get('market_type','')),str(r.get('selected_side',''))]))
def offer_key(r):
    return '|'.join([cid(r),str(r.get('sportsbook') or r.get('actionable_book') or ''),str(r.get('line') if r.get('line') is not None else r.get('actionable_line')),str(r.get('american_odds') if r.get('american_odds') is not None else r.get('actionable_price_american'))])
def settle(r): return str(r.get('settlement') or '').upper()
def ppu(r): return float(r.get('realized_profit') or 0.0)
def units_for(lane,r): return float(hhr_stake(r).recommended_units if lane=='hit_rate' else recommended_units(r))

def dollar_stake(bankroll, profile_name, units):
    if units<=0: return 0.0
    prof=risk_profile(profile_name); b=Decimal(str(bankroll)); raw=b*Decimal(str(prof.unit_bankroll_pct))*Decimal(str(units)); cap=b*Decimal(str(PER_WAGER_BANKROLL_CAP_PCT)); bounded=min(raw,cap); q=Decimal(str(ROUNDING_QUANTUM_DOLLARS)); rounded=(bounded/q).to_integral_value(rounding=ROUND_FLOOR)*q
    return 0.0 if rounded<Decimal(str(MINIMUM_STAKE_DOLLARS)) else float(rounded)

def summarize(rows):
    w=sum(settle(r)=='WIN' for r in rows); l=sum(settle(r)=='LOSS' for r in rows); p=sum(settle(r)=='PUSH' for r in rows); n=w+l
    return {'plays':len(rows),'wins':w,'losses':l,'pushes':p,'hit_rate':None if n==0 else w/n,'weighted_profit_units':sum(float(r['units'])*ppu(r) for r in rows),'total_units_staked':sum(float(r['units']) for r in rows)}

def run(v3, discovery, confirmation, out):
    rows=pl.read_parquet(v3).to_dicts(); seasons={int(r['season']) for r in rows}
    if seasons!=ALL or SEALED in seasons: raise RuntimeError(f'2025 firewall: {sorted(seasons)}')
    prov=pl.concat([pl.read_csv(discovery,infer_schema_length=10000),pl.read_csv(confirmation,infer_schema_length=10000)],how='vertical_relaxed').to_dicts()
    if {int(r['season']) for r in prov}!=ALL: raise RuntimeError('unexpected provenance seasons')
    enriched=enrich_board_rows(rows,build_candidate_registry(prov)); blocks=defaultdict(list)
    for r in enriched: blocks[str(r['block'])].append(r)
    state=ValueSelectorState(); season_now=None; headlines=[]; combined_by_block={}; duplicate_conflicts=[]
    for block in sorted(blocks,key=block_key):
        season,_=block_key(block)
        if season_now!=season: state=ValueSelectorState(); season_now=season
        br=blocks[block]; sels={'hit_rate':select_hit_rate(br),'balanced':select_balanced(br),'value':select_value(br,state)}
        none={'hit_rate':NO_HIT_RATE_PLAY,'balanced':NO_BALANCED_PLAY,'value':NO_VALUE_PLAY}
        by_offer={}; lanes=defaultdict(list)
        for lane,s in sels.items():
            if s==none[lane]: continue
            r=dict(s); u=units_for(lane,r); r.update(block=block,season=season,lane=lane,units=u,offer_key=offer_key(r)); headlines.append(r)
            if u<=0: continue
            k=r['offer_key']; lanes[k].append(lane)
            if k not in by_offer: by_offer[k]=dict(r)
            elif abs(float(by_offer[k]['units'])-u)>1e-12:
                duplicate_conflicts.append({'block':block,'offer_key':k,'prior_units':float(by_offer[k]['units']),'new_units':u,'prior_lane':by_offer[k]['lane'],'new_lane':lane})
                if u>float(by_offer[k]['units']): by_offer[k]=dict(r)
        combined_by_block[block]=list(by_offer.values())
        state=advance_value_state(state,br)
    if len([r for r in headlines if r['lane']=='hit_rate'])!=81: raise RuntimeError('frozen HHR count changed')
    if any(int(r['season'])==SEALED for r in headlines): raise RuntimeError('2025 entered selections')

    season_lane=[]
    for season in sorted(ALL):
        for lane in LANES:
            rr=[r for r in headlines if int(r['season'])==season and r['lane']==lane]
            s=summarize(rr); s.update(season=season,lane=lane,positive_stake_plays=sum(float(r['units'])>0 for r in rr),zero_stake_cards=sum(float(r['units'])<=0 for r in rr)); season_lane.append(s)
    season_combined=[]
    for season in sorted(ALL):
        rr=[r for b,rs in combined_by_block.items() if block_key(b)[0]==season for r in rs]
        s=summarize(rr); s.update(season=season,unique_recommended_wagers=len(rr)); season_combined.append(s)

    scenarios=[]; ledgers=[]
    for start in STARTS:
        for profile in PROFILES:
            bank=start; peak=bank; maxdd=0.0; total_staked=0.0; total_profit=0.0; wagers=0; suppressed=0; cap_blocks=0
            for block in sorted(combined_by_block,key=block_key):
                rs=combined_by_block[block]; proposed=[]
                for i,r in enumerate(rs):
                    stake=dollar_stake(bank,profile,float(r['units'])); suppressed+=int(stake==0 and float(r['units'])>0); proposed.append((str(i),stake))
                capped=cap_slate_stakes(bank,proposed); cap_blocks+=int(any(capped.get(k,0.0)+1e-12<s for k,s in proposed))
                block_pnl=0.0; block_stake=0.0
                for i,r in enumerate(rs):
                    stake=float(capped.get(str(i),0.0));
                    if stake<=0: continue
                    pnl=stake*ppu(r); block_pnl+=pnl; block_stake+=stake; wagers+=1
                    ledgers.append({'start_bankroll':start,'profile':profile,'block':block,'season':block_key(block)[0],'lane_source':r['lane'],'offer_key':r['offer_key'],'units':r['units'],'stake':stake,'settlement':settle(r),'profit':pnl})
                bank+=block_pnl; total_staked+=block_stake; total_profit+=block_pnl; peak=max(peak,bank); maxdd=max(maxdd,(peak-bank)/peak if peak else 0.0)
            scenarios.append({'starting_bankroll':start,'profile':profile,'ending_bankroll':bank,'profit':total_profit,'return_pct':total_profit/start if start else None,'total_staked':total_staked,'wagers_bet':wagers,'min_stake_suppressed':suppressed,'slate_cap_binding_blocks':cap_blocks,'max_drawdown_pct':maxdd})

    out.mkdir(parents=True,exist_ok=True)
    pl.DataFrame(season_lane).write_csv(out/'season_lane_summary.csv'); pl.DataFrame(season_combined).write_csv(out/'season_combined_summary.csv'); pl.DataFrame(scenarios).write_csv(out/'all_cards_bankroll_scenarios.csv'); pl.DataFrame(headlines).write_csv(out/'headline_cards.csv'); pl.DataFrame(duplicate_conflicts).write_csv(out/'duplicate_unit_conflicts.csv') if duplicate_conflicts else (out/'duplicate_unit_conflicts.csv').write_text('block,offer_key,prior_units,new_units,prior_lane,new_lane\n')
    pl.DataFrame(ledgers).write_csv(out/'scenario_ledger.csv')
    score={'seasons':sorted(ALL),'sealed_not_run':[SEALED],'headline_counts':dict(Counter(r['lane'] for r in headlines)),'positive_stake_headline_counts':dict(Counter(r['lane'] for r in headlines if float(r['units'])>0)),'combined_unique_recommended_wagers':sum(len(v) for v in combined_by_block.values()),'duplicate_unit_conflict_count':len(duplicate_conflicts),'hhr_heavily_juiced_count':sum(bool(hhr_stake(r).heavily_juiced) for r in headlines if r['lane']=='hit_rate'),'scenario_count':len(scenarios),'invariants':{'hhr_count_81':sum(r['lane']=='hit_rate' for r in headlines)==81,'all_hhr_positive_units':all(float(r['units'])>0 for r in headlines if r['lane']=='hit_rate'),'no_2025':True}}
    (out/'scorecard.json').write_text(json.dumps(score,indent=2,sort_keys=True)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--v3-candidates',type=Path,required=True); p.add_argument('--discovery',type=Path,default=Path('reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv')); p.add_argument('--confirmation',type=Path,default=Path('reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv')); p.add_argument('--out',type=Path,required=True); a=p.parse_args(); run(a.v3_candidates,a.discovery,a.confirmation,a.out)
