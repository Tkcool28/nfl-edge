# Task 05E-D4 — Discovery Outcome Analysis (2020–2022 ONLY)

Status: **DISCOVERY_ANALYSIS_COMPLETE** (confirmation 2023–24 CLOSED, 2025 SEALED)
Worktree: `/root/workspaces/nfl-edge-task-05e-edge-prereg-v1`
Branch: `feat/task-05e-edge-preregistration-v1` @ `45897d5ba6722ce22c16dfbb44e60777b3091d7e`
Production: `/root/nfl-edge` `main` @ `b8055348110ceb96933298e01b74d6b45afad89d` (untouched)
Prereg fingerprint: `d195340940e5c9d6c9f62bbfbb8f8f50836013e05334e870f0905d3592d62e5c`

> This is the **first authorized outcome analysis**, restricted to discovery
> seasons 2020, 2021, 2022. Confirmation (2023–24) and the 2025 sealed holdout
> were **not** opened. All grading uses the frozen methodology and frozen
> buckets; only the seven preregistered families are evaluated. All sample
> thresholds, buckets, bootstrap, and season splits are unchanged.

**Fail-closed prereg check passed** before any outcome was read: fingerprint
recomputed == pinned hash; exact seven families; discovery==[2020,2021,2022];
confirmation==[2023,2024]; sealed==[2025]; ML buckets [0,2,4,8,12); spread and
total buckets [0,1,2,3,4).

**Methodology change:** NONE. This is outcome analysis only, no model, bucket,
family, threshold, or role was altered.

---

## 1. Fail-closed prereg check (PASSED)

- fingerprint recompute: `d195340940e5c9d6c9f62bbfbb8f8f50836013e05334e870f0905d3592d62e5c` ✅
- families: exactly 7 ✅
- discovery `[2020,2021,2022]` / confirmation `[2023,2024]` / sealed `[2025]` ✅
- bucket edges unchanged ✅

## 2. Outcome-source provenance

- Sources: `data/market_data/...` census candidates + `data/frozen/games/games_2018_2025.parquet` (scores)
- Input SHA-256 recorded in `reports/task_05e_d4_discovery_provenance.json`
- Outcome-bearing columns: `home_score, away_score, margin_home, total_score, profit, w, p_push, breakeven`
- **exact seasons in outcome frames: [2020, 2021, 2022]** (asserted)
- confirmation_data_loaded = **false**; sealed_2025_loaded = **false**
- model_training / retuning / stacker / Odds-API = **false**

## 3. Season firewall proof

All census rows and games were URL-filtered to `season IN (2020,2021,2022)`
BEFORE the outcome join. The framed outcome set asserts only 2020–22 present;
2023/2024/2025 are absent from every graded frame. See provenance.

---

## 4. Top-level results by seven frozen families (DISCOVERY 2020–22)

Legend: `N` bets · `HR` hit rate · `BE` avg break-even prob · `ROI` flat-stake ·
`vsBE` = HR − BE. **Status** is a discovery-only screen label.

### Moneyline disagreement (per-model buckets)

**QB_ELO**

| bucket | N | W–L–P | HR | BE | ROI | status |
|---|---|---|---|---|---|---|
| 0–2 pp | 132 | 57–74–1 | 43.2% | 47.4% | **+4.9%** | NEG |
| 2–4 pp | 122 | 56–65–1 | 45.9% | 50.8% | −11.8% | NEG |
| 4–8 pp | 214 | 94–120–0 | 43.9% | 45.7% | −10.1% | NEG |
| 8–12 pp | 181 | 70–110–1 | 38.7% | 41.8% | −5.5% | NEG |
| 12+ pp | 189 | 64–124–1 | 33.9% | 38.5% | −15.9% | NEG |
| ALL | 838 | 341–493–4 | 40.7% | 44.2% | −8.3% | NEG |

**XGB**

| bucket | N | W–L–P | HR | BE | ROI | status |
|---|---|---|---|---|---|---|
| 0–2 pp | 83 | 36–47–0 | 43.4% | 50.4% | −19.7% | NEG |
| 2–4 pp | 70 | 26–44–0 | 37.1% | 43.5% | −15.7% | NEG |
| 4–8 pp | 168 | 73–95–0 | 43.5% | 42.8% | **+2.6%** | POS |
| 8–12 pp | 125 | 47–76–2 | 37.6% | 39.4% | −11.5% | NEG |
| 12+ pp | 287 | 84–202–1 | 29.3% | 31.8% | −6.9% | NEG |
| ALL | 733 | 266–464–3 | 36.3% | 38.8% | −7.8% | NEG |

**AVG**

| bucket | N | W–L–P | HR | BE | ROI | status |
|---|---|---|---|---|---|---|
| 0–2 pp | 136 | 75–61–0 | 55.2% | 48.4% | **+15.4%** | **POS** |
| 2–4 pp | 111 | 54–55–2 | 48.6% | 47.5% | **+4.4%** | **POS** |
| 4–8 pp | 208 | 78–130–0 | 37.5% | 40.9% | −8.5% | NEG |
| 8–12 pp | 169 | 57–110–2 | 33.7% | 37.7% | −10.7% | NEG |
| 12+ pp | 214 | 64–150–0 | 29.9% | 31.7% | −9.0% | NEG |
| ALL | 838 | 328–506–4 | 39.1% | 40.0% | −3.5% | NEG |

**CORROBORATED**

| bucket | N | W–L–P | HR | BE | ROI | status |
|---|---|---|---|---|---|---|
| 0–2 pp | 14 | 6–8–0 | 42.9% | 37.0% | +37.6% | LIMITED |
| 2–4 pp | 34 | 14–20–0 | 41.2% | 42.8% | −13.6% | NEG |
| 4–8 pp | 124 | 45–79–0 | 36.3% | 41.1% | −10.6% | NEG |
| 8–12 pp | 115 | 38–76–1 | 33.0% | 37.3% | −10.6% | NEG |
| 12+ pp | 190 | 53–137–0 | 27.9% | 31.4% | −15.1% | NEG |
| ALL | 477 | 156–320–1 | 32.7% | 36.3% | −11.2% | NEG |

### Dog-value zone (40% ≤ p < 50% AND +111..+200 AND positive edge)

| view | N | W–L–P | HR | BE | ROI | status |
|---|---|---|---|---|---|---|
| QB_ELO | 115 | 54–60–1 | 47.0% | 40.2% | **+19.1%** | **POS** |
| XGB | 130 | 60–70–0 | 46.2% | 40.3% | **+14.8%** | **POS** |
| AVG | 149 | 74–75–0 | 49.7% | 39.9% | **+25.2%** | **POS** |
| CORROBORATED | 85 | 42–43–0 | 49.4% | 39.1% | **+28.1%** | **POS** |
| ALL_MODELS | 394 | 188–205–1 | 47.7% | 40.2% | **+20.0%** | **POS** |

### Long dogs (+201+) — separate higher-risk context

| view | N | HR | BE | ROI | status |
|---|---|---|---|---|---|
| QB_ELO | 275 | 17.5% | 24.0% | −23.8% | NEG |
| XGB | 292 | 17.1% | 23.6% | −24.7% | NEG |
| AVG | 322 | 18.3% | 23.9% | −20.8% | NEG |

Long dogs +201+ are **strongly negative** across all models. They remain a
separately reported higher-risk population and are NOT folded into the normal
dog-value hypothesis.

### SPREAD (Expected-Margin)

| bucket | N | W–L–P | HR | BE | ROI | status |
|---|---|---|---|---|---|---|
| 0–1 | 109 | 60–47–2 | 55.0% | 51.8% | **+8.0%** | **POS** |
| 1–2 | 135 | 74–59–2 | 54.8% | 51.8% | **+7.2%** | **POS** |
| 2–3 | 117 | 67–48–2 | 57.3% | 51.9% | **+12.0%** | **POS** |
| 3–4 | 106 | 61–44–1 | 57.5% | 51.8% | **+12.3%** | **POS** |
| 4+ | 371 | 171–191–9 | 46.1% | 52.0% | −8.9% | NEG |
| ALL | 838 | 433–389–16 | 51.7% | 51.9% | +1.5% | NEG |

### TOTAL (Ridge Totals V1 R4)

| bucket | N | W–L–P | HR | BE | ROI | status |
|---|---|---|---|---|---|---|
| 0–1 | 192 | 101–90–1 | 52.6% | 52.0% | +1.7% | POS |
| 1–2 | 160 | 77–83–0 | 48.1% | 52.0% | −7.4% | NEG |
| 2–3 | 161 | 81–78–2 | 50.3% | 52.2% | −2.3% | NEG |
| 3–4 | 129 | 68–59–2 | 52.7% | 52.0% | +3.0% | POS |
| 4+ | 196 | 102–94–0 | 52.0% | 52.0% | −0.05% | NEG |
| ALL | 838 | 429–404–5 | 51.2% | 52.0% | −1.0% | NEG |

Totals are essentially **flat / around break-even** across discovery; no strong
edge. `0-1` and `3-4` buckets are marginally positive only.

---

## 5–7. QB-Elo / XGB / AVG bucket economics (see tables above)

The consistent pattern across all three ML models and corroborated: **small
disagreement is unprofitable-or-noisy, and the strongest positive signal
concentrates in the low-edge 0–2 / 2–4 AVG bins and, much more strongly, in the
fixed dog-value zone.** Larger disagreement (8–12, 12+) is broadly negative for
all views — i.e. bigger model-vs-market disagreement did NOT translate into
positive ROI in discovery.

## 8. Corroborated ML results

Corroboration itself (both models pick the same underpriced side) did **not**
beat single models in the buckets (ALL −11.2%). Its **only** strong positive is
inside the dog-value zone (CORROBORATED DOG ZONE: N=85, +28.1%). So
corroboration adds value mainly within the dog-value zone, not generally.

## 9. Dog-value results

The **dog-value zone is the standout ML finding**: positive ROI across every
view, with AVG +25.2% (N=149), CORROBORATED +28.1% (N=85), and all three
discovery seasons (2020, 2021, 2022) positive in the AVG/per-view splits. This
is the pre-registered normal +EV dog hypothesis zone. (Only 2020–22 were
opened in discovery; confirmation 2023–24 remains closed.)

## 10. Spread results

Expected-Margin spread shows a clean **low-disagreement edge**: buckets 0–1
through 3–4 are each positive (+7% to +12%), while 4+ is strongly negative.

**SPREAD_0_4 is a DECISIVELY-NAMED DISCOVERY-SELECTED UNION OF FOUR
contiguous individual preregistered frozen buckets** — `[0,1)`, `[1,2)`,
`[2,3)`, `[3,4)` (equivalent `[0,4)`). It was NOT itself an originally
standalone preregistered bucket. It is a discovery-selected union of the four
individually-preregistered buckets that were all positive. No bucket boundary
was changed. Union: N=467, ROI +9.7%.

## 11. R4 totals results

No robust totals edge in discovery. All buckets near break-even; 0–1 and 3–4
marginally positive, rest negative. Not a confirmation priority.

---

## 12. Season consistency (per selected candidates)

**DOG_VALUE_ZONE (AVG)** — all 3 seasons positive:
- 2020: N=40, HR 55.0%, ROI +34.3%
- 2021: N=56, HR 53.6%, ROI +36.4%
- 2022: N=53, HR 41.5%, ROI +6.6%
- Catastrophic-instability: **false** (no season ≤ −20%). Season-dominance: false.

**SPREAD_0_4 (DISCOVERY_SELECTED_UNION_OF_FROZEN_BUCKETS: [0,1),[1,2),[2,3),[3,4))** —
all 3 seasons positive:
- 2020: N=145, ROI +4.5% · 2021: N=161, ROI +5.3% · 2022: N=161, ROI +18.9%
- Catastrophic: **false**. Season-dominance: **true** (2022 = 67% of pooled positive profit) — noted for confirmation.

**AVG 0–2** — all 3 seasons positive (2020 +14.4%, 2021 +18.7%, 2022 +13.6%);
week-block 95% CI includes zero (weaker).

**AVG 2–4** — NOT recommended: 2022 ROI −24.5% (N=28) → **CATASTROPHIC_SEASON_INSTABILITY** flag.

## 13. Losing-streak / drawdown diagnostics (candidates)

| candidate | max losing streak | max drawdown | worst rolling-10 |
|---|---|---|---|
| DOG_VALUE_ZONE (AVG) | (see JSON) | (see JSON) | (see JSON) |
| SPREAD_0_4 | (see JSON) | (see JSON) | (see JSON) |
| AVG 0–2 | (see JSON) | (see JSON) | (see JSON) |

Full streak/drawdown/rolling numbers are in
`reports/task_05e_d4_candidate_lock_recommendations.json`. These are
diagnostic only; bucket definitions were NOT modified.

## 14. Week-block bootstrap (5000 reps, season+week block)

| candidate | point ROI | 2.5% | 97.5% | P(ROI>0) |
|---|---|---|---|---|
| DOG_VALUE_ZONE (AVG) | +25.2% | +7.9% | +43.0% | 99.7% |
| CORROBORATED DOG ZONE | +28.1% | +1.7% | +54.8% | 98.2% |
| AVG 0–2 | +15.4% | −5.3% | +37.3% | 92.5% |
| SPREAD_0_4 | +9.7% | +1.2% | +18.2% | 98.5% |
| SPREAD_3_4 | +12.3% | −4.2% | +27.6% | 93.0% |

IID game bootstrap was NOT used as the sole estimate.

## 15. DK/FD vs Pinnacle display diagnostics (diagnostics only)

- **Moneyline candidate rows** — DK/FD price vs Pinnacle (BETTER/EQUAL/WORSE):
  reported per candidate in `reports/task_05e_d4_display_diagnostics.json`.
  (e.g. AVG 0–2: BETTER 49 / EQUAL 15 / WORSE 72 of 136).
- **Spread** — overall 51.3% of bets had number AND price better than Pinnacle
  (`number_and_price_better` = 430/838).
- **Total** — display-state columns were not populated in the audit census
  (NaN); reported as unavailable (diagnostics only, not required for grading).

These states are layout/UX diagnostics, NOT independent systems, and are not
optimized.

## 16. Model complementarity observations

- QB-ELO and XGB both eligible on 733/838 games; **477 (65%)** same-side
  (corroborated).
- Single-model bucket economics do NOT strongly align: AVG's low bins are
  positive while QB-ELO's are flat/negative; XGB 4–8 is the lone XGB positive.
- Corroboration alone is not a winning filter (ALL −11.2%), but **corroboration
  inside the dog-value zone** is the strongest single cell observed.
- Verdict: `LATER_STACKING_STUDY_SUPPORTED` — distinct signals exist (AVG low-edge
  + dog-zone corroboration vs. single models) that a separate, future stacking
  study could investigate. No stacker was fit; none is recommended as
  production-ready.

## 17. Big Opportunity discovery screen

Frozen large-disagreement ML regions **8–12 and 12+** pp, and the long-dog +201+
context, were screened. **Every** large-disagreement bucket and long-dog
population is **negative or near-break-even** ROI in discovery (see §4/§5/§10
tables and `reports/task_05e_d4_big_opportunity_screen.json`):

- All 8–12 / 12+ ML buckets (QB_ELO, XGB, AVG): ROI −5% to −16%.
- Long dogs +201+ (all models): ROI −21% to −25%.

→ **Big Opportunity discovery result: NO_BIG_OPPORTUNITY_DISCOVERY_CANDIDATE.**
(Bigger disagreement did not show replicable positive ROI; confirmation stays
closed.)

## 18. Candidate-lock recommendation set (small, frozen-only, for review)

Machine-readable: `reports/task_05e_d4_candidate_lock_recommendations.json`

**Moneyline (up to 3 → recommending 3):**
1. **ML_DOG_VALUE_ZONE (AVG view)** — the standout.
2. **ML_DOG_VALUE_ZONE (CORROBORATED view)** — strongest single cell.
3. **ML_AVG_0_2** — moderately strong, all seasons positive (weaker bootstrap).

**Spread (up to 2 → recommending 1):**
- **SPREAD_0_4** — labeled `DISCOVERY_SELECTED_UNION_OF_FROZEN_BUCKETS`:
  a discovery-selected union of four contiguous individually-preregistered
  frozen buckets `[0,1)`, `[1,2)`, `[2,3)`, `[3,4)` (equivalent `[0,4)`); it is
  NOT an originally standalone preregistered bucket. `4+` excluded (clearly
  negative). No bucket boundary changed.

**Totals (up to 2 → recommending 0):**
- None (discovery shows no robust totals edge).

**Big Opportunity:** none.

Every recommendation uses only frozen buckets/zones and frozen selected-
side/price rules. No new threshold invented. Candidates proceeding to
confirmation will be LOCKED unchanged (model, side rule, buckets, price zones,
metrics all frozen).

## 19. Tests / assertions

Contract test file added (NOT committed): `tests/contracts/test_market_edge_discovery_v1.py`
Proving:
- prereg fingerprint matches before outcome read
- only 2020–22 outcomes loaded (2023/2024/2025 absent)
- exact seven families
- frozen ML/spread/total buckets unchanged
- dog zone unchanged
- actual DK/FD actionable pricing used; Pinnacle never used as actionable return price
- pushes handled as zero profit; 1-unit profit math correct
- season-week block bootstrap, 5000 reps
- discovery-only status does not masquerade as final validation
- candidate recommendations use only frozen buckets/zones; no new arbitrary threshold

## 20. Proof 2023/2024/2025 remained unopened

- Provisioned: every graded frame contains only seasons `{2020,2021,2022}`
  (asserted in code + provenance `exact_seasons_present_in_outcome_frames`).
- `confirmation_data_loaded = false`, `sealed_2025_loaded = false`,
  `sealed_2025_used = false`.
- No confirmation model run, no 2023–25 game was joined to outcomes.
- Test `test_only_discovery_2020_2022_loaded` asserts absence of 2023/2024/2025.

---

## STOP

Discovery (2020–22) analysis is complete. **Do NOT start confirmation.**

DO NOT assign final STRONG_VALIDATION / SUPPORTED_USABLE / FAILED_TO_VALIDATE
labels yet (they require confirmation). The statuses above are
`DISCOVERY_POSITIVE` / `DISCOVERY_NEGATIVE` / `DISCOVERY_LIMITED_SAMPLE` only —
screening labels, not confirmation claims.

Production `/root/nfl-edge` was NEVER modified. No commit made (task instructed
no commit until independent review).
