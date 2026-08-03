# Data Gap Report — Frozen Baseline v1

## Verdict boundary

The official audited sources support an honest compact historical baseline. They do **not** prove exact record-level availability for every historical decision timestamp. The next feature task must use the conservative rules below rather than inventing precision.

## Kickoff and completion timestamps

- Schedules contain `gameday` and `gametime`, plus venue and roof fields.
- The source does not provide a native timezone-aware `scheduled_start_utc` or exact `game_end_utc`.
- The normalized games table preserves `gameday`, `gametime`, venue fields, and the timestamp derivation classification.
- Exact `game_end_utc` is intentionally null.
- Do not infer final whistle from kickoff plus assumed game duration.

Recommended next-task rule:

```text
completed-game availability = only after the audited weekly source publication boundary
```

For a point-in-time feature builder, use a documented weekly batch boundary after the relevant completed week and before the next prediction boundary. If a precise publication timestamp is needed, it must come from an independently audited first-party release artifact; do not derive it from row values.

## Depth charts

NFLverse depth charts contain a source `dt` field and player/position/depth columns. The field is preserved as `source_dt`. The audit classifies it as `batch_or_source_defined`; it is not automatically treated as proof that the record was available at a specific historical hour.

Consequences:

- A depth-chart row may support a conservative weekly snapshot.
- It may not silently establish a precise pregame expected starter timestamp.
- The next task should select the latest conservative source snapshot before its documented weekly cutoff.
- If no defensible pre-cutoff snapshot exists, starter certainty must remain unknown.

## Starting-quarterback reconstruction

Schedules expose QB IDs/names for many games and weekly player statistics expose stable player IDs for game participation. Depth charts and snap counts provide supporting evidence. However:

- A schedule QB field is not itself proof of when the information became available.
- Weekly player statistics are postgame evidence, not pregame starter evidence.
- Snap counts confirm participation after the game, not what was known before kickoff.
- Depth-chart `dt` semantics require conservative batch treatment.

Therefore 2018–2024 starting-QB reconstruction is defensible only as an explicitly classified certainty state, not as universally precise historical news timing. Unknown or conflicting cases must remain unknown or be reported as gaps.

## Injury/status coverage

Injury records include `date_modified`, report statuses, and practice statuses. The audit preserves this source field but does not assume that historical `date_modified` equals public availability time for every record. The source’s historical publication process is not sufficient to claim exact record-level as-of semantics without additional first-party evidence.

Post-2024 coverage and semantics should be treated as especially provisional and audited again before live use.

## Stable identifiers

- Stable game identifiers are available through `game_id`.
- Stable player IDs are available for many weekly player-stat rows and roster/depth rows, but coverage is not universal.
- Name-only joins are prohibited.
- Null player identifiers remain explicit.

## Venue, roof, and neutral site

Schedules provide venue IDs/names, roof, and a location field. The normalized venues table preserves these values. The source does not provide a complete independently normalized venue timezone table in the audited files. Timezone conversion must therefore remain conservative and documented rather than guessed from stadium names.

Neutral-site classification should be reviewed from the schedule location field and retained as source evidence; it must not be silently inferred from team geography.

## Season recommendations

### Development start

2018 remains a defensible *candidate* development start for compact game, team, QB, roster, and source-coverage research, provided the next task uses weekly conservative availability boundaries and explicit missingness. It should not claim uniformly precise hourly starter or injury knowledge.

### 2025 holdout

2025 may remain an untouched holdout for coverage auditing and later evaluation. This task does not use 2025 outcomes for feature choices, tuning, or model decisions. Any missingness or timestamp weakness discovered in 2025 must be reported, not repaired using outcomes.

## Storage decision

Measured complete raw Parquet snapshots total approximately 12.3 MB; gzip measurement total approximately 11.8 MB; the largest compressed source is approximately 3.35 MB. Ordinary Git is reasonable under the explicit task authorization and below the 25 MiB raw-source threshold. Track one Parquet copy per source, with manifests and checksums; do not track duplicate gzip copies or play-by-play archives.

Compact normalized tables are substantially smaller and should remain ordinary Git data. If future source growth exceeds policy, move only the raw snapshots to a versioned GitHub Release asset while retaining manifests and deterministic retrieval code in Git.

## Consequences for the next task

- Build features from completed-game weekly boundaries, not fabricated final-whistle times.
- Keep `source_dt`, `date_modified`, original kickoff fields, timestamp-quality labels, and missingness indicators.
- Do not treat postgame stats or snap counts as pregame information.
- Add leakage tests for the conservative boundary and explicit unknown starter cases.
