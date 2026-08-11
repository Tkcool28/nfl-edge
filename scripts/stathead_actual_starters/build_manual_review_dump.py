#!/usr/bin/env python3
"""Build manual-only starter exception review files; no adjudication."""
import csv, hashlib, json
from collections import Counter
from pathlib import Path
R=Path(__file__).resolve().parents[2]; B=R/'data/derived/stathead_actual_starters_v1'; I=B/'stage02_exception_inventory'; O=B/'manual_starter_review'
def rd(p):
 with p.open(newline='') as h:return list(csv.DictReader(h))
def wr(n,cols,rows):
 O.mkdir(parents=True,exist_ok=True)
 with (O/n).open('w',newline='') as h:
  w=csv.DictWriter(h,cols,lineterminator='\n');w.writeheader();w.writerows(rows)
def sh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 zero=rd(I/'zero_candidate_game_sides.csv'); multi=rd(I/'multi_candidate_summary.csv'); detail=rd(I/'multi_candidate_game_sides.csv'); unmatched=rd(I/'unmatched_raw_rows.csv'); raw={x['Rk']:x for x in rd(B/'stage00_structural/stathead_qb_started_2018_2024_raw_combined.csv')}
 assert len(zero)==49 and len(multi)==50 and len(zero)+len(multi)==99 and len(unmatched)==15
 sides=[]
 for x in zero:
  sides.append({**{k:x[k] for k in ['game_id','season','week','season_type','game_date','away_team','home_team','team_side','canonical_team']},'canonical_opponent':x['home_team'] if x['team_side']=='away' else x['away_team'],'candidate_count':'0','candidate_names':'','candidate_pfr_ids':'','candidate_ranks':'','candidate_positions':'','exception_type':'ZERO_CANDIDATE','manual_actual_starting_qb_name':'','manual_actual_starting_qb_pfr_id':'','manual_source':'','manual_source_locator':'','manual_notes':''})
 for x in multi:
  ranks=x['candidate_ranks'].split('|'); pos='|'.join(raw[k]['Pos.'] for k in ranks)
  sides.append({**{k:x[k] for k in ['game_id','season','week','season_type','game_date','team_side','canonical_team','candidate_count','candidate_names','candidate_pfr_ids','candidate_ranks']},'away_team':'','home_team':'','canonical_opponent':'','candidate_positions':pos,'exception_type':'MULTIPLE_CANDIDATES','manual_actual_starting_qb_name':'','manual_actual_starting_qb_pfr_id':'','manual_source':'','manual_source_locator':'','manual_notes':''})
 # fill canonical game teams from Stage01 side dump
 allg={x['game_id']:x for x in rd(B/'stage01_canonical_reconciliation/game_side_candidates.csv')}
 for x in sides:
  g=allg[x['game_id']];x['away_team']=g['away_team'];x['home_team']=g['home_team'];x['canonical_opponent']=g['home_team'] if x['team_side']=='away' else g['away_team']
 sidecols=list(sides[0]);wr('exception_game_sides.csv',sidecols,sorted(sides,key=lambda x:(x['season'],x['game_date'],x['game_id'],x['team_side'])))
 by={}
 for x in sides:by.setdefault(x['game_id'],[]).append(x)
 games=[];md=['# Manual starter review','',f'Unique affected games: **{len(by)}**','']
 for gid,ss in sorted(by.items(),key=lambda z:(z[1][0]['season'],z[1][0]['game_date'],z[0])):
  g=allg[gid];d={s['team_side']:s for s in ss};a=d.get('away');h=d.get('home');reason='|'.join(('ZERO_CANDIDATE_AWAY' if a and a['exception_type']=='ZERO_CANDIDATE' else 'MULTI_CANDIDATE_AWAY' if a else '', 'ZERO_CANDIDATE_HOME' if h and h['exception_type']=='ZERO_CANDIDATE' else 'MULTI_CANDIDATE_HOME' if h else '')).strip('|')
  def f(s,k):return s[k] if s else g['candidate_'+k] if False else ''
  games.append({'game_id':gid,'season':g['season'],'week':g['week'],'season_type':g['season_type'],'gameday':g['game_date'],'away_team':g['away_team'],'home_team':g['home_team'],'away_candidate_count':a['candidate_count'] if a else g['candidate_count'] if g['team_side']=='away' else '1','away_candidate_names':a['candidate_names'] if a else '','away_candidate_pfr_ids':a['candidate_pfr_ids'] if a else '','away_candidate_ranks':a['candidate_ranks'] if a else '','away_candidate_positions':a['candidate_positions'] if a else '','home_candidate_count':h['candidate_count'] if h else '1','home_candidate_names':h['candidate_names'] if h else '','home_candidate_pfr_ids':h['candidate_pfr_ids'] if h else '','home_candidate_ranks':h['candidate_ranks'] if h else '','home_candidate_positions':h['candidate_positions'] if h else '','away_review_needed':bool(a),'home_review_needed':bool(h),'review_reason':reason})
  md += [f"### {g['game_date']} — {g['away_team']} at {g['home_team']} — {g['season']}/{g['week']}",f'Game ID: {gid}','',f"Away: candidate count: {a['candidate_count'] if a else 1}; status: {'NEEDS_REVIEW' if a else 'single candidate'}",f"Home: candidate count: {h['candidate_count'] if h else 1}; status: {'NEEDS_REVIEW' if h else 'single candidate'}",'']
 wr('affected_games.csv',list(games[0]),games)
 u=[{'rank':x['rank'],'player_name':x['player_name'],'pfr_id':x['pfr_id'],'raw_date':x['raw_date'],'raw_week':raw[x['rank']]['Week'],'raw_team':x['raw_team'],'raw_location':x['raw_location'],'raw_opp':x['raw_opp'],'raw_pos':x['raw_pos'],'existing_diagnosis':x['diagnosis']} for x in unmatched];wr('unmatched_raw_evidence.csv',list(u[0]),u)
 dc=[]
 for x in detail:
  g=allg[x['game_id']];dc.append({**{k:x[k] for k in ['game_id','season','week','season_type','team_side','canonical_team','candidate_rank','candidate_name','candidate_pfr_id']},'gameday':g['game_date'],'away_team':g['away_team'],'home_team':g['home_team'],'canonical_opponent':g['home_team'] if x['team_side']=='away' else g['away_team'],'candidate_raw_position':x['candidate_raw_pos']})
 wr('multi_candidate_detail.csv',list(dc[0]),dc);(O/'manual_starter_review.md').write_text('\n'.join(md).rstrip()+'\n')
 rep={'exception_game_side_count':99,'unique_affected_game_count':len(by),'zero_candidate_side_count':49,'multi_candidate_side_count':50,'games_with_one_exceptional_side':sum(len(v)==1 for v in by.values()),'games_with_both_sides_exceptional':sum(len(v)==2 for v in by.values()),'regular_season_affected_games':sum(g['season_type']=='REG' for g in games),'postseason_affected_games':sum(g['season_type']!='REG' for g in games),'super_bowl_affected_games':sum(g['season_type']=='SB' for g in games),'affected_game_ids':sorted(by)};(O/'manual_starter_review_report.json').write_text(json.dumps(rep,indent=2)+'\n');rep['output_sha256']={p.name:sh(p) for p in O.iterdir()};(O/'manual_starter_review_report.json').write_text(json.dumps(rep,indent=2)+'\n')
if __name__=='__main__':main()
