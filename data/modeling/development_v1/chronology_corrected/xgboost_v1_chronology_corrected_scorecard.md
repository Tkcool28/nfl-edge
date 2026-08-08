# XGBoost V1 chronology-corrected scorecard

**Status:** XGBOOST_V1_CONSERVATIVE_SELECTED_AFTER_CHRONOLOGY_CORRECTION

## Row accounting

| Total | Binary scored | Warm-up | Tie/non-binary | Fitted blocks | Warm-up blocks |
|---:|---:|---:|---:|---:|---:|
| 1,942 | 1,655 | 284 | 3 | 119 | 32 |

`1655 + 284 + 3 = 1942`

## Selected conservative

| Brier | Logloss | Accuracy | ROC-AUC | ECE |
|---:|---:|---:|---:|---:|
| 0.232639 | 0.657508 | 0.607855 | 0.649541 | 0.026433 |

## QB-Elo exact-common-row comparison

| Rows | QB-Elo Brier | QB-Elo Logloss | QB-Elo Accuracy | QB-Elo AUC |
|---:|---:|---:|---:|---:|
| 1655 | 0.222823 | 0.637241 | 0.636858 | 0.688594 |

QB-Elo remains stronger standalone. ECE and reliability tables are primary calibration evidence; no post-hoc calibration was applied.

## Season metrics

| Season | Rows | Brier | Logloss | Accuracy | AUC |
|---:|---:|---:|---:|---:|
| 2018 | 197 | 0.241447 | 0.675625 | 0.598985 | 0.556673 |
| 2019 | 228 | 0.245653 | 0.685317 | 0.521930 | 0.602691 |
| 2020 | 233 | 0.229706 | 0.652100 | 0.630901 | 0.681158 |
| 2021 | 249 | 0.229457 | 0.652689 | 0.614458 | 0.682773 |
| 2022 | 248 | 0.227821 | 0.646618 | 0.620968 | 0.657089 |
| 2023 | 250 | 0.234721 | 0.660954 | 0.612000 | 0.610742 |
| 2024 | 250 | 0.222430 | 0.635065 | 0.648000 | 0.690241 |

## Time slices

| Slice | Rows | Brier | Logloss | Accuracy | AUC |
|---|---:|---:|---:|---:|---:|
| early_weeks_1_4 | 189 | 0.241664 | 0.677646 | 0.571429 | 0.647640 |
| middle_weeks_5_9 | 503 | 0.235557 | 0.663088 | 0.604374 | 0.636441 |
| late_weeks_10_plus | 963 | 0.229343 | 0.650640 | 0.616822 | 0.656566 |
| postseason | 58 | 0.227244 | 0.645007 | 0.620690 | 0.616162 |
