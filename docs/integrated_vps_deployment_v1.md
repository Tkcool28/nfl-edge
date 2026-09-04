# NFL EDGE Integrated VPS Deployment V1

## Status and boundary

This document is the repository-side deployment procedure for the milestone target:

```text
NFL_EDGE_INTEGRATED_VPS_DEPLOYMENT_READY
```

Repository preparation alone does **not** earn that verdict. Final acceptance requires the VPS/external-device proofs listed below.

This milestone is deployment/integration only. It must not change model methodology, evaluators, selectors, staking, automatic wager settlement, or launch UX.

## Reviewed repository starting point

The implementation branch for this deployment milestone starts from the exact PR #99 merge commit:

```text
a5a3d039c81a77050c7e20b1c6ac5f15d53fa8ec
```

The production origin recorded by the existing deployment contract is:

```text
https://nfl.tkhermes.duckdns.org
```

Before VPS work, re-check current `origin/main`; deploy only a reviewed/merged commit, never an unmerged feature-branch head.

## Architecture

```text
browser / installed PWA
    |
    v
Caddy HTTPS :443
    |-- static -> /srv/nfl-edge/frontend/current
    |
    `-- /api/* -> 127.0.0.1:8769
                       |
                       v
             scripts/run_backend_v1.py
                       |
                       v
                    FastAPI
               /       |        \
              /        |         \
 persistent SQLite  product     tracked entering-2026
 users/profiles/     latest      decision state
 sessions/wagers
```

The request-serving backend never acquires sportsbook data and never scores/refits football models.

## 1. Pre-change VPS inventory — mandatory

Run this inspection before changing the VPS. Record outputs in the deployment report.

```bash
cd /root/nfl-edge

git fetch origin
git branch --show-current
git rev-parse HEAD
git rev-parse origin/main
git status --short
git diff --name-only
git diff --cached --name-only
# Inventory untracked/ignored runtime state. Do not delete it.
git status --short --untracked-files=all

systemctl list-unit-files 'nfl-edge*'
systemctl list-timers --all 'nfl-edge*'
systemctl --no-pager --full status 'nfl-edge*' || true

ss -ltnp

caddy validate --config /etc/caddy/Caddyfile
sha256sum /etc/caddy/Caddyfile

find /root/nfl-edge -maxdepth 3 -type d -print | sort
find /var/lib/nfl-edge /srv/nfl-edge /etc/nfl-edge -maxdepth 3 -print 2>/dev/null | sort || true
```

Also identify:

- current production product candidate/latest artifact;
- current entering-2026 decision state and its Git SHA;
- current Python interpreter/venv used by NFL EDGE services;
- existing Caddy NFL site block, if any;
- current Sleeper latest successful run and next timer firing;
- any live-market/product refresh services/timers;
- all unrelated services that must not be restarted.

**Do not run `git clean`.** Preserve unrelated untracked/runtime artifacts.

## 2. Repository update

The normal deployment path is a reviewed merged commit on `main`.

```bash
cd /root/nfl-edge
git fetch origin

# Stop if tracked/staged work exists. Do not overwrite it.
git diff --quiet
git diff --cached --quiet

# Confirm the reviewed deployment commit is on origin/main before moving main.
git merge-base --is-ancestor <REVIEWED_DEPLOYMENT_SHA> origin/main

git switch main
git merge --ff-only origin/main

git rev-parse HEAD
git status --short
```

The DB and published product are not under the Git working tree and therefore are not replaced by this update.

## 3. Python/backend dependency check

Use the existing NFL EDGE `.venv` unless inspection proves a reviewed replacement is needed. The systemd unit deliberately invokes the existing startup path:

```text
/root/nfl-edge/.venv/bin/python /root/nfl-edge/scripts/run_backend_v1.py
```

Check imports first:

```bash
cd /root/nfl-edge
PYTHONPATH=/root/nfl-edge/src /root/nfl-edge/.venv/bin/python - <<'PY'
import fastapi, uvicorn, argon2
from nfl_edge.backend.settings import BackendSettings
print('backend_imports=OK')
print(BackendSettings.from_env())
PY
```

If merged project dependencies are missing, update the same venv from the repository project metadata; do not create a second server entrypoint.

## 4. Persistent runtime directories

Production authority:

```text
DB      /var/lib/nfl-edge/backend/nfl_edge_users_v1.sqlite3
product /var/lib/nfl-edge/product_v1/latest.json
```

Create directories only after confirming ownership needs from the current services/publisher:

```bash
install -d -m 0750 /var/lib/nfl-edge/backend
install -d -m 0750 /var/lib/nfl-edge/product_v1
install -d -m 0750 /var/backups/nfl-edge
install -d -m 0750 /etc/nfl-edge
install -d -m 0755 /srv/nfl-edge/frontend/releases
```

Do not put the live DB under `/root/nfl-edge/data/runtime` even though development defaults support it.

## 5. Backend environment

Install the reviewed template, then inspect every value before service activation:

```bash
install -m 0600 /root/nfl-edge/deploy/nfl-edge-backend.env.example /etc/nfl-edge/backend.env
sed -n '1,200p' /etc/nfl-edge/backend.env
```

Required production choices are:

- `NFL_EDGE_BACKEND_HOST=127.0.0.1`
- `NFL_EDGE_BACKEND_PORT=8769`
- DB under `/var/lib/nfl-edge/backend`
- product root under `/var/lib/nfl-edge/product_v1`
- accepted tracked entering-2026 decision state
- 30-day session lifetime unless deliberately changed
- `NFL_EDGE_COOKIE_SECURE=true`
- `NFL_EDGE_COOKIE_SAMESITE=lax`
- final hostname in `NFL_EDGE_ALLOWED_HOSTS`
- same-origin `NFL_EDGE_ALLOWED_ORIGIN=` empty by default
- auth rate limit retained

No `ODDS_API_KEY` belongs in the backend environment.

## 6. Product publication / last-good bootstrap

First inspect whether `/var/lib/nfl-edge/product_v1/latest.json` already contains a valid current product. If it does, do not republish merely for deployment plumbing.

If the stable production publication directory is new, promote an already-existing valid product candidate through the existing publication path:

```bash
cd /root/nfl-edge
PYTHONPATH=/root/nfl-edge/src /root/nfl-edge/.venv/bin/python \
  scripts/publish_backend_product_v1.py \
  <ALREADY_VALID_PRODUCT_CANDIDATE.json> \
  --publication-dir /var/lib/nfl-edge/product_v1
```

This step is validation/publication only. Do not run live sportsbook acquisition just to populate deployment plumbing.

Confirm:

```bash
ls -la /var/lib/nfl-edge/product_v1
python -m json.tool /var/lib/nfl-edge/product_v1/latest.json >/dev/null
```

A deliberately bad production publication is **not** required to test last-good behavior; use existing integration/fixture proof for failure semantics.

## 7. SQLite production proof and backup

After the backend has initialized the production DB, verify the application connection settings without changing them:

```bash
cd /root/nfl-edge
NFL_EDGE_DB_PATH=/var/lib/nfl-edge/backend/nfl_edge_users_v1.sqlite3 \
PYTHONPATH=/root/nfl-edge/src \
/root/nfl-edge/.venv/bin/python - <<'PY'
import os
from nfl_edge.backend.db import BackendDatabase

db = BackendDatabase(os.environ['NFL_EDGE_DB_PATH'])
conn = db._connect()
try:
    print('journal_mode=' + str(conn.execute('PRAGMA journal_mode').fetchone()[0]))
    print('busy_timeout=' + str(conn.execute('PRAGMA busy_timeout').fetchone()[0]))
    print('foreign_keys=' + str(conn.execute('PRAGMA foreign_keys').fetchone()[0]))
finally:
    conn.close()
PY
```

Expected:

```text
journal_mode=wal
busy_timeout=30000
foreign_keys=1
```

### Safe online backup

Use SQLite's backup API so WAL state is captured consistently while the service is live:

```bash
DB=/var/lib/nfl-edge/backend/nfl_edge_users_v1.sqlite3
BACKUP=/var/backups/nfl-edge/nfl_edge_users_v1-$(date -u +%Y%m%dT%H%M%SZ).sqlite3

/root/nfl-edge/.venv/bin/python - "$DB" "$BACKUP" <<'PY'
import sqlite3, sys
src_path, dst_path = sys.argv[1:3]
src = sqlite3.connect(src_path)
dst = sqlite3.connect(dst_path)
try:
    src.backup(dst)
finally:
    dst.close()
    src.close()
check = sqlite3.connect(dst_path)
try:
    result = check.execute('PRAGMA integrity_check').fetchone()[0]
finally:
    check.close()
print('backup=' + dst_path)
print('integrity_check=' + str(result))
if result != 'ok':
    raise SystemExit(1)
PY
```

Record the backup path, size, checksum, and `integrity_check=ok`.

### Restore procedure

Restore only when genuinely required:

1. stop `nfl-edge-backend.service`;
2. preserve the current DB and any WAL/SHM companions as a pre-restore recovery set;
3. place the integrity-checked backup at the configured DB path;
4. remove stale `-wal`/`-shm` files only while the backend is stopped;
5. restore the reviewed owner/group/mode;
6. start the backend;
7. repeat DB health, account/profile, session, and wager proof.

Ordinary code/frontend rollback must **not** replace the DB.

## 8. Backend systemd activation

Install only the reviewed backend service unit:

```bash
install -m 0644 /root/nfl-edge/deploy/systemd/nfl-edge-backend.service \
  /etc/systemd/system/nfl-edge-backend.service

systemd-analyze verify /etc/systemd/system/nfl-edge-backend.service
systemctl daemon-reload
systemctl enable --now nfl-edge-backend.service
systemctl --no-pager --full status nfl-edge-backend.service
journalctl -u nfl-edge-backend.service -n 100 --no-pager
```

Prove loopback-only bind:

```bash
ss -ltnp | grep ':8769'
```

The listener must be `127.0.0.1:8769`, not `0.0.0.0:8769` or a public address.

Local backend health:

```bash
curl -fsS http://127.0.0.1:8769/api/v1/health | python -m json.tool
```

Do not hide a stale/unavailable product state merely to make health look green.

## 9. Frontend activation

The production frontend source is the merged repository `frontend/` directory. Activate it by exact Git SHA:

```bash
/root/nfl-edge/deploy/scripts/sync_frontend_v1.sh /root/nfl-edge /srv/nfl-edge/frontend
readlink -f /srv/nfl-edge/frontend/current
```

The helper refuses tracked/staged changes and refuses to replace a non-symlink `current` path. It creates a versioned release under `releases/<git-sha>` and atomically switches `current`.

Do not deploy the old `NFL_Front` staging tree.

## 10. Caddy integration

Before change:

```bash
cp -a /etc/caddy/Caddyfile /etc/caddy/Caddyfile.pre-nfl-edge-integrated-v1
sha256sum /etc/caddy/Caddyfile /etc/caddy/Caddyfile.pre-nfl-edge-integrated-v1
```

Integrate only the isolated site block from:

```text
deploy/caddy/nfl-edge.Caddyfile
```

Do not replace unrelated site blocks. Then:

```bash
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
systemctl --no-pager --full status caddy
```

External HTTPS proof:

```bash
curl -fsSI https://nfl.tkhermes.duckdns.org/
curl -fsS https://nfl.tkhermes.duckdns.org/api/v1/health | python -m json.tool
curl -fsSI https://nfl.tkhermes.duckdns.org/manifest.webmanifest
curl -fsSI https://nfl.tkhermes.duckdns.org/sw.js
```

Confirm a valid certificate, no redirect to HTTP, manifest MIME `application/manifest+json`, JavaScript service-worker MIME, and API `Cache-Control: no-store`.

## 11. Anonymous application proof

From the public HTTPS origin, with no session cookie:

- frontend shell loads;
- health/freshness renders accurately;
- product board/headline lanes populate from the production backend;
- generic recommended units appear;
- personalized dollar stakes are absent;
- no mock fixture is authority;
- no authentication error is shown merely because the visitor is anonymous.

Capture product version from both UI/API to prove the frontend is reading the production backend.

## 12. Bounded production test accounts

Use clearly labeled test usernames and non-reused test passwords. Do not place passwords or raw cookies in the deployment report/journal.

For User A prove:

1. registration succeeds over public HTTPS;
2. Secure/HttpOnly session cookie is issued;
3. `/api/v1/auth/me` returns User A;
4. profile starts with defaults;
5. set non-zero bankroll;
6. set a non-default risk profile;
7. reload browser and confirm identity/profile persist;
8. close/reopen browser and confirm identity persists while session is valid.

For generic recommendation invariance, record anonymous canonical fields and authenticated canonical fields for the same product version. These must remain unchanged:

- probability;
- trust probability;
- lane;
- recommendation state;
- recommended units;
- Play Through;
- Value At.

Only the overlay `recommended_dollars` should personalize by bankroll/risk profile.

## 13. Wager persistence and isolation

User A:

1. log one clearly labeled test/current headline wager if the live product permits;
2. verify create response;
3. verify the card logged state;
4. verify wager history;
5. restart only `nfl-edge-backend.service`;
6. reload the app;
7. verify wager, profile, and session still exist.

Create User B for isolation proof:

- User B cannot list User A wagers;
- User B cannot fetch/patch User A wager ID;
- User B profile is independent;
- with a different bankroll/risk profile, the same canonical recommendation may produce a different personalized dollar stake.

Do not manipulate any non-test user's data.

## 14. Exact-offer proof

Through the public frontend/backend stack, using supported current offers:

- evaluate one DraftKings offer;
- evaluate one FanDuel offer;
- confirm backend provenance/state is returned;
- confirm authenticated personalized dollars when verdict/units permit;
- confirm Pinnacle remains reference/non-actionable rather than a user betting target.

No browser request may call the sportsbook provider directly.

If the current product has no natural duplicate headline or roof-sensitive case, use the already-accepted fixture/integration proof rather than altering the production product.

## 15. Freshness / last-good proof

Production should be observed in its actual current freshness state. Do not corrupt the live product.

Accepted code/integration evidence covers FRESH, AGING, STALE, unavailable, failed-refresh metadata, and last-good retention. External production proof must confirm that the UI accurately reflects the current backend health state.

## 16. PWA and offline proof — Android Chrome priority

From `https://nfl.tkhermes.duckdns.org`:

1. confirm manifest resolves;
2. confirm 192/512 icons resolve;
3. confirm service worker registers at root scope;
4. install/Add to Home Screen when Chrome exposes the action;
5. launch from icon;
6. confirm standalone presentation;
7. confirm the existing authenticated session is recognized;
8. confirm product/profile/wagers/API requests work in standalone mode.

Offline test:

1. with the app loaded, disable network;
2. reload/launch;
3. app shell or `offline.html` may load;
4. no cached API recommendation may appear as a current actionable bet;
5. restore network;
6. confirm product/health return normally.

The merged service worker already routes `/api/` to network fetch with `cache: 'no-store'`; production proof verifies that deployed behavior rather than changing it.

## 17. Restart and reboot readiness

Restart only NFL EDGE backend:

```bash
systemctl restart nfl-edge-backend.service
systemctl is-active nfl-edge-backend.service
systemctl is-enabled nfl-edge-backend.service
curl -fsS https://nfl.tkhermes.duckdns.org/api/v1/health | python -m json.tool
```

Then reconfirm:

- frontend reachable;
- DB survives;
- session survives by design because sessions persist server-side;
- profile/wager survives;
- product survives;
- Caddy remains active.

A whole-VPS reboot is not required for this milestone if it risks unrelated services. Reboot readiness is accepted from `systemctl is-enabled`, dependency inspection, filesystem persistence, and service restart proof unless a separately inventoried safe reboot is explicitly chosen.

## 18. Sleeper non-interference

Record before and after:

```bash
systemctl list-timers --all 'nfl-edge-sleeper*'
systemctl --no-pager --full status 'nfl-edge-sleeper*' || true
journalctl -u nfl-edge-sleeper-qb-audit.service -n 50 --no-pager
```

Confirm latest successful run and next scheduled run. Do not change cadence/methodology for deployment convenience.

## 19. Live market/product scheduling and Odds API cost

Inventory the existing production refresh path. Deployment plumbing should reuse a valid already-produced product and consume:

```text
provider requests: 0
Odds API credits:  0
```

If a later acceptance step genuinely requires a live refresh, it must be explicit, bounded, counted, and reported separately. Credits are credits, not dollars.

## 20. Logging and permissions

Confirm:

- backend startup/failure visible in `journalctl -u nfl-edge-backend.service`;
- Caddy routing errors visible in Caddy journal;
- auth errors are summary-level only;
- no password/raw session token/provider key appears in logs;
- `/etc/nfl-edge/backend.env` is not world-readable;
- DB directory/file and backup directory have controlled permissions;
- product publication is writable only by intended backend/publisher identities;
- frontend release files are readable by Caddy and not writable by the public server process;
- no live DB, session token, or secret is committed to Git.

## 21. Repeatable update procedure

For later merged application updates:

1. inventory repo/runtime/service state;
2. back up DB when the change warrants a recovery point;
3. fetch `origin/main`;
4. fast-forward only with tracked/staged tree understood;
5. preserve all `/var/lib/nfl-edge` runtime state;
6. update the existing `.venv` only when dependencies changed;
7. run `sync_frontend_v1.sh` for the new Git SHA;
8. restart only `nfl-edge-backend.service` if backend code/config changed;
9. validate local and public health;
10. validate frontend/PWA assets;
11. verify Sleeper/unrelated services unchanged.

No manual random-file copy is the deployment authority.

## 22. Rollback

Record before deployment:

- previous known-good Git SHA;
- previous frontend `current` target;
- pre-change Caddy checksum/copy;
- last-good product version;
- latest integrity-checked DB backup when created.

### Code rollback

```bash
cd /root/nfl-edge
git switch --detach <PREVIOUS_KNOWN_GOOD_SHA>
systemctl restart nfl-edge-backend.service
```

Do not replace `/var/lib/nfl-edge/backend` or `/var/lib/nfl-edge/product_v1` during an ordinary code rollback.

### Frontend rollback

```bash
ln -s /srv/nfl-edge/frontend/releases/<PREVIOUS_SHA> /srv/nfl-edge/frontend/.current.rollback
mv -Tf /srv/nfl-edge/frontend/.current.rollback /srv/nfl-edge/frontend/current
```

### Caddy rollback

Restore the preserved Caddy file only if required, validate the complete config, then reload Caddy.

### Product rollback

Use the prior validated immutable/last-good publication. Do not fetch new provider data just to roll back presentation/backend code.

### DB recovery

Use the restore procedure in section 7 only when database recovery is genuinely required.

## 23. Required acceptance record

Do not emit the target verdict until every applicable item has direct evidence or a clearly identified accepted fixture proof:

1. final merged main SHA used;
2. VPS deployed SHA;
3. understood VPS repo status;
4. external HTTPS frontend;
5. `/api/v1` same-origin route;
6. backend loopback-only bind;
7. valid certificate;
8. health endpoint;
9. production product loaded;
10. anonymous board;
11. registration;
12. session persistence;
13. bankroll persistence;
14. risk-profile persistence;
15. personalized dollars;
16. canonical recommendation invariance;
17. wager logging;
18. wager restart persistence;
19. user isolation;
20. exact DraftKings evaluation;
21. exact FanDuel evaluation;
22. Pinnacle non-actionability;
23. freshness state;
24. roof-state render or accepted fixture proof;
25. manifest;
26. service worker;
27. PWA install;
28. standalone launch;
29. authenticated standalone session;
30. offline-safe behavior;
31. DB production path;
32. WAL / busy timeout / FK proof;
33. DB backup + integrity proof;
34. product publication path;
35. entering decision-state path;
36. systemd status;
37. service restart proof;
38. reboot-readiness proof;
39. Caddy validation;
40. Sleeper timer health;
41. provider request count;
42. Odds API credits consumed;
43. secrets not committed;
44. rollback procedure recorded;
45. no methodology change;
46. no UX redesign;
47. deployment defects found/fixed;
48. final repo/PR state;
49. final VPS health;
50. final verdict.

Target only after all applicable proof:

```text
NFL_EDGE_INTEGRATED_VPS_DEPLOYMENT_READY
```

After acceptance, stop. Launch UX Polish is the next separate milestone and must not begin inside this deployment task.
