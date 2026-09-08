import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname,resolve} from 'node:path';

const here=dirname(fileURLToPath(import.meta.url));
const app=readFileSync(resolve(here,'..','app.js'),'utf8');

test('clicked DK/FD team offers submit canonical normalized selection',()=>{
  // The provider-facing selection remains available for display, but exact-offer
  // evaluation must use the canonical team identity already carried by the
  // validated market offer (for example Arizona Cardinals -> ARI).
  assert.match(app,/function offerSelectionMarkup\(o\)\{const selection=String\(o\.selection\|\|''\)/);
  assert.match(app,/data-selection="\$\{esc\(o\.normalized_selection\)\}"/);
  assert.doesNotMatch(app,/data-selection="\$\{esc\(o\.selection\)\}"/);
  assert.match(app,/selection:button\.dataset\.selection/);
  assert.match(app,/api\.evaluateOffer\(offer\)/);
});

test('moneyline and spread retail rows both use the shared canonical offer path',()=>{
  assert.match(app,/offers\.map\(o=>retail\?detailOfferMarkup\(g,market,book,o\):benchmarkOfferMarkup\(o\)\)/);
  assert.match(app,/data-market-tab="moneyline"/);
  assert.match(app,/data-market-tab="spread"/);
});
