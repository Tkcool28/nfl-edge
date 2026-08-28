# Task05G 2020–2024 Product Simulation V1 — Review

## Verdict

`TASK05G_DOWNSTREAM_PRODUCT_POLICY_VALIDATED_ON_EXPOSED_2020_2024_WITH_PLAY_THROUGH_NARROW_AND_DISTINCT_FROM_VALUE__2025_NOT_RUN`

This report is development/product evidence only. 2020–2024 has been repeatedly inspected during Task05G. Outcome metrics below must not be represented as untouched forward expectations.

2025 was **not loaded, opened, scored, or run**. The workflow hard-failed on any 2025 development input.

## Validated workflow

Initial deterministic product run after the report-writer identity defect was corrected:

- workflow: `33085193913`
- result: SUCCESS
- artifact: `9651869547`
- artifact digest: `sha256:17ac9c37a8ef052f5351404dbfe97b2ff4fe7b7f81ffad8710e2d919235236d8`

Current presentation-contract revalidation:

- workflow: `33085764534`
- result: SUCCESS
- artifact: `9652098427`
- artifact digest: `sha256:79b08dcd09687d306bbdc77510e52c2d9c013b946ca6f6b03230637a1f7691be`
- product simulation replayed twice byte-identically
- staking/profile tests PASS
- frozen selector tests PASS
- frozen Task05F Play Through/evaluator tests PASS
- Task05F board reproduction PASS
- Model Confidence V2 reproduction PASS
- Spread Confidence V3 reproduction PASS
- product invariants PASS
- 2025 firewall PASS

The first attempted simulation failed only after computation while writing a CSV because the V3 historical table derives candidate identity rather than storing a `candidate_id` column. The report runner was corrected to materialize the deterministic derived identity before writing evidence. No policy/outcome threshold changed.

## 1. What Play Through is — and is not

Play Through remains a distinct exact-offer state:

- `VALUE` = strict evaluated EV > 0;
- `PLAYABLE` = supported exact offer just outside strict +EV but within the frozen bounded concession;
- `LEAN`/`PASS` = no recommended stake at the exact current offer;
- `UNSUPPORTED` = fail closed.

The maximum corridor is 1.5 percentage points of break-even probability, but Task05F applies the frozen reliability/uncertainty confidence multiplier. Therefore the actual permitted concession is usually materially smaller than 1.5pp.

Play Through does not change the HHR/Balanced/Value selector winner and never turns `PLAYABLE` into `VALUE`.

## 2. Full exact-offer board effect

Across 109 season-week blocks and 8,448 deterministically shopped exact offers:

| Exact-offer status | Count | Share |
|---|---:|---:|
| VALUE | 1,686 | 19.96% |
| PLAYABLE | 384 | 4.55% |
| LEAN | 5,222 | 61.81% |
| PASS | 854 | 10.11% |
| UNSUPPORTED | 302 | 3.57% |

Availability by week/block:

- at least one broad-board `VALUE`: 98/109 blocks (89.91%);
- at least one `PLAYABLE`: 74/109 (67.89%);
- at least one `VALUE` or `PLAYABLE`: 99/109 (90.83%);
- `PLAYABLE` present with no broad-board `VALUE` anywhere: only 1/109 blocks (0.92%).

Therefore Play Through is **not primarily a mechanism for manufacturing action in otherwise empty weeks**. Its main product value is price tolerance on a selected/full-board/manual wager when the exact offer is slightly worse than strict Value.

### Broad PLAYABLE outcomes — descriptive warning

All 384 broad-board PLAYABLE offers:

- 173 wins / 208 losses / 3 pushes;
- 45.41% non-push hit rate;
- -44.56 flat units;
- -11.60% flat ROI.

By market:

| Market | Plays | W-L-P | Flat ROI |
|---|---:|---:|---:|
| Moneyline | 125 | 60-65-0 | -3.83% |
| Spread | 192 | 87-103-2 | -12.23% |
| Total | 67 | 26-40-1 | -24.32% |

This is a critical product guardrail: **the app must never imply that every PLAYABLE board row is a recommended bet.** Play Through is an actionability boundary applied to a supported offer; recommendation selection and staking remain separate layers. Totals are not headline eligible in the frozen selector V1.

The broad `VALUE` status population is also not the final Value selector family; broad Task05F Value status alone must not be confused with the frozen final Value headline protocol.

## 3. Actual frozen headline effect

Frozen selectors generated 237 headline instances across 109 blocks:

### Hit Rate — 81 headlines

- 29 `VALUE`;
- 4 `PLAYABLE`;
- 48 `LEAN`;
- 16 headline instances received positive units;
- 65 received 0u.

Unit distribution:

- 0u: 65
- 0.5u: 4
- 0.75u: 7
- 1.0u: 5

### Balanced — 88 headlines

- 34 `VALUE`;
- 6 `PLAYABLE`;
- 48 `LEAN`;
- 21 headline instances received positive units;
- 67 received 0u.

Unit distribution:

- 0u: 67
- 0.5u: 6
- 0.75u: 8
- 1.0u: 7

### Value — 68 headlines

- all 68 remain strict `VALUE`;
- 40 received positive units;
- 28 received 0u because evaluator reliability was LOW;
- 0.75u: 28;
- 1.0u: 12;
- 1.25u / 1.5u: 0 in the exposed development headline set.

The absence of 1.25u/1.5u historical headlines is not a reason to retune the ladder. Those tiers require HIGH reliability/evidence conditions that the selected 2020–2024 headlines did not satisfy.

## 4. Zero-unit cards are an intentional product state

Across all three lanes:

- 160/237 headline instances received 0u;
- 96 were `LEAN` at the exact current price;
- 64 were strict `VALUE` signals with LOW reliability.

By lane, LOW-reliability strict Value instances receiving 0u:

- Hit Rate: 17;
- Balanced: 19;
- Value: 28.

The selector and staking responsibilities are intentionally separate. A football/model selector may identify the strongest HHR/Balanced candidate even when the current exact price is not bettable. Likewise, an exact offer can be strict positive-EV but remain informational when evaluator reliability is LOW.

The backend presentation contract therefore distinguishes:

- `BET_VALUE`;
- `BET_PLAYABLE`;
- `INFORMATIONAL_NO_STAKE` / `RELIABILITY_INFORMATIONAL_ONLY`;
- `NO_RECOMMENDED_STAKE_AT_CURRENT_PRICE`;
- `UNSUPPORTED`.

This prevents misleading `$0 BET` cards.

## 5. Selected Play Through headlines

There were 10 PLAYABLE headline instances, but lane overlap reduces them to **7 unique exact wagers**:

- HHR instances: 4;
- Balanced instances: 6;
- Value instances: 0;
- unique exact wagers after HHR/Balanced overlap deduplication: 7.

All 7 unique selected PLAYABLE wagers were:

- moneylines;
- MEDIUM reliability;
- 0.5u recommendations.

Descriptive outcomes:

- 5 wins / 2 losses;
- 71.43% hit rate;
- +0.564 flat units;
- +8.06% flat ROI.

By season:

- 2023: 2-0;
- 2024: 3-2;
- no selected PLAYABLE headline wagers in 2020–2022.

This seven-play result is small exposed-development evidence. It supports neither expanding the corridor nor increasing PLAYABLE unit size. The broad-board PLAYABLE result above is the stronger warning against treating Play Through as generic Value.

## 6. How narrow was the real corridor?

### All 384 PLAYABLE board offers

Actual frozen concession after reliability/uncertainty haircut:

- minimum: 0.064pp;
- median: 0.650pp;
- mean: 0.606pp;
- maximum: 1.140pp.

The full 1.5pp theoretical ceiling was never reached in the 2020–2024 PLAYABLE board.

### Selected PLAYABLE headlines

For the 10 headline instances / 7 unique wagers:

- minimum: 0.613pp;
- median: 0.656pp;
- mean: 0.660pp;
- maximum: 0.689pp.

So the actual selected-user Play Through corridor was roughly **six to seven tenths of one percentage point**, much tighter than the 1.5pp maximum.

## 7. Concrete Play Through examples

### Minnesota at Chicago, 2023 Week 6

Frozen Hit Rate and Balanced both selected the same Minnesota ML offer:

- DraftKings `-166`;
- model-confidence probability: ~72.39%;
- evaluator/actionable probability: ~61.61%;
- exact price break-even: ~62.41%;
- exact-offer EV: about -0.79%;
- frozen realized Play Through concession: ~0.681pp;
- same-context Play Through boundary: `-167`;
- status: `PLAYABLE`, not `VALUE`;
- recommended units: 0.5u.

For a `$250` Normal user:

- 1u = `$2.50`;
- raw 0.5u = `$1.25`;
- frozen floor rounding -> **$1.00 recommended stake**.

HHR and Balanced overlap on the same exact offer, so it is one 0.5u wager, not two separate stakes.

### New York Jets at Miami, 2023 Week 15

- DraftKings `-298`;
- PLAYABLE boundary `-307`;
- MEDIUM reliability;
- 0.5u;
- historical settlement WIN.

The boundary communicates price tolerance; it does not turn the offer into strict Value.

## 8. Risk-profile bankroll simulation

Simulation started every profile at `$1,000` and replayed the same selected exact wagers chronologically. Risk profile changes dollar exposure only; the picks and recommended units are identical.

### With Play Through enabled

| Profile | Ending bankroll | Profit | Return on initial | Max drawdown | Total staked | Unique wagers |
|---|---:|---:|---:|---:|---:|---:|
| Cautious | $1,050.42 | $50.42 | 5.04% | 2.03% | $259.00 | 68 |
| Conservative | $1,078.80 | $78.80 | 7.88% | 3.01% | $398.00 | 68 |
| Normal | $1,106.24 | $106.24 | 10.62% | 4.07% | $545.50 | 68 |
| Aggressive | $1,136.86 | $136.86 | 13.69% | 5.02% | $693.00 | 68 |
| Ultra | $1,164.68 | $164.68 | 16.47% | 6.03% | $846.50 | 68 |

Each profile placed:

- 61 unique strict-Value-status wagers with positive units;
- 7 unique PLAYABLE wagers;
- same exact selected wagers and unit recommendations.

The monotonic dollar return in this exposed profitable development sample is simply the result of larger risk exposure/compounding. It does **not** mean Ultra predicts better or improves expected performance.

Ultra warning remains frozen:

> Ultra is the highest staking exposure setting. It does not imply higher expected performance, better picks, greater model confidence, or any increase in predictive edge.

## 9. Incremental Play Through bankroll effect

Counterfactual: same frozen selectors and units, but suppress PLAYABLE stakes to 0 while retaining strict-Value-status stakes.

| Profile | Strict-only ending | With Play Through | PT delta | Max DD changed? |
|---|---:|---:|---:|---|
| Cautious | $1,049.01 | $1,050.42 | +$1.41 | No |
| Conservative | $1,076.83 | $1,078.80 | +$1.97 | No |
| Normal | $1,102.97 | $1,106.24 | +$3.27 | No |
| Aggressive | $1,132.75 | $1,136.86 | +$4.11 | No |
| Ultra | $1,159.74 | $1,164.68 | +$4.94 | No |

Play Through added seven unique wagers and modestly improved the exposed development bankroll path. It did not increase the historical maximum drawdown in any profile. This is descriptive evidence only and was not used to widen the corridor or alter units.

## 10. Caps, rounding, and overlap

In the `$1,000` chronological simulation:

- per-wager 2.5% cap binding events: 0;
- slate 10% cap binding blocks: 0;
- minimum/rounding suppressed otherwise-positive wagers: 0;
- same exact offer appearing in more than one lane was deduplicated into one stake.

The 2.5% per-wager cap has headroom above the frozen maximum normal exposure: Ultra 1u = 1.5% bankroll and 1.5u = 2.25% bankroll before rounding.

### `$250` stake examples

| Profile | 1u | 0.5u PLAYABLE | 0.75u | 1.0u | 1.25u | 1.5u |
|---|---:|---:|---:|---:|---:|---:|
| Cautious | $1.25 | $0.50 | $0.50 | $1.00 | $1.50 | $1.50 |
| Conservative | $1.875 | $0.50 | $1.00 | $1.50 | $2.00 | $2.50 |
| Normal | $2.50 | $1.00 | $1.50 | $2.50 | $3.00 | $3.50 |
| Aggressive | $3.125 | $1.50 | $2.00 | $3.00 | $3.50 | $4.50 |
| Ultra | $3.75 | $1.50 | $2.50 | $3.50 | $4.50 | $5.50 |

Dollar stakes are floored to the nearest `$0.50`, so small-bankroll/profile combinations intentionally do not preserve exact percentage ratios.

## 11. Stored/manual exact-offer parity

Frozen Task05G policy tests prove that a manual and stored exact offer with the same line and price use the same evaluator/policy path and produce the same price status and unit recommendation.

For a changed spread/total line, the exact alternate offer must be reevaluated. The backend may not approve it using a synthetic fixed probability cost per line point.

## 12. Product interpretation

The cleanest user mental model is:

### HHR / Balanced

These always answer the selector question first. Their exact offer may then display:

- `VALUE` + positive stake;
- `PLAYABLE` + smaller stake;
- `LEAN` / current price not recommended + 0u;
- strict Value signal but LOW reliability + informational 0u.

Therefore HHR/Balanced are not promises that every featured card is an immediate bet.

### Value

The Value lane itself remains strict +EV only. It can also be withheld by the frozen selector fail-safes. If the resulting exact Value headline is LOW reliability, downstream staking remains 0u/informational rather than inventing bankroll permission from a strict EV calculation alone.

### Play Through

Play Through answers:

> This exact offer is not strict Value. Is it still close enough to the supported fair-price estimate that following the selected wager at a smaller stake remains reasonable?

It does **not** answer:

> Is every PLAYABLE offer a good bet?

The broad-board historical evidence strongly rejects that interpretation.

## 13. Remaining Task05G completion items

Before declaring downstream 05G frozen:

- freeze canonical staking/risk config separate from the superseded early selector/unit preregistration;
- freeze backend output contract/action reason codes;
- add product-simulation regression locks;
- record code/config/report SHAs and current-head CI artifact digest;
- preserve 2025 as explicitly NOT RUN.

No 2025 acceptance run is part of this completion by project direction.
