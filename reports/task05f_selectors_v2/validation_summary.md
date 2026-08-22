# Task05F Selectors V2 — Validation Evidence

Status: **VALID EXECUTION / SELECTOR V2 NOT PROMOTED**

V2 was preregistered before historical scoring in `config/task05f_selectors_v2_prereg.yaml`. It changed exactly one selector eligibility rule from V1: every primary-card candidate had to have strictly positive **direction-only** support from the already-frozen football signal. The support threshold was fixed at zero and its magnitude was not used in ranking. All V1 rankings, tiebreaks, reliability eligibility, Value semantics, Play Through behavior, no-play behavior, and duplicate-card policy remained unchanged.

All results below are **`OBSERVATIONAL_ONLY_NOT_TUNED`**. They may not be used to alter V2's threshold, ranking, or formulas. Season 2025 remained sealed.

## Reproducibility

- Branch feature head: `8760b14fc01a9aa442631ad660137cd20f186118`
- GitHub Actions run: `32556609815`
- Actions execution/merge SHA recorded by runner: `a863707170df04138263743b6c03ac760d2e55ca`
- Artifact ID: `9471687833`
- Artifact ZIP digest: `sha256:d7f88e21fe9c6cce08c9b0db30f6c5a9f3cdd89dc43598a9367554a96fc5ec2d`
- V2 preregistration SHA-256: `2eedf1d9c3801e4fe43b9aeb4c7288d4a38b0ac0d150c41be652ea6c96c1d7a8`
- Two complete selector executions: PASS
- Deterministic output comparison: PASS
- Candidate rows: 8,448
- Candidate table immutable through selection: PASS
- Candidate table outcome fields: none
- Outcomes joined only after selections were frozen: PASS
- Selector slates: 109 chronological season-week blocks
- 2025 firewall: PASS
- Direction support on every selected wager: strictly `> 0`
- Direction magnitude used in ranking: false
- Production promotion: false

## Overall selector results

| Card | Plays | Coverage | Hit rate ex-push | Flat ROI |
|---|---:|---:|---:|---:|
| High Hit Rate | 58 | 53.2% | 50.88% | -7.96% |
| Balanced | 52 | 47.7% | 45.10% | -14.36% |
| Value | 52 | 47.7% | 40.38% | -14.92% |

High Hit Rate had 29 wins, 28 losses, and 1 push. Balanced had 23 wins, 28 losses, and 1 push. Value had 21 wins and 31 losses.

## Market mix and market-specific diagnostic results

The market-specific performance below is post-selection diagnostic evidence only. It is not a tuning target and does not create a new market/ROI rule.

| Card | Market | Plays | Hit rate ex-push | Flat ROI |
|---|---|---:|---:|---:|
| High Hit Rate | Moneyline | 11 | 45.45% | -36.44% |
| High Hit Rate | Spread | 47 | 52.17% | -1.30% |
| Balanced | Moneyline | 7 | 28.57% | -49.65% |
| Balanced | Spread | 45 | 47.73% | -8.87% |
| Value | Moneyline | 14 | 21.43% | -28.97% |
| Value | Spread | 38 | 47.37% | -9.75% |

No totals qualified because the upstream reliability policy kept totals at LOW, which is explorer-only for primary cards.

All selected rows were MEDIUM reliability. High Hit Rate selected 38 VALUE rows and 20 PLAYABLE rows. Balanced and Value selected only strict VALUE rows, as required.

## Comparison with frozen Selector V1 evidence

V1 had been frozen separately before V2 was designed. The comparison is diagnostic only:

| Card | V1 hit rate | V1 ROI | V2 hit rate | V2 ROI |
|---|---:|---:|---:|---:|
| High Hit Rate | 61.67% | +1.30% | 50.88% | -7.96% |
| Balanced | 46.43% | -14.30% | 45.10% | -14.36% |
| Value | 44.64% | -9.70% | 40.38% | -14.92% |

The direction-only gate also failed to preserve V1's strong selected-spread diagnostics. V1 selected-spread results were approximately +19.86% ROI for High Hit Rate, +14.29% for Balanced, and +8.91% for Value; the corresponding V2 selected-spread diagnostics were -1.30%, -8.87%, and -9.75%.

This does **not** invalidate the frozen spread evaluator or the frozen Task05E spread evidence. It shows only that a zero-threshold raw-football-direction gate is not a useful universal primary-card eligibility rule on top of the accepted evaluator.

## Interpretation

V2 answered a narrow architecture question: should every primary-card wager be required to have raw frozen football inference pointing in the same direction as the actionable wager before the unchanged selector ranking is applied?

The development evidence says **no**. The rule reduced coverage slightly, materially weakened High Hit Rate, did not improve Balanced or Value, and suppressed the favorable V1 spread-selection behavior. The gate therefore fails its intended role as a universal primary-card prerequisite.

No disagreement-magnitude threshold, alternative zero, market-specific threshold, price bucket, ROI bucket, or special-case historical rule will be searched. V2 is closed as a valid but rejected experiment.

## Architecture consequence

The next selector architecture must be derived from **upstream capability status that was locked before selector V1/V2 evidence**, not from searching these outcomes:

- **Moneyline V4:** accepted as a fair-value probability base; universal full-board ML Value edge was not demonstrated.
- **Spread V3:** accepted/frozen probability and valuation architecture; previously frozen spread edge was preserved and materially enriched.
- **Totals V3:** probability base accepted, but `TOTALS_VALUE_WEAK_NO_DEMONSTRATED_EDGE` remains in force and LOW reliability already keeps totals out of primary cards.

Therefore the next product-policy design may distinguish **probability capability** from **demonstrated Value capability**. Any such policy must be separately preregistered and must not reuse V1/V2 ROI as an input. Because V1 and V2 selector outcomes have now been observed, 2020–2024 can no longer serve as clean acceptance evidence for a newly designed selector version. A future selector architecture should be independently reviewed before sealed 2025 is considered as true holdout evidence.
