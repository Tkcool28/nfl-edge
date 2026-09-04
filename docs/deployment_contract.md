# NFL EDGE Production Deployment Contract

## Purpose

Define the production boundary for the integrated NFL EDGE application: HTTPS frontend/PWA, same-origin FastAPI API, persistent users/wagers, and validated last-good product publication.

This contract supersedes the former static-only deployment rule. It does not change football-model methodology, evaluators, selectors, staking, or sportsbook-provider policy.

## Production origin

```text
https://nfl.tkhermes.duckdns.org
```

Caddy is the only public application listener for NFL EDGE.

## Production request path

```text
browser/PWA
  -> Caddy HTTPS
     -> static frontend release under /srv/nfl-edge/frontend/current

browser/PWA
  -> Caddy HTTPS /api/v1/...
     -> 127.0.0.1:8769
        -> scripts/run_backend_v1.py
           -> FastAPI
              -> persistent SQLite user/wager state
              -> validated last-good product snapshot
              -> frozen entering-2026 decision state for exact-offer evaluation
```

HTTP requests must never trigger Sleeper acquisition, football scoring, sportsbook acquisition, model fitting, or product generation.

## Production paths

The default integrated deployment uses these stable paths:

```text
repository:       /root/nfl-edge
frontend releases:/srv/nfl-edge/frontend/releases/<git-sha>
frontend current: /srv/nfl-edge/frontend/current
backend env:      /etc/nfl-edge/backend.env
backend DB:       /var/lib/nfl-edge/backend/nfl_edge_users_v1.sqlite3
product root:     /var/lib/nfl-edge/product_v1
backend listener: 127.0.0.1:8769
decision state:   /root/nfl-edge/data/live/2026/entering_product_state_v1.json
```

The DB and product publication directories are deliberately outside the Git working tree. Git checkout, reset, or frontend activation must not replace them.

## Allowed production contents

- Git-tracked NFL EDGE application code at a declared commit.
- One Python environment required to run the merged backend and existing scheduled Sleeper services.
- Versioned static frontend releases generated directly from the merged `frontend/` directory.
- The dedicated FastAPI backend systemd service.
- Existing reviewed Sleeper evidence services/timers.
- Persistent SQLite user/profile/session/wager state under the declared runtime directory.
- Validated canonical product publications, immutable versions, `latest.json`, and publication status under the declared publication directory.
- Caddy configuration for the isolated NFL EDGE site.
- Bounded backup, deployment, validation, and rollback records.

## Prohibited production behavior/content

- Model refitting or methodology changes during deployment or backend startup.
- Raw historical training archives copied to the public/static tree.
- Training notebooks or ad-hoc model-development processes on the request-serving path.
- Streamlit as production authority.
- A second backend/server entrypoint when `scripts/run_backend_v1.py` already exists.
- Direct public exposure of the FastAPI listener.
- Browser-side sportsbook-provider calls.
- Odds API credentials in frontend assets or the backend service environment.
- Live SQLite files, session tokens, passwords, provider keys, or private runtime artifacts committed to Git.
- Production DB/product files inside paths subject to `git clean`, checkout replacement, or frontend release activation.
- API responses stored as authoritative service-worker cache state.

## Backend service contract

The backend must:

- use `scripts/run_backend_v1.py`;
- bind `127.0.0.1:8769` unless a reviewed deployment change explicitly selects another loopback port;
- load settings through the existing `NFL_EDGE_*` environment contract;
- use `Restart=on-failure`, bounded restart behavior, and journal logging;
- start after local filesystem/network prerequisites;
- have no provider acquisition command in `ExecStart`, `ExecStartPre`, or request handling;
- write only to declared runtime/publication locations required by the application.

## SQLite durability contract

Production DB authority is:

```text
/var/lib/nfl-edge/backend/nfl_edge_users_v1.sqlite3
```

The merged database layer remains authoritative for:

- WAL journal mode;
- `busy_timeout=30000` ms;
- `foreign_keys=ON` on application connections;
- explicit `BEGIN IMMEDIATE` write transactions;
- commit/rollback semantics.

Backups must use SQLite's online backup mechanism (CLI `.backup` or Python `sqlite3.Connection.backup`) rather than copying only the main DB file while the service is writing. A created backup is not accepted until `PRAGMA integrity_check` returns `ok`.

A restore is performed with the backend stopped. It must preserve a pre-restore copy, remove stale WAL/SHM companions only while the service is stopped, restore controlled ownership/permissions, restart the backend, and re-run health/user-state proof.

## Product publication contract

Production product authority is:

```text
/var/lib/nfl-edge/product_v1/latest.json
```

Publication uses the existing `ProductStore` / `scripts/publish_backend_product_v1.py` path. Candidates validate before promotion; immutable versions remain available when created by the publication implementation; a failed candidate must not truncate or replace the last-good `latest.json`.

The backend loads the validated last-good product at startup and serves it independently of later acquisition failures. Runtime health must report FRESH/AGING/STALE/unavailable and refresh-failure state truthfully.

## Exact-offer decision state

The backend reads the already-materialized entering-2026 decision state from the configured `NFL_EDGE_DECISION_STATE_PATH`. Deployment must point to the accepted tracked state for the deployed commit and must not regenerate/refit it during backend startup.

## Same-origin/Caddy contract

Caddy must:

- terminate HTTPS for `nfl.tkhermes.duckdns.org`;
- serve the activated `frontend/` release;
- reverse proxy `/api/*` to the loopback backend without stripping `/api`;
- keep API responses non-cacheable at the browser/proxy boundary;
- serve the service worker and manifest at root scope;
- preserve correct static MIME types;
- validate the full Caddy configuration before reload;
- leave unrelated site blocks untouched.

FastAPI is not exposed directly through the public firewall/listener surface.

## Authentication/security contract

Production sessions retain the merged backend behavior:

- server-side session persistence;
- random client token with only its hash persisted;
- HttpOnly cookie;
- Secure cookie over HTTPS;
- SameSite policy from reviewed settings;
- cookie path `/`;
- expiry enforced server-side;
- logout revokes the server-side session;
- username/session authority is not stored in browser local storage.

`NFL_EDGE_ALLOWED_HOSTS` must include the final production hostname. For the same-origin deployment, `NFL_EDGE_ALLOWED_ORIGIN` is intentionally empty unless VPS validation proves an explicit value is required; this avoids adding CORS when the frontend and API share one origin.

## Frontend/PWA contract

The merged `frontend/` directory is production authority. Do not deploy the obsolete staged `NFL_Front` tree.

The service worker may cache the app shell, but `/api/...` remains network/no-store. Offline navigation may show the offline shell; cached recommendations must not be presented as current actionable state.

## Scheduled pipelines

Sleeper / live football scoring / live markets / product generation are operationally separate from the request-serving backend. Existing Sleeper cadence/methodology is not changed by this deployment.

Live provider acquisition is not required for Caddy/backend/frontend plumbing proof. Deployment target cost is `0` new Odds API credits unless a later explicit acceptance step requires a bounded live refresh.

## Deployment source and atomicity

Application code deploys only from a declared merged Git commit. Frontend activation uses `deploy/scripts/sync_frontend_v1.sh`, which stages a versioned release and atomically changes the `current` symlink.

Before updating the production repo:

1. inventory branch/HEAD, tracked modifications, staged files, untracked/runtime paths, services, listeners, Caddy, DB/product locations, and Sleeper timers;
2. do not run `git clean`;
3. preserve unrelated runtime/untracked artifacts;
4. fetch the reviewed merged commit;
5. update code without replacing `/var/lib/nfl-edge` state;
6. activate the frontend release;
7. restart only the NFL EDGE backend if required;
8. validate local health and external HTTPS.

## Caddy change rules

- Add/update only the isolated NFL EDGE site block.
- Preserve a pre-change Caddy config copy/checksum.
- Run `caddy validate` against the full production config before reload.
- Reload rather than restart when possible.
- Verify unrelated sites/services afterward.

## Rollback

A code/frontend rollback must not roll back user/wager data.

- Code: switch the repo to the previous known-good commit (detached is acceptable for bounded rollback), then restart only the backend.
- Frontend: atomically point `/srv/nfl-edge/frontend/current` at the previous release.
- Caddy: restore the preserved previous configuration only if the NFL EDGE site change itself caused the fault, validate, then reload.
- Product: retain/restore the prior validated last-good publication without provider acquisition.
- DB: restore from an integrity-checked SQLite backup only when database recovery is actually required; ordinary code rollback does not replace the DB.

## Non-interference proof

Acceptance must confirm:

- existing Sleeper services/timers remain healthy;
- unrelated Caddy sites remain valid/reachable;
- no unrelated service is restarted/reconfigured;
- no unrelated site directory is modified;
- backend listener is loopback only;
- persistent DB/product paths survive code and service restart;
- provider requests and Odds API credits consumed are reported explicitly.

## Failure behavior

A deployment failure may not damage the last-good product, persistent user/wager DB, previous frontend release, or unrelated VPS applications. Stop and report on failed validation, unexpected repo state, invalid Caddy config, unhealthy backend, corrupt backup, or security/path mismatch rather than forcing promotion.
