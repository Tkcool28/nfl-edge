# Task 05C — Totals V1 Feature Redundancy Report

**DESCRIPTIVE / NO PRUNING.** This report identifies conceptual redundancy groups
among the accepted CORE_V1 features. No features are deleted or changed. No model
is fit. No target performance is used to select features.

## Accepted contract decisions already frozen in Phase 2

The contract explicitly deferred or excluded certain redundant families rather than
carrying duplicates:

| Redundant pair | Decision |
|---|---|
| Interception rate (PBP) vs Turnover rate vs QB interception rate | Interception rate DEFERed; turnover rate INCLUDE V1; QB interception rate in V1 via accepted Oracle |
| Lost-fumble rate (PBP) vs Turnover rate | Lost-fumble rate DEFERed; turnover rate INCLUDE V1 |
| QB hits/dropback vs Pressure/hurry vs Sacks/dropback | QB hits DEFERed; pressure/hurry REJECTed; sacks/dropback INCLUDE V1 |
| Weekly frozen EPA/CPOE/attempts direct columns vs PBP-derived rates | Direct column representations DEFERed; PBP rates are the selected canonical V1 representation |
| Lagged snap participation (player-selection) vs team-level PBP rates | Snap participation DEFERed |
| Scored points/drive vs scoring-drive rate vs EPA/play | All three INCLUDE V1 (different signal: raw scoring vs efficiency vs efficiency-plus-field-position) |

## Conceptual overlap groups in CORE_V1

### Group 1: EPA/play ↔ Success rate
Both are aggregated efficiency measures from the same VFP play population.
- `epa_per_play` captures expected-points-added efficiency
- `success_rate` captures binary outcome success (positive EPA)
EPA is a continuous magnitude measure; success rate is a binary consistency measure.
Keep both.

### Group 2: Points/drive ↔ Scoring-drive rate ↔ Scoring history
All three measure scoring efficiency from possession outcomes.
- `points_per_drive`: total offensive points per possession (magnitude)
- `scoring_drive_rate`: TD-or-FG rate (binary)
Points/drive is a superset of scoring-drive rate + TD/FG value differentiation, but
the binary rate captures different game-level signal.

### Group 3: Turnover rate ↔ Interception/sack benchmarks
Turnover rate captures all TOs per drive (INT + fumble lost). QB interception rate and
sacks/dropback provide driver-level decomposition. Not strictly redundant: QBs affect
INT/sack rates independently of team turnover environment.

### Group 4: Air yards/attempt ↔ YAC/completion
Both passing-depth measures but orthogonal: air yards measure downfield intent,
YAC measures receiver/after-catch effectiveness. Complementary, not redundant.

### Group 5: Red-zone TD rate ↔ Goal-to-go TD rate
Goal-to-go is a strict subset of red-zone opportunities (pre-play yardline <= 2).
Goal-to-go rates have smaller sample (higher missingness) but capture conversion
efficiency inside the 2-yard line — a different game-management signal.

### Group 6: Neutral pass rate ↔ Explosive pass rate
Neutral pass rate captures pass/run balance in neutral game script; explosive pass
rate captures big-play frequency through the air. Different axes of passing
environment.

### Group 7: Seconds/play ↔ Neutral seconds/play
Neutral seconds/play is a strict subset (clock intervals where the prior play was
neutral). Provides pace-in-neutral-script signal. Not redundant: game-script-dependent
pace differs materially.

### Group 8: Explosive pass rate ↔ Explosive rush rate
Different play types, independent signal sources.

## Summary

No conceptual redundancy in CORE_V1 is strong enough to justify pre-modelling
pruning. The accepted 90 features contain intentional complementary metrics
(efficiency magnitude + binary, raw scoring + rate, passing depth + YAC,
script-dependent pace + neutral pace). All retained CORE_V1 features should be
presented to later bake-off models without pre-pruning.

*This is a DESCRIPTIVE report only. No model fitting, no target performance
evaluation, and no feature deletion occurs here.*