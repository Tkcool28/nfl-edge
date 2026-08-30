# NFL EDGE — 2025 Oracle-QB Input Materialization Blocker V1

Status: **2025_ORACLE_QB_INPUT_NOT_READY**

This document records the narrow blocker found while attempting to materialize the missing 2025 Oracle-QB input surface. No 2025 holdout execution occurred. No model methodology, evaluator, selector, staking, Play Through, market, Odds API, or frozen 2018–2024 Oracle-QB artifact was changed.

## Starting anchor

- repository: `Tkcool28/nfl-edge`
- starting main: `c0cb6e35438e8bedb6c1166f5fa10d550b4038b5`
- feature branch: `feat/2025-oracle-qb-input-v1`

## Accepted historical starter methodology inspected

The accepted 2018–2024 Oracle starter pipeline uses Sports Reference Stathead Player Game Stats Finder output for `QB` + `Started Game`, reconciled against canonical games without using target-game performance to choose a starter. Ambiguous/zero-candidate exceptions are resolved through the existing deterministic manual/web resolution ledger using accepted postgame starter evidence and the existing PFR -> GSIS identity mapping process.

The accepted historical builders are intentionally frozen to 2018–2024 and must not be relaxed:

- `scripts/stathead_actual_starters/build_final_oracle_starters.py`
- `scripts/build_oracle_qb_entering_state_v2.py`
- `src/nfl_edge/features/oracle_qb_entering_state_v2.py`

The frozen historical primary starter ledger SHA-256 remains:

- `38732823861bb1def3c216ce9189b651a2dc4d0737d2f65f88f17e97f40b2a1a`

The frozen historical Oracle adjustment parquet SHA-256 remains:

- `268368c81913e183d7e9ea5050c0da0a01be619790b75c5bab9362c97349e886`

## Exact missing source

The repository contains no 2025 Stathead `QB Started` raw export, no 2025 actual-starter game-side ledger, and no frozen 2025 Oracle-QB input artifact.

The accepted raw Stathead archive was manually copied from the subscriber UI; there is no repository source adapter or subscriber credential available to reproduce the 2025 query from GitHub Actions.

A narrow source-availability probe tested whether the same Sports Reference/PFR QB-start evidence family could be read from the GitHub Actions runtime through the public PFR `QB Starts by player` endpoint.

Probe evidence:

- workflow run: `33295816230`
- job: `99215163912`
- source family: `SPORTS_REFERENCE_PRO_FOOTBALL_REFERENCE`
- endpoint semantics: `QB_STARTS_BY_PLAYER`
- HTTP result: `403 Forbidden`
- persisted page content: `false`
- holdout outcome artifacts read by probe: `false`

The temporary probe code/workflow was removed from the feature branch after the result was established.

## Why implementation stops here

Without the missing 2025 Stathead export or another already-accepted deterministic starter evidence surface, completing 285 games / 570 sides would require one of the following prohibited changes:

1. infer actual starters from 2025 QB performance/statistical output;
2. substitute a different source hierarchy or new fuzzy-matching methodology;
3. guess unresolved starter identities;
4. weaken the accepted 2018–2024 freeze assertions.

Those are all outside this task's allowed methodology boundary.

Therefore the explicit stop condition applies: **2025 starter data is unavailable through the accepted source path in the current repository/runtime.**

## Required unblock

Provide a repository-contained 2025 Sports Reference Stathead `QB` + `Started Game` export using the same query semantics as Task04A, or provide another starter evidence artifact that has already been explicitly accepted as equivalent methodology. Once that source exists, this branch can resume with a 2025-only reconciliation/resolution layer and strict-prior Oracle-QB entering-state materialization without changing the historical builders.

## Holdout / downstream confirmation

- real 2025 holdout executed: **NO**
- Odds API requests/credits used: **0**
- PR #69 modified: **NO**
- accepted 2018–2024 identities modified: **NO**
- Oracle QB-Elo methodology modified: **NO**
- Totals methodology modified: **NO**

