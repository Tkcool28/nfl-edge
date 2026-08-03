# Architecture Contract

## Status

Authoritative for Version 1.

## System boundary

NFL Edge has four durable layers:

1. **Frozen evidence** — versioned historical inputs, manifests, checksums, and deterministic fixtures.
2. **Research pipeline** — point-in-time features, model training, walk-forward predictions, holdout evaluation, and approved artifacts.
3. **Scoring/publication pipeline** — current schedule and QB resolution, independent model probability, current odds, EV, eligibility, and public JSON.
4. **Static product** — HTML/CSS/JavaScript served through Caddy.

## Trust boundaries

### GitHub repository

Authoritative for contracts, code, compact data, manifests, artifacts, predictions, scorecards, workflows, site source, and deployment configuration.

### Hermes environment

Disposable implementation and training environment. It may download large raw data, build artifacts, and run tests. Temporary virtual environments and raw local data are removed after final proof.

### GitHub Actions

Trusted scheduled scoring environment. Secrets remain in workflow secret storage. Public outputs contain no secret material.

### VPS

Static hosting target only. It receives generated website files and sanitized JSON. It does not train models, score games, fetch secret APIs, or run an NFL Python service.

## Required data flow

```text
frozen historical evidence
-> point-in-time feature rows
-> out-of-sample base-model predictions
-> stacker and holdout
-> approved model artifact
-> current point-in-time scoring
-> current odds and EV
-> versioned public JSON
-> static site deployment
```

## Forbidden architecture

- Streamlit or another permanent Python web application on the VPS
- Market prices inside the football model
- Training directly against the untouched holdout during development
- Runtime model selection based on current game outcomes
- Public browser access to secret-bearing APIs
- Hidden mutable files on the VPS as the authoritative project state
- Untracked manual production changes that cannot be reconstructed from GitHub

## Repository ownership

- `docs/`: human-readable contracts
- `config/`: reviewed behavior and thresholds
- `data/manifests/`: source identity and checksums
- `data/frozen/`: compact immutable historical tables
- `data/fixtures/`: tiny deterministic test data
- `src/nfl_edge/data/`: acquisition and normalization
- `src/nfl_edge/features/`: point-in-time feature construction
- `src/nfl_edge/models/`: base models and stacker
- `src/nfl_edge/backtest/`: walk-forward and evaluation
- `src/nfl_edge/scoring/`: current slate scoring and eligibility
- `src/nfl_edge/publication/`: public-schema generation
- `artifacts/`: versioned models, predictions, and scorecards
- `site/`: final static product
- `deploy/`: static delivery and Caddy configuration
- `tests/`: contract, leakage, unit, integration, and end-to-end proof

## Change control

Architecture changes require:

1. A documented reason.
2. Identification of affected contracts.
3. Updated tests and migration consequences.
4. Explicit approval before implementation.

Implementation convenience alone is not sufficient to bypass a contract.
