# Point-in-Time Feature Pipeline v1

## Scope

This phase builds deterministic model-ready football rows from the approved frozen baseline. It does not train, fit, tune, calibrate, backtest, score live games, consume odds, or deploy anything.

## Entry points

```bash
PYTHONPATH=src python -m nfl_edge.features \
  --root /root/nfl-edge \
  --config config/features.yaml \
  --output-dir data/derived/features_v1 \
  --created-at-utc <artifact timestamp>
```

Core modules:

- `features/availability.py`: conservative weekly boundaries.
- `features/team.py`: shifted prior-game team history.
- `features/starters.py`: pre-cutoff starter certainty and scenario candidates.
- `features/qb.py`: shifted prior-QB history and fixed-prior shrinkage inputs.
- `features/validation.py`: duplicate, UTC, market, schema, and logical replay checks.
- `features/pipeline.py`: bundle assembly, registry, deterministic files, and manifest.

## Output grains

- `game_features_2018_2025.parquet`: one row per game.
- `team_pregame_features_2018_2025.parquet`: one row per game/team.
- `qb_pregame_features_2018_2025.parquet`: one row per game/team/candidate rank. Unknown candidates remain null rows so every game side is represented.
- `starter_certainty_2018_2025.parquet`: one row per game.
- `weekly_availability_2018_2025.parquet`: one row per season/type/week.
- `feature_registry_v1.json`: one entry per model feature column.
- `feature_manifest_v1.json`: artifact identity, checksums, schemas, coverage, configuration, and code identifier.

## Team feature groups

The pipeline constructs home- and away-prefixed values for rolling 4, rolling 8, and season-to-date history:

- prior games, wins, losses, ties, win rate;
- points scored, points allowed, point differential;
- passing EPA, rushing EPA, offensive total EPA, defensive EPA allowed;
- passing and rushing yards;
- minimum-sample, missingness, and imputation indicators;
- prior-season carryover and early-season indicators;
- week-gap/bye proxy where date-level rest is not supportable;
- home, neutral site, venue ID/missingness, and roof category/missingness;
- rolling population standard deviation for **offensive total EPA** and **defensive EPA allowed** on **roll4 and roll8 only**. Each STD field is paired with an explicit `*_std_missing` indicator. Fewer than two eligible prior observations produces a null standard deviation and a `True` missingness flag; the current game is always excluded. The **season-to-date** aggregate intentionally emits **no standard deviation** — only `roll4` and `roll8` carry STD fields, per the Task 02 correction.

Team rows use only prior records whose weekly availability boundary is at or before the current prediction cutoff. Current-game exclusion is explicit and tested.

## QB feature groups

For each scenario candidate:

- stable `player_id` only; no name join;
- prior attempts/dropbacks and prior games;
- passing EPA per dropback, CPOE, sack rate, and interception rate;
- recency-weighted, season-to-date, and career-within-frozen-coverage form;
- zero-sample, low-sample, missing-player-ID, and metric-imputation flags;
- observed value, fixed prior, sample size, shrinkage weight, and shrunk passing-EPA output.

The fixed shrinkage form is:

```text
weight = prior_dropbacks / (prior_dropbacks + K)
shrunk = weight * observed + (1 - weight) * fixed_prior
```

`K=250` and all priors are configuration values fixed independently of 2025 outcomes. This phase does not fit a QB adjustment model.

## Targets

Targets are labels, never feature inputs:

- `target_home_win`: null for ties or unavailable outcomes;
- `target_margin`: signed home score minus away score when available;
- `target_tie`: explicit boolean;
- `target_available`: explicit outcome availability.

Feature definitions never branch on targets. A contract test removes 2025 outcomes and proves identical feature definitions, windows, and registry.

## Market prohibition

The model matrix hard-fails if it contains known market columns or market-name tokens. Raw schedule odds are never loaded by `FeatureInputs.from_repository`; the normalized games table contains none.

## Determinism

Rows and columns use fixed ordering and UTC dtypes. Parquet uses fixed zstd settings. Tests prove logical replay, byte-identical data files across separate artifact timestamps, and independence from frozen-file mtime. Only manifest `created_at_utc` changes between those runs.
