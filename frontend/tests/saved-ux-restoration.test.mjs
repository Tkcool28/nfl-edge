import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname,resolve} from 'node:path';
import {compareOffer,comparisonLabel,gameComparisonRows} from '../market-compare.js';
const here=dirname(fileURLToPath(import.meta.url));
const root=resolve(here,'..');
const read=name=>readFileSync(resolve(root,name),'utf8');

test('production layout remains primary while seven themes and compare controls are present',()=>{
  const html=read('index.html'),css=read('saved-ux.css');
  for(const marker of ['headlines','games-list','view-detail','view-check','view-bets','view-account','wager-dialog'])assert.match(html,new RegExp(marker));
  for(const marker of ['theme-popover','compare-toggle','compare-info','compare-help'])assert.match(html,new RegExp(marker));
  for(const theme of ['light','cream','slate','mint','fancy','modern','extreme'])assert.match(html,new RegExp(`data-theme-choice="${theme}"`));
  assert.match(css,/Theme: Fancy/);assert.match(css,/Theme: Modern/);assert.match(css,/Theme: Extreme/);
  assert.match(css,/--ribbon-value:#146cff/);
});

test('production frontend has no saved mock artifact authority',()=>{
  for(const name of ['index.html','api.js','ui-core.js','app.js','ux.js','market-compare.js','sw.js']){
    const source=read(name);
    assert.doesNotMatch(source,/data\/latest\.json/i,`${name} must not load saved mock data`);
    assert.doesNotMatch(source,/MOCK_GAMES|HEADLINES\s*=\s*\{/i,`${name} must not restore saved mock model state`);
  }
});

test('same-origin API and no-store service-worker exclusion remain intact',()=>{
  const api=read('api.js'),sw=read('sw.js');
  assert.match(api,/\/api\/v1\/product\/latest/);
  assert.match(api,/credentials:'include'/);
  assert.match(api,/cache:'no-store'/);
  assert.match(sw,/pathname\.startsWith\('\/api\/'\)/);
  assert.match(sw,/fetch\(request,\{cache:'no-store'\}\)/);
  assert.match(sw,/market-compare\.js/);
  assert.match(sw,/nfl-edge-shell-v5/);
});

test('Pinnacle help semantics match approved color contract',()=>{
  const html=read('index.html');
  assert.match(html,/Blue<\/strong><span>Better line than Pinnacle/);
  assert.match(html,/Green<\/strong><span>Better price than Pinnacle/);
  assert.match(html,/Purple<\/strong><span>Both line and price are better/);
  assert.match(html,/Red<\/strong><span>The line or price is worse than Pinnacle/);
  assert.match(html,/No color<\/strong><span>Same line and price as Pinnacle/);
  assert.match(html,/Pinnacle is the hidden benchmark/);
});

test('offer comparison is side-aware and worse overrides mixed improvement',()=>{
  assert.equal(compareOffer('spread',{selection:'CHI',line:-7,price:-110},{selection:'CHI',line:-10,price:-110}),'line');
  assert.equal(compareOffer('spread',{selection:'MIN',line:10,price:-110},{selection:'MIN',line:7,price:-110}),'line');
  assert.equal(compareOffer('total',{selection:'OVER',line:47.5,price:-110},{selection:'OVER',line:48.5,price:-110}),'line');
  assert.equal(compareOffer('total',{selection:'UNDER',line:49.5,price:-110},{selection:'UNDER',line:48.5,price:-110}),'line');
  assert.equal(compareOffer('moneyline',{selection:'CHI',line:null,price:+105},{selection:'CHI',line:null,price:-105}),'price');
  assert.equal(compareOffer('spread',{selection:'CHI',line:-7,price:-120},{selection:'CHI',line:-10,price:-110}),'worse');
  assert.equal(compareOffer('spread',{selection:'CHI',line:-7,price:+100},{selection:'CHI',line:-10,price:-110}),'both');
  assert.equal(compareOffer('spread',{selection:'CHI',line:-10,price:-110},{selection:'CHI',line:-10,price:-110}),'same');
  assert.equal(comparisonLabel('both'),'better line + price');
});

test('board comparison rows include moneyline and spread for both retail books and never Pinnacle',()=>{
  const game={market_board:{
    moneyline:{DRAFTKINGS:[{selection:'CAR',line:null,price:130},{selection:'CHI',line:null,price:-155}],FANDUEL:[{selection:'CAR',line:null,price:132},{selection:'CHI',line:null,price:-156}],PINNACLE:[{selection:'CAR',line:null,price:132},{selection:'CHI',line:null,price:-149}]},
    spread:{DRAFTKINGS:[{selection:'CAR',line:2.5,price:-102},{selection:'CHI',line:-2.5,price:-118}],FANDUEL:[{selection:'CAR',line:2.5,price:102},{selection:'CHI',line:-2.5,price:-124}],PINNACLE:[{selection:'CAR',line:2.5,price:102},{selection:'CHI',line:-2.5,price:-115}]}
  }};
  const rows=gameComparisonRows(game);
  assert.equal(rows.length,8);
  assert.deepEqual([...new Set(rows.map(r=>r.market))],['moneyline','spread']);
  assert.deepEqual([...new Set(rows.map(r=>r.book))],['DRAFTKINGS','FANDUEL']);
  assert.ok(rows.every(r=>r.book!=='PINNACLE'));
});

test('game detail offers are actionable and reuse exact-offer evaluator without provider access',()=>{
  const app=read('app.js');
  assert.match(app,/data-detail-offer/);
  assert.match(app,/evaluateDetailOffer/);
  assert.match(app,/api\.evaluateOffer\(offer\)/);
  assert.match(app,/openDetailExact/);
  assert.match(app,/Log wager/);
  assert.doesNotMatch(app,/the-odds-api|sleeper/i);
});

test('team logos and QB headshots use existing game identity with resilient fallbacks',()=>{
  const ux=read('ux.js');
  assert.match(ux,/a\.espncdn\.com\/i\/teamlogos\/nfl\/500/);
  assert.match(ux,/sleepercdn\.com\/content\/nfl\/players\/thumb/);
  assert.match(ux,/sleeper_player_id/);
  assert.match(ux,/asset-fallback/);
  assert.match(ux,/asset-failed/);
  assert.match(ux,/decorateQbCard/);
  assert.match(ux,/detail-matchup-visual/);
  assert.match(ux,/game-matchup-visual/);
  assert.doesNotMatch(ux,/api\.sleeper|the-odds-api/i);
});

test('extreme primary actions are outlined chartreuse and header is protected from wrapping',()=>{
  const saved=read('saved-ux.css'),base=read('styles.css');
  assert.match(saved,/\[data-theme="extreme"\] \.btn-primary\{border:1px solid #c7ff00;background:#080a08;color:#c7ff00/);
  assert.match(base,/\.app-name\{font-weight:800;white-space:nowrap/);
  assert.match(base,/grid-template-columns:minmax\(0,1fr\) auto/);
});

test('theme and comparison settings are persisted locally without provider API access',()=>{
  const ux=read('ux.js');
  assert.match(ux,/nfl-edge-theme-v1/);
  assert.match(ux,/nfl-edge-pinny-compare-v1/);
  assert.match(ux,/new ApiClient/);
  assert.match(ux,/ML/);
  assert.match(ux,/SPREAD/);
  assert.doesNotMatch(ux,/the-odds-api|api\.sleeper/i);
});

test('mobile rules and four production tabs remain explicit',()=>{
  const saved=read('saved-ux.css'),base=read('styles.css'),html=read('index.html');
  assert.match(saved,/@media\(max-width:320px\)/);
  assert.match(base,/grid-template-columns:repeat\(4,1fr\)/);
  assert.equal((html.match(/data-nav=/g)||[]).length,4);
});
