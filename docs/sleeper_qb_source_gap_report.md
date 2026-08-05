# Sleeper QB Source Gap Report

|**Status**: Bounded live source-feasibility audit (interim).
|**Date**: August 3, 2026 (sub-phase C revision 2026-08-04)
|**Repository**: `Tkcool28/nfl-edge`
|**Branch**: `feat/sleeper-qb-source-audit-v1` (refreshed onto merged `main`; based on `cd4a483`)

## 1. What this report covers

This report records every Sleeper-related source gap observed during
the bounded live audit. It is an interim report: the final
source-suitability verdict is deferred until the Hall of Fame Game
observation window and at least one full twice-daily cycle have
completed.

## 2. Endpoint gap inventory

| Item | Status | Evidence |
| --- | --- | --- |
| Documented filtered active-QB endpoint | Available | `https://docs.sleeper.com/` (Players -> Fetch all players) |
| Public access (no API key) | Confirmed | docs note "No API Token is necessary" |
| Rate-limit headers | Not exposed | The audit does not observe any rate-limit response headers in the success case |
| `provider_updated_at` field | **Not exposed** | The audit relies on `fetched_at_utc` and `first_observed_at_utc` instead |
| ETag support | Yes | First observation shows an `ETag` header on the response |
| Last-Modified support | Yes | First observation shows a `Last-Modified` header on the response |
| Redirection | Disabled in client | `allow_redirects=False`; the audit never follows a 30x to a mirror |
| Historical snapshots | **Not supported** | The endpoint is current-state only; the audit must not claim otherwise |

## 3. Field-population gaps observed

The audit counts how many active QB records in each snapshot have a
populated value for each downstream-relevant field. Until the bounded
window is complete, the audit cannot publish a stable ratio. The
counts in this section are reported in the live audit report
(`data/source_audits/sleeper_qb_v1/reports/sleeper_qb_live_audit.json`)
and updated on every run.

| Field | Expectation |
| --- | --- |
| `gsis_id` | Required for stable crosswalk. Sleeper returns it as a string. |
| `espn_id` | Required fallback for stable crosswalk. |
| `team` | Required for name+team fallback. May be null for free agents. |
| `injury_status` | Often null even for active QBs. The audit treats null as "no designation reported" and never as "verified healthy". |
| `injury_start_date` | String in `YYYY-MM-DD` form. The audit preserves null vs absent. |
| `practice_participation` | Often null on non-practise days. |
| `depth_chart_order` | Required for the depth-order classification. May be null. |
| `depth_chart_position` | Often null. The audit records it but does not branch on it. |

## 4. Identity crosswalk gaps

- **Name-only fallback is intentionally flagged.** The audit refuses
  to treat `name_team_fallback` matches as authoritative. They are
  emitted with `review_required=True` so a human must inspect them
  before they can ever feed into model scoring.
- **Duplicate nflverse ids are not silently merged.** The
  `duplicate_id_violations` counter in the metrics report is the
  audit's primary signal that the nflverse reference needs
  deduplication.
- **2025 is excluded by design.** The crosswalk drops any
  nflverse row with `season == 2025` before indexing, even if the
  supplied reference file contains it. This guarantees the 2025
  sealed holdout cannot influence the crosswalk.

## 5. Hall of Fame Game observation gaps

- **Kickoff time is the audit's documented assumption, not a verified
  fact.** The HOF resolver uses the project's trusted schedule source
  (nflverse `schedules`) for the 2026 preseason. The audit treats the
  `gameday` + `gametime` UTC composition as the kickoff. A
  timezone-aware nflverse schedule (with venue-local time) is not yet
  audited and is therefore not in this report.
- **Pregame evidence is preserved as a separate snapshot id.** The
  pregame collection writes its own `latest_snapshot_before_kickoff`
  value; the postgame collection appends to the change ledger rather
  than overwriting it. The audit can therefore prove, after the
  postgame snapshot, that the pregame evidence was not mutated.
- **First-snap QB is not the verdict driver.** The audit records the
  observed `depth_chart_order` for each relevant QB, but the
  source-feasibility verdict depends on reliability metrics, not on
  which QB actually took the field.

## 6. Operational gaps

- The audit's lock helper (`nfl_edge.source_audits.sleeper_qb_v1.locking`)
  is a two-layer POSIX advisory lock: an `O_CREAT|O_EXCL` ownership
  sentinel + `fcntl.flock(LOCK_EX|LOCK_NB)`. The helper honors
  `--lock-timeout-seconds` (default 0 = fail fast) and recovers
  stale owners whose PID is no longer alive (`kill(pid, 0)`
  tripwire). A dead harness does not leave the next collection
  blocked; the owner sentinel is overwritten on the next acquire.
- The twice-daily timer is documented to drift up to one hour
  seasonally because it is anchored to fixed UTC clock-times rather
  than the local Mountain Time clock. The deviation is acceptable
  for a source-feasibility audit.
- All mutable artifacts are written through
  `atomic_io.atomic_write_parquet` / `atomic_write_text` /
  `atomic_append_parquet` (temp-file + fsync + `os.replace`).
  The prior valid artifact is byte-identical until the new one
  is fully durable; a forced write failure cannot leave a
  half-written file behind.
- Per rereviews `4851615980` and `4859475614`, the audit's
  **authority model** is:
  - `run_history.parquet` is the **sole authoritative terminal
    ledger**. Every mutable artifact (latest pointers, status
    file, HOF pointer cache, live report, HOF report) is a
    *derived view* and is NEVER read for correctness.
  - A successful run appends **exactly one** row to
    `run_history.parquet`. Snapshot artifacts may exist for any
    historical fetch attempt but rows whose `snapshot_id` is not
    present in any committed history row are *ghost* rows and
    are ignored by every reader.
  - Derived-view write failures surface as `projection_warnings`
    on stderr / journald. They do NOT mutate the committed
    `RunOutcome`, do NOT append a second history row, and do NOT
    change the process exit code.
  - A failed `run_history.parquet` append returns
    `PERSISTENCE_FAILURE` (exit 13) with NO derived-view writes
    and no claim that the failure itself was recorded.
  - Stale `reports/sleeper_qb_live_audit.json` caches (cached
    `source_history` provenance disagrees with the live ledger)
    are rejected by `scripts/report_sleeper_qb_audit.py
    --report live` with `STALE_DERIVED_REPORT` (exit 2).

## 7. Unsupported claims (explicit)

- **No historical Sleeper injury data.** The audit does not
  reconstruct or impute 2018-2024 injury or practice reports from
  Sleeper. The deferred historical QB-retraining milestone in
  `docs/modeling_gap_report.md` therefore remains blocked.
- **No verified health status.** `DEPTH_CHART_EXPECTED_HEALTHY` is
  the absence of an adverse designation, not a positive medical
  claim. The audit will not promote this label into model scoring
  without a separate positive verification source.
- **No depth-chart agreement claim.** The audit reports
  `depth_chart_order` and `depth_chart_position` verbatim. It does
  not score them against any other source.
- **No CONFIRMED_STARTER state.** The audit's classifier only emits
  the eight allowed states. A test
  (`test_no_confirmed_starter_or_confirmed_active_label_emitted`)
  asserts that the forbidden labels are never produced.

## 8. Open questions

1. Will Sleeper expose a stable historical archive of player states
   that would unlock a true point-in-time historical reconstruction?
2. Will Sleeper's `injury_start_date` be a reliable pregame
   availability signal once regular-season practice reports begin?
3. Will Sleeper's `depth_chart_order` agree with the nflverse depth
   chart for the August 6, 2026 HOF Game and the regular season?
4. Is the daily rate limit (`stay under 1000 API calls per minute`)
   enforced, and if so, what is the actual response on limit
   exceeded? (Audit has not yet observed a 429.)
5. Does the HOF Game kickoff time require a venue-local timezone
   conversion that the current nflverse reference does not yet
   provide?

## 9. Recommended next actions

- Wait for the HOF Game pregame snapshot, the kickoff itself, and the
  postgame snapshot to complete.
- After the HOF window, run the bounded twice-daily collection for at
  least one full 24-hour cycle so the freshness states can be
  observed under load.
- File the final source-suitability verdict in
  `reports/source_audits/sleeper_qb_live_audit.md` and mirror the
  verdict into this gap report.
- Do not promote Sleeper into model scoring without a separate
  acceptance gate that demonstrates the source is
  `SLEEPER_QB_SOURCE_SUPPORTED` and the historical reconstruction
  audit has been completed.

## 8. Current-team crosswalk reconciliation (per snapshot, mutually exclusive)

The audit reports the following current-team QB candidate counts and
match-method buckets for snapshot
`sleeper-scheduled-20260803T222318Z-f19da9f9`:

| Bucket | Count |
|---|---|
| `total_current_team_candidates` | **127** |
| `exact_sleeper_id` | 111 |
| `exact_gsis` | 0 |
| `exact_espn` | 0 |
| `exact_other_stable` | 3 |
| `name_team_fallback` | 0 |
| `unmatched` | 13 |
| `excluded_dup_ambig` | 0 |
| **sum(buckets + unmatched + excluded)** | **127** |
| **reconciles** | **YES** |

All 13 unmatched current-team QBs are UDFAs / camp arms whose
`gsis_id` and `espn_id` are not yet populated in Sleeper:

| Sleeper id | Name | Team | GSIS | ESPN |
|---|---|---|---|---|
| 4683 | Aaron Bailey | BAL | None | 3042451 |
| 13350 | Joe Fagnano | BAL | None | None |
| 4924 | Zach Terrell | BAL | None | None |
| 13310 | Miller Moss | CHI | None | None |
| 13599 | Kyron Drones | GB | None | None |
| 7262 | Jalen Morton | IND | None | None |
| 13428 | Joey Aguilar | JAX | None | None |
| 13597 | Matthew Caldwell | LAR | None | None |
| 13802 | Jacob Clark | LV | None | None |
| 4926 | Nick Schuessler | PIT | None | None |
| 4936 | Skyler Howard | SEA | None | None |
| 12776 | Connor Bazelak | TB | None | None |
| 12792 | Garrett Greene | TB | None | None |

List length = 13 = reported `unmatched` count.

The 13-name list is restricted to current-team QBs (rows where the
Sleeper payload has a non-null `team`). It excludes:

- 227 free-agent QBs (`team IS NULL`, 100 of whom are unmatched in
  the global crosswalk)
- 1 fantasy-position-only record (Tommy Stevens, NYG; `position=TE`,
  `fantasy_positions=[QB]`) which the normalize step drops before
  the crosswalk runs
- 0 retired/inactive records (filtered out by the `active=true`
  parameter on the endpoint)
- 0 duplicate Sleeper ids (the audit would report these as
  `excluded_dup_ambig` if present; the live run had 0)

The 13-name list is **the same** as the 13-row `unmatched` slice of
the current-team crosswalk subset. The serialized
`unmatched_qb_count` (100) and the per-snapshot
`current_team_crosswalk_by_snapshot[sid].unmatched` (13) refer to
**different denominators**: 100 is all active QBs; 13 is current-team
QBs only. Both are reported; both reconcile.
