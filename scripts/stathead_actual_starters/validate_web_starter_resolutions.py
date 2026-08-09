import csv,hashlib,json,re
from pathlib import Path
import pandas as pd
R=Path(__file__).resolve().parents[2];O=R/'data/derived/stathead_actual_starters_v1/manual_starter_review';X=Path('/root/nfl-edge-task04a-raw/crosswalk/players.csv.gz')
def sh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def norm(s):return re.sub(r'[^a-z0-9 ]','',s.lower()).split()
def same(a,b):return norm(a)==norm(b) or norm(a)==list(reversed(norm(b)))
def main():
 rs=list(csv.DictReader(open(O/'web_researched_starter_name_map_v1.csv')));es=list(csv.DictReader(open(O/'exception_game_sides.csv'))); rk={(x['game_id'],x['team_side']):x for x in rs};ek={(x['game_id'],x['team_side']):x for x in es};assert len(rs)==len(rk)==99 and set(rk)==set(ek)
 d=pd.read_csv(X,dtype=str);assert len(d)==25038 and sh(X)=='c2da9ec0ac104ba4a1240c164c48452e8dfefe49425a482a0e3073267d6b97ba'
 audit=[];out=[];stats={}
 for k,r in rk.items():
  e=ek[k];name=r['researched_actual_starting_qb_name'];pfr=gsis='';status='IDENTITY_UNRESOLVED';etype=e['exception_type']
  if etype=='MULTIPLE_CANDIDATES':
   cand=list(zip(e['candidate_names'].split('|'),e['candidate_pfr_ids'].split('|'))); exact=[z for z in cand if z[0]==name]; form=[]
   for cn,cp in cand:
    h=d[d.pfr_id==cp]; cw=h.display_name.iloc[0] if len(h)==1 else ''
    if not exact and len(h)==1 and same(name,cw) and same(cn,cw):form.append((cn,cp,cw))
   pick=exact[0] if len(exact)==1 else (form[0][:2] if len(form)==1 else None)
   for cn,cp in cand:
    h=d[d.pfr_id==cp];cw=h.display_name.iloc[0] if len(h)==1 else ''
    cs='EXACT_NAME_MATCH' if cn==name else ('NAME_FORM_MISMATCH_WITH_UNIQUE_PFR_ID' if any(cp==z[1] for z in form) else 'TRUE_IDENTITY_MISMATCH')
    audit.append({'game_id':k[0],'team_side':k[1],'canonical_team':r['canonical_team'],'researched_name':name,'raw_candidate_name':cn,'candidate_pfr_id':cp,'crosswalk_name':cw,'comparison_status':cs,'resolution_basis':'EXACT_STRING' if cs=='EXACT_NAME_MATCH' else 'PFR_ID_CONFIRMED_LAST_FIRST_INVERSION' if cs.startswith('NAME_FORM') else 'UNRESOLVED','notes':r['notes']})
   if pick:
    pfr=pick[1];h=d[d.pfr_id==pfr];gsis=h.gsis_id.iloc[0] if len(h)==1 else '';status='EXISTING_STATHEAD_PFR_AND_GSIS_RESOLVED' if exact else 'PFR_CONFIRMED_NAME_FORM_VARIANT_AND_GSIS_RESOLVED'
  else:
   h=d[(d.display_name==name)&(d.position=='QB')][['pfr_id','gsis_id']].drop_duplicates()
   if len(h)==1 and pd.notna(h.pfr_id.iloc[0]):pfr=h.pfr_id.iloc[0];gsis=h.gsis_id.iloc[0];status='NFLVERSE_EXACT_NAME_PFR_AND_GSIS_RESOLVED'
  out.append({'game_id':k[0],'team_side':k[1],'canonical_team':r['canonical_team'],'actual_starting_qb_name':name,'actual_starting_qb_pfr_id':pfr,'actual_starting_qb_gsis_id':gsis,'original_exception_type':etype,'starter_evidence_class':'POSTGAME_ACTUAL_STARTER','historical_model_usage':'ORACLE_STARTER_IDENTITY_ONLY','identity_mapping_status':status,'source_locator_note':r['source_locator_note'],'notes':r['notes']})
 def wr(n,rows):
  with open(O/n,'w',newline='') as f:w=csv.DictWriter(f,rows[0]);w.writeheader();w.writerows(rows)
 wr('multi_candidate_name_form_audit_v1.csv',audit);wr('web_researched_starter_resolutions_v1.csv',out)
 rep={'research_rows':99,'exception_keys_matched':99,'multi_candidate_rows':sum(x['original_exception_type']=='MULTIPLE_CANDIDATES' for x in out),'multi_exact_name_matches':sum(x['comparison_status']=='EXACT_NAME_MATCH' for x in audit),'multi_name_form_mismatches':sum(x['comparison_status'].startswith('NAME_FORM') for x in audit),'multi_name_form_resolved':sum(x['identity_mapping_status'].startswith('PFR_CONFIRMED') for x in out),'multi_true_identity_mismatches':sum(x['comparison_status']=='TRUE_IDENTITY_MISMATCH' for x in audit),'multi_unresolved':sum(x['original_exception_type']=='MULTIPLE_CANDIDATES' and not x['actual_starting_qb_pfr_id'] for x in out),'zero_candidate_rows':sum(x['original_exception_type']=='ZERO_CANDIDATE' for x in out),'zero_exact_name_resolved':sum(x['original_exception_type']=='ZERO_CANDIDATE' and bool(x['actual_starting_qb_pfr_id']) for x in out),'zero_name_form_resolved':0,'zero_unresolved':sum(x['original_exception_type']=='ZERO_CANDIDATE' and not x['actual_starting_qb_pfr_id'] for x in out),'pfr_resolved':sum(bool(x['actual_starting_qb_pfr_id']) for x in out),'pfr_unresolved':sum(not bool(x['actual_starting_qb_pfr_id']) for x in out),'gsis_resolved':sum(bool(x['actual_starting_qb_gsis_id']) for x in out),'gsis_unresolved':sum(not bool(x['actual_starting_qb_gsis_id']) for x in out),'exact_unresolved_game_side_keys':[f"{x['game_id']}:{x['team_side']}" for x in out if not x['actual_starting_qb_pfr_id']],'crosswalk_sha256':sh(X),'output_sha256':{'audit':sh(O/'multi_candidate_name_form_audit_v1.csv'),'ledger':sh(O/'web_researched_starter_resolutions_v1.csv')}};(O/'web_researched_starter_resolution_report.json').write_text(json.dumps(rep,indent=2)+'\n')
if __name__=='__main__':main()
