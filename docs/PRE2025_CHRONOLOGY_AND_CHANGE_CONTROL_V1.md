# NFL EDGE — 2025 Chronology and Post-Holdout Change Control V1

## Purpose

Freeze the simulated-live chronology contract and the only permissible post-holdout correction path before 2025 is opened.

## Chronological block contract

Authoritative progress unit: one NFL `(season, season_type, week)` block.

Stable ordering:

1. season
2. season-type priority (`REG`, `WC`, `DIV`, `CON`, `SB`)
3. week
4. scheduled start UTC
5. game ID as deterministic final tie-breaker

For each 2025 block:

1. establish the block-start football/model state using only information available before the block
2. establish the pregame sportsbook snapshot under the frozen T-60 acquisition policy
3. materialize football predictions for the full block
4. build market anchors and exact DK/FD actionable offers
5. evaluate all exact offers through the frozen Task05F public evaluator path
6. assign support/reliability exactly once per evaluation
7. build the common candidate table
8. apply Model Confidence V2 where frozen
9. apply Spread Confidence V3 where frozen
10. apply the frozen Value-family/state logic
11. select Hit Rate, Balanced, and Value
12. apply headline actionability and recommended units without reranking/reselecting
13. calculate all five profile dollar stakes
14. enforce duplicate-wager and wager/slate caps
15. freeze the complete week product and its deterministic hash
16. only after that freeze, admit that block's outcomes
17. grade the frozen recommendations
18. advance evaluator reliability, model-confidence history, spread-confidence history, Value state, model state, and bankroll state causally for later blocks only

## Same-block firewall

No prediction or recommendation in a block may observe any outcome from another game in the same block. The entire block is predicted first and updated second.

Changing a later block's outcome must not alter any earlier block's frozen product hash.

## Outcome separation

Pregame materialization and outcome grading are separate surfaces. The future runner must never preload the full 2025 outcome table into memory before producing all pregame recommendations.

The authorization gate must be passed before the first 2025 data read. The one-shot spend marker must prevent an ordinary second execution of the untouched holdout.

## Frozen-methodology rule

The holdout may advance state according to already-frozen causal update rules. It may not refit methodology by choosing new formulas, parameters, thresholds, model families, selector families, odds bands, staking rules, or product states from observed 2025 performance.

## Allowed post-holdout change

Only a methodology-preserving implementation defect may be corrected.

A qualifying defect is something such as:

- wrong field wired into the intended frozen formula
- orientation/sign bug contrary to the frozen contract
- serialization bug that drops valid frozen output
- deterministic ordering bug contrary to the chronology contract
- incorrect import/export path causing the wrong already-frozen implementation to execute

A poor betting result is not an implementation defect.

## Required defect procedure

If a qualifying defect is found after opening 2025:

1. preserve the original 2025 run and hashes permanently
2. document the exact defect and why it violates the pre-holdout contract
3. prove the correction restores, rather than changes, the intended methodology
4. create a new versioned implementation freeze
5. rerun transparently as an implementation-correction rerun
6. report both original and corrected artifacts

## Prohibited post-holdout changes

Do not change:

- football-model hyperparameters or features
- evaluator formulas, shrinkage, calibration, or support thresholds
- trust/confidence formulas or thresholds
- selector families, eligibility, ranking, odds bands, or quality floors
- recommended-unit ladder
- risk-profile percentages
- bankroll rounding/floors/caps
- Play Through corridor
- Value-at/Value-through semantics
- market families
- team/season filters
- retrospective performance buckets
- any rule whose purpose is to improve the observed 2025 result

## Result interpretation

The holdout answers whether the frozen product behaved usefully and honestly in a genuinely untouched season. It is not permission to mine the season for a better product after the fact.
