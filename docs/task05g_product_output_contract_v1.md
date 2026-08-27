# Task05G Product Output Contract V1

## Status

`BACKEND_PRODUCT_CONTRACT_FROZEN_FOR_2020_2024__2025_NOT_RUN`

This contract is downstream of the frozen Task05G selector implementation. It does not change which wager is Hit Rate, Balanced, or Value. It defines how an exact evaluated offer becomes an actionable or informational user-facing backend payload.

## Core separation

The backend must preserve three separate concepts:

1. **Selector/model confidence** — why a wager was featured.
2. **Exact-offer market evaluation** — whether the user's current price is `VALUE`, `PLAYABLE`, `LEAN`, `PASS`, or `UNSUPPORTED`.
3. **Staking/risk profile** — how many units the exact offer deserves and how those units convert to dollars for the user's bankroll.

Do not collapse these concepts into one opaque score.

## Product actions

### `BET_VALUE`

Use only when:

- exact-offer status is `VALUE`;
- strict evaluated EV is positive;
- frozen staking policy assigns positive recommended units.

The user may see the selected wager, exact book/line/price, model confidence, evaluator probability/EV, reliability, recommended units, and one dollar stake.

### `BET_PLAYABLE`

Use only when:

- the exact offer is supported;
- it is not strict positive-EV Value;
- it remains inside the frozen Play Through corridor after the Task05F reliability/uncertainty confidence multiplier;
- frozen staking policy assigns positive recommended units.

`PLAYABLE` must never be rendered, counted, or described as `VALUE`.

Recommended units are deliberately smaller:

- `0.5u` default;
- `0.75u` only for HIGH reliability with actionable probability at least 0.55;
- never above `0.75u`.

### `INFORMATIONAL_NO_STAKE`

Use when a supported selector/evaluator signal exists but frozen staking policy assigns `0u` for a non-price reason. The important V1 example is a supported `VALUE` signal with LOW reliability.

The card must **not** say `BET_VALUE` while simultaneously showing `$0` stake.

Suggested future UI meaning:

> Value signal — informational only. Reliability is too low for a recommended stake.

The exact frontend copy is not frozen here; the backend action and reason code are.

### `NO_RECOMMENDED_STAKE_AT_CURRENT_PRICE`

Use for supported `LEAN`/`PASS` states when the featured football/model candidate is still useful but the exact current offer is outside the actionable corridor.

The app may still show:

- the selected candidate;
- current exact price;
- model confidence;
- target/play-through information when deterministically available;
- `0u` and `$0` recommended stake.

This avoids hiding the football recommendation while also avoiding fabricated action.

### `UNSUPPORTED`

Fail closed. Play Through cannot rescue an unsupported evaluator region.

## Play Through V1

Play Through is a bounded actionability concession, not another Value definition.

Frozen maximum:

```text
1.5 percentage points of break-even probability
```

The actual concession is:

```text
maximum_concession × frozen Task05F reliability/uncertainty confidence multiplier
```

Therefore users should conceptually be told **"up to 1.5 percentage points"**, not that every wager automatically receives the full 1.5pp corridor.

The exact offer must be reevaluated through the same evaluator path. Stored-board and manual exact offers with the same line/price must classify identically.

For spreads and totals, a different line must be evaluated as a genuinely different exact offer. Do not assume that one point of line movement has a fixed probability cost and do not approve an alternate line using a synthetic price conversion.

`play_through_price_american` is a price boundary for the evaluated market/line context. It is not permission to synthetically convert a different spread/total line into an approved offer.

## Required backend fields

Each user wager view should expose at least:

- `lane`
- `candidate_id`
- `offer_id` when production normalization supplies one
- `game_id`
- `market_type`
- `selection`
- `sportsbook`
- `line`
- `american_odds`
- `price_status`
- `strict_value`
- `playable`
- `action`
- `action_reason`
- `model_confidence_probability`
- `actionable_probability`
- `break_even_probability`
- `expected_value`
- `reliability`
- `recommended_units`
- `risk_profile`
- `unit_bankroll_pct`
- `bankroll`
- `unit_dollars`
- `recommended_stake`
- `play_through_break_even_concession`
- `play_through_break_even_probability`
- `play_through_price_american`
- `risk_profile_caution`

### Probability labels

The frontend must not present `model_confidence_probability` and `actionable_probability` as if they were the same number.

- `model_confidence_probability` is selector/model evidence.
- `actionable_probability` is the evaluator probability used in exact-offer economics/actionability.

A future UI can simplify the language, but the data contract must preserve both.

## Risk profiles

Frozen order and unit bankroll fractions:

| Profile | 1u bankroll fraction |
|---|---:|
| Cautious | 0.50% |
| Conservative | 0.75% |
| Normal | 1.00% |
| Aggressive | 1.25% |
| Ultra | 1.50% |

Ultra warning:

> Ultra is the highest staking exposure setting. It does not imply higher expected performance, better picks, greater model confidence, or any increase in predictive edge.

A profile changes **dollar exposure only**. It cannot change:

- featured candidate;
- price status;
- model/evaluator probability;
- expected value;
- reliability;
- recommended units.

## Stake conversion

```text
unit_dollars = bankroll × profile_unit_fraction
recommended_stake = unit_dollars × recommended_units
```

Then apply:

- floor to nearest `$0.50`;
- minimum stake `$0.50`; below minimum becomes `$0`;
- per-wager cap `2.5%` of bankroll;
- slate cap `10%` of bankroll;
- identical exact offer shown in multiple headline lanes is one wager, not multiple stakes.

Kelly staking is prohibited in final V1.

## Example payload behavior at $250 / Normal

### Strict Value

Historical example:

- Hit Rate
- New Orleans moneyline, DraftKings `-233`
- price status `VALUE`
- model confidence approximately `74.98%`
- evaluator/actionable probability approximately `72.40%`
- recommended units `1.0u`
- Normal 1u = `$2.50`
- recommended stake `$2.50`
- action `BET_VALUE`

### Playable

Historical example:

- Hit Rate
- Minnesota moneyline, DraftKings `-166`
- price status `PLAYABLE`
- model confidence approximately `72.39%`
- evaluator/actionable probability approximately `61.61%`
- break-even approximately `62.41%`
- exact-offer EV approximately `-0.79%`
- frozen realized Play Through concession approximately `0.681pp`
- price boundary `-167`
- recommended units `0.5u`
- Normal recommended stake `$1.00` after floor rounding
- action `BET_PLAYABLE`

This demonstrates why Play Through must be visually distinct from Value: the football signal can be strong while the exact price is slightly worse than strict fair value.

### Informational low-reliability Value signal

Historical example:

- Hit Rate
- Jacksonville spread `+13.5 -106`, FanDuel
- exact-offer status `VALUE`
- reliability `LOW`
- recommended units `0u`
- recommended stake `$0`
- action `INFORMATIONAL_NO_STAKE`
- reason `RELIABILITY_INFORMATIONAL_ONLY`

The backend must preserve the distinction between **strict price value** and **permission to risk bankroll**.

## Scope boundary

This is a backend/data contract. Final visual design, account persistence/authentication, and polished settings UX remain later work.

2025 was not opened or run for this contract and remains outside this Task05G completion work by explicit project direction.
