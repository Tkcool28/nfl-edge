# Task05F Product Selector Contract V1

Status: PRODUCT CONTRACT — SELECTOR FORMULAS NOT YET PREREGISTERED

This document locks the intended app behavior above the frozen Task05F evaluator. It does not change any football model, evaluator probability, value label, stake formula, or historical acceptance result.

## Top-of-app primary cards

The app surfaces exactly three primary selector cards for the whole current slate:

1. **High Hit Rate** — one wager, from any market type, representing the strongest supported candidate for conservative probability of winning.
2. **Balanced** — one wager, from any market type, representing the strongest supported combination of win probability, expected value, reliability, and uncertainty under a separately preregistered selector utility.
3. **Value** — one wager, from any market type, representing the strongest credible strict positive-EV candidate. `VALUE` remains mathematically defined by `expected_value > 0`; no selector may relabel negative EV as Value.

The three cards are global slate selectors, not market-specific lists. Moneyline, spread, and total candidates compete in the same selector pools subject to support/reliability rules.

A selector may return no qualifying candidate when its hard requirements are not met. The product must not fabricate a play merely to fill a card.

Selector diversification is not a hard requirement. The same wager may mathematically rank first for more than one card. Any future UI diversification rule must be separately defined and may not materially downgrade the recommendation merely to force different wagers.

## Game-by-game explorer

Below the three primary cards, the app presents each game with wager boxes for:

- spread
- total
- moneyline

The board displays DraftKings and FanDuel actionable offers with Pinnacle beside them as the benchmark.

Clicking a wager box exposes the evaluator/staking detail when available, including at minimum:

- frozen football model output / model view
- calibrated fair-value probability
- `p_win`, `p_push`, `p_loss` where applicable
- current sportsbook line and price
- Pinnacle benchmark line/price/probability where applicable
- break-even probability
- fair price
- strict expected value
- Play Through number/status once locked
- reliability
- uncertainty
- staking probability / stake recommendation once locked
- status: `VALUE`, `PLAYABLE`, `LEAN`, or `PASS`

The explorer remains honest for every supported/unsupported option. `PASS` and unsupported outputs are valid product results.

## Sleeper Watch

Sleeper Watch is a secondary product surface, not a fourth primary selector card.

Its purpose is to track a supported longer-price or underdog-style wager where the frozen football signal materially likes the opportunity relative to the market, but the current actionable price has not yet satisfied the future Sleeper selector/actionability contract.

State behavior across the twice-daily market refresh:

- `WATCH`: candidate is interesting enough to monitor, but the current actionable price does not satisfy the locked Sleeper activation requirement.
- `ACTIVE`: on a refresh, an actionable DK/FD number satisfies the locked Sleeper selector/price requirement. The UI may highlight/glow the Sleeper Watch item.
- If the favorable number disappears on a later refresh, the item returns from `ACTIVE` to `WATCH` rather than remaining permanently promoted.
- If the underlying football/evaluator support disappears or becomes `PASS`, the item may leave Sleeper Watch entirely.

Sleeper Watch must never mean "highest odds" or "forced long shot." It must remain supported by evaluator evidence and a separately preregistered selector rule.

No Sleeper threshold, odds range, disagreement bucket, or historical ROI rule is defined in this document. Those formulas must be preregistered before historical selector scoring.

## Layer separation

The intended stack is:

```text
Frozen football models
    ↓
Locked Task05F fair-value evaluator
    ↓
Play Through / reliability / uncertainty
    ↓
Staking probability and stake policy
    ↓
Global slate selectors
    ├── High Hit Rate (one play)
    ├── Balanced (one play)
    ├── Value (one play)
    └── Sleeper Watch (secondary dynamic state)
    ↓
App presentation + twice-daily refresh
```

The selector layer consumes evaluator outputs; it may not change the evaluator in order to obtain attractive selector results.

## Integrity

- 2025 remains sealed during Task05F development.
- No selector formula may be chosen by retrospective price/ROI/disagreement bucket hunting.
- Play Through never changes the strict `VALUE` definition.
- Sleeper Watch activation/deactivation is driven by current market refresh state, not by preserving a previously favorable stale price.
- The independent second reviewer should be able to inspect evaluator evidence and selector contracts separately.
