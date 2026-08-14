"""Game/team primitive observation construction for Totals V1 (Phase 3B + 3C).

Translates the accepted Phase 2 contract into per-game/per-team
numerator/denominator updates that feed
:class:`nfl_edge.features.totals_v1.block_state.GameObservation`.

Three non-negotiable contract rules:

1. **Offense / defense inversion is explicit.** Every offense metric
   from team A is mirrored to team B as its ``*_defense_allowed`` twin
   with the exact same ``(numerator, denominator, sample)`` triple.

2. **No silent zero-imputation.** Missing observation fields contribute
   neither numerator nor denominator. The per-row observation extractors
   in :mod:`nfl_edge.features.totals_v1.pbp_semantics` already encode
   this; this module routes them through.

3. **Every game in a block produces a GameObservation, even if its
   ``team_updates`` is empty.** Phase 3A's complete-block invariant
   requires this.

Primitive metric names exposed (NOT the final 90-column feature names --
the contract separates the two layers):

    offense                defense-allowed
    epa_play_offense           epa_play_defense_allowed
    success_offense            success_defense_allowed
    pass_attempts_offense      pass_attempts_defense_allowed
    completions_offense        completions_defense_allowed
    rush_attempts_offense      rush_attempts_defense_allowed
    dropbacks_offense          dropbacks_defense_allowed
    sacks_offense              sacks_defense_allowed
    turnovers_offense          turnovers_defense_allowed
    points_per_drive_offense   points_per_drive_defense_allowed
    scoring_drive_rate_offense scoring_drive_rate_defense_allowed
    turnovers_per_drive_offense turnovers_per_drive_defense_allowed
    seconds_play_offense       seconds_play_defense_allowed
    neutral_seconds_play_offense  neutral_seconds_play_defense_allowed
    neutral_pass_rate_offense  (defense side mirrors opponent offense)
    red_zone_td_rate_offense   red_zone_td_rate_defense_allowed
    goal_to_go_td_rate_offense goal_to_go_td_rate_defense_allowed
    sacks_per_dropback_offense sacks_per_dropback_defense_allowed
    air_yards_per_attempt_offense   air_yards_per_attempt_defense_allowed
    yac_per_completion_offense      yac_per_completion_defense_allowed
    explosive_pass_rate_offense     explosive_pass_rate_defense_allowed
    explosive_rush_rate_offense     explosive_rush_rate_defense_allowed

The ``neutral_pass_rate_offense`` primitive is built from two per-row
contributions (``neutral_pass_attempts`` and ``neutral_rush_attempts``)
that the game_observations layer combines into a single
``(neutral_passes, neutral_passes + neutral_rushes, count)`` triple.
The internal helpers are stripped before the offense/defense inversion
runs (see :func:`build_team_updates`), so they never appear as final
primitive metrics.
"""

from __future__ import annotations

from typing import Callable, Mapping

import polars as pl

from ...common.errors import WalkForwardError
from .block_state import GameObservation
from .drive_observations import (
    METRIC_GOAL_TO_GO_TD_RATE_DEFENSE_ALLOWED,
    METRIC_GOAL_TO_GO_TD_RATE_OFFENSE,
    METRIC_RED_ZONE_TD_RATE_DEFENSE_ALLOWED,
    METRIC_RED_ZONE_TD_RATE_OFFENSE,
    PossessionObservation,
    goal_to_go_opportunity_observations,
    points_per_drive_observation,
    red_zone_opportunity_observations,
    scoring_drive_observation,
    turnovers_per_drive_observation,
)
from .pace_observations import (
    METRIC_NEUTRAL_SECONDS_PLAY_DEFENSE_ALLOWED,
    METRIC_NEUTRAL_SECONDS_PLAY_OFFENSE,
    METRIC_SECONDS_PLAY_DEFENSE_ALLOWED,
    METRIC_SECONDS_PLAY_OFFENSE,
    pace_interval_observations,
)
from .pbp_semantics import (
    air_yards_observation,
    annotate_pbp_semantics,
    completion_observation,
    dropback_observation,
    epa_observation,
    explosive_pass_observation,
    explosive_rush_observation,
    neutral_pass_attempt_observation,
    neutral_rush_attempt_observation,
    pass_attempt_observation,
    rush_attempt_observation,
    sack_observation,
    sack_within_dropback_observation,
    success_observation,
    turnover_event_observation,
    yac_observation,
)


# Primitive metric names.
METRIC_EPA_PLAY_OFFENSE = "epa_play_offense"
METRIC_EPA_PLAY_DEFENSE_ALLOWED = "epa_play_defense_allowed"
METRIC_SUCCESS_OFFENSE = "success_offense"
METRIC_SUCCESS_DEFENSE_ALLOWED = "success_defense_allowed"
METRIC_PASS_ATTEMPTS_OFFENSE = "pass_attempts_offense"
METRIC_PASS_ATTEMPTS_DEFENSE_ALLOWED = "pass_attempts_defense_allowed"
METRIC_COMPLETIONS_OFFENSE = "completions_offense"
METRIC_COMPLETIONS_DEFENSE_ALLOWED = "completions_defense_allowed"
METRIC_RUSH_ATTEMPTS_OFFENSE = "rush_attempts_offense"
METRIC_RUSH_ATTEMPTS_DEFENSE_ALLOWED = "rush_attempts_defense_allowed"
METRIC_DROPBACKS_OFFENSE = "dropbacks_offense"
METRIC_DROPBACKS_DEFENSE_ALLOWED = "dropbacks_defense_allowed"
METRIC_SACKS_OFFENSE = "sacks_offense"
METRIC_SACKS_DEFENSE_ALLOWED = "sacks_defense_allowed"
METRIC_TURNOVERS_OFFENSE = "turnovers_offense"
METRIC_TURNOVERS_DEFENSE_ALLOWED = "turnovers_defense_allowed"
METRIC_POINTS_PER_DRIVE_OFFENSE = "points_per_drive_offense"
METRIC_POINTS_PER_DRIVE_DEFENSE_ALLOWED = "points_per_drive_defense_allowed"
METRIC_SCORING_DRIVE_RATE_OFFENSE = "scoring_drive_rate_offense"
METRIC_SCORING_DRIVE_RATE_DEFENSE_ALLOWED = "scoring_drive_rate_defense_allowed"
METRIC_TURNOVERS_PER_DRIVE_OFFENSE = "turnovers_per_drive_offense"
METRIC_TURNOVERS_PER_DRIVE_DEFENSE_ALLOWED = "turnovers_per_drive_defense_allowed"

# Phase 3C metric names.
METRIC_NEUTRAL_PASS_ATTEMPTS_OFFENSE = "neutral_pass_attempts_offense"
METRIC_NEUTRAL_RUSH_ATTEMPTS_OFFENSE = "neutral_rush_attempts_offense"
METRIC_NEUTRAL_PASS_RATE_OFFENSE = "neutral_pass_rate_offense"
METRIC_NEUTRAL_PASS_RATE_DEFENSE_ALLOWED = "neutral_pass_rate_defense_allowed"
METRIC_SACKS_PER_DROPBACK_OFFENSE = "sacks_per_dropback_offense"
METRIC_SACKS_PER_DROPBACK_DEFENSE_ALLOWED = "sacks_per_dropback_defense_allowed"
METRIC_AIR_YARDS_PER_ATTEMPT_OFFENSE = "air_yards_per_attempt_offense"
METRIC_AIR_YARDS_PER_ATTEMPT_DEFENSE_ALLOWED = "air_yards_per_attempt_defense_allowed"
METRIC_YAC_PER_COMPLETION_OFFENSE = "yac_per_completion_offense"
METRIC_YAC_PER_COMPLETION_DEFENSE_ALLOWED = "yac_per_completion_defense_allowed"
METRIC_EXPLOSIVE_PASS_RATE_OFFENSE = "explosive_pass_rate_offense"
METRIC_EXPLOSIVE_PASS_RATE_DEFENSE_ALLOWED = "explosive_pass_rate_defense_allowed"
METRIC_EXPLOSIVE_RUSH_RATE_OFFENSE = "explosive_rush_rate_offense"
METRIC_EXPLOSIVE_RUSH_RATE_DEFENSE_ALLOWED = "explosive_rush_rate_defense_allowed"


# Per-row offense metric extractors. Each tuple = (metric_name, extractor).
# ``sacks_offense`` counts any sack (VFP AND sack == 1); it is the
# Phase 3B "sacks / VFP" primitive and is independent from
# ``sacks_per_dropback_offense`` (sacks / dropbacks), which has a
# different denominator. Both are emitted for completeness.
_ROW_OFFENSE_EXTRACTORS: tuple[
    tuple[str, Callable[[dict], tuple[float, float, int]]], ...
] = (
    (METRIC_EPA_PLAY_OFFENSE, epa_observation),
    (METRIC_SUCCESS_OFFENSE, success_observation),
    (METRIC_PASS_ATTEMPTS_OFFENSE, pass_attempt_observation),
    (METRIC_COMPLETIONS_OFFENSE, completion_observation),
    (METRIC_RUSH_ATTEMPTS_OFFENSE, rush_attempt_observation),
    (METRIC_DROPBACKS_OFFENSE, dropback_observation),
    (METRIC_SACKS_OFFENSE, sack_observation),
    (METRIC_TURNOVERS_OFFENSE, turnover_event_observation),
    # Phase 3C row metrics.
    # ``neutral_pass_attempts_offense`` and
    # ``neutral_rush_attempts_offense`` are also used to derive the
    # combined ``neutral_pass_rate_offense`` metric in
    # :func:`aggregate_row_metrics`.
    (METRIC_NEUTRAL_PASS_ATTEMPTS_OFFENSE, neutral_pass_attempt_observation),
    (METRIC_NEUTRAL_RUSH_ATTEMPTS_OFFENSE, neutral_rush_attempt_observation),
    (METRIC_SACKS_PER_DROPBACK_OFFENSE, sack_within_dropback_observation),
    (METRIC_AIR_YARDS_PER_ATTEMPT_OFFENSE, air_yards_observation),
    (METRIC_YAC_PER_COMPLETION_OFFENSE, yac_observation),
    (METRIC_EXPLOSIVE_PASS_RATE_OFFENSE, explosive_pass_observation),
    (METRIC_EXPLOSIVE_RUSH_RATE_OFFENSE, explosive_rush_observation),
)


# Offense-metric -> defense-allowed twin. Explicit, not derived.
# Both Phase 3B and Phase 3C offense primitives appear here so the
# offense/defense inversion is complete.
_OFFENSE_TO_DEFENSE: dict[str, str] = {
    METRIC_EPA_PLAY_OFFENSE: METRIC_EPA_PLAY_DEFENSE_ALLOWED,
    METRIC_SUCCESS_OFFENSE: METRIC_SUCCESS_DEFENSE_ALLOWED,
    METRIC_PASS_ATTEMPTS_OFFENSE: METRIC_PASS_ATTEMPTS_DEFENSE_ALLOWED,
    METRIC_COMPLETIONS_OFFENSE: METRIC_COMPLETIONS_DEFENSE_ALLOWED,
    METRIC_RUSH_ATTEMPTS_OFFENSE: METRIC_RUSH_ATTEMPTS_DEFENSE_ALLOWED,
    METRIC_DROPBACKS_OFFENSE: METRIC_DROPBACKS_DEFENSE_ALLOWED,
    METRIC_SACKS_OFFENSE: METRIC_SACKS_DEFENSE_ALLOWED,
    METRIC_TURNOVERS_OFFENSE: METRIC_TURNOVERS_DEFENSE_ALLOWED,
    METRIC_POINTS_PER_DRIVE_OFFENSE: METRIC_POINTS_PER_DRIVE_DEFENSE_ALLOWED,
    METRIC_SCORING_DRIVE_RATE_OFFENSE: METRIC_SCORING_DRIVE_RATE_DEFENSE_ALLOWED,
    METRIC_TURNOVERS_PER_DRIVE_OFFENSE: METRIC_TURNOVERS_PER_DRIVE_DEFENSE_ALLOWED,
    METRIC_SECONDS_PLAY_OFFENSE: METRIC_SECONDS_PLAY_DEFENSE_ALLOWED,
    METRIC_NEUTRAL_SECONDS_PLAY_OFFENSE: METRIC_NEUTRAL_SECONDS_PLAY_DEFENSE_ALLOWED,
    METRIC_NEUTRAL_PASS_RATE_OFFENSE: METRIC_NEUTRAL_PASS_RATE_DEFENSE_ALLOWED,
    METRIC_SACKS_PER_DROPBACK_OFFENSE: METRIC_SACKS_PER_DROPBACK_DEFENSE_ALLOWED,
    METRIC_RED_ZONE_TD_RATE_OFFENSE: METRIC_RED_ZONE_TD_RATE_DEFENSE_ALLOWED,
    METRIC_GOAL_TO_GO_TD_RATE_OFFENSE: METRIC_GOAL_TO_GO_TD_RATE_DEFENSE_ALLOWED,
    METRIC_AIR_YARDS_PER_ATTEMPT_OFFENSE: METRIC_AIR_YARDS_PER_ATTEMPT_DEFENSE_ALLOWED,
    METRIC_YAC_PER_COMPLETION_OFFENSE: METRIC_YAC_PER_COMPLETION_DEFENSE_ALLOWED,
    METRIC_EXPLOSIVE_PASS_RATE_OFFENSE: METRIC_EXPLOSIVE_PASS_RATE_DEFENSE_ALLOWED,
    METRIC_EXPLOSIVE_RUSH_RATE_OFFENSE: METRIC_EXPLOSIVE_RUSH_RATE_DEFENSE_ALLOWED,
}


# Phase 3C: neutral pass rate is derived from two per-row contributors
# (neutral pass attempts and neutral rush attempts). After the per-row
# aggregation step, :func:`_combine_neutral_pass_rate` merges them into
# the final ``neutral_pass_rate_offense`` triple
# ``(neutral_passes, neutral_passes + neutral_rushes, count)``.
_NEUTRAL_PASS_RATE_DERIVED_FROM: tuple[str, str] = (
    METRIC_NEUTRAL_PASS_ATTEMPTS_OFFENSE,
    METRIC_NEUTRAL_RUSH_ATTEMPTS_OFFENSE,
)


class GameObservationError(WalkForwardError):
    """Raised when per-game observation construction cannot proceed."""


def aggregate_row_metrics(
    annotated: pl.DataFrame,
) -> dict[str, dict[str, dict[str, list[tuple[float, float, int]]]]]:
    """Aggregate per-row offense metrics to ``game_id -> team -> metric -> [obs]``.

    Inner value is a list of ``(numerator, denominator, sample)`` triples,
    one per qualifying row. ``build_game_observations`` sums them.

    Rows whose ``posteam`` is null are skipped: they are not VFP by
    construction (VFP requires ``posteam`` non-null), but the explicit
    skip is defensive.

    In addition to the per-row extractors, this function also aggregates
    Phase 3C pace intervals (seconds/play and neutral seconds/play) and
    Phase 3C drive-opportunity metrics (red-zone TD rate and goal-to-go
    TD rate) and folds them into the same return structure. Pace
    intervals are computed from the annotated frame; drive opportunities
    are computed by drive-aggregation on the annotated frame.

    After the per-row and pace aggregation, this function derives
    ``neutral_pass_rate_offense`` from the two neutral-attempt metrics:
    the combined triple is ``(neutral_passes, neutral_passes +
    neutral_rushes, count)``.
    """
    if "posteam" not in annotated.columns:
        raise GameObservationError(
            "aggregate_row_metrics", "annotated frame missing posteam"
        )

    rows: list[tuple[str, str, str, float, float, int]] = []
    for row in annotated.iter_rows(named=True):
        posteam = row.get("posteam")
        if posteam is None:
            continue
        game_id = str(row["game_id"])
        posteam_str = str(posteam)
        for metric_name, extractor in _ROW_OFFENSE_EXTRACTORS:
            numerator, denominator, sample = extractor(row)
            if denominator == 0 and numerator == 0 and sample == 0:
                continue
            rows.append(
                (game_id, posteam_str, metric_name, numerator, denominator, sample)
            )

    out: dict[str, dict[str, dict[str, list[tuple[float, float, int]]]]] = {}
    for game_id, posteam, metric, n, d, s in rows:
        per_game = out.setdefault(game_id, {})
        per_team = per_game.setdefault(posteam, {})
        per_metric = per_team.setdefault(metric, [])
        per_metric.append((n, d, s))

    # Phase 3C: fold pace intervals into the same row-aggregate dict
    # using the offense metric name (seconds_play_offense /
    # neutral_seconds_play_offense). The defense-allowed twins are
    # produced later in ``build_team_updates`` via the same
    # offense/defense inversion map as every other offense metric.
    pace_aggs = pace_interval_observations(annotated)
    for game_id, per_team in pace_aggs.items():
        dest_game = out.setdefault(game_id, {})
        for team, metrics in per_team.items():
            dest_team = dest_game.setdefault(team, {})
            for metric, triples in metrics.items():
                dest_team.setdefault(metric, []).extend(triples)

    # Phase 3C: fold red-zone and goal-to-go opportunity triples into
    # the same dict using the offense metric names. Drives whose
    # ``fixed_drive_result`` is null contribute nothing.
    rz_opps = red_zone_opportunity_observations(annotated)
    gtg_opps = goal_to_go_opportunity_observations(annotated)
    for game_id, posteam, triple in rz_opps:
        dest_team = out.setdefault(game_id, {}).setdefault(posteam, {})
        dest_team.setdefault(METRIC_RED_ZONE_TD_RATE_OFFENSE, []).append(triple)
    for game_id, posteam, triple in gtg_opps:
        dest_team = out.setdefault(game_id, {}).setdefault(posteam, {})
        dest_team.setdefault(METRIC_GOAL_TO_GO_TD_RATE_OFFENSE, []).append(triple)

    # Phase 3C: derive ``neutral_pass_rate_offense`` from the two
    # neutral-attempt metrics. The combined triple is
    # ``(neutral_passes, neutral_passes + neutral_rushes, count)``
    # where count is the number of qualifying rows (== neutral_passes
    # + neutral_rushes by construction, since each row contributes
    # either (1, 1, 1) or (0, 0, 0) to both metrics).
    for game_id in list(out.keys()):
        for posteam in list(out.get(game_id, {}).keys()):
            per_team = out[game_id][posteam]
            pass_triples = per_team.get(METRIC_NEUTRAL_PASS_ATTEMPTS_OFFENSE)
            rush_triples = per_team.get(METRIC_NEUTRAL_RUSH_ATTEMPTS_OFFENSE)
            if pass_triples is None and rush_triples is None:
                continue
            n_pass, d_pass, s_pass = _sum_triples(pass_triples or [])
            n_rush, d_rush, s_rush = _sum_triples(rush_triples or [])
            combined = (n_pass, n_pass + n_rush, int(d_pass) + int(d_rush))
            per_team[METRIC_NEUTRAL_PASS_RATE_OFFENSE] = [combined]

    return out


def aggregate_possession_metrics(
    possessions: list[PossessionObservation],
) -> dict[str, dict[str, dict[str, list[tuple[float, float, int]]]]]:
    """Aggregate per-possession offense metrics to ``game_id -> team -> metric -> [obs]``.

    Emits one triple per included possession for:

    - ``points_per_drive_offense`` (Phase 3B)
    - ``scoring_drive_rate_offense`` (Phase 3B)
    - ``turnovers_per_drive_offense`` (Phase 3B)

    Phase 3C drive-opportunity primitives (red-zone TD rate and
    goal-to-go TD rate) are aggregated inside
    :func:`aggregate_row_metrics` because they reuse the same annotated
    frame and same per-team grouping structure; the defense-allowed
    twins of those primitives are produced by the offense/defense
    inversion in :func:`build_team_updates`.
    """
    out: dict[str, dict[str, dict[str, list[tuple[float, float, int]]]]] = {}
    for p in possessions:
        per_game = out.setdefault(p.game_id, {})
        per_team = per_game.setdefault(p.posteam, {})
        per_team.setdefault(METRIC_POINTS_PER_DRIVE_OFFENSE, []).append(
            points_per_drive_observation(p)
        )
        per_team.setdefault(METRIC_SCORING_DRIVE_RATE_OFFENSE, []).append(
            scoring_drive_observation(p)
        )
        per_team.setdefault(METRIC_TURNOVERS_PER_DRIVE_OFFENSE, []).append(
            turnovers_per_drive_observation(p)
        )
    return out


def _sum_triples(
    triples: list[tuple[float, float, int]],
) -> tuple[float, float, int]:
    n = 0.0
    d = 0.0
    s = 0
    for tn, td, ts in triples:
        n += tn
        d += td
        s += ts
    return (n, d, s)


def build_team_updates(
    game_id: str,
    row_aggregates: dict[str, dict[str, dict[str, list[tuple[float, float, int]]]]],
    possession_aggregates: dict[str, dict[str, dict[str, list[tuple[float, float, int]]]]],
    home_team: str | None,
    away_team: str | None,
) -> dict[str, dict[str, tuple[float, float, int]]]:
    """Build ``team_updates`` for one game with explicit offense/defense inversion.

    Internal aggregation helpers (``neutral_pass_attempts_offense`` and
    ``neutral_rush_attempts_offense``) are stripped here, before the
    offense/defense inversion runs, so that the inversion step never
    has to know about them. They are used only inside
    :func:`aggregate_row_metrics` to derive the single
    ``neutral_pass_rate_offense`` primitive and must not escape as final
    primitives. The defense twin of the derived primitive is emitted
    normally because ``neutral_pass_rate_offense`` is registered in
    ``_OFFENSE_TO_DEFENSE``.
    """
    per_team_row: dict[str, dict[str, list[tuple[float, float, int]]]] = (
        row_aggregates.get(game_id, {})
    )
    per_team_pos: dict[str, dict[str, list[tuple[float, float, int]]]] = (
        possession_aggregates.get(game_id, {})
    )

    merged: dict[str, dict[str, list[tuple[float, float, int]]]] = {}
    for team, metrics in per_team_row.items():
        bucket = merged.setdefault(team, {})
        for metric, triples in metrics.items():
            bucket.setdefault(metric, []).extend(triples)
    for team, metrics in per_team_pos.items():
        bucket = merged.setdefault(team, {})
        for metric, triples in metrics.items():
            bucket.setdefault(metric, []).extend(triples)

    # FIX 1: strip internal neutral-pass component helpers before the
    # offense/defense inversion. These two metrics are aggregation-only
    # and must never appear in the final ``team_updates``; they have no
    # defense twins registered and would otherwise hard-fail the
    # inversion step. The derived ``neutral_pass_rate_offense`` is kept
    # untouched so the user-visible neutral-pass primitive and its
    # defense-allowed twin are emitted as before.
    for team_metrics in merged.values():
        team_metrics.pop(METRIC_NEUTRAL_PASS_ATTEMPTS_OFFENSE, None)
        team_metrics.pop(METRIC_NEUTRAL_RUSH_ATTEMPTS_OFFENSE, None)

    teams_in_game = sorted(merged.keys())
    if not teams_in_game:
        # No football plays in this game -> empty GameObservation (Phase 3A
        # complete-block invariant must still be satisfied).
        return {}
    if home_team is not None and away_team is not None:
        if set(teams_in_game) != {home_team, away_team}:
            raise GameObservationError(
                "build_team_updates",
                f"game {game_id} team mismatch: aggregates={teams_in_game} "
                f"vs home/away={home_team!r},{away_team!r}",
            )
        canonical_pair = (home_team, away_team)
    else:
        if len(teams_in_game) != 2:
            raise GameObservationError(
                "build_team_updates",
                f"game {game_id}: expected exactly 2 teams, got {teams_in_game}; "
                "cannot apply offense/defense inversion deterministically",
            )
        canonical_pair = (teams_in_game[0], teams_in_game[1])

    home, away = canonical_pair
    updates: dict[str, dict[str, tuple[float, float, int]]] = {}

    for offense_team in (home, away):
        team_metrics = merged.get(offense_team, {})
        if not team_metrics:
            continue
        per_team = updates.setdefault(offense_team, {})
        for metric, triples in sorted(team_metrics.items()):
            per_team[metric] = _sum_triples(triples)

    for offense_team in (home, away):
        opponent = away if offense_team == home else home
        team_metrics = merged.get(offense_team, {})
        if not team_metrics:
            continue
        per_team = updates.setdefault(opponent, {})
        for offense_metric, triples in sorted(team_metrics.items()):
            defense_metric = _OFFENSE_TO_DEFENSE.get(offense_metric)
            if defense_metric is None:
                raise GameObservationError(
                    "build_team_updates",
                    f"offense metric {offense_metric!r} has no defense-allowed twin",
                )
            per_team[defense_metric] = _sum_triples(triples)

    return updates


def build_game_observations(
    block_id: str,
    pbp_frames: dict[str, pl.DataFrame],
    game_to_teams: Mapping[str, tuple[str, str]] | None = None,
) -> list[GameObservation]:
    """Build one :class:`GameObservation` per (block_id, game_id)."""
    from .drive_observations import build_possessions, possession_observations

    all_row_aggs: dict[str, dict[str, dict[str, list[tuple[float, float, int]]]]] = {}
    all_pos_aggs: dict[str, dict[str, dict[str, list[tuple[float, float, int]]]]] = {}

    for game_id, frame in pbp_frames.items():
        annotated = annotate_pbp_semantics(frame)
        # Per-game row aggregates -> global.
        row_aggs = aggregate_row_metrics(annotated)
        for gid, per_team in row_aggs.items():
            dest = all_row_aggs.setdefault(gid, {})
            for team, metrics in per_team.items():
                dest_team = dest.setdefault(team, {})
                for metric, triples in metrics.items():
                    dest_team.setdefault(metric, []).extend(triples)

        # Per-game possession aggregates -> global.
        possessions_tbl = build_possessions(annotated)
        possessions = possession_observations(possessions_tbl)
        pos_aggs = aggregate_possession_metrics(possessions)
        for gid, per_team in pos_aggs.items():
            dest = all_pos_aggs.setdefault(gid, {})
            for team, metrics in per_team.items():
                dest_team = dest.setdefault(team, {})
                for metric, triples in metrics.items():
                    dest_team.setdefault(metric, []).extend(triples)

    observations: list[GameObservation] = []
    for game_id in sorted(pbp_frames.keys()):
        teams = game_to_teams.get(game_id) if game_to_teams else None
        if teams is not None:
            home_team, away_team = teams
        else:
            home_team = away_team = None
        updates = build_team_updates(
            game_id=game_id,
            row_aggregates=all_row_aggs,
            possession_aggregates=all_pos_aggs,
            home_team=home_team,
            away_team=away_team,
        )
        observations.append(
            GameObservation(block_id=block_id, game_id=game_id, team_updates=updates)
        )
    return observations


def build_game_observations_with_provenance(
    block_id: str,
    pbp_frames: dict[str, pl.DataFrame],
    game_to_teams: Mapping[str, tuple[str, str]] | None = None,
) -> "tuple[list[GameObservation], ProvenanceCounters]":
    """Build game observations AND a populated :class:`ProvenanceCounters`.

    The counters here are informational, not violations: the only
    counter this function populates is ``dropback_fallback_rows``, which
    counts VFP rows that qualified for the dropback fallback
    (``qb_dropback IS NULL AND (pass_attempt == 1 OR sack == 1)``).
    This count is informational per the accepted contract; it does NOT
    affect ``valid_development_build`` or ``assert_clean_development``.

    The function reuses the same annotated-PBP pipeline as
    :func:`build_game_observations`. ``is_dropback_fallback`` is the
    deterministic source-of-truth column produced by
    :func:`nfl_edge.features.totals_v1.pbp_semantics.annotate_pbp_semantics`;
    we sum its truthy rows once across all supplied PBP frames.
    """
    from .provenance import ProvenanceCounters

    observations = build_game_observations(
        block_id=block_id,
        pbp_frames=pbp_frames,
        game_to_teams=game_to_teams,
    )
    total_fallback = 0
    for frame in pbp_frames.values():
        annotated = annotate_pbp_semantics(frame)
        if "is_dropback_fallback" not in annotated.columns:
            # annotate_pbp_semantics always adds this column; defensive only.
            continue
        total_fallback += int(annotated["is_dropback_fallback"].sum())

    counters = ProvenanceCounters()
    if total_fallback:
        counters = counters.add_dropback_fallback_rows(total_fallback)
    return observations, counters


__all__ = [
    "METRIC_EPA_PLAY_OFFENSE",
    "METRIC_EPA_PLAY_DEFENSE_ALLOWED",
    "METRIC_SUCCESS_OFFENSE",
    "METRIC_SUCCESS_DEFENSE_ALLOWED",
    "METRIC_PASS_ATTEMPTS_OFFENSE",
    "METRIC_PASS_ATTEMPTS_DEFENSE_ALLOWED",
    "METRIC_COMPLETIONS_OFFENSE",
    "METRIC_COMPLETIONS_DEFENSE_ALLOWED",
    "METRIC_RUSH_ATTEMPTS_OFFENSE",
    "METRIC_RUSH_ATTEMPTS_DEFENSE_ALLOWED",
    "METRIC_DROPBACKS_OFFENSE",
    "METRIC_DROPBACKS_DEFENSE_ALLOWED",
    "METRIC_SACKS_OFFENSE",
    "METRIC_SACKS_DEFENSE_ALLOWED",
    "METRIC_TURNOVERS_OFFENSE",
    "METRIC_TURNOVERS_DEFENSE_ALLOWED",
    "METRIC_POINTS_PER_DRIVE_OFFENSE",
    "METRIC_POINTS_PER_DRIVE_DEFENSE_ALLOWED",
    "METRIC_SCORING_DRIVE_RATE_OFFENSE",
    "METRIC_SCORING_DRIVE_RATE_DEFENSE_ALLOWED",
    "METRIC_TURNOVERS_PER_DRIVE_OFFENSE",
    "METRIC_TURNOVERS_PER_DRIVE_DEFENSE_ALLOWED",
    "GameObservationError",
    "aggregate_possession_metrics",
    "aggregate_row_metrics",
    "build_game_observations",
    "build_game_observations_with_provenance",
    "build_team_updates",
]