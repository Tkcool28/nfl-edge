#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from collections import Counter, defaultdict
from pathlib import Path
import polars as pl

from nfl_edge.recommendation.final_selectors_v1 import ValueSelectorState, advance_value_state, select_hit_rate, select_balanced, select_value
from nfl_edge.recommendation.policy import NO_HIT_RATE_PLAY, NO_BALANCED_PLAY, NO_VALUE_PLAY
from nfl_edge.recommendation.remediation_provenance_v1 import build_candidate_registry, enrich_board_rows
from nfl_edge.recommendation.hhr_staking_audit_v2 import hhr_stake
from nfl_edge.recommendation.staking_v1 import recommended_units

ALL={2020,2021,2022,2023,2024}; SEALED=2025
BALANCED_MIN_UNITS=0.75
VALUE_RESCUE_REQUIRED=0.010
VALUE_RESCUE_MAX=0.015
VALUE_RESCUE_UNITS=0.50

def block_key(b):
    s,w=str(b).split('-',1); return int(s),int(w)

def be_prob(odds:int)->float:
    if odds <= -100: return (-odds)/((-odds)+100.0)
    if odds >= 100: return 100.0/(odds+100.0)
    raise ValueError(f'invalid American odds {odds}')

def first_better_price(current:int, required:float=VALUE_RESCUE_REQUIRED):
    p0=be_prob(current)
    if current <= -100:
        candidates=list(range(current+1,-99))+list(range(100,5001))
    else:
        candidates=list(range(current+1,5001))
    for odds in candidates:
        improvement=p0-be_prob(odds)
        if improvement+1e-12 >= required:
            return odds, improvement
    return None, None

def settle(r): return str(r.get('settlement') or '').upper()
def ppu(r): return float(r.get('realized_profit') or 0.0)

def run(v3, discovery, confirmation, out):
    rows=pl.read_parquet(v3).to_dicts(); seasons={int(r['season']) for r in rows}
    if seasons!=ALL or SEALED in seasons: raise RuntimeError(f'2025 firewall: {sorted(seasons)}')
    prov=pl.concat([pl.read_csv(discovery,infer_schema_length=10000),pl.read_csv(confirmation,infer_schema_length=10000)],how='vertical_relaxed').to_dicts()
    if {int(r['season']) for r in prov}!=ALL: raise RuntimeError('unexpected provenance seasons')
    enriched=enrich_board_rows(rows,build_candidate_registry(prov)); blocks=defaultdict(list)
    for r in enriched: blocks[str(r['block'])].append(r)

    state=ValueSelectorState(); season_now=None; output=[]
    for block in sorted(blocks,key=block_key):
        season,_=block_key(block)
        if season_now!=season: state=ValueSelectorState(); season_now=season
        br=blocks[block]
        sels={'hit_rate':select_hit_rate(br),'balanced':select_balanced(br),'value':select_value(br,state)}
        none={'hit_rate':NO_HIT_RATE_PLAY,'balanced':NO_BALANCED_PLAY,'value':NO_VALUE_PLAY}
        for lane,s in sels.items():
            if s==none[lane]: continue
            r=dict(s); current_generic=float(recommended_units(r)); published=True; current_units=current_generic; display_units=current_generic; action='BET'; value_at_odds=None; rescue_pp=None
            if lane=='hit_rate':
                current_units=display_units=float(hhr_stake(r).recommended_units)
            elif lane=='balanced':
                current_units=display_units=max(BALANCED_MIN_UNITS,current_generic)
            else:
                if current_generic>0:
                    current_units=display_units=current_generic
                else:
                    current_units=0.0
                    odds=int(r.get('american_odds') if r.get('american_odds') is not None else r.get('actionable_price_american'))
                    target, improvement=first_better_price(odds)
                    if target is not None and improvement is not None and improvement <= VALUE_RESCUE_MAX+1e-12:
                        action='VALUE_AT'; display_units=VALUE_RESCUE_UNITS; value_at_odds=target; rescue_pp=improvement*100.0
                    else:
                        published=False; action='SUPPRESSED'; display_units=0.0
            output.append({
                'season':season,'block':block,'lane':lane,'game_id':r.get('game_id'),'market_type':r.get('market_type'),'selected_side':r.get('selected_side'),
                'sportsbook':r.get('sportsbook'),'line':r.get('line'),'american_odds':r.get('american_odds'),'reliability':r.get('reliability'),'price_status':r.get('price_status'),
                'selector_trust':r.get('selector_trust'),'expected_value':r.get('expected_value'),'settlement':settle(r),'realized_profit':r.get('realized_profit'),
                'generic_units_before':current_generic,'current_bet_units':current_units,'display_action_units':display_units,'headline_action':action,'published':published,
                'value_at_odds':value_at_odds,'value_at_break_even_improvement_pp':rescue_pp,
            })
        state=advance_value_state(state,br)

    h=[r for r in output if r['lane']=='hit_rate']; b=[r for r in output if r['lane']=='balanced']; v=[r for r in output if r['lane']=='value']
    if len(h)!=81 or len(b)!=88 or len(v)!=68: raise RuntimeError(f'frozen selector counts changed: {len(h)}/{len(b)}/{len(v)}')
    if any(int(r['season'])==SEALED for r in output): raise RuntimeError('2025 entered outputs')

    by_season=[]
    for season in sorted(ALL):
        for lane in ['hit_rate','balanced','value']:
            rr=[r for r in output if r['season']==season and r['lane']==lane]
            pub=[r for r in rr if r['published']]; wins=sum(r['settlement']=='WIN' for r in rr); losses=sum(r['settlement']=='LOSS' for r in rr); pushes=sum(r['settlement']=='PUSH' for r in rr)
            by_season.append({'season':season,'lane':lane,'selected':len(rr),'published':len(pub),'current_bets':sum(float(r['current_bet_units'])>0 for r in pub),'value_at_cards':sum(r['headline_action']=='VALUE_AT' for r in pub),'suppressed':sum(not r['published'] for r in rr),'wins':wins,'losses':losses,'pushes':pushes})

    rescued=[r for r in v if r['headline_action']=='VALUE_AT']; suppressed=[r for r in v if not r['published']]
    score={
        'seasons':sorted(ALL),'sealed_not_run':[SEALED],
        'selector_counts':{'hit_rate':len(h),'balanced':len(b),'value':len(v)},
        'hhr_positive_current_bets':sum(float(r['current_bet_units'])>0 for r in h),
        'balanced_positive_current_bets':sum(float(r['current_bet_units'])>0 for r in b),
        'value_positive_current_bets':sum(float(r['current_bet_units'])>0 for r in v),
        'value_rescued_value_at_cards':len(rescued),'value_suppressed_cards':len(suppressed),
        'published_headlines_with_zero_action_units':sum(r['published'] and float(r['display_action_units'])<=0 for r in output),
        'value_rescue_target_improvement_pp':None if not rescued else {'min':min(float(r['value_at_break_even_improvement_pp']) for r in rescued),'median':float(pl.Series([float(r['value_at_break_even_improvement_pp']) for r in rescued]).median()),'max':max(float(r['value_at_break_even_improvement_pp']) for r in rescued)},
        'invariants':{
            'selectors_unchanged':len(h)==81 and len(b)==88 and len(v)==68,
            'all_hhr_selected_positive_current_units':all(float(r['current_bet_units'])>0 for r in h),
            'all_balanced_selected_positive_current_units':all(float(r['current_bet_units'])>0 for r in b),
            'no_published_zero_action_headlines':all((not r['published']) or float(r['display_action_units'])>0 for r in output),
            'all_value_rescues_within_1_5pp':all(float(r['value_at_break_even_improvement_pp'])<=1.5+1e-12 for r in rescued),
            'no_2025':True,
        }
    }
    out.mkdir(parents=True,exist_ok=True)
    pl.DataFrame(output).write_csv(out/'headline_actionability_rows.csv')
    pl.DataFrame(by_season).write_csv(out/'season_actionability_summary.csv')
    if rescued: pl.DataFrame(rescued).write_csv(out/'value_at_rescues.csv')
    else: (out/'value_at_rescues.csv').write_text('season,block,lane\n')
    if suppressed: pl.DataFrame(suppressed).write_csv(out/'suppressed_value_cards.csv')
    else: (out/'suppressed_value_cards.csv').write_text('season,block,lane\n')
    (out/'scorecard.json').write_text(json.dumps(score,indent=2,sort_keys=True)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--v3-candidates',type=Path,required=True); p.add_argument('--discovery',type=Path,default=Path('reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv')); p.add_argument('--confirmation',type=Path,default=Path('reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv')); p.add_argument('--out',type=Path,required=True); a=p.parse_args(); run(a.v3_candidates,a.discovery,a.confirmation,a.out)
