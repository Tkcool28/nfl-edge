import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname,resolve} from 'node:path';

const here=dirname(fileURLToPath(import.meta.url));
const root=resolve(here,'..');
const read=name=>readFileSync(resolve(root,name),'utf8');

test('Bets tab exposes current bankroll, settled P/L, and open stakes without model math',()=>{
  const html=read('index.html'),ui=read('bankroll-ui.js');
  assert.match(html,/bankroll-ui\.js/);
  assert.match(html,/Settlement is manual; bankroll updates as results are recorded/);
  assert.match(ui,/Current bankroll/);
  assert.match(ui,/Settled P\/L/);
  assert.match(ui,/Open stakes/);
  assert.match(ui,/Open wagers reserve their stake\. Wins return the full payout\./);
  assert.match(ui,/legacy_untracked_wagers/);
  assert.doesNotMatch(ui,/model_probability|trust_probability|recommended_units|Play Through|the-odds-api|api\.sleeper|ODDS_API_KEY/i);
});

test('actual wager dollars are required by the logging UI',()=>{
  const html=read('index.html');
  assert.match(html,/id="wager-dollars"[^>]*min="0\.01"[^>]*required/);
});

test('bankroll summary uses same-origin no-store API client',()=>{
  const api=read('api.js'),ui=read('bankroll-ui.js'),sw=read('sw.js');
  assert.match(api,/bankroll\(\)\{return this\.request\('\/api\/v1\/bankroll'\);\}/);
  assert.match(ui,/api\.bankroll\(\)/);
  assert.match(sw,/\.\/bankroll-ui\.js/);
  assert.match(sw,/pathname\.startsWith\('\/api\/'\)/);
  assert.match(sw,/fetch\(request,\{cache:'no-store'\}\)/);
});
