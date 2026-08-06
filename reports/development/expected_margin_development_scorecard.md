# Expected-Margin v1 Development Scorecard (EXPECTED_MARGIN_V1_IMPLEMENTED_BUT_WEAK)

Selected candidate: **stable** · model version `expected_margin_v1.0.0`
Development period 2018-2024 · sealed holdout 2025 · 2026+ rejected.

## Aggregate (selected, official scored rows)
- Official scored rows: 1593 (prob-available 1597; warm-up 78; total prediction rows 1942)
- Brier: **0.238291**
- Log loss: **0.669988**
- Accuracy: **0.601381**
- Calibration intercept: **0.0448**
- Calibration slope: **0.7962**
- Margin MAE: 10.6929 · RMSE: 13.8145 · mean signed: 0.4871

## Common-row QB-Elo comparison
- Common rows: 1593
- Expected-Margin Brier 0.238291 vs QB-Elo 0.222809
- **Brier Skill Score: -0.069483** (1 - EM/QB)
- Log loss EM 0.669988 vs QB 0.637340 (diff +0.032648)
- Accuracy EM 0.601381 vs QB 0.637790
- Calibration EM (0.0448, 0.7962) vs QB (-0.0929, 0.9487)

## Bootstrap (week-block, seed 20260802, N=1000)
- Selected Brier CI: [0.23209, 0.24426]
- Brier Skill Score CI: [-0.09606, -0.04467]
- Log-loss-difference CI: [0.02046, 0.04565]
- Win proportion (EM Brier < QB-Elo): 0.0
- Win proportion (EM log loss < QB-Elo): 0.0

**Expected-Margin v1 is weaker than QB-Elo as a win-probability model.**

## Reliability table
See `expected_margin_reliability_table.csv` (fixed buckets [0,0.2)...[0.8,1.0)).
