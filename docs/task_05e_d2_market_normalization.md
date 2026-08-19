# Task 05E-D2 — Raw Market Backup + Normalization / Canonicalization Prep

Status: RAW_MARKET_BACKUP_VERIFIED → MARKET_NORMALIZATION_CANONICALIZATION_COMPLETE
Production branch: `main` @ `a113235d52c524c4bcd95dd7f08524b3117aff16` (untouched)

## Phase A — Raw backup

- ZIP: `backups/historical_market/historical_market_raw_2020_2024_05e_d1_20260819_162243Z.zip`
- SHA-256: `ba20257f1266537e9d21f3a04d2b61568319e3d1c5b4f86d0819953e700d1353`
- 587 entries, 575 raw JSON payloads + ledger + manifests + backup manifest + hash inventory
- Integrity test: no errors. No `.env`, no secrets, no Sleeper runtime files archived.
- Backup manifest: `backups/historical_market/backup_manifest_<ts>.json` (579-entry sha inventory)
- Raw inventory: `backups/historical_market/raw_inventory_<ts>.txt`

## Phase B — Normalization / Canonicalization (outcome-blind)

### New modules (`src/nfl_edge/market_data/`)

**`matching.py`** — deterministic, outcome-blind game identity via canonical team
alias map (nflverse abbrev -> provider spellings; `WAS` has two historical
spellings; Rams use schedule abbrev `LA`). Resolves event identity from
home/away team names only. No scores, no event-id reliance (provider event_id
is an opaque hash). `game_id_abbr_pair()` splits frozen `game_id`.

**`normalize.py`** — builds the normalized long-form layer from immutable RAW
(read-only) + ledger + plan. One row per (event, bookmaker, market, outcome).
Preserves every provenance column (request id, raw path+sha, requested +
actual snapshot, provider event id + commence, book/market keys + last_update,
side, point, american price, target/non-target flag, matched games). Verifies
raw on-disk SHA against ledger (fails closed on mismatch). No consensus,
no averaging, no vig removal.

**`canonical.py`** — builds the canonial dataset:
- `canonical_games.parquet`: one row per frozen target game (1,408) with identity
  match status, kickoff UTC, snapshot timestamps, lead minutes, coverage flags
  per book/market, complete-market books, quality flags.
- `canonical_book_market.parquet`: long-form book x market observations,
  restricted to target events only.
Match status vocabulary: MATCHED_EXACT / MATCHED_ALIAS / UNMATCHED_NO_EVENT /
AMBIGUOUS / OTHER_EXPLICIT_REASON. Quality flags per frozen vocabulary.

**`coverage.py`** — outcome-blind coverage / missingness reports:
per-season, book-market coverage, intersections, books-per-game distributions.

### CLI
- `scripts/build_market_canonical.py --production` — reads production RAW
  read-only, writes derived normalized/canonical to this worktree's
  `data/market_data/`.
- `scripts/report_market_coverage.py` — writes `reports/market_coverage_report_05e_d2.txt`

### Derived artifacts (generated, size/rarationale below)
- `data/market_data/normalized/normalized_book_market.parquet` (1.1 MB,
  427,790 raw provenance rows; includes non-target events for audit)
- `data/market_data/canonical/canonical_games.parquet` (40 KB, 1,408 rows)
- `data/market_data/canonical/canonical_book_market.parquet` (296 KB, 80,188 target rows)

## Outcome-blind coverage headline
- 1,408 / 1,408 target games MATCHED_EXACT (up from 1,262 preliminary; the ~146
  delta is Rams-alias resolution and strict one-snapshot-per-game assignment).
- 0 ambiguous, 0 unmatched, 0 SNAPSHOT_NOT_PREGAME violations.
- Lead time: median 64.4 min, range [60.0, 94.37] pre-kickoff. All strictly
  pregame.
- Markets: h2h/spreads/totals complete book coverage at Pinnacle 1,408/1408
  (100%); DK/FD/PIN 99.8% intersection; DK+FD+PIN+BO 1,405 games.
- 5 genuine DUPLICATE_BOOK_MARKET flags (provider returned 2 lines per market
  in one snapshot) — preserved, not silently resolved.

## Outcomes
None. No scores, winners, edges, ROI, or 2025 data were inspected, computed,
joined, or stored. No Odds API calls, no raw mutation.

## Git
- Worktree: `/root/workspaces/nfl-edge-task-05e-market-normalization-v1`
- Branch: `feat/task-05e-market-normalization-v1` (from exact main SHA)
- Derived `data/market_data/` is NOT committed (large derived dataset);
  source modules, tests, CLI, and this doc ARE committed. Decisions in report.