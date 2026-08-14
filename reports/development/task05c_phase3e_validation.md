# Task 05C — Phase 3E Validation Report (Team-Normalization Remediation)

Worktree: `/root/workspaces/nfl-edge-totals-feature-contract-v1`
Branch: `feat/totals-feature-contract-v1`
HEAD: `bc1d85414dd2c7c8fafb572946706c1cc0394345`
Contract: `docs/totals_feature_contract_v1.md`
Contract SHA-256: `becc6fb9211ea56527cf580f3bad168998c23e2c4f868de226becfce6546e061`
Date: 2026-08-14

## Scope
Phase 3E is validation + adversarial leakage + provenance + reproducibility
over the accepted Phase 3A–3D Totals V1 pipeline. A verified deviation in
historical team abbreviation normalization was remediated to strict per-game
contract conformance. No feature semantics, minima, formulas, or source
authority were changed.

## Remediation (contract-conformance)
### (1) Per-game normalization (previous pass)
`_normalize_pbp_teams_to_canonical()` previously collapsed per-game mappings
into a GLOBAL alias dictionary and used `replace_strict(global_alias,
default=keep)`. Replaced with deterministic **per-game** normalization:
- per `game_id`, canonical authority is only `raw home -> home_canonical` and
  `raw away -> away_canonical`;
- `posteam`/`defteam` normalize ONLY through that game's own two-team mapping;
- a non-null unknown value hard-fails (`TeamNormalizationError`) -- never
  preserved as-is, never guessed;
- null `posteam`/`defteam` remain null; `game_id` is never changed.

### (2) Identity completeness + distinctness guards (this pass)
Added two pre-validation guards so each `game_id` has EXACTLY ONE complete,
unambiguous two-team identity before normalization:
- each slot must be present exactly once: `n_raw_home == 1`,
  `n_raw_away == 1`, `n_canon_home == 1`, `n_canon_away == 1`; **0 or >1**
  hard-fails (missing identity is a gap, never deferred to a referencing row);
- two distinct teams per side: `raw home != raw away` and
  `canonical home != canonical away`; a collapsed one-team identity hard-fails.

## Real-data team-normalization audit (2018–2024)
| metric | value |
|---|---|
| games scanned | 1942 |
| observed source→canonical changes | LA → LAR |
| seasons affected by LA→LAR | 2018–2024 |
| missing raw home identity | **0** |
| missing raw away identity | **0** |
| missing canonical home identity | **0** |
| missing canonical away identity | **0** |
| raw home == raw away (collapsed) | **0** |
| canonical home == canonical away (collapsed) | **0** |
| ambiguous mappings | **0** |
| unknown / unmapped posteam/defteam | **0** |

(No OAK→LV row was observed because the nflverse source already carries the
Raiders' current canonical abbreviation `LV`; this was not forced into the
report.)

## Reproducibility (regenerated with corrected normalization)
Two independent full 2018–2024 builds:
- feature rows: 1942 (both runs)
- features width 90 / identity width 7 (both runs)
- 2024 postseason: 13 (calendar-2025 games, incl. `2024_22_KC_PHI` present)
- season-2025 rows: 0
- leakage counters: same_game=0, same_block=0, future_block=0,
  season_2025=0, canonical_mapping_failures=0
- feature fingerprint: `db2461ff00727406361850523292f552ff3cbbf2f67760fc7a6d0f79f46a2803` (RUN1 == RUN2)
- identity fingerprint: `e98d135540bca39f735bc70dec2d38b04d543883059ed2c658a5ce0bb180a4f6` (RUN1 == RUN2)
- features parquet SHA-256: `d33d88cb97756e0074408ea4e859b6ae30e5ae7cfa428b3080799613c042a9f6`
- identity parquet SHA-256: `67db18cd117fa2c789153d322807ae987159ea321e3c98ff56e077bbe1e8bf61`

Note: the regenerated artifacts are byte-identical to the pre-remediation build
because per-game normalization produces the same canonical team values on real
data (only LA→LAR is transformed; all other teams are already canonical).

## Validation evidence
- Focused team-normalization remediation tests: **19 passed** (including
  exactly-one-per-slot missing-slot hard-fails, raw/canonical collapsed-team
  hard-fails, unknown hard-fails, cross-game isolation, OAK→LV, LA→LAR,
  already-canonical, shuffled-row determinism, normal two-team pass).
- Full Phase 3E suite (`test_totals_v1_phase3e.py`): **122 passed**.
- `tests/features/test_totals_v1_*.py` (batched per-file to respect the VPS
  worker/memory cap): 531 passed, 1 skipped, with the single heavy real-data
  build test (`test_end_to_end_builder_returns_90_features`) deselected.
- `tests/contracts/` + `tests/leakage/` + `tests/holdout/test_2025_sealed.py`
  + `tests/integration/`: 77 passed.
- non-xgboost backtest subset: 144 passed.
- Known unrelated, unchanged collection failures (not caused by this work):
  `tests/backtest/test_roc_auc.py` (missing `run_03c4b_execution` module) and
  `tests/backtest/test_xgboost_*.py` (missing `xgboost` package — not installed
  by design).

### Full-build reproducibility demonstration (memory-cap note)
The complete 2018–2024 feature build was demonstrated earlier in this task
(RUN1 and RUN2) with identical fingerprints
`db2461ff…` (features) / `e98d1355…` (identity) and persisted SHAs
`d33d88cb…` (features) / `67db18cd…` (identity), all invariants green (1942
rows / 90 cols / 7 identity cols / 13 postseason / KC_PHI / season-2025=0 /
leakage=0). The identity-completeness + distinctness guards added in this pass
**reject zero real identities** (the freshly-run real-data audit above shows
all four missing-slot counts, both collapsed-team counts, ambiguity, and
unknown all equal 0 across all 1942 games), so they alter no real output — the
previously-verified build and persisted artifacts remain exactly valid. A fresh
re-run of the full-data build under pytest could not be completed because the
VPS worker/memory cap now OOM-kills it, per the environment protection; its
exact invariants are instead demonstrated by (a) the real-data audit (full load
+ mapping + normalization + per-game build, run clean over all 1942 games) and
(b) the prior identical-build fingerprints above.

## Output artifacts
- `data/derived/totals_v1_features_2018_2024.parquet` (90 feature cols)
- `data/derived/totals_v1_feature_identity_2018_2024.parquet` (7 identity cols)
- Audit JSONs: `data/derived/audit_RUN1.json`,
  `data/derived/phase3e_audit/audit_RUN2.json`, `data/derived/audit_realdata_audits.json`

## Safety
No `git add/commit/merge/reset/clean/stash` performed. Work remains uncommitted
for review. Production `/root/nfl-edge` untouched (main @ `bc1d854…`).

## Verdict
PHASE_3E_VALIDATION_READY
