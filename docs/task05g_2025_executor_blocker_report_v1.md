# NFL EDGE — 2025 One-Shot Executor Blocker Report V1

Status: **NOT READY FOR SINGLE AUTHORIZED 2025 HOLDOUT EXECUTION**

This report is additive evidence only. It does not supersede or mutate the protected pre-2025 acceptance contract. The real 2025 holdout has not been executed and no real 2025 outcome bytes were read while producing this report.

## Resolved prerequisites

The historical 2025 T-60 market prerequisite recorded in the older protected acceptance contract has subsequently been completed outside the sealed outcome boundary:

- acquisition workflow run: `33254688086`
- acquisition artifact: `9715458059`
- acquisition archive SHA-256: `081be41b05d246e50edf933b27b1ca75c63684d79520fdf73431c9c60009e7af`
- plan SHA-256: `d1b1eace49177bf01a22db9c2d9d991d07fe8144d165a9a8a67ba1f29f481425`
- schedule slice SHA-256: `de36585a681bc79824b8427168ec4a74103fead35e2efc980590077d3eb20228`
- requests: 123 / 123 successful
- target games: 285 / 285
- credits spent: 3690
- outcomes opened: NO

Outcome-blind canonicalization also completed:

- canonicalization workflow run: `33288564115`
- artifact: `9725230097`
- artifact digest: `sha256:47382881862b4bdd4a1f175d4f342e8c99ac51cb37e8f92383a82708cbb61369`
- `canonical_book_market_2025.parquet` SHA-256: `c8499262388fca13d6dfd0a7da2f891c1989ed601c75b6987067013ce8092a62`
- `canonical_games_2025.parquet` SHA-256: `e9d4b9a5302a72d32f767a87b52f86e32044118bfb27900fb4c4217d6edd74ef`
- `normalized_book_market_2025.parquet` SHA-256: `6323bf9728280626b129cf533051c46b5de1cd038791fa6b911ca16af889f371`
- structural validation SHA-256: `ed5dd6dd08acc47f0042827a5020856cce7f59bc96cecba65ea076c28bb1b98a`
- score/outcome columns read during canonicalization: 0

The four frozen holdout prediction seams exist:

- Oracle QB-Elo: `src/nfl_edge/holdout/football_2025.py`
- conservative chronology-corrected XGBoost: `src/nfl_edge/holdout/xgboost_2025.py`
- Expected Margin V1 stable: `src/nfl_edge/holdout/expected_margin_2025.py`
- Ridge Totals V1 R4 alpha=100: `src/nfl_edge/holdout/totals_2025.py`
- exact-90 Totals freeze/reveal bridge: `src/nfl_edge/holdout/totals_features_2025.py`

This branch additionally implements and tests:

- deterministic whole-block freeze-before-reveal mechanics (`src/nfl_edge/holdout/one_shot_2025.py`)
- a holdout-only Task05F evaluator parity seam that preserves the canonical 2025 firewall (`src/nfl_edge/holdout/evaluator_2025.py`)
- pre-result Task05F -> Model Confidence V2 -> Spread Confidence V3 -> selectors/headline/staking product orchestration (`src/nfl_edge/holdout/product_2025.py`)
- independent executor-freeze CI (`.github/workflows/task05g-2025-executor-freeze-v1.yml`)

Executor-freeze run `33290870919` passed the immutable prefreeze anchor, compilation, synthetic/development-only holdout tests, invalid-authorization fail-closed proof, double 2020-2024 canonical product reproduction, and exact frozen development-product hashes.

### 2025 Oracle-QB input blocker is resolved

The separately reviewed 2025 Oracle-QB materialization task was completed and merged in PR #70. The tracked 2025 Oracle surface now includes:

- `data/derived/oracle_qb_entering_state_2025_v1/oracle_qb_entering_state_game_sides_2025_v1.parquet`
- `data/derived/oracle_qb_entering_state_2025_v1/oracle_qb_pregame_adjustments_by_game_2025_v1.parquet`
- `data/derived/oracle_qb_entering_state_2025_v1/oracle_qb_entering_state_validation_report_2025_v1.json`
- frozen 2025 actual-starter and identity-crosswalk inputs under `data/derived/stathead_actual_starters_2025_v1/`

The merged validation report records:

- 285 unique 2025 games
- 570 game sides
- zero unmatched starter identities
- adjustment schema matching the historical contract
- zero current-block QB-stat game IDs visible
- zero future-2025 QB-stat game IDs visible
- zero market-data reads
- zero selected outcome columns from the games source
- zero holdout executions

The old Oracle-only blocker described by the original version of this report is therefore closed.

## Definitive remaining blocker — no frozen 2025 PBP/GameObservation surface for Ridge Totals exact-90 state advancement

A second dependency became visible when the exact-90 Totals state transition was traced end to end.

`src/nfl_edge/features/totals_v1/game_observations.py` constructs the `GameObservation` updates consumed by the Totals block state from play-by-play semantics. The accepted primitive state includes PBP-derived EPA/play, success, pass/rush/dropback/sack/turnover rates, drive scoring and turnover rates, pace, neutral situation rates, red-zone and goal-to-go rates, air-yards/YAC rates, and explosive play rates. These are not score-only state updates.

The exact-90 holdout bridge therefore needs, after each completed 2025 block is revealed, an accepted 2025 PBP-derived observation surface with which to advance the state before the next block is frozen.

### Evidence 1 — accepted Task05C PBP inventory stops at 2024

`data/manifests/task05c_source_inventory_v1.json` is the accepted source inventory for the Totals feature system. Its `pbp_manifest` contains exactly:

- `play_by_play_2018.parquet`
- `play_by_play_2019.parquet`
- `play_by_play_2020.parquet`
- `play_by_play_2021.parquet`
- `play_by_play_2022.parquet`
- `play_by_play_2023.parquet`
- `play_by_play_2024.parquet`

There is no 2025 entry. Each of those artifacts is described as `nflverse promoted PBP; canonical source for Totals V1 PBP-derived features`.

### Evidence 2 — the tracked frozen 2018-2025 summary tables are not an accepted substitute

The same Task05C inventory describes `data/frozen/team_game_stats/team_game_stats_2018_2025.parquet` as:

`Frozen team game stats: passing_epa/rushing_epa (audit cross-check only per contract)`

The frozen repository tree also contains 2018-2025 games, QB game stats, rosters, team game stats, venues, schedules, weekly team stats, and related inputs, but no tracked 2025 promoted-PBP artifact and no separately frozen 2025 `GameObservation` ledger.

Using those summary tables to synthesize the missing PBP primitives would change the accepted Totals feature/state methodology and is outside this executor task.

### Evidence 3 — the observation builder materially requires PBP semantics

`src/nfl_edge/features/totals_v1/game_observations.py` imports and applies the accepted PBP semantic extractors and drive/pace observation builders. Its contract explicitly mirrors offense observations to defense-allowed state and forbids silent zero-imputation.

Consequently, advancing 2025 Totals state with empty observations, score-only observations, zero-filled primitives, or team-game summary proxies would not be equivalent to the frozen exact-90 methodology.

## Why the executor cannot be marked ready

The Oracle input is now available, but the full one-shot path still cannot truthfully reproduce the frozen Ridge Totals exact-90 state across 2025 blocks without an accepted 2025 PBP/GameObservation source.

Finishing the top-level authorization runner by inventing such a source inside PR #69 would cross from orchestration into a new data/input materialization decision and could alter model semantics. That is explicitly outside this task.

Accordingly:

- `config/task05g_2025_acceptance_v1.yaml` remains protected and byte-identical to its reviewed frozen blob.
- `execution.ready` remains `false`.
- `scripts/task05g_2025_holdout_one_shot_v1.py` remains fail-closed rather than pretending to be complete.
- the valid authorization command must **not** be run yet.
- `HOLDOUT_SPENT.json` has not been created.
- the 2025 holdout has not been executed.

## Required next task

Create a separately reviewed and frozen **2025 Totals PBP/GameObservation input materialization task** that preserves the accepted Task05C/Phase 3 semantics while supplying the post-game state updates required by `totals_features_2025.py`.

At minimum, that task must:

1. acquire/freeze the 2025 promoted PBP source under the same accepted source semantics as 2018-2024, or materialize a byte-frozen `GameObservation` ledger proven exactly equivalent to that source path;
2. freeze artifact identity, row/game coverage, and SHA-256 hashes;
3. preserve the existing `pbp_semantics`, drive, pace, offense/defense inversion, and no-zero-imputation rules;
4. prove complete block coverage for all 285 2025 games;
5. prove current/future block PBP rows are physically unavailable before reveal and become available only after the applicable block result boundary;
6. make no model refit, selector, evaluator, staking, Play Through, or market-policy changes;
7. execute no 2025 holdout predictions while materializing or validating the source.

Only after that input is independently frozen should PR #69 resume final one-shot composition, refreeze the superseding acceptance identity, and consider `execution.ready: true`.

## Final blocker verdict

`NOT_READY_FOR_SINGLE_AUTHORIZED_2025_HOLDOUT_EXECUTION`

Resolved blocker: **2025 Oracle-QB input — CLOSED by PR #70.**

Remaining blocker: **2025 Ridge Totals exact-90 PBP/GameObservation input — OPEN.**

**2025 HOLDOUT HAS NOT BEEN EXECUTED.**
