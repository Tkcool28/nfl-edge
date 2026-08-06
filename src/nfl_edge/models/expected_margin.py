"""Expected-Margin v1 — deterministic ridge-regularized scoring model.

Base Model C (docs/model_contract.md, Base Model C). The model
estimates a per-team offensive strength and a per-team defensive
strength, both regularized toward zero by a per-team ridge prior.
The expected home and away points are obtained by combining these
team strengths with a FITTED league-scoring baseline and the
opponent's defensive or offensive strength (the opponent adjustment).

Sign conventions (fixed; the contract returned by the model is::

    Positive offensive_strength  => the team is expected to score
                                     ABOVE the league baseline.
    Positive defensive_strength  => the team is expected to ALLOW
                                     FEWER opponent points than the
                                     league baseline (i.e. a stronger
                                     defense; opponent's expected
                                     points are reduced by this term).
    Negative defensive_strength  => the team allows more points than
                                     the league baseline; opponent's
                                     expected points are increased.

Equations::

    expected_home_points  = league_baseline
                          + home_field_effect        (if not neutral_site else 0)
                          + home_offensive_strength
                          - away_defensive_strength

    expected_away_points  = league_baseline
                          + away_offensive_strength
                          - home_defensive_strength

    expected_home_margin  = expected_home_points - expected_away_points

Two-observation scoring design (the identifiability fix):

For each completed training game we emit TWO observations:

  Home scoring observation:
    target = actual_home_points
    prediction = league_baseline + hfa*(not neutral) + home_off - away_def

  Away scoring observation:
    target = actual_away_points
    prediction = league_baseline + away_off - home_def

Both observations are fitted jointly with a single ridge linear
regression on the recency-weighted design matrix. The identity of
offense vs defense is therefore anchored by which game the team is
playing (home or away), not by the algebraic sign of the margin.

Identifiability (symmetric ridge fit + prediction-invariant post-fit centering):

- The league baseline is the FITTED intercept; its L2 prior is
  ``shared.league_baseline_prior`` (default 22.5). The intercept is
  NOT simultaneously a fixed constant.
- All team offense and defense effects are fitted symmetrically
  with their declared ridge priors; NO team is pinned as an
  alphabetical reference. The ridge on every effect makes the
  linear system uniquely solvable; there is no soft-penalty fake
  "sum-to-zero" diagonal term.
- After the closed-form solve, the offense and defense vectors are
  CENTERED so that ``sum(offense) = 0`` and ``sum(defense) = 0``,
  and the league baseline is adjusted so every predicted score is
  unchanged. The centering is prediction-invariant: predicted home
  and away points do not depend on team naming or team-index order.
- HFA is a single scalar fitted jointly with its own ridge prior.

Ties (margin == 0) are INCLUDED in the scoring fit. Both home and
away points are valid targets; ties are excluded only from the
binary home-win logistic mapping and the probability scorecard.

Recency weights:

- Chronological order is established by the block ordering
  ``(season, season_type_priority, week)`` and the within-block
  ``prediction_as_of_utc`` (UTC-aware). ``game_id`` is a final
  tie-breaker only.
- ``age_in_completed_games`` is the count of completed games that
  finished strictly before the current game in chronological order.
  The recency weight is ``w = 0.5 ** (age / half_life)``.

The model never uses market data, never uses sportsbook prices, and
never uses the future. The maximum development season is read from
the shared configuration and enforced at the boundary.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .expected_margin_config import (
    expected_margin_canonical_config_sha256,
    load_expected_margin_canonical_config,
)

# ---------------------------------------------------------------------------
# Configuration value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpectedMarginSharedConfig:
    """Shared parameters used by all three candidates."""

    league_baseline_prior: float
    probability_min: float
    probability_max: float
    mapping_intercept_l2_prior: float
    mapping_slope_l2_prior: float
    mapping_solver_tolerance: float
    mapping_solver_max_iterations: int
    tie_policy: str
    minimum_training_games: int
    minimum_mapping_rows: int
    apply_probability_clipping: bool
    reject_nonpositive_slope: bool
    maximum_development_season: int


@dataclass(frozen=True)
class ExpectedMarginCandidateConfig:
    """One locked candidate configuration."""

    id: str
    offense_ridge: float
    defense_ridge: float
    home_field_ridge: float
    recency_half_life_games: float
    mapping_intercept_l2_weight: float
    mapping_slope_l2_weight: float


def shared_config_from_normalized(
    normalized: dict[str, Any],
) -> ExpectedMarginSharedConfig:
    shared = normalized["shared"]
    return ExpectedMarginSharedConfig(
        league_baseline_prior=float(shared["league_baseline_prior"]),
        probability_min=float(shared["probability_min"]),
        probability_max=float(shared["probability_max"]),
        mapping_intercept_l2_prior=float(shared["mapping_intercept_l2_prior"]),
        mapping_slope_l2_prior=float(shared["mapping_slope_l2_prior"]),
        mapping_solver_tolerance=float(shared["mapping_solver_tolerance"]),
        mapping_solver_max_iterations=int(shared["mapping_solver_max_iterations"]),
        tie_policy=str(shared["tie_policy"]),
        minimum_training_games=int(shared["minimum_training_games"]),
        minimum_mapping_rows=int(shared["minimum_mapping_rows"]),
        apply_probability_clipping=bool(shared["apply_probability_clipping"]),
        reject_nonpositive_slope=bool(shared["reject_nonpositive_slope"]),
        maximum_development_season=int(shared["maximum_development_season"]),
    )


def candidate_config_from_normalized(
    normalized_candidate: dict[str, Any],
) -> ExpectedMarginCandidateConfig:
    return ExpectedMarginCandidateConfig(
        id=str(normalized_candidate["id"]),
        offense_ridge=float(normalized_candidate["offense_ridge"]),
        defense_ridge=float(normalized_candidate["defense_ridge"]),
        home_field_ridge=float(normalized_candidate["home_field_ridge"]),
        recency_half_life_games=float(
            normalized_candidate["recency_half_life_games"]
        ),
        mapping_intercept_l2_weight=float(
            normalized_candidate["mapping_intercept_l2_weight"]
        ),
        mapping_slope_l2_weight=float(
            normalized_candidate["mapping_slope_l2_weight"]
        ),
    )


def load_all_candidates(
    yaml_path: str | Path,
) -> tuple[ExpectedMarginSharedConfig, tuple[ExpectedMarginCandidateConfig, ...], str]:
    """Load the canonical config and return (shared, candidates, sha256)."""
    normalized = load_expected_margin_canonical_config(yaml_path)
    shared = shared_config_from_normalized(normalized)
    candidates = tuple(
        candidate_config_from_normalized(c) for c in normalized["candidates"]
    )
    sha = expected_margin_canonical_config_sha256(normalized)
    return shared, candidates, sha


# ---------------------------------------------------------------------------
# Fitted model container
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FittedExpectedMargin:
    """The output of a single fit on the prior training window.

    The fitted model never references the absolute path of the input
    data, never depends on the current time, and is fully reproducible
    from the training data and the candidate configuration.

    The fitted intercept is the league baseline. The team effects are
    deviations around the league baseline. Identification is enforced
    by a sum-to-zero constraint on offense and defense: the sum of
    offense_effect across all teams is zero, and the sum of
    defense_effect across all teams is zero. This constraint is
    prediction-invariant: predicted home and away points do not depend
    on team naming or ordering.
    """

    train_rows: int
    train_completed_rows: int
    n_teams: int
    team_index: dict[str, int]
    offense_effect: tuple[float, ...]
    defense_effect: tuple[float, ...]
    home_field_effect: float
    fitted_at_cutoff_utc: str
    league_baseline: float  # the fitted intercept

    def expected_home_points(
        self, home_team: str, away_team: str, neutral_site: bool
    ) -> float:
        hfa = 0.0 if neutral_site else self.home_field_effect
        return (
            self.league_baseline
            + hfa
            + self._offense(home_team)
            - self._defense(away_team)
        )

    def expected_away_points(
        self, home_team: str, away_team: str, neutral_site: bool
    ) -> float:
        return (
            self.league_baseline
            + self._offense(away_team)
            - self._defense(home_team)
        )

    def expected_home_margin(
        self, home_team: str, away_team: str, neutral_site: bool
    ) -> float:
        return self.expected_home_points(
            home_team, away_team, neutral_site
        ) - self.expected_away_points(home_team, away_team, neutral_site)

    def _offense(self, team: str) -> float:
        idx = self.team_index.get(team)
        if idx is None:
            return 0.0
        return self.offense_effect[idx]

    def _defense(self, team: str) -> float:
        idx = self.team_index.get(team)
        if idx is None:
            return 0.0
        return self.defense_effect[idx]


# ---------------------------------------------------------------------------
# Ridge linear regression
# ---------------------------------------------------------------------------


def _recency_weight(
    age_in_completed_games: float, half_life_games: float
) -> float:
    """Deterministic exponential decay weight based on the candidate half-life.

    ``w = 0.5 ** (age / half_life)``.

    The function is total and deterministic. ``age`` is the number of
    completed games that finished strictly before the current game in
    chronological order (the block ordering plus ``prediction_as_of_utc``
    plus ``game_id`` as a final tie-breaker). ``half_life`` is the
    candidate's ``recency_half_life_games`` parameter.
    """
    if half_life_games <= 0:
        raise ValueError("recency_half_life_games must be positive")
    if age_in_completed_games < 0:
        raise ValueError("age_in_completed_games must be non-negative")
    return math.pow(0.5, age_in_completed_games / half_life_games)


def _build_team_index(teams: Sequence[str]) -> dict[str, int]:
    return {team: i for i, team in enumerate(sorted(teams))}


def _solve_two_observation_ridge(
    *,
    n_teams: int,
    target_points,
    side_indicator,
    home_field_indicator,
    offensive_team_offset,
    defensive_team_offset,
    weights,
    offense_ridge: float,
    defense_ridge: float,
    home_field_ridge: float,
    league_baseline_prior: float,
    league_baseline_prior_weight: float,
):
    """Closed-form ridge linear regression for the two-observation scoring fit.

    Identifiability is enforced by a SYMMETRIC ridge fit followed by
    a PREDICTION-INVARIANT POST-FIT CENTERING so that the output
    satisfies ``sum(offense) = 0`` and ``sum(defense) = 0``.

    All team effects receive their declared ridge priors; NO team is
    pinned as an alphabetical reference. The ridge on every effect
    makes the system uniquely solvable (positive definite) — the
    earlier hand-added tiny diagonal is removed because it is NOT a
    sum-to-zero constraint and is not required as numerical ridge.
    After the solve, the offense and defense vectors are centered by
    subtracting their means and the league baseline is adjusted so
    every predicted score is unchanged. This centering is
    prediction-invariant: predictions do not depend on team naming
    or team-index ordering. Tests
    ``test_team_order_permutation_invariance`` and
    ``test_reference_team_rename_invariance`` lock this property.

    Sign convention::

        side = +1.0  -> home scoring observation (HFA may contribute)
             = -1.0  -> away scoring observation (HFA does not contribute)

    For a home observation the prediction is::

        league_baseline + hfa*(not neutral) + off[home_team] - def[away_team]

    For an away observation the prediction is::

        league_baseline + off[away_team] - def[home_team]

    The solve is numpy-free pure-Python dense Cholesky.
    """
    # Full parameter vector with all n_teams offense and defense
    # coefficients in the system. The ridge is applied to all teams
    # symmetrically. There is NO reference-team pinning and NO
    # soft-penalty sum-to-zero term: the declared ridge on every
    # effect makes the system positive definite and uniquely
    # solvable. Identification to a prediction-invariant gauge is
    # achieved afterward by post-fit centering.
    league_baseline_idx = 0
    offense_start = 1
    defense_start = 1 + n_teams
    hfa_idx = 1 + 2 * n_teams
    n_params = 2 * n_teams + 2

    xtw_x = [0.0] * (n_params * n_params)
    xtw_y = [0.0] * n_params

    for i in range(len(target_points)):
        w = float(weights[i])
        if w <= 0.0:
            continue
        side = float(side_indicator[i])
        hfa_eff = float(home_field_indicator[i]) * (1.0 if side > 0.0 else 0.0)
        off_global = int(offensive_team_offset[i])
        def_global = int(defensive_team_offset[i])
        y = float(target_points[i])

        coefs = [0.0] * n_params
        coefs[league_baseline_idx] = 1.0
        coefs[offense_start + off_global] += 1.0
        coefs[defense_start + def_global] -= 1.0
        coefs[hfa_idx] = hfa_eff

        for r in range(n_params):
            if coefs[r] == 0.0:
                continue
            for c in range(n_params):
                if coefs[c] == 0.0:
                    continue
                xtw_x[r * n_params + c] += w * coefs[r] * coefs[c]
            xtw_y[r] += w * coefs[r] * y

    xtw_x[league_baseline_idx * n_params + league_baseline_idx] += league_baseline_prior_weight
    xtw_y[league_baseline_idx] += league_baseline_prior_weight * float(league_baseline_prior)

    for k in range(n_teams):
        xtw_x[(offense_start + k) * n_params + (offense_start + k)] += offense_ridge
    for k in range(n_teams):
        idx = defense_start + k
        xtw_x[idx * n_params + idx] += defense_ridge
    xtw_x[hfa_idx * n_params + hfa_idx] += home_field_ridge

    solution = _cholesky_solve(xtw_x, xtw_y, n_params)
    raw_league_baseline = float(solution[league_baseline_idx])
    raw_offense = [float(v) for v in solution[offense_start:offense_start + n_teams]]
    raw_defense = [float(v) for v in solution[defense_start:defense_start + n_teams]]
    hfa = float(solution[hfa_idx])

    # Prediction-invariant post-fit centering. Subtract each effect
    # vector's mean so sum(offense) = 0 and sum(defense) = 0, and add
    # the combined centering offset to the league baseline so every
    # expected home/away points value (and hence every margin) is
    # numerically unchanged.
    mean_offense = sum(raw_offense) / n_teams
    mean_defense = sum(raw_defense) / n_teams
    league_baseline = raw_league_baseline + mean_offense - mean_defense
    offense = tuple(v - mean_offense for v in raw_offense)
    defense = tuple(v - mean_defense for v in raw_defense)

    return (league_baseline, offense, defense, hfa, {})


def _cholesky_solve(
    a_flat: list[float], b: list[float], n: int
) -> list[float]:
    """Solve Ax = b for symmetric positive-definite A.

    Pure-Python implementation. Used for both the team-effects ridge
    fit and the small (2x2) mapping fit. Deterministic given the
    input ordering.
    """
    L = [0.0] * (n * n)
    for i in range(n):
        for j in range(i + 1):
            s = a_flat[i * n + j]
            for k in range(j):
                s -= L[i * n + k] * L[j * n + k]
            if i == j:
                if s <= 0.0:
                    raise ValueError(
                        f"cholesky: non-positive pivot at row {i} ({s})"
                    )
                L[i * n + j] = math.sqrt(s)
            else:
                L[i * n + j] = s / L[j * n + j]
    y = [0.0] * n
    for i in range(n):
        s = b[i]
        for k in range(i):
            s -= L[i * n + k] * y[k]
        y[i] = s / L[i * n + i]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = y[i]
        for k in range(i + 1, n):
            s -= L[k * n + i] * x[k]
        x[i] = s / L[i * n + i]
    return x


# ---------------------------------------------------------------------------
# Public fit API
# ---------------------------------------------------------------------------


def fit_expected_margin(
    *,
    prior_training_games: list[dict[str, Any]],
    home_points: list[float],
    away_points: list[float],
    neutral_site: list[bool],
    home_team_codes: list[str],
    away_team_codes: list[str],
    chronological_age_in_completed_games: list[float],
    candidate: ExpectedMarginCandidateConfig,
    shared: ExpectedMarginSharedConfig,
    fitted_at_cutoff_utc: str,
) -> FittedExpectedMargin:
    """Fit a single candidate ridge linear regression on prior games.

    Two observations per game:

    - Home scoring observation: target = actual home points.
    - Away scoring observation: target = actual away points.

    Ties (margin == 0) are included in the scoring fit. Both home
    and away points are valid targets regardless of the margin.

    Identifiability:

    - The league baseline is the FITTED intercept, with L2 prior
      ``shared.league_baseline_prior``. The intercept is the ONLY
      baseline; there is no fixed constant 22.5 added on top.
    - Identification is enforced by a sum-to-zero constraint on
      offense and defense across all teams. Predictions are invariant
      to team naming and ordering.
    - All team effects receive their declared ridge priors.

    Chronological ordering:

    - ``chronological_age_in_completed_games`` is the number of
      completed games that finished strictly before the current
      game in chronological order. The recency weight is
      ``w = 0.5 ** (age / half_life)``. The chronological order is
      established by the caller's block ordering and the block's
      ``prediction_as_of_utc``; this function never recomputes the
      order itself.

    Inputs:

    - ``prior_training_games`` : list of completed game records
      (positional metadata, currently unused but reserved for
      future audit-side metadata).
    - ``home_points`` / ``away_points`` : the actual points scored
      by the home / away team for each completed prior game.
    - ``neutral_site`` : bool flag for each completed prior game.
    - ``home_team_codes`` / ``away_team_codes`` : team identifiers.
    - ``chronological_age_in_completed_games`` : per-game age in
      chronological order (recency weight).
    - ``candidate`` : locked candidate ridge/recency settings.
    - ``shared`` : shared configuration.
    - ``fitted_at_cutoff_utc`` : the cutoff ISO-8601 string used as
      the canonical timestamp on the fitted model.

    The function returns a fully-fitted model. The team index is
    sorted alphabetically for determinism; the offense and defense
    vectors satisfy the sum-to-zero identification constraint.
    """
    if not (len(prior_training_games) == len(home_points)
            == len(away_points) == len(neutral_site)
            == len(home_team_codes) == len(away_team_codes)
            == len(chronological_age_in_completed_games)):
        raise ValueError("fit inputs must have matching lengths")

    teams_set: set[str] = set()
    for i in range(len(home_team_codes)):
        teams_set.add(str(home_team_codes[i]))
        teams_set.add(str(away_team_codes[i]))
    team_index = _build_team_index(sorted(teams_set))
    n_teams = len(team_index)

    target_points: list[float] = []
    side_indicator: list[float] = []
    home_field_indicator: list[float] = []
    offensive_team_offset: list[int] = []
    defensive_team_offset: list[int] = []
    weights: list[float] = []

    half_life = float(candidate.recency_half_life_games)
    for i in range(len(home_team_codes)):
        home_team = str(home_team_codes[i])
        away_team = str(away_team_codes[i])
        neutral = bool(neutral_site[i])
        age = float(chronological_age_in_completed_games[i])
        weight = _recency_weight(age, half_life)

        target_points.append(float(home_points[i]))
        side_indicator.append(+1.0)
        home_field_indicator.append(0.0 if neutral else 1.0)
        offensive_team_offset.append(team_index[home_team])
        defensive_team_offset.append(team_index[away_team])
        weights.append(weight)

        target_points.append(float(away_points[i]))
        side_indicator.append(-1.0)
        home_field_indicator.append(0.0)
        offensive_team_offset.append(team_index[away_team])
        defensive_team_offset.append(team_index[home_team])
        weights.append(weight)

    train_rows = len(prior_training_games)
    train_completed_rows = len(prior_training_games)

    if len(prior_training_games) == 0:
        return FittedExpectedMargin(
            train_rows=train_rows,
            train_completed_rows=0,
            n_teams=n_teams,
            team_index=team_index,
            offense_effect=tuple([0.0] * n_teams),
            defense_effect=tuple([0.0] * n_teams),
            home_field_effect=0.0,
            fitted_at_cutoff_utc=fitted_at_cutoff_utc,
            league_baseline=float(shared.league_baseline_prior),
        )

    league_baseline_prior_weight = 1.0e-6

    league_baseline, offense, defense, hfa, _ = _solve_two_observation_ridge(
        n_teams=n_teams,
        target_points=target_points,
        side_indicator=side_indicator,
        home_field_indicator=home_field_indicator,
        offensive_team_offset=offensive_team_offset,
        defensive_team_offset=defensive_team_offset,
        weights=weights,
        offense_ridge=candidate.offense_ridge,
        defense_ridge=candidate.defense_ridge,
        home_field_ridge=candidate.home_field_ridge,
        league_baseline_prior=shared.league_baseline_prior,
        league_baseline_prior_weight=league_baseline_prior_weight,
    )

    return FittedExpectedMargin(
        train_rows=train_rows,
        train_completed_rows=train_completed_rows,
        n_teams=n_teams,
        team_index=team_index,
        offense_effect=offense,
        defense_effect=defense,
        home_field_effect=hfa,
        fitted_at_cutoff_utc=fitted_at_cutoff_utc,
        league_baseline=float(league_baseline),
    )


# ---------------------------------------------------------------------------
# Mapping layer (margin to probability)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FittedMapping:
    """Result of the prior-OOS logistic mapping fit."""

    row_count: int
    intercept: float
    slope: float
    fit_status: str  # "converged" | "warmup" | "rejected_nonpositive_slope" | "singular"
    convergence_status: str
    cutoff_utc: str


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def fit_mapping(
    *,
    prior_oos_margins: Sequence[float],
    prior_oos_home_win: Sequence[bool],
    intercept_l2_prior: float,
    slope_l2_prior: float,
    intercept_l2_weight: float,
    slope_l2_weight: float,
    tolerance: float,
    max_iterations: int,
    cutoff_utc: str,
) -> FittedMapping:
    """Fit a 2-parameter logistic regression on prior OOS rows.

    The model is::

        logit(P(home_win)) = intercept + slope * expected_home_margin

    Fit by deterministic Newton-Raphson / IRLS on the penalized
    binomial log-likelihood::

        L = sum_i  y_i log p_i + (1 - y_i) log(1 - p_i)
            - 0.5 * intercept_l2_weight * (intercept - intercept_l2_prior)^2
            - 0.5 * slope_l2_weight * (slope - slope_l2_prior)^2

    Ties are pre-filtered by the caller (the binary home-win
    mapping excludes ties per the shared ``tie_policy``). The fit
    returns a :class:`FittedMapping` whose ``fit_status`` reflects
    whether the fit converged, was rejected (non-positive slope),
    or the input warm-up state was active.
    """
    n_obs = len(prior_oos_margins)
    if n_obs != len(prior_oos_home_win):
        raise ValueError("prior_oos_margins and prior_oos_home_win must match")

    intercept = float(intercept_l2_prior)
    slope = float(slope_l2_prior)
    intercept_diff = intercept - float(intercept_l2_prior)
    slope_diff = slope - float(slope_l2_prior)

    if n_obs == 0:
        return FittedMapping(
            row_count=0,
            intercept=float("nan"),
            slope=float("nan"),
            fit_status="warmup",
            convergence_status="skipped_due_to_warmup",
            cutoff_utc=cutoff_utc,
        )

    fit_status = "converged"
    convergence_status = "converged"
    for iteration in range(int(max_iterations)):
        sum_pp = 0.0
        sum_pp_x = 0.0
        sum_pp_x2 = 0.0
        sum_resid = 0.0
        sum_resid_x = 0.0
        for margin, win in zip(prior_oos_margins, prior_oos_home_win):
            x = float(margin)
            y = 1.0 if bool(win) else 0.0
            p = _sigmoid(intercept + slope * x)
            p1mp = p * (1.0 - p)
            sum_pp += p1mp
            sum_pp_x += p1mp * x
            sum_pp_x2 += p1mp * x * x
            sum_resid += (y - p)
            sum_resid_x += x * (y - p)

        h00 = -sum_pp - intercept_l2_weight
        h01 = -sum_pp_x
        h11 = -sum_pp_x2 - slope_l2_weight
        g0 = sum_resid - intercept_l2_weight * intercept_diff
        g1 = sum_resid_x - slope_l2_weight * slope_diff

        b0 = -g0
        b1 = -g1
        det = h00 * h11 - h01 * h01
        if det == 0.0:
            fit_status = "singular"
            convergence_status = "hessian_singular"
            break
        d0 = (h11 * b0 - h01 * b1) / det
        d1 = (-h01 * b0 + h00 * b1) / det

        intercept_new = intercept + d0
        slope_new = slope + d1
        step = max(abs(d0), abs(d1))
        intercept = intercept_new
        slope = slope_new
        intercept_diff = intercept - float(intercept_l2_prior)
        slope_diff = slope - float(slope_l2_prior)
        if step < float(tolerance):
            convergence_status = "converged"
            break
    else:
        convergence_status = "max_iterations_reached"
        fit_status = "max_iterations_reached"

    if slope <= 0.0:
        return FittedMapping(
            row_count=n_obs,
            intercept=float("nan"),
            slope=float(slope),
            fit_status="rejected_nonpositive_slope",
            convergence_status=convergence_status,
            cutoff_utc=cutoff_utc,
        )

    return FittedMapping(
        row_count=n_obs,
        intercept=float(intercept),
        slope=float(slope),
        fit_status=fit_status,
        convergence_status=convergence_status,
        cutoff_utc=cutoff_utc,
    )


def predict_home_win_probability(
    mapping: FittedMapping,
    expected_home_margin: float,
    probability_min: float,
    probability_max: float,
    apply_clipping: bool,
) -> float:
    """Apply the fitted mapping to one expected margin.

    Returns a finite probability strictly inside (probability_min,
    probability_max). The mapping is monotonic in the expected
    margin: a larger margin cannot yield a lower probability when
    the slope is positive.
    """
    if not math.isfinite(expected_home_margin):
        raise ValueError("expected_home_margin must be finite")
    logit = float(mapping.intercept) + float(mapping.slope) * expected_home_margin
    p = _sigmoid(logit)
    if apply_clipping:
        if p < probability_min:
            p = probability_min
        elif p > probability_max:
            p = probability_max
    if p <= 0.0:
        p = float(probability_min)
    if p >= 1.0:
        p = float(probability_max)
    return p


def is_mapping_available(mapping: FittedMapping) -> bool:
    """Return True only when the mapping fit is ready for production use."""
    return mapping.fit_status == "converged"


def is_warmup_state(
    *, training_rows_available: int, minimum_training_games: int
) -> bool:
    """Return True when the available training rows are below the threshold.

    The threshold is the shared ``minimum_training_games`` parameter
    (default 64 for the development baseline). Below this threshold
    the model is in the team-strength warm-up state and does not
    emit a numeric expected margin.
    """
    return int(training_rows_available) < int(minimum_training_games)
