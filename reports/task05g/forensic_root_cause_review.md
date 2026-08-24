# Task05G Forensic Root-Cause Review

Verdict: `TASK05G_FORENSIC_ROOT_CAUSE_IDENTIFIED`

This review is read-only diagnostic evidence over 2020–2024. No selector threshold, Task05F evaluator, football model, frozen evidence, or 2025 material was changed or opened.

Validated forensic code head: `2cbde12a4c32c88dcc07ca12fe114ac432f3b902`.
Validation workflow run: `32677426141` — PASS.
Evidence artifact: `9503118360`, SHA-256 `07335718074f34c6a205818a9d20c95439e5edc98809a9bbb95bc5ac8badc406`.

## Executive finding

The Task05G paradox is real, but it is not caused by settlement math, American-odds economics, best-book shopping, exact-offer probability transfer, or home/away team mapping.

The central architecture problem is that the current pipeline is **not equivalent to taking the historically tested football-model picks and becoming more selective**.

Task05E's profitable discovery regions were conditional football-model-vs-market signals. Task05F then fit global market-calibration/pooling parameters whose objective was broad probability fit. In most historical blocks those fitted parameters reduced the football model's incremental influence to exactly zero or nearly zero. Task05G subsequently treated generic evaluator `VALUE` (exact-offer EV > 0) as a full-board candidate discovery signal and ranked the largest point-estimated EV first.

That changed the meaning of the recommendation from:

> football model identifies an underpriced side/region, then exact-offer evaluation decides whether the available price is acceptable

into something much closer to:

> calibrated market estimate says one DK/FD price is attractive; choose the largest estimated EV even when the football model does not support that side

This is why increased selectivity did not mechanically improve the historical model ROI: the selector was becoming selective on a **different signal**.

## 1. Mechanical integrity is clean

Across all 187 selected Task05G headline rows in the first forensic audit:

- final-score settlement mismatches: 0
- exact American-odds profit mismatches: 0
- DK/FD shopping mismatches: 0
- exact evaluated board row missing: 0
- probability/EV transfer mismatches: 0

The separate moneyline team-identity audit covered all 112 selected ML rows:

- canonical `game_id` home/away mismatches: 0
- selected price matched the expected labeled team: 112/112
- selected price missing from expected team: 0
- opposite team carrying the selected price: 0
- ambiguous same-price both-team matches: 0

The extreme away-side skew is therefore real selection behavior, not a side-label or sportsbook-team mapping bug.

## 2. Hit Rate's apparent +ROI is not evidence that price does not matter

Hit Rate produced 59 plays and +6.30% aggregate ROI, but its market decomposition is:

- Moneyline: 54 plays, ROI approximately -1.13%
- Spread: 5 plays, 5-0, ROI approximately +86.58%
- Totals: 0 plays

The five winning spread wagers drove the positive aggregate. Those spread wagers were not evidence that a pure win-probability strategy systematically dominated value-aware selection.

## 3. Balanced has a direct selector-design pathology

Current Balanced ranking places `VALUE` status ahead of actionable probability. It therefore behaved much more like a second Value selector than the intended middle-ground product.

Observed over 67 eligible blocks:

- current Balanced selection was `VALUE` in 64/67 blocks
- current and a diagnostic probability-first ordering differed in 50/67 blocks
- current ordering surrendered an average 6.59 percentage points of actionable probability
- surrendered >=5pp in 36 blocks
- surrendered >=10pp in 23 blocks

Current Balanced:

- average q: 55.45%
- hit rate: 45.45%
- ROI: -15.12%

Diagnostic probability-first ordering with **identical eligibility**:

- average q: 62.04%
- hit rate: 61.19%
- ROI: +0.87%

Season ROI for the diagnostic ordering: 2021 +13.67%, 2022 +0.26%, 2023 -19.88%, 2024 +17.70%.

This counterfactual is diagnostic only and is not adopted post hoc. It proves that the current lexicographic ordering itself materially harms Balanced.

## 4. Highest-EV Value ranking exhibits optimizer's-curse behavior

Using the exact same frozen Value eligibility and ranking eligible offers by the current Value key within each season-week block:

- rank 1 / current Value headline: ROI -18.45%
- rank 2: ROI +8.14%
- rank 3: ROI -4.07%
- ranks 4-5: ROI +3.42%
- rank 6+: ROI -20.84%

Cumulative top-k:

- top 1: 61 plays, avg EV +6.71%, ROI -18.45%
- top 3: 155 plays, avg EV +5.79%, ROI -5.55%
- top 5: 216 plays, avg EV +5.34%, ROI -3.02%
- all eligible: 283 plays, avg EV +4.78%, ROI -7.24%

The largest point-estimated EV is not a reliably ordered estimate of realized edge. Selecting the maximum magnifies estimation noise.

Fixed EV bands reinforce this:

- 2-4% estimated EV: ROI -16.16%
- 4-6%: ROI +18.03%
- 6-10%: ROI -15.97%
- >=10%: ROI -2.16%

Estimated EV magnitude is not monotonically calibrated to realized ROI.

## 5. Reliability/uncertainty does not fully protect the selected tail

All Value-eligible exact offers by accepted-family uncertainty:

- 2-3% radius: ROI +4.02%
- 3-4%: ROI -3.88%
- >4%: ROI -19.93%

All 61 selected Value rows were MEDIUM reliability; none were HIGH.

This is diagnostic evidence that uncertainty contains useful information, but no new cutoff is adopted from these retrospective results.

## 6. Market decomposition shows where the failure lives

Current Value selected tail:

- ML: 32 plays, ROI -37.25%
- Spread: 17 plays, ROI +40.77%
- Total: 12 plays, ROI -52.18%

Current Balanced selected tail:

- ML: ROI -25.15%
- Spread: ROI +13.12%
- Total: ROI -55.86%

Best Value-eligible exact offer **within each market** per block:

- ML: 40 plays, ROI -35.62%
- Spread: 39 plays, ROI +5.47%
- Total: 13 plays, ROI -55.86%

This is not evidence for a post-hoc spread-only rule. It shows that generic evaluator EV behaves very differently across accepted families and should not be assumed comparable as a universal full-board ranking statistic.

## 7. The evaluator often removes the football model's incremental influence

Task05F state-by-block trace:

### Moneyline V4 model weight

98 supported blocks:

- zero model influence: 91
- positive influence: 7
- mean weight: 0.00137
- maximum weight: 0.03511

By season:

- 2020: 10/10 zero
- 2021: 15/22 zero; 7 positive
- 2022: 22/22 zero
- 2023: 22/22 zero
- 2024: 22/22 zero

Thus every supported ML block from 2022 onward used a final probability with **zero incremental QB-Elo/XGBoost weight** after calibrated Pinnacle.

### Spread V3 beta

100 supported blocks:

- zero beta: 71
- positive beta: 29
- mean beta: 0.01090

By season:

- 2020: 12/12 positive, mean 0.0642
- 2021: 13 zero / 9 positive
- 2022: 15 zero / 7 positive
- 2023: 21 zero / 1 positive
- 2024: 22/22 zero

### Total V3 beta

Totals retained more model influence from 2022 onward, but Task05E had explicitly found **no robust totals betting edge** and Task05F retained the label `TOTALS_VALUE_WEAK_NO_DEMONSTRATED_EDGE`.

## 8. Why zero influence can coexist with profitable model regions

Task05F's accepted calibrators fit a **global probability objective**.

ML V4 calibrates Pinnacle probability and then fits a single global model-vs-market pooling weight. If the football model does not improve global predictive loss, the constrained optimum can be exactly zero.

Spread V3 fits a single global beta on model-minus-market implied mean. If disagreement is not linearly useful across all observations, beta can be zero.

This is not mathematically incompatible with a model having profitable **conditional disagreement regions**. A model can add little global Brier/log-loss improvement while still contain useful betting information in a specific side/price/disagreement state.

Task05E's model-edge work was explicitly about those conditional regions.

## 9. The historical model-edge evidence was conditional, not universal

Task05E discovery (2020-2022) recorded:

- ML dog Value AVG: +25.2% ROI; all 3 discovery seasons positive
- ML corroborated dog Value: +28.07%; all 3 positive
- ML AVG 0-2 disagreement: +15.44%; all 3 positive
- Spread 0-4 disagreement: +9.74%; all 3 positive
- Totals: no candidate recommended

Later 2023-2024 confirmation was materially weaker and mostly negative for the ML regions, so the original edge was not universally stable across all five years. This prevents claiming that the football models themselves were guaranteed profitable in every development season.

However, Task05F's pooled 2020-2024 preservation audit still showed that when it started from the **predefined model-derived candidate rows** and then used the evaluator as a filter:

- ML dog AVG strict +EV kept: +16.87% ROI
- ML corroborated dog strict +EV kept: +12.33%
- Spread 0-4 strict +EV kept: +11.16%

That is crucial: these preservation tests did **not** ask the evaluator to discover wagers from the full board. The model/region had already chosen the side and candidate. The evaluator only decided whether the exact offer was supported/+EV.

Task05G changed that architecture by asking generic evaluator `VALUE` to discover and rank the whole board.

## 10. Generic ML Value is largely not a football-model signal

Across all 140 generic ML Value-eligible Task05G opportunities:

- side = away: 140
- side = home: 0
- football model more bullish than calibrated market on selected side: 34
- football model not more bullish than calibrated market: 106
- overall ROI: -3.22%

The 106 rows where the model was not more bullish than market were therefore still considered generic evaluator Value because the evaluator's final probability/available DK-FD price relationship made EV positive.

Selected ML Value headlines are even more revealing:

- 32 plays, all away
- 8 where model was more bullish than market
- 24 where model was not more bullish than market
- raw model selected-side probability <50% on 24/32
- overall ML Value ROI: -37.25%
- model-more-bullish subgroup: -1.62% ROI (n=8)
- model-not-more-bullish subgroup: -49.13% ROI (n=24)

The current ML Value selector is therefore mostly **not selecting the side on which the football model expresses a positive market disagreement**.

## 11. Exact frozen-region overlap is limited

Among the 32 selected ML Value headlines, exact membership counts in previously frozen model-derived regions were:

- ML dog Value AVG: 9
- ML corroborated dog Value: 5
- ML AVG 0-2: 5

The selector is primarily ranking generic evaluator Value, not recovering the original model-derived candidate population.

For selected Spread Value, 6/17 exact offers belonged to the frozen Spread 0-4 region; those six produced +42.70% ROI in this small diagnostic subset. Again, no new market-specific policy is inferred from the small sample.

## Root-cause conclusion

The current pipeline should not be described as:

> same football models + evaluators + more selective selectors

because that is not what it does.

A more accurate description is:

1. football models produce raw signals;
2. Task05F globally pools/calibrates those signals against Pinnacle, often assigning the football model zero incremental weight;
3. generic `VALUE` becomes positive exact-offer EV under that accepted evaluator probability;
4. Task05G searches all markets/sides and ranks maximum evaluator EV;
5. the historical conditional model-edge definition is no longer a required eligibility axis.

This explains how a supposedly more selective layer can perform worse than the original model-derived candidate regions: it is selective on a different and poorly rank-calibrated statistic.

## Remediation principles — not yet implemented

Do **not** retune the football models first. Do **not** open 2025. Do **not** choose retrospective ROI thresholds.

A remediation should be preregistered around these principles:

1. **Preserve model signal as its own axis.** Raw model direction/disagreement with Pinnacle must remain visible and cannot be silently replaced by generic evaluator Value.
2. **Separate candidate discovery from price evaluation.** Football model/validated structural state chooses or qualifies the side; evaluator judges the exact available offer, support, price, and Play Through status.
3. **Do not equate `EV > 0` with validated Value.** Task05F `VALUE` is an exact-offer mathematical status, not proof that the row belongs to a historically demonstrated betting-edge population.
4. **Do not rank purely by maximum point EV.** The forensic rank audit shows severe optimizer's-curse behavior.
5. **Balanced must genuinely balance probability and price.** Its current VALUE-first lexicographic ordering should be replaced by a preregistered structure in which a modest EV label cannot automatically trump a much larger probability advantage.
6. **Treat accepted market families separately in diagnostics.** Generic EV magnitudes from ML V4, Spread V3, and Total V3 should not be assumed universally comparable without evidence.
7. **Totals cannot inherit a Value headline merely because evaluator EV is positive.** The upstream model phase had no demonstrated totals betting edge.
8. **Use 2020-2024 only for remediation development.** Keep 2025 sealed for the eventual holdout.

No remediation is implemented in this review. PR #25 remains draft/unmerged.
