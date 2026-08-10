import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from nfl_edge.features.oracle_qb_entering_state import block_key, entering_state
from nfl_edge.models.qb_elo_config import load_qb_elo_canonical_config

ROOT = Path(__file__).resolve().parents[1]
STARTERS = ROOT / "data/derived/stathead_actual_starters_v1/final_oracle_starters/actual_starting_qb_game_sides_2018_2024_v1.csv"
STATS = ROOT / "data/frozen/qb_game_stats/qb_game_stats_2018_2025.parquet"
OUT = ROOT / "data/derived/oracle_qb_entering_state_v1"

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 cfg_raw=load_qb_elo_canonical_config(ROOT/'config/qb_elo_v1.yaml'); cfg=SimpleNamespace(replacement_passing_epa=cfg_raw['qb_adjustment_replacement_passing_epa'],sample_k=cfg_raw['qb_adjustment_sample_k'],scale_elo_per_shrunk_epa=cfg_raw['qb_adjustment_scale_elo_per_shrunk_epa'],max_abs_elo=cfg_raw['qb_adjustment_max_abs_elo'])
 starters=list(csv.DictReader(STARTERS.open())); assert len(starters)==3884
 stats=pd.read_parquet(STATS); stats=stats[stats.season<=2024].copy(); assert not (stats.season==2025).any()
 stats['block']=list(zip(stats.season,stats.season_type.map({'REG':0,'WC':1,'DIV':2,'CON':3,'SB':4}),stats.week))
 hist={}
 for r in stats.sort_values(['season','block','game_id']).to_dict('records'): hist.setdefault(r['player_id'],[]).append(r)
 out=[]
 for r in starters:
  state=entering_state(hist.get(r['actual_starting_qb_gsis_id'],[]),block_key(r['season'],r['season_type'],r['week']),cfg)
  out.append({**{k:r[k] for k in ['season','week','season_type','gameday','game_id','team_side','canonical_team','canonical_opponent','actual_starting_qb_name','actual_starting_qb_pfr_id','actual_starting_qb_gsis_id','historical_model_usage','starter_evidence_class','semantic_exception_flag','official_qb_start_credit']},'prior_qualifying_games':state.games,'prior_dropbacks':state.dropbacks,'prior_total_passing_epa':state.total_epa,'observed_prior_passing_epa':state.observed_epa,'shrinkage_weight':state.weight,'shrunk_passing_epa':state.shrunk_epa,'qb_adjustment_elo':state.adjustment,'prior_sample_class':'PRIOR_SAMPLE' if state.dropbacks else 'ZERO_PRIOR_SAMPLE','earliest_prior_game_id':state.earliest_game,'latest_prior_game_id':state.latest_game,'latest_prior_game_end_utc':state.latest_end,'target_block_key':'|'.join(map(str,block_key(r['season'],r['season_type'],r['week']))),'same_block_rows_used':0,'target_game_rows_used':0,'future_block_rows_used':0,'nfl_2025_rows_used':0})
 assert len(out)==3884 and all(x['qb_adjustment_elo'] is not None for x in out)
 OUT.mkdir(parents=True,exist_ok=True)
 def save(name,rows):
  p=OUT/name
  with p.open('w',newline='') as f:w=csv.DictWriter(f,rows[0],lineterminator='\n');w.writeheader();w.writerows(rows)
  return p
 sidecsv=save('oracle_qb_entering_state_game_sides_2018_2024_v1.csv',out); pd.DataFrame(out).to_parquet(OUT/'oracle_qb_entering_state_game_sides_2018_2024_v1.parquet',index=False)
 games=[]
 for gid in sorted({x['game_id'] for x in out}):
  a,h=sorted([x for x in out if x['game_id']==gid],key=lambda x:x['team_side']);a,h=(a,h) if a['team_side']=='away' else (h,a)
  z={'season':a['season'],'week':a['week'],'season_type':a['season_type'],'game_date':a['gameday'],'game_id':gid,'away_team':a['canonical_team'],'home_team':h['canonical_team'],'historical_model_usage':'ORACLE_STARTER_IDENTITY_ONLY','starter_evidence_class':'POSTGAME_ACTUAL_STARTER','away_semantic_exception_flag':a['semantic_exception_flag'],'home_semantic_exception_flag':h['semantic_exception_flag']}
  for side,x in [('away',a),('home',h)]:
   for k in ['actual_starting_qb_name','actual_starting_qb_pfr_id','actual_starting_qb_gsis_id','prior_qualifying_games','prior_dropbacks','prior_total_passing_epa','observed_prior_passing_epa','shrinkage_weight','shrunk_passing_epa','qb_adjustment_elo']:z[f'{side}_{k}']=x[k]
  z['oracle_qb_adjustment_net']=h['qb_adjustment_elo']-a['qb_adjustment_elo'];games.append(z)
 gamecsv=save('oracle_qb_pregame_adjustments_by_game_2018_2024_v1.csv',games);pd.DataFrame(games).to_parquet(OUT/'oracle_qb_pregame_adjustments_by_game_2018_2024_v1.parquet',index=False)
 kh=[x for x in out if x['game_id']=='2020_12_NO_DEN' and x['team_side']=='home'][0]
 rep={'game_side_rows':3884,'unique_game_side_keys':3884,'game_rows':1942,'unique_game_ids':1942,'starter_identities_matched':3884,'starter_identities_unmatched':0,'zero_prior_sample_sides':sum(x['prior_dropbacks']==0 for x in out),'prior_sample_sides':sum(x['prior_dropbacks']>0 for x in out),'same_block_rows_used':0,'target_game_rows_used':0,'future_block_rows_used':0,'nfl_2025_rows_used':0,'min_qb_adjustment':min(x['qb_adjustment_elo'] for x in out),'max_qb_adjustment':max(x['qb_adjustment_elo'] for x in out),'mean_abs_qb_adjustment':sum(abs(x['qb_adjustment_elo']) for x in out)/3884,'season_game_counts':{str(y):sum(x['season']==str(y) for x in games) for y in range(2018,2025)},'postseason_games':sum(x['season_type']!='REG' for x in games),'kendall_hinton_key':'2020_12_NO_DEN:home','kendall_hinton_prior_dropbacks':kh['prior_dropbacks'],'kendall_hinton_prior_total_passing_epa':kh['prior_total_passing_epa'],'kendall_hinton_shrunk_passing_epa':kh['shrunk_passing_epa'],'kendall_hinton_qb_adjustment_elo':kh['qb_adjustment_elo'],'qb_stats_passing_epa_semantics':'GAME_TOTAL_EPA_ON_PASS_ATTEMPTS_AND_SACKS','qb_stats_prior_epa_aggregation':'SUM(passing_epa) / SUM(attempts + sacks_suffered)','qb_stats_dropback_definition':'attempts + sacks_suffered','starter_input_sha256':sha(STARTERS),'qb_stats_source_sha256':sha(STATS),'qb_elo_config_sha256':sha(ROOT/'config/qb_elo_v1.yaml'),'output_sha256':{sidecsv.name:sha(sidecsv),gamecsv.name:sha(gamecsv)}};(OUT/'oracle_qb_entering_state_validation_report_v1.json').write_text(json.dumps(rep,indent=2)+'\n')
if __name__=='__main__':main()
