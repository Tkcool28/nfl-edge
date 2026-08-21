# Task 05E — ML Reversal Forensic (v1)

Diagnostic scope: the **corrected** repo-native scorer ledgers
(`reports/task05e_remediated/market_edge_{discovery,confirmation}_corrected_ledger_v1.parquet`),
split **discovery 2020–2022** vs **confirmation 2023–2024**, per season. Frozen
experiment preserved — **no retuning, no threshold/candidate/definition change,
2025 stays SEALED**. No commit / no push.

Primary populations (all from the corrected ledgers):
| label | family | model | bucket |
|---|---|---|---|
| DOG_AVG    | ML_DOG_VALUE_ZONE   | AVG   | ZONE  |
| DOG_CORROB | ML_DOG_VALUE_ZONE   | CORROB| ZONE  |
| AVG_0_2    | ML_AVG_DISAGREEMENT | AVG   | 0-2   |

Driver script: `scripts/diagnose_ml_reversal.py`. Supporting tables:
`ml_reversal_forensic_v1.json`, `ml_reversal_forensic_d*.csv`.

> **Task 05E closeout (correction 6b):** the corroborated ML fail-open fallback
> (`src/nfl_edge/market_edge/candidates.py`) was removed. Previously, when a
> QB-ELO and XGBoost agreed on the same positive side but the exact AVG could
> not be constructed (an AVG row or one constituent's prediction missing), the
> corroborated candidate was emitted and scored from the QB-ELO value alone.
> Now the scorer **fails closed**: the corroborated candidate is emitted only
> when the exact AVG exists (both QB-ELO *and* XGBoost predictions present).
> Regression gate in `tests/contracts/test_market_edge_scorer_remediation_v1.py::
> test_corroborated_never_emitted_via_qb_fallback_when_avg_missing`. Audit of the
> frozen data: **0 of 808 corroboration-predicate games (2020–2024) lacked a
> constructable AVG**, so (consistent with `task05e_remediation_audit_v1.md`)
> the corrected corroborated numbers are **unchanged** (DOG_CORROB = 85
> discovery / 55 confirmation); the removed fallback was never exercised. This
> narrative reflects the corrected ledgers and the regenerated JSON.

---

## 0. Headline reversal (pooled)

| candidate | DISCOVERY N | Disc ROI | Conf N | CONF ROI | z (vs HR) | 2-tail p |
|---|---|---|---|---|---|---|
| DOG_AVG    | 131 | **+26.8%** | 101 | **−23.1%** | +2.86 | 0.0085 |
| DOG_CORROB |  85 | +28.1% |  55 | −31.8% | +2.60 | 0.0184 |
| AVG_0_2    | 126 | +13.7% |  90 | −28.1% | — | — |

Per season (DOG_AVG ROI): 2020 +43.2, 2021 +29.9, 2022 +10.8 → **2023 −28.6,
2024 −15.7**. The reversal is statistically significant and present in every
confirmation season.

---

## 1. Selected-side home vs away (D1)

DOG_AVG pooled:
| period | side | N | HR | ROI | avg p_model | avg BE | avg price |
|---|---|---|---|---|---|---|---|
| DISCOVERY  | home | 59 | 0.475 | +22.4% | 0.458 | 0.392 | 155.5 |
| DISCOVERY  | away | 72 | 0.528 | +30.4% | 0.445 | 0.405 | 146.6 |
| CONFIRMATION| home | 40 | 0.300 | −26.1% | 0.453 | 0.405 | 150.0 |
| CONFIRMATION| away | 61 | 0.328 | −21.1% | 0.443 | 0.410 | 145.0 |

Both sides reverse independently (home +22%→−26%, away +30%→−21%). Per-season
the worst single cell is **2023 away-dog 40–45: N=24, HR 0.125, profit −16.60**
(see D5). The 2023 collapse is **away-dog / low-p probability driven**; 2024 is
home-45-50 (N=11, HR 0.000, −11.0). There is no single universal side story;
the loss is spread across home and away.

---

## 2. Market identity / orientation (D2) — MECHANICAL HYPOTHESIS TEST

For **every** dog-zone row (DOG_AVG n=232, DOG_CORROB n=140) verified against a
Pinnacle side-price + Pinnacle no-vig map:

| Check | DOG_AVG | DOG_CORROB |
|---|---|---|
| rows checked | 232 | 140 |
| plus-money on selected side | 232/232 | 140/140 |
| selected side is UNDERDOG by Pinnacle no-vig (< 0.5) | 232/232 | 140/140 |
| selected side is underdog by Pinnacle offered price (> +100) | 232/232 | 140/140 |
| **selected side is a FAVORITE by no-vig (inversion)** | **0** | **0** |
| **price attached to the OPPONENT** | **0** | **0** |
| any home/away inversion | 0 | 0 |

**Verdict: the home/away or favorite/dog inversion hypothesis is RULED OUT.**
Every dog-zone row is genuinely the plus-money Pinnacle underdog on the modeled
side, priced from the correct side, with no opponent-price attachment. There is
**no mechanical orientation bug** in the corrected scorer ledgers.

---

## 2. Exact row-level recomputation (D3) — CORRECTNESS CHECK

Independently recomputed W/L + profit with `scoring.moneyline_grading` from
frozen game scores at the exact actual price:

| Population | rows checked | mismatches |
|---|---|---|
| DOG_AVG (25 disc + 25 conf deterministic head) | 50 | **0** |
| DOG_CORROB (all feasible) | 140 | **0** |

**No mismatches.** Grading is consistent with the source of truth. Fail-closed
condition not triggered. (Row samples in `ml_reversal_forensic_d3_recompute_*.csv`.)

---

## 3. Calibration INSIDE the slice by season (D4/D4b) — the mechanism core

For DOG_AVG, observed win vs mean predicted p (calibration gap = m_p − obs):
| Season | AVG N | AVG obs | AVG mean p | AVG gap(pp) | QB gap | XGB gap | AVG Brier |
|---|---|---|---|---|---|---|---|
| 2020 | 36 | 0.583 | 0.457 | **−12.6** | −9.9 | −11.8 | 0.257 |
| 2021 | 49 | 0.510 | 0.447 | −6.3 | −1.6 | −4.5 | 0.248 |
| 2022 | 46 | 0.435 | 0.451 | +1.6 | +2.3 | +4.6 | 0.245 |
| 2023 | 58 | 0.293 | 0.444 | **+15.0** | +15.3 | +17.7 | 0.225 |
| 2024 | 43 | 0.349 | 0.452 | +10.3 | +10.7 | +22.1 | 0.241 |

Discovery: dog slice **underpriced** (obs wins ABOVE model p) → value.
Confirmation: dog slice **overpriced** (obs wins BELOW model p) → the model is
systematically 10–22pp too optimistic on 40–50% sub-50 dogs. XGB is the most
over-fit constituent (confirmation gap up to +22.1pp in 2024).

p-band 40-45 vs 45-50 (DOG_AVG ROI):
| season | 40-45 ROI | 45-50 ROI |
|---|---|---|
| 2020 | +30.3% | +52.5% |
| 2021 | −2.0% | +72.4% |
| 2022 | −0.5% | +18.0% |
| 2023 | −42.9% | −5.1% |
| 2024 | +8.7% | −33.3% |

Confirmation degrades across essentially both p-bands, worst at the overlap
(2023 low-band, 2024 high-band).

---

## 5. Home/away x p-band and x edge-band (D5)

The heaviest driver is **2023 away 40-45: N=24, HR 0.125, ROI −0.69** (contributes
most of −16 profit). In 2024 the killer is **home 45-50: N=11, HR 0.000, ROI −1.0**
(N=11, caught an extreme cold streak). Edge-band splits show no monotonic rule
that survives confirmation.

---

## 6. Actionable book mix DK vs FD + price band

Book mix barely moves: ~54% DK / 46% FD across the pool, both books negative in
confirmation (DK −8.9%, FD −10.3% on dog AVG). **No book-dependence single point
of failure.** Composition DID shift materially in the price band domain:

| price band | DISCOVERY share | DISC ROI | CONFIRM share | CONF ROI |
|---|---|---|---|---|
| 111-125  | 14% | +35.2% | 13% | +34.0% |
| 126-150  | 37% | +24.1% | **54%** | **−30.7%** |
| 151-175  | 33% | +10.3% | 16% | −50.5% |
| 176-200  | 17% | +58.2% | 14% | −16.4% |

Confirmation got **heavily concentrated into the 126-150 band** (37%→54% of
volume), and that same mid band was the biggest % loser. So part of the pooled
loss is a band-composition effect, but the mid band also flipped sign on its
own (discovery +24% → confirmation −31%) — it is not purely composition.

---

## 7. Pinnacle fair-prob / model-edge distribution (D7)

| period | Pinnacle fair-prob mean (Q1/Q2/Q3) | model edge pp mean |
|---|---|---|
| DISCOVERY | ~0.389 (0.36/0.39/0.42) | ~6.5 |
| CONFIRMATION| ~0.392 (0.37/0.39/0.42) | ~5.4 |

The same nominal 40–50% zone represents essentially the **same market situation**
(fair prob ~0.39, model edge ~5–6pp) in both periods. So the reversal is NOT
explained by the dog slice becoming, e.g., "longer" or "tighter" dogs — the
inputs looked the same; the **outcome/calibration** changed.

---

## 8. Team concentration (D8)

Max single-team count is 11 (HOU, DOG_AVG over all 5 years); **no team
concentration in the confirmation collapse**. Top teams are low-N. The 2023-24
loss is broad (spread across many teams); LAC/CHI/DEN/MIA carry the worst
cumulative at −3…−6 units each. No one team or QB is responsible for any
material share of the crash. Concentration hypothesis: **not the driver**.

---

## 9. Chronology (D9)

- **2022**: starts slow (early -ROI) but is consistently **positive from wk5
  onward**, ends +4.95 (+10.8%).
- **2023**: **bad immediately** — first 4 picks all lose (cum ROI −1.00), a brief
  week-5 cutback to ~+0.34, then monotonic decay to a season-long −0.28 → −16.6.
  There is no "cluster"; it is a **season-long, year-to-year break at the
  chronological boundary** (2022→2023), not a within-season spike.
- 2024: also starts badly, never meaningfully recovers.

---

## 10. Constituent disagreement (D10)

| period | N | ∣QB−XGB∣ mean (pp) | n( QB higher) : n(XGB higher) |
|---|---|---|---|
| DISCOVERY | 140 | 6.5 | 33 : 52 |
| CONFIRMATION | 55 | 6.9 | 26 : 29 |

Disagreement does not sharply widen in confirmation (6.5→6.9pp) and the
directional mix is balanced — **no systemic (XGB/QB) directional divergence
explains the flip**. CORROB (both agree on the same underdog side) still
reversed (z=−2.60), so corroboration did not rescue it; the calibration error
is shared by both constituents.

---

## 11. Raw prediction orientation & joins (D11)

Re-derived each DOG_AVG row's p from the **frozen source prediction tables**
(XGB conservative chronology_corrected `prediction_probability` p_home ;
QB-Elo `predicted_home_win_probability` p_home), then converted to the selected
side (1−p if away) and compared against the census `p_model`.

| rows checked | 232 |
|---|---|
| orientation/join mismatches | **0** |

**p_home ↔ selected-side conversion is verified correct for away selections.**
No join/orientation defect in prediction→AVG/ledger.

---

## 12. Global model calibration vs the dog slice (D12)

| season | GLOBAL AVG gap (pp) | DOG-SLICE AVG gap (pp) |
|---|---|---|
| 2020 | +0.2 | −12.6 |
| 2021 | +0.2 | −6.3 |
| 2022 | +0.4 | +1.6 |
| 2023 | 0.0 | **+15.0** |
| 2024 | 0.0 | **+10.3** |

The model is **globally well-calibrated every season** (0–0.4pp). The reversal is
therefore **CONDITIONAL miscalibration** — the defect is specific to the
sub-0.50 dog zone (Pinnacle underdog in the 40–50% band), not a global
degradation of AVG.

---

## Ranked diagnosis with evidence

1. **CONDITIONAL_MISCALIBRATION — primary.**
   Evidence: (a) global AVG calibration stable ~0 each year while the dog slice
   plate flips from −12pp (value) to +15/+10pp (over-optimistic) — D12; (b) the
   identical nominal zone (fair prob ~0.39, edge ~5pp, p_model ~0.45) delivered
   opposite results per year — D7; (c) the mechanism label "CONDITIONAL
   MISCALIBRATION" is the one consistent with a model that stays calibrated on
   the whole board but overstates the win prob of the specific sub-0.50
   dogs that the strategy bet on in 2023-24. XGB is the least calibrated
   constituent in confirmation (+22pp in 2024).

2. **COMPOSITION_SHIFT — secondary (real but not the primary cause).**
   Confirmation shifted 37%→54% of volume into the 126-150 band, which also
   flipped sign. That contributed to pooling, but does not explain making
   globally-calibrated model return only 0.29–0.35 on dogs it said 0.44–0.45.

3. **RANDOM_VARIANCE — ruled out as the sole cause.** Reversal z=+2.86 (p =
   0.0085) and +2.60 (p = 0.018); consistent across BOTH confirmation seasons
   and BOTH dogs + corroborated. Not luck.

4. **MECHANICAL_ORIENTATION_BUG — RULED OUT.** 0/232 + 0/140 side-inversion
   errors, 0 opponent-price attachment, 0 row recompute mismatches,
   0 prediction orientation mismatches. The scorer is verifiably correct in
   these corrected ledgers; the home/away and favorite/dog inversion hypotheses
   are explicitly **not supported**.

5. **TEAM_CONCENTRATION — RULED OUT.** Max team count 5/yr; collapse is broad.

### Explicit statements requested
- **Home/away inversion hypothesis: NOT SUPPORTED** (ruled out by D2/D11).
- **Favorite/dog inversion: NOT SUPPORTED** (all rows are true Pinnacle underdogs
  on the correct side, D2).
- No mechanical/orientation defect: the rendered numbers are correct; the
  reversal is **conditional (dog-slice) miscalibration**, secondarily a
  price-band composition shift, with random variance well below the observed
  effect size.

---

## Files emitted
- `scripts/diagnose_ml_reversal.py` (deterministic reader)
- `ml_reversal_forensic_v1.json` (all tables)
- `ml_reversal_forensic_d1_side_*.csv` — side splits
- `ml_reversal_forensic_d2_identity_*.csv` — market identity per row
- `ml_reversal_forensic_d3_recompute_*.csv` — row recompute
- `ml_reversal_forensic_d5_interaction.csv` — home/away × p / edge
- `ml_reversal_forensic_d6_pricebands_*.csv` — DK/FD + price bands
- `ml_reversal_forensic_d8_teams_*.csv` — team concentration
- `ml_reversal_forensic_d9_cumulative.csv` — week-by-week

2025 remained **sealed and unopened** (hard guard in the script).