from __future__ import annotations
import json,re,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; FRONTEND=ROOT/'frontend'
def png_size(p):
 d=p.read_bytes(); assert d[:8]==b'\x89PNG\r\n\x1a\n'; return struct.unpack('>II',d[16:24])
def test_manifest_and_install_assets_are_valid():
 m=json.loads((FRONTEND/'manifest.webmanifest').read_text()); assert m['name']==m['short_name']=='NFL EDGE'; assert m['display']=='standalone'; icons={x['sizes']:x for x in m['icons']}; assert {'192x192','512x512'}<=set(icons); assert 'maskable' in icons['192x192']['purpose']; assert png_size(FRONTEND/icons['192x192']['src'].removeprefix('./'))==(192,192); assert png_size(FRONTEND/icons['512x512']['src'].removeprefix('./'))==(512,512)
def test_index_mobile_accessible_model_driven():
 h=(FRONTEND/'index.html').read_text(); assert 'width=device-width' in h and 'manifest.webmanifest' in h and 'data/latest.json' not in h; assert 'id="offer-book"' not in h; assert 'available at any sportsbook' in h; assert 'class="skip-link"' in h and 'aria-live=' in h; assert 'backend' not in h.lower()
def test_service_worker_never_caches_api_responses():
 s=(FRONTEND/'sw.js').read_text(); assert "url.pathname.startsWith('/api/')" in s; assert "fetch(request,{cache:'no-store'})" in s; assert "nfl-edge-shell-v6" in s; assert "./ui-polish.css" in s; shell=re.search(r'APP_SHELL=\[(.*?)\];',s,re.S).group(1); assert '/api/' not in shell
def test_no_mock_or_frozen_business_logic():
 js='\n'.join(p.read_text() for p in FRONTEND.glob('*.js')); forbidden=['data/latest.json','PER_WAGER_CAP','SLATE_CAP','STAKE_FLOOR','UNIT_LADDER','RELIABILITY_HAIRCUT','PT_CONCESSION_PP','MANUAL_DEFAULT_PROB','americanToImplied','stakeFromUnits','unitDollars','ODDS_API_KEY','api.the-odds-api.com']; [(_ for _ in ()).throw(AssertionError(x)) for x in forbidden if x in js]
def test_api_routes_centralized_relative():
 a=(FRONTEND/'api.js').read_text(); app=(FRONTEND/'app.js').read_text(); core=(FRONTEND/'ui-core.js').read_text(); required=['/api/v1/health','/api/v1/auth/register','/api/v1/auth/login','/api/v1/auth/logout','/api/v1/auth/me','/api/v1/profile','/api/v1/product/latest','/api/v1/games','/api/v1/evaluate-offer','/api/v1/wagers']; assert all(x in a for x in required); assert "credentials:'include'" in a and "cache:'no-store'" in a; assert 'http://' not in a and 'https://' not in a; assert '/api/v1/' not in app and '/api/v1/' not in core
def test_user_facing_app_copy_avoids_backend_jargon():
 app=(FRONTEND/'app.js').read_text(); core=(FRONTEND/'ui-core.js').read_text(); api=(FRONTEND/'api.js').read_text(); visible='\n'.join((app,core,api)); assert 'Backend unavailable' not in visible; assert 'Backend details' not in visible; assert 'backend-calculated' not in visible; assert 'backend session' not in visible; assert 'Backend-selected' not in visible; assert 'Model details' in app; assert 'model-calculated' in app; assert 'Model-selected roof scenario.' in core; assert 'App unavailable' in api
def test_detail_market_rows_are_actionable_and_legible():
 app=(FRONTEND/'app.js').read_text(); css=(FRONTEND/'styles.css').read_text(); polish=(FRONTEND/'ui-polish.css').read_text(); assert 'data-detail-offer' in app and 'evaluateDetailOffer' in app and 'openDetailExact' in app; assert '.detail-offer' in css and '.market-offers' in css and '.model-value' in css; assert '.detail-market-tabs' in polish and '.evaluation-grid' in polish
def test_sportsbook_identity_and_extreme_black_are_explicit():
 p=(FRONTEND/'ui-polish.css').read_text(); assert 'data-book="DRAFTKINGS"' in p and 'content:"DK"' in p; assert 'data-book="FANDUEL"' in p and 'content:"FD"' in p; assert '[data-theme="extreme"]{--bg:#000;--surface:#000;--surface-2:#000' in p; assert 'background:#000!important' in p; assert 'inset 4px 0 0 var(--cmp-line)' in p
def test_local_storage_is_presentation_only():
 app=(FRONTEND/'app.js').read_text(); keys=re.findall(r"localStorage\.(?:getItem|setItem)\((?:key|'([^']+)'|\"([^\"]+)\")",app); text=' '.join(sum(([a,b] for a,b in keys),[])); assert 'bankroll' not in text.lower() and 'wager' not in text.lower() and 'password' not in text.lower()
def test_mobile_touch_and_states_exist():
 c=(FRONTEND/'styles.css').read_text(); p=(FRONTEND/'ui-polish.css').read_text(); assert '@media(max-width:340px)' in c and 'min-height:44px' in c and ':focus-visible' in c and '.state-chip' in c and '.roof-badge' in c; assert '@media(max-width:320px)' in p
