# Task05F ML V4 — Validation Evidence

Status: **VALID EXECUTION / ML FAIR-VALUE BASE ACCEPTED / UNIVERSAL FULL-BOARD ML VALUE EDGE NOT DEMONSTRATED**

ML V4 was preregistered before V4 outcome scoring in `config/task05f_ml_v4_prereg.yaml`. Spread and totals remained frozen at their V3 architectures. V4 changed only the downstream moneyline evaluator. Frozen QB-Elo, XGBoost, model outputs, Task05E definitions/evidence, and sealed 2025 outcomes were not modified or used for tuning.

## Reproducibility

- Feature head that triggered the ML V4 workflow: `d2891b1db801157cd0df0823720cd22f45a2d272`
- PR merge ref executed by Actions: `41cfc61f7168c8275c46158580719cf4a0b553dc`
- Workflow run: `32545786273`
- Artifact ID: `9468471788`
- Artifact ZIP digest: `sha256:47e0f6cc1612f3a754c465160db8ac7510c05f4c874471c2f0bc4575d50ae6cb`
- ML V4 preregistration SHA-256: `843ffdc5c13a030bd4a3eaf2f10f446d8abfb2901c8df859b2d4a2c277b31506`
- Evaluator-only scope guard: PASS
- Value-layer tests: PASS
- 2025 firewall: PASS
- Two complete chronological 2020-2024 ML V4 runs: PASS
- Deterministic JSON/CSV/NDJSON and logical parquet comparison: PASS
- `calibration_state_by_block.ndjson` SHA-256, both runs: `74c353fffb70eb000400c070f4811d6bfadb0ec488580d27d52870b3577474a6`
- `ev_calibration.csv` SHA-256, both runs: `aeb87a25c99e72a49ae6dda82d95bc4d66765cd3477ec4c30eb2d4b691879469`
- `frozen_ml_edge_preservation.json` SHA-256, both runs: `92eb74be366bd502ff8ede46bad7409e2b51c96da7d5c0ca3a8bb0a11c38334f`
- `full_board.parquet` SHA-256, both runs: `1b787a6117b4abc6870e809f0fe697a88e5f91f74c1aae3c55852e2633527926`
- `scorecard.json` SHA-256, both runs: `b1267386027f3dfcc7614f5fd46ddcd347aa7b4d0a90d0d37436735f3aaa2017`

## Candidate contract

V4 has two prior-only proper-scoring stages.

### Stage 1 — calibrate Pinnacle no-vig probability

`x = logit(p_pinnacle_no_vig)`

Fit a single monotone logistic calibration of home win on `x`, with intercept enabled and L2 `C=1.0`. A non-positive slope fails closed.

### Stage 2 — optional frozen-model contribution

`p_model = exact AVG(QB-Elo, XGBoost)`

`logit(p_final) = logit(p_market_cal) + w * (logit(p_model) - logit(p_market_cal))`

`w` is constrained to `[0,1]` and chosen only by prior binary log loss. DK/FD prices, ROI, dog/favorite status, historical buckets, and sealed 2025 outcomes are forbidden fit inputs.

## Proper scoring / fitted-state behavior

On the 2,198 non-tie scored rows:

- Raw Pinnacle no-vig: Brier **0.2069417**, log loss **0.6013285**, AUC **0.7403854**
- Calibrated Pinnacle: Brier **0.2068512**, log loss **0.6025166**, AUC **0.7418505**
- Final V4 candidate: conditional non-push Brier **0.2068471**, log loss **0.6024810**, AUC **0.7418662**
- Raw exact AVG: Brier **0.2205924**, log loss **0.6314573**, AUC **0.6990089**

The market calibration materially preserves Pinnacle's proper-scoring strength and slightly improves Brier/AUC, while log loss is slightly worse. It does not reverse market ordering.

Across the 98 supported calibration blocks:

- Market-calibration slope is positive throughout, roughly **0.958 to 1.210**, median about **1.056**, final about **1.113**.
- Market intercept is modestly negative, median about **-0.123**, final about **-0.057**.
- Exact-AVG model-pool weight is **0 in 91/98 supported blocks**.
- The only nonzero weights occur briefly in 2021 and are very small; maximum about **0.0351**.
- Final model-pool weight is **0.0**.

Thus the historical full-board proper-scoring evidence does not justify forcing exact AVG into the universal fair-value probability. The raw football-model probability/disagreement remains emitted separately and is not erased.

## Full-board wagering discrimination

- Supported: **2,202 / 2,816**
- Positive predicted EV: **754**, realized ROI **-4.756%**
- Nonpositive EV: **1,448**, realized ROI **-4.707%**

This is an enormous repair versus V3/raw-Pinnacle valuation, where the apparent +EV set was 197 wagers at about **-41.35% ROI**. V4 removes that catastrophic anti-informative false-edge concentration.

However, V4 does **not** demonstrate a universal full-board ML betting edge: positive and nonpositive populations perform essentially the same. Therefore the final status is not `ML_FULL_BOARD_VALUE_EDGE_PROVEN`.

Fixed diagnostic EV bands:

- `<=0%`: n=1,448, ROI **-4.71%**
- `0-2%`: n=206, ROI **+0.76%**
- `2-5%`: n=197, ROI **-5.71%**
- `5-10%`: n=227, ROI **-0.14%**
- `>10%`: n=124, ROI **-20.87%**

These fixed bands are diagnostic only. No EV cutoff is created from them and no band is fed back into Task05F.

## Frozen external ML evidence

These regions were frozen before the evaluator rebuild and are external validation only.

### `ML_DOG_VALUE_ZONE_AVG`

- Baseline: 232 wagers, **+5.10% ROI**
- Exact-offer joined: 232
- Supported: 207
- V4 +EV kept: 76, **+16.87% ROI**
- V4 nonpositive rejected: 131, **-9.98% ROI**

### `ML_CORROBORATED_DOG_VALUE_ZONE`

- Baseline: 140 wagers, **+4.53% ROI**
- Exact-offer joined: 140
- Supported: 122
- V4 +EV kept: 45, **+12.33% ROI**
- V4 nonpositive rejected: 77, **-12.34% ROI**

### `ML_AVG_0_2`

- Baseline: 216 wagers, **-3.71% ROI**
- Supported: 198
- V4 +EV kept: 72, **-21.34% ROI**
- V4 nonpositive rejected: 126, **+0.20% ROI**

The two previously frozen dog-zone signals are strongly enriched by the V4 fair-value layer; the already-weak `ML_AVG_0_2` signal remains weak and is not rescued. This evidence was not used to fit V4 and does not authorize a new bucket search.

## Decision

### Accepted as evaluator infrastructure

**ML V4 is frozen as the Task05F moneyline fair-value probability base.**

It successfully:

1. calibrates Pinnacle without sportsbook-actionable prices entering the fit;
2. removes the catastrophic raw-Pinnacle false +EV concentration;
3. preserves exact-offer valuation semantics;
4. keeps the raw frozen football signal separately available;
5. strongly enriches the two previously locked dog-zone external signals;
6. remains deterministic, chronological, and sealed from 2025.

### Not claimed

- No universal full-board ML +EV betting population is proven.
- Exact AVG is not promoted as a universal probability correction.
- No odds/dog/favorite/disagreement/EV bucket is created.
- No new model feature, model parameter, or model training rule is changed.

The correct product interpretation is to keep **fair-value probability** and **football-model signal** as separate downstream axes. Later selectors may use the frozen football inference/reliability plus fair price, but `VALUE` remains strict current-offer `EV > 0`.

## Core Task05F probability architecture after V4

- **Moneyline:** V4 calibrated Pinnacle fair-value base; frozen exact-AVG/model disagreement retained separately. Full-board Value status: **WEAK / NO UNIVERSAL EDGE PROVEN**.
- **Spread:** V3 price-aware Pinnacle line+price anchor with exact-offer push-aware valuation. **ACCEPTED/FROZEN**.
- **Totals:** V3 price-aware Pinnacle line+price anchor with R4 contribution. Probability base **ACCEPTED/FROZEN**; betting status **TOTALS_VALUE_WEAK_NO_DEMONSTRATED_EDGE**.

The next Task05F phase is consolidation of these accepted per-market probability/valuation contracts, followed by a separately preregistered **global Play Through** layer. Play Through must remain distinct from `VALUE` and may not be outcome-tuned to force a play.
