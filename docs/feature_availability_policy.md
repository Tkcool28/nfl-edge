# Feature Availability Policy v1

## Purpose

Historical NFL Edge sources intentionally do not claim exact `scheduled_start_utc`, `game_end_utc`, or record-level `observed_at_utc`. Feature v1 therefore uses a deterministic conservative weekly model instead of fabricating precision.

## Configured rule

`config/features.yaml` defines an explicit UTC publication boundary:

```text
Tuesday 12:00 UTC
rule: WEEK_COMPLETE_TUESDAY_1200_UTC_V1
```

For every `(season, season_type, week)`:

1. Read the earliest and latest source `gameday` values in that week.
2. Set `prediction_as_of_utc` to the configured boundary **strictly before** the first game date.
3. Set `week_completed_at_boundary_utc` and `eligible_for_features_at_utc` to the configured boundary **strictly after** the last game date.
4. A source row is eligible when `source_available_at_utc <= prediction_as_of_utc`.
5. Current-game and later rows remain excluded even if a source is malformed.

A boundary on a Tuesday game date is not accepted as postgame availability; the row waits until the following Tuesday. This handles rescheduled Tuesday games conservatively. Monday-night games publish the following day at noon. Thursday/Saturday/Sunday games in the same NFL week wait until the last dated game in that week has passed. Postseason labels (`WC`, `DIV`, `CON`, `SB`) use the same algorithm and are explicitly tagged `POSTSEASON`.

`week_completed_at_boundary_utc` is an eligibility-boundary label. It is **not** an asserted exact completion timestamp.

## Time guarantees

- UTC only; local machine timezone is never consulted.
- No current date or wall clock in eligibility calculations.
- No filesystem mtime.
- No source-manifest retrieval time.
- No derived-artifact `created_at_utc`.
- `created_at_utc` exists only in `feature_manifest_v1.json`.

## Prediction-time limitation

Because the approved baseline lacks exact historical kickoff UTC, `prediction_as_of_utc` is a week-level research cutoff rather than an exact game kickoff cutoff. `scheduled_start_utc` remains null in model-ready output. Exact live kickoff timing must be introduced only from a separately audited timezone-aware source.

## Starter evidence

- Timestamped pre-cutoff overrides may be `CONFIRMED_PRE_CUTOFF`.
- Timestamped, unambiguous depth evidence may be `DEPTH_CHART_SUPPORTED`.
- Roster-only evidence is accepted only in explicit deterministic fixtures marked `PRE_CUTOFF_FIXTURE_EVIDENCE`; production frozen roster batch times are not precise enough.
- Weekly player stats and snap counts are retained only as `POSTGAME_ONLY_EVIDENCE`; they never populate expected candidates or raise pregame certainty.
- Conflicts remain `AMBIGUOUS`; absent evidence remains `UNKNOWN`.
