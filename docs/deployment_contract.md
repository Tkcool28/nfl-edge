# Deployment Contract

## Purpose

Define a reproducible static deployment that does not turn the VPS into a training or application runtime.

## Production target

```text
https://nfl.tkhermes.duckdns.org
```

Caddy serves a dedicated NFL Edge static directory.

## Allowed production contents

- Generated HTML
- CSS
- JavaScript
- Public JSON
- Static images/icons when later approved
- Caddy configuration for the isolated site
- Bounded deployment and rollback records

## Prohibited production contents

- Raw play-by-play archives
- Historical model-training tables
- Training notebooks
- NFL Python virtual environments
- Streamlit
- XGBoost training processes
- Odds API credentials
- A permanent NFL backend service
- Mutable files that exist only on the VPS and cannot be reconstructed from GitHub

## Deployment source

Only a validated static bundle created from a declared repository commit and scoring run may deploy.

Required deployment metadata:

```text
deployment_id
repository_commit_sha
site_build_version
public_run_id
bundle_sha256
created_at_utc
deployed_at_utc
target_path
previous_deployment_id
```

## Staging and atomicity

1. Build the bundle outside the live directory.
2. Validate required files and JSON schema.
3. Calculate the bundle checksum.
4. Copy to a versioned staging directory on the VPS.
5. Verify file counts/checksums.
6. Atomically switch the live path or perform an equivalent safe replacement.
7. Run an external URL smoke test.
8. Retain the previous successful version for rollback.

## Restricted credentials

Deployment credentials should be limited to the NFL static deployment path and necessary commands. They must not grant broad access to unrelated repositories or services when a narrower option is practical.

## Caddy change rules

- Add one isolated site block for NFL Edge.
- Do not modify existing site blocks.
- Validate the full Caddy configuration before reload.
- Reload rather than restart when appropriate.
- Record the pre-change configuration checksum and preserve a rollback copy.

## Non-interference proof

Deployment proof must confirm:

- Existing Caddy configuration remains valid.
- Existing public endpoints remain reachable.
- No unrelated service was restarted or reconfigured.
- No existing site directory was modified.
- The NFL site uses its own directory and hostname.

## Rollback

A rollback must restore the previous successful static bundle without rebuilding the model or fetching new data.

Rollback proof includes:

- Previous deployment ID
- Command or atomic switch used
- Resulting live bundle checksum
- Public URL smoke test

## Cleanup

After final production proof:

- Remove temporary deployment directories not needed for rollback.
- Remove temporary Hermes training environments and raw local data.
- Confirm no NFL venv or raw training data exists on the VPS.
- Keep only bounded successful rollback bundles according to the retention policy.

## Failure behavior

A deployment failure may not damage the last known good public site. The workflow stops and reports when validation, transfer, checksum, Caddy validation, or smoke testing fails.
