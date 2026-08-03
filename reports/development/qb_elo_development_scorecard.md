# QB-Elo Development Scorecard

- **Model:** qb_elo v1.0.0
- **Run ID:** qb_elo-v1.0.0-20260803T120000Z
- **Development seasons:** 2018-2024
- **Sealed holdout season:** 2025 (not scored)

## Totals

- Predicted games: 1942
- Scored games: 1935
- Ties: 7
- Unscored / warm-up: 7

## Aggregate Metrics

- Brier score: 0.2254
- Log loss: 0.6429
- Descriptive accuracy: 0.6305
- Calibration intercept: 0.4833
- Calibration slope: 0.2143

## Results by Season

| Season | Predicted | Scored | Ties | Accuracy | Log loss | Brier |
| --- | --- | --- | --- | --- | --- | --- |
| 2018 | 267 | 265 | 2 | 0.6264 | 0.6478 | 0.2282 |
| 2019 | 267 | 266 | 1 | 0.6353 | 0.6413 | 0.2243 |
| 2020 | 269 | 268 | 1 | 0.6530 | 0.6311 | 0.2194 |
| 2021 | 285 | 284 | 1 | 0.6092 | 0.6565 | 0.2308 |
| 2022 | 284 | 282 | 2 | 0.6064 | 0.6445 | 0.2268 |
| 2023 | 285 | 285 | 0 | 0.6070 | 0.6627 | 0.2343 |
| 2024 | 285 | 285 | 0 | 0.6772 | 0.6163 | 0.2136 |

## Results by QB Certainty

| Certainty | Predicted | Scored | Accuracy | Log loss | Brier |
| --- | --- | --- | --- | --- | --- |
| UNKNOWN | 1942 | 1935 | 0.6305 | 0.6429 | 0.2254 |

## Reliability Table

| Bucket | Count | Mean Predicted | Actual Home-Win Rate |
| --- | --- | --- | --- |
| 0.10–0.20 | 22 | 0.1655 | 0.3182 |
| 0.20–0.30 | 76 | 0.2633 | 0.3026 |
| 0.30–0.40 | 210 | 0.3561 | 0.3238 |
| 0.40–0.50 | 321 | 0.4536 | 0.4174 |
| 0.50–0.60 | 478 | 0.5513 | 0.5000 |
| 0.60–0.70 | 426 | 0.6463 | 0.6385 |
| 0.70–0.80 | 306 | 0.7477 | 0.7745 |
| 0.80–0.90 | 86 | 0.8420 | 0.7674 |
| 0.90–1.01 | 10 | 0.9091 | 0.9000 |

## Missingness

- home_elo_before: 0 nulls
- away_elo_before: 0 nulls
- home_field_adjustment: 0 nulls
- home_qb_adjustment: 0 nulls
- away_qb_adjustment: 0 nulls
- predicted_home_win_probability: 0 nulls

## Worst Log-Loss Predictions

| Game | Season | Week | Home | Away | Pred P(home) | Home Win | Log Loss |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2020_15_NYJ_LA | 2020 | 15 | LAR | NYJ | 0.9055 | False | 2.3587 |
| 2021_11_HOU_TEN | 2021 | 11 | TEN | HOU | 0.8994 | False | 2.2966 |
| 2021_18_IND_JAX | 2021 | 18 | JAX | IND | 0.1142 | True | 2.1695 |
| 2020_17_LAC_KC | 2020 | 17 | KC | LAC | 0.8840 | False | 2.1545 |
| 2021_18_GB_DET | 2021 | 18 | DET | GB | 0.1166 | True | 2.1488 |
| 2024_18_BUF_NE | 2024 | 18 | NE | BUF | 0.1295 | True | 2.0438 |
| 2023_17_ARI_PHI | 2023 | 17 | PHI | ARI | 0.8683 | False | 2.0272 |
| 2021_09_BUF_JAX | 2021 | 9 | JAX | BUF | 0.1330 | True | 2.0174 |
| 2019_16_ARI_SEA | 2019 | 16 | SEA | ARI | 0.8643 | False | 1.9974 |
| 2019_10_ATL_NO | 2019 | 10 | NO | ATL | 0.8633 | False | 1.9902 |

## Configuration

```json
{
  "home_field_elo": 48.0,
  "initial_rating": 1500.0,
  "k_factor_postseason": 4.0,
  "k_factor_regular": 20.0,
  "margin_of_victory": {
    "cap": 2.5,
    "divisor": 6.0
  },
  "probability": {
    "max": 0.99,
    "min": 0.01
  },
  "qb_adjustment": {
    "max_abs_elo": 50.0,
    "replacement_passing_epa": -0.05,
    "sample_k": 250.0,
    "scale_elo_per_shrunk_epa": 500.0,
    "supported_uses_replacement_scenario": true,
    "unknown_returns_zero": true
  },
  "season_mean_reversion_fraction": 0.333
}
```

## Manifest Fingerprint

- model_config_sha256: `d37661befee7fa0e00b71337890b9bf2b2a3740b0f1a7103ed3776fbabd00d7a`
- backtest_config_sha256: `2f1727a45f205ef491cd1800d93bdb10d948b3dbcb932e93d11694ba3d086275`
- model_code_fingerprint: `65594378c090191bdbb508eecdc569be620dbb8eb8c9f7625e2b20818f77f198`

_No 2025 predictions, scores, or calibration included._
