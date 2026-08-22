# Task05F Evaluator Rebuild V1

Status: ARCHITECTURE / VALIDATION CONTRACT

Base commit: `3ed8d740a88b59d46e27e206f39757307a6a13da`

## Scope

This branch changes only the downstream wager-evaluation system. The frozen football models remain untouched:

- Moneyline: Oracle QB-Elo + chronology-corrected XGBoost
- Spread: Expected Margin V1
- Totals: Ridge Totals V1 R4

No model feature changes, retraining, parameter tuning, threshold hunting, price-band hunting, or retrospective bucket discovery are permitted in Task05F.

The evaluator answers: **Given the frozen football inference, what is the win/push/loss probability of this exact wager, what is its fair price, and how attractive is the actual sportsbook offer?**

## Integrity rules

1. Development/evaluation seasons are 2020-2024 only. 2025 remains sealed.
2. All fitted evaluator state is expanding walk-forward using strictly prior season-week blocks.
3. Existing frozen Task05E regions are external validation evidence only. They are never model/evaluator features and never tuning targets.
4. Any newly observed historical pattern is labeled `OBSERVATIONAL_ONLY_NOT_TUNED`; it may be preserved as a predeclared 2025 hypothesis but cannot feed back into Task05F development.
5. Pinnacle is a benchmark/anchor only; DK/FD are actionable books.
6. Every wager is evaluated at its own actionable line and price.
7. Shopping is deterministic and side-specific: spread best selected-side number then price; total Over lower line, Under higher line, then price; fixed DK-before-FD tie-break.
8. Exact complement identities may be used only when two offers are exact complements at the same line. Independently shopped opposite sides are evaluated independently at their own lines.
9. Pushes are explicit for spread/totals. Point-market EV must use win/push/loss economics; push is zero-unit return.
10. Experimental and incumbent evaluator families must use the same chronology, cold-start, support/OOD, and offer universe when compared.
11. No production family is promoted merely because it improves historical ROI. Probability quality, calibration, coherence, wagering discrimination, and frozen-edge preservation are separate acceptance dimensions.

## Value semantics

`VALUE` is strict mathematical positive expected value at the current offer:

- `EV > 0`: positive value
- `EV = 0`: fair
- `EV < 0`: negative value

There is no arbitrary +2%, +3%, or +5% minimum to qualify as positive value.

If no positive-EV wager exists, the future Value selector may honestly show no positive-value play.

## Global Play Through contract

Play Through is a global downstream price-tolerance / presentation concept. It does **not** redefine Value and does **not** alter football-model output or evaluator fitting.

Every supported wager should eventually expose:

- `actionable_probability`
- `p_win`, `p_push`, `p_loss` where applicable
- `fair_price_american`
- `expected_value`
- `reliability`
- `uncertainty`
- `play_through_price_american` (when available)
- `play_through_status`

The product semantics are:

- `VALUE`: current price has strict `EV > 0`
- `PLAYABLE`: current price is not strict positive EV at the point estimate, but remains inside a separately defined, uncertainty-aware Play Through envelope
- `LEAN`: football side/model opinion exists, but price is outside the Play Through envelope
- `PASS`: unsupported, invalid, materially mispriced, or no actionable football signal

The exact Play Through formula is intentionally **not tuned in this rebuild phase**. It must be locked only after the core probability/valuation layer passes validation. It may use evaluator uncertainty/reliability, but may not use retrospective ROI buckets or guarantee that a slate produces a play.

## Point-market probability contract

For spread and totals, the preferred public contract is three-way:

- `p_win`
- `p_push`
- `p_loss`

with `p_win + p_push + p_loss = 1` within numerical tolerance.

Expected value for a one-unit stake is:

`EV = p_win * (decimal_odds - 1) - p_loss`

Push contributes zero.

For half-point lines where push is impossible, `p_push = 0` and the contract reduces to binary win/loss.

## Moneyline contract

Moneyline retains selected-side win probability from the frozen QB-Elo/XGB information plus the evaluator's permitted market benchmark logic. Missing required constituents fail closed. NFL ties must follow the wager settlement convention and must not be silently encoded as losses.

## Frozen-edge validation

Frozen Task05E membership is reconstructed from the authoritative lock/corrected ledgers. Preservation joins must retain exact wager identity/semantics, including the selected side and the authoritative actionable line/price/book where those are part of the frozen wager.

Frozen evidence is used only to answer whether the evaluator destroys, preserves, or usefully ranks previously locked information. It cannot be used to choose new thresholds.

## Full-board validation

For each market, validation reports at least:

- Brier / log loss / calibration / AUC where applicable
- probability dispersion
- support/OOD/cold-start counts
- positive-EV vs nonpositive-EV economics
- fixed diagnostic EV bands only
- per-season behavior
- exact-offer shopping consistency
- point-market win/push/loss coherence
- exact-complement checks only on exact mirrored offers
- frozen 05E preservation
- deterministic rerun hashes

## GitHub Actions execution contract

The repository is the source of truth. Validation runs execute from the exact commit SHA in GitHub Actions. Actions may execute tests and generate artifacts; Actions do not make methodological decisions.

The workflow must upload compact scorecards/provenance artifacts tied to the commit SHA. The implementation voice remains the code/review process in this branch; a later independent second review may inspect the same committed source and Actions evidence.
