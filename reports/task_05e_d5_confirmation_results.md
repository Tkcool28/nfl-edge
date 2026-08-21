# Task 05E-D5 Phase B — Confirmation Analysis (2023–2024 ONLY)

Status: **CONFIRMATION_ANALYSIS_COMPLETE** (2025 SEALED, unopened)
Worktree: `/root/workspaces/nfl-edge-task-05e-edge-prereg-v1`
Branch: `feat/task-05e-edge-preregistration-v1`
Prereg fingerprint: `d195340940e5c9d6c9f62bbfbb8f8f50836013e05334e870f0905d3592d62e5c`
Candidate-lock commit: `aab7a6c558ff324b208052ec1caae05efa0e5717`
Candidate-lock SHA-256: `41c909823a58e9fb5d7de6a4be8c4de55537974d61ddaedffd12acd8c119ead0`
Production: `/root/nfl-edge` `main` @ `b8055348…` (untouched)

> The four discovery candidates were locked FIRST (Phase A commit `aab7a6c`),
> then confirmation (Phase B) opened outcome data strictly for **2023 and 2024
> only**. 2025 stayed SEALED. Grading used the identical frozen rules as
> discovery. **No candidate definition, bucket, threshold, or price rule was
> changed.** The confirmation verdict is mechanistic and honest.

**VERDICT (no rescue):** None of the four locked discovery candidate signals
replicated on 2023–2024. Every candidate shows **DIRECTION_REVERSAL**
(discovery ROI > 0, confirmation ROI < 0). All four are labeled
**FAILED_TO_VALIDATE** under the frozen rules. No bucket was moved, no
"close-enough" redefinition, no filter invented.

---

## 1. Fail-closed / precheck (PASSED, before any outcome)

- Prereg fingerprint recomputed == `d1953409…12e5c` ✅
- Candidate-lock SHA-256 recomputed == `41c9090c…bd119ead0` ✅
- Lock declares confirmation `[2023,2024]`, sealed `[2025]` ✅

## 2. Lock existed before confirmation read

Phase A committed the discovery candidate lock (`aab7a6c`) and only then was the
confirmation firewall opened. Contract test `test_lock_hash_verified_before_confirmation`
asserts the lock hash is pinned before any outcome-bearing confirmation read.

## 3. Confirmation firewall (2023–24 only)

All confirmation graded frames contain only seasons `{2023, 2024}`. 2020/2021/2022
and 2025 are absent. Provenance asserts `exact_seasons_present_in_outcome_frames =
[2023, 2024]`, `sealed_2025_loaded=false`, `sealed_2025_used=false`, discovery
outcome rows were NOT re-joined into the confirmation frame.

---

## 4. Per-candidate discovery vs confirmation

### ML_DOG_VALUE_ZONE_AVG
| | DISCOVERY (2020–22) | CONFIRMATION (2023–24) |
|---|---|---|
| N | 149 | 112 |
| HR / BE | 49.7% / 39.9% | **31.3% / 40.8%** |
| HR−BE | +9.7pp | **−9.5pp** |
| ROI | **+25.2%** | **−23.7%** |
| profit | +37.6 | −26.6 |
Bootstrap conf CI: (−44.3%, −3.7%). DIRECTION_REVERSAL **True**. → FAILED_TO_VALIDATE.

### ML_CORROBORATED_DOG_VALUE_ZONE
|  | DISCOVERY | CONFIRMATION |
|---|---|---|
| N | 85 | 55 |
| HR−BE | +10.4pp | **−12.5pp** |
| ROI | **+28.1%** | **−31.9%** |
Bootstrap conf CI: (−56.2%, −7.5%). DIRECTION_REVERSAL True. FAILED_TO_VALIDATE.

### ML_AVG_0_2 (secondary)
|  | DISCOVERY | CONFIRMATION |
|---|---|---|
| N | 136 | 104 |
| HR−BE | +4.0pp | **−0.55pp** |
| ROI | **+15.4%** | **−14.6%** |
Bootstrap conf CI: (−39.8%, +11.5%). DIRECTION_REVERSAL True. FAILED_TO_VALIDATE.

### SPREAD_0_4_DISCOVERY_UNION
|  | DISCOVERY | CONFIRMATION |
|---|---|---|
| N | 467 | 342 |
| HR−BE | +4.3pp | **−2.1pp** |
| ROI | **+9.7%** | **−1.4%** |
Bootstrap conf CI: (−12.3%, +9.3%). DIRECTION_REVERSAL True (discovery +, confirmation −). FAILED_TO_VALIDATE.

---

## 5. Spread constituents — confirmation (diagnostic, union stands as locked)

| constituent | conf N | HR | BE | ROI |
|---|---|---|---|---|
| 0–1 | 105 | 58.1% | 51.6% | **+15.3%** |
| 1–2 | 73 | 46.6% | 51.6% | −4.2% |
| 2–3 | 95 | 45.3% | 51.9% | −11.8% |
| 3–4 | 69 | 46.4% | 52.0% | −9.3% |
| **union [0,4)** | 342 | 49.7% | 51.8% | **−1.4%** |

The one positive confirmation constituent (0–1) does not rescue the locked
union. The union stands exactly as locked — no constituent dropped.

## 6. Confirmation per-season results

| candidate | 2023 | 2024 |
|---|---|---|
| DOG AVG | −30.4% | −15.1% |
| CORROB DOG | −25.6% | −42.0% |
| AVG 0–2 | −44.6% | +4.4% |
| SPREAD_0_4 | −10.5% | +7.2% |

## 7. Confirmation bootstrap (season-week block, 5000)

| candidate | point ROI | CI | P(ROI>0) |
|---|---|---|---|
| DOG AVG | −23.7% | (−44%, −4%) | 1% |
| CORROB DOG | −31.9% | (−56%, −8%) | 0.7% |
| AVG 0–2 | −14.6% | (−40%, +11%) | 13% |
| SPREAD_0–4 | −1.4% | (−12%, +9%) | 41% |

## 8. Pooled 2020–2024 (descriptive, after confirmation metrics finalized)

| candidate | pooled N | pooled ROI | pooled HR−BE |
|---|---|---|---|
| DOG AVG | 261 | +0.5% | −1.6pp |
| CORROB DOG | 140 | +4.5% | −1.3pp |
| AVG 0–2 | 240 | +5.6% | −0.9pp |
| SPREAD_0–4 | 809 | +4.7% | +0.2pp |

The pooled numbers do not REPLACE confirmation; they are only supporting. No
selection was changed.

## 9. Final evidence labels (frozen rules, exact)

| candidate | label |
|---|---|
| ML_DOG_VALUE_ZONE_AVG | **FAILED_TO_VALIDATE** |
| ML_CORROBORATED_DOG_VALUE_ZONE | **FAILED_TO_VALIDATE** |
| ML_AVG_0_2 | **FAILED_TO_VALIDATE** |
| SPREAD_0_4_DISCOVERY_UNION | **FAILED_TO_VALIDATE** |

Every candidate satisfied the `FAILED_TO_VALIDATE` trigger (DIRECTION_REVERSAL:
discovery ROI>0, confirmation ROI<0; pooled failures at break-even or worse).
No STRONG / SUPPORTED label was earned because confirmation was not positive in
any case.

## 10. Dog-zone casual-user / product diagnostics (confirmation)

**DOG VALUE (AVG):** avg price +147, median +142, range +112..+200; p_avg mean
44.7%; HR 31.3% vs BE 40.8% → **beat break-even is NOT met** (customer would
lose money); 84% of conf weeks had ≥2.2 candidate; max drawdown −26.6 units
(near root loss). This is NOT a viable casual-bettor +EV product under the locked
definition on 2023–24.

## 11. AVG 0–2 interpretation (DK/FD vs Pinnacle)

- Confirmation ROI **−14.6%**; HR 41.4% vs BE 46.7%; HR–BE **−5.3pp**.
- DK/FD vs Pinnacle display: BETTER 41 / EQUAL 6 / WORSE 57 (of 104).
- The "model ≈ sharp-market fair value + DK/FD actionable price" hypothesis is
  **NOT** confirmed. No added price filter applied (locked).

## 12. Totals status

- **TOTAL_R4**: `NOT_ADVANCED_FROM_DISCOVERY` (per lock). Not reopened as a
  confirmation candidate.

## 13. Big Opportunity status

- **BIG_OPPORTUNITY**: `NO_BIG_OPPORTUNITY_DISCOVERY_CANDIDATE`. Not reopened.

## 14. Artifacts

- `reports/task_05e_d5_confirmation_results.csv`
- `reports/task_05e_d5_confirmation_results.md` (this)
- `reports/task_05e_d5_final_evidence_labels.json`
- `reports/task_05e_d5_confirmation_provenance.json`
- `reports/task_05e_d5_product_alignment.json`
- `data/modeling/development_v1/market_edge_confirmation_scored_v1.parquet` (2023–24 only)
- (candidate lock committed under `reports/task_05e_d5_candidate_lock.json` + tests at `tests/contracts/test_market_edge_d5_confirmation_v1.py`)

## 15. Tests

10 confirmation contract tests pass: lock hash verified before confirmation,
prereg hash verified, only 2023–24 in scored parquet (2020–22/2025 absent),
exactly 4 candidates, no candidate definition changed, dog zone / corroborated
subset / AVG 0–2 / spread union exact, totals & Big Op absent, actual DK/FD
returns, pushes zero-profit, season-week block bootstrap 5000, final labels
implement frozen rules exactly.

---

## STOP — NO 2025, NO TOP-CARD DESIGN, NO RETUNE

Confirmation analysis complete but **negative**: the locked discovery edge
signals did not replicate on 2023–2024. No candidate earned STRONG or
SUPPORTED. 2025 remains sealed and unused. Do NOT open 2025, do NOT design
weekly top-card selectors, and do NOT retune any model until the science is
aligned on these results.