# Task05G Default Board + Manual Exact-Offer Policy V1

## Status

`PRODUCT_CONTRACT_FREEZE_2020_2024__2025_NOT_RUN`

This contract fills the product gap outside the three weekly headline cards. It does not change the frozen HHR, Balanced, or Value selectors.

## Default policy outside the three headline cards

When a user opens a game and taps one exact market/side, the app does not run the whole-slate headline selector again. The user has already chosen the game and wager family.

The default recommendation philosophy is **Balanced**:

- use the frozen football/evaluator evidence for that exact wager;
- evaluate the exact line and price;
- apply the canonical unit/risk-profile staking layer;
- never manufacture action when the exact offer does not qualify.

This applies to:

- game-detail wagers;
- full-board market clicks;
- manual exact-offer entries.

## Frozen primary wording

The primary recommendation verb is always **BET**.

If the current exact offer qualifies:

```text
Bears ML +120
BET 0.75u · $2.00
```

If the current exact offer does not qualify:

```text
Bears ML -125
NO at -125
BET at -110 or better · 0.5u · $1.00
```

`NO` is a verdict on the **current exact offer**, not on the team/game itself.

Do not render `No bet` or `No recommended stake` as the main casual-facing action string in this default policy. The clean separation is:

- `BET` = current exact offer qualifies;
- `NO` = current exact offer does not qualify;
- `BET at X or better` = first same-line exact price where a positive recommendation qualifies.

## Playable Through wording

When the current exact Balanced/default offer already qualifies, show the reduced-stake extension separately:

```text
Bears +3 -110
BET 1.0u · $2.50
Playable through +2.5 -115 · 0.5u · $1.00
```

`BET` is the primary recommendation. `Playable through` is the extension. Do not use `Play` as the primary action verb.

For a different spread/total line, that alternate line must be evaluated as a genuinely new exact offer. The backend must not infer approval using a synthetic line conversion.

## Headline-specific price language

The three headline lanes intentionally use different secondary price semantics.

### Hit Rate

HHR is confidence/hit-rate first and does not use ordinary Playable Through language.

```text
Chiefs ML -250
BET [HHR units/stake]
Value at -220 or better · [Value units/stake]
```

The secondary threshold is **Value at**, and it must represent a genuinely strict positive-EV exact offer.

### Balanced

```text
Bears +3 -110
BET [Balanced units/stake]
Playable through [worse approved exact offer] · [reduced units/stake]
```

### Value

The Value headline is strict +EV by definition.

```text
Bears ML +145
BET [Value units/stake]
Value through +137 · [units/stake]
```

Any extension shown on the Value headline must itself remain strict positive EV. Do not display a negative-EV `Playable through` extension on the Value headline.

## Manual exact-offer entries

A user-entered wager is treated as a normal exact sportsbook offer for methodology purposes.

Example user input:

```text
Market: Bears ML
Price: +132
```

The backend normalizes the input into the same `NormalizedOffer` contract and sends it through the same frozen Task05F `evaluate_offer` path used for stored sportsbook offers.

The `source` field may retain `manual` for provenance/UI display, but **source must not change**:

- evaluator probability;
- EV;
- reliability/support;
- price status;
- recommended units;
- risk-profile dollar conversion;
- Playable Through threshold;
- `NO` / `BET at` target behavior.

Manual entries do **not** need to pretend to be literally DraftKings or FanDuel in metadata. They are treated **methodologically as equivalent exact offers**. This avoids lying about provenance while guaranteeing identical decision logic.

The frozen evaluator already supports this contract: `NormalizedOffer.source` is metadata and `evaluate_offer` accepts stored or manual exact offers using the same market/model state.

## Same-line target behavior

For a supported exact offer whose current price is too expensive, the frozen Play Through boundary can identify the first same-line price inside the Balanced actionability corridor.

Before exposing a stake, that boundary price must be passed back through the exact evaluator path.

Therefore:

```text
NO at -125
BET at -110 or better · 0.5u · $1.00
```

means that `-110` was verified as an exact same-line offer that receives positive units under the frozen policy.

## Different-line behavior

For spreads/totals:

```text
+3 -110
```

and

```text
+2.5 -115
```

are different exact offers.

If the product wants to show `Playable through +2.5 -115`, the `+2.5 -115` offer must be evaluated directly. No fixed point-to-probability conversion can approve it.

## 2025

2025 is not opened, loaded, or run by this contract. It remains outside Task05G completion by explicit project direction.
