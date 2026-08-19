# Task 05E-D3C-A1 — Final Preregistration Pre-Outcome Amendment

Status: **EDGE_PREREGISTRATION_AMENDED_PRE_OUTCOME** (outcome-blind; no outcomes opened)
Repo: `/root/nfl-edge` — production `main` @ `b8055348110ceb96933298e01b74d6b45afad89d` (untouched)
Worktree: `/root/workspaces/nfl-edge-task-05e-edge-prereg-v1`
Branch: `feat/task-05e-edge-preregistration-v1`
Pinned config: `config/market_edge_validation_v1.yaml`
Fingerprint (SHA-256, AMENDED): `d195340940e5c9d6c9f62bbfbb8f8f50836013e05334e870f0905d3592d62e5c`
Superseded prior fingerprint: `e0cff2756488aeda7f2f1ec3f5d322c48b507f482947cc07300dfb240bee2137`
Superseded provisional (OBSOLETE): `d178922bedd5ebe206d883828d230083db5d7742263c811fddff69547fe8901f`

> This is an **outcome-blind mechanical/semantic amendment** to the frozen
> preregistration. **No historical outcomes have been opened.** No discovery
> started; no scores, winners, ATS, totals results, hit rates, ROI, or profit
> inspected; no model roles, edge buckets, hypothesis families, sample
> thresholds, bootstrap methodology, season splits, dog-value hypothesis, or
> product architecture changed. This amendment only (1) fixes the reporting
> price-band taxonomy, (2) corrects the `no_dispersion_grid` boolean, and
> (3) operationalizes the evidence-label consistency language into
> deterministic, outcome-blind diagnostics.

---

## 0. Product architecture (frozen, not optimized here)

### WEEKLY TOP CARDS — exactly one each (highest-ranked weekly plays)
1. **HIT RATE**
2. **BALANCED**
3. **+EV**

### Below them — EVERY GAME
- Moneyline · Spread · Total
- Relevant football-model opinions
- DK/FD actionable prices
- Pinnacle benchmark/reference

### Separate conditional section — BIG OPPORTUNITY
- Appears **only** when a validated higher-disagreement signal is present.
- Not required weekly.

> This Task 05E study **validates EDGE FAMILIES**. It does **not** yet optimize
> the final weekly top-card ranking formula.

---

## 1. Split (frozen)

- **DISCOVERY:** 2020, 2021, 2022
- **CONFIRMATION:** 2023, 2024 (identical methodology; pass/fail; not retunable)
- **FINAL PRODUCT HOLDOUT — 2025 SEALED:** hard-rejected at every entry point.
  2025 stays untouched through discovery, confirmation, edge-family selection,
  and weekly top-card selector design. After the HIT RATE / BALANCED / +EV
  selectors are frozen separately, 2025 is used as an untouched end-to-end
  product simulation only.

---

## 2. Frozen market architecture

- **ACTIONABLE AUTO-FEEDS:** DraftKings, FanDuel.
- **REFERENCE / BENCHMARK:** Pinnacle.
- **SECONDARY HISTORICAL AUDIT ONLY:** BetOnline and other acquired books
  (they must NOT define the primary product signal).
- The product may accept manually entered sportsbook offers, so the edge
  evaluator conceptually evaluates **ANY ACTIONABLE OFFER** while DK/FD are the
  auto-populated production books.

---

## 3. Frozen football model roles (do not modify)

- **MONEYLINE** — primary views tested **separately**:
  - **A. Oracle QB-Elo**
  - **B. XGBoost ML**
  - **C. simple untrained 50/50 average:** `AVG = (QB_ELO + XGB) / 2`
  - **D. corroborated edge:** QB-Elo and XGB independently indicate the SAME side
    is underpriced versus Pinnacle.
  - **No stacker.** Complementarity is evaluated from results and may motivate a
    SEPARATE future stacking study only.
- **SPREAD:** Expected-Margin `expected_home_margin`.
- **TOTAL:** Ridge Totals V1 R4, `candidate_id R4`, **alpha = 100** (existing
  frozen R4 model, no retuning). Expected-Margin total may remain secondary
  context only.
- No model tuning from market data. Market data enters only as the comparison
  benchmark in the edge layer, never as a football-model feature.

---

## 4. Vig removal — proportional normalization (ML only)

```
q_home = 1 / decimal_of(american->decimal(price_home))
q_away = 1 / decimal_of(american->decimal(price_away))
p_home = q_home / (q_home + q_away)
p_away = q_away / (q_home + q_away)
```

Two-way proportional normalization of Pinnacle implied probabilities. Applies
to h2h moneyline only. **No alternative no-vig method may be chosen after
outcome inspection.**

---

## 5. Moneyline positive-edge definition (frozen)

For EACH model view and each game:

```
edge_side = model_probability_side - pinnacle_no_vig_probability_side
```

- The **POSITIVE_EDGE_CANDIDATE** is the single side with `edge > 0`.
- **No `model_probability > 0.50` requirement.** Value underdogs MUST remain
  eligible.
- Example: model 45%, market 35% → valid **+10 pp** positive-edge candidate.

For the 50/50 AVG:

```
p_avg        = (p_qbelo + p_xgb) / 2
avg_edge_pp  = (p_avg_selected_side - pinnacle_selected_side) * 100
```

Keep **MODEL_DISAGREEMENT** separate from **MODEL_IMPLIED_EV**:

```
MODEL_IMPLIED_EV = p_model * actionable_decimal_price - 1
```

`MODEL_IMPLIED_EV` is a diagnostic, **not** realized ROI.

---

## 6. Final moneyline disagreement buckets (frozen, primary)

Based only on the completed outcome-blind census (not on outcomes):

```
0–2 pp        [0,2)
2–4 pp        [2,4)
4–8 pp        [4,8)
8–12 pp       [8,12)
12+  pp       [12,+inf)
```

Machine-readable: `[0,2) [2,4) [4,8) [8,12) [12,+inf)`.
No observation dropped above an arbitrary upper cap. These bins apply
independently to **QB_ELO, XGB, AVG**. Corroborated candidates are analyzed
using the relevant disagreement measure(s) without inventing outcome-optimized
thresholds.

---

## 7. Normal +EV dog-value hypothesis (frozen ONE broad zone)

```
model win probability:  40% <= p_model < 50%
AND actual best DK/FD American price:  +111 through +200 inclusive
AND model edge versus Pinnacle:        positive
```

Evaluated for **QB_ELO, XGB, AVG, CORROBORATED** where applicable. This is NOT a
guarantee the eventual +EV weekly card must be a dog; it is predefined because
the outcome-blind census showed adequate sample. Do **not** later carve it into
arbitrary narrow price/probability windows to chase results.

**Long dogs (+201 and higher)** are a separately reported higher-risk population
and may inform BIG OPPORTUNITY research. They are NOT folded into the primary
normal +EV dog hypothesis now.

---

## 8. Spread buckets (frozen)

Use Expected-Margin `expected_home_margin` vs Pinnacle spread. Signed
selected-side advantage is orientation-safe:

```
L = canonical home spread line
selected HOME if expected_home_margin + L > 0, else AWAY
disagreement_pts = |expected_home_margin + L|
```

```
0–1 pt   [0,1)
1–2 pts  [1,2)
2–3 pts  [2,3)
3–4 pts  [3,4)
4+       [4,+inf)
```

Historical returns later use the actual selected actionable DK/FD spread and
price under the frozen line-shopping rule.

---

## 9. Total buckets (frozen)

Use Ridge Totals V1 R4 `predicted_total` vs Pinnacle total:

```
0–1 pt   [0,1)
1–2 pts  [1,2)
2–3 pts  [2,3)
3–4 pts  [3,4)
4+       [4,+inf)
```

OVER candidate when `R4 > Pinnacle total`; UNDER when `R4 < Pinnacle total`.
Historical returns later use actual actionable DK/FD total + price.

---

## 10. Actionable line shopping (deterministic, frozen)

- **MONEYLINE:** choose the better American price between DK and FD for the
  selected side. If one exists use it; if neither exists → not actionable.
- **SPREAD:** normalize to selected side; choose the numerically greatest
  selected-side spread (+3.5 > +3; −2.5 > −3). If identical line, choose better
  price; if still identical use a deterministic fixed book tie-break.
- **TOTAL OVER:** lower total line is better (choose lowest first); if identical,
  better price.
- **TOTAL UNDER:** higher total line is better (choose highest first); if
  identical, better price.
- Do not optimize line-vs-juice trade using outcomes.

---

## 11. DK/FD vs Pinnacle product-display states (frozen diagnostics)

Outcome-blind market-display diagnostics preserved for the future app:

- **MONEYLINE:** DK/FD price relative to Pinnacle → `BETTER / EQUAL / WORSE`.
- **SPREAD / TOTAL:** record separately `NUMBER_BETTER_THAN_PINNACLE`,
  `PRICE_BETTER_THAN_PINNACLE`, and `NUMBER_AND_PRICE_BETTER_THAN_PINNACLE`.

These correspond to future UI concepts (GREEN: actionable DK/FD price better
than Pinnacle; PURPLE: number and price both better than Pinnacle). These
display states are **not assumed profitable**; historical validation may report
their relationship to validated model edge, but they are not new independent
systems to mine.

---

## 12. Hypothesis ledger — FREEZE (exactly seven)

1. `ML_QBELO_DISAGREEMENT`
2. `ML_XGB_DISAGREEMENT`
3. `ML_AVG_DISAGREEMENT`
4. `ML_CORROBORATED_DISAGREEMENT`
5. `ML_DOG_VALUE_ZONE`
6. `SPREAD_DISAGREEMENT`
7. `TOTAL_R4_DISAGREEMENT`

Preserved in `reports/task_05e_d3b_hypothesis_ledger_v1.csv`. Do not treat every
bucket cell as a brand-new independent "system." No new substantive hypothesis
family may be added after discovery outcomes are inspected without being
explicitly labeled `EXPLORATORY_POST_DISCOVERY`, and such findings cannot be
treated as confirmation-validated using the same 2023–24 pool.

---

## 13. Uncertainty / dependence (frozen)

**Primary:** NFL **season-week block bootstrap**.
- Block key: **season + canonical NFL week/postseason block identity**.
- All candidates from the same season-week remain together.
- Sample blocks **with replacement** within the relevant analysis pool.
- **Replicates: 5000.**
- **Primary interval:** 95% **percentile interval**.
- **Primary metric:** actual-price flat-stake ROI; hit rate secondary where
  relevant.
- Per-season results reported separately.
- **Do NOT use IID game bootstrap as the sole uncertainty estimate.**

---

## 14. Outcome metrics to report LATER (evaluation only)

Per frozen bucket/family at minimum: N, wins, losses, pushes (where relevant),
hit rate, average actionable odds, break-even hit rate at actual prices,
**HIT RATE MINUS BREAK-EVEN**, flat 1-unit profit, flat-stake ROI,
MODEL_IMPLIED_EV diagnostic, discovery / confirmation / pooled results,
per-season results, week-block bootstrap interval, candidate week coverage.
Casual-user consistency: longest losing streak, max flat-stake drawdown, worst
season ROI, positive/negative season count, worst rolling 10 qualifying bets
where N permits. These are **evaluation** metrics — do NOT optimize bucket
thresholds to improve them.

---

## 15. Normal +EV evidence labels (frozen, deterministic)

95% statistical significance is NOT the only useful-edge gate. Three labels.
The consistency terms below are replaced by the explicit deterministic
diagnostics in §15a — frozen NOW, outcome-blind:

- **A. STRONG_VALIDATION** — requires positive actual-price ROI in discovery,
  positive in confirmation, hit rate above actual-price break-even in both
  pools, pooled week-block 95% ROI lower bound > 0, **NOT
  CATASTROPHIC_SEASON_INSTABILITY**, sufficient N.
- **B. SUPPORTED_USABLE** — same favorable direction in discovery and
  confirmation, positive pooled actual-price ROI, pooled hit rate above pooled
  break-even, **NOT SEASON_DOMINANCE**, sufficient N. Uncertainty may
  still include zero (modest real edges may not clear a 95% lower-bound gate
  with limited NFL sample).
- **C. FAILED_TO_VALIDATE** — **DIRECTION_REVERSAL**, pooled performance fails
  break-even, **CATASTROPHIC_SEASON_INSTABILITY**, or other preregistered core
  checks fail. Do not promote a failed bucket for one attractive discovery
  sub-period.

### 15a. Deterministic consistency diagnostics (frozen now, outcome-blind)

Vague post-outcome-discretion phrases in the evidence labels are replaced by
these exact machine-checkable definitions (no additional performance
thresholds):

- **SEASON_DOMINANCE** — the largest absolute-profit-contributing season
  accounts for **> 60%** of pooled positive flat-stake profit.
- **CATASTROPHIC_SEASON_INSTABILITY** — at least one season with sufficient
  per-season sample has **ROI ≤ −20% AND pooled ROI is positive**.
- **DIRECTION_REVERSAL** — discovery ROI and confirmation ROI have
  **opposite signs**.

These numbers are frozen now, outcome-blind; no outcome values were used to
choose them.

---

## 16. Normal +EV product objective (frozen)

The NORMAL +EV weekly top card must eventually prioritize validated positive
edge, realistic actionable price, repeatability, manageable variance, and
casual-user usability. It is **NOT** "highest historical ROI" and is **not**
required to be an underdog. The final weekly +EV ranking rule is **not**
optimized here.

---

## 17. Big Opportunity (frozen)

A separate conditional section, not required weekly; identifies unusually large,
historically replicated model-market disagreement. Do **not** freeze a 65%
historical hit-rate threshold. It requires a **higher** evidence standard than
normal +EV: positive discovery performance, positive unchanged confirmation
performance, actual-price results above break-even, meaningful sample,
dependence-aware support, acceptable consistency/concentration, evidence not
obviously caused by stale/outlier quotes, and the larger-disagreement signal
does not collapse in confirmation. If no frozen large-disagreement bucket
qualifies: **`NO_BIG_OPPORTUNITY_SIGNAL_YET`** is a valid result.

---

## 18. HIT RATE / BALANCED / +EV top cards (frozen)

Every production week surfaces exactly **ONE HIT RATE, ONE BALANCED, ONE +EV**
play at the top of the app — weekly ranking outputs across eligible
games/markets. This study does not optimize those ranking formulas. After
discovery + confirmation, a separate task freezes deterministic weekly ranking
logic:
- **HIT RATE:** reliability / estimated win probability prioritized
- **BALANCED:** confidence and price/value jointly prioritized
- **+EV:** validated EV opportunity prioritized with reasonable
  variance/product usability

Then the untouched 2025 season is used for an end-to-end historical simulation
of what those weekly top cards would have shown. **Do not use 2025 while
designing those selectors.**

---

## 19. All-game board (frozen)

The app shows every game below the three weekly headline cards: MONEYLINE,
SPREAD, TOTAL with relevant model opinions where available. A game need not
qualify as a weekly top-3 card to appear. The edge validation task does not
force every game into a recommended-bet category.

---

## 20. Staking separation (frozen)

Historical edge validation uses **flat 1-unit staking** for comparison and
validation. Do not optimize betting strategy using Kelly during edge-family
selection. The production app has a separate user-selected staking-strategy
module (full/fractional/capped Kelly, fixed units). Edge selection answers
"should this bet be considered?"; staking answers "how much should the user
risk?" — kept separate.

---

## 21. Market freshness / dispersion (diagnostics only)

Retained only as sanity diagnostics. Quote freshness is **not** a production
signal; no freshness filter is frozen (`no_freshness_filter_frozen: true`).
DK/FD/Pinnacle dispersion is **not** a new optimization grid
(`no_dispersion_grid: true`). Purpose: detect obvious outlier/stale-market
situations when interpreting extreme model disagreements.

### 21a. Price-band REPORTING taxonomy (frozen; does NOT alter dog-value hypothesis)

A semantically-correct reporting taxonomy, used only to bucket/present
selected-side actionable American prices. It is **reporting only** and does
**not** change the separately frozen ML dog-value hypothesis:

```text
heavy_favorite      : american <= -200
moderate_favorite   : -199 .. -111
near_even           : -110 .. +110
short_plus_money    : +111 .. +150
moderate_plus_money : +151 .. +200
long_plus_money     : american >= +201
```

> The frozen **ML dog-value hypothesis is unchanged**: `40% <= p_model < 50%`
> **AND** best actionable DK/FD price `+111 through +200 inclusive` **AND**
> positive model-vs-Pinnacle edge.

---

## 22. Minimum sample rules (evidence guards, frozen)

- **REPORTABLE BUCKET:** N ≥ 25 in a pool. Lower N → report + mark
  `LIMITED_SAMPLE`.
- **NORMAL +EV PRIMARY EVIDENCE:** N ≥ 50 discovery, N ≥ 50 confirmation.
- **BIG OPPORTUNITY:** N ≥ 50 discovery, N ≥ 40 confirmation, plus stricter
  replication/consistency requirements. Per-season N also reported. These
  thresholds were chosen before outcomes from the blind census; do not lower
  them after results to rescue a signal.

---

## 23. Concentration (frozen diagnostics — no arbitrary cutoffs)

Do **not** freeze arbitrary 40% team / 40% QB cutoffs. Instead preregister
diagnostics: largest season share, largest selected-team share, largest
selected-QB share, actionable DK vs FD source share, price-band concentration.
A result obviously dominated by one identity may not receive the strongest
product label, but no post-hoc numerical cutoff may be invented after outcomes.
A deterministic disqualifier, if ever required, must be defined before
confirmation is opened.

---

## 24. Trial accounting / anti-overfitting (frozen)

Preserve the hypothesis ledger; primary results must tie to one of the seven
frozen families. Candidate findings proceeding to confirmation must be LOCKED
before confirmation outcomes are opened. Do not change model, side definition,
bucket boundaries, price-zone boundaries, or metric formulas between discovery
and confirmation. Limit promoted findings to a small understandable set; do not
produce dozens of bespoke systems.

---

## 25. Files (authoritative artifacts)

- `config/market_edge_validation_v1.yaml` — machine-readable frozen config + fingerprint
- `docs/task_05e_edge_preregistration_v1.md` — this document
- `reports/task_05e_edge_preregistration_v1.txt` — itemized freeze report
- `reports/task_05e_d3b_hypothesis_ledger_v1.csv` — seven frozen families
- `tests/contracts/test_market_edge_preregistration_v1.py` — contract tests
- `scripts/freeze_market_edge_prereg.py` — deterministic fingerprint machinery

Repaired outcome-blind census artifacts are retained as supporting design
evidence:
- `reports/task_05e_d3b_outcome_blind_census.csv` / `.md`
- `reports/task_05e_d3b_census_provenance.json`
- `reports/task_05e_d3b_quote_freshness_v1.csv`
- `data/modeling/development_v1/market_edge_census_v1.parquet`
- `scripts/repair_census.py`, `scripts/analyze_repair_census.py`,
  `scripts/render_repair_census.py`
- `tests/contracts/test_market_edge_census_repair.py`

---

## 26. Git & STOP

Production `/root/nfl-edge` remains `main @ b8055348110ceb96933298e01b74d6b45afad89d`
(untouched; verified). Committing this branch is allowed **only** after all
contract tests pass and the fingerprint is deterministic. Do **not** push. Do
**not** open a PR. Stop before any discovery/confirmation outcome analysis.

---

## 27. STOP

**DO NOT START DISCOVERY OUTCOME ANALYSIS.** This is the end of methodology
design for the primary study. Awaiting review of the frozen preregistration.
