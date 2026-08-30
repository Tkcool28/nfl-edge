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

The four frozen holdout prediction seams also exist:

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

## Definitive remaining blocker — no frozen 2025 Oracle-QB input surface

The frozen 2025 Oracle QB-Elo predictor requires a resolver whose identity is `ORACLE` and whose `assert_coverage` covers every current-block `game_id`. The frozen Totals exact-90 feature materializer also consumes a current-block Oracle-QB surface. Those are input requirements shared by two frozen model paths; they cannot be replaced by zero adjustment, projected starter identity, or a different QB source without changing methodology.

The repository does **not** contain a frozen 2025 artifact or generic accepted materializer capable of satisfying this requirement.

### Evidence 1 — accepted Oracle entering-state builder is explicitly 2018-2024

`scripts/build_oracle_qb_entering_state_v2.py` hardcodes:

- starter input: `actual_starting_qb_game_sides_2018_2024_v1.csv`
- output prefixes containing `2018_2024`
- authoritative adjustment artifact scoped to 2018-2024

It further fails if the produced game-side frame contains `season >= 2025`:

`if result.height != starters.height or result.filter(pl.col("season") >= 2025).height: raise ValueError("unexpected v2 starter coverage")`

Therefore this accepted builder is not a season-generic 2025 materializer.

### Evidence 2 — final Oracle starter builder is explicitly frozen to the 2018-2024 universe

`scripts/stathead_actual_starters/build_final_oracle_starters.py` pins:

- `EXPECT_SEASON_COUNTS = {2018: 267, 2019: 267, 2020: 269, 2021: 285, 2022: 284, 2023: 285, 2024: 285}`
- exact Stage01 rows: 3884 game sides
- exact final games: 1942
- exact manual/web exception ledger SHA and row count: 99
- exact crosswalk SHA and row count: 138
- exact primary ledger hash

It explicitly asserts:

- Stage01 seasons equal exactly 2018-2024
- `2025 not in seasons`

The final ledger is therefore a frozen historical reconstruction, not a generic mechanism that can be pointed at season 2025.

### Evidence 3 — existing tracked Oracle artifacts stop at 2024

Tracked Oracle QB entering-state and adjustment artifact names are 2018-2024 scoped. The final Stathead starter artifacts are likewise `actual_starting_qb_*_2018_2024_v1`.

No separate 2025 actual-starter/Oracle-QB artifact or builder was found in the current branch.

## Why the executor cannot be marked ready

Finishing the top-level authorization runner would require choosing or constructing the missing 2025 Oracle-QB identity surface. That would cross from orchestration into a new data/source methodology decision. The executor task explicitly prohibits inventing replacement model seams or changing the frozen model/input contract.

Accordingly:

- `config/task05g_2025_acceptance_v1.yaml` remains protected and byte-identical to its reviewed frozen blob.
- `execution.ready` remains `false`.
- `scripts/task05g_2025_holdout_one_shot_v1.py` remains fail-closed rather than pretending to be complete.
- the valid authorization command must **not** be run yet.
- `HOLDOUT_SPENT.json` has not been created.

## Required next task

Create a separately reviewed and frozen **2025 Oracle-QB input materialization task** that preserves the already-accepted historical Oracle semantics while supplying, for all 285 2025 games:

1. actual historical starting-QB identity for each home/away side under the same `ORACLE_STARTER_IDENTITY_ONLY` interpretation;
2. deterministic player identity resolution compatible with the accepted QB feature inputs;
3. point-in-time entering QB form derived only from strictly prior eligible rows;
4. authoritative home/away QB-Elo adjustments using the already-frozen QB-Elo formula/config;
5. the exact Oracle-QB consumed columns required by the Totals exact-90 materializer;
6. complete `game_id` coverage and frozen artifact hashes;
7. tests proving no same-game/future outcome or QB-stat leakage into entering state.

Only after that artifact/materializer is independently frozen should the one-shot executor branch be resumed, the top-level authorization path wired, the acceptance contract superseded/refrozen, and `execution.ready` considered for `true`.

## Final blocker verdict

`NOT_READY_FOR_SINGLE_AUTHORIZED_2025_HOLDOUT_EXECUTION`

**2025 HOLDOUT HAS NOT BEEN EXECUTED.**
