# Task05F Canonical Market Input Import

Purpose: make the exact frozen 05E T-60 canonical market inputs available to deterministic GitHub Actions validation of the downstream Task05F evaluator.

This is **not** a new market-data pull, regeneration, normalization change, model change, or betting-hypothesis change.

## Authoritative source

Copy byte-for-byte from the existing production runtime artifacts used by Task05E/Task05F:

- `/root/nfl-edge/data/market_data/canonical/canonical_games.parquet`
- `/root/nfl-edge/data/market_data/canonical/canonical_book_market.parquet`

Do **not** run the Odds API.
Do **not** regenerate the files.
Do **not** use the D3b census, D4/D5 reports, or corrected ledgers as substitutes.
Do **not** read/use 2025 outcomes.

## Historical provenance

Task05E-D2 documented the original canonical build as:

- 1,408 canonical target games, seasons 2020-2024
- 80,188 target book-market rows
- all target games matched exactly
- all snapshots strictly pregame
- median lead time 64.37 minutes
- source raw backup SHA-256 `ba20257f1266537e9d21f3a04d2b61568319e3d1c5b4f86d0819953e700d1353`

The original D2 commit intentionally did not commit `data/market_data/`; this import closes that reproducibility gap by committing only the two small frozen canonical outputs needed by Task05F.

## Required import verification

Before commit, record:

- SHA-256 of each parquet
- byte size of each parquet
- row count of each parquet
- seasons in `canonical_games.parquet`
- minimum/median/maximum `lead_minutes`
- count of `lead_minutes <= 0`
- unique game count in `canonical_book_market.parquet`

Expected structural invariants:

- `canonical_games.parquet`: 1,408 rows
- seasons exactly `[2020, 2021, 2022, 2023, 2024]`
- `canonical_book_market.parquet`: 80,188 rows
- unique target games: 1,408
- no non-pregame snapshot (`lead_minutes <= 0` count = 0)

Any mismatch is a hard stop and must be reviewed before import.

## Scope

Only these two binary inputs and their generated hash/shape manifest may be added by the import commit. Model artifacts, model source, Task05E corrected evidence, and evaluator source must remain untouched.
