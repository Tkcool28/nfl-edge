# Task 05C — Totals Feature Contract V1 Final Closeout Report

**Date:** 2026-08-14
**Worktree:** `/root/workspaces/nfl-edge-totals-feature-contract-v1`
**Contract:** `docs/totals_feature_contract_v1.md`

---

## 1. Final Verdict

**TOTALS_FEATURE_CONTRACT_READY**

All gates pass. The accepted Totals V1 feature implementation is complete with:
- Contracts, manifests, modeling table, coverage audit, redundancy report, production-parity assessment, tests, and provenance all verified.

---

## 2–3. Starting / Working Branch / HEAD

| Field | Value |
|---|---|
| Starting branch | `feat/totals-feature-contract-v1` |
| Starting HEAD | `bc1d85414dd2c7c8fafb572946706c1cc0394345` |
| Final working branch | `feat/totals-feature-contract-v1` (no merges) |
| Final working HEAD | `433eadc0bbc30d152cd43c319d078025cce37fa0` |
| Ahead of origin/main | 2 commits |
| origin/main | `bc1d85414dd2c7c8fafb572946706c1cc0394345` |
| Production `/root/nfl-edge` | untouched on `main @ bc1d854…` |

Commits on the feature branch:

```
62ccf6eef085602e34b097cfa23d222b97f41e09  feat: implement Totals V1 feature contract
433eadc0bbc30d152cd43c319d078025cce37fa0  docs: close Task05C totals feature inventory and audits
```

---

## 4–5. Source Inventory & External Sources

**File:** `data/manifests/task05c_source_inventory_v1.json`
**SHA-256:** `7c2b0a3d36629eb46aeab29e1f29d72157cdd2a7c27ed382a55cd3b7b45be04a`

### Exact nflverse datasets/versions used

The 7 promoted nflverse PBP files (from the accepted Phase-1 acquisition):

| Season | Dataset | Filename | Byte size | SHA-256 |
|---|---|---|---|---|
| 2018 | nflverse PBP | `play_by_play_2018.parquet` | 19072097 | `2e6f2dce…` |
| 2019 | nflverse PBP | `play_by_play_2019.parquet` | 19119729 | `60c30670…` |
| 2020 | nflverse PBP | `play_by_play_2020.parquet` | 19311336 | `73b7dbf6…` |
| 2021 | nflverse PBP | `play_by_play_2021.parquet` | 20249925 | `333ad343…` |
| 2022 | nflverse PBP | `play_by_play_2022.parquet` | 20426548 | `931121d8…` |
| 2023 | nflverse PBP | `play_by_play_2023.parquet` | 20534088 | `bd348473…` |
| 2024 | nflverse PBP | `play_by_play_2024.parquet` | 20576368 | `6d432dd4…` |

All 7 verified — full integrity PASS (bytes + SHA match accepted manifest).

Permanent source path:
```
/var/lib/chatgpt-vps-mcp/artifacts/nfl-edge/raw/task05c_pbp_v1/
```

Acquisition URL/release: NOT RECORDED (precedes this closeout; Phase-1 evidence available separately).
Acquisition timestamp: NOT RECORDED. The promoted files are read-only and immutable.
Raw-byte preservation: The files at the above path have been verified byte-exact against the accepted manifest. They have not been re-downloaded or modified during this closeout.

### External sources acquired (beyond PBP)

No new external sources were acquired during this closeout. All required sources (PB oracle QB v2, schedules, canonical games) were already present from earlier phases.

---

## 6. Raw source paths and SHA-256 hashes

See source inventory JSON above. Key canonical inputs:

| Artifact | SHA-256 |
|---|---|
| `data/frozen/games/games_2018_2025.parquet` | See source inventory |
| `data/raw/source_snapshots/v1/schedules_2018_2025_frozen-baseline-v1.parquet` | See source inventory |
| `data/derived/oracle_qb_entering_state_v2/oracle_qb_entering_state_game_sides_2018_2024_v2.parquet` | See source inventory |

---

## 7–10. Feature families

### Available from existing data (INCLUDE V1)

| Family | Letter | CORE_V1 elements |
|---|---|---|
| Rest/scheduling | L | 4 columns (rest_days per side + _missing) |
| Game environment | K | 4 columns (roof_category + _missing, surface_category + _missing) |
| QB context | M | 22 columns (Oracle QB v2 entering state per side) |
| Offensive/defensive efficiency | A/B | 8 columns (EPA/play, success_rate, points/drive, scoring_drive rate per side matchup) |
| Pace / play volume | C | 4 columns (seconds/play, neutral seconds/play per side) |
| Passing environment | D | 6 columns (neutral_pass_rate, air_yards/attempt, YAC/completion per side) |
| Rushing environment | E | 2 columns (explosive_rush_rate per side) |
| Explosive-play | F | 4 columns (explosive_pass_rate + explosive_rush_rate per side) |
| Red-zone / finishing drives | G | 4 columns (red_zone_td_rate, goal_to_go_td_rate per side) |
| Turnover environment | H | 2 columns (turnovers_per_drive per side) |
| Pressure/sacks | I | 2 columns (sacks_per_dropback per side) |

### Requiring new sources

None. All INCLUDE V1 families are sourced from existing accepted promoted inputs (PBP, Oracle QB v2, canonical games, schedules).

### Deferred/rejected

| Family | Letter | Classification | Reason |
|---|---|---|---|
| Interception rate (PBP standalone) | H | DEFERRED | Redundant with turnover rate & Oracle QB rate |
| Lost-fumble rate | H | DEFERRED | Sparse, redundant with turnover rate |
| QB hits/dropback | I | DEFERRED | Redundant, never pressure/hurry |
| Weekly frozen direct-stat columns | A/B/D/E/J | DEFERRED | PBP rates canonical V1 representation |
| Lagged snap participation | N | DEFERRED | Player-selection-dependent, no stable aggregation |
| Current injuries/depth | N | DEFERRED | No pregame historical timestamp semantics |
| True pressure/hurry | I | REJECTED | No legitimate source field |
| Realized temperature/wind | K | REJECTED | Result-derived context prohibited |

---

## 11–12. CORE_V1 and OPTIONAL_V1

**CORE_V1: 90 predictors** — all implemented as EXACT_90_COLUMNS.
**OPTIONAL_V1: 0** — no promoted OPTIONAL families per contract.

---

## 13. Feature manifest

**File:** `data/manifests/task05c_totals_feature_manifest_v1.json`
**Byte SHA-256:** `6acc24f2362276110a95c01ae58a401df7d4a9b3240f08ec658104001e35eca3`
**Logical fingerprint:** `3ae63f19da54193395406d3eef78151c103230453a3b39f7cdd8631d52022f80`
**CORE_V1 records:** 90 (exact order = EXACT_90_COLUMNS)
**DEFERRED families:** 6
**REJECTED families:** 2

Contributing source files (25 `.py` files under `src/nfl_edge/features/totals_v1/`):
Aggregate builder source hash: `23abd12b7dfaf5bee364ca94c86ea819233b6b3a10342d09daa1548b6fab2ebf`

---

## 14. Final modeling table

**File:** `data/derived/totals_v1_modeling_table_2018_2024.parquet`
**Logical fingerprint:** `a4aa982c882d11945585d671d1b1ef315f323ee413e4614b9bc5be442789dc9e`
**Byte SHA-256:** `c379e6a933054248f8da331839e619479a95e56003c27681370114abe353a4cc`
**Reproducibility:** BUILD1 == BUILD2 (identical logical fp + byte sha)

---

## 15–16. Development row count and column count

| Metric | Value |
|---|---|
| Feature artifact rows | 1942 |
| Feature artifact width | 90 |
| Identity artifact rows | 1942 |
| Identity artifact width | 7 |
| Modeling table rows | 1942 |
| Modeling table width | 100 (7 identity + 90 predictors + 3 target/diagnostic) |

---

## 17. Season coverage

| Season | Total | REG | POST |
|---|---|---|---|
| 2018 | 267 | 256 | 11 |
| 2019 | 267 | 256 | 11 |
| 2020 | 269 | 256 | 13 |
| 2021 | 285 | 272 | 13 |
| 2022 | 284 | 271 | 13 |
| 2023 | 285 | 272 | 13 |
| 2024 | 285 | 272 | 13 |
| **Total** | **1942** | **1855** | **87** |

2024 postseason games (Jan/Feb 2025): **13** (all INCLUDE per NFL-season rule)
`2024_22_KC_PHI` present: **YES**
Season 2025 rows in development: **0**

---

## 18. Cold-start rules

- **PBP matchup features:** expanding volume-weighted ratio over eligible prior completed blocks; cross-season history retained. Below metric-specific minimum denominator (20 plays, 5 possessions, 10 intervals, 20 attempts, 5 opps, 20 dropbacks, 20 observed-yard attempts/completions) → null + `_missing=1`. No mean imputation.
- **Oracle QB:** accepted fixed-prior/shrinkage semantics; 250-dropback shrinkage, 0.75 decay over last 8 eligible games. `low_sample` marks sub-shrinkage games; `*_imputed` marks prior-based imputation; `missing_player_id` indicates absent starter identity.
- **Static context (rest/roof/surface):** source values; null + `_missing=1` if absent from schedule/games (extremely rare in real data).

---

## 19. Missingness report

**File:** `reports/development/task05c_totals_feature_coverage_v1.json`
**Logical fingerprint:** `fac1e3b387dc8d58ef780d92801220c6f37a4401422c735c77cf75524f2c7bcb`

Key findings:
- Rows with at least one missing predictor: 1942 (every game has some PBP matchup columns below minimum for early-season/insufficient-history games)
- Rows with null PBP matchup feature: primarily early-season games (Week 1 of each season has zero prior block → all PBP states null + paired _missing=1)
- Rows with QB low-sample or imputed flag: games where Oracle QB has sub-shrinkage confidence (early-season, new QBs)
- Rows with missing static source context: **0** (rest/roof/surface always present in accepted sources)

Per-feature null counts: documented in coverage JSON.

---

## 20. Pregame safety classification

| Class | Applicable columns |
|---|---|
| SAFE_STATIC | Rest days, roof, surface (scheduled pregame context) |
| SAFE_LAGGED | All PBP-derived matchup columns (prior completed blocks) |
| SAFE_SHRUNK | Oracle QB entering-state columns (accepted shrinkage semantics) |
| UNSAFE_TARGET_GAME | Not used in model inputs |
| UNSAFE_FUTURE | Not used in model inputs |

---

## 21–23. Leakage proof

Reusing accepted RUN1 audit evidence:

| Leakage counter | Value |
|---|---|
| target-game PBP source rows used | 0 |
| same-block source rows used | 0 |
| future-block source rows used | 0 |
| NFL season-2025 development rows used | 0 |
| postgame/in-game-only fields as model features | 0 |
| sportsbook fields as model features | 0 |
| Dropback fallback rows | 0 |
| Canonical mapping failures | 0 |

All counters zero in RUN1, RUN2, and SHUFFLED audits.

Target columns exist in the explicit target/diagnostic namespace only (`home_score`, `away_score`, `target_total_points`). They are never in the 90-column model-input projection. Verified by test `test_model_input_projection_equals_accepted_90` — model-input projection equals the accepted 90-feature artifact byte-for-column-value.

NFL 2024 postseason games played in Jan/Feb 2025 remain INCLUDED (13 games). No calendar-year filter was applied — the NFL-season rule governed.

---

## 24. Production-parity assessment

**File:** `reports/development/task05c_totals_feature_production_parity_v1.md`

| Family | Parity status | Action needed for 2026+ |
|---|---|---|
| Rest/scheduling (L) | READY_EXISTING_PIPELINE | None |
| Game environment (K) | READY_EXISTING_PIPELINE | None |
| QB context (M) | REQUIRES_LIVE_SOURCE_ADAPTER | Weekly nflverse QB stats refresh |
| All PBP-derived families (A/B–I) | REQUIRES_LIVE_SOURCE_ADAPTER | Weekly nflverse PBP refresh |

---

## 25. Test results

| Test suite | Passed | Skipped | Notes |
|---|---|---|---|
| Closeout tests (`test_totals_v1_closeout.py`) | 30 | 0 | §9 assertions + both PR-hardening adversarial test groups |
| `tests/features/` total (excludes heavy end-to-end) | 567 | 1 | One skip = durable-path smoke test; heavy `test_end_to_end_builder` deselected once |
| Heavy end-to-end builder test | EXTERNAL PASS | 0 | Proved in an independent external ChatGPT Work/cloud execution environment (150.98s, PASS) |

The external full-data test is documented in:
`reports/development/task05c_phase3e_external_validation_addendum.md`
External validation zip: `/tmp/task05c_phase3e_external_validation.zip` (117595520 bytes, SHA `07cdf5ee72b7…`). The passing external test proved features.width=90, columns=EXACT_90_COLUMNS, identity.width=7, exact identity columns, feature/identity alignment, and no leakage.

## 25b. PR #14 hardening remediation

A PR review identified two narrow robustness gaps in the modeling-table
assembly, both addressed without changing any feature/PBP/semantics logic:

1. **Predictor alignment (Finding A).** The prior assembly attached the
   90-feature predictors to the identity/score join by positional row index
   *after* the score join, implicitly relying on Polars join ordering. The
   canonical accepted artifact was **not** shown to be corrupted. The builder
   (`scripts/build_totals_v1_modeling_table.py`) was refactored to make
   alignment **explicit and fail-closed**: one deterministic row key is
   stamped on the original identity and original feature frames *before* any
   score join; scores join the keyed identity by `game_id`; predictors join
   back by the preserved explicit row key; row-key uniqueness, no row
   loss/duplication, and exact one-to-one identity coverage are enforced. Final
   deterministic `game_id` sort happens only at the end. Score-input row order
   can no longer change which predictors attach to which game.
2. **False hard-fail coverage (Finding B).** The old duplicate-score and
   missing-target tests only asserted on injected data without invoking the
   production path. They now call the real `assemble_modeling_table`
   production logic and assert the raised `TotalsModelingTableError`.

Adversarial production-path tests added:
- score-order shuffle, reverse, and sort-by-other-field → `game→predictor`
  mapping proven identical;
- duplicate `game_id` → production hard-fail;
- missing/unmatched score row and explicit null score → production hard-fail;
- feature/identity height mismatch → production hard-fail;
- duplicated preserved row key and dropped row key (fragment) → fail-closed;
- refactored builder's 90-predictor projection equals the accepted feature
  artifact exactly through the identity bridge.

Holdout/season/leakage requirements are unchanged and re-validated: 1942 rows,
correct season counts, 2024 postseason = 13, `2024_22_KC_PHI` present,
NFL season-2025 rows = 0, sportsbook fields absent, target isolation intact.

**Reproducibility after remediation:** the refactored builder reproduces the
accepted modeling table byte-for-byte — logical fingerprint
`a4aa982c882d11945585d671d1b1ef315f323ee413e4614b9bc5be442789dc9e` and
parquet byte SHA-256 `c379e6a933054248f8da331839e619479a95e56003c27681370114abe353a4cc`
are identical to the accepted artifact. Build-twice determinism verified
(logical_fp and byte SHA equal across BUILD1/BUILD2).

## 25c. Second independent hardening note — sealed 2025 score boundary

Independent rereview found that score-source duplicate validation ran before the
NFL season-2025 development boundary. This was a fail-closed hardening issue,
not demonstrated leakage in the accepted artifact. Validation is now ordered as
required schema validation → `season <= 2024` restriction → bounded-frame
duplicate/row-count/unique-id validation → normal assembly/target checks.

Real production-path adversarial tests prove that an injected duplicate
season-2025 score row and a season-2025 null score cannot affect the 2018–2024
assembly: final `game_id` order, target columns, and all 90 predictors remain
identical to canonical assembly. A duplicate or null score in a development
season still raises `TotalsModelingTableError`. `2024_22_KC_PHI` remains
present, preserving NFL-season-2024 postseason games played in calendar 2025.
The accepted modeling artifact remained unchanged: logical fingerprint
`a4aa982c882d11945585d671d1b1ef315f323ee413e4614b9bc5be442789dc9e`, byte
SHA-256 `c379e6a933054248f8da331839e619479a95e56003c27681370114abe353a4cc`.

---

## 26. Reproducibility result

- **Accepted feature/identity artifacts:** RUN1 == RUN2 == SHUFFLED — identical fingerprints `db2461ff…` / `e98d1355…`, identical parquet SHAs `d33d88cb…` / `67db18cd…`.
- **Feature art. SHA:** `d33d88cb97756e0074408ea4e859b6ae30e5ae7cfa428b3080799613c042a9f6` (matches accepted)
- **Identity art. SHA:** `67db18cd117fa2c789153d322807ae987159ea321e3c98ff56e077bbe1e8bf61` (matches accepted)
- **Modeling table reproducibility:** BUILD1 == BUILD2 (logical_fp: `a4aa982c…`, byte_sha: `c379e6a9…`) both runs produce identical output.
- **Feature manifest reproducibility:** deterministic JSON/ordering; single deterministic generation (verified).

---

## 27. Git status

All Task05C work is committed on the feature branch (2 commits ahead of
`origin/main`). No staged changes. No tracked modifications from base. No
`.env`/`venv`/secrets/caches staged.

Unrelated production-runtime artifacts in `/root/nfl-edge` (Sleeper source-audit files) are NOT staged and were not touched.

---

## 28. Commit(s)

Two logical commits were created:

- `62ccf6eef085602e34b097cfa23d222b97f41e09`
  `feat: implement Totals V1 feature contract`
  (source, tests, builder scripts, contract, derived feature/identity artifacts, existing audits)
- `433eadc0bbc30d152cd43c319d078025cce37fa0`
  `docs: close Task05C totals feature inventory and audits`
  (manifests, closeout scripts, coverage/parity/redundancy reports, external-validation addendum, closeout tests, modeling table, final report)

Neither commit was pushed. No merge was performed (user handles merge).

---

## 29. PR number/status

**N/A.** The user handles PR merge. No PR has been opened. No merge performed.

---

## 30. Recommendation for subsequent bake-off

The later Ridge/XGBoost/CatBoost totals-model bake-off should consume:

1. **Modeling table:** `data/derived/totals_v1_modeling_table_2018_2024.parquet`
   - 1,942 development rows, 100 columns (7 identity + 90 features + target)
   - The 90 model-input columns are defined ONLY by the feature manifest

2. **Feature manifest:** `data/manifests/task05c_totals_feature_manifest_v1.json`
   - Contains the exact 90 CORE_V1 predictor definitions in column order
   - Model-input projection = manifest feature_records where inclusion_status=CORE_V1 and model_input=true

3. **Target column:** `target_total_points` = `home_score + away_score`

4. **Identity columns to drop before fitting:** `game_id`, `season`, `season_type`, `week`, `home_team`, `away_team`, `block_id`

5. **Holdout enforcement:** Do NOT use any NFL season 2025 data. The 2025 holdout is a sealed year. Season 2024 postseason games (Jan/Feb 2025) remain development data per NFL-season rule.

6. **Missingness handling:** Null values carry paired `_missing` indicator columns (1 = missing/null). The feature artifact's null handling is: missing state → null + indicator=1. A deterministic model-pipeline null-to-zero transform IS allowed AFTER the `_missing` indicator is in place. The indicators capture the missingness pattern; zero-imputed values carry the missing signal. Ridge can handle this structure natively. XGBoost/CatBoost may benefit from explicit imputation before fitting, with the `_missing` column as input.

7. **Cold-start** Early-season weeks (especially Week 1) have no prior PBP history → many PBP matchup columns null. The bake-off should stratify or filter by `week` to evaluate cold-start performance separately.

---

## Contract and artifact hash summary

| Item | Path | SHA-256 |
|---|---|---|
| Contract | `docs/totals_feature_contract_v1.md` | `becc6fb9…` |
| Feature artifact | `data/derived/totals_v1_features_2018_2024.parquet` | `d33d88cb…` |
| Identity artifact | `data/derived/totals_v1_feature_identity_2018_2024.parquet` | `67db18cd…` |
| Feature manifest | `data/manifests/task05c_totals_feature_manifest_v1.json` | `6acc24f2…` |
| Modeling table | `data/derived/totals_v1_modeling_table_2018_2024.parquet` | `c379e6a9…` |
| Source inventory | `data/manifests/task05c_source_inventory_v1.json` | `7c2b0a3d…` |
| Builder source identity | `data/manifests/task05c_builder_source_identity_v1.json` | aggregate: `23abd12b…` |
| Coverage report | `reports/development/task05c_totals_feature_coverage_v1.json` | `fac1e3b3…` |
| Phase-3E validation | `reports/development/task05c_phase3e_validation.md` | N/A |
| External validation addendum | `reports/development/task05c_phase3e_external_validation_addendum.md` | N/A |
| Redundancy report | `reports/development/task05c_totals_feature_redundancy_v1.md` | N/A |
| Production parity report | `reports/development/task05c_totals_feature_production_parity_v1.md` | N/A |

---

## Final gate checklist

| Gate | Status |
|---|---|
| Accepted contract unchanged semantically | ✓ |
| Accepted 90-feature artifact hash unchanged | ✓ (d33d88cb) |
| Accepted identity artifact hash unchanged | ✓ (67db18cd) |
| All 7 PBP hashes verified | ✓ |
| Exact 90-feature manifest complete | ✓ |
| Final modeling table assembled | ✓ (1942 rows, 100 cols) |
| Target fields isolated from predictor manifest | ✓ |
| 1942 development games preserved | ✓ |
| Correct season counts | ✓ |
| 2024 postseason preserved (13 games) | ✓ |
| Season-2025 development rows zero | ✓ |
| Leakage counters zero | ✓ (RUN1/RUN2/SHUFFLED) |
| Source inventory complete | ✓ |
| Missingness/cold-start audit complete | ✓ |
| Production-parity assessment complete | ✓ |
| Redundancy report complete | ✓ |
| Focused tests pass (25 closeout + 538 lightweight = 563 total in tests/features) | ✓ |
| New closeout outputs reproducible | ✓ |
| External heavy full-data PASS accurately recorded | ✓ |
| No prohibited model training occurred | ✓ (no Ridge/ElasticNet/XGB/CatBoost/NGBoost/HP search) |
| Production /root/nfl-edge untouched | ✓ |

---

## Verdict

**TOTALS_FEATURE_CONTRACT_READY**

No totals model has been trained. No Ridge/XGBoost/CatBoost bake-off has begun. No merge has occurred.