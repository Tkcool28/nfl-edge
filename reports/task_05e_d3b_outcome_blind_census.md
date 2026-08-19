# Task 05E-D3B-R1 — Outcome-Blind Edge Census (REPAIRED) + Product-Alignment Audit

Status: **EDGE_OUTCOME_BLIND_CENSUS_REPAIRED (OUTCOME-BLIND)**

This repairs the single existing outcome-blind census. It does not create a new
research program, change the fundamental questions, or inspect outcomes. **No
realized hit rate, ROI, profit, winner, ATS result, or totals result was
computed or reported anywhere here.**

Product families kept: **HIGH CONFIDENCE · BALANCED · NORMAL +EV · optional
BIG OPPORTUNITY.**

## Product questions (unchanged)
- **NORMAL +EV:** broad, understandable zone for a casual value bet without
  extreme risk?
- **BIG OPPORTUNITY:** do large model-vs-market disagreements occur often enough
  to test as a separate higher-risk signal?
- **MODEL COMPLEMENTARITY:** do QB-Elo / XGBoost disagree enough to later justify
  investigating stacking? (Complementarity is NOT proof stacking works.)

## Row-concept distinction (fixed)
- **TWO_SIDED_ABSOLUTE_DIAGNOSTIC** — all (game × side × model) rows; |edge_pp|.
  This is a distribution diagnostic only, **not** a count of betting opportunities.
- **POSITIVE_EDGE_CANDIDATE** — product row, one per (game, model), the side where
  `edge_pp_prim > 0` (model says Pinnacle underprices). All +EV/opportunity sample
  decisions use THIS family.

## 1. Production safety / provenance
- Production `/root/nfl-edge` on `main` @ `b8055348…` untouched; no commit/push/PR.
- Ridge Totals V1 **R4** predictions USED from the existing artifact (candidate_id==R4,
  alpha=100, `RIDGE_TOTALS_V1_SELECTED`). No refit.
- `observed_total` **never loaded**; R4 read with a strict whitelist.
- Provenance: `reports/task_05e_d3b_census_provenance.json`

## 1. Positive-edge ML candidate counts (unique game per model)

| model | unique (game,model) | disc | conf | weeks |
|---|---|---|---|---|
| QB_ELO | 1408 | 838 | 570 | 109/109 |
| XGB | 1233 | 733 | 500 | 89/109 |
| AVG | 1408 | 838 | 570 | 109/109 |

> Positivity check: 0 `>1-positive-side` pairs and 0 zero-positive pairs in the
> per-(game,model) pathology — under valid two-way no-vig inputs there is at most one
> positive side per game/model. No mirrored side is double-counted as a candidate.

## 2. ML probability distribution (POSITIVE_EDGE candidates)

### QB_ELO
| bin | total | disc | conf | 2020 | 2021 | 2022 | 2023 | 2024 | wk |
|---|---|---|---|---|---|---|---|---|---|
| <35% | 271 | 174 | 97 | 60 | 68 | 46 | 57 | 40 | 95/109 |
| 35-40% | 121 | 70 | 51 | 28 | 20 | 22 | 21 | 30 | 68/109 |
| 40-45% | 125 | 71 | 54 | 18 | 24 | 29 | 28 | 26 | 73/109 |
| 45-50% | 154 | 94 | 60 | 23 | 36 | 35 | 33 | 27 | 75/109 |
| 50-55% | 125 | 68 | 57 | 25 | 22 | 21 | 31 | 26 | 68/109 |
| 55-60% | 127 | 70 | 57 | 22 | 23 | 25 | 25 | 32 | 78/109 |
| 60-65% | 137 | 81 | 56 | 27 | 27 | 27 | 30 | 26 | 77/109 |
| 65%+ | 348 | 210 | 138 | 66 | 65 | 79 | 60 | 78 | 100/109 |
### XGB
| bin | total | disc | conf | 2020 | 2021 | 2022 | 2023 | 2024 | wk |
|---|---|---|---|---|---|---|---|---|---|
| <35% | 191 | 120 | 71 | 40 | 50 | 30 | 36 | 35 | 67/109 |
| 35-40% | 103 | 56 | 47 | 18 | 25 | 13 | 24 | 23 | 59/109 |
| 40-45% | 162 | 92 | 70 | 40 | 35 | 17 | 34 | 36 | 70/109 |
| 45-50% | 230 | 152 | 78 | 33 | 51 | 68 | 46 | 32 | 76/109 |
| 50-55% | 176 | 110 | 66 | 27 | 27 | 56 | 35 | 31 | 68/109 |
| 55-60% | 98 | 47 | 51 | 21 | 17 | 9 | 24 | 27 | 59/109 |
| 60-65% | 105 | 49 | 56 | 16 | 12 | 21 | 29 | 27 | 58/109 |
| 65%+ | 168 | 107 | 61 | 39 | 33 | 35 | 22 | 39 | 54/109 |
### AVG
| bin | total | disc | conf | 2020 | 2021 | 2022 | 2023 | 2024 | wk |
|---|---|---|---|---|---|---|---|---|---|
| <35% | 277 | 170 | 107 | 54 | 73 | 43 | 54 | 53 | 91/109 |
| 35-40% | 173 | 101 | 72 | 36 | 30 | 35 | 41 | 31 | 86/109 |
| 40-45% | 189 | 109 | 80 | 28 | 43 | 38 | 44 | 36 | 89/109 |
| 45-50% | 185 | 114 | 71 | 35 | 36 | 43 | 30 | 41 | 77/109 |
| 50-55% | 147 | 85 | 62 | 29 | 25 | 31 | 35 | 27 | 75/109 |
| 55-60% | 134 | 77 | 57 | 18 | 26 | 33 | 32 | 25 | 73/109 |
| 60-65% | 108 | 67 | 41 | 20 | 22 | 25 | 19 | 22 | 65/109 |
| 65%+ | 195 | 115 | 80 | 49 | 30 | 36 | 30 | 50 | 73/109 |

## 3. ML market disagreement (primary Pinnacle no-vig, pp)

### QB_ELO
| bin | total | disc | conf | 2020 | 2021 | 2022 | 2023 | 2024 | wk |
|---|---|---|---|---|---|---|---|---|---|
| 0-2 | 234 | 132 | 102 | 44 | 44 | 44 | 50 | 52 | 93/109 |
| 2-4 | 204 | 122 | 82 | 40 | 43 | 39 | 47 | 35 | 89/109 |
| 4-6 | 197 | 118 | 79 | 37 | 39 | 42 | 38 | 41 | 86/109 |
| 6-8 | 187 | 96 | 91 | 34 | 30 | 32 | 46 | 45 | 87/109 |
| 8-10 | 142 | 84 | 58 | 28 | 30 | 26 | 30 | 28 | 72/109 |
| 10-12 | 144 | 97 | 47 | 35 | 30 | 32 | 27 | 20 | 74/109 |
| 12-15 | 121 | 70 | 51 | 21 | 22 | 27 | 25 | 26 | 71/109 |
| 15+ | 179 | 119 | 60 | 30 | 47 | 42 | 22 | 38 | 79/109 |
### XGB
| bin | total | disc | conf | 2020 | 2021 | 2022 | 2023 | 2024 | wk |
|---|---|---|---|---|---|---|---|---|---|
| 0-2 | 156 | 83 | 73 | 29 | 25 | 29 | 35 | 38 | 73/109 |
| 2-4 | 141 | 70 | 71 | 24 | 27 | 19 | 36 | 35 | 65/109 |
| 4-6 | 148 | 92 | 56 | 23 | 35 | 34 | 23 | 33 | 65/109 |
| 6-8 | 118 | 76 | 42 | 20 | 26 | 30 | 22 | 20 | 67/109 |
| 8-10 | 121 | 73 | 48 | 23 | 30 | 20 | 26 | 22 | 64/109 |
| 10-12 | 96 | 52 | 44 | 19 | 25 | 8 | 25 | 19 | 53/109 |
| 12-15 | 144 | 82 | 62 | 31 | 17 | 34 | 35 | 27 | 70/109 |
| 15+ | 309 | 205 | 104 | 65 | 65 | 75 | 48 | 56 | 87/109 |
### AVG
| bin | total | disc | conf | 2020 | 2021 | 2022 | 2023 | 2024 | wk |
|---|---|---|---|---|---|---|---|---|---|
| 0-2 | 240 | 136 | 104 | 42 | 43 | 51 | 50 | 54 | 96/109 |
| 2-4 | 192 | 111 | 81 | 35 | 48 | 28 | 41 | 40 | 82/109 |
| 4-6 | 183 | 106 | 77 | 41 | 36 | 29 | 36 | 41 | 79/109 |
| 6-8 | 188 | 102 | 86 | 39 | 34 | 29 | 47 | 39 | 82/109 |
| 8-10 | 146 | 87 | 59 | 20 | 28 | 39 | 33 | 26 | 74/109 |
| 10-12 | 127 | 82 | 45 | 24 | 28 | 30 | 22 | 23 | 66/109 |
| 12-15 | 154 | 101 | 53 | 37 | 27 | 37 | 24 | 29 | 81/109 |
| 15+ | 178 | 113 | 65 | 31 | 41 | 41 | 32 | 33 | 77/109 |

## 4. ML actionable price distribution (POSITIVE_EDGE candidates)

### QB_ELO
| bin | total | disc | conf | 2020 | 2021 | 2022 | 2023 | 2024 | wk |
|---|---|---|---|---|---|---|---|---|---|
| <=-200 | 184 | 109 | 75 | 41 | 35 | 33 | 28 | 47 | 84/109 |
| -199to-151 | 135 | 76 | 59 | 22 | 22 | 32 | 31 | 28 | 79/109 |
| -150to-111 | 153 | 93 | 60 | 28 | 31 | 34 | 34 | 26 | 85/109 |
| -110to+110 | 82 | 44 | 38 | 18 | 9 | 17 | 16 | 22 | 61/109 |
| +111to+125 | 91 | 44 | 47 | 11 | 10 | 23 | 24 | 23 | 57/109 |
| +126to+150 | 139 | 76 | 63 | 22 | 30 | 24 | 38 | 25 | 81/109 |
| +151to+175 | 110 | 71 | 39 | 19 | 28 | 24 | 19 | 20 | 65/109 |
| +176to+200 | 75 | 44 | 31 | 10 | 18 | 16 | 18 | 13 | 53/109 |
| +201to+250 | 127 | 80 | 47 | 29 | 24 | 27 | 16 | 31 | 69/109 |
| +251+ | 312 | 201 | 111 | 69 | 78 | 54 | 61 | 50 | 97/109 |
### XGB
| bin | total | disc | conf | 2020 | 2021 | 2022 | 2023 | 2024 | wk |
|---|---|---|---|---|---|---|---|---|---|
| <=-200 | 73 | 44 | 29 | 18 | 13 | 13 | 7 | 22 | 44/109 |
| -199to-151 | 74 | 34 | 40 | 9 | 10 | 15 | 20 | 20 | 43/109 |
| -150to-111 | 104 | 65 | 39 | 26 | 17 | 22 | 19 | 20 | 59/109 |
| -110to+110 | 71 | 39 | 32 | 13 | 8 | 18 | 15 | 17 | 51/109 |
| +111to+125 | 87 | 40 | 47 | 10 | 12 | 18 | 25 | 22 | 57/109 |
| +126to+150 | 162 | 95 | 67 | 25 | 39 | 31 | 43 | 24 | 73/109 |
| +151to+175 | 113 | 77 | 36 | 22 | 24 | 31 | 18 | 18 | 66/109 |
| +176to+200 | 76 | 42 | 34 | 10 | 19 | 13 | 18 | 16 | 53/109 |
| +201to+250 | 130 | 78 | 52 | 26 | 24 | 28 | 21 | 31 | 67/109 |
| +251+ | 343 | 219 | 124 | 75 | 84 | 60 | 64 | 60 | 87/109 |
### AVG
| bin | total | disc | conf | 2020 | 2021 | 2022 | 2023 | 2024 | wk |
|---|---|---|---|---|---|---|---|---|---|
| <=-200 | 95 | 57 | 38 | 29 | 14 | 14 | 11 | 27 | 56/109 |
| -199to-151 | 91 | 53 | 38 | 17 | 16 | 20 | 17 | 21 | 61/109 |
| -150to-111 | 136 | 85 | 51 | 25 | 29 | 31 | 28 | 23 | 80/109 |
| -110to+110 | 81 | 44 | 37 | 17 | 8 | 19 | 17 | 20 | 61/109 |
| +111to+125 | 94 | 43 | 51 | 14 | 8 | 21 | 25 | 26 | 59/109 |
| +126to+150 | 174 | 91 | 83 | 24 | 37 | 30 | 51 | 32 | 82/109 |
| +151to+175 | 134 | 89 | 45 | 23 | 33 | 33 | 24 | 21 | 75/109 |
| +176to+200 | 88 | 48 | 40 | 10 | 21 | 17 | 21 | 19 | 62/109 |
| +201to+250 | 148 | 92 | 56 | 32 | 27 | 33 | 21 | 35 | 74/109 |
| +251+ | 367 | 236 | 131 | 78 | 92 | 66 | 70 | 61 | 98/109 |

## 5. MODEL_IMPLIED_EV distribution (POSITIVE_EDGE candidates; NOT realized ROI)

### QB_ELO
| bin | total | disc | conf | 2020 | 2021 | 2022 | 2023 | 2024 | wk |
|---|---|---|---|---|---|---|---|---|---|
| <=0% | 171 | 88 | 83 | 27 | 36 | 25 | 39 | 44 | 80/109 |
| 0to2.5% | 137 | 88 | 49 | 33 | 23 | 32 | 26 | 23 | 76/109 |
| 2.5to5% | 103 | 65 | 38 | 20 | 16 | 29 | 20 | 18 | 62/109 |
| 5to7.5% | 104 | 52 | 52 | 17 | 20 | 15 | 31 | 21 | 66/109 |
| 7.5to10% | 88 | 52 | 36 | 19 | 17 | 16 | 11 | 25 | 59/109 |
| 10to15% | 162 | 89 | 73 | 28 | 28 | 33 | 37 | 36 | 83/109 |
| 15%+ | 643 | 404 | 239 | 125 | 145 | 134 | 121 | 118 | 99/109 |
### XGB
| bin | total | disc | conf | 2020 | 2021 | 2022 | 2023 | 2024 | wk |
|---|---|---|---|---|---|---|---|---|---|
| <=0% | 121 | 67 | 54 | 22 | 23 | 22 | 26 | 28 | 67/109 |
| 0to2.5% | 72 | 29 | 43 | 10 | 10 | 9 | 20 | 23 | 46/109 |
| 2.5to5% | 70 | 37 | 33 | 8 | 14 | 15 | 16 | 17 | 46/109 |
| 5to7.5% | 73 | 41 | 32 | 14 | 10 | 17 | 14 | 18 | 49/109 |
| 7.5to10% | 76 | 51 | 25 | 13 | 18 | 20 | 13 | 12 | 48/109 |
| 10to15% | 106 | 60 | 46 | 19 | 24 | 17 | 25 | 21 | 64/109 |
| 15%+ | 715 | 448 | 267 | 148 | 151 | 149 | 136 | 131 | 89/109 |
### AVG
| bin | total | disc | conf | 2020 | 2021 | 2022 | 2023 | 2024 | wk |
|---|---|---|---|---|---|---|---|---|---|
| <=0% | 171 | 97 | 74 | 31 | 34 | 32 | 37 | 37 | 78/109 |
| 0to2.5% | 108 | 56 | 52 | 19 | 19 | 18 | 24 | 28 | 72/109 |
| 2.5to5% | 103 | 58 | 45 | 19 | 20 | 19 | 24 | 21 | 66/109 |
| 5to7.5% | 95 | 52 | 43 | 21 | 19 | 12 | 18 | 25 | 65/109 |
| 7.5to10% | 86 | 56 | 30 | 20 | 18 | 18 | 16 | 14 | 58/109 |
| 10to15% | 144 | 78 | 66 | 21 | 24 | 33 | 35 | 31 | 78/109 |
| 15%+ | 701 | 441 | 260 | 138 | 151 | 152 | 131 | 129 | 102/109 |

## 6. Model complementarity / overlap at UNIQUE (game_id, side)

| metric | count |
|---|---|
| QB_ELO | 1408 |
| XGB | 1233 |
| AVG | 1408 |
| QB_cap_XGB | 808 |
| QB_cap_AVG | 1165 |
| XGB_cap_AVG | 1051 |
| QB_cap_XGB_cap_AVG | 808 |
| QB_ELO_ONLY | 243 |
| XGB_ONLY | 182 |
| AVG_ONLY | 0 |
| BOTH_QB_XGB_share | 0.4408 |
| jaccard_QB_XGB | 0.4408 |

| corroboration | unique (game,side) |
|---|---|
| BOTH_MODELS_CORROBORATE | 808 |
| QB_ELO_ONLY | 600 |
| XGB_ONLY | 425 |

**Interpretation:** complementarity is described by counts/percentages only. A later
stacking study is NOT asserted to be warranted merely because populations differ.

## XII. Dog-region sample counts — POSITIVE-EDGE side only (AVG)

### 40-45% (positive-edge AVG)
| bin | total | disc | conf | 2020 | 2021 | 2022 | 2023 | 2024 | wk |
|---|---|---|---|---|---|---|---|---|---|
| +111to+125 | 3 | 1 | 2 | 1 | 0 | 0 | 1 | 1 | 3/109 |
| +126to+150 | 46 | 17 | 29 | 3 | 9 | 5 | 20 | 9 | 36/109 |
| +151to+175 | 42 | 30 | 12 | 8 | 12 | 10 | 8 | 4 | 36/109 |
| +176to+200 | 32 | 19 | 13 | 4 | 8 | 7 | 7 | 6 | 32/109 |
| +201to+250 | 36 | 22 | 14 | 5 | 6 | 11 | 4 | 10 | 30/109 |
| +251+ | 30 | 20 | 10 | 7 | 8 | 5 | 4 | 6 | 26/109 |
combined +201+: **66** (explicit sum of +201..+250 and +251+, from CSV `price_band=+201+`)
### 45-50% (positive-edge AVG)
| bin | total | disc | conf | 2020 | 2021 | 2022 | 2023 | 2024 | wk |
|---|---|---|---|---|---|---|---|---|---|
| +111to+125 | 26 | 15 | 11 | 6 | 3 | 6 | 5 | 6 | 23/109 |
| +126to+150 | 65 | 35 | 30 | 11 | 13 | 11 | 15 | 15 | 45/109 |
| +151to+175 | 35 | 25 | 10 | 6 | 8 | 11 | 4 | 6 | 29/109 |
| +176to+200 | 18 | 13 | 5 | 2 | 6 | 5 | 1 | 4 | 16/109 |
| +201to+250 | 20 | 14 | 6 | 4 | 4 | 6 | 3 | 3 | 16/109 |
| +251+ | 10 | 6 | 4 | 1 | 2 | 3 | 1 | 3 | 10/109 |
combined +201+: **30** (explicit sum of +201..+250 and +251+, from CSV `price_band=+201+`)

> Fix: `+201+` is emitted ONLY as the explicit combined sum of `N(+201..+250) + N(+251+)`;
> the exact `+201..+250` and `+251+` bins are each emitted separately, never silently dropped.

## 7. DK/FD vs Pinnacle product-display STATE (moneyline positive-edge)

| best DK/FD vs Pinnacle price | count |
|---|---|
| BETTER | 1649 |
| EQUAL | 294 |
| WORSE | 2106 |

> Market-display diagnostic only: 'better price than Pinny' is the user's planned label;
> it is not claimed to be proven profitable.

## Spread census (Expected-Margin expected_home_margin)

| bin | total | disc | conf | 2020 | 2021 | 2022 | 2023 | 2024 | wk |
|---|---|---|---|---|---|---|---|---|---|
| 0-0.5 | 91 | 50 | 41 | 14 | 14 | 22 | 21 | 20 | 66/109 |
| 0.5-1 | 123 | 59 | 64 | 15 | 20 | 24 | 32 | 32 | 74/109 |
| 1-1.5 | 105 | 66 | 39 | 18 | 21 | 27 | 19 | 20 | 61/109 |
| 1.5-2 | 103 | 69 | 34 | 25 | 22 | 22 | 13 | 21 | 63/109 |
| 2-2.5 | 105 | 59 | 46 | 18 | 21 | 20 | 27 | 19 | 63/109 |
| 2.5-3 | 107 | 58 | 49 | 22 | 20 | 16 | 21 | 28 | 64/109 |
| 3-4 | 175 | 106 | 69 | 33 | 43 | 30 | 32 | 37 | 88/109 |
| 4-5 | 147 | 85 | 62 | 28 | 27 | 30 | 39 | 23 | 77/109 |
| 5+ | 452 | 286 | 166 | 96 | 97 | 93 | 81 | 85 | 102/109 |

### Spread DK/FD vs Pinnacle (diagnostic)
- games where any actionable offer better than Pinnacle spread
  - num_offers_with_pinnacle: 1408
  - games_any_actionable_better_than_pinnacle: 499
  - games_no_actionable_better_than_pinnacle: 909

## Total census (Ridge Totals V1 R4, corrected)

| bin | total | disc | conf | 2020 | 2021 | 2022 | 2023 | 2024 | wk |
|---|---|---|---|---|---|---|---|---|---|
| 0-0.5 | 161 | 109 | 52 | 36 | 37 | 36 | 16 | 36 | 82/109 |
| 0.5-1 | 143 | 83 | 60 | 28 | 26 | 29 | 33 | 27 | 78/109 |
| 1-1.5 | 143 | 84 | 59 | 35 | 28 | 21 | 27 | 32 | 80/109 |
| 1.5-2 | 134 | 76 | 58 | 19 | 30 | 27 | 30 | 28 | 79/109 |
| 2-2.5 | 150 | 89 | 61 | 21 | 32 | 36 | 31 | 30 | 73/109 |
| 2.5-3 | 125 | 72 | 53 | 31 | 23 | 18 | 25 | 28 | 78/109 |
| 3-4 | 204 | 129 | 75 | 40 | 45 | 44 | 37 | 38 | 89/109 |
| 4-5 | 142 | 89 | 53 | 26 | 35 | 28 | 26 | 27 | 75/109 |
| 5+ | 206 | 107 | 99 | 33 | 29 | 45 | 60 | 39 | 85/109 |

## Quote-freshness sanity (DK/FD/PIN)
- Median quote age at snapshot (hours): DK ~0.0167, FD ~0.0169, PIN ~0.0175;
  max age ~0.13h (DK/FD) / ~0.27h (PIN). Quotes are near-fresh at the frozen
  T-60 snapshot; no obvious stale-quote domination even in the largest
  positive-edge (AVG 8+ pp) bins: DK med 0.018 h, FD 0.020 h, PIN 0.019 h.
- Purely diagnostic: app cadence ~2x/day means freshness is NOT a product signal.
  No cutoff, no extra bucket grid, no product feature. Full table:
  `reports/task_05e_d3b_quote_freshness_v1.csv`.

## Narrow market-dispersion (DK/FD/Pinnacle only; sanity)
- Moneyline: no-vig implied probability range across DK/FD/Pinnacle per game is
  bounded and tiny (afforded by the ~0.017h freshness). Other 7 historical books
  are retained only as optional audit context and do **not** expand the product grid.
- Spread/total: offered-line range across DK/FD/PIN is 1-unit class at most;
  purpose is later distinguishing *model vs broadly-aligned market* from *model
  vs a single-book outlier*; diagnostic only, no buckets created from it.

---
END REPAIRED_OUTCOME-BLIND CENSUS. STOP for review.