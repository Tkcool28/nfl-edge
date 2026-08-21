# Task05F Market Evaluation Layer V1 — Repo-Native Validation Evidence

Branch: `feat/task05f-market-evaluator-v1`
Original (pre-this-commit) HEAD: `c14fec17ec3336da93feb187ce5a483134219188`
Base lineage (main): `7824f1de54d039874abf96b1f97ff135018b34cf`
Production `/root/nfl-edge`: `main @ 7824f1de54d039874abf96b1f97ff135018b34cf` (untouched)

## Scope of this commit

1. Mechanical fail-closed fix to `src/nfl_edge/value/evaluators.py` — the `exact_avg`
   evaluator family now enters the same missing-constituent guard as the combined ML
   families (`global_shrinkage`, `reliability_aware_shrinkage`, `strong_logistic`).
   When either QB-Elo or XGBoost is absent, `exact_avg` returns
   `UNSUPPORTED` / `exact_avg_requires_both_models` instead of raising `TypeError`.
2. Regression test locking that family-path fail-closed behavior.
3. Deterministic chronological-OOS validation artifacts.

## Development universe (resolved)

- Evaluator training observation seasons: **2020–2024 only**.
- Evaluator scored-out-of-sample seasons: **2020–2024 only**.
- 2018–2019 **never enter evaluator fitting or scoring** — the runner applies
  `filter(season.is_in(DEV))` with `DEV=[2020..2024]` to every upstream model input
  before materialization. 2018–2019 exist **only** inside the frozen upstream
  football-model artifacts (QB-Elo / XGBoost / Expected Margin / Ridge R4 produce
  2018–2024), but the Task05F evaluator consumes none of those rows.
- No scored evaluator row is outside 2020–2024 (verified: max season = 2024).

## Football-model unchanged proof

`git diff 7824f1de<base>..HEAD` shows Task05F added only new files under
`src/nfl_edge/value/`, `config/market_evaluator_v1.yaml`, `scripts/market_evaluator_v1_runner.py`,
`tests/value/`, `docs/market_evaluator_v1.md`, and `reports/value_evaluator_v1/`.
No file under `src/nfl_edge/models/` is modified. QB-Elo, chronology-corrected
XGBoost, Expected Margin V1, and Ridge R4 input parquet are read-only inputs,
unchanged. `test_frozen_football_models_do_not_import_market_evaluator_layer` passes.

## 2025 firewall proof

- Evaluator functions hard-reject `season == 2025` (raise RuntimeError) before any
  materialization.
- Runner uses lazy `season.is_in(DEV)` predicates (2020–2024) before collect.
- Verified max season across all 31,109 materialized evaluator rows = **2024**.
- No 2025 market result, ROI, or outcome is consumed.

## Test results

```
tests/value/  ->  15 passed in 0.13s
  (incl. new test_exact_avg_family_fails_closed_on_missing_constituent)
```

Market-edge compatibility: re-ran the relevant existing contracts. One known stale
test (`test_production_head_untouched`) hard-codes an obsolete production HEAD
`b805534`; production is now `main @ 7824f1de` (the Task05F base). This is a
**pre-existing stale expectation**, not a Task05F regression — git history confirms
no Task05F commit touches that file.

## Determinism proof

Chronological runner re-run into a fresh dir produced byte-identical
`scorecard.json` / `provenance.json` (verified by SHA-256 and `diff` across two
separate runs).

## Selection recommendation (preregistered rule applied — NOT ROI)

- Moneyline: **global_shrinkage** (Brier 0.2070, log-loss 0.6013 best; within
  simplicity tolerance of the near-tied reliability-aware shrinkage 0.2070).
  Simplicity rule favors the plainer global shrinkage when performance is tied.
- Spread: **calibrated_normal** (Brier 0.2501, log-loss 0.6938).
- Totals: **calibrated_normal** (Brier 0.2509, log-loss 0.6949).

## Committed artifacts

- `reports/value_evaluator_v1/scorecard.json`
- `reports/value_evaluator_v1/provenance.json`
- `reports/value_evaluator_v1/scorecard.md`
- `reports/value_evaluator_v1/sixth_metrics.json`
- `reports/value_evaluator_v1/oos_rows_manifest.json` (deterministic manifest for
  the oversized 7.5MB row-level artifact, which is left uncommitted)