# NFL EDGE Market Evaluation Layer V1 — Task05F

Task05F is a downstream evaluator only. It does not modify or retrain QB-Elo, chronology-corrected XGBoost, Expected Margin V1, or Ridge Totals V1 R4.

## Frozen preregistration

`config/market_evaluator_v1.yaml` freezes the 2020–2024 expanding season-week OOS design, evaluator families, probability clipping, minimum support, deterministic reliability tiers, block-bootstrap uncertainty, conservative staking-probability haircut, shopping semantics, output contract, and 2025 firewall before candidate comparisons.

## Core interface

`evaluate_offer(game_state, normalized_offer, evaluator_state, ...)`

`NormalizedOffer` is source-agnostic. A DK/FD/Pinnacle feed row, historical row, or manual user input is normalized into the same object. Manual offers do not mutate evaluator state.

## Support-coordinate system (v1.1 — Task05F consistency fix)

Historical support envelopes and live/manual evaluations share one coordinate definition:

- Moneyline:
  - `pin` = selected-side Pinnacle no-vig probability (as-is)
  - `avg_pin_gap` = **signed** `exact_avg_selected_side - pinnacle_no_vig_selected` (direction of model-vs-market disagreement is meaningful)
  - `qb_xgb_gap` = **absolute** `|QB-Elo - XGBoost|` constituent disagreement
- Spread: `delta_magnitude` = **abs(selected-side Expected-Margin advantage relative to line)**; `market_magnitude` = abs(spread line) — orientation-invariant, so home/away mirrored sides share one support space.
- Totals: `delta_magnitude` = **abs(predicted_total - total line)**; `market_magnitude` = total-line level — orientation-invariant, so over/under mirrored sides share one support space.

Probability formulas keep using selected-side **signed** deltas (Normal-CDF / calibrated-Normal / strong-logistic unchanged); only support-distance uses absolute magnitude. Same-block or future-block support is never used (prior blocks only).

## Evaluator families

Moneyline: Pinnacle, raw QB-Elo, raw XGB, exact AVG, global market shrinkage, tiny reliability-aware shrinkage, strongly regularized logistic. Exact AVG and combined candidates fail closed unless both constituents exist.

Spread: Normal-CDF translation from Expected Margin residual sigma, calibrated Normal, strongly regularized logistic. Selected-side delta is `selected_expected_margin + selected_side_line`.

Totals: Normal-CDF translation from Ridge R4 residual sigma, calibrated Normal, strongly regularized logistic. Over delta is `prediction-line`; Under delta is `line-prediction`.

## Reliability and uncertainty

Reliability is deterministic HIGH/MEDIUM/LOW/UNSUPPORTED from prior support, block-bootstrap calibration uncertainty, support distance, model disagreement, and block stability. Unsupported rows fail closed. Staking probability shrinks actionable probability toward a market/break-even anchor based on reliability and uncertainty; Task05F does not implement Kelly or user-account staking.

## Product contract

The common candidate schema retains game identity, raw model signal, corroboration, book identity, actionable line/price, Pinnacle benchmark line/price/no-vig probability, actionable/staking probabilities, fair price, EV, reliability, support/evidence, model version, market timestamp, and config hash. Those fields support a full game board and deterministic DK/FD-vs-Pinnacle number/price coloring without equating market quality with wager quality.

## 2025

2025 is sealed. Development uses lazy projected parquet scans with a 2020–2024 season predicate and evaluator functions hard-reject `season == 2025`. No selector or staking simulation is included here.
