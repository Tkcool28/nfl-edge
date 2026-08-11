#!/usr/bin/env python3
# ruff: noqa: E501, E701, E702
"""Stage 02A exception inventory only; never selects a starter."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'data/derived/stathead_actual_starters_v1'
OUT=BASE/'stage02_exception_inventory'
ALIASES={'GNB':'GB','KAN':'KC','LVR':'LV','NWE':'NE','NOR':'NO','SFO':'SF','TAM':'TB','OAK':'LV','SD':'LAC','SDG':'LAC','STL':'LAR','JAC':'JAX'}
def norm(x): return ALIASES.get(str(x).strip().upper(),str(x).strip().upper())
def read(p):
 with p.open(newline='',encoding='utf-8') as h:return list(csv.DictReader(h))
def write(p,cols,rows):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('w',newline='',encoding='utf-8') as h:
  w=csv.DictWriter(h,fieldnames=cols,lineterminator='\n');w.writeheader();w.writerows(rows)
def sha(p):
 h=hashlib.sha256();h.update(p.read_bytes());return h.hexdigest()
def diagnose(r,games):
 if 'location' in r['reconciliation_reason']:return 'LOCATION_MISMATCH'
 same_date=[g for g in games if g['game_date']==r['raw_date']]
 if any(norm(r['raw_team']) in (g['away_team'],g['home_team']) for g in same_date):return 'OPPONENT_MISMATCH'
 if any({norm(r['raw_team']),norm(r['raw_opp'])}=={g['away_team'],g['home_team']} for g in games):return 'DATE_MISMATCH'
 return 'NO_CANONICAL_GAME'
def run():
 rows=read(BASE/'stage01_canonical_reconciliation/row_reconciliation.csv');groups=read(BASE/'stage01_canonical_reconciliation/game_side_candidates.csv')
 raw={r['Rk']:r for r in read(BASE/'stage00_structural/stathead_qb_started_2018_2024_raw_combined.csv')}
 assert len(rows)==3921 and Counter(g['candidate_count'] for g in groups)==Counter({'0':49,'1':3785,'2':49,'3':1})
 games=[{'game_id':g['game_id'],'game_date':g['game_date'],'away_team':g['away_team'],'home_team':g['home_team']} for g in groups]
 unmatched=[]
 for r in rows:
  if r['match_status']=='UNMATCHED':
   x={k:r[k] for k in ['rank','player_name','pfr_id','raw_date','raw_team','raw_location','raw_opp','raw_pos','reconciliation_reason']};x['raw_result']=raw[r['rank']]['Result'];x['diagnosis']=diagnose(r,games);unmatched.append(x)
 assert len(unmatched)==15
 zeros=[]
 for g in groups:
  if g['candidate_count']=='0':
   opts=[r for r in unmatched if r['raw_date']==g['game_date'] and norm(r['raw_team'])==g['canonical_team'] and norm(r['raw_opp'])== (g['home_team'] if g['team_side']=='away' else g['away_team'])]
   x={k:g[k] for k in ['game_id','season','week','season_type','game_date','away_team','home_team','team_side','canonical_team']}
   if opts:
    x.update(possible_unmatched_rank=opts[0]['rank'],possible_link_reason='same date/team/opponent; unmatched location or source identity issue',possible_link_confidence='EXACT_IDENTITY_EXCEPT_LOCATION')
   else:x.update(possible_unmatched_rank='',possible_link_reason='',possible_link_confidence='NO_OBVIOUS_RAW_ROW')
   zeros.append(x)
 assert len(zeros)==49
 multi=[];summary=[]
 for g in groups:
  if int(g['candidate_count'])>=2:
   ranks=g['candidate_ranks'].split('|'); poss=[raw[k]['Pos.'] for k in ranks]
   anomaly='MULTIPLE_QB_ROWS' if all(p=='QB' for p in poss) else ('MIXED_POSITION_QB_ROW' if any('QB' in p for p in poss) else 'OTHER_MULTI_CANDIDATE')
   summary.append({**{k:g[k] for k in ['game_id','season','week','season_type','game_date','canonical_team','team_side','candidate_count','candidate_ranks','candidate_names','candidate_pfr_ids']},'candidate_raw_positions':'|'.join(poss),'anomaly_type':anomaly})
   for k,p in zip(ranks,poss):multi.append({**{q:g[q] for q in ['game_id','season','week','season_type','game_date','canonical_team','team_side','candidate_count']},'candidate_rank':k,'candidate_name':raw[k]['Player'],'candidate_pfr_id':raw[k]['Player-additional'],'candidate_raw_pos':p,'anomaly_type':anomaly})
 assert len(summary)==50
 paths={'unmatched_raw_rows.csv':(list(unmatched[0]),unmatched),'zero_candidate_game_sides.csv':(list(zeros[0]),zeros),'multi_candidate_game_sides.csv':(list(multi[0]),multi),'multi_candidate_summary.csv':(list(summary[0]),summary)}
 for n,(c,d) in paths.items():write(OUT/n,c,d)
 report={'raw_unmatched_count':15,'zero_candidate_game_side_count':49,'multi_candidate_game_side_count':50,'multi_candidate_distribution':dict(Counter(x['candidate_count'] for x in summary)),'unmatched_diagnosis_distribution':dict(Counter(x['diagnosis'] for x in unmatched)),'multi_candidate_anomaly_distribution':dict(Counter(x['anomaly_type'] for x in summary)),'zero_sides_with_possible_unmatched_link':sum(x['possible_unmatched_rank']!='' for x in zeros),'zero_sides_without_possible_unmatched_link':sum(x['possible_unmatched_rank']=='' for x in zeros),'all_affected_game_ids':sorted(set(x['game_id'] for x in zeros+summary)),'all_affected_raw_ranks':sorted([int(x['rank']) for x in unmatched]+[int(x['candidate_rank']) for x in multi]),'guardrail':'inventory only; no starter selection'}
 (OUT/'exception_inventory_report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
 report['output_sha256']={n:sha(OUT/n) for n in [*paths,'exception_inventory_report.json']};(OUT/'exception_inventory_report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
 print(json.dumps(report,indent=2,sort_keys=True))
if __name__=='__main__':run()
