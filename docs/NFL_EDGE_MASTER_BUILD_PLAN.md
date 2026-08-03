# NFL Edge — Master Build and Execution Plan

**Status:** Authoritative  
**Version:** 1.0  
**Date:** August 2, 2026  
**Repository:** `Tkcool28/nfl-edge`  
**Public URL target:** `https://nfl.tkhermes.duckdns.org`

## 1. Purpose

Build a trustworthy pregame NFL win-probability and betting-value system that is developed and audited through GitHub, trained and backtested in a disposable Hermes environment, and hosted as a static website through Caddy.

This file controls build order, scope, responsibilities, acceptance gates, and deployment boundaries. When later instructions conflict with it, stop and resolve the conflict before implementation.

## 2. Final product

The finished product will provide:

1. Pregame win probabilities for the current NFL slate.
2. A high-hit-rate moneyline selection when one qualifies.
3. A best expected-value moneyline selection when one qualifies.
4. A clear no-play result when nothing qualifies.
5. DraftKings and FanDuel prices with Pinnacle as an informational benchmark.
6. Browser-side manual odds entry and instant EV recalculation.
7. Starting-quarterback certainty and alternate-QB scenarios when material.
8. Model explanations and supporting football features.
9. Historical scorecards and forward performance tracking.
10. A polished mobile-first static JavaScript website.

The final website design is deliberately **TBD** until the model, backtest, scoring, publication, and deployment path are proven.

## 3. Non-negotiable decisions

### Independent football probability

Sportsbook odds and closing-line information are not model features.

```text
football data -> model probability -> current price -> EV and eligibility
```

Closing odds, future market movement, and CLV may not be used for training, tuning, calibration, or model approval.

### Model architecture

The intended stack is:

- QB-adjusted Elo
- Regularized XGBoost on point-in-time football features
- Opponent-adjusted expected margin
- Regularized logistic stacker trained only from out-of-sample base-model predictions

A weak base model may be removed. The project does not preserve components merely to call the result an ensemble.

### Evaluation

Primary metric: Brier Skill Score versus QB-adjusted Elo.

Required supporting evidence:

- Raw Brier score
- Log loss
- Calibration intercept and slope
- Reliability analysis
- Weekly and seasonal breakdowns
- Favorite/underdog breakdowns
- QB-certain/QB-uncertain breakdowns
- Block-bootstrap or equivalent uncertainty estimate

### Production design

Production is static HTML/CSS/JavaScript plus sanitized JSON served by Caddy.

The VPS will not retain:

- A permanent NFL Python environment
- Streamlit
- A Python web server
- Raw historical training data
- Model-training processes

### GitHub authority

GitHub holds the durable project state: contracts, source, compact frozen data, manifests, checksums, model artifacts, predictions, scorecards, static site source, generated public JSON, workflows, and deployment configuration.

Large raw archives may use GitHub Release assets when ordinary Git storage would be cumbersome.

## 4. High-level architecture

```text
GitHub repository
  |-- architecture and contracts
  |-- compact frozen data and manifests
  |-- implementation and tests
  |-- approved artifacts and evidence
  |-- static site and workflows
  |
  | temporary build
  v
Hermes disposable environment
  |-- verify/download data
  |-- build point-in-time features
  |-- train and walk-forward test
  |-- run untouched holdout
  |-- commit artifacts and evidence
  |-- remove temporary venv and raw data

GitHub Actions twice daily
  |-- load approved artifact
  |-- resolve schedule and QB status
  |-- fetch current odds
  |-- score slate and calculate EV
  |-- write versioned public JSON
  |-- deploy static bundle
  v
VPS Caddy static file server
  v
nfl.tkhermes.duckdns.org
```

## 5. Data policy

The NFL has approximately 272 regular-season games in a current season, not 272 games total. Multi-season game-level and weekly model tables should remain compact. Full play-by-play archives may be materially larger.

Commit compact auditable data directly:

- Game results and schedule rows
- Team-week features
- QB-week features
- Starting-QB mappings
- Model-ready game rows
- Deterministic fixtures
- Manifests, checksums, data dictionaries, and row-count reports

Measure compressed raw archive size before deciding repository versus GitHub Release storage.

Frozen historical files are immutable. Revisions receive a new retrieval timestamp, checksum, manifest entry, and derived data version.

## 6. Point-in-time contract

Every prediction row carries:

```text
game_id
as_of_utc
scheduled_start_utc
data_version
feature_version
model_version
```

All inputs satisfy:

```text
observed_at_utc <= as_of_utc
```

Completed-game statistics satisfy:

```text
game_end_utc < as_of_utc
```

Required leakage tests:

1. Future-row poisoning test.
2. Same-game exclusion test.
3. One-second cutoff-boundary test.
4. Closing-line prohibition test.
5. Deterministic replay test.
6. Held-out-season isolation test.

## 7. Starting-quarterback policy

Resolve starters in this order:

1. Latest timestamped depth-chart information available before `as_of_utc`.
2. Available official game-status information.
3. Timestamped manual override for confirmed starter news.
4. Explicit uncertain-starter state.

When uncertainty is material, score QB1 and QB2 scenarios, display both, and suppress the official pick when the configured probability difference is too large.

Low-sample quarterback performance must be strongly shrunk toward a conservative prior. One game may not create an extreme lasting adjustment.

## 8. Backtest design

Use expanding weekly walk-forward validation. Random splitting is prohibited.

For each historical week:

```text
train only on prior information
-> generate base-model predictions for that week
-> permanently store the predictions
-> advance to the next week
```

The stacker trains only on stored out-of-sample development predictions.

The intended untouched holdout is the 2025 season unless the data audit identifies a documented reason to use another isolated period.

Holdout procedure:

1. Finish contracts, feature selection, and tuning on development seasons.
2. Generate development walk-forward predictions.
3. Train the stacker on out-of-sample development predictions.
4. Freeze the full model contract.
5. Run the holdout sequentially week by week.
6. Publish the complete result before any retuning.
7. After acceptance, retrain through the holdout for 2026 live use.

## 9. Acceptance gates

### Gate 1 — data integrity

- Manifests and checksums complete
- Point-in-time and leakage tests pass
- Predictions reproduce deterministically
- QB uncertainty is explicit
- No market or closing-line feature exists

### Gate 2 — base-model proof

Separate scorecards for QB-Elo, XGBoost, and opponent-adjusted expected margin.

### Gate 3 — stacker proof

The stack must improve on the best base model or provide a clearly defensible calibration improvement.

### Gate 4 — untouched holdout

Publish the complete holdout result without selective omission.

Possible verdicts:

- `MODEL_VALIDATED`
- `MODEL_PROMISING_BUT_UNPROVEN`
- `MODEL_FAILED_BASELINE`

A simpler approved base model may proceed if the stack fails.

### Gate 5 — live-product authorization

Live scoring and public deployment begin only after an explicit decision following Gates 1–4.

## 10. Live scoring and picks

Run two scheduled refreshes:

- 12:00 PM Eastern
- 11:58 PM Eastern

Every run records actual `observed_at_utc` and all version identifiers.

Live flow:

```text
approved model
-> current schedule and QB status
-> point-in-time football features
-> independent win probability
-> current DK/FD/Pinnacle prices
-> expected value and eligibility
-> versioned public JSON
-> static deployment
```

High-hit-rate pick: highest qualifying model probability with an actionable DK or FD price, positive EV, and acceptable QB certainty.

Best-EV pick: highest qualifying expected value subject to configured probability, edge, price, and QB-certainty thresholds.

The system must support `No qualifying play at current prices.`

Pinnacle is display/reference only, not a model feature or approval metric.

## 11. Static publication

The publication pipeline writes a versioned file such as `site/public/data/latest.json` containing:

- Generation and as-of timestamps
- Data, feature, model, schedule, and odds versions
- Current games and probabilities
- Book prices
- QB status
- EV and eligibility
- High-hit-rate and best-EV selections
- Warnings and explanation fields

The browser may recalculate EV from manual odds, but it may not call secret-bearing APIs.

## 12. Correct build order

### Phase 0 — architecture lock

Deliver contracts, repository structure, configuration shells, and bounded Hermes task definitions.

Exit: `ARCHITECTURE_AND_CONTRACTS_LOCKED`

### Phase 1 — frozen data acquisition and audit

Inventory sources, measure archive sizes, choose repository versus Release storage, write manifests/checksums, produce compact baseline tables and deterministic fixtures, and report gaps.

Exit: `FROZEN_DATA_BASELINE_PROVEN`

### Phase 2 — data and feature pipeline

Hermes implements readers, normalization, team/QB features, starter resolution, `as_of_utc`, deterministic rows, and leakage/contract tests. No full model training.

Exit: `DATA_AND_FEATURE_CONTRACT_PROVEN`

### Phase 3 — base models and walk-forward engine

Hermes implements QB-Elo, opponent-adjusted margin, regularized XGBoost, the weekly runner, prediction ledger, and base-model scorecards.

Exit: `BASE_MODELS_AND_WALK_FORWARD_PROVEN`

### Phase 4 — stacker and untouched holdout

Hermes implements the logistic stacker, justified calibration only, complete development and holdout scorecards, uncertainty analysis, and the approved artifact when warranted.

Exit: one of the three model verdicts.

### Phase 5 — live scoring and public JSON

Hermes implements approved-artifact loading, current schedule/QB resolution, twice-daily odds, EV, eligibility, no-play handling, prediction ledger, JSON, workflows, and end-to-end tests.

Exit: `LIVE_SCORING_AND_PUBLICATION_PROVEN`

### Phase 6 — static deployment plumbing

Hermes proves restricted static deployment, the isolated Caddy site, rollback, scheduling, and non-interference. The site may remain visually plain.

Exit: `STATIC_DELIVERY_PATH_PROVEN`

### Phase 7 — final JavaScript design and implementation

Todd and the project assistant decide the final design. Hermes implements it only after upstream contracts are stable.

Exit: `FINAL_STATIC_UI_PROVEN`

### Phase 8 — production proof and cleanup

Hermes proves the full scheduled path, public URL, versions, rollback, documentation, unrelated-service safety, and removal of temporary NFL environments and raw data.

Exit: `NFL_EDGE_PRODUCTION_COMPLETE`

## 13. Division of work

### Project assistant

- Maintain architecture and contracts
- Set up repository structure
- Define schemas, acceptance gates, and Hermes task boundaries
- Organize frozen source data where practical
- Review reports and implementation against contracts
- Prevent scope drift
- Lead final interface design with Todd after the pipeline is proven

### Hermes

- Production implementation within approved boundaries
- Tests and detailed proof
- Data transformations and feature pipeline
- Training, walk-forward backtest, and holdout
- Artifacts and scoring workflow
- Static publication and deployment
- Final JavaScript implementation after design approval
- Cleanup of temporary environments and data

Hermes does not independently redesign the project.

### Todd

- Approve major phase transitions
- Supply or authorize secrets
- Approve final visual design
- Decide whether evidence is strong enough for wagering use
- Decide whether to continue, simplify, or stop after weak results

## 14. Hermes task rules

Every task must state repository, branch, expected starting state, exact scope, prohibited scope, allowed paths, required tests, required artifacts, final verdict, cleanup, and report format.

Hermes must stop rather than improvise when a contract is ambiguous, required data is unavailable, checksums fail, leakage is detected, the holdout is exposed, unrelated services would be affected, or architecture would need to change.

Every report must include starting/final Git state, files changed, test commands and complete counts, data row counts and checksums, model metrics when applicable, artifact paths and sizes, prohibited actions not taken, cleanup, limitations, and the recommended next phase without beginning it.

## 15. Version 1 exclusions

- Player props
- In-game betting or live win probability
- Same-game parlays
- Automated wager placement
- User accounts
- Permanent database server
- Permanent Python web backend
- Streamlit
- CLV-based approval
- Sportsbook prices as model features
- Final UI design before model validation
- Unnecessary microservices or extra models

## 16. Simplicity rules

1. Prefer deterministic files over databases when practical.
2. Prefer one scoring workflow over overlapping jobs.
3. Prefer one approved artifact over runtime model selection.
4. Prefer simple stacking over clever blending.
5. Prefer explicit no-play states over forced recommendations.
6. Prefer a smaller proven feature set over a large fragile one.
7. Prefer static publication over a permanent app server.
8. Prefer narrow Hermes tasks over a broad full-project prompt.
9. Stop at failed acceptance gates instead of continuing automatically.
10. Keep interface design separate from model research.

## 17. Immediate next action

Complete Phase 0 and Phase 1 preparation. Do not begin polished site design or full model coding until the contracts and frozen-data baseline are accepted.
