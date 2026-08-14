"""Expanding per-team entering-state aggregation with metric-specific minima.

Phase 3D extracts rate features from the Phase 3A/3B/3C
:class:`~nfl_edge.features.totals_v1.block_state.TeamEntState` accumulator
state.  Each rate family has its own exact minimum denominator threshold
(no umbrella pass/rush threshold).

Rate formula (contract-literal):

    value = sum(prior numerators) / sum(prior denominators)

    expanding history, volume-weighted by the metric's own denominator,
    no rolling window, no recency decay, no current-game information,
    cross-season history retained, REG and postseason both eligible in
    forward canonical order.

Null/missing rules:

    If denominator < metric minimum OR numerator/denominator unavailable:
        value = None, *_missing = 1
    Otherwise:
        value = ratio, *_missing = 0

    No mean imputation, no future-season mean, no full-universe prior,
    no silent zero fill.
"""

from __future__ import annotations

from dataclasses import dataclass

from .block_state import TeamEntState


@dataclass(frozen=True)
class MetricFamilyConfig:
    """Configuration for one matchup feature family."""

    feature_name: str
    offense_metric: str
    defense_metric: str
    minimum: int


# The 15 selected matchup families in contract order.
# Each maps to a primitive metric name in game_observations.py and a
# minimum denominator threshold from the Phase 2 contract.
MATCHUP_FAMILIES: tuple[MetricFamilyConfig, ...] = (
    MetricFamilyConfig("epa_per_play", "epa_play_offense", "epa_play_defense_allowed", 20),
    MetricFamilyConfig("success_rate", "success_offense", "success_defense_allowed", 20),
    MetricFamilyConfig("points_per_drive", "points_per_drive_offense", "points_per_drive_defense_allowed", 5),
    MetricFamilyConfig("scoring_drive_rate", "scoring_drive_rate_offense", "scoring_drive_rate_defense_allowed", 5),
    MetricFamilyConfig("seconds_per_play", "seconds_play_offense", "seconds_play_defense_allowed", 10),
    MetricFamilyConfig(
        "neutral_seconds_per_play", "neutral_seconds_play_offense", "neutral_seconds_play_defense_allowed", 10
    ),
    MetricFamilyConfig("neutral_pass_rate", "neutral_pass_rate_offense", "neutral_pass_rate_defense_allowed", 20),
    MetricFamilyConfig("red_zone_td_rate", "red_zone_td_rate_offense", "red_zone_td_rate_defense_allowed", 5),
    MetricFamilyConfig("goal_to_go_td_rate", "goal_to_go_td_rate_offense", "goal_to_go_td_rate_defense_allowed", 5),
    MetricFamilyConfig("turnovers_per_drive", "turnovers_per_drive_offense", "turnovers_per_drive_defense_allowed", 5),
    MetricFamilyConfig("sacks_per_dropback", "sacks_per_dropback_offense", "sacks_per_dropback_defense_allowed", 20),
    MetricFamilyConfig(
        "air_yards_per_attempt", "air_yards_per_attempt_offense", "air_yards_per_attempt_defense_allowed", 20
    ),
    MetricFamilyConfig("yac_per_completion", "yac_per_completion_offense", "yac_per_completion_defense_allowed", 20),
    MetricFamilyConfig(
        "explosive_pass_rate", "explosive_pass_rate_offense", "explosive_pass_rate_defense_allowed", 20
    ),
    MetricFamilyConfig(
        "explosive_rush_rate", "explosive_rush_rate_offense", "explosive_rush_rate_defense_allowed", 20
    ),
)


def extract_entering_rate(
    state: TeamEntState,
    metric_name: str,
    minimum: int,
) -> tuple[float | None, int]:
    """Extract a single entering rate from team state with minimum check.

    Returns ``(value, missing)`` where ``missing`` is 0 or 1.

    Contract rules:
    - If accumulator not present, or denominator < minimum: (None, 1)
    - Otherwise: (numerator / denominator, 0)
    - No imputation, no zero fill, no mean imputation.
    """
    acc = state.get(metric_name)
    if acc is None or acc.denominator < minimum:
        return (None, 1)
    return (acc.numerator / acc.denominator, 0)


def compute_matchup_pair(
    home_state: TeamEntState,
    away_state: TeamEntState,
    family: MetricFamilyConfig,
) -> dict[str, float | None | int]:
    """Compute both away_matchup and home_matchup for one feature family.

    Formula (contract-literal):

    - home_matchup = (home_offense + away_defense_allowed) / 2
    - away_matchup = (away_offense + home_defense_allowed) / 2

    If either side is unavailable or below minimum, the matchup is null
    and missing = 1.  Each side state is formed first, then simple
    arithmetic mean of the two rates.

    Returns a dict with four keys:
    - ``away_matchup_{feature_name}``
    - ``away_matchup_{feature_name}_missing``
    - ``home_matchup_{feature_name}``
    - ``home_matchup_{feature_name}_missing``
    """
    fname = family.feature_name

    # away_matchup = (away_offense + home_defense_allowed) / 2
    away_off_v, away_off_m = extract_entering_rate(away_state, family.offense_metric, family.minimum)
    home_def_v, home_def_m = extract_entering_rate(home_state, family.defense_metric, family.minimum)
    if away_off_m or home_def_m:
        away_matchup: float | None = None
        away_missing = 1
    else:
        away_matchup = (away_off_v + home_def_v) / 2
        away_missing = 0

    # home_matchup = (home_offense + away_defense_allowed) / 2
    home_off_v, home_off_m = extract_entering_rate(home_state, family.offense_metric, family.minimum)
    away_def_v, away_def_m = extract_entering_rate(away_state, family.defense_metric, family.minimum)
    if home_off_m or away_def_m:
        home_matchup: float | None = None
        home_missing = 1
    else:
        home_matchup = (home_off_v + away_def_v) / 2
        home_missing = 0

    return {
        f"away_matchup_{fname}": away_matchup,
        f"away_matchup_{fname}_missing": away_missing,
        f"home_matchup_{fname}": home_matchup,
        f"home_matchup_{fname}_missing": home_missing,
    }
