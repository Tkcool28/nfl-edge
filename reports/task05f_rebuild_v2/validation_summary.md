# Task05F Evaluator Rebuild V2 — Validation Evidence

Status: **VALID EXECUTION / NO V2 CANDIDATE PROMOTED**

This report preserves the second complete GitHub Actions evaluation of the clean Task05F evaluator rebuild. V2 was preregistered before V2 outcome scoring in `config/task05f_evaluator_rebuild_v2_prereg.yaml` and remained evaluator-only. Frozen QB-Elo, XGBoost, Expected Margin V1, Ridge R4, Task05E candidate definitions, and sealed 2025 outcomes were not modified or used as tuning targets.

## Reproducibility

- Feature head at review: `2557083326ec8628c03743498809a8802a363777`
- PR merge ref executed by Actions: `1fb6d95a3ddec6c7329111e699bd711b4d59b61d`
- Workflow run: `32544589470`
- Artifact ID: `9468143309`
- Artifact ZIP digest: `sha256:58fd016416c88f7f44edf78c2187d007a6eb3d1856bde014155f4bf6d6a0840c`
- V2 preregistration SHA-256: `cae2efd388d4fa8c468e94cba89d0aed82c76356f5094c885d938657825eec3d`
- Evaluator-only scope guard: PASS
- 2025 firewall: PASS
- Two complete chronological 2020-2024 V2 runs: PASS
- Deterministic JSON/CSV/NDJSON and logical parquet comparison: PASS
- `full_board.parquet` SHA-256, both runs: `fb32a68213fae36ba2794e66ba1f69c8a578b5e2afbcdd0eb940b8fb209918ab`
- `scorecard.json` SHA-256, both runs: `ba8e8b6c2ae342a44414cf2d9d98a981f5bb0cea18b6ea14ec42e6f349e937c8`
- `frozen_edge_preservation.json` SHA-256, both runs: `c2d23e524d49b7e5d33918bdcb6c9389e9f3bd028325effc724ee361650e6f31`
- `ev_calibration.csv` SHA-256, both runs: `c34218d30bbd860b379a3f00d36097c3bac00861b9f52335a6705ec5d607f7f3`
- `calibration_state_by_block.ndjson` SHA-256, both runs: `052443cfed543663aeabf734f336b96b94f37ab98a9af7aa56860bf713a29093`

## Moneyline — exact AVG monotone logit calibration

Preregistered formula: fit one prior-only logistic calibration of home win on `logit(exact_avg)` with positive-slope fail-closed behavior. Pinnacle remains benchmark/support evidence and does not enter the V2 probability formula.

- Supported: 2,202 / 2,816
- Positive predicted EV: 963, realized ROI **-7.90%**
- Nonpositive EV: 1,239, realized ROI **-2.26%**
- Conditional non-push Brier: **0.22003**
- Conditional non-push AUC: **0.70375**
- Raw exact-AVG benchmark Brier: **0.22059**
- Raw exact-AVG benchmark AUC: **0.69901**
- Pinnacle no-vig Brier: **0.20694**
- Pinnacle no-vig AUC: **0.74038**
- Fixed >10% predicted-EV band: 626 wagers, realized ROI **-7.57%**
- Supported calibration slope blocks: 98
- Calibration slope range: about **1.076 to 1.336**; median about **1.167**; final about **1.182**

The calibrator improves proper scoring versus raw exact AVG only slightly and does not repair full-board wagering discrimination. It is not promoted.

### Frozen external ML evidence

These are previously frozen Task05E regions and are external validation only:

- `ML_DOG_VALUE_ZONE_AVG`: baseline 232 at **+5.10%**; supported 207; V2 +EV kept 167 at **+5.16%**; nonpositive rejected 40 at **-22.17%**.
- `ML_CORROBORATED_DOG_VALUE_ZONE`: baseline 140 at **+4.53%**; supported 122; V2 +EV kept 110 at **+3.12%**; nonpositive rejected 12 at **-61.50%**.
- `ML_AVG_0_2`: baseline 216 at **-3.71%**; supported 198; V2 +EV kept 99 at **-8.19%**; rejected 99 at **-7.08%**.

The first two frozen dog-zone checks show that useful model/market disagreement evidence still exists inside previously locked regions. That does **not** authorize a new region search or a region-specific V2 calibration. Full-board V2 remains unacceptable.

## Spread — Pinnacle line anchor + Expected Margin global slope

Preregistered formula: `market_home_margin = -Pinnacle_home_line`, fit `beta = clip(sum(d*y)/sum(d^2), 0, 1)` globally on prior games where `d = ExpectedMargin - market_home_margin`, then evaluate exact actionable wagers with the prior-only empirical residual distribution and explicit push economics.

- Supported: 2,548 / 2,816
- Positive predicted EV: 359, realized ROI **-8.64%**
- Nonpositive EV: 2,189, realized ROI **-2.97%**
- Conditional non-push Brier: **0.25060**
- Conditional non-push AUC: **0.49710**
- Incumbent calibrated-normal Brier: **0.25028**
- Supported calibration blocks: 100
- `beta` median about **0.0019**
- 49 / 100 supported blocks clip to exactly **0.0**
- Final `beta = 0.0` (`beta_raw ≈ -0.051`)

V2 fixes V1's poor global probability quality, but the globally fitted linear mean-shift says Expected Margin contributes almost no average incremental mean information beyond the Pinnacle line. That is a global result only; it does not erase previously frozen external evidence.

Frozen `SPREAD_0_4_DISCOVERY_UNION`:

- Corrected baseline: 800 wagers, **+5.538% ROI**
- Exact-offer joined: 799; one exact offer missing
- Supported: 722, **+5.80% ROI**
- +EV kept: 132, **+0.81% ROI**
- Nonpositive rejected: 590, **+6.92% ROI**

This fails the preregistered frozen-edge preservation requirement. V2 is not promoted.

## Totals — Pinnacle line anchor + R4 global slope

- Supported: 2,542 / 2,816
- Positive predicted EV: 569, realized ROI **-4.02%**
- Nonpositive EV: 1,973, realized ROI **-3.63%**
- Conditional non-push Brier: **0.25078**
- Conditional non-push AUC: **0.49965**
- Incumbent calibrated-normal Brier: **0.25084**
- Supported calibration blocks: 100
- `beta` median about **0.138**; final about **0.154**

V2 totals is approximately as well calibrated as the incumbent but does not show full-board positive-EV discrimination. Verdict remains **WEAK / NO DEMONSTRATED VALUE EDGE**.

### New totals observation — sealed for future checking only

The preregistered fixed diagnostic EV bands happened to produce:

- 0-2% predicted EV: n=252, realized ROI **-11.68%**
- 2-5%: n=211, **+0.77%**
- 5-10%: n=92, **+3.80%**
- >10%: n=14, **+10.20%**

This pattern was observed **after** V2 was locked and scored. It is therefore labeled `OBSERVATIONAL_ONLY_NOT_TUNED`. It must not create a 2% cutoff, alter Task05F, or change current selector semantics. If V2 itself is ever evaluated unchanged on sealed 2025, this exact predeclared observation may be checked there as new evidence.

## Integrity decision

- ML V2: **NOT ACCEPTABLE** for the full board.
- Spread V2: **NOT ACCEPTABLE**; frozen edge remains concentrated in rejected wagers.
- Totals V2: **WEAK / NO EDGE**.
- No production probability family is promoted.
- No retrospective price, ROI, disagreement, or market bucket was searched.
- No Play Through formula is fitted yet. Play Through remains downstream and deferred until the core probability architecture is acceptable.
