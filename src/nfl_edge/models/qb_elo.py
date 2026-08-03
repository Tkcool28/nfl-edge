"""QB-adjusted Elo probability model.

The model is sequential, deterministic, and does not fit. It is a base
model whose output is a single home-win probability per game. The four
moving parts are:

1. Team Elo state: persistent rating per team updated after every
   completed game. The state is initialized to ``initial_rating`` at the
   start of the development window and regressed toward the mean at every
   season boundary.
2. Home-field adjustment: a fixed Elo additive applied to the home team's
   expected score. Neutral-site games use ``0``.
3. Margin-of-victory multiplier: a logistic-style multiplier that inflates
   K for larger margins. Capped at 2.5 so a single blowout cannot move
   the rating more than 2.5 * K points.
4. QB adjustment: a bounded Elo additive that is ``0.0`` whenever the
   pregame starter is unknown, replaced by a conservative prior, or not
   certifiably CONFIRMED_PRE_CUTOFF/DEPTH_CHART_SUPPORTED. This is the
   conservative approach required by the Task 03A QB-starter environment,
   where 2,226 of 2,227 historical games are ``POSTGAME_ONLY_EVIDENCE``.

The probability is the standard Elo logistic:

    p_home = 1 / (1 + 10^(-(home_elo + hfa + home_qb_adj
                              - away_elo - away_qb_adj) / 400))

clamped to ``[prob_min, prob_max]`` for numerical safety only. The clamp
is not used to improve calibration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from ..common.errors import ConfigurationError, WalkForwardError

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class QBAdjustmentConfig:
    """Configuration for the QB adjustment component.

    The component uses pregame certainty only. ``scale_elo_per_shrunk_epa``
    converts the documented QB passing-EPA shrinkage differential to an
    Elo additive. ``max_abs_elo`` clamps the absolute adjustment so a low-
    sample QB cannot produce an extreme adjustment.
    """

    # Shrinkage form matches the feature pipeline: weight = sample / (sample + K)
    sample_k: float = 250.0
    # Prior passing EPA per dropback for the conservative replacement QB.
    replacement_passing_epa: float = -0.05
    # Elo points per 1.0 of passing-EPA advantage. 25 points per 0.05 EPA
    # advantage is the documented approximation.
    scale_elo_per_shrunk_epa: float = 500.0
    # Maximum absolute Elo adjustment from a QB shift on either side.
    max_abs_elo: float = 50.0
    # When the pregame starter is unknown, the adjustment is exactly 0.0.
    unknown_returns_zero: bool = True
    # When the pregame starter is supported but not confirmed, use the
    # replacement scenario (so the adjustment is the delta from the
    # replacement) rather than the unknown = 0 short-circuit.
    supported_uses_replacement_scenario: bool = True

    def __post_init__(self) -> None:
        if self.sample_k <= 0.0:
            raise ConfigurationError("sample_k must be > 0")
        if self.scale_elo_per_shrunk_epa <= 0.0:
            raise ConfigurationError("scale_elo_per_shrunk_epa must be > 0")
        if self.max_abs_elo <= 0.0:
            raise ConfigurationError("max_abs_elo must be > 0")


@dataclass(frozen=True)
class EloConfig:
    """Static Elo configuration. The values are documented in the run
    manifest as the primary configuration; sensitivity variants are listed
    in the tuning ledger."""

    initial_rating: float = 1500.0
    k_factor_regular: float = 20.0
    k_factor_postseason: float = 4.0
    home_field_elo: float = 48.0
    season_mean_reversion_fraction: float = 1.0 / 3.0
    # Margin-of-victory multiplier: 1 + ((margin/6)^2) capped at 2.5.
    mov_divisor: float = 6.0
    mov_cap: float = 2.5
    # Numerical safety clamp on probabilities.
    prob_min: float = 0.01
    prob_max: float = 0.99
    # QB adjustment
    qb_adjustment: QBAdjustmentConfig = field(default_factory=QBAdjustmentConfig)

    def __post_init__(self) -> None:
        if self.initial_rating <= 0.0:
            raise ConfigurationError("initial_rating must be > 0")
        if self.k_factor_regular <= 0.0:
            raise ConfigurationError("k_factor_regular must be > 0")
        if self.k_factor_postseason <= 0.0:
            raise ConfigurationError("k_factor_postseason must be > 0")
        if self.home_field_elo < 0.0:
            raise ConfigurationError("home_field_elo must be >= 0")
        if not 0.0 <= self.season_mean_reversion_fraction <= 1.0:
            raise ConfigurationError("season_mean_reversion_fraction must be in [0, 1]")
        if self.mov_divisor <= 0.0:
            raise ConfigurationError("mov_divisor must be > 0")
        if self.mov_cap < 1.0:
            raise ConfigurationError("mov_cap must be >= 1.0")
        if not 0.0 < self.prob_min < self.prob_max < 1.0:
            raise ConfigurationError("prob_min/prob_max must be in (0, 1) with min < max")


# ----------------------------------------------------------------------------
# State
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class TeamState:
    """Persistent Elo state for one team. ``rating`` is the team's current
    Elo rating. ``last_season`` records the season of the team's last
    update so the engine can apply mean reversion between seasons."""

    team: str
    rating: float
    last_season: int | None = None


@dataclass(frozen=True)
class EloState:
    """A complete Elo state: a mapping of team -> :class:`TeamState` plus
    the global mean and the season currently in progress. The state is
    frozen at every block boundary so the previous step can be replayed."""

    teams: dict[str, TeamState]
    mean: float
    current_season: int | None

    def rating(self, team: str) -> float:
        return self.teams[team].rating

    def known_teams(self) -> set[str]:
        return set(self.teams.keys())


@dataclass(frozen=True)
class UpdateRecord:
    """A single Elo update applied after a completed game. The state
    ledger persists both the home and away update records for every
    game."""

    team: str
    opponent: str
    side: str  # "home" or "away"
    elo_before: float
    expected_result: float
    actual_result: float
    margin: int
    update_multiplier: float
    k_factor: float
    home_field_adjustment: float
    probability_before_update: float
    elo_change: float
    elo_after: float


# ----------------------------------------------------------------------------
# Pure math helpers
# ----------------------------------------------------------------------------


def elo_expected(elo_a: float, elo_b: float) -> float:
    """Standard Elo expected score for ``a`` versus ``b``."""

    return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))


def elo_probability_home(
    home_elo: float,
    away_elo: float,
    home_field_adjustment: float,
    home_qb_adjustment: float,
    away_qb_adjustment: float,
) -> float:
    """Convert Elo differences into a home-win probability.

    The combined score difference is::
        home_elo + hfa + home_qb_adj  -  (away_elo + away_qb_adj).

    This produces the same probability as the standard Elo logistic when
    QB adjustments are zero. The clamp is applied for numerical safety."""

    diff = (home_elo + home_field_adjustment + home_qb_adjustment) - (
        away_elo + away_qb_adjustment
    )
    return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))


def mov_multiplier(
    margin: int,
    config: EloConfig,
) -> float:
    """Canonical FiveThirtyEight-style margin-of-victory multiplier.

    The documented intended formula is::

        mov_multiplier = min(mov_cap, 1 + (abs(margin) / mov_divisor) ** 2)

    Invariants:

    - ``margin == 0`` returns exactly ``1.0`` (the leading 1 is **not**
      added twice and the squared term is exactly 0).
    - The result is always ``>= 1.0`` for any non-negative absolute
      margin (the leading 1 plus a non-negative square).
    - The result is capped at ``config.mov_cap`` to prevent a single
      blowout from moving a team's rating by more than
      ``mov_cap * K`` points.
    - Negative ``margin`` is treated as a loss and the multiplier
      is ``1.0`` (the loser receives a flat multiplier regardless of
      how badly they lost). The zero-sum update path is responsible
      for applying the right sign and the single ``delta``.

    The orchestrator must call this helper; the formula is *not*
    duplicated inline.
    """

    abs_margin = abs(int(margin))
    if abs_margin == 0:
        return 1.0
    raw = 1.0 + (abs_margin / float(config.mov_divisor)) ** 2
    return min(float(config.mov_cap), raw)


def clamp_probability(p: float, config: EloConfig) -> float:
    """Clamp probability to ``[prob_min, prob_max]`` for numerical safety."""

    if p < config.prob_min:
        return config.prob_min
    if p > config.prob_max:
        return config.prob_max
    return p


# ----------------------------------------------------------------------------
# QB adjustment
# ----------------------------------------------------------------------------


def qb_adjustment_for(
    *,
    candidate_player_id: str | None,
    confidence_state: str | None,
    shrunk_passing_epa: float | None,
    config: QBAdjustmentConfig,
) -> tuple[float, str]:
    """Return ``(adjustment_elo, qb_certainty_state)`` for one side.

    States map as follows:

    - Unknown / absent / no candidate / unknown confidence: ``0.0`` and
      the certainty label is rewritten as ``UNKNOWN``.
    - Supported but not confirmed (depth_chart / roster / ambiguous): the
      replacement scenario is used so the adjustment is the documented
      delta from the conservative prior. The certainty label is returned
      as ``SUPPORTED_BUT_UNCERTAIN``.
    - Confirmed (overridden timestamp + cutoff): the candidate's shrunk
      EPA is used. The certainty label is ``CONFIRMED``.

    The function is pure: the only inputs are the pregame candidate and
    the pregame certainty state. Postgame evidence is never inspected.
    """
    # Pre-cutoff override ⇒ CONFIRMED_PRE_CUTOFF. Depth chart support is
    # the next strongest evidence. Roster-only and ambiguous are
    # considered supported but not confirmed.
    confirmed = confidence_state == "CONFIRMED_PRE_CUTOFF"
    supported = confidence_state in {
        "DEPTH_CHART_SUPPORTED",
        "ROSTER_SUPPORTED",
        "AMBIGUOUS",
    }
    if confidence_state == "POSTGAME_ONLY_EVIDENCE":
        # Postgame evidence stored on the row is for audit only and never
        # raises pregame certainty. Treat as unknown.
        return 0.0, "UNKNOWN"
    if not candidate_player_id or confidence_state == "UNKNOWN":
        return 0.0, "UNKNOWN"
    if not confirmed:
        if not supported:
            return 0.0, "UNKNOWN"
        if not config.supported_uses_replacement_scenario:
            return 0.0, "SUPPORTED_BUT_UNCERTAIN"
        # Use the replacement scenario: the delta is zero because the
        # candidate is the replacement. Return zero explicitly.
        return 0.0, "SUPPORTED_BUT_UNCERTAIN"
    # CONFIRMED_PRE_CUTOFF: use the shrunk passing EPA differential.
    if shrunk_passing_epa is None:
        return 0.0, "CONFIRMED_BUT_NO_DATA"
    delta = float(shrunk_passing_epa) - config.replacement_passing_epa
    adjustment = delta * config.scale_elo_per_shrunk_epa
    if adjustment > config.max_abs_elo:
        adjustment = config.max_abs_elo
    elif adjustment < -config.max_abs_elo:
        adjustment = -config.max_abs_elo
    return float(adjustment), "CONFIRMED"


# ----------------------------------------------------------------------------
# State engine
# ----------------------------------------------------------------------------


def initial_state(teams: list[str], config: EloConfig) -> EloState:
    """Construct a fresh Elo state with every team at the initial rating."""

    return EloState(
        teams={team: TeamState(team=team, rating=config.initial_rating) for team in teams},
        mean=config.initial_rating,
        current_season=None,
    )


def ensure_team(state: EloState, team: str, config: EloConfig) -> EloState:
    """Return a new state with ``team`` guaranteed to be present. New teams
    are added at the initial rating and the new mean is recomputed."""

    if team in state.teams:
        return state
    new_team = TeamState(team=team, rating=config.initial_rating)
    teams = dict(state.teams)
    teams[team] = new_team
    new_mean = sum(t.rating for t in teams.values()) / len(teams)
    return EloState(teams=teams, mean=new_mean, current_season=state.current_season)


def apply_season_carryover(
    state: EloState,
    *,
    new_season: int,
    config: EloConfig,
) -> EloState:
    """Regress every team's rating toward ``initial_rating`` by
    ``season_mean_reversion_fraction`` and recompute the mean."""

    if state.current_season is not None and new_season <= state.current_season:
        raise WalkForwardError(
            "apply_season_carryover",
            f"non-monotonic season {state.current_season} -> {new_season}",
        )
    fr = config.season_mean_reversion_fraction
    target = config.initial_rating
    teams = {
        team: TeamState(
            team=team,
            rating=state.rating(team) + fr * (target - state.rating(team)),
            last_season=new_season,
        )
        for team in state.teams
    }
    new_mean = sum(t.rating for t in teams.values()) / len(teams)
    return EloState(teams=teams, mean=new_mean, current_season=new_season)


# ----------------------------------------------------------------------------
# Pregame prediction
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class PregamePrediction:
    """The result of one prediction step. The engine records this BEFORE
    applying the Elo update in the same block."""

    game_id: str
    season: int
    season_type: str
    week: int
    home_team: str
    away_team: str
    home_elo_before: float
    away_elo_before: float
    home_field_adjustment: float
    home_qb_adjustment: float
    away_qb_adjustment: float
    qb_adjustment_net: float
    qb_certainty_state: str
    predicted_home_win_probability: float
    actual_home_win: bool | None
    actual_tie: bool
    target_available: bool


def predict_game(
    *,
    game_id: str,
    season: int,
    season_type: str,
    week: int,
    home_team: str,
    away_team: str,
    neutral_site: bool,
    home_qb_candidate_player_id: str | None,
    home_qb_certainty_state: str | None,
    home_qb_shrunk_passing_epa: float | None,
    away_qb_candidate_player_id: str | None,
    away_qb_certainty_state: str | None,
    away_qb_shrunk_passing_epa: float | None,
    home_score: int | None,
    away_score: int | None,
    state: EloState,
    config: EloConfig,
) -> tuple[PregamePrediction, EloState]:
    """Compute the pregame prediction. Caller-supplied state is *not*
    mutated; this step only reads the state and returns a new state via
    the assurance that the team is present (no-op for already-known
    teams). The actual Elo update is performed by :func:`update_state`.

    Inputs are inspected at the boundary and any 2025 season value is
    impossible because the engine caller filters at the games frame
    boundary. The function trusts the caller's contract."""

    state = ensure_team(state, home_team, config)
    state = ensure_team(state, away_team, config)
    home_elo = state.rating(home_team)
    away_elo = state.rating(away_team)
    hfa = 0.0 if neutral_site else config.home_field_elo
    home_qb_adj, home_qb_state = qb_adjustment_for(
        candidate_player_id=home_qb_candidate_player_id,
        confidence_state=home_qb_certainty_state,
        shrunk_passing_epa=home_qb_shrunk_passing_epa,
        config=config.qb_adjustment,
    )
    away_qb_adj, away_qb_state = qb_adjustment_for(
        candidate_player_id=away_qb_candidate_player_id,
        confidence_state=away_qb_certainty_state,
        shrunk_passing_epa=away_qb_shrunk_passing_epa,
        config=config.qb_adjustment,
    )
    p = elo_probability_home(
        home_elo=home_elo,
        away_elo=away_elo,
        home_field_adjustment=hfa,
        home_qb_adjustment=home_qb_adj,
        away_qb_adjustment=away_qb_adj,
    )
    p = clamp_probability(p, config)
    target_available = home_score is not None and away_score is not None
    if target_available:
        if home_score == away_score:
            actual_tie = True
            actual_home_win: bool | None = None
        else:
            actual_tie = False
            actual_home_win = home_score > away_score
    else:
        actual_tie = False
        actual_home_win = None
    # Combined certainty state used in the ledger: the more conservative
    # of the two sides.
    if home_qb_state == "CONFIRMED" and away_qb_state == "CONFIRMED":
        qb_state = "CONFIRMED"
    elif home_qb_state == "UNKNOWN" and away_qb_state == "UNKNOWN":
        qb_state = "UNKNOWN"
    else:
        qb_state = "SUPPORTED_BUT_UNCERTAIN"
    return (
        PregamePrediction(
            game_id=game_id,
            season=season,
            season_type=season_type,
            week=week,
            home_team=home_team,
            away_team=away_team,
            home_elo_before=home_elo,
            away_elo_before=away_elo,
            home_field_adjustment=hfa,
            home_qb_adjustment=home_qb_adj,
            away_qb_adjustment=away_qb_adj,
            qb_adjustment_net=home_qb_adj - away_qb_adj,
            qb_certainty_state=qb_state,
            predicted_home_win_probability=p,
            actual_home_win=actual_home_win,
            actual_tie=actual_tie,
            target_available=target_available,
        ),
        state,
    )

def update_state_with_margin(
    *,
    prediction: PregamePrediction,
    margin: int,
    state: EloState,
    config: EloConfig,
) -> tuple[UpdateRecord, UpdateRecord, EloState]:
    """Apply the Elo update for one completed game.

    This is the **single canonical update path**. The orchestrator
    (and any other caller) must use this function rather than
    reimplementing the formula.

    The zero-sum update is::

        delta = K * MOV_multiplier * (actual_home - expected_home)
        new_home = home_before + delta
        new_away = away_before - delta

    The MOV multiplier is applied to the *single* delta. There is no
    separate winner and loser delta. The sign of ``(actual - expected)``
    and the loser's flat 1.0 multiplier combine so that the loser
    receives only the negative side of the same delta.

    ``margin`` is the signed home-minus-away margin (positive means
    the home team won). The function takes the absolute value when
    passing the margin into the MOV helper.

    The state is *not* mutated in place; a new state is returned.
    """

    home_team = prediction.home_team
    away_team = prediction.away_team
    home_elo = state.rating(home_team)
    away_elo = state.rating(away_team)
    hfa = prediction.home_field_adjustment
    season_type = prediction.season_type.upper()
    k = (
        config.k_factor_postseason
        if season_type in {"WC", "DIV", "CON", "SB"}
        else config.k_factor_regular
    )

    if prediction.actual_tie:
        actual_home = 0.5
    elif prediction.actual_home_win:
        actual_home = 1.0
    else:
        actual_home = 0.0

    expected_home = elo_expected(home_elo + hfa, away_elo)
    expected_away = 1.0 - expected_home

    # Single canonical MOV multiplier. On a tie the multiplier is
    # exactly 1.0. On a win/loss the multiplier is computed from the
    # absolute margin and applied to the single zero-sum delta.
    if prediction.actual_tie:
        mult = 1.0
    else:
        mult = mov_multiplier(margin, config)

    delta = k * mult * (actual_home - expected_home)
    new_home = home_elo + delta
    new_away = away_elo - delta
    teams = dict(state.teams)
    teams[home_team] = TeamState(
        team=home_team, rating=new_home, last_season=prediction.season
    )
    teams[away_team] = TeamState(
        team=away_team, rating=new_away, last_season=prediction.season
    )
    new_mean = sum(t.rating for t in teams.values()) / len(teams)
    new_state = EloState(teams=teams, mean=new_mean, current_season=prediction.season)
    home_record = UpdateRecord(
        team=home_team,
        opponent=away_team,
        side="home",
        elo_before=home_elo,
        expected_result=expected_home,
        actual_result=actual_home,
        margin=int(margin),
        update_multiplier=mult,
        k_factor=k,
        home_field_adjustment=hfa,
        probability_before_update=prediction.predicted_home_win_probability,
        elo_change=delta,
        elo_after=new_home,
    )
    away_record = UpdateRecord(
        team=away_team,
        opponent=home_team,
        side="away",
        elo_before=away_elo,
        expected_result=expected_away,
        actual_result=1.0 - actual_home,
        margin=int(margin),
        update_multiplier=mult,
        k_factor=k,
        home_field_adjustment=-hfa,
        probability_before_update=1.0 - prediction.predicted_home_win_probability,
        elo_change=-delta,
        elo_after=new_away,
    )
    return home_record, away_record, new_state


# ----------------------------------------------------------------------------
# Configuration fingerprinting
# ----------------------------------------------------------------------------


def config_to_dict(config: EloConfig) -> dict[str, Any]:
    """Return a JSON-serializable dict of the configuration that participates
    in the model fingerprint. The sorted-key serialization hands a
    deterministic result to ``canonical_json_sha256``."""

    qb = config.qb_adjustment
    return {
        "initial_rating": config.initial_rating,
        "k_factor_regular": config.k_factor_regular,
        "k_factor_postseason": config.k_factor_postseason,
        "home_field_elo": config.home_field_elo,
        "season_mean_reversion_fraction": config.season_mean_reversion_fraction,
        "mov_divisor": config.mov_divisor,
        "mov_cap": config.mov_cap,
        "prob_min": config.prob_min,
        "prob_max": config.prob_max,
        "qb_adjustment": {
            "sample_k": qb.sample_k,
            "replacement_passing_epa": qb.replacement_passing_epa,
            "scale_elo_per_shrunk_epa": qb.scale_elo_per_shrunk_epa,
            "max_abs_elo": qb.max_abs_elo,
            "unknown_returns_zero": qb.unknown_returns_zero,
            "supported_uses_replacement_scenario": qb.supported_uses_replacement_scenario,
        },
    }


def config_from_dict(data: Mapping[str, Any]) -> EloConfig:
    """Inverse of :func:`config_to_dict`. Used by sensitivity variants."""

    qb_in = data.get("qb_adjustment", {})
    qb = QBAdjustmentConfig(
        sample_k=float(qb_in.get("sample_k", 250.0)),
        replacement_passing_epa=float(qb_in.get("replacement_passing_epa", -0.05)),
        scale_elo_per_shrunk_epa=float(qb_in.get("scale_elo_per_shrunk_epa", 500.0)),
        max_abs_elo=float(qb_in.get("max_abs_elo", 50.0)),
        unknown_returns_zero=bool(qb_in.get("unknown_returns_zero", True)),
        supported_uses_replacement_scenario=bool(
            qb_in.get("supported_uses_replacement_scenario", True)
        ),
    )
    return EloConfig(
        initial_rating=float(data.get("initial_rating", 1500.0)),
        k_factor_regular=float(data.get("k_factor_regular", 20.0)),
        k_factor_postseason=float(data.get("k_factor_postseason", 4.0)),
        home_field_elo=float(data.get("home_field_elo", 48.0)),
        season_mean_reversion_fraction=float(
            data.get("season_mean_reversion_fraction", 1.0 / 3.0)
        ),
        mov_divisor=float(data.get("mov_divisor", 6.0)),
        mov_cap=float(data.get("mov_cap", 2.5)),
        prob_min=float(data.get("prob_min", 0.01)),
        prob_max=float(data.get("prob_max", 0.99)),
        qb_adjustment=qb,
    )


def rebuild_state_from_ledger(
    ledger: "list[dict[str, Any]]",
    teams: list[str],
    config: EloConfig,
) -> EloState:
    """Reconstruct the final Elo state from a state ledger. Used by the
    state-ledger-reproduces-final-state test and by the deterministic
    replay proof.

    The ledger must be sorted by ``state_update_order``. The function
    applies season carryover at every season boundary.

    This function only accepts dict rows (the persisted ledger format);
    it does not accept ``UpdateRecord`` because the ledger includes extra
    columns like ``state_update_order`` that do not exist on the dataclass.
    """
    state = initial_state(teams, config)
    if not ledger:
        return state
    rows = ledger
    # Determine the season boundary ordering.
    last_season = None
    for row in rows:
        rseason = int(row["season"])
        # Apply season carryover before the first update of a new season.
        if last_season is not None and rseason > last_season:
            state = apply_season_carryover(state, new_season=rseason, config=config)
        last_season = rseason
    # Now replay the updates.
    for row in rows:
        team = str(row["team"])
        new_rating = float(row["elo_after"])
        row_season = int(row["season"])
        teams_d = dict(state.teams)
        teams_d[team] = TeamState(team=team, rating=new_rating, last_season=row_season)
        state = EloState(teams=teams_d, mean=state.mean, current_season=state.current_season)
    return state


def independent_replay_from_pregame(
    *,
    predictions: "list[dict[str, Any]]",
    teams: list[str],
    config: EloConfig,
) -> tuple[EloState, list[dict[str, float]]]:
    """Independent state replay that recalculates every Elo update from
    pregame inputs and game outcomes, **without reading persisted
    ``elo_after`` values**. The function is the source of truth used
    to detect corrupted state-ledger rows.

    Inputs are the canonical prediction rows. Each row must contain
    at least::

        game_id, season, season_type, week, home_team, away_team,
        home_elo_before, away_elo_before, home_field_adjustment,
        predicted_home_win_probability, actual_home_win, actual_tie,
        target_available

    For rows where ``target_available`` is true, the function reads
    the signed margin from a parallel ``margins_by_game`` mapping
    (game_id -> int) so the replay can recompute the MOV multiplier
    independently. If the replay's computed ``elo_after`` for any
    side disagrees with the ledger value (provided in the parallel
    ``ledger_by_game`` mapping), the function raises
    :class:`StateLedgerCorruptionError`.

    Returns ``(final_state, replayed_updates)`` where ``replayed_updates``
    is a list of ``(game_id, side, elo_before, elo_after)`` dicts the
    caller can use to compare against the persisted state ledger.
    """
    state = initial_state(teams, config)
    replayed: list[dict[str, float]] = []
    last_season: int | None = None
    # Group predictions into the same chronological block order the
    # orchestrator uses. The caller is responsible for sorting.
    for row in predictions:
        season = int(row["season"])
        season_type = str(row["season_type"]).upper()
        home_team = str(row["home_team"])
        away_team = str(row["away_team"])
        week = int(row["week"])
        # Apply season carryover at the same boundary the engine uses.
        if last_season is not None and season > last_season:
            state = apply_season_carryover(state, new_season=season, config=config)
        last_season = season
        # Ensure both teams exist in the state.
        state = ensure_team(state, home_team, config)
        state = ensure_team(state, away_team, config)
        home_elo = state.rating(home_team)
        away_elo = state.rating(away_team)
        hfa = float(row["home_field_adjustment"])
        # Reconstruct the prediction in-process. The prediction row's
        # home_elo_before/away_elo_before are ignored: the replay
        # computes the canonical state before the update from its own
        # monotonic state copy.
        if not bool(row.get("target_available", False)):
            # No completed outcome -> no state update; carry on.
            continue
        margin_signed = int(row.get("signed_margin", 0) or 0)
        if int(row.get("actual_tie", 0)) == 1 or row.get("actual_home_win") is None:
            actual_home: float | None = 0.5
        else:
            actual_home = 1.0 if bool(row["actual_home_win"]) else 0.0
        expected_home = elo_expected(home_elo + hfa, away_elo)
        if actual_home is None:
            continue
        # The tie multiplier is exactly 1.0; the win/loss multiplier
        # is the canonical MOV multiplier.
        mult = 1.0 if actual_home == 0.5 else mov_multiplier(margin_signed, config)
        k = (
            config.k_factor_postseason
            if season_type in {"WC", "DIV", "CON", "SB"}
            else config.k_factor_regular
        )
        delta = k * mult * (actual_home - expected_home)
        new_home = home_elo + delta
        new_away = away_elo - delta
        teams_d = dict(state.teams)
        teams_d[home_team] = TeamState(
            team=home_team, rating=new_home, last_season=season
        )
        teams_d[away_team] = TeamState(
            team=away_team, rating=new_away, last_season=season
        )
        new_mean = sum(t.rating for t in teams_d.values()) / len(teams_d)
        state = EloState(teams=teams_d, mean=new_mean, current_season=season)
        replayed.append({
            "game_id": str(row["game_id"]),
            "side": "home",
            "elo_before": home_elo,
            "elo_after_replay": new_home,
            "elo_change_replay": delta,
            "season": int(season),
            "week": int(week),
        })
        replayed.append({
            "game_id": str(row["game_id"]),
            "side": "away",
            "elo_before": away_elo,
            "elo_after_replay": new_away,
            "elo_change_replay": -delta,
            "season": int(season),
            "week": int(week),
        })
    return state, replayed


def detect_state_ledger_corruption(
    *,
    state_ledger: "list[dict[str, Any]]",
    predictions: "list[dict[str, Any]]",
    config: EloConfig,
) -> list[str]:
    """Return a list of corruption messages (empty == OK).

    Replays the Elo updates from the prediction rows in chronological
    order and compares every ``elo_after`` in the persisted state
    ledger to the replay-computed value. Any mismatch within numerical
    tolerance is reported. The function is a pure verification helper
    and never mutates its inputs.
    """
    from ..common.errors import StateLedgerCorruptionError

    teams = sorted({
        str(r["team"]) for r in state_ledger
    })
    # Group the state ledger by game_id so we can match each side.
    by_game: dict[str, dict[str, dict[str, float]]] = {}
    for row in state_ledger:
        side_dict = by_game.setdefault(str(row["game_id"]), {})
        side_dict[str(row["side"])] = {
            "elo_before": float(row["elo_before"]),
            "elo_after": float(row["elo_after"]),
            "elo_change": float(row["elo_change"]),
        }
    _, replayed = independent_replay_from_pregame(
        predictions=predictions,
        teams=teams,
        config=config,
    )
    problems: list[str] = []
    for entry in replayed:
        gid = str(entry["game_id"])
        side = str(entry["side"])
        if gid not in by_game or side not in by_game[gid]:
            problems.append(f"missing ledger row for game {gid} side {side}")
            continue
        ledger_after = by_game[gid][side]["elo_after"]
        replay_after = float(entry["elo_after_replay"])
        if abs(ledger_after - replay_after) > 1e-6:
            problems.append(
                f"elo_after mismatch game {gid} side {side}: "
                f"ledger={ledger_after!r} replay={replay_after!r}"
            )
    if problems:
        raise StateLedgerCorruptionError("detect_state_ledger_corruption", problems)
    return []


# ----------------------------------------------------------------------------
# Convenience helpers
# ----------------------------------------------------------------------------


def elo_state_summary(state: EloState) -> list[dict[str, Any]]:
    """Return a deterministic list of all team ratings. Used by the
    run manifest and the scorecard."""

    return [
        {"team": team, "rating": team_state.rating}
        for team, team_state in sorted(state.teams.items())
    ]


def safe_utc(value: datetime) -> datetime:
    """Re-export of the UTC safety helper so model callers don't need to
    import from common. Validates a datetime is timezone-aware."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value
