# Publication Contract

## Purpose

Define the stable, sanitized boundary between trusted scoring code and the final static JavaScript website.

## Public artifact

The canonical current file is:

```text
site/public/data/latest.json
```

Historical versioned files may also be written under:

```text
site/public/data/runs/<run_id>.json
```

The public artifact contains no secrets, raw provider credentials, private deployment details, or unrestricted source payloads.

## Top-level schema

Required fields:

```text
schema_version
generated_at_utc
run_id
as_of_utc
schedule_observed_at_utc
odds_observed_at_utc
data_version
feature_version
model_version
model_status
games
high_hit_rate_pick
best_ev_pick
warnings
```

## Game schema

Required fields:

```text
game_id
scheduled_start_utc
season
week
away_team
home_team
expected_away_qb
expected_home_qb
qb_status
qb_scenarios
away_win_probability
home_win_probability
book_prices
best_actionable_price
expected_value_by_side
eligibility_by_side
reason_codes
model_explanation
```

## Pick schema

Each hero-card selection is either `null` with a no-play reason or an object containing:

```text
pick_type
game_id
team
opponent
model_probability
book
american_odds
decimal_odds
expected_value
qb_status
reason_codes
```

## Validation

Before publication:

- JSON parses successfully.
- Schema version is supported.
- Required fields are present.
- Probabilities are finite and in `[0, 1]`.
- Opposing win probabilities are consistent within tolerance.
- Prices are valid.
- Timestamps are timezone-aware UTC values.
- Games are unique and deterministically ordered.
- No game already started is eligible.
- Referenced model/data/feature versions match the scoring run.
- No secret-pattern or API-key field is present.

## Atomic publication

The workflow must create and validate a staged bundle before replacing the current public bundle.

A failed staged build leaves the last known good `latest.json` and static site untouched.

## Browser responsibility

The browser may:

- Render public data
- Sort/filter games
- Expand details
- Compare book prices
- Accept manual odds
- Recalculate implied probability and EV locally
- Save user-only display preferences in browser storage

The browser may not:

- Hold an Odds API key
- Fetch secret-bearing provider endpoints
- Modify the authoritative prediction ledger
- Present manual odds as official captured prices
- Change the model probability

## Backward compatibility

Schema-breaking changes require a new `schema_version` and coordinated site update.

The site should show a clear unavailable/incompatible state rather than guessing when it receives an unknown schema.

## Minimal technical viewer

Before final UI design, a plain technical viewer may display timestamps, versions, game probabilities, prices, eligibility, and warnings. It must not establish final branding or visual design.
