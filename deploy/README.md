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

See `docs/deployment_contract.md` for the authoritative production boundary and `docs/integrated_vps_deployment_v1.md` for the deployment/acceptance procedure.
