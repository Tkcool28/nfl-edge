# Sleeper QB Source Contract v1

|**Status**: Source-feasibility audit, not a model input.
|**Version**: 1.0
|**Date**: August 3, 2026 (sub-phase C revision 2026-08-04)
|**Repository**: `Tkcool28/nfl-edge`
|**Branch**: `feat/sleeper-qb-source-audit-v1` (refreshed onto merged `main`; based on `cd4a483`)

## 1. Purpose

Define the read-only contract between NFL Edge and the Sleeper public
API for the bounded QB source-feasibility audit. The contract is the
document the audit reports against; the audit must not promote Sleeper
into model scoring under any verdict.

## 2. Endpoint

| Field | Value |
| --- | --- |
| Method | `GET` |
| URL | `https://api.sleeper.app/v1/players/nfl` |
| Query parameters | `position=QB&active=true` |
| Authentication | None (public, no API key) |
| Documented rate guidance | "Stay under 1000 API calls per minute" |
| Response content type | `application/json` |

The client (`nfl_edge.sources.sleeper.client`) refuses to issue any
request to a host other than `api.sleeper.app` and a path other than
`/v1/players/nfl`. 30x redirects are disabled.

## 3. Documented response schema

A JSON object keyed by Sleeper `player_id` (string). The relevant
fields are:

```text
player_id          string   Sleeper's stable id
first_name         string
last_name          string
position           string   "QB" for our purposes
team               string   NFL team abbreviation (may be null for free agents)
status             string   Sleeper roster status (e.g. "Active", "Inactive", "PUP")
active             bool     true when on a roster and not retired
gsis_id            string   NFL GSIS id; crosswalk priority 1
espn_id            string   ESPN id; crosswalk priority 2
sportradar_id      string   Sportradar id; crosswalk priority 3
yahoo_id           string   Yahoo id; crosswalk priority 3
fantasy_data_id    number   FantasyData id; crosswalk priority 3
rotowire_id        number   Rotowire id; crosswalk priority 3
depth_chart_position number   Sleeper depth chart position
depth_chart_order  number   1 = starter, 2 = backup, ...
injury_status      string   "Out" / "Questionable" / "Doubtful" / "Probable" / "IR" / "PUP" / null
injury_body_part   string|null
injury_notes       string|null
injury_start_date  string|null  YYYY-MM-DD
practice_participation   string|null  "Full" / "Limited" / "DNP"
practice_description    string|null
search_rank        number
age                number
years_exp          number
```

Sleeper does **not** expose a provider-level update timestamp in the
public response. The audit therefore tracks three independent times:

| Field | Meaning |
| --- | --- |
| `provider_updated_at` | (Not exposed) |
| `fetched_at_utc` | When the audit issued the request |
| `first_observed_at_utc` | When the audit first saw a particular field value |

## 4. Audit invariant

Every successful or failed fetch produces a `SleeperFetchResult` row in
`data/source_audits/sleeper_qb_v1/fetch_ledger.parquet` and a raw
payload in `data/source_audits/sleeper_qb_v1/raw/YYYY/MM/DD/<snapshot>_attemptNN.bin`.
The audit will not declare reliability from one successful call.

## 5. Bounded retry

The client retries up to three times (initial + two retries)
with exponential backoff (`1.0s`, `2.0s`) placed **only
between failed attempts**, never before the first attempt.

| Constant | Value |
| --- | --- |
| `DEFAULT_TIMEOUT_SECONDS` | 10.0 |
| `DEFAULT_RETRY_BACKOFF_SECONDS` | `(1.0, 2.0)` |
| `MAX_ATTEMPTS` | 3 |
| Worst-case total | 3 × 10s + (1.0 + 2.0)s = **33.0s** |
| systemd `TimeoutStartSec` | 120s (87s headroom) |
| Spec target `TimeoutStartSec` | 60s (27s headroom) |

The audit never raises the service timeout merely to
accommodate a longer client retry budget. On any non-2xx or
network exception it persists an audit envelope rather than
the upstream body, so the failure case is itself auditable.

## 5.1 Lock + write atomicity

The audit uses an OS-advisory file lock with two layers
(`O_CREAT|O_EXCL` ownership sentinel + `fcntl.flock`). The
helper honors `--lock-timeout-seconds` (default 0 = fail
fast) and recovers stale owners whose PID is no longer alive
(`kill(pid, 0)` tripwire). Every mutable artifact is written
through `atomic_io.atomic_write_parquet` / `atomic_write_text`
/ `atomic_append_parquet`, which uses temp-file + fsync +
`os.replace`. The prior valid artifact remains byte-identical
until the new one is fully durable.

## 6. Storage

| Path | Purpose |
| --- | --- |
| `data/source_audits/sleeper_qb_v1/raw/YYYY/MM/DD/*.bin` | Raw bytes per attempt |
| `data/source_audits/sleeper_qb_v1/fetch_ledger.parquet` | One row per attempt |
| `data/source_audits/sleeper_qb_v1/latest_snapshot.json` | Pointer to the most recent successful snapshot |
| `data/source_audits/sleeper_qb_v1/latest_run_status.json` | Terminal outcome of the most recent run |
| `data/source_audits/sleeper_qb_v1/hof_pregame_pointer.json` | Frozen pregame snapshot reference (HOF Game) |
| `data/source_audits/sleeper_qb_v1/normalized/qb_snapshots.parquet` | Active QB snapshots |
| `data/source_audits/sleeper_qb_v1/normalized/qb_inactive_snapshots.parquet` | Inactive QB snapshots (defensive tripwire) |
| `data/source_audits/sleeper_qb_v1/normalized/qb_evidence_states.parquet` | Per-QB audit-only state (with `snapshot_id` + `observed_at_utc`) |
| `data/source_audits/sleeper_qb_v1/normalized/qb_identity_crosswalk.parquet` | Sleeper -> nflverse crosswalk |
| `data/source_audits/sleeper_qb_v1/normalized/qb_change_ledger.parquet` | Snapshot-to-snapshot change events (prior+current snapshot ids) |
| `data/source_audits/sleeper_qb_v1/normalized/hof_game_observation.parquet` | Hall of Fame Game observation rows (pregame+postgame per QB) |
| `data/source_audits/sleeper_qb_v1/reference/manifest.json` | Reference-fixture SHA-256 manifest (tracked) |
| `data/source_audits/sleeper_qb_v1/reference/hof_game_2026_fixture.parquet` | HOF Game fixture (tracked, checksum-verified) |
| `data/source_audits/sleeper_qb_v1/reference/nflverse_player_identity_pre2025.parquet` | nflverse identity reference (tracked, checksum-verified) |
| `data/source_audits/sleeper_qb_v1/reports/sleeper_qb_live_audit.{md,json}` | Rolling live audit report (aggregates every persisted run) |
| `data/source_audits/sleeper_qb_v1/reports/sleeper_hof_game_observation.{md,json}` | HOF Game observation report |
| `data/source_audits/sleeper_qb_v1/audit.lock` | Overlap-prevention lock file (POSIX advisory) |

## 6.1 Reference fixtures (clean-clone contract)

The audit ships two reference fixtures and a manifest. Every
fresh checkout must contain:

* `reference/hof_game_2026_fixture.parquet`
* `reference/nflverse_player_identity_pre2025.parquet`
* `reference/manifest.json` (SHA-256 manifest for both)

The CLI verifies every fixture against the manifest before
each run; a missing or tampered fixture fails the run with
`REFERENCE_FAILURE` (exit 21). The crosswalk's exact-ID
priority order is: Sleeper id, GSIS, ESPN, sportradar, Yahoo,
fantasy_data, rotowire. When two nflverse rows share an exact
id, the crosswalk emits `is_matched=False`,
`review_required=True`, and a descriptive `conflict_reason`;
it never silently selects the first row.

## 7. Allowed evidence states

The audit uses eight labels. `CONFIRMED_STARTER` and `CONFIRMED_ACTIVE`
are explicitly forbidden.

| State | Meaning |
| --- | --- |
| `DEPTH_CHART_EXPECTED_HEALTHY` | depth order 1 and no adverse status |
| `DEPTH_CHART_EXPECTED_LIMITED` | depth order 1 and Limited practice |
| `DEPTH_CHART_EXPECTED_QUESTIONABLE` | Questionable / Probable / DNP |
| `DEPTH_CHART_EXPECTED_DOUBTFUL` | Doubtful |
| `DEPTH_CHART_EXPECTED_OUT` | Out / IR / PUP |
| `BACKUP_CANDIDATE` | depth order >= 2 |
| `AMBIGUOUS` | Conflicting evidence |
| `UNKNOWN` | No usable evidence (no depth order, no status) |

`UNKNOWN` is the default when no field is populated. The audit will not
infer "healthy" merely because `injury_status` is null; absence of a
designation is not equivalent to verified health.

## 8. Identity crosswalk priority

1. Exact Sleeper id (`exact_sleeper_id`).
2. Exact GSIS id (`exact_gsis`).
3. Exact ESPN id (`exact_espn`).
4. Another exact stable provider id (`exact_other_stable`).
5. Normalized name + team (`name_team_fallback`, **always
   `review_required = True`**).

The 2025 sealed holdout season is filtered out of the nflverse
reference at the crosswalk boundary even if a 2025 row is supplied,
so a 2025 row can never contribute to a crosswalk match.

### 8.1 Identity reference (nflverse player identity table)

The audit does not read the 2025 sealed model holdout. Identity
resolution uses a static nflverse identity table loaded once at
audit-config time.

| Field | Value |
|---|---|
| Source function | `nflreadpy.load_ff_playerids()` (offline build) |
| Source artifact | `data/source_audits/sleeper_qb_v1/reference/nflverse_player_identity_pre2025.parquet` |
| Filter expression | `position == "QB" AND db_season != 2025` |
| Total row count (all positions, all seasons) | 12,470 |
| Rows where `db_season == 2025` before filter | 0 (the shipped reference is the 2024 nflreadpy snapshot) |
| Row count after `position == "QB"` filter | 682 |
| Row count after `db_season != 2025` filter | 682 |
| Identity metadata only? | **Yes** (no fit, predict, score, or report is performed) |

The 2025 strip is a defensive tripwire that activates only if
the table is ever replaced with a version that contains 2025
rows; today the shipped file contains zero such rows.

## 9. Timer schedule

The twice-daily audit timer fires at `12:00 UTC` and `00:00 UTC`
(== 06:00 MDT and 18:00 MDT). The MDT mapping assumes Mountain
Daylight Time (UTC-6) during summer; the timer does not follow DST
shifts automatically. The deviation is bounded to one hour and is
acceptable for a source-feasibility audit because the audit's job
is to record change events, not to optimize clock-time alignment.

The Hall of Fame Game timers (Panthers at Cardinals, kickoff
`2026-08-07T00:00:00Z`, == 2026-08-06 20:00 America/New_York EDT, ==
2026-08-06 18:00 America/Denver MDT):

| Timer | UTC | America/New_York | America/Denver |
|---|---|---|---|
| Pregame | `2026-08-06T22:30:00Z` | `2026-08-06T18:30:00-04:00` | `2026-08-06T16:30:00-06:00` |
| Postgame | `2026-08-07T03:30:00Z` | `2026-08-06T23:30:00-04:00` | `2026-08-06T21:30:00-06:00` |

Both HOF timers are `Persistent=false` and `OnCalendar=...UTC`,
bounded to a single calendar date, and become inert after a
successful run.

## 10. Boundary guarantees

- The audit never reads from `data/derived/`, `data/modeling/`,
  `data/frozen/`, `data/raw/`, `artifacts/`, `models/`, or `reports/development/`.
- The audit never imports from `nfl_edge.models`,
  `nfl_edge.backtest`, `nfl_edge.evaluation`, or `nfl_edge.scoring`.
- The audit never reads any environment variable whose name contains
  `API_KEY`, `TOKEN`, or `SECRET`.
- The audit never makes a request to a host other than
  `api.sleeper.app`.
- The audit never writes outside `audit_root` and `/tmp` (atomic
  write temp files only).
- The 2025 sealed holdout is unreachable from the crosswalk path.

## 11. Forbidden claims

- "Sleeper is healthy" - the audit may only report
  `DEPTH_CHART_EXPECTED_HEALTHY`; it may not claim a verified health
  status.
- "Sleeper is the starter" - the audit may not emit
  `CONFIRMED_STARTER`.
- "Sleeper agrees with team depth chart" - the audit may not synthesize
  agreement it did not measure.
- "Sleeper has historical injury data" - the public endpoint is
  current-state only; the audit must not claim otherwise.

## 12. Operational ownership

This contract is owned by the audit harness. Any change to the
endpoint URL, query parameters, retry policy, or evidence-state
vocabulary is a contract change and must be reviewed before merge.
