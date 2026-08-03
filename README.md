# NFL Edge

NFL Edge is a pregame NFL win-probability and betting-value research system.

The project is designed to produce an **independent football probability first**, then compare that probability with current actionable sportsbook prices. Closing lines and sportsbook probabilities are not model features.

## Status

**Architecture and contracts phase.** Production model implementation has not yet been authorized.

The authoritative build order is:

1. Lock architecture and contracts.
2. Audit and freeze historical data.
3. Prove the point-in-time feature pipeline.
4. Build and walk-forward test the base models.
5. Train the stacker from out-of-sample predictions and run the untouched holdout.
6. Build live scoring and versioned public JSON.
7. Prove static deployment through Caddy.
8. Design and implement the final JavaScript interface last.

See [`docs/NFL_EDGE_MASTER_BUILD_PLAN.md`](docs/NFL_EDGE_MASTER_BUILD_PLAN.md) and the supporting contracts in [`docs/`](docs/).

## Planned model

- QB-adjusted Elo
- Regularized XGBoost on point-in-time football features
- Opponent-adjusted expected margin
- Regularized logistic stacker trained only on out-of-sample base-model predictions

Primary evaluation is Brier Skill Score against QB-adjusted Elo, supported by raw Brier score, log loss, calibration, and uncertainty analysis.

## Market policy

DraftKings, FanDuel, and Pinnacle prices are introduced only after the football model produces its probability. They may be used for expected-value calculation, best-price selection, eligibility, and display.

They may not be used as model inputs, targets, calibration inputs, or model-approval metrics.

## Production architecture

The final public product will be a static HTML/CSS/JavaScript site reading sanitized JSON. The VPS will host static files through Caddy only.

There will be no permanent NFL Streamlit service, Python web server, training environment, or raw historical training data on the VPS.

## Repository areas

```text
docs/          authoritative architecture and contracts
config/        reviewed model, data, backtest, and scoring configuration
data/          frozen compact data, manifests, and deterministic fixtures
src/nfl_edge/  implementation packages
artifacts/     model metadata, predictions, backtests, and scorecards
site/          static site source and generated public data
deploy/        static deployment and Caddy material
tests/         contract, leakage, unit, integration, and end-to-end tests
.github/       CI and scheduled publication workflows
```

## Important legacy notice

The initial commit contained a Streamlit prototype, a VPS systemd/cron design, and an early market-informed model. Those runtime prototypes have been removed from the architecture branch and remain available only in Git history and the superseded original planning material. They are not authoritative for implementation.

## Public URL target

`https://nfl.tkhermes.duckdns.org`

## License

MIT
