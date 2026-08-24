# Task05G Model Confidence + Selector V2 — Preregistration

Status: **PREREGISTERED BEFORE V2 OUTCOMES**

This document freezes the V2 experiment before any V2 development or confirmation ROI is generated.

## 1. Purpose

Test whether NFL EDGE can restore the intended product separation:

- **Hit Rate:** football-model confidence first; price only prevents unreasonable overpayment.
- **Balanced:** football-model confidence first; materially tighter price discipline than Hit Rate.
- **Value:** football-model candidate/provenance first; exact-offer economics second.

The experiment is motivated by Task05G forensic evidence showing that Task05F actionable probability can become market/juice-derived, especially for moneyline, and that max estimated EV can anti-select otherwise useful candidate pools.

This experiment does **not** retrain QB-Elo, XGBoost, Expected Margin, or Ridge Totals. It does not change Task05F evaluator code or frozen Task05E evidence.

## 2. Chronology / Holdouts

Three distinct periods are frozen:

1. **Model-confidence calibration warmup:** 2018–2019 only as strictly-prior football-outcome history.
2. **Selector development:** 2020–2022 only.
3. **Selector confirmation:** 2023–2024 only, opened automatically only after the development configuration is chosen by the preregistered rule.
4. **2025:** remains sealed and must hard-fail if loaded into the V2 development/confirmation runner.

At every chronological block, model-confidence calibration may use only games completed before that block. 2020–2024 outcomes are therefore used only after the prediction block they belong to.

## 3. Market-independent Model Confidence V1

### 3.1 Moneyline

Raw football input:

```text
raw_ml_home = (QB_Elo_home + XGB_home) / 2
```

Requirements:
- both QB-Elo and XGB must exist;
- no sportsbook price, line, Pinnacle probability, or market feature enters calibration;
- use strictly-prior completed binary game outcomes only.

Calibration:
- fit a two-parameter logistic/Platt calibration of home win outcome on `logit(raw_ml_home)`;
- require at least 256 strictly-prior binary observations;
- when fewer than 256 prior observations exist, model confidence is unsupported for headline selection;
- selected-side probability is the calibrated home probability or its complement.

Diagnostics preserve:
- raw QB-Elo probability;
- raw XGB probability;
- raw AVG probability;
- calibrated model-confidence probability;
- constituent disagreement;
- strictly-prior calibration N.

### 3.2 Spread

Raw football input:

```text
expected_home_margin
```

For each exact offered spread, derive a model-only cover probability from the strictly-prior residual distribution:

```text
residual = actual_home_margin - expected_home_margin
```

Requirements:
- no Pinnacle probability, market-implied mean, sportsbook price, or fitted market beta enters the model-confidence probability;
- the exact spread line defines the event being priced but does not alter the Expected Margin football prediction;
- use strictly-prior residuals only;
- require at least 256 strictly-prior residuals.

For the exact selected side/line, compute empirical `p_win`, `p_push`, and conditional non-push cover probability from the prior residuals using the exact W/L/P spread grading rule.

The model-confidence probability used for selector ranking is the conditional non-push cover probability.

### 3.3 Totals

Totals are **diagnostic only** in V2.

Ridge R4 remains frozen, but totals are not eligible for V2 HHR, Balanced, or Value headline selection because Task05E did not establish a validated totals betting-edge family and the Task05G forensic audit found totals to be a major downstream loss source.

No claim is made that totals are permanently excluded from the product.

## 4. Common V2 Candidate Requirements

Headline candidate rows must:

- be exact-shopped DraftKings/FanDuel offers under the frozen shopping semantics;
- be Task05F `supported == true` (UNSUPPORTED remains fail-closed);
- have model-confidence support N >= 256;
- be moneyline or spread;
- carry complete provenance and exact-offer break-even probability;
- never use 2025.

Task05F `HIGH/MEDIUM/LOW` is preserved as a diagnostic/tie-break signal, but V2 does **not** hard-exclude supported `LOW` rows because the forensic audit showed current LOW conflates cold-start history with mature signal warnings. No reliability threshold is loosened to achieve a desired play count; V2 instead requires the independent model-confidence support floor above.

## 5. Price / Edge Definitions

For every exact offer:

```text
model_price_gap = model_confidence_probability - break_even_probability
```

This quantity is used only after football-model inference.

It answers:

> How far above or below the exact offer's break-even requirement is the football-model confidence?

It is not a sportsbook feature in the football model.

## 6. Hit Rate V2

Product question:

> Which supported exact wager does the football system think is most likely to cash?

Eligibility:
- common V2 requirements;
- model-confidence probability >= 0.55;
- American odds from -300 through +200 inclusive.

No positive-EV requirement.
No Task05F VALUE requirement.
No frozen Task05E +ROI-region requirement.
No minimum `model_price_gap` beyond the loose American-odds sanity band.

Ranking:
1. highest model-confidence probability;
2. better Task05F reliability tier as tie-break only (`HIGH > MEDIUM > LOW`);
3. larger `model_price_gap`;
4. better American price;
5. stable candidate ID.

## 7. Balanced V2

Product question:

> Which high-confidence football-model wager gives the best balance between chance to cash and the price being demanded?

Common eligibility:
- common V2 requirements;
- model-confidence probability >= 0.52;
- American odds from -220 through +200 inclusive.

Balanced does **not** require Task05F strict VALUE.
Balanced does **not** rank by maximum Task05F EV.

### 7.1 Fixed preregistered price-tolerance grid

Exactly three variants are allowed:

- `B0`: `model_price_gap >= 0.00` (model meets/exceeds break-even)
- `B1`: `model_price_gap >= -0.01` (allow 1.0 percentage point concession)
- `B2`: `model_price_gap >= -0.02` (allow 2.0 percentage point concession)

No other thresholds may be evaluated in this experiment.

For every variant, ranking is:
1. highest model-confidence probability;
2. larger `model_price_gap`;
3. better Task05F reliability tier as tie-break only;
4. better American price;
5. stable candidate ID.

### 7.2 Development winner rule

The winning Balanced tolerance is selected using **2020–2022 only**.

First compute original Task05G Balanced V1 development coverage on the identical 2020–2022 blocks without using results.

A V2 variant is product-viable only if:

```text
V2 development play blocks >= 75% of original Balanced V1 development play blocks
```

This is an anti-neutering guardrail, not a training target. If a variant misses the floor, it is ineligible even if its ROI is high. The threshold is not loosened to recover coverage.

Among product-viable variants:
1. require development non-push hit rate >= 55%;
2. require overall development flat-1u ROI >= 0%;
3. choose the variant with the highest number of development seasons (2020, 2021, 2022) having non-negative ROI;
4. then highest overall development ROI;
5. then highest development coverage;
6. final deterministic tie-break: tighter tolerance (`B0`, then `B1`, then `B2`).

If no variant passes the hit-rate + ROI + coverage gates, Balanced V2 is declared **development failure** and no outcome-driven replacement threshold is searched.

After a winner is selected, that exact tolerance is frozen before 2023–2024 confirmation is scored.

## 8. Value V2

Purpose:

> Preserve football-model provenance while letting Task05F judge the exact offered price.

Eligibility:
- common V2 requirements;
- model-confidence probability > exact-offer break-even probability (`model_price_gap > 0`);
- Task05F price status must be strict `VALUE` (not PLAYABLE);
- Task05F expected value must be > 0;
- support distance must be <= 0.10 (frozen Task05F supported envelope already fails beyond this);
- American odds from -180 through +250 inclusive.

No frozen Task05E region membership is required. The V2 candidate universe is therefore broader than the remediation's region-only experiment while still requiring football-model agreement with the wager economics.

Ranking:
1. highest `consensus_edge`, where

```text
consensus_edge = min(model_price_gap, Task05F evaluated_edge_probability)
```

2. highest model-confidence probability;
3. better Task05F reliability tier;
4. better American price;
5. stable candidate ID.

This deliberately avoids ranking by maximum point-estimated Task05F EV.

## 9. Coverage / Anti-Neutering Diagnostics

The source plan says coverage is an acceptance diagnostic rather than a training target. This experiment follows that rule.

For HHR, Balanced, and Value report separately for development and confirmation:
- total chronological blocks;
- play blocks;
- no-play blocks;
- play-block percentage;
- mean eligible candidates per block;
- median eligible candidates per block;
- market mix;
- reliability mix.

### HHR coverage viability

HHR V2 must retain at least 75% of original HHR V1 **development-period** play-block coverage.

If it does not, HHR V2 is considered product-neutered even if ROI improves. No threshold is loosened inside this experiment.

### Balanced coverage viability

Handled in the winner rule above: at least 75% of original Balanced V1 development coverage.

### Value coverage viability

Value is allowed to be rarer by product design and is not required every week. It is therefore **not** forced to match V1 coverage.

However, the experiment must explicitly report the ratio:

```text
Value V2 development coverage / Value V1 development coverage
```

and flag `VALUE_COVERAGE_COLLAPSE` if V2 has fewer than 50% as many development play blocks as V1. This is a product warning, not authorization to loosen Value after seeing outcomes.

## 10. Performance Metrics

For each lane/variant and each phase report:
- plays;
- W/L/P;
- non-push hit rate;
- flat 1u ROI;
- average odds;
- average model-confidence probability;
- average model-price gap;
- per-season play count / hit rate / ROI;
- market mix;
- reliability mix;
- maximum losing streak when feasible.

Calibration diagnostics for model-confidence probabilities:
- Brier;
- log loss;
- calibration intercept/slope where feasible;
- 10-point reliability table.

ROI alone cannot select the ML calibration method because the method is frozen above.

## 11. Confirmation Rules

The runner must choose the Balanced variant from 2020–2022 **before** calculating or printing any 2023–2024 selector outcome metrics.

The chosen selector configuration is then applied unchanged to 2023–2024.

No threshold, ranking rule, eligibility rule, calibration family, or market inclusion may change after confirmation results are observed.

Confirmation is reported honestly even if negative.

## 12. Baselines

Report V2 against:
- original Task05G V1 HHR/Balanced/Value on identical phase blocks;
- preregistered region-only remediation results where useful as diagnostic context;
- raw model-confidence eligible pools before headline selection.

The comparison must not silently change board, shopping, grading, or phase definitions.

## 13. Success / Failure Interpretation

A lane is not considered improved merely because ROI rises on fewer bets.

### HHR desired behavior
- materially higher hit rate than ordinary candidate pools;
- frequency remains useful;
- small negative ROI is acceptable if hit-rate product semantics are clearly achieved;
- market juice must not create the confidence ranking.

### Balanced desired behavior
- materially useful frequency;
- model confidence drives ranking;
- price tolerance prevents HHR-like overpayment;
- development rule must pass before confirmation;
- confirmation should not show catastrophic degradation.

### Value desired behavior
- football provenance is preserved;
- strict exact-price economics remain required;
- no max-EV optimizer's curse ranking;
- coverage is monitored so the product does not collapse into perpetual PASS.

## 14. Prohibited Actions

Do not:
- inspect or use 2025;
- add sportsbook inputs to football models;
- search thresholds beyond `B0/B1/B2`;
- redefine HHR/Balanced/Value after seeing V2 outcomes;
- add team or season identity features;
- tune reliability thresholds to restore play counts;
- force one play per week;
- select a design solely because it has the highest ROI on a tiny sample;
- change exact-offer shopping or settlement rules;
- modify frozen Task05F evaluator code in this experiment.

## 15. Required Evidence

Implementation must produce deterministic artifacts containing:
- preregistration hash;
- code SHA;
- phase definitions;
- model-confidence calibration state by block;
- all V2 candidate rows;
- development metrics for HHR/B0/B1/B2/Value;
- frozen Balanced winner decision proof;
- confirmation metrics for frozen HHR/Balanced/Value;
- V1 phase baselines;
- coverage comparison;
- scorecard Markdown/JSON;
- 2025 firewall proof;
- deterministic replay proof.
