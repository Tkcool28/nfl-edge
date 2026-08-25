# Task05G HHR Model-Market Corroboration V1 — Preregistration

Status: **FROZEN BEFORE OUTCOME OUTPUT**

Purpose: test whether HHR headline ranking improves when extreme ML model confidence is partially tempered by sharp-market disagreement without replacing the football-model signal or reducing card coverage.

This experiment is stacked on the completed HHR market-price audit. It changes ranking only. It does not change Task05F, the football models, ML confidence calibration, Spread Confidence V3, eligibility thresholds, units, bankroll policy, or Play Through. 2025 remains sealed.

## Chronology

- 2020-2022: development diagnostic
- 2023-2024: already-exposed locked diagnostic only
- 2025: sealed / prohibited

No result from 2023-2024 may be used to tune a coefficient or threshold. No production promotion is authorized from this experiment by itself.

## Baseline

The baseline is the current Spread V3 HHR selector ordering:

1. highest `model_confidence_probability`
2. reliability
3. model price gap
4. price
5. deterministic candidate id

Candidate eligibility and exact DK/FD shopping are unchanged.

## Primary rule: HALF_SHRINK

For moneyline candidates:

```text
excess_model_over_market = max(model_confidence_probability - pinnacle_anchor_probability, 0)
headline_trust_score = model_confidence_probability - 0.50 * excess_model_over_market
```

Equivalent interpretation:

- if the model is at or below Pinnacle no-vig, leave the model confidence unchanged;
- if the model is above Pinnacle no-vig, pull only the excess halfway back toward the market;
- the football model therefore remains the primary signal and is never replaced by Pinnacle.

For spread candidates, retain Spread V3 `model_confidence_probability` unchanged as the headline trust score.

The trust score is **ranking-only** and is not a calibrated probability.

## Secondary comparator: MIN_CAP

For diagnostic comparison only:

```text
min_cap_score = min(model_confidence_probability, pinnacle_anchor_probability)
```

for ML candidates; spread candidates retain Spread V3 confidence.

`MIN_CAP` is deliberately not the primary rule because it can collapse to a sharp-market ranking whenever model confidence exceeds Pinnacle. It cannot replace HALF_SHRINK after results are observed.

## Coverage invariant

The experiment may not alter HHR eligibility. Therefore baseline, HALF_SHRINK, and MIN_CAP must have the **same play/no-play blocks** in both periods. Any coverage mismatch invalidates the experiment.

This means the test cannot improve by simply withholding cards.

## Model-agency diagnostics

For each phase, report:

- overlap of HALF_SHRINK selection with baseline model-confidence rank 1;
- overlap with pure Pinnacle-no-vig rank 1 among the same HHR-eligible candidate set;
- changed selections versus baseline;
- selections where HALF_SHRINK differs from both pure-model rank 1 and pure-Pinnacle rank 1;
- average selected model confidence;
- average selected Pinnacle no-vig probability;
- average model-minus-Pinnacle gap;
- average QB-Elo/XGBoost disagreement;
- market mix, odds, hit rate, ROI, and coverage.

These diagnostics are descriptive. No post-hoc overlap threshold may be invented.

## Frozen development success gate

HALF_SHRINK is directionally successful only if all are true in 2020-2022:

1. exact HHR block coverage parity versus baseline;
2. non-push hit rate improves by at least **+5.0 percentage points** versus baseline;
3. ROI does not worsen versus baseline;
4. deterministic replay passes;
5. 2025 firewall passes.

The 2023-2024 diagnostic is reported separately as robustness evidence but cannot select or retune the rule.

## Prohibited actions

- no new confidence floor;
- no new Pinnacle threshold;
- no model-market disagreement cutoff;
- no eligibility filtering based on market corroboration;
- no changing the 0.50 coefficient after results;
- no replacing HALF_SHRINK with MIN_CAP after results;
- no Task05F refit;
- no ML calibrator change;
- no Spread V3 change;
- no opening 2025.
