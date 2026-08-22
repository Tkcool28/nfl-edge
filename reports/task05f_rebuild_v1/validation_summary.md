# Task05F Evaluator Rebuild V1 — Validation Evidence

Status: **VALID EXECUTION / NO V1 CANDIDATE PROMOTED**

This report preserves the first complete GitHub Actions evaluation of the clean Task05F evaluator rebuild. It is an evaluator-only result. Frozen football models, Task05E candidate definitions, and sealed 2025 outcomes were not modified or used for tuning.

## Reproducibility

- Feature head executed: `56c7d4ff1ea46faeecfb7a8eb0571306a9d84776`
- PR merge ref executed by Actions: `10429c0c71ddbd2189bfad66649fce2a061684b8`
- Workflow run: `32544032079`
- Artifact ID: `9467988745`
- Artifact ZIP digest: `sha256:4bebd91e61f12ad033d03b233c44cea991029c4303673b5aeb80d3774c5afcbc`
- Value-layer tests: `58 passed`
- 2025 firewall: PASS
- Evaluator-only scope guard: PASS
- Two complete chronological 2020-2024 runs: PASS
- Deterministic JSON/CSV and logical parquet comparison: PASS
- `full_board.parquet` SHA-256, both runs: `a8eaa2ebe15d023d50a6355a9119973af287002eaa07c32dded9b8c2bad63643`
- `scorecard.json` SHA-256, both runs: `0863be0546b66bb5257e1baea11b706a1cf0ad65cf9d53168ad3a99f55223485`
- `frozen_edge_preservation.json` SHA-256, both runs: `2b67e405d60701a0d2d0889d90278ec5557b9a808e3dbd4bcbb4d3f90610ef0c`
- `ev_calibration.csv` SHA-256, both runs: `c89135405c12442f3517c4d4dbdddbe8e822b8f37d60d6a2d94e341f75a6945a`

## Market results

### Moneyline — exact AVG

- Supported: 2,202 / 2,816
- Positive predicted EV: 969, realized ROI **-6.49%**
- Nonpositive EV: 1,233, realized ROI **-3.33%**
- Conditional non-push Brier: **0.22059**
- Conditional non-push AUC: **0.6990**
- Pinnacle benchmark Brier: **0.20694**
- Pinnacle benchmark AUC: **0.7404**
- Fixed >10% predicted-EV band: 652 wagers, realized ROI **-9.23%**

Conclusion: raw exact-AVG probability is too poorly calibrated for direct full-board valuation. It fails full-board wagering discrimination and is not promoted.

Frozen external evidence remains mixed rather than being used as a tuning target:
- `ML_DOG_VALUE_ZONE_AVG`: exact joined 232; supported 207; +EV kept 178 at **+4.89%**, rejected 29 at **-30.90%**.
- `ML_CORROBORATED_DOG_VALUE_ZONE`: supported 122; +EV kept 118 at **-1.89%**, rejected 4 at **-43.0%**.
- `ML_AVG_0_2`: supported 198; +EV kept 70 at **-5.66%**, rejected 128 at **-8.71%**.

### Spread — empirical residual distribution

- Supported: 2,548 / 2,816
- Positive predicted EV: 1,165, realized ROI **-2.46%**
- Nonpositive EV: 1,383, realized ROI **-4.87%**
- Conditional non-push Brier: **0.27208**
- Conditional non-push AUC: **0.5000**
- Incumbent calibrated-normal benchmark Brier: **0.25028**

Frozen `SPREAD_0_4_DISCOVERY_UNION`:
- Corrected baseline: 800 wagers, **+5.538% ROI**
- Exact-offer joined: 799; one exact offer missing
- Supported: 722, **+5.80% ROI**
- +EV kept: 605, **+4.03% ROI**
- Nonpositive rejected: 117, **+15.00% ROI**

Conclusion: the exact-offer/push-aware architecture is sound, but the global empirical residual probability map does not rank the frozen spread evidence usefully and has materially worse probability quality than the incumbent. It is not promoted.

### Totals — empirical residual distribution

- Supported: 2,542 / 2,816
- Positive predicted EV: 1,094, realized ROI **-2.23%**
- Nonpositive EV: 1,448, realized ROI **-4.84%**
- Conditional non-push Brier: **0.25973**
- Conditional non-push AUC: **0.5047**
- Incumbent calibrated-normal benchmark Brier: **0.25084**

Conclusion: no demonstrated positive-value totals layer. Structural exact-line and push semantics are retained, but this probability family is not promoted as a value evaluator.

## Baseline correction

The frozen spread pooled baseline is **+5.538%**, not the earlier carried-forward approximation of ~+5.79%. The committed corrected Task05E summaries give discovery profit `+46.09` over 460 wagers and confirmation profit `-1.784` over 340 wagers, for `44.306 / 800 = 5.538%`. No Task05E evidence changed.

## Integrity decision

No V1 probability family is promoted to production. No new price/disagreement/ROI bucket was searched. The Actions `observations.json` remained `OBSERVATIONAL_ONLY_NOT_TUNED` with an empty items list.

The next evaluator iteration, if performed, must be preregistered before its outcome scoring and must remain a global calibration/valuation architecture change rather than football-model tuning or retrospective bucket discovery.
