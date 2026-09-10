import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname,resolve} from 'node:path';

const here=dirname(fileURLToPath(import.meta.url));
const sw=readFileSync(resolve(here,'..','sw.js'),'utf8');

test('team logo fix forces installed clients to refresh cached app shell',()=>{
  assert.match(sw,/SHELL_REVISION='team-logo-lazy-fallback-v1'/);
  assert.match(sw,/CACHE_NAME='nfl-edge-shell-v20'/);
  assert.match(sw,/['"]\.\/app\.js['"]/);
  assert.match(sw,/['"]\.\/manual-guidance\.js['"]/);
  assert.match(sw,/['"]\.\/education\.js['"]/);
  assert.match(sw,/caches\.delete\(CACHE_NAME\)/);
  assert.match(sw,/fetch\(path,\{cache:'reload'\}\)/);
  assert.match(sw,/self\.skipWaiting\(\)/);
  assert.match(sw,/self\.clients\.claim\(\)/);
});
