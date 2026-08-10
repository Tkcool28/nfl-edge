import csv,hashlib,json
from pathlib import Path
import pandas as pd
R=Path(__file__).resolve().parents[2];B=R/'data/derived/stathead_actual_starters_v1';O=B/'final_oracle_starters';X=Path('/root/nfl-edge-task04a-raw/crosswalk/players.csv.gz')
def sh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 g=list(csv.DictReader(open(B/'stage01_canonical_reconciliation/game_side_candidates.csv')));v=list(csv.DictReader(open(B/'manual_starter_review/web_researched_starter_resolutions_v2.csv')));vk={(x['game_id'],x['team_side']):x for x in v};assert len(g)==3884 and len(vk)==99
 c=pd.read_csv(X,dtype=str);assert sh(X)=='c2da9ec0ac104ba4a1240c164c48452e8dfefe49425a482a0e3073267d6b97ba';cm=dict(zip(c.pfr_id,c.gsis_id));dist={};out=[]
 for x in g:
  k=(x['game_id'],x['team_side']);n=int(x['candidate_count']);dist[n]=dist.get(n,0)+1;assert (n==1)==(k not in vk)
  if k in vk:r=vk[k];name,pfr,gsis=r['actual_starting_qb_name'],r['actual_starting_qb_pfr_id'],r['actual_starting_qb_gsis_id'];cl='SPECIAL_KENDALL_HINTON_QB_ROLE_EXCEPTION' if r['identity_mapping_status'].startswith('SPECIAL') else 'VALIDATED_MANUAL_WEB_EXCEPTION';src='VALIDATED_MANUAL_WEB_RESEARCH';rank='';loc=r['source_locator_note'];notes=r['notes']
  else:name,pfr=x['candidate_names'],x['candidate_pfr_ids'];gsis=cm[pfr];cl='STATHEAD_UNAMBIGUOUS_SINGLE_CANDIDATE';src='STATHEAD_QB_STARTED_QUERY';rank=x['candidate_ranks'];loc=f'Stage01 canonical reconciliation rank {rank}';notes=''
  assert name and pfr and gsis
  sem=cl.startswith('SPECIAL');out.append({'season':x['season'],'week':x['week'],'season_type':x['season_type'],'gameday':x['game_date'],'game_id':x['game_id'],'away_team':x['away_team'],'home_team':x['home_team'],'team_side':x['team_side'],'canonical_team':x['canonical_team'],'canonical_opponent':x['home_team'] if x['team_side']=='away' else x['away_team'],'actual_starting_qb_name':name,'actual_starting_qb_pfr_id':pfr,'actual_starting_qb_gsis_id':gsis,'starter_resolution_class':cl,'starter_source':src,'starter_source_game_id':x['game_id'],'starter_source_locator':loc,'starter_source_rank':rank,'starter_evidence_class':'POSTGAME_ACTUAL_STARTER','historical_model_usage':'ORACLE_STARTER_IDENTITY_ONLY','postseason_flag':x['season_type']!='REG','semantic_exception_flag':sem,'official_qb_start_credit':'NONE' if sem else 'CREDITED','notes':notes})
 assert dist=={0:49,1:3785,2:49,3:1} and len(out)==3884
 O.mkdir(exist_ok=True);p=O/'actual_starting_qb_game_sides_2018_2024_v1.csv'
 with p.open('w',newline='') as f:w=csv.DictWriter(f,out[0],lineterminator='\n');w.writeheader();w.writerows(out)
 games={}
 for x in out:games.setdefault(x['game_id'],[]).append(x)
 rows=[]
 for gid,z in games.items():
  a,h=sorted(z,key=lambda q:q['team_side']);a,h=(a,h) if a['team_side']=='away' else (h,a);rows.append({'season':a['season'],'week':a['week'],'season_type':a['season_type'],'game_date':a['gameday'],'game_id':gid,'away_team':a['away_team'],'home_team':a['home_team'],**{f'{s}_{k}':q[k] for s,q in [('away',a),('home',h)] for k in ['actual_starting_qb_name','actual_starting_qb_pfr_id','actual_starting_qb_gsis_id','starter_source','starter_source_locator','starter_resolution_class','semantic_exception_flag','official_qb_start_credit']},'starter_evidence_class':'POSTGAME_ACTUAL_STARTER','historical_model_usage':'ORACLE_STARTER_IDENTITY_ONLY','postseason_flag':a['postseason_flag']})
 assert len(rows)==1942
 q=O/'actual_starting_qbs_by_game_2018_2024_v1.csv';
 with q.open('w',newline='') as f:w=csv.DictWriter(f,rows[0],lineterminator='\n');w.writeheader();w.writerows(rows)
 pd.DataFrame(rows).to_parquet(O/'actual_starting_qbs_by_game_2018_2024_v1.parquet',index=False)
 rep={'canonical_games':1942,'canonical_game_sides':3884,'ordinary_single_candidate_sides':3785,'validated_exception_sides':99,'final_game_side_rows':3884,'final_game_rows':1942,'pfr_resolved':3884,'pfr_unresolved':0,'gsis_resolved':3884,'gsis_unresolved':0,'semantic_exception_count':1,'semantic_exception_keys':['2020_12_NO_DEN:home'],'season_game_counts':{s:sum(x['season']==s for x in rows) for s in sorted({x['season'] for x in rows})},'postseason_games':sum(x['season_type']!='REG' for x in rows),'super_bowl_games':sum(x['season_type']=='SB' for x in rows),'crosswalk_path':str(X),'crosswalk_sha256':sh(X),'output_sha256':{z.name:sh(z) for z in [p,q,O/'actual_starting_qbs_by_game_2018_2024_v1.parquet']}};(O/'final_oracle_starter_validation_report_v1.json').write_text(json.dumps(rep,indent=2)+'\n')
if __name__=='__main__':main()
