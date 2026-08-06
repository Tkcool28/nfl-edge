# Expected-Margin v1 Development Scorecard (EXPECTED_MARGIN_V1_IMPLEMENTED_BUT_WEAK)

Selected candidate: **stable** · model version `expected_margin_v1.0.0`
Development period 2018-2024 · sealed holdout 2025 · 2026+ rejected.

## Aggregate (stable, official scored rows)
- Official scored rows: 1593 (warm-up rows: 78; total prediction rows: 1942)
- Brier: **0.248562053**
- Log loss: **0.6902788369**
- Accuracy: **0.541745135**
- Calibration intercept: **0.1233884866**
- Calibration slope: **0.3583380744**
- Margin MAE: **11.3820346541**
- Margin RMSE: **14.6789664528**
- Mean signed margin error: **0.0214422957**

## Common-row QB-Elo comparison (n = 1593)
- Expected-Margin Brier: 0.248562
- QB-Elo Brier: 0.222809
- Brier Skill Score: **-0.115582**
- Expected-Margin log loss: 0.690279
- QB-Elo log loss: 0.63734
- Log-loss difference (EM − QB): **+0.052939**
- Accuracy: EM 0.541745 vs QB-Elo 0.63779

## Bootstrap (week-block, seed 20260802, N=1000)
- Expected-Margin Brier CI: [0.24679, 0.25029]
- Brier Skill Score CI: [-0.15068, -0.08301]
- Log-loss difference CI: [0.03785, 0.06848]
- Win proportion (EM Brier < QB-Elo): 0.0
- Win proportion (EM log loss < QB-Elo): 0.0

**Expected-Margin v1 is weaker than QB-Elo as a win-probability model.**

## Reliability table
See `expected_margin_reliability_table.csv` (fixed buckets [0,0.2)…[0.8,1.0)).
