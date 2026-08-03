# Data Contract

## Purpose

Define the historical and live inputs that NFL Edge may consume and the evidence required to reproduce them.

## Data classes

### Raw source archive

A source file obtained without project transformation. Large raw archives may be GitHub Release assets.

Required manifest fields:

```text
source_id
source_name
source_locator
retrieved_at_utc
seasons
file_name
compression
byte_size
sha256
row_count
schema_fingerprint
license_or_terms_note
```

### Frozen normalized table

A compact, immutable table derived from one or more raw sources and committed to the repository when practical.

Required metadata:

```text
data_version
source_manifest_ids
transform_version
created_at_utc
row_count
column_count
sha256
min_event_time_utc
max_event_time_utc
```

### Deterministic fixture

A tiny hand-auditable dataset used by contract, leakage, and integration tests. Fixtures may not be silently regenerated from a changing network source.

### Live snapshot

A timestamped current schedule, QB-status, or odds response used for one scoring run.

Required identity:

```text
snapshot_id
observed_at_utc
source
request_parameters_without_secrets
row_or_event_count
sha256
```

## Canonical compact tables

### `games`

Minimum fields:

```text
game_id
season
season_type
week
scheduled_start_utc
game_end_utc
home_team
away_team
home_score
away_score
neutral_site
venue_id
roof_type
source_game_id
observed_at_utc
```

### `team_game_stats`

One row per team-game with offense and defense values attributable only to that completed game.

Minimum identity:

```text
game_id
team
opponent
is_home
game_end_utc
observed_at_utc
```

### `qb_game_stats`

One row per quarterback-game with stable player identifier, dropback volume, and approved QB performance components.

### `depth_chart_snapshots`

Timestamped team/player/position/depth information. Records without a reliable observation timestamp may not be used to simulate a more precise historical decision time than the data supports.

### `starter_overrides`

Manual, timestamped, sourced corrections. Required fields:

```text
game_id
team
expected_starter_id
observed_at_utc
source
operator_note
```

## Identifier policy

- Use stable source identifiers when available.
- Preserve source IDs alongside canonical IDs.
- Team aliases must be normalized through one reviewed mapping.
- Player-name text alone is not a stable identifier.
- Duplicate canonical game IDs are fatal.

## Time policy

All timestamps are stored in UTC with timezone information.

A feature source record is eligible only when:

```text
observed_at_utc <= prediction_as_of_utc
```

Completed-game data is eligible only when:

```text
game_end_utc < prediction_as_of_utc
```

When a source provides only a date or weekly batch timestamp, the project must use the most conservative defensible availability time and document the assumption.

## Missingness policy

- Missing values remain explicit.
- Imputation rules live in the feature contract and configuration.
- Unknown starter status may not be silently converted to a confirmed starter.
- Missing source coverage must appear in the data-gap report.
- A row may not be dropped merely because its outcome is inconvenient.

## Frozen-data acceptance

A frozen baseline is accepted only when:

1. Every file has a manifest and checksum.
2. Row counts and season coverage are reported.
3. Duplicate and key-integrity checks pass.
4. Timestamp coverage is measured.
5. Missingness is summarized by column and season.
6. Known source revisions are documented.
7. The transformation can be reproduced from its declared inputs.
8. A compact fixture exercises every critical path.

## Repository size decision

Before adding large raw archives:

1. Download in a disposable environment.
2. Compress per season.
3. Measure each file and the full set.
4. Record checksums.
5. Commit directly only when ordinary Git history remains practical.
6. Otherwise publish as a GitHub Release asset and commit the manifest plus retrieval script.

## Prohibited behavior

- Downloading a changing source during a supposedly reproducible backtest without recording it
- Overwriting a frozen file under the same version
- Using a revised historical file without updating the manifest
- Treating final game data as available before game completion
- Treating un-timestamped modern depth-chart knowledge as historical point-in-time truth
- Storing API keys in snapshots or request metadata
