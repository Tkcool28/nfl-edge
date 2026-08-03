# Hermes Task 01 — Frozen Historical Data Audit and Baseline

## Execution status

**Do not start until the architecture PR is merged and the exact `main` SHA is supplied.**

This is a narrow data task. It is not permission to implement models, scoring, workflows, the website, or deployment.

## Repository

```text
Tkcool28/nfl-edge
```

Expected production checkout when executed:

```text
/root/nfl-edge
```

If the checkout is elsewhere, report the actual path before proceeding.

## Branch

Create from the exact approved `main` SHA:

```text
data/frozen-baseline-v1
```

Do not work directly on `main`.

## Required preflight

Report before modification:

```text
pwd
git branch --show-current
git rev-parse HEAD
git rev-parse origin/main
git rev-list --left-right --count HEAD...origin/main
git status --short --branch
git ls-files --others --exclude-standard
```

Read and follow:

- `docs/NFL_EDGE_MASTER_BUILD_PLAN.md`
- `docs/architecture.md`
- `docs/data_contract.md`
- `docs/feature_contract.md`
- `config/data.yaml`
- `config/features.yaml`

Stop if those files conflict or are missing.

## Purpose

Establish an auditable historical data baseline for 2018–2025, measure actual raw and compressed sizes, identify point-in-time coverage, and commit only the compact evidence and code needed for the next feature-pipeline task.

The main questions this task must answer are:

1. Which official NFLverse datasets are required and actually available for 2018–2025?
2. What are the exact raw and compressed sizes by source and season?
3. Which sources provide reliable observation timestamps for historical point-in-time use?
4. Is 2018 a defensible development start, or should it move later?
5. Can the 2025 season remain an untouched holdout with complete enough game, team, QB, roster, and depth-chart coverage?
6. Which compact normalized tables should be committed directly to GitHub?
7. Is any raw archive small enough to justify committing, or should raw retrieval remain source-based / use a later GitHub Release asset?

## Data-source boundary

Use official or first-party NFLverse data locations and documentation for the historical football data.

Audit at least:

- Schedules and game results
- Play-by-play or approved team game statistics sufficient to derive team-week features
- Player/QB game or weekly statistics
- Rosters and stable player identifiers
- Depth charts
- Snap counts when useful for starter evidence
- Injury/status data availability and its known historical limits
- Venue/roof/neutral-site information

Do not use sportsbook odds in this task.

Do not use scraped secondary data merely to fill a gap without stopping and reporting the gap first.

## Disposable environment

Create a temporary environment outside the repository, for example:

```text
/tmp/nfl-edge-data-audit-venv
/tmp/nfl-edge-data-audit-raw
```

Do not use or modify another project's virtual environment.

Do not create a permanent NFL environment on the VPS.

## Allowed repository changes

Only these paths may change:

```text
src/nfl_edge/data/**
data/manifests/**
data/frozen/**
data/fixtures/**
docs/data_source_audit.md
docs/data_gap_report.md
config/data.yaml
requirements/base.txt
requirements/training.txt
requirements/lock.txt
pyproject.toml
tests/contracts/**
tests/unit/**
```

`requirements/lock.txt` may be added after a clean disposable install is proven.

Do not modify any other path without stopping for approval.

## Explicitly prohibited

Do not:

- Implement Elo, XGBoost, opponent-adjusted margin, stacking, or calibration
- Build model-ready rolling features beyond what is strictly necessary to prove normalized source tables
- Run a model backtest
- Fetch live or historical sportsbook odds
- Add GitHub Actions workflows
- Build the JavaScript site
- Touch Caddy, systemd, cron, or any running service
- Create a production database
- Add Streamlit
- Commit secrets
- Commit a raw archive before measuring and obtaining approval for its storage location
- Use the 2025 outcomes for model tuning or feature decisions
- Delete pre-existing untracked files

## Required implementation

### 1. Source audit

Create `docs/data_source_audit.md` with, for every source:

```text
source name
first-party locator
dataset purpose
seasons available
retrieval method
file format
raw bytes by season
compressed bytes by season
row count by season
column count/schema fingerprint
minimum and maximum event timestamps
observation timestamp availability
license/terms note
known revisions or limitations
```

### 2. Deterministic retrieval and verification

Implement bounded source retrieval under `src/nfl_edge/data/`.

Requirements:

- Explicit season list
- No hidden current-year default
- Retry and timeout handling
- Clear errors
- No secrets
- Raw file checksum before transformation
- Deterministic output paths
- No implicit overwrite of frozen versions

### 3. Manifests

Commit machine-readable manifests under `data/manifests/` containing the fields required by `docs/data_contract.md`.

Every downloaded source file used to create compact tables must have a SHA-256 checksum, row count, byte size, schema fingerprint, and retrieval timestamp.

### 4. Compact normalized tables

Produce only the compact baseline tables needed for the next task, partitioned by season where practical:

```text
data/frozen/games/
data/frozen/team_game_stats/
data/frozen/qb_game_stats/
data/frozen/depth_chart_snapshots/
data/frozen/rosters/
data/frozen/venues/
```

The exact included columns must be documented. Preserve stable source identifiers.

Do not create rolling or opponent-adjusted model features in this task.

### 5. Starter and timestamp gap analysis

Create `docs/data_gap_report.md` covering:

- Historical depth-chart timestamp quality by season
- Whether expected starters can be reconstructed at a realistic pregame `as_of_utc`
- Injury/status coverage and known post-2024 limitations
- Missing stable QB identifiers
- Missing venue/roof data
- Any source that provides only batch-level rather than record-level availability
- Recommended conservative historical scoring timestamp
- Recommendation on whether 2018–2024 development and 2025 untouched holdout are defensible

Do not hide gaps by silently filling them.

### 6. Deterministic fixtures

Create a tiny fixture covering at least:

- Two teams across multiple completed weeks
- One bye
- One neutral-site game
- A starting-QB change
- A rookie or zero-sample QB
- A depth-chart record before a cutoff
- A depth-chart record one second after a cutoff
- A future game that must not influence earlier rows

Fixtures must be hand-auditable and small.

### 7. Tests

Add tests for:

- Manifest schema and checksum verification
- Duplicate game rejection
- Stable team/player identifier normalization
- UTC timestamp enforcement
- Deterministic retrieval/output naming without requiring live network in the test suite
- Frozen-file overwrite prevention
- Fixture integrity
- Season coverage and expected row-count sanity

Do not build full feature leakage tests yet; those belong to the next task.

### 8. Storage decision evidence

Report:

- Total raw bytes
- Total compressed bytes
- Largest single archive
- Compact frozen table bytes
- Expected repository growth
- Recommendation: ordinary Git, Git LFS, GitHub Release assets, or source-retrieval-only

Do not implement the large-file storage choice without approval unless every proposed tracked file is plainly small and within the current repository policy.

## Required quality checks

At minimum run:

```text
python -m compileall src tests
pytest -q
ruff check src tests
```

Run any additional focused integrity command needed to prove row counts, checksums, and reproducibility.

The ordinary test suite must not require internet access.

## Required final verdict

Use exactly one:

```text
FROZEN_DATA_BASELINE_PROVEN
```

or:

```text
FROZEN_DATA_BASELINE_BLOCKED
```

Do not claim success when timestamp or source gaps make the proposed holdout design unreliable.

## Required final report

Provide a detailed report containing:

1. Plain-English verdict
2. Starting path, branch, HEAD, `origin/main`, ahead/behind, tracked and untracked state
3. Exact official sources used
4. Version/package environment used
5. Raw and compressed size table by source and season
6. Row-count and schema table by normalized output and season
7. Every committed file
8. Manifest/checksum proof
9. Test commands and complete pass/fail counts
10. Point-in-time timestamp findings
11. Starting-QB reconstruction findings
12. 2018 development-start recommendation
13. 2025 holdout recommendation
14. Repository versus Release/raw-retrieval storage recommendation
15. Known data gaps and their consequences
16. Temporary files and environments created
17. Cleanup performed
18. Final branch, HEAD, ahead/behind, tracked and untracked state
19. Draft PR number and URL if publication is authorized
20. Recommended next task only; do not begin it

## Cleanup

After committed compact outputs and checksums are verified:

- Remove the disposable virtual environment.
- Remove temporary raw downloads unless they are explicitly needed for an approved pending Release upload.
- Do not remove any pre-existing file.
- Confirm no NFL environment or raw audit directory remains outside the repository, or list the exact approved exception.
