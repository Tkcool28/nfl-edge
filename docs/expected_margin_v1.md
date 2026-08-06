# Expected-Margin v1 (Task 03B)

Model **expected_margin_v1.0.0**, selected candidate **stable**.
Code commit `3913ca371b917590ee25b330ab8641696d6a19e0` · Configuration SHA `37df479ab032784825e88e40010e65a84a983a832cf51ad9ca78080362dcfd18` · Verdict: **EXPECTED_MARGIN_V1_IMPLEMENTED_BUT_WEAK**.

## Scoring formulation
Two-observation scoring design. For each completed training game the model emits two
observations:
- Home scoring observation: `target = actual_home_points`; `prediction = league_baseline + hfa + home_off - away_def`.
- Away scoring observation: `target = actual_away_points`; `prediction = league_baseline + away_off - home_def`.

Both are fitted jointly with a single recency-weighted ridge linear regression.

## Offense and defense signs
Positive offensive strength ⇒ expected to score above league baseline. Positive defensive
strength ⇒ expected to allow fewer opponent points (stronger defense); opponent's expected
points are reduced.

## Sum-to-zero identification
A deterministic reduced parameterization (reference team pinned to offense=defense=0 inside
the linear system) plus post-fit centering forces `sum(offense)=0` and `sum(defense)=0`, with
the league baseline adjusted by the centering offset. The fit is prediction-invariant.

## Ridge objective
Regularized least squares with L2 penalties on offense, defense, and home-field effects, a
soft L2 prior on the fitted league baseline, and a small soft sum-to-zero penalty. The
logistic margin→probability mapping is L2-regularized and fit only on prior out-of-sample rows.

## Recency policy
Exponential decay `w = 0.5 ** (age / half_life)`, keyed by chronological completion order.
`recency_half_life_games = 16.0` for stable.

## Warm-up rules
- Team-strength warm-up: fewer than 64 training games before a block ⇒ `prior_games_warmup`, no numeric margin.
- Mapping warm-up: fewer than 256 prior OOS rows ⇒ `mapping_warmup = true`, no official probability.

## Prior-OOS mapping
The logistic mapping is fit only on prior out-of-sample rows; the current block is excluded
from its own mapping fit. No in-sample leakage.

## Neutral-site handling
`neutral_site = true` removes the home-field effect from the home scoring observation.
(Neutral n=33 Brier 0.24353.)

## Tie handling
`tie_policy = exclude` for the binary mapping and official binary scoring; ties remain in the
scoring-model fit (both home and away points are valid targets).

## Three-candidate policy
Three locked candidates (responsive, balanced, stable), predeclared and frozen in
`config/expected_margin_v1.yaml` before comparison. No fourth candidate tested.

## Stable selection
Selected for lowest Brier, lowest log loss, lowest margin MAE/RMSE, the only positive
calibration slope, the largest usable scored-row count, and the best early/later and
season-to-season stability. See scorecard and tuning ledger.

## Weak-model verdict
**EXPECTED_MARGIN_V1_IMPLEMENTED_BUT_WEAK.** On 1,593 common rows vs QB-Elo: expected-margin Brier 0.248562 vs QB-Elo
0.222809 (Brier Skill Score −0.1156); log loss 0.690279 vs 0.637340 (+0.0529 worse); accuracy
0.541745 vs 0.637790. Bootstrap (week blocks, seed 20260802, 1000 resamples): never beats
QB-Elo on Brier or log loss (0.0%). Expected-Margin v1 is weaker than QB-Elo as a
win-probability model.

## Holdout isolation
2025 is the sealed holdout; 2026+ are forward-use. Both are rejected/excluded at the
extraction boundary before any fitting, prediction, mapping, or evaluation. 2025 was never
admitted to any model frame.

## Market prohibition
The model reads no market/odds data; no market fields appear in any ledger or artifact.

## QB-certainty limitation
The QB-certainty field in the QB-Elo ledger is `UNKNOWN` for every row; no certainty
breakdown is possible.

## Future follow-up (recorded, not started)
Expected-Margin v1 should later be evaluated separately as an expected-points and game-totals model. Its weak win-probability performance does not by itself establish whether its home-points, away-points, or total-points estimates have useful predictive value. That totals evaluation is outside Task 03B and must use a separately authorized leakage-safe scoring contract.
