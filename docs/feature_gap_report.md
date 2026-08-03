# Feature Gap Report v1

## Honest boundary

The pipeline can prove leakage-safe weekly feature rows from the frozen evidence. It cannot prove exact game-level historical decision timestamps or universally known historical starting quarterbacks.

## Timing gaps

- `scheduled_start_utc`: intentionally null for all 2,227 games; venue timezone/DST mapping was not audited.
- `game_end_utc`: intentionally null; final whistle is not inferred.
- historical `observed_at_utc`: intentionally null; artifact-generation time is not substituted.
- Consequence: team/QB results become available only at conservative Tuesday 12:00 UTC weekly boundaries.
- `rest_days`: exact elapsed-day rest is unsupported. v1 emits an explicit week-gap/bye proxy with null first-game values.

## Team-stat limitations

The compact normalized table supports totals for passing/rushing EPA and yards, but not play counts. Therefore v1 does not falsely label EPA totals as EPA per play and does not implement success rate, explosive-play rate, or early-down EPA. Those require a separately frozen point-in-time play-by-play source in a future data task.

Defensive EPA allowed is derived from the completed opponent's offensive passing+rushing EPA for the same past game. No opponent-adjusted model or Massey fit occurs in this phase.

## Starter reconstruction limitations

Frozen 2018–2024 depth rows have incomplete normalized identity/rank/timestamp semantics; the later timestamped depth rows are not historical 2018–2025 weekly proof. Frozen rosters are batch-level, not exact pre-cutoff evidence. Schedule QB identifiers are postgame-like source fields and are deliberately not promoted to pregame certainty.

Production output therefore preserves conservative states:

- `POSTGAME_ONLY_EVIDENCE`: 2226 games in the current baseline build.
- `UNKNOWN`: 1 game in the current baseline build.

Manual starter overrides are also rejected when they lack a timezone-aware `observed_at_utc`. An override with a missing column, null value, or naive timestamp raises a `ValueError`. Only overrides with a valid UTC timestamp before the per-week cutoff are eligible to promote a side to `CONFIRMED_PRE_CUTOFF`.

No production game is falsely labeled confirmed. Scenario candidate IDs remain null when only postgame evidence exists. The fixture suite separately proves timestamped depth, ambiguity, roster-supported, missing-ID, and conflicting-record paths.

## QB-feature limitation

Because historical starter candidates are mostly unknown, production QB scenario rows are fixed-prior/zero-sample audit rows. Prior-QB aggregation code is implemented and poison-tested, but meaningful historical starter-specific QB values require a better timestamped expected-starter source. This is a data gap, not an invitation to backfill actual starters.

## 2025 isolation

2025 rows are built using the same fixed configuration and code as earlier seasons. Outcomes are retained only as target labels. Feature windows, priors, registry, and missingness behavior do not depend on 2025 model performance or outcomes.

## Remaining work boundary

The recommended next task is the separately authorized base-model and walk-forward engine only after this PR's contract evidence is reviewed. It should consume these source fields without modifying feature definitions based on the untouched 2025 result.
