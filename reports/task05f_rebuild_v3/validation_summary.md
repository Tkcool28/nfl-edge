# Task05F Evaluator Rebuild V3 — Validation Evidence

Status: **VALID EXECUTION / SPREAD ARCHITECTURE ACCEPTED / TOTALS PROBABILITY BASE ACCEPTED-WEAK / ML NOT ACCEPTED**

V3 was preregistered before outcome scoring in `config/task05f_evaluator_rebuild_v3_prereg.yaml`. It remained strictly evaluator-only. Frozen QB-Elo, XGBoost, Expected Margin V1, Ridge R4, Task05E definitions/evidence, and sealed 2025 outcomes were not modified or used as tuning targets.

## Reproducibility

- Feature head executed: `f711a7cb1fe48bb13d9fa6b2e44fd167600c3154`
- GitHub Actions run: `32545272084`
- Artifact ID: `9468356083`
- Artifact ZIP digest: `sha256:9ce4e50872abec58be3a2106a9e61fa32baf89eee43896ef7b201e29ba7d6dea`
- V3 preregistration SHA-256: `ad83ef686a22976e09c18c540d0db23dccb96399c3e573af28dc06bbb5e9eb6e`
- Value-layer tests before V3 scoring: 79 passed
- Evaluator-only scope guard: PASS
- 2025 firewall: PASS
- Two complete chronological 2020-2024 V3 runs: PASS
- Deterministic JSON/CSV/NDJSON and logical parquet comparison: PASS
- `full_board.parquet` SHA-256, both runs: `54f95cfd8af374ebb09f4701e4593a04e2efa3b8ce6f5422ed64c95dc1f70192`
- `scorecard.json` SHA-256, both runs: `484bd8cff5125608abcc6dbbb62e6f5dda2b0c326a203bcd7255655886c26886`
- `frozen_edge_preservation.json` SHA-256, both runs: `0896f02f4b93d8a1d6a962d1fe9fc4479f18eeaccb1da5a658a474db7621205a`
- `ev_calibration.csv` SHA-256, both runs: `5e9e6a80583eea25f630f6c62c3da457e52db8b8073331c4ad43186f87527fe1`
- `calibration_state_by_block.ndjson` SHA-256, both runs: `48f2174e3126c7b3fae141047345332642b8f1973b7cbe1268373ae501e7746b`

## Moneyline — Pinnacle + exact AVG bounded logit pool

Preregistered V3 fits a prior-only proper-scoring weight `w` in `[0,1]`:

`logit(p) = logit(p_pinnacle) + w * (logit(p_exact_avg) - logit(p_pinnacle))`

Results:

- Supported: 2,202 / 2,816
- Fitted model weight: **0.0 in every one of 98 supported calibration blocks**
- Candidate conditional non-push Brier: **0.20694**, exactly the Pinnacle benchmark
- Candidate AUC: **0.74038**, effectively the Pinnacle benchmark
- Positive predicted EV: 197, realized ROI **-41.35%**
- Nonpositive EV: 2,005, realized ROI **-1.13%**
- Fixed +EV bands are severely anti-monotone; >10% predicted EV is 9 wagers at **-62.78%**

This reproduces the original Task05F pathology under a cleaner architecture: global proper scoring says the frozen exact-AVG model adds no incremental full-board probability information to raw Pinnacle, while treating raw Pinnacle no-vig probability as perfectly fair creates catastrophic apparent DK/FD +EV.

Frozen external ML evidence:

- `ML_DOG_VALUE_ZONE_AVG`: +EV kept 12 at **+24.75%**, rejected 195 at **-1.65%**.
- `ML_CORROBORATED_DOG_VALUE_ZONE`: +EV kept 5 at **+5.00%**, rejected 117 at **-3.59%**.
- `ML_AVG_0_2`: +EV kept 21 at **-31.14%**, rejected 177 at **-4.84%**.

The first two frozen dog zones still contain previously locked evidence, but V3 ML is not a usable full-board value evaluator. **ML V3 is not accepted.**

## Spread — price-aware Pinnacle anchor + Expected Margin slope

V3 corrects a V2 omission: Pinnacle **price** now affects the market-implied mean instead of treating every identical line as a 50/50 belief. The frozen Expected Margin output can contribute through one prior-only bounded global slope; no bucket or ROI feature enters the fit.

- Supported: 2,548 / 2,816
- Conditional non-push Brier: **0.25056**
- Incumbent calibrated-normal Brier: **0.25028**
- Candidate AUC: **0.49569**
- Positive predicted EV: 385, realized ROI **-1.54%**
- Nonpositive EV: 2,163, realized ROI **-4.16%**
- Market scale final/typical: about **11.86 points**
- Global Expected Margin beta is small and often zero; final beta **0.0**

Frozen `SPREAD_0_4_DISCOVERY_UNION`:

- Baseline: 800 wagers, **+5.538% ROI**
- Exact-offer joined: 799
- Supported: 722, **+5.80% ROI**
- V3 +EV kept: 141, **+12.78% ROI**
- V3 nonpositive rejected: 581, **+4.11% ROI**

Kept subset by season:

- 2020: n=27, **-3.39%**
- 2021: n=51, **+4.86%**
- 2022: n=20, **+44.35%**
- 2023: n=19, **+5.74%**
- 2024: n=24, **+27.06%**

Rejected subset by season:

- 2020: **+11.99%**
- 2021: **+4.16%**
- 2022: **+16.35%**
- 2023: **-10.03%**
- 2024: **+3.90%**

This meets the preregistered V3 spread acceptance dimensions: probability quality remains competitive with incumbent, full-board +EV is directionally better than nonpositive, and the previously frozen spread edge is materially enriched rather than suppressed. The architecture does not claim every full-board +EV wager is profitable; it supplies a valid downstream valuation layer for football-model signals.

**Decision: freeze the V3 spread probability/valuation architecture. No further Task05F spread redesign unless an independent code/evidence review finds a defect.**

## Totals — price-aware Pinnacle anchor + R4 slope

- Supported: 2,542 / 2,816
- Conditional non-push Brier: **0.25046**
- Incumbent calibrated-normal Brier: **0.25084**
- AUC: **0.51007**
- Positive predicted EV: 544, realized ROI **-1.04%**
- Nonpositive EV: 1,998, realized ROI **-4.45%**
- Final global R4 beta: about **0.159**
- Final robust market scale: about **12.60 points**

V3 materially improves the structural probability base and provides directional discrimination, but the positive-EV population is still slightly negative overall. Therefore:

**Decision: freeze the V3 totals probability/valuation architecture, but retain `TOTALS_VALUE_WEAK_NO_DEMONSTRATED_EDGE`. Do not invent an EV cutoff.**

The V2 post-hoc totals fixed-band observation did not persist monotonically under V3, reinforcing why it was not used for tuning. It remains only a V2-specific sealed-2025 observation if V2 is ever evaluated unchanged.

## Next scope

Spread and totals are frozen at V3 pending independent review. The next evaluator iteration is **ML-only**.

The ML problem is now isolated: proper scoring assigns zero incremental weight to exact AVG globally, while raw Pinnacle no-vig probabilities produce severely miscalibrated apparent DK/FD +EV. The next ML-only candidate may calibrate Pinnacle's no-vig probability itself using prior outcomes before any optional frozen-model pooling. It may not use ROI, price buckets, dog/favorite buckets, frozen Task05E membership, or sealed 2025 outcomes.

Play Through remains preserved as a global downstream product contract and is still deferred until the core ML probability/valuation layer is resolved.
