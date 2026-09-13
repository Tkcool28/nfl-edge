# Deployment Area

NFL EDGE production deployment is same-origin and isolated from unrelated VPS applications.

```text
caddy/                          reviewed NFL EDGE HTTPS/static/API site block
data omitted from Git           persistent DB/product state lives outside the repository
nfl-edge-backend.env.example    non-secret production backend settings template
scripts/                        bounded frontend activation helpers
systemd/                        NFL EDGE backend plus existing Sleeper units
```

The production application is now allowed to retain one permanent FastAPI backend runtime. That backend serves only the product/user API and must not run acquisition, scoring, model fitting, or sportsbook-provider work in HTTP request paths.

The VPS may retain the Python environment required by the backend and the already-existing Sleeper evidence services. Model-training environments, raw training archives, Streamlit, and ad-hoc provider credentials remain outside this deployment boundary.

Production state is split deliberately:

- Git-tracked application code: `/root/nfl-edge`
- public frontend releases: `/srv/nfl-edge/frontend`
- backend environment: `/etc/nfl-edge/backend.env`
- persistent user/wager DB: `/var/lib/nfl-edge/backend`
- validated product publication: `/var/lib/nfl-edge/product_v1`
- prospective runtime observations: `/var/lib/nfl-edge/prospective_card_log_v1`
- isolated prospective Git checkout: `/var/lib/nfl-edge/prospective_repo_v1` on `ops/prospective-card-evidence-v1`
- governed Daily News runtime: `/var/lib/nfl-edge/news_v1`

See `docs/deployment_contract.md` for the authoritative production boundary and `docs/integrated_vps_deployment_v1.md` for the deployment/acceptance procedure.

Prospective repository persistence is performed only by the dedicated oneshot/timer pair. It reads `/root/nfl-edge` and the runtime observation directory, writes only the isolated evidence checkout, stages only `prospective/cards/**`, and pushes only the evidence branch. It never makes sportsbook-provider calls.


## Daily News V1

Daily News runtime state lives at `/var/lib/nfl-edge/news_v1`. The backend reads only `latest.json`.

The dedicated `nfl-edge-daily-news.service`:
- reads the isolated prospective evidence checkout;
- invokes the configured research and writer commands;
- verifies evidence/source linkage and The Fade usage guidance;
- writes research/candidate artifacts;
- atomically promotes only a verified article to `latest.json`;
- leaves the last good article untouched on any failed run.

The timer is scheduled at 06:20 and 18:20 America/Denver. It adds zero Odds API calls by contract.

Research/writer command configuration lives in `/etc/nfl-edge/news.env`. The backend does not own or invoke those agents.

## ChatGPT Editorial Ingest V1

`POST /api/v1/news/editorial` is disabled unless `NFL_EDGE_NEWS_EDITORIAL_BEARER_TOKEN` is non-empty. It accepts only a bounded JSON submission using `NFL_EDGE_DAILY_NEWS_EDITORIAL_SUBMISSION_V1` and atomically stages it at `/var/lib/nfl-edge/news_v1/editorial_submissions/candidate.json`; it cannot write `candidate.json`, `latest.json`, or public archives.

`nfl-edge-news-editorial-publisher.service` is a separate deterministic oneshot template. Its companion timer template schedules 06:35 and 18:35 America/Denver, verifies the submission's 45-minute freshness plus the existing evidence/source verifier, archives idempotently, and promotes only a verified submission. Installing or enabling either the existing Daily News timer or this publisher timer is an explicit later deployment action and is not performed by this repository change.
