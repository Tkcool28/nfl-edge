# Expected-Margin v1 (Task 03B)

Model **expected_margin_v1.0.0**, corrected selected candidate **stable**.
Code commit `1b3d23b7bc9c09da6514b4da0a9ef584883d18a6` · Configuration SHA `37df479ab032784825e88e40010e65a84a983a832cf51ad9ca78080362dcfd18` · Verdict: **EXPECTED_MARGIN_V1_IMPLEMENTED_BUT_WEAK**.

## Scoring formulation
Two-observation scoring design. For each completed training game the model emits two observations:
- Home: `target = actual_home_points`; `prediction = league_baseline + hfa + home_off - away_def`.
- Away: `target = actual_away_points`; `prediction = league_baseline + away_off - home_def`.

Both are fitted jointly with a single recency-weighted ridge linear regression.

## Offense and defense signs
Positive offensive strength => expected to score above league baseline. Positive defensive
strength => fewer opponent points allowed (stronger defense).

## Identifiability (no reference team)
There is NO alphabetical reference team. All team effects are fitted symmetrically with their
declared ridge priors; after the closed-form solve the offense and defense vectors are CENTERED
so `sum(offense)=0` and `sum(defense)=0`, and the league baseline is adjusted. The centering is
prediction-invariant (team naming and ordering do not change any prediction). The previous
hand-added soft diagonal is removed: symmetric ridge fit followed by prediction-invariant
post-fit centering is the identification method.

## Recency
Exponential decay `w = 0.5 ** (age / half_life)`. The NEWEST prior completed game has age 0
(greatest recency weight) and the OLDEST has age n-1 (corrected direction).

## Mapping
The logistic margin -> probability mapping is fit only on prior out-of-sample rows, excluding
ties and null binary outcomes. The official probability is available only when the mapping fit
is usable.

## Official scoring
A row is officially binary-scored only when the target is available, the game is not a tie, a
home-win probability is available, and the predicted probability is finite.

## Warm-up
- Team-strength warm-up: fewer than 64 training games before a block => `prior_games_warmup`.
- Mapping warm-up: fewer than 256 prior OOS rows => `mapping_warmup = true`.

## State ledger
`expected_margin_state_2018_2024.parquet` stores the complete fitted block state (team index,
full centered offense/defense vectors, baseline, HFA, candidate parameters, training counts,
mapping state, sums, solver status, fitted-state fingerprint) sufficient to reconstruct each
block's expected-points and expected-margin calculations without refitting.

## Three-candidate policy
Three locked candidates (responsive, balanced, stable), predeclared and frozen before comparison.
No fourth candidate and no post-result tuning. Selected **stable** (decisive).

## Weak-model verdict
**EXPECTED_MARGIN_V1_IMPLEMENTED_BUT_WEAK.** On 1593 common rows vs QB-Elo: EM Brier 0.238291
vs QB-Elo 0.222809 (BSS -0.069483); log loss 0.669988
vs 0.637340 (diff +0.032648); accuracy 0.601381
vs 0.637790. Bootstrap (seed 20260802, 1000): never beats QB-Elo on
Brier or log loss (0.0%). Expected-Margin v1 is weaker than QB-Elo as a win-probability model.

## Holdout isolation
2025 is the sealed holdout; 2026+ are forward-use. Both are rejected/excluded at the extraction
boundary before any fitting, prediction, mapping, or evaluation.

## Market prohibition
The model reads no market/odds data; no market fields appear in any ledger or artifact.

## Future follow-up (recorded, not started)
Expected-Margin v1 should later be evaluated separately as an expected-points and game-totals model. Its weak win-probability performance does not by itself establish whether its home-points, away-points, or total-points estimates have useful predictive value. That totals evaluation is outside Task 03B and must use a separately authorized leakage-safe scoring contract.
