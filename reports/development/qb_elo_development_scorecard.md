# QB-Elo Development Scorecard

- **Model:** qb_elo v1.0.0
- **Run ID:** None
- **Development seasons:** 2018-2024
- **Sealed holdout season:** 2025 (not scored)

## Totals

- Predicted games: 1942
- Binary-scored games: 1935
- Ties (excluded from binary metrics): 7
- Target-unavailable games: 0
- Warm-up excluded games: 0

## Aggregate Metrics

- Brier score: 0.2240
- Log loss: 0.6397
- Descriptive accuracy: 0.6351
- Calibration intercept: -0.0816
- Calibration slope: 0.9670

## Results by Season

| Season | Predicted | Binary-Scored | Ties | Accuracy | Log loss | Brier |
| --- | --- | --- | --- | --- | --- | --- |
| 2018 | 267 | 265 | 2 | 0.6226 | 0.6454 | 0.2272 |
| 2019 | 267 | 266 | 1 | 0.6429 | 0.6404 | 0.2238 |
| 2020 | 269 | 268 | 1 | 0.6567 | 0.6240 | 0.2162 |
| 2021 | 285 | 284 | 1 | 0.6197 | 0.6557 | 0.2309 |
| 2022 | 284 | 282 | 2 | 0.6277 | 0.6379 | 0.2239 |
| 2023 | 285 | 285 | 0 | 0.6035 | 0.6613 | 0.2336 |
| 2024 | 285 | 285 | 0 | 0.6737 | 0.6126 | 0.2120 |

## Results by QB Certainty

| Certainty | Predicted | Scored | Accuracy | Log loss | Brier |
| --- | --- | --- | --- | --- | --- |
| UNKNOWN | 1942 | 1935 | 0.6351 | 0.6397 | 0.2240 |

## Reliability Table

| Bucket | Count | Mean Predicted | Actual Home-Win Rate |
| --- | --- | --- | --- |
| 0.00–0.10 | 0 | n/a | n/a |
| 0.10–0.20 | 20 | 0.1599 | 0.3000 |
| 0.20–0.30 | 87 | 0.2611 | 0.3218 |
| 0.30–0.40 | 211 | 0.3561 | 0.2986 |
| 0.40–0.50 | 326 | 0.4528 | 0.4233 |
| 0.50–0.60 | 460 | 0.5536 | 0.5217 |
| 0.60–0.70 | 428 | 0.6477 | 0.6262 |
| 0.70–0.80 | 280 | 0.7482 | 0.7643 |
| 0.80–0.90 | 112 | 0.8363 | 0.7857 |
| 0.90–1.00 | 11 | 0.9086 | 0.9091 |

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
| 2020_15_NYJ_LA | 2020 | 15 | LAR | NYJ | 0.9050 | False | 2.3537 |
| 2020_17_LAC_KC | 2020 | 17 | KC | LAC | 0.8949 | False | 2.2528 |
| 2024_18_BUF_NE | 2024 | 18 | NE | BUF | 0.1091 | True | 2.2159 |
| 2021_11_HOU_TEN | 2021 | 11 | TEN | HOU | 0.8840 | False | 2.1539 |
| 2021_18_GB_DET | 2021 | 18 | DET | GB | 0.1168 | True | 2.1472 |
| 2019_17_MIA_NE | 2019 | 17 | NE | MIA | 0.8781 | False | 2.1049 |
| 2021_18_IND_JAX | 2021 | 18 | JAX | IND | 0.1259 | True | 2.0720 |
| 2023_17_ARI_PHI | 2023 | 17 | PHI | ARI | 0.8733 | False | 2.0660 |
| 2019_10_ATL_NO | 2019 | 10 | NO | ATL | 0.8705 | False | 2.0443 |
| 2021_09_BUF_JAX | 2021 | 9 | JAX | BUF | 0.1386 | True | 1.9758 |

## Configuration

```json
{
  "model_name": "qb_elo",
  "model_version": "v1.0.0"
}
```

## Manifest Fingerprint

- model_config_sha256: `None`
- backtest_config_sha256: `None`
- model_code_fingerprint: `None`
- feature_code_fingerprint: `None`
- backtest_code_fingerprint: `None`

_No 2025 predictions, scores, or calibration included._
