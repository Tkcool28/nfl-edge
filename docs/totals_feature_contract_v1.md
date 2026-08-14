# Totals V1 Feature Contract

## Status and scope

This is a Phase 2 design contract only, pinned to canonical source commit
`bc1d85414dd2c7c8fafb572946706c1cc0394345`. It authorizes neither feature
implementation nor model training. Its development universe is NFL seasons
2018--2024 inclusive; the sealed holdout is NFL season 2025. Development code
must exclude every NFL `season == 2025` row at its boundary, before any feature
state or context join can consume it. This is an NFL-season rule, not a
calendar-year rule: season-2024 postseason games played in January/February
2025 are required development data. For example, `2024_22_KC_PHI`, played
`2025-02-09`, remains included because `season == 2024`. Approved input and
output filenames may contain `2018_2025`; no `year != 2025`, `game_date`, or
`gameday` calendar filter is authorized.

The persistent read-only PBP inputs are the seven independently promoted files
`/artifacts/raw/task05c_pbp_v1/play_by_play_{2018..2024}.parquet`. No PBP
acquisition is authorized. Before Phase 3 reads any file, its SHA-256 and byte
size must be verified against a separately supplied immutable promotion manifest;
this contract does not invent checksum or size values that it does not contain.

## Reused repository contracts and source interfaces

### Chronology and source availability

Reuse `WEEK_COMPLETE_TUESDAY_1200_UTC_V1` from
`src/nfl_edge/features/availability.py` and its availability table interface:
`season`, `season_type`, `week`, `prediction_as_of_utc`, and
`eligible_for_features_at_utc`. A completed game is source-eligible iff its
own canonical weekly `eligible_for_features_at_utc <= target
prediction_as_of_utc`; equality is eligible. This is the repository's
conservative weekly source-availability model, not an assertion of exact
kickoff or final-whistle time.

The canonical prediction block is exactly `(season, season_type, week)`, with
`block_id = "{season}_{season_type}_W{week:02d}"`, as defined by
`src/nfl_edge/backtest/blocks.py`. For each target game, the eligible game set
is additionally filtered to a strictly earlier block in canonical order:
`(season, REG/WC/DIV/CON/SB priority, week) < target block`. Thus no row in the
target block can update any other target-block row, even if the weekly source
boundary comparison would otherwise be equal. This is stricter than, and
compatible with, the existing availability rule. An implementation must build
one immutable team-state snapshot before emitting every game in a block, then
apply all completed target-block games only after that block is complete.

Canonical order is season ascending, then `REG`, `WC`, `DIV`, `CON`, `SB`, then
week ascending. Postseason blocks may consume all earlier regular-season blocks
of that season and earlier postseason blocks; they update only later postseason
blocks. They never update an earlier regular-season block. Prior-season history
is eligible subject to the aggregation rule below.

### Weekly/frozen sources reused rather than re-derived

* `data/frozen/games/games_2018_2025.parquet`: normalized `game_id`,
  `season`, `season_type`, `week`, `away_team`, `home_team`, `roof_type`, and
  `neutral_site_source`. The normalized canonical games table is the authority
  for canonical identity/block/team/roof mapping. PBP rows must join it by
  unique `game_id`; use the canonical game's `season`, `season_type`, `week`,
  `away_team`, and `home_team` for prediction-block identity and chronology.
  Raw PBP `season_type='POST'` is expected broad source semantics, never a
  canonical prediction block: map it through `game_id` to canonical `WC`,
  `DIV`, `CON`, or `SB`. Hard-fail on duplicate canonical `game_id`, an
  unmatched required PBP `game_id`, or conflicting NFL `season` values between
  PBP and canonical game rows. This follows the established Oracle-QB-v2
  canonical-game identity principle.
* Before any context join, project the raw/frozen schedule context path to only
  the approved identity/context fields needed for `game_id`, canonical NFL
  season/block identity where needed, `away_rest`, `home_rest`, `roof`, and
  `surface`. The Totals V1 intermediate context frame must not contain
  `away_score`, `home_score`, `result`, `total`, moneyline, spread, total-line,
  over/under-odds, historical QB IDs/names, `temp`, `wind`, or any other
  market/outcome/realized-weather/prohibited field. Prohibited fields may not
  merely be ignored at final selection. Exclude NFL `season == 2025` context
  rows at this development boundary before they can join or contribute state.
  The raw frozen schedule source additionally provides `away_rest`,
  `home_rest`, and `surface`; this contract uses only those accepted rest/roof/
  surface inputs.
* `data/frozen/team_game_stats/team_game_stats_2018_2025.parquet`: historical
  `passing_epa` and `rushing_epa` remain an audit cross-check only. PBP is the
  authoritative numerator/denominator source for V1 EPA/play; the weekly table
  cannot legitimately produce a play denominator.
* `data/frozen/qb_game_stats/qb_game_stats_2018_2025.parquet` is not used to
  rebuild QB state. The accepted derived Oracle interface below is reused.
* Frozen snap-count fields (`game_id`, `season`, `game_type`, `week`, `team`,
  `opponent`, `offense_snaps`, `offense_pct`, `defense_snaps`, `defense_pct`)
  are only completed-game evidence.

### Accepted Oracle QB entering-state v2 interface

Reuse, without changing its builder, the game-side artifact
`data/derived/oracle_qb_entering_state_v2/oracle_qb_entering_state_game_sides_2018_2024_v2.parquet` keyed uniquely by `(game_id, side)`. Totals V1 may join
only these numerical entering-state columns:

`passing_epa`, `passing_cpoe`, `sacks_suffered_rate`, `interception_rate`,
`recency_weighted_form`, and their explicit quality fields
`prior_dropback_or_attempt_volume`, `low_sample`, `missing_player_id`,
`passing_epa_imputed`, `passing_cpoe_imputed`, `sack_rate_imputed`, and
`interception_rate_imputed`.

Do not consume `qb_adjustment_elo`, `oracle_qb_adjustment_net`, actual-starter
names/IDs, or any QB-Elo code. The artifact's historical actual-starter labels
remain `POSTGAME_ACTUAL_STARTER_IDENTITY_ONLY`; that accepted Oracle
historical-development semantics is not a claim of live pregame starter
knowledge. Its numeric state is already constructed by
`build_qb_pregame_features`, uses prior eligible games, fixed configured priors,
250-dropback shrinkage, and 0.75 decay over the last eight eligible games.

## PBP semantic layer (all INCLUDE PBP rates)

PBP columns relied upon are: `game_id`, `season`, `season_type`, `week`,
`posteam`, `defteam`, `play_type`, `sp`, `play_deleted`, `aborted_play`,
`pass`, `rush`, `pass_attempt`, `rush_attempt`, `qb_dropback`, `sack`,
`qb_hit`, `complete_pass`, `epa`, `success`, `yards_gained`, `air_yards`,
`yards_after_catch`, `interception`, `fumble_lost`, `yardline_100`,
`goal_to_go`, `score_differential`, `game_seconds_remaining`,
`half_seconds_remaining`, `quarter_seconds_remaining`, `qtr`, `drive`,
`fixed_drive`, `fixed_drive_result`, and `play_id`.

The seven inspected PBP schemas contain every listed field with stable types.
`play_deleted` was always zero; nevertheless the predicate explicitly requires
zero. `aborted_play` has both zero and one and is excluded. `qb_hit` is a
nullable 0/1 event field; it is a hit event, not a pressure/hurry measurement.
`play_clock` is the literal string `"0"` in inspected seasons and is unusable.

`sp` is scoring-play metadata only; it never determines VFP membership or any
ordinary scrimmage eligibility predicate.

**Valid football play (VFP):** `posteam` and `defteam` non-null;
`play_deleted=0`; `aborted_play=0`; and `play_type` is `pass`, `run`,
`qb_kneel`, or `qb_spike`. `no_play` rows, kickoffs, punts, field goals, extra
points, two-point attempts, timeouts, quarter markers, and all non-VFP rows
are excluded. A penalty-bearing row is not categorically excluded: it remains
only if it satisfies the exact VFP predicate and the metric-specific rule below.
Thus a penalty-only/no-play row is excluded by its source play classification,
not an undefined generic penalty predicate.

**Metric-specific PBP denominators and nulls:** no missing observation is
silently converted to zero. EPA/play uses VFPs with non-null `epa`: numerator
is `sum(epa)` and denominator is the count of those rows. Success rate uses
VFPs with non-null `success`: numerator is `sum(success)` and denominator is
the count of those rows. Neither metric requires the other field to be
non-null. Sacks are included in these metrics when the source flags them as a
valid scrimmage pass play.

**Pass attempts/completions:** VFP with `pass_attempt=1` (attempt); completion
also requires `complete_pass=1`. These event flags are non-null qualifying
population predicates; a row missing a required predicate is not counted.
Sacks are excluded from pass attempts.
**Rush attempts:** VFP with `rush_attempt=1`; kneels are excluded from all rush
and explosive-rush rates even if a source flag is present. **Dropbacks:** VFP
with `qb_dropback=1`; fallback only for a source-null `qb_dropback` is
`pass_attempt=1 OR sack=1`. The fallback is recorded in provenance.

**Neutral situation:** VFP in quarters 1--3, `abs(score_differential) <= 8`,
and `game_seconds_remaining >= 900`. The score is the pre-play offensive
score differential. This deliberately excludes all fourth-quarter plays.

**Red-zone opportunity:** a VFP whose pre-play `yardline_100 <= 20`; one
opportunity per `(game_id, fixed_drive, posteam)`, counted once at that drive's
first qualifying VFP. A red-zone TD is an opportunity drive whose
`fixed_drive_result='Touchdown'`. The same drive result is applied to the
opponent defensive perspective. Red-zone efficiency is TD opportunities / all
such opportunities, not TDs / plays.

**Goal-to-go opportunity:** one per `(game_id, fixed_drive, posteam)` when at
least one VFP in the drive has `goal_to_go=1`; numerator is that drive ending
`Touchdown`. It is a subset defined by the source flag, not by an inferred
yardline.

**Drive/possession:** one offensive possession per non-null `(game_id,
fixed_drive, posteam)` containing at least one VFP. Exclude drive groups with
no VFP, and exclude a group from all drive denominators if `fixed_drive_result`
is null. Points are 7 for `Touchdown`, 3 for `Field goal`, 2 for `Safety`, and
0 for `Punt`, `Turnover`, `Turnover on downs`, `Missed field goal`, `End of
half`, or `Opp touchdown`. `Opp touchdown` is zero offensive points (the
opponent's defensive score is not attributed to this possession). Points/drive
is sum of these points / included possessions; scoring-drive rate is possessions
ending `Touchdown` or `Field goal` / included possessions.

**Pace / seconds per play:** do not use `play_clock`. Derive `game_half` from
`qtr` exactly: first half for `qtr in {1,2}`, second half for `qtr in {3,4}`;
overtime is its own non-pairable half class. For each consecutive pair
of included VFPs on the same `(game_id, fixed_drive, posteam)`, ordered by
`play_id`, use `delta = prior game_seconds_remaining - current
game_seconds_remaining` only when both values are non-null, both plays are in
the same `qtr` and derived `game_half`, `delta >= 0`, and `delta <= 120`. The prior play is
the denominator play; the final play has no following interval. Exclude pairs
whose prior or current play is a spike, kneel, `no_play`, or non-VFP, or crosses
a quarter, half, overtime, or game boundary. A penalty-bearing VFP is retained;
there is no generic penalty filter. Exclude zero-second and
>120-second deltas (stoppages/recording edge cases). Seconds/play is
`sum(delta) / count(delta)`. Neutral seconds/play additionally requires the
prior play to meet the neutral definition. Defensive pace exposure is exactly
the opponent offense's same rate while that team is `defteam`; it is not a
claim that the defense controls elapsed time.

**Explosives:** pass is `yards_gained >= 20` on a pass attempt with non-null
`yards_gained`; rush is `yards_gained >= 10` on a rush attempt after kneel
exclusion with non-null `yards_gained`. Each denominator is its qualifying
attempt population with non-null `yards_gained`; null `yards_gained` is neither
zero nor an event.

**Turnovers:** offensive turnover is `interception=1` on a pass attempt or
`fumble_lost=1` on a VFP. Each qualifying play counts once even if both flags
are set. Turnover-on-downs is explicitly excluded from turnover rates because
PBP exposes it reliably at drive-result level, not as a player-play turnover
flag, and it has different semantics. Interception rate is interceptions / pass
attempts; lost-fumble rate is lost fumbles / VFP. For the selected V1 column,
turnovers/drive is total turnovers / included possessions.

**Sacks and hits:** sacks/dropback uses `sack=1 / dropbacks`. Offensive is
sacks suffered; defensive is sacks recorded against the opponent. `qb_hit` is
not selected for V1: if ever enabled its name must be `qb_hits_per_dropback`
or `qb_hits_allowed_per_dropback`, never pressure or hurry.

**Exact selected-family numerator/denominator/null rules:** EPA/play and
success rate are as defined above. Air yards/attempt has numerator
`sum(air_yards)` over qualifying pass attempts with observed `air_yards`, and
that same observed-air-yards attempt count is its denominator; null `air_yards`
is excluded, never zero. YAC/completion has numerator `sum(yards_after_catch)`
over qualifying completed passes with observed `yards_after_catch`, and that
same observed-YAC completion count is its denominator; null YAC is excluded,
never zero. Neutral pass rate numerator is qualifying neutral pass attempts;
denominator is qualifying neutral pass attempts plus qualifying neutral rush
attempts (kneels excluded); missing event predicates are excluded, never zero.
Explosive pass/rush rates use the observed-`yards_gained` populations stated
above, with event numerator values 1/0. Sacks/dropback uses `sack=1` as the
numerator and qualifying dropbacks as the denominator; rows with a null required
predicate are excluded. Turnovers/drive counts a qualifying `interception=1` or `fumble_lost=1` event
once per VFP as numerator and included possessions as denominator; a null event
flag never creates an event and is not silently converted to zero. Points/drive
sums mapped included-possession points over included possessions; scoring-drive, red-zone,
and goal-to-go rates use their explicitly defined completed drive/opportunity
events over their respective included possession/opportunity populations. Pace
uses valid non-null clock intervals only, as specified above. Every ratio is
null below its family minimum or when its numerator/denominator observation is
unavailable.

## Entering-state aggregation, perspectives, and combinations

Each per-team metric below is an **expanding, volume-weighted ratio** over all
eligible completed prior games: `sum(prior numerators) / sum(prior
denominators)`. Thus it has exact weights equal to its listed denominator, no
tuned window, and no current-game information. Cross-season history is
retained; regular and postseason games are both eligible only in forward
canonical order. This simple expanding estimator avoids 2025 tuning.

Minimum denominator is metric-specific and is applied to the matching observed
denominator population, never an umbrella “pass rates” population:

| Selected family | Numerator / denominator population | Null treatment | Minimum |
|---|---|---|---:|
| EPA/play | `sum(epa)` / VFPs with observed `epa` | null `epa` excluded | 20 plays |
| Success rate | `sum(success)` / VFPs with observed `success` | null `success` excluded | 20 plays |
| Points/drive; scoring-drive rate; turnovers/drive | mapped points; scoring possession; qualifying turnover events / included possessions | null drive result excludes possession; a VFP contributes at most one turnover event | 5 possessions |
| Seconds/play; neutral seconds/play | `sum(delta)` / valid clock intervals | null clock excludes interval | 10 intervals |
| Neutral pass rate | neutral pass attempts / neutral pass + rush attempts | null required flag excludes play | 20 attempts |
| Red-zone and goal-to-go TD rates | TD opportunity / included opportunity drives | null drive result excludes opportunity | 5 opportunities |
| Sacks/dropback | sacks / qualifying dropbacks | null required predicate excludes row | 20 dropbacks |
| Air yards/attempt | observed-air-yards sum / attempts with observed air yards | null air yards excluded | 20 observed-air-yards attempts |
| YAC/completion | observed-YAC sum / completions with observed YAC | null YAC excluded | 20 observed-YAC completions |
| Explosive pass rate | qualifying explosive-pass event / attempts with observed yards gained | null yards gained excluded | 20 observed-yards pass attempts |
| Explosive rush rate | qualifying explosive-rush event / kneel-excluded rushes with observed yards gained | null yards gained excluded | 20 observed-yards rush attempts |

If below minimum or numerator/denominator is unavailable, the state value is
null and its paired `*_missing` indicator is 1; otherwise indicator is 0. No
full-universe mean, future-season mean, or silent imputation is allowed. The
model receives zero for a null value only after a deterministic model-pipeline
null-to-zero transform paired with its indicator; that transform is part of the
future implementation test contract, not an estimated prior.

For a game-level matchup rate, `home_matchup_X = (home_offense_X +
away_defense_allowed_X) / 2` and `away_matchup_X = (away_offense_X +
home_defense_allowed_X) / 2`, only if both components meet their minima;
otherwise it is null with its indicator. “Allowed”/“exposure” always means the
opponent offense's statistic, so inversion is explicit. The same formula is
used for pace exposure. Rest is side-specific, not paired. Roof and surface
are game-level categorical context.

## Candidate-family adjudication

| Family | Classification | Exact source / definition | Leakage rationale |
|---|---|---|---|
| Offensive EPA/play; defensive EPA/play allowed | INCLUDE V1 | observed `epa` / VFP with observed `epa`; offense / opponent-offense allowed | eligible prior blocks only |
| Offensive success; defensive success allowed | INCLUDE V1 | observed `success` / VFP with observed `success` | same |
| Offensive points/drive; defensive allowed | INCLUDE V1 | `fixed_drive`, `fixed_drive_result`, possession rules above | same |
| Offensive scoring-drive rate; defensive allowed | INCLUDE V1 | included scoring drives / included possessions | same |
| Offensive seconds/play; defensive opponent pace exposure | INCLUDE V1 | clock-pair definition above; defense receives opponent rate | same |
| Neutral offensive seconds/play; neutral defensive pace exposure | INCLUDE V1 | clock pairs with prior play neutral | same |
| Neutral pass rate; defensive opponent neutral pass-rate exposure | INCLUDE V1 | neutral pass attempts / neutral (pass attempts + rush attempts), kneels excluded | same |
| Red-zone TD efficiency offense/defense | INCLUDE V1 | unique red-zone drive opportunities | same |
| Goal-to-go TD efficiency offense/defense | INCLUDE V1 | unique goal-to-go drive opportunities | same |
| Turnovers/drive offense/defense | INCLUDE V1 | INT or lost-fumble events / included possessions; no TOD | same |
| Interception rate offense/defense | DEFER | legitimate PBP definition exists, but redundant with turnover rate and accepted QB rate in simple V1 | no implementation authorized |
| Lost-fumble rate offense/defense | DEFER | legitimate PBP definition exists, but sparse and redundant with turnover rate | no implementation authorized |
| Sacks/dropback offense/defense | INCLUDE V1 | `sack` / dropbacks, suffered vs recorded | same |
| QB hits/dropback offense/defense | DEFER | nullable `qb_hit` 0/1 is legitimate hit proxy, but excluded for redundancy; never pressure/hurry | no implementation authorized |
| Air yards/attempt offense/defense | INCLUDE V1 | observed `air_yards` sum / pass attempts with observed `air_yards` | same |
| YAC/completion offense/defense | INCLUDE V1 | observed YAC sum / completed passes with observed YAC | same |
| Explosive pass/rush rate offense/defense | INCLUDE V1 | >=20 pass yards / observed-yards pass attempts; >=10 rush yards / observed-yards kneel-excluded rush attempts | same |
| Rest | INCLUDE V1 | accepted frozen schedules `away_rest`, `home_rest`; use source integer as a side value, null + indicator if absent | scheduled pregame context; no outcome field |
| Roof | INCLUDE V1 | accepted normalized games `roof_type`; lower-case category, null -> `unknown` + `roof_missing=1` | venue context only |
| Surface | INCLUDE V1 | accepted frozen schedules `surface`; lower-case category, null -> `unknown` + `surface_missing=1` | venue context only |
| Oracle QB v2 totals inputs | INCLUDE V1 | accepted game-side interface listed above; numeric state only | builder already excludes same/future source rows |
| Weekly/frozen EPA totals, CPOE, attempts/carries/yards, scoring history | DEFER as direct columns | preserve for audit/cross-check; PBP rates or Oracle interface are the selected canonical representations | avoids duplicate representations |
| Lagged snap participation | DEFER | frozen snap counts, prior eligible games only, could support future participation proxy but is player-selection-dependent | no stable totals aggregation selected |
| Current injuries/depth | DEFER | no accepted pregame historical timestamp semantics | would risk postgame/batch leakage |
| True pressure/hurry | REJECT | no legitimate source field; `qb_hit` is only a named proxy | must not mislabel proxy |
| Realized historical temperature/wind | REJECT | schedule/PBP `temp`, `wind` are realized historical results, not pregame predictors | result-derived context prohibited |

## Exact ordered V1 feature columns

All numeric matchup columns have a following same-name `_missing` column in
this order. Categorical `unknown` is deterministic and is accompanied by its
listed missing indicator.

1. `away_rest_days`
2. `away_rest_days_missing`
3. `home_rest_days`
4. `home_rest_days_missing`
5. `roof_category`
6. `roof_missing`
7. `surface_category`
8. `surface_missing`
9. `away_qb_passing_epa`
10. `away_qb_passing_epa_imputed`
11. `away_qb_passing_cpoe`
12. `away_qb_passing_cpoe_imputed`
13. `away_qb_sacks_suffered_rate`
14. `away_qb_sack_rate_imputed`
15. `away_qb_interception_rate`
16. `away_qb_interception_rate_imputed`
17. `away_qb_recency_weighted_form`
18. `away_qb_low_sample`
19. `away_qb_missing_player_id`
20. `home_qb_passing_epa`
21. `home_qb_passing_epa_imputed`
22. `home_qb_passing_cpoe`
23. `home_qb_passing_cpoe_imputed`
24. `home_qb_sacks_suffered_rate`
25. `home_qb_sack_rate_imputed`
26. `home_qb_interception_rate`
27. `home_qb_interception_rate_imputed`
28. `home_qb_recency_weighted_form`
29. `home_qb_low_sample`
30. `home_qb_missing_player_id`
31. `away_matchup_epa_per_play`
32. `away_matchup_epa_per_play_missing`
33. `home_matchup_epa_per_play`
34. `home_matchup_epa_per_play_missing`
35. `away_matchup_success_rate`
36. `away_matchup_success_rate_missing`
37. `home_matchup_success_rate`
38. `home_matchup_success_rate_missing`
39. `away_matchup_points_per_drive`
40. `away_matchup_points_per_drive_missing`
41. `home_matchup_points_per_drive`
42. `home_matchup_points_per_drive_missing`
43. `away_matchup_scoring_drive_rate`
44. `away_matchup_scoring_drive_rate_missing`
45. `home_matchup_scoring_drive_rate`
46. `home_matchup_scoring_drive_rate_missing`
47. `away_matchup_seconds_per_play`
48. `away_matchup_seconds_per_play_missing`
49. `home_matchup_seconds_per_play`
50. `home_matchup_seconds_per_play_missing`
51. `away_matchup_neutral_seconds_per_play`
52. `away_matchup_neutral_seconds_per_play_missing`
53. `home_matchup_neutral_seconds_per_play`
54. `home_matchup_neutral_seconds_per_play_missing`
55. `away_matchup_neutral_pass_rate`
56. `away_matchup_neutral_pass_rate_missing`
57. `home_matchup_neutral_pass_rate`
58. `home_matchup_neutral_pass_rate_missing`
59. `away_matchup_red_zone_td_rate`
60. `away_matchup_red_zone_td_rate_missing`
61. `home_matchup_red_zone_td_rate`
62. `home_matchup_red_zone_td_rate_missing`
63. `away_matchup_goal_to_go_td_rate`
64. `away_matchup_goal_to_go_td_rate_missing`
65. `home_matchup_goal_to_go_td_rate`
66. `home_matchup_goal_to_go_td_rate_missing`
67. `away_matchup_turnovers_per_drive`
68. `away_matchup_turnovers_per_drive_missing`
69. `home_matchup_turnovers_per_drive`
70. `home_matchup_turnovers_per_drive_missing`
71. `away_matchup_sacks_per_dropback`
72. `away_matchup_sacks_per_dropback_missing`
73. `home_matchup_sacks_per_dropback`
74. `home_matchup_sacks_per_dropback_missing`
75. `away_matchup_air_yards_per_attempt`
76. `away_matchup_air_yards_per_attempt_missing`
77. `home_matchup_air_yards_per_attempt`
78. `home_matchup_air_yards_per_attempt_missing`
79. `away_matchup_yac_per_completion`
80. `away_matchup_yac_per_completion_missing`
81. `home_matchup_yac_per_completion`
82. `home_matchup_yac_per_completion_missing`
83. `away_matchup_explosive_pass_rate`
84. `away_matchup_explosive_pass_rate_missing`
85. `home_matchup_explosive_pass_rate`
86. `home_matchup_explosive_pass_rate_missing`
87. `away_matchup_explosive_rush_rate`
88. `away_matchup_explosive_rush_rate_missing`
89. `home_matchup_explosive_rush_rate`
90. `home_matchup_explosive_rush_rate_missing`

## Required implementation validation gates

Before any later implementation may claim this contract, tests must prove:
1. ordinary non-scoring pass/rush rows remain VFP-eligible regardless of
   `sp=0`;
2. scoring pass/rush rows remain VFP-eligible regardless of `sp=1`;
3. changing only `sp` cannot change VFP membership for otherwise identical
   scrimmage plays;
4. raw PBP `POST` maps through `game_id` to canonical `WC`/`DIV`/`CON`/`SB`,
   while duplicate canonical IDs, unmatched required PBP IDs, and conflicting
   NFL seasons hard-fail;
5. same-game/same-block poisoning cannot change a target row;
6. later-block poisoning cannot affect prior rows, and postseason forward
   updates cannot affect regular-season states;
7. season-2024 postseason calendar-2025 games, including `2024_22_KC_PHI`,
   remain included;
8. an NFL `season == 2025` poison row is rejected and cannot affect a
   development feature, entering state, or development output;
9. no calendar-year filter excludes January/February 2025 season-2024 games;
10. prohibited frozen schedule market/outcome/weather/QB columns cannot enter
    the Totals V1 intermediate context frame;
11. `play_id` ordering and derived-half pace boundaries are deterministic;
12. non-plays and defined drive exclusions are rejected, and metric-null
    observations are never silently coerced to zero;
13. home/away and offense/defense inversion is correct; unique fixed-drive
    opportunities and neutral/clock boundaries work; all missing fallbacks are
    deterministic; and final feature-column order remains exactly the declared
    90 columns.

A provenance report must record the PBP file checksum, row counts, eligible
source block IDs, target block ID, canonical mapping failure counts, and zero
same-block/current-game/future-block/NFL-season-2025 source rows for every
development build.

## Phase-2 self-review

This design excludes same-game and same-block updates, future blocks, NFL
season-2025 input, and backward postseason leakage; maps broad PBP postseason
semantics through canonical game identity; makes offense/defense pairing
explicit; excludes garbage rows; defines drive, neutral, clock, turnover, and
explosive semantics; uses metric-specific observed denominators and deterministic
missingness; narrowly projects context; and locks columns and source versions.
It preserves exactly 18 INCLUDE V1 families, six DEFER families (interception
rate, lost-fumble rate, QB hits/dropback, weekly/frozen direct-stat
representations, lagged snap participation, and current injuries/depth), and
two REJECT families. No unresolved semantic blocker remains. The only explicit
assumptions are the existing accepted weekly availability model, accepted
rest/roof/surface source conclusion, and accepted Oracle QB entering-state-v2
historical interface.
