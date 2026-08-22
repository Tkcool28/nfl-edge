# Task05F Reliability / Support Remediation — Validation

Branch: `feat/task05f-market-evaluator-v1`
Starting HEAD: `86db7bbaf0d745668261238eb425147984560b60`
Base (main): `7824f1de54d039874abf96b1f97ff135018b34cf`
Production `/root/nfl-edge`: `main @ 7824f1de54d039874abf96b1f97ff135018b34cf` (untouched)

This remediation makes the frozen reliability/support contract *real*: out-of-support
distance is computed (was hard-disabled at 0.0), chronological stability is evidenced
(was an unchanging `True`), and uncertainty is never silently 0 (`EvaluatorState.uncertainty`
default is now `None` and every fitted family receives its own real bootstrap radius).

## 1. Reliability tier formula

`tier(support_n, uncertainty, support_distance, constituent_disagreement, stable_blocks)`

1. **UNSUPPORTED** if `support_n < 128` (insufficient prior support) OR `support_distance > 0.10` (out of support).
2. **LOW** if history is unstable (`stable_blocks == False`) — capped, never HIGH/MEDIUM.
3. **HIGH** if `support_n >= 512` and `0 < uncertainty <= 0.025` and disagreement `<= 0.08` and stable.
4. **MEDIUM** if `support_n >= 256` and `0 < uncertainty <= 0.045` and disagreement `<= 0.15` and stable.
5. else **LOW**.

Note `0 < uncertainty` is required for HIGH/MEDIUM — an uncomputed/`None` uncertainty can
never masquerade as "perfect certainty".

## 2. Support-distance formula

For each required scalar feature with historical prior-block `[min, max]` and safe span `span = max(max-min, 1e-6)`:

```
distance_i = 0                                   if min <= value <= max
           = (min - value) / span                if value < min
           = (value - max) / span                if value > max
support_distance = max_i(distance_i)
```
Do-not-silently-change threshold: `MAX_OUT_OF_SUPPORT_DISTANCE = 0.10` (from frozen config).

## 3. Support features by market

| Market | Feature name | Meaning |
|---|---|---|
| moneyline | `pin` | selected-side Pinnacle no-vig probability |
| moneyline | `avg_pin_gap` | **signed** `exact_avg - Pinnacle` (direction of model disagreement is meaningful) |
| moneyline | `qb_xgb_gap` | **absolute** `|QB-Elo - XGBoost|` constituent disagreement |
| spread | `delta_magnitude` | **abs**(selected-side Expected-Margin advantage relative to line) — orientation-invariant |
| spread | `market_magnitude` | abs(spread line) |
| total | `delta_magnitude` | **abs**(predicted_total − total line) — orientation-invariant |
| total | `market_magnitude` | total-line level |

Side-mirror invariance (V1 consistency fix): spread `delta_magnitude = |delta|` and total
`delta_magnitude = |delta|` put the reflected side (away/under) in the same support space as
the canonical HOME/OVER orientation, so equivalent mirrored offers classify identically w.r.t.
delta support. This is **support-only**: the evaluator probability formulas continue to use the
selected-side **signed** delta (Normal-CDF / calibrated-Normal / strong-logistic unchanged).
Mirrored sides are never treated as extra training observations (one canonical orientation per
game).

## 4. Stability rule (explicit, single, pre-declared)

Prior-block stability evidence for each family:
- **stable** only if the family has `>= MIN_STABLE_BLOCKS = 4` distinct **prior** season-week blocks **and** its block-bootstrap 0.90-quantile calibration-gap radius `<= STABILITY_MAX_RADIUS = 0.05`.
- Cold-start (< 4 prior blocks) or a large recent calibration-gap radius → **unstable** → capped at **LOW** (fails closed; never HIGH/MEDIUM).
- Derived exclusively from PRIOR training blocks; current/future blocks never enter.

## 5. Uncertainty definition

`EvaluatorState.uncertainty` = chronological block-bootstrap calibration-gap radius
(0.90 quantile, seed `20260820`, 1000 replicates) of **that family's own probability**
over its PRIOR-block predictions. Computed for every family (Pinnacle, raw QB-Elo, raw
XGB, exact AVG, global shrink, reliability-aware shrink, strong logistic, spread/total
normal-CDF, calibrated-normal, strong-logistic). Default is `None` (unknown), never `0.0`.

## 6. Deterministic rerun hash proof

Two independent chronological runs into fresh output dirs produced byte-identical
`scorecard.json` and `provenance.json` (SHA-256 below).

## 7. Support counts / unsupported reasons / tier distribution

From the remediated full evaluation (2020–2024 expanding season-week OOS):

| Family | total | HIGH | MEDIUM | LOW | UNSUPPORTED | dominant unsupported reason |
|---|---|---|---|---|---|---|
| ML Pinnacle | 2816 | 44 | 936 | 1510 | 326 | out_of_support 109 / insuff. 217 |
| ML raw_qbelo | 2816 | 0 | 498 | 1992 | 326 | out_of_support 109 / insuff. 217 |
| ML raw_xgb | 2816 | 200 | 710 | 1294 | 612 | missing_xgb 350 / out 45 / insuff 217 |
| ML exact_avg | 2816 | 0 | 724 | 1480 | 612 | requires_both 350 / out 45 / insuff 217 |
| ML global_shrinkage | 2816 | 38 | 796 | 1370 | 612 | requires_both 350 / out 45 / insuff 217 |
| ML reliability_aware | 2816 | 86 | 748 | 1370 | 612 | requires_both 350 / out 45 / insuff 217 |
| ML strong_logistic | 2494 | 610 | 874 | 720 | 290 | requires_both 286 / out 4 |
| spread normal_cdf | 2760 | 122 | 1983 | 392 | 263 | out 42 / insuff 221 |
| spread calibrated_normal | 2501 | 881 | 1363 | 253 | 4 | out_of_support 4 |
| spread strong_logistic | 2501 | 935 | 1309 | 253 | 4 | out_of_support 4 |
| total normal_cdf | 2790 | 0 | 397 | 2122 | 271 | out 43 / insuff 228 |
| total calibrated_normal | 2526 | 580 | 1610 | 329 | 7 | out_of_support 7 |
| total strong_logistic | 2526 | 546 | 1612 | 361 | 7 | out_of_support 7 |

`missing_xgb`/`exact_avg_requires_both` rows were ALREADY UNSUPPORTED in the original
registration (no XGB probability because of XGB mapping warm-up), independent of this
remediation. The remediation adds genuine `out_of_support` fail-closures (e.g. 45 moneyline
global_shrinkage rows, 4 spread/total calibrated rows) that were previously passing through
as if in-support.

## 8. Selection (preregistered rule, unchanged)

- Moneyline: **global_shrinkage** (Brier ~0.2069; within simplicity tolerance of the
  near-tied reliability-aware).
- Spread: **calibrated_normal** (Brier ~0.2503).
- Totals: **calibrated_normal** (Brier ~0.2508).

Selection unchanged after remediation; rows that became properly UNSUPPORTED were a small
fraction and did not flip the winner.

## 9. Signal interpretation (K)

- **Moneyline** global_shrinkage: Brier ~0.2069, AUC ~0.740 — incremental discrimination
  over Pinnacle (Pinnacle Brier ~0.2106). This is a real improvement in probability quality.
- **Spread** calibrated_normal: Brier ~0.2503, **AUC ~0.492** — calibrated probability
  translation with **weak/no demonstrated global discrimination**. Not promoted as strong
  wagering signal; good calibration, not proven edge.
- **Totals** calibrated_normal: Brier ~0.2508, **AUC ~0.499** — same characterization:
  calibrated probability translation, no demonstrated global discrimination.

These three must not be conflated: (1) calibration quality is good for all three selected
families; (2) discrimination is only demonstrated for moneyline; (3) wagering usefulness
is not established for spread/totals.
