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

test('game comparison rows expose only actionable books, never Pinnacle',()=>{
  const game={market_board:{spread:{DRAFTKINGS:[{selection:'CHI',line:-7,price:-110}],FANDUEL:[{selection:'CHI',line:-10,price:+100}],PINNACLE:[{selection:'CHI',line:-10,price:-110}]}}};
  const rows=gameComparisonRows(game);
  assert.deepEqual(rows.map(r=>r.book),['DRAFTKINGS','FANDUEL']);
  assert.deepEqual(rows.map(r=>r.status),['line','price']);
  assert.ok(rows.every(r=>r.book!=='PINNACLE'));
});

test('theme and comparison settings are persisted locally without provider access',()=>{
  const ux=read('ux.js');
  assert.match(ux,/nfl-edge-theme-v1/);
  assert.match(ux,/nfl-edge-pinny-compare-v1/);
  assert.match(ux,/new ApiClient/);
  assert.doesNotMatch(ux,/the-odds-api|sleeper/i);
});

test('mobile rules and four production tabs remain explicit',()=>{
  const saved=read('saved-ux.css'),base=read('styles.css'),html=read('index.html');
  assert.match(saved,/@media\(max-width:320px\)/);
  assert.match(base,/grid-template-columns:repeat\(4,1fr\)/);
  assert.equal((html.match(/data-nav=/g)||[]).length,4);
});
