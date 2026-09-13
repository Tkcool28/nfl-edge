import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname, resolve} from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const read = name => readFileSync(resolve(here, '..', name), 'utf8');

test('Daily News API-client shell contract uses a fresh cache identity', () => {
  const sw = read('sw.js');
  const api = read('api.js');
  const news = read('news.js');

  assert.match(sw, /SHELL_REVISION='daily-news-api-client-v1'/);
  assert.match(sw, /CACHE_NAME='nfl-edge-shell-v22'/);
  assert.doesNotMatch(sw, /nfl-edge-shell-v21/);
  assert.match(sw, /['"]\.\/api\.js['"]/);
  assert.match(sw, /caches\.delete\(CACHE_NAME\)/);
  assert.match(sw, /fetch\(path,\{cache:'reload'\}\)/);
  assert.match(sw, /fetch\(request,\{cache:'no-store'\}\)/);

  assert.match(api, /newsLatest\(\)\{return this\.request\('\/api\/v1\/news\/latest'\);\}/);
  assert.match(news, /import \{ApiClient,ApiError\} from '\.\/api\.js';/);
  assert.match(news, /api\.newsLatest\(\)/);
});
