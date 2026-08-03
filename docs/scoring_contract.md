# Live Scoring Contract

## Purpose

Define the trusted twice-daily process that converts current football information and an approved model artifact into public predictions and betting-value candidates.

## Schedule

Target refreshes:

- 12:00 PM Eastern
- 11:58 PM Eastern

The scheduler must be timezone-aware. Every run records actual start time, odds observation time, and publication time in UTC.

## Required inputs

- Approved model artifact and metadata
- Matching feature configuration
- Current NFL schedule
- Latest eligible completed-game data
- Current point-in-time team/QB inputs
- Expected starter resolution
- Current DraftKings, FanDuel, and Pinnacle moneyline prices

No scoring run may silently substitute a different model, feature version, or incomplete dataset.

## Execution order

1. Validate configuration and artifact checksums.
2. Load current schedule.
3. Resolve expected starters and uncertainty.
4. Build point-in-time football features.
5. Produce independent model probabilities.
6. Fetch and preserve the current odds snapshot.
7. Normalize book/team/game identities.
8. Calculate implied probabilities and expected value.
9. Apply eligibility and suppression rules.
10. Write the forward prediction ledger.
11. Generate validated public JSON.
12. Publish only after all validation passes.

## Market boundary

Odds are introduced only after model probability generation.

Allowed uses:

- Expected-value calculation
- Best actionable price
- Pick eligibility
- Display and Pinnacle comparison

Prohibited uses:

- Model features
- Model calibration
- Runtime probability adjustment
- Model selection

## Expected value

```text
EV = p_model * (decimal_odds - 1) - (1 - p_model)
```

The exact book price used must be retained with its observation timestamp.

## High-hit-rate selection

Choose the eligible side with the highest model win probability, subject to:

- Actionable DraftKings or FanDuel price
- Positive EV
- Minimum configured model probability
- Acceptable starter certainty
- Game not started
- Complete and valid source data

## Best-EV selection

Choose the eligible side with the highest EV, subject to:

- Minimum configured model probability
- Minimum configured EV/edge
- Maximum configured price/risk boundary
- Acceptable starter certainty
- Game not started
- Complete and valid source data

## No-play behavior

When no side qualifies, publish an explicit no-play state. Do not reduce thresholds automatically to fill a card.

## QB uncertainty

When starter uncertainty is material:

- Produce approved QB1 and QB2 scenario probabilities
- Mark `qb_status` as uncertain
- Publish the scenario range
- Suppress official pick eligibility when the configured materiality threshold is exceeded

## Failure behavior

A run must not overwrite the last known good public bundle when:

- Artifact checksum fails
- Required data is missing
- Odds response is malformed
- Game identity cannot be reconciled
- Probability or schema validation fails
- Publication validation fails

The failed run writes a private diagnostic report without secrets.

## Forward ledger

Each scored side records:

```text
run_id
game_id
as_of_utc
scheduled_start_utc
team
opponent
model_probability
qb_status
model_version
data_version
feature_version
book
american_odds
decimal_odds
odds_observed_at_utc
expected_value
eligibility_status
reason_codes
surfaced_pick_type
```

## Required tests

- Odds added only after model prediction
- American/decimal conversion
- EV calculation
- Best-price selection
- High-hit-rate and best-EV selection
- No-play state
- Started-game suppression
- QB-uncertainty suppression
- Malformed odds failure
- Artifact mismatch failure
- Last-known-good preservation
- Deterministic public output ordering
