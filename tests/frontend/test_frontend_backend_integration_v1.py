from __future__ import annotations
import json,os
from copy import deepcopy
from pathlib import Path
from fastapi.testclient import TestClient
os.environ.setdefault('NFL_EDGE_DB_PATH','/tmp/nfl-edge-frontend-integration-import.sqlite3');os.environ.setdefault('NFL_EDGE_PRODUCT_DIR','/tmp/nfl-edge-frontend-integration-import-product');os.environ.setdefault('NFL_EDGE_COOKIE_SECURE','false')
from nfl_edge.backend.app import create_app
from nfl_edge.backend.publication import ProductStore
from nfl_edge.backend.settings import BackendSettings
from nfl_edge.contracts.live_product_v1 import validate_product_snapshot
ROOT=Path(__file__).resolve().parents[2];FIXTURE=ROOT/'fixtures/contracts/nfl_edge_product_api_v1_week1_mock.json';STATE=ROOT/'data/live/2026/entering_product_state_v1.json'
def opposing(t,offer_id,selection,line,price):
 r=deepcopy(t);r.update(offer_id=offer_id,selection=selection,normalized_selection=selection,line=line,price=price);return r
def product():
 p=json.loads(FIXTURE.read_text());p['product_version']='frontend-backend-integration-v1';b=p['games'][0]['market_board'];b['moneyline']['PINNACLE'].append(opposing(b['moneyline']['PINNACLE'][0],'front-pin-ml-aaa','AAA',None,102));b['spread']['PINNACLE'].append(opposing(b['spread']['PINNACLE'][0],'front-pin-spread-bbb','BBB',-2.5,-106));b['total']['PINNACLE'].append(opposing(b['total']['PINNACLE'][0],'front-pin-total-under','UNDER',44.5,-107));validate_product_snapshot(p);return p
def test_frontend_required_api_flow_is_backend_authoritative(tmp_path):
 settings=BackendSettings(db_path=tmp_path/'users.sqlite3',product_dir=tmp_path/'publication',decision_state_path=STATE,cookie_secure=False,allowed_origin='http://testserver',allowed_hosts=('testserver',),auth_rate_limit_per_minute=100);p=product();ProductStore(settings.product_dir).publish(p);app=create_app(settings);c=TestClient(app)
 assert c.get('/api/v1/health').status_code==200;anon=c.get('/api/v1/product/latest').json();assert c.get('/api/v1/games').status_code==200;assert c.get(f"/api/v1/games/{p['games'][0]['game_id']}").status_code==200;canonical=deepcopy(anon['product']);assert anon['user'] is None;assert all(x['recommended_dollars'] is None for x in anon['headline_overlays'].values())
 pw='frontend integration durable password';assert c.post('/api/v1/auth/register',json={'username':'FrontendUser','password':pw}).status_code==201;assert c.put('/api/v1/profile',json={'bankroll':'500.00','risk_profile':'Normal'}).status_code==200
 normal=c.get('/api/v1/product/latest').json();assert normal['product']==canonical;assert normal['headline_overlays']['balanced']['recommended_dollars']=='3.50';normal_dollars=normal['headline_overlays']['balanced']['recommended_dollars'];assert normal['product']['headlines']['balanced']['recommended_units']==.75;assert normal['product']['headlines']['balanced']['model_probability']==.54
 logged=c.post('/api/v1/wagers',json={'source_type':'HEADLINE','product_version':p['product_version'],'lane':'BALANCED','actual_units':.5,'actual_dollars':'4.00','note':'frontend integration','idempotency_key':'front-balanced-1'});assert logged.status_code==201,logged.text;wid=logged.json()['wager']['wager_id'];o=c.get('/api/v1/product/latest').json()['headline_overlays']['balanced'];assert o['wager_logged'] and o['logged_wager_id']==wid and o['actual_dollars']=='4.00';assert c.get('/api/v1/wagers').json()['wagers'][0]['wager_id']==wid
 assert c.patch(f'/api/v1/wagers/{wid}',json={'status':'WON'}).json()['status']=='WON';assert c.get('/api/v1/wagers',params={'state':'settled'}).json()['wagers'][0]['wager_id']==wid
 assert c.post('/api/v1/auth/logout').status_code==204;out=c.get('/api/v1/product/latest').json();assert out['user'] is None and out['headline_overlays']['balanced']['recommended_dollars'] is None;assert c.get('/api/v1/wagers').status_code==401;assert c.post('/api/v1/auth/login',json={'username':'frontenduser','password':pw}).status_code==200
 cookies=dict(c.cookies);r=TestClient(app);r.cookies.update(cookies);assert r.get('/api/v1/auth/me').status_code==200;assert r.get('/api/v1/profile').json()['bankroll']=='500.00';assert r.get(f'/api/v1/wagers/{wid}').json()['actual_dollars']=='4.00'
 assert r.put('/api/v1/profile',json={'risk_profile':'Aggressive'}).status_code==200;a=r.get('/api/v1/product/latest').json();assert a['product']==canonical;assert a['product']['headlines']['balanced']['recommended_units']==.75;assert a['product']['headlines']['balanced']['model_probability']==.54;assert a['headline_overlays']['balanced']['recommended_dollars']!=normal_dollars
 base={'game_id':p['games'][0]['game_id'],'market_type':'MONEYLINE','selection':'BBB','line':None};dk=r.post('/api/v1/evaluate-offer',json={**base,'book':'DRAFTKINGS','price':-115});fd=r.post('/api/v1/evaluate-offer',json={**base,'book':'FANDUEL','price':-112});pin=r.post('/api/v1/evaluate-offer',json={**base,'book':'PINNACLE','price':-108});assert dk.status_code==fd.status_code==200;assert pin.status_code==422
 stale=r.post('/api/v1/wagers',json={'source_type':'HEADLINE','product_version':'obsolete','lane':'BALANCED','idempotency_key':'stale'});assert stale.status_code==409
