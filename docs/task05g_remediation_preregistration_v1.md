# Task05G Remediation V1 — Preregistration

Status: `PREREGISTERED_BEFORE_REMEDIATION_BACKTEST`

Preregistration config commit: `4b860cd1c87d605d26b305a7d7c90c8a1f34f315`

Parent forensic head: `f389223b3a77cc628e07750b620e6e77cf031763`

Frozen Task05F main baseline: `4984ea1ee38377f7f5016d2081be8f7c43bda4cd`

## Purpose

Test the architecture identified by the Task05G forensic review without retuning football models, changing Task05F, opening 2025, or selecting new historical regions after seeing remediation results.

The hypothesis is architectural:

> football models define the candidate side/region; Task05F evaluates the exact available price; selectors rank only the surviving model-derived candidates.

The remediation deliberately does **not** allow generic full-board evaluator `VALUE` to create a new candidate side.

## Frozen candidate-discovery regions

The remediation reuses only the previously locked Task05E candidate definitions:

1. Moneyline — `ML_DOG_VALUE_ZONE`, `AVG`, `ZONE`.
2. Moneyline — `ML_DOG_VALUE_ZONE`, `CORROB`, `ZONE`.
3. Moneyline — `ML_AVG_DISAGREEMENT`, `AVG`, `0-2`.
4. Spread — `SPREAD_DISAGREEMENT`, `EXPECTED_MARGIN`, union of `0-1`, `1-2`, `2-3`, `3-4`.
5. Totals — no headline candidate family.

These definitions predate this remediation. No new market, side, odds, probability, or disagreement bucket may be added after remediation results are observed.

For historical validation, the corrected Task05E discovery/confirmation ledgers are used only to recover the frozen candidate identity and region tags. Eligibility may use `game_id`, `family`, `model`, `bucket`, and `selected_side`. Outcome fields such as win/loss, push, and profit are forbidden from candidate eligibility.

Candidate identity is **game + market + selected side**. The historical Task05E actionable line or price is not part of candidate identity because the intended architecture is for Task05F to judge the exact current DK/FD offer on that already-discovered side.

## Exact-offer evaluator gate

The frozen Task05F board remains authoritative for exact-offer probability, support, reliability, uncertainty, EV, price status, Play Through, and settlement economics.

The remediation keeps the original Task05G primary eligibility fences wherever possible:

### Hit Rate

- model-derived candidate required
- exact shopped DK/FD offer
- supported
- HIGH or MEDIUM reliability
- `VALUE` or `PLAYABLE`
- actionable probability >= 0.55
- American odds from -300 through +200

### Balanced

- model-derived candidate required
- exact shopped DK/FD offer
- supported
- HIGH or MEDIUM reliability
- `VALUE` or `PLAYABLE`
- actionable probability >= 0.50
- expected value >= -0.03
- American odds from -220 through +200

### Value

- model-derived candidate required
- exact shopped DK/FD offer
- supported
- HIGH or MEDIUM reliability
- strict Task05F `VALUE`
- actionable probability >= 0.35
- point-estimated EV >= 0.02
- support_n >= 256
- support_distance <= 0.05
- uncertainty <= 0.045
- American odds from -180 through +250
- robust EV floor > 0

## Robust EV floor

The forensic audit showed that maximizing point-estimated EV amplified noise. V1 therefore uses a deterministic one-uncertainty-radius downside estimate without changing Task05F.

For an exact offer:

- `q = conditional_nonpush_probability`
- `u = uncertainty`
- `r = p_push`
- `q_lower = max(0, q - u)`
- `p_win_lower = (1-r) * q_lower`
- `D = decimal odds`
- `robust_EV = p_win_lower * D + r - 1`

This is the exact expected-profit identity `EV = p_win * D + p_push - 1` evaluated at a lower conditional-nonpush win probability. It is comparable across moneyline and point markets and naturally penalizes long prices for probability uncertainty.

No robust-EV cutoff other than zero is permitted in this preregistered pass.

## Ranking

### Hit Rate

1. actionable probability descending
2. reliability descending
3. price status (`VALUE` before `PLAYABLE`)
4. robust EV descending
5. point EV descending
6. better American price
7. candidate ID

### Balanced

1. actionable probability descending
2. reliability descending
3. price status (`VALUE` before `PLAYABLE`)
4. robust EV descending
5. point EV descending
6. candidate ID

This explicitly repairs the prior pathology where `VALUE` status outranked probability.

### Value

1. robust EV descending
2. reliability descending
3. actionable probability descending
4. point EV descending
5. candidate ID

The frozen model-derived region is an eligibility gate, not a retrospective cross-market ROI ranking. No model-region priority is assigned from historical ROI.

## Shopping and exact-offer semantics

Unchanged:

- ML: better price
- spread: better selected-side number, then price
- Over: lower line, then price
- Under: higher line, then price
- DK before FD only as deterministic final book tie-break
- no probability or EV transfer across alternate offers
- exact alternate Play Through offers must rerun through frozen Task05F `evaluate_offer(...)`

## Units / bankroll profiles

Unchanged from Task05G V1. This pass is testing candidate/evaluator/selector architecture, not staking optimization.

## Chronology and firewall

- development seasons only: 2020–2024
- expanding season-week chronology inherited from Task05F board
- 2025 sealed and forbidden
- no model retraining
- no evaluator modification
- no new historical threshold scan

## Required output

The remediation runner must report:

- play/no-play counts by selector
- aggregate and per-season ROI
- hit rate
- market mix
- frozen candidate-region mix
- robust-EV distribution
- overlap between selectors
- comparison to the original Task05G results
- five unchanged risk-profile simulations
- exact 2025 firewall proof
- deterministic replay proof

A positive aggregate result alone does not promote the policy. Season stability, sample coverage, and whether performance genuinely comes from model-derived candidates must be reported before any production recommendation.

## Stop rule

After the preregistered run, do **not** change thresholds, candidate regions, ordering, or the robust-EV formula in response to the observed ROI. If this pass fails, report failure and return to architecture/model provenance analysis rather than optimizing the same 2020–2024 outcomes.
