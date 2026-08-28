# Task05G Product Output Contract V1

## Final status

`TASK05G_FINAL_PRODUCT_CONTRACT_FROZEN_2020_2024__2025_NOT_RUN`

This contract is downstream of the frozen Task05G selectors and Task05F exact-offer evaluator. It does not change which wager is Hit Rate, Balanced, or Value. It defines how already-selected headline cards and default/game-detail/manual exact offers are presented and staked.

## Core separation

Keep these concepts separate:

1. **Selector/model confidence** — why a wager is featured.
2. **Exact-offer evaluation** — VALUE / PLAYABLE / LEAN / PASS / UNSUPPORTED for the current exact offer.
3. **Headline actionability/staking** — how an already-selected headline is staked and worded.
4. **Risk profile** — how units convert to dollars for the user's bankroll.

Do not let downstream staking re-select or re-rank HHR/Balanced/Value.

## Primary user-facing vocabulary

The primary recommendation verb is **`BET`**.

For default/game-detail/manual exact offers that do not currently qualify, use **`NO`**.

`NO` means the current exact offer fails. It is not a team/game judgment.

Do not use `PLAY` as the main recommendation verb. Do not show a selected headline card with a dead `0u` recommendation.

## Headline-card invariant

If the app promotes a wager into one of the three weekly headline cards, the published card must contain an actionable instruction.

- HHR selected headline: always `BET` with positive units.
- Balanced selected headline: always `BET` with positive units.
- Value selected headline: either a current `BET` with positive units or a nearby actionable `Value at ...` target with positive units. If neither is available inside the bounded rescue corridor, suppress the Value headline.

A published headline must never display `0u` / `$0` as its actionable recommendation.

## Hit Rate headline

Selector semantics remain frozen and separate from staking. HHR selection is not re-opened by this contract.

Once selected:

- every supported HHR headline is `BET`;
- `selector_trust` sets the base stake;
- break-even price pressure may only haircut stake after selection;
- price can never change which HHR candidate won the selector;
- current HHR can never become `NO`, `PASS`, or `0u` merely because the price is over-juiced;
- minimum HHR headline stake = `0.25u`;
- price pressure at or above `+8.0 percentage points` exposes **`HEAVILY_JUICED`**;
- HHR has no ordinary `Playable through` label;
- its secondary better-price language is **`Value at X or better`**, with units/stake recomputed when strict Value economics are reached.

Conceptual presentation:

```text
HHR
Chiefs ML -250
BET · 0.50u · $X
⚠ Heavily juiced   # only when +8pp pressure threshold is met
Value at -220 or better · 1.00u · $Y
```

## Balanced headline

Balanced remains the frozen probability-first / sensible-price lane. It is not a strict +EV selector.

Once selected:

- every supported Balanced headline is `BET`;
- preserve any larger canonical generic stake;
- minimum Balanced headline stake = `0.75u`;
- the reduced-price extension is **`Playable through ...`**;
- Playable Through is `0.50u` in the headline contract and remains visibly smaller than the primary recommendation;
- a different spread/total line must be an exactly reevaluated offer, never a synthetic line conversion.

Conceptual presentation:

```text
BALANCED
Bears +3 -110
BET · 0.75u · $X
Playable through +2.5 -115 · 0.50u · $Y
```

The selector may still return no Balanced card for a week. The must-BET rule applies only after a Balanced headline has actually been selected.

## Value headline

Value remains strict +EV only and uses the frozen validated ML/spread families and trust/safety state.

### Current-price Value

When canonical generic staking assigns positive units:

```text
VALUE
Bears ML +145
BET · 1.00u · $X
Value through +137 · 0.75u · $Y
```

`Value through` may be exposed only while the exact price remains genuinely strict +EV.

### Low-reliability target-only Value

A selected strict-Value row that would otherwise receive `0u` may still publish only when a realistic same-line better price creates an actionable target:

- required break-even improvement: at least `1.0pp`;
- maximum rescue distance: `1.5pp`;
- rescue stake: `0.50u`;
- same market/side/line only;
- no synthetic spread/total line conversion.

Presentation:

```text
VALUE
Bears ML +145
Value at +152 or better · 0.50u · $X
```

Do **not** render `BET $0` or an informational 0u headline.

If the first actionable better price requires more than `1.5pp` break-even improvement, suppress that Value headline. If a book later truly moves to a much better price, the next refresh evaluates that exact offer and the frozen Value selector may surface it naturally.

## Default rest-of-board / game-detail policy

All non-headline user-selected wager/game-detail recommendations use the **Balanced-style policy by default**.

Important distinction:

- the global Balanced headline selects the best Balanced play across the board;
- default game-detail evaluation assesses the exact wager the user clicked or entered and does not replace it with another global candidate.

Current exact offer qualifies:

```text
BET at -110 · 1.0u · $2.50
Playable through -118 · 0.5u · $1.00
```

Current exact offer does not qualify:

```text
NO at -125
BET at -110 or better · 0.5u · $1.00
```

`NO` is deliberately short and visually distinct from `BET`.

## Manual exact entries

Whatever exact offer the user types in is treated methodologically the same as a normal DK/FD sourced exact offer:

- same Task05F `evaluate_offer` path;
- same default Balanced policy;
- same canonical generic units;
- same risk-profile dollar conversion;
- same Playable Through / `BET at` target logic;
- exact line/side/market/price required;
- different spread/total line requires a genuinely new exact evaluation.

Preserve provenance truth (`source=manual` when applicable), but source metadata must not change probability, EV, reliability, support, units, or stake.

## Play Through V1

Play Through is a bounded execution range on a selected recommendation, not a second pool of extra bets and not another definition of Value.

Maximum headline corridor:

```text
1.5 percentage points of break-even probability
```

The actual Task05F concession may be smaller because reliability/uncertainty multipliers remain authoritative.

For spreads/totals, exact alternate lines must be reevaluated. Never infer that one point of line movement has a fixed probability cost.

## Risk profiles

| Profile | 1u bankroll fraction |
|---|---:|
| Cautious | 0.50% |
| Conservative | 0.75% |
| Normal | 1.00% |
| Aggressive | 1.25% |
| Ultra | 1.50% |

Ultra warning:

> Ultra is the highest staking exposure setting. It does not imply higher expected performance, better picks, greater model confidence, or any increase in predictive edge.

Risk profile changes dollars only. It cannot change selector choice, selector ranking, recommended units, probability, reliability, expected performance, or edge.

## Stake conversion and caps

```text
unit_dollars = bankroll × profile_unit_fraction
recommended_stake = unit_dollars × recommended_units
```

Then apply:

- floor to nearest `$0.50`;
- minimum dollar stake `$0.50`; below minimum becomes `$0` at execution level;
- per-wager cap `2.5%` bankroll;
- slate cap `10%` bankroll;
- identical exact offer shown in multiple headline lanes is one wager, not additive stakes;
- when duplicate headline lanes recommend different units, use the larger recommendation for the one actual wager.

Canonical unit conversion supports `0.25u` so the HHR floor can be represented. Generic/default/manual staking does not gain a new 0.25u recommendation tier merely from that conversion support.

Kelly staking is prohibited in V1.

## Frozen selector context retained

This product contract consumes the already-frozen selectors:

- HHR: `HALF_SHRINK`, q floor `.55`, odds `[-300,+200]`;
- Balanced: `MARKET_HALF_ONLY`, q floor `.52`, odds `[-220,+200]`;
- Value: strict validated +EV ML/spread families with causal trust and fail-closed safety valves;
- totals excluded from headline V1.

For ML probability lanes, market-half trust shrinks model q halfway toward the Pinnacle anchor only when q exceeds the anchor. For spreads, Spread Confidence V3 q passes through as selector trust. The current staking/product layer does not change those rules.

## Final 2020-24 canonical validation

Canonical replay after integration preserved selector identity:

- HHR: `81` selected;
- Balanced: `88` selected;
- Value: `68` selected.

Headline actionability:

- HHR current positive BET: `81 / 81`;
- Balanced current positive BET: `88 / 88`;
- Value current positive BET: `40 / 68`;
- Value target-only `Value at`: `28 / 68`;
- suppressed Value: `0` in exposed 2020-24 replay;
- published headline cards with zero actionable units: `0`.

Follow-every-current-recommended-headline, exact-offer deduped:

- `174` unique current wagers;
- `112-61-1`;
- `64.7%` non-push hit rate;
- `144.00u` risked;
- `+8.05u` weighted result on exposed development evidence.

Normal profile, continuous `$1,000` bankroll:

- ending bankroll `$1,075.59`;
- return `+7.56%`;
- maximum drawdown `8.69%`.

These are exposed 2020-24 development results, not promised forward performance.

## Scope / sealed boundary

**2025 WAS NOT OPENED, LOADED, SCORED, REPLAYED, OR RUN FOR TASK05G.**

2025 remains sealed at this freeze point. Any later 2025 acceptance/evaluation must be a separately authorized phase and must not be retroactively used to tune this frozen 2020-24 contract.
