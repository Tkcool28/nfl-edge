# Data Source Audit — Frozen Baseline v1

## Scope and method

This audit covers NFLverse first-party data retrieved with `nflreadpy==0.1.5` for seasons 2018–2025. Retrieval uses explicit seasons and writes immutable Parquet snapshots under `data/raw/source_snapshots/v1/`. The upstream locator is the [nflverse data releases repository](https://github.com/nflverse/nflverse-data/releases).

The snapshots are audited evidence, not model features. No sportsbook odds, play-by-play archive, model, rolling feature, backtest, or score was created.

The original precise network retrieval timestamp was not recoverable from the first audit run. Source manifests therefore mark `retrieved_at_utc` unavailable rather than retaining the unsupported fixed-midnight value, preserve the snapshot file modification time as supporting filesystem evidence, and record the truthful metadata-correction time separately. Source files are versioned with `frozen-baseline-v1`; rerunning against an existing destination refuses to overwrite it.

## Source summary

| Source | Dataset purpose | Seasons | Format | Timestamp quality |
|---|---|---|---|---|
| `schedules` | Games, results, kickoff source fields, venue, roof | 2018–2025 | Parquet | `gameday`/`gametime` supplied; timezone and exact completion time require conservative handling |
| `team_stats_week` | Completed team-game statistics | 2018–2025 | Parquet | Weekly batch availability; exact game-end timestamp unavailable |
| `player_stats_week` | Weekly player/QB statistics | 2018–2025 | Parquet | Weekly batch availability; exact game-end timestamp unavailable |
| `rosters` | Season/week roster identity and status | 2018–2025 | Parquet | Batch-level season/week; not record-level publication proof |
| `depth_charts` | Team/player/position/depth snapshots | 2018–2025 | Parquet | Source `dt` preserved; semantics and record-level historical availability are not proven |
| `snap_counts` | Participation and starter evidence | 2018–2025 | Parquet | Completed-game weekly evidence; not pregame starter truth |
| `injuries` | Injury and practice status | 2018–2025 | Parquet | `date_modified` preserved upstream; historical record-level availability is not assumed |

## Measured source evidence

Measurements below are for the complete 2018–2025 snapshots retrieved during the audit. `compressed bytes` means gzip-compressed Parquet for measurement only; duplicate gzip copies are not tracked.

| Source | Rows | Columns | Raw bytes | Gzip bytes | Schema fingerprint |
|---|---:|---:|---:|---:|---|
| schedules | 2,227 | 46 | 127,477 | 117,453 | recorded in manifest |
| team_stats_week | 4,454 | 133 | 441,382 | 411,412 | recorded in manifest |
| player_stats_week | 147,223 | 145 | 4,180,166 | 4,070,595 | recorded in manifest |
| rosters | 24,862 | 36 | 1,562,985 | 1,530,844 | recorded in manifest |
| depth_charts | 813,157 | 26 | 3,638,919 | 3,349,801 | recorded in manifest |
| snap_counts | 205,354 | 16 | 1,752,976 | 1,733,620 | recorded in manifest |
| injuries | 45,337 | 17 | 618,312 | 606,590 | recorded in manifest |
| **Total** | **1,262,612** | — | **12,322,217** | **11,820,315** | — |

Largest compressed source: depth charts at 3,349,801 bytes. No play-by-play archive is included in this task.

## Season-level measurements

The machine-readable manifests contain per-season row counts, byte sizes, checksums, and schema fingerprints for the source snapshots and normalized outputs. A single combined source snapshot is used per source to avoid duplicated raw files; the normalized output report is partitioned by source and retains season columns for exact season filtering.

## Schema and identifiers

- `schedules.game_id` is the canonical game key and is checked for duplicates.
- NFLverse `team`/team aliases are normalized through one mapping while source values remain available in raw snapshots.
- Player identifiers normalize `ID` prefixes and preserve nulls; player name alone is never treated as stable identity.
- Every manifest records ordered columns and a SHA-256 schema fingerprint.

## Schedule and venue fields

NFLverse schedules provide `gameday`, `gametime`, `location`, `roof`, `stadium_id`, and `stadium`. The normalized games table preserves all source fields needed to revisit timezone treatment. Because `gametime` is venue-local and no approved venue-timezone/DST mapping exists, `scheduled_start_utc` is null for every historical row. Exact UTC conversion is deferred; no timezone is invented or approximated. `game_end_utc` remains null because the audited source does not provide exact final-whistle timestamps.

## Legal / terms note

NFLverse is the first-party football-data source used here. Downstream use must follow the upstream repository’s current licensing, attribution, and terms requirements. No claim of NFL endorsement is made.

## Revisions and limitations

NFLverse datasets may be revised. A revised source must receive a new versioned path, retrieval timestamp, checksum, and derived frozen-data version. The current audit does not silently replace an existing frozen file.
