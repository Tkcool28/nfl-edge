# NFL EDGE Twice-Daily Production Refresh V1

## Boundary

`nfl-edge-production-refresh.service` is the only production acquisition surface. It is a `Type=oneshot` service with no restart policy and no HTTP route. The FastAPI backend, frontend, health/product reads, game details, auth, profiles, exact-offer, and wagers cannot invoke it.

The refresh composes frozen existing contracts only:

```text
validated Sleeper audit -> football scorer -> one Odds API capture ->
market normalization -> deterministic materialization -> atomic publication ->\nobservational prospective capture
```

It neither changes models, evaluators, selectors, staking, provider set, frontend, nor settlement. Prospective capture consumes only the already-published canonical product and makes no sportsbook-provider request.

## Schedule and time zone

The existing Sleeper timer uses fixed UTC triggers: `00:00` and `12:00 UTC`. Its latest observed scheduled run completed in about four seconds. The proposed refresh timer fires five minutes later:

- `00:05 UTC`
- `12:05 UTC`

During MDT this is approximately `18:05` and `06:05` America/Denver. During MST it is approximately `17:05` and `05:05`. Both timers deliberately use fixed UTC, so local Mountain wall-clock time shifts one hour at DST transitions; the sequencing relationship remains five minutes after Sleeper in UTC.

`Persistent=false` is intentional: a reboot or downtime does **not** cause a catch-up billable Odds API request. The next ordinary scheduled cycle is the next opportunity.

## Preconditions and safety

Before scoring or any paid request, the orchestrator loads the accepted Sleeper pointer and requires `FRESH` evidence with a successful latest audit status. A missing, stale, failed, or unusable source exits `SLEEPER_NOT_READY`; provider requests remain zero.

Football scoring runs next and must produce a canonical non-empty valid snapshot. A scoring failure exits `SCORING_FAILED`; provider requests remain zero.

A normal successful provider request has an expected cost of **3 credits** (credits, not dollars) for DraftKings, FanDuel, Pinnacle × h2h/spreads/totals. The code calls the acquisition seam once only, with no retry loop. HTTP failure exits `MARKET_ACQUISITION_FAILED` after at most one attempt.

After a HTTP 200, the existing acquisition seam persists the raw response and metadata before JSON parsing. Normalization, materialization, validation, and publication therefore use the persisted response; they never reacquire. Failed downstream stages keep the previous atomic `latest.json` as last-good.

## Artifacts and status

Every acquired/attempted run uses a unique directory below:

```text
/var/lib/nfl-edge/production_refresh_v1/refresh-<UTC timestamp>/
```

Artifacts include `sleeper-source.json`, football snapshot, raw response/metadata, normalized market, candidate product, deterministic proof, and `run-status.json` as applicable. The root `latest-status.json` is an atomically written concise pointer. Neither status nor artifacts include `ODDS_API_KEY`.

Outcomes are `SUCCESS`, `SLEEPER_NOT_READY`, `SCORING_FAILED`, `MARKET_ACQUISITION_FAILED`, `MARKET_NORMALIZATION_FAILED`, `MATERIALIZATION_FAILED`, `PUBLICATION_FAILED`, or `LOCKED`. An exclusive non-blocking `flock` on `/var/lib/nfl-edge/production_refresh_v1/.production-refresh.lock` makes a concurrent invocation return `LOCKED` before it can create artifacts or call the provider.

Publication uses the existing `ProductStore.publish()` atomic publisher. Only after publication succeeds and the authoritative latest product is re-read does the orchestrator attempt prospective capture under `/var/lib/nfl-edge/prospective_card_log_v1/`. A capture failure is recorded in `run-status.json` / `latest-status.json` as `prospective_capture_result=FAILED` with redacted error metadata, but the refresh remains `SUCCESS` because the product was already published. The backend is never restarted or reloaded by this unit. The merged ProductStore refresh-on-read behavior observes the new valid `latest.json` on future product-dependent requests in the same backend PID.

## Secret installation

The repository holds only `deploy/nfl-edge-refresh.env.example`. During **post-merge deployment**, create `/etc/nfl-edge/refresh.env` with root ownership and mode `0600`; it contains the existing `ODDS_API_KEY` only. Do not put that key in a systemd unit, backend environment, logs, Git, artifacts, or chat. If an existing secure source must be copied, compare only safe SHA-256 fingerprints and never rotate the key.

## Operator commands (after merge only)

Inspect status:

```bash
systemctl status --no-pager nfl-edge-production-refresh.service
systemctl list-timers --all nfl-edge-production-refresh.timer
journalctl -u nfl-edge-production-refresh.service -n 100 --no-pager
python -m json.tool /var/lib/nfl-edge/production_refresh_v1/latest-status.json
```

Disable safely:

```bash
systemctl disable --now nfl-edge-production-refresh.timer
```

Re-enable only after a separately authorized fixture acceptance:

```bash
systemctl enable --now nfl-edge-production-refresh.timer
systemctl list-timers --all nfl-edge-production-refresh.timer
```

A manual `--live` invocation is a billable request and requires explicit owner authorization. Do not use it merely to test the scheduler. Fixture/replay acceptance must use `--market-response`, an isolated runtime root, and an isolated publication directory.

## Post-merge deployment plan (not executed by this PR)

1. `git fetch origin`, require clean tracked state, and fast-forward `/root/nfl-edge` to the reviewed merged main SHA.
2. Install the two reviewed unit files under `/etc/systemd/system/`; create `/var/lib/nfl-edge/production_refresh_v1` and `/var/lib/nfl-edge/prospective_card_log_v1` with root-only write access.
3. Install `/etc/nfl-edge/refresh.env` as `root:root 0600`, retaining the same existing key and checking only a safe fingerprint equality.
4. Run `systemctl daemon-reload` and `systemd-analyze verify` on both installed units.
5. Do **not** enable the timer yet.
6. Run a zero-credit replay fixture against isolated run/publication/prospective roots; verify candidate publication, one native-format prospective capture, capture idempotency, and backend hot-reload with unchanged backend PID where the fixture is suitable.
7. Enable the timer only after that acceptance. Inspect `systemctl list-timers --all` and record the next `00:05 UTC` and `12:05 UTC` triggers.
8. Observe the first ordinary scheduled live run as a separate acceptance event. Record one provider attempt, reported credits, artifacts, publication, unchanged backend PID, and public product transition. Do not manually trigger a second billable run merely to test scheduling.
