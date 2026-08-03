# Artifacts Area

Versioned outputs from research and scoring belong here.

```text
models/       approved and retired model packages with metadata/checksums
predictions/  out-of-sample development and forward prediction ledgers
backtests/    run manifests, tuning ledgers, and metric outputs
holdout/      untouched-holdout predictions and scorecards
scorecards/   human-readable model and forward-performance reports
```

Disposable experiments belong in `artifacts/local/` or `artifacts/tmp/` and are ignored.

Artifacts may not be labeled approved without the evidence required by `docs/model_contract.md` and `docs/backtest_contract.md`.
