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
