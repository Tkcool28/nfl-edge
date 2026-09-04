import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname,resolve} from 'node:path';
const here=dirname(fileURLToPath(import.meta.url));
const root=resolve(here,'..');
const read=name=>readFileSync(resolve(root,name),'utf8');

test('saved UX visual lineage is materially restored',()=>{
  const html=read('index.html'),css=read('saved-ux.css');
  for(const marker of ['theme-popover','theme-grid','headlines','hcard','slate','games','tabbar'])assert.match(html,new RegExp(marker));
  for(const marker of ['theme-tile-fancy','theme-tile-modern','theme-tile-extreme','hcard\\[data-lane="HHR"\\]','ribbon-balanced','edge-purple'])assert.match(css,new RegExp(marker));
});

test('production frontend has no saved mock artifact authority',()=>{
  for(const name of ['index.html','api.js','ui-core.js','app.js','ux.js','sw.js']){
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
  assert.doesNotMatch(sw,/data\/latest\.json/i);
});

test('production-only controls survive the restored shell',()=>{
  const html=read('index.html');
  for(const id of ['install-btn','account-quick-btn','view-check','view-bets','view-account','wager-dialog','exact-form'])assert.match(html,new RegExp(`id="${id}"`));
  assert.match(html,/data-nav="account"/);
  assert.match(html,/Log bet/i);
});

test('320px compatibility rules are explicit',()=>{
  const css=read('saved-ux.css');
  assert.match(css,/@media\(max-width:320px\)/);
  assert.match(css,/grid-template-columns:repeat\(4,1fr\)/);
});
