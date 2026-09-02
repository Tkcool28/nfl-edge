# NFL EDGE — Post-V5 Prelaunch Architecture V2

## Status

`POST_V5_PRELAUNCH_SUCCESSOR_IMPLEMENTED__V5_REMAINS_IMMUTABLE_EVIDENCE`

This document records the bounded successor architecture created after the
completed `2025-standard-eval-v5` diagnosis. It does **not** rewrite, rerun, or
reinterpret V5 as a new untouched holdout.

## Change-control boundary

V5 exposed architecture/product behavior. The successor therefore:

- preserves all V5 artifacts;
- preserves `final_selectors_v1.py`, the package-root V1 recommendation route,
  and the frozen XGBoost V1 engine/adapter;
- does not acquire new market data;
- does not call the Odds API;
- does not rerun 2025 to choose thresholds;
- does not retune HHR, Value, Task05F, Spread Confidence V3, or XGBoost model parameters;
- treats any 2025 comparison from this point onward as diagnostic only.

The next pristine forward acceptance must use genuinely unseen future data.

## 1. Balanced V2

Balanced is the app's bread-and-butter lane: more hit-rate oriented than Value,
but at a genuinely bounded price rather than HHR-style heavy juice.

### Moneyline

- Task05F supported + model-confidence supported;
- model-confidence `q >= 0.52`;
- **short true favorites only: -130 through -100**;
- Pinnacle/no-vig anchor probability must be `>= 0.50` for the selected side;
- negative retail odds alone do not establish favorite status because both sides
  can be juiced around pick'em;
- plus-money ML is excluded from Balanced;
- no strict +EV requirement;
- no VALUE/PLAYABLE requirement;
- no positive model-price-gap requirement;
- existing market-half trust is retained.

This places heavier favorites in HHR, rejects retail-juiced sides that remain
sharp-market underdogs, and leaves plus-money ML primarily to Value rather than
allowing either to dominate the Balanced card.

### Spread

Balanced spread eligibility is market-specific rather than reusing the ML
`q >= .52` gate.

Required:

- Task05F supported;
- Spread Confidence V3 supported;
- `q >= 0.50` neutral sanity floor;
- `SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4` model-candidate provenance;
- positive `model_cover_margin_v3` for the selected side;
- price no worse than -130;
- no strict +EV requirement.

Spread Confidence V3 remains the honest probability/trust layer. Raw Expected
Margin magnitude is not maximized and the old 75-85% spread-confidence behavior
is not restored.

### Cross-market ranking

Raw ML cash probability and spread cover probability are not compared as if
they live on an identical scale.

Balanced V2 ranks a deterministic probability-first utility:

`selector_trust - max(break_even_probability - 0.50, 0)`

This is a **juice penalty, not an EV gate**. Negative utility remains eligible.
EV, price status, and model-price-gap are not ranking objectives. The rule lets
a properly calibrated ~50-51% spread compete with a short ML favorite without
requiring the spread calibrator to manufacture 55%+ confidence.

### Descriptive replay only

`scripts/post_v5_balanced_v2_diagnostic.py` replays the already-exposed
2020-2024 V3 evidence table after the V2 contract is fixed. Its purpose is to
prove mechanical viability, market mix, coverage, price bounds, and product
invariants. Its hit rate/ROI are descriptive only and **cannot** be used to
retune the -130 cap, 50% sharp-favorite gate, spread floor, or ranking formula.
2025 is hard-forbidden from this diagnostic.

### Forward application API

The frozen package root `nfl_edge.recommendation` remains V1 because existing
freeze/replay contracts assert that historical routing. New application code
must import `nfl_edge.recommendation.live_v2`, which exposes Balanced V2 while
delegating HHR and Value to the unchanged V1 selector implementations and
reusing the unchanged staking/risk-profile surface.

This explicit version boundary prevents a launch correction from silently
rewriting the V1/V5 replay API.

## 2. XGBoost validation-tail V2

The frozen V1 model parameters and feature contract remain unchanged.

V1 reserved exactly the two most recent prior blocks as the early-stopping
validation tail. At a season boundary those blocks can be the Conference
Championship and Super Bowl, producing only a few validation games despite many
seasons of available fit history.

V2 changes only split construction:

1. start with the most recent strictly-prior block;
2. expand backward through a contiguous recent tail;
3. stop as soon as the existing validation gates are met:
   - at least 2 validation blocks;
   - at least 21 validation rows;
4. never consume rows/blocks needed by the existing fit gates:
   - at least 2 fit blocks;
   - at least 32 fit rows;
5. current/future blocks remain forbidden;
6. if history is genuinely insufficient, retain fail-closed warm-up behavior.

This removes the artificial annual Week 1 cold start without changing model
parameters, using current-season outcomes, or weakening chronology.

### Launch-facing live path

The adaptive split is not limited to the old 2025 holdout harness.
`src/nfl_edge/models/xgboost_live_v2.py` is season-agnostic and explicitly
supports live 2026+ blocks. It keeps the accepted 2018-2024 feature/categorical
contract while allowing already-settled later seasons to enter strictly-prior
training history. It rejects current/future history and any current-block
revealed outcome.

The focused regression suite explicitly constructs a 2026 Week 1 block with a
small 2025 Conference/Super Bowl tail and proves V2 produces a prediction rather
than an artificial warm-up.

`src/nfl_edge/holdout/xgboost_2025_v2.py` remains a separate 2025-specific proof
adapter so V5-era chronology can be regression-tested without making the launch
path 2025-specific.

## 3. Explicitly unchanged

- HHR selector: V1 HALF_SHRINK unchanged.
- Value selector: V1 strict +EV/family-trust policy unchanged.
- Task05F evaluator: unchanged.
- Spread Confidence V3 calibrator: unchanged for launch.
- Expected Margin model and 0-4 candidate definition: unchanged.
- staking/risk profiles/Play Through: unchanged.
- `nfl_edge.recommendation` package-root V1 route: unchanged.
- V5 artifacts and run identity: unchanged.

## 4. Launch integration surface

Successor implementations:

- `src/nfl_edge/recommendation/final_selectors_v2.py`
- `src/nfl_edge/recommendation/live_v2.py`
- `config/task05g_final_selectors_v2.yaml`
- `src/nfl_edge/backtest/xgboost_walk_forward_v2.py`
- `src/nfl_edge/models/xgboost_live_v2.py`
- `src/nfl_edge/holdout/xgboost_2025_v2.py`
- `config/xgboost_validation_tail_v2.yaml`

The V1 modules remain historical replay authorities. New launch/live wiring
must explicitly consume the V2 surfaces rather than silently mutating V1 imports.
