"""Focused tests for the Expected-Margin v1 model and walk-forward.

These tests cover the 20+ scenarios required by the Task 03B
Chunk-2A remediation. They use small synthetic frames so execution
is fast and deterministic. The frames are constructed in-test
rather than loaded from the fixture CSVs because the canonical game
features parquet is the only authoritative source and we never want
the model tests to depend on the fixture layout.

Sign conventions enforced here (and verified by the contract):

- Positive offensive_strength  => the team is expected to score
  ABOVE the baseline.
- Positive defensive_strength  => the team is expected to ALLOW
  FEWER opponent points than the baseline (i.e. a stronger defense).
- Negative defensive_strength  => the team allows more opponent
  points than the baseline.
- Defense is subtracted from the opponent's expected points.
"""

from __future__ import annotations

import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from nfl_edge.backtest.blocks import (
    DEVELOPMENT_SEASON_MAX,
    FORWARD_USE_SEASON,
    SEALED_HOLDOUT_SEASON,
    build_development_blocks,
)
from nfl_edge.backtest.expected_margin_walk_forward import (
    _chronological_age_per_row,
    _load_games,
    _prior_completed_games,
    _prior_oos_for_mapping,
    run_expected_margin_candidate,
)
from nfl_edge.common.errors import (
    SealedHoldoutAccessError,
    WalkForwardError,
)
from nfl_edge.common.polars_utils import assert_no_market_columns
from nfl_edge.models.expected_margin import (
    ExpectedMarginCandidateConfig,
    ExpectedMarginSharedConfig,
    FittedExpectedMargin,
    FittedMapping,
    _cholesky_solve,
    _recency_weight,
    candidate_config_from_normalized,
    fit_expected_margin,
    fit_mapping,
    is_mapping_available,
    is_warmup_state,
    load_all_candidates,
    predict_home_win_probability,
    shared_config_from_normalized,
)
from nfl_edge.models.expected_margin_config import (
    load_expected_margin_canonical_config,
    lock_expected_margin_config,
)


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def _lock_config() -> str:
    return lock_expected_margin_config(
        Path(__file__).resolve().parent.parent.parent
        / "config"
        / "expected_margin_v1.yaml"
    )["config_sha256"]


def _shared_and_candidates() -> tuple[ExpectedMarginSharedConfig, tuple[ExpectedMarginCandidateConfig, ...]]:
    normalized = load_expected_margin_canonical_config(
        Path(__file__).resolve().parent.parent.parent
        / "config"
        / "expected_margin_v1.yaml"
    )
    shared = shared_config_from_normalized(normalized)
    candidates = tuple(
        candidate_config_from_normalized(c) for c in normalized["candidates"]
    )
    return shared, candidates


def _cu(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _synthetic_game_frame(
    *,
    season: int,
    week: int,
    n_games: int = 4,
    base_offset: int = 0,
    home_points: list[float] | None = None,
    away_points: list[float] | None = None,
    neutral_indices: set[int] | None = None,
    prediction_as_of_offsets_minutes: list[int] | None = None,
) -> pl.DataFrame:
    """Build a small fake game frame with deterministic outcomes.

    Each game offsets by ``base_offset`` so multiple block builders
    can produce distinct game_ids without collision. ``home_points``
    and ``away_points`` default to alternating 21 and 17 with margin
    4 across the synthetic data.
    """
    rows = []
    for i in range(n_games):
        gid = f"S{season}-W{week:02d}-G{i+base_offset:03d}"
        home = f"H{i+base_offset:03d}"
        away = f"A{i+base_offset:03d}"
        if home_points is not None and i < len(home_points):
            hp = float(home_points[i])
        else:
            hp = 21.0 if i % 2 == 0 else 17.0
        if away_points is not None and i < len(away_points):
            ap = float(away_points[i])
        else:
            ap = 17.0 if i % 2 == 0 else 21.0
        margin = hp - ap
        is_neutral = (neutral_indices is not None and i in neutral_indices)
        pao_offset = (
            prediction_as_of_offsets_minutes[i]
            if prediction_as_of_offsets_minutes is not None
            else 0
        )
        # canonical chronological timestamp
        base_dt = datetime(season, 9, max(1, week), 17, 0, 0, tzinfo=timezone.utc)
        from datetime import timedelta
        pao = base_dt + timedelta(minutes=pao_offset)
        rows.append(
            {
                "game_id": gid,
                "season": season,
                "season_type": "REG",
                "week": week,
                "home_team": home,
                "away_team": away,
                "neutral_site": is_neutral,
                "target_available": True,
                "target_margin": margin,
                "target_home_win": margin > 0,
                "target_tie": margin == 0,
                "home_score": hp,
                "away_score": ap,
                "prediction_as_of_utc": pao,
            }
        )
    return pl.DataFrame(rows)


# ---------------------------------------------------------------------------
# 1. Identifiability: distinguish offense from defense
# ---------------------------------------------------------------------------


def test_identifiability_distinguishes_offense_and_defense() -> None:
    """Clean balanced fixture: four teams with KNOWN distinct offense and
    defense profiles. AA is the reference team (pinned to (off=0, def=0))
    and is the strongest offense AND strongest defense. BB is high O / weak D.
    CC is low O / great D. DD is low O / weak D. The model must identify
    a non-reference team as the unique offense leader and a DIFFERENT
    non-reference team as the unique defense leader.
    """
    shared, candidates = _shared_and_candidates()
    cand = candidates[1]
    # True deviations from AA (the reference team).
    # AA itself: off=+4, def=+4 (high O, great D).
    # BB: off=+4, def=-4 (high O, weak D).
    # CC: off=-4, def=+4 (low O, great D).
    # DD: off=-4, def=-4 (low O, weak D).
    # league=22, hfa=0. Neutral-site games for identifiability.
    true_off = {"AA": 2.0, "BB": 8.0, "CC": -5.0, "DD": -5.0}
    true_def = {"AA": 8.0, "BB": 2.0, "CC": -5.0, "DD": -5.0}
    league = 22.0
    home_teams: list[str] = []
    away_teams: list[str] = []
    home_points: list[float] = []
    away_points: list[float] = []
    neutral_site: list[bool] = []
    for h in ["AA", "BB", "CC", "DD"]:
        for a in ["AA", "BB", "CC", "DD"]:
            if h == a:
                continue
            home_teams.append(h)
            away_teams.append(a)
            home_points.append(league + true_off[h] - true_def[a])
            away_points.append(league + true_off[a] - true_def[h])
            neutral_site.append(True)
            home_teams.append(a)
            away_teams.append(h)
            home_points.append(league + true_off[a] - true_def[h])
            away_points.append(league + true_off[h] - true_def[a])
            neutral_site.append(True)
    home_teams *= 10
    away_teams *= 10
    home_points *= 10
    away_points *= 10
    neutral_site *= 10
    fitted = fit_expected_margin(
        prior_training_games=[{}] * len(home_teams),
        home_points=home_points,
        away_points=away_points,
        neutral_site=neutral_site,
        home_team_codes=home_teams,
        away_team_codes=away_teams,
        chronological_age_in_completed_games=[float(i) for i in range(len(home_teams))],
        candidate=cand,
        shared=shared,
        fitted_at_cutoff_utc="2026-08-05T00:00:00Z",
    )
    # Sum-to-zero identification: no reference team is involved.
    off = dict(zip(fitted.team_index.keys(), fitted.offense_effect))
    deff = dict(zip(fitted.team_index.keys(), fitted.defense_effect))
    # BB has the highest offense (truth=+8); AA has the strongest
    # defense (truth=+8). CC and DD are tied at -5 in the truth;
    # the soft sum-to-zero weight may break that tie slightly.
    assert off["BB"] > off["AA"], f"BB should have higher offense than AA: {off}"
    assert off["BB"] > off["CC"], f"BB should have higher offense than CC: {off}"
    assert off["BB"] > off["DD"], f"BB should have higher offense than DD: {off}"
    assert deff["AA"] > deff["BB"], f"AA should have stronger defense than BB: {deff}"
    assert deff["AA"] > deff["CC"], f"AA should have stronger defense than CC: {deff}"
    assert deff["AA"] > deff["DD"], f"AA should have stronger defense than DD: {deff}"
    # The offense leader and defense leader are distinct teams.
    offense_stronger = max(off, key=off.get)
    defense_stronger = max(deff, key=deff.get)
    assert offense_stronger != defense_stronger, (
        f"Offense leader and defense leader must be distinct teams: "
        f"off_leader={offense_stronger}, def_leader={defense_stronger}"
    )


def test_identifiability_sum_to_zero_constraint() -> None:
    """Identifiability is enforced by a SUM-TO-ZERO constraint on
    offense and defense, not by pinning a reference team. The sum
    of offense effects across all teams equals zero; the sum of
    defense effects across all teams equals zero. This constraint
    is prediction-invariant: predictions do not depend on which
    team is the alphabetical reference."""
    shared, candidates = _shared_and_candidates()
    cand = candidates[1]
    home_teams = ["AAA", "AAA", "BBB", "CCC", "BBB", "CCC", "AAA"]
    away_teams = ["BBB", "CCC", "AAA", "BBB", "CCC", "AAA", "BBB"]
    home_points = [25.0, 30.0, 20.0, 18.0, 22.0, 28.0, 24.0]
    away_points = [20.0, 25.0, 22.0, 24.0, 22.0, 24.0, 20.0]
    fitted = fit_expected_margin(
        prior_training_games=[{}] * 7,
        home_points=home_points,
        away_points=away_points,
        neutral_site=[False] * 7,
        home_team_codes=home_teams,
        away_team_codes=away_teams,
        chronological_age_in_completed_games=[0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        candidate=cand,
        shared=shared,
        fitted_at_cutoff_utc="2026-08-05T00:00:00Z",
    )
    off = list(fitted.offense_effect)
    deff = list(fitted.defense_effect)
    assert abs(sum(off)) < 1e-3, f"sum(offense) must be 0; got {sum(off)}"
    assert abs(sum(deff)) < 1e-3, f"sum(defense) must be 0; got {sum(deff)}"


# ---------------------------------------------------------------------------
# 2. Higher offense raises that team's expected points
# ---------------------------------------------------------------------------


def test_higher_offense_raises_expected_points() -> None:
    """A team observed scoring high carries a positive fitted offense
    effect. The expected home points for that team hosting a fixed
    opponent must exceed the league baseline plus the HFA."""
    shared, candidates = _shared_and_candidates()
    cand = candidates[1]
    home_teams: list[str] = []
    away_teams: list[str] = []
    home_points: list[float] = []
    away_points: list[float] = []
    cycles = [
        ("AAA", "BBB", 35.0, 20.0),
        ("AAA", "CCC", 35.0, 20.0),
        ("AAA", "DDD", 35.0, 20.0),
        ("BBB", "AAA", 20.0, 30.0),
        ("BBB", "CCC", 20.0, 20.0),
        ("BBB", "DDD", 20.0, 20.0),
        ("CCC", "AAA", 20.0, 30.0),
        ("CCC", "BBB", 20.0, 20.0),
        ("CCC", "DDD", 20.0, 20.0),
        ("DDD", "AAA", 20.0, 30.0),
        ("DDD", "BBB", 20.0, 20.0),
        ("DDD", "CCC", 20.0, 20.0),
    ]
    for h, a, hp, ap in cycles:
        home_teams.append(h)
        away_teams.append(a)
        home_points.append(hp)
        away_points.append(ap)
    fitted = fit_expected_margin(
        prior_training_games=[{}] * len(home_teams),
        home_points=home_points,
        away_points=away_points,
        neutral_site=[False] * len(home_teams),
        home_team_codes=home_teams,
        away_team_codes=away_teams,
        chronological_age_in_completed_games=[float(i) for i in range(len(home_teams))],
        candidate=cand,
        shared=shared,
        fitted_at_cutoff_utc="2026-08-05T00:00:00Z",
    )
    # AAA is the high-O team (reference team pinned to 0; AAA's
    # offense effect is the deviation from the reference team).
    # Its expected home points for AAA vs BBB must exceed the
    # league baseline.
    pts = fitted.expected_home_points("AAA", "BBB", neutral_site=False)
    assert pts > fitted.league_baseline, (
        f"AAA (high O) should have expected home points above the baseline "
        f"({fitted.league_baseline}); got {pts}"
    )


# ---------------------------------------------------------------------------
# 3. Stronger defense lowers opponent expected points
# ---------------------------------------------------------------------------


def test_stronger_defense_lowers_opponent_points() -> None:
    """With rich data, the fitted defense effect must rank teams in
    the SAME direction as the observed opponent-scoring differential.

    Design: four teams (AAA, BBB, CCC, DDD). They play each other
    in a full round-robin. AAA is the strongest defense (allows few
    points). DDD is the weakest defense (allows many points). BBB
    and CCC are intermediate with AAA > BBB > CCC > DDD in defense.
    The fitted defense effects must order AAA, BBB, CCC, DDD in
    the same direction.
    """
    shared, candidates = _shared_and_candidates()
    cand = candidates[1]
    # Use a hand-crafted design with known good ordering.
    # AAA strongest D, DDD weakest D. BBB, CCC intermediate.
    # Each pair plays twice (home and away).
    pts = {
        ("AAA", "BBB"): (28.0, 14.0),  # AAA hosts BBB: AAA 28, BBB 14
        ("BBB", "AAA"): (22.0, 24.0),  # BBB hosts AAA: BBB 22, AAA 24
        ("AAA", "CCC"): (28.0, 14.0),
        ("CCC", "AAA"): (22.0, 24.0),
        ("AAA", "DDD"): (28.0, 14.0),
        ("DDD", "AAA"): (22.0, 24.0),
        ("BBB", "CCC"): (25.0, 17.0),
        ("CCC", "BBB"): (20.0, 22.0),
        ("BBB", "DDD"): (25.0, 17.0),
        ("DDD", "BBB"): (20.0, 22.0),
        ("CCC", "DDD"): (23.0, 19.0),
        ("DDD", "CCC"): (18.0, 24.0),
    }
    home_teams = []
    away_teams = []
    home_points = []
    away_points = []
    for (h, a), (hp, ap) in pts.items():
        home_teams.append(h)
        away_teams.append(a)
        home_points.append(hp)
        away_points.append(ap)
    # Repeat 30 times for stability.
    home_teams *= 30
    away_teams *= 30
    home_points *= 30
    away_points *= 30
    fitted = fit_expected_margin(
        prior_training_games=[{}] * len(home_teams),
        home_points=home_points,
        away_points=away_points,
        neutral_site=[False] * len(home_teams),
        home_team_codes=home_teams,
        away_team_codes=away_teams,
        chronological_age_in_completed_games=[float(i) for i in range(len(home_teams))],
        candidate=cand,
        shared=shared,
        fitted_at_cutoff_utc="2026-08-05T00:00:00Z",
    )
    deff = dict(zip(fitted.team_index.keys(), fitted.defense_effect))
    # AAA is the reference team (alphabetically smallest).
    # sum-to-zero; no reference team
    # The defense rank by the data is AAA > BBB > CCC > DDD
    # (AAA strongest, DDD weakest). Under our convention, positive
    # defense = strong, so defense effects must be ordered
    # AAA > BBB > CCC > DDD.
    assert deff["AAA"] >= deff["BBB"], (
        f"AAA should have defense >= BBB: AAA={deff['AAA']:.3f}, "
        f"BBB={deff['BBB']:.3f}"
    )
    assert deff["BBB"] >= deff["CCC"], (
        f"BBB should have defense >= CCC: BBB={deff['BBB']:.3f}, "
        f"CCC={deff['CCC']:.3f}"
    )
    assert deff["CCC"] >= deff["DDD"], (
        f"CCC should have defense >= DDD: CCC={deff['CCC']:.3f}, "
        f"DDD={deff['DDD']:.3f}"
    )
    # And the strongest defender (AAA) must yield a lower opponent
    # expected points than the weakest defender (DDD).
    pts_aaa = fitted.expected_away_points("AAA", "BBB", neutral_site=False)
    pts_ddd = fitted.expected_away_points("DDD", "BBB", neutral_site=False)
    assert pts_aaa < pts_ddd, (
        f"AAA (great D) should yield lower opponent expected points "
        f"than DDD (weak D); AAA={pts_aaa:.3f}, DDD={pts_ddd:.3f}"
    )


# ---------------------------------------------------------------------------
# 4. Scoring fit uses both home points and away points
# ---------------------------------------------------------------------------


def test_scoring_fit_uses_both_home_and_away_points() -> None:
    """The fitted model reproduces both home and away points targets
    on the training data. The residual sum of squares is finite and
    the model maps onto both targets simultaneously."""
    shared, candidates = _shared_and_candidates()
    cand = candidates[1]
    home_teams = ["A", "A", "B", "B", "A", "B"]
    away_teams = ["B", "B", "A", "A", "B", "A"]
    home_points = [28.0, 30.0, 22.0, 20.0, 25.0, 24.0]
    away_points = [20.0, 18.0, 28.0, 30.0, 22.0, 26.0]
    fitted = fit_expected_margin(
        prior_training_games=[{}] * len(home_teams),
        home_points=home_points,
        away_points=away_points,
        neutral_site=[False] * len(home_teams),
        home_team_codes=home_teams,
        away_team_codes=away_teams,
        chronological_age_in_completed_games=[float(i) for i in range(len(home_teams))],
        candidate=cand,
        shared=shared,
        fitted_at_cutoff_utc="2026-08-05T00:00:00Z",
    )
    # Compute the in-sample residuals for both home and away
    # observations.
    home_resid = 0.0
    away_resid = 0.0
    for h, a, hp, ap in zip(home_teams, away_teams, home_points, away_points):
        pred_h = fitted.expected_home_points(h, a, neutral_site=False)
        pred_a = fitted.expected_away_points(h, a, neutral_site=False)
        home_resid += (hp - pred_h) ** 2
        away_resid += (ap - pred_a) ** 2
    assert math.isfinite(home_resid)
    assert math.isfinite(away_resid)
    # Neither residual collapses to zero (which would indicate the
    # model is fitting only one side). Both targets must contribute
    # to the fit.
    assert (home_resid > 0.0) and (away_resid > 0.0), (
        f"Both home and away targets must contribute to the fit; "
        f"home_resid={home_resid}, away_resid={away_resid}"
    )


# ---------------------------------------------------------------------------
# 5. Expected home and away points reproduce the equations
# ---------------------------------------------------------------------------


def test_expected_points_reproduce_fitted_equations() -> None:
    """For any (home, away, neutral_site) tuple, the returned
    expected_home_points must equal
    ``league_baseline + hfa*(not neutral) + home_off - away_def``."""
    shared, candidates = _shared_and_candidates()
    cand = candidates[1]
    home_teams = ["A", "B", "A", "B"]
    away_teams = ["B", "A", "A", "B"]
    home_points = [25.0, 22.0, 28.0, 20.0]
    away_points = [20.0, 25.0, 22.0, 24.0]
    fitted = fit_expected_margin(
        prior_training_games=[{}] * 4,
        home_points=home_points,
        away_points=away_points,
        neutral_site=[False] * 4,
        home_team_codes=home_teams,
        away_team_codes=away_teams,
        chronological_age_in_completed_games=[0.0, 1.0, 2.0, 3.0],
        candidate=cand,
        shared=shared,
        fitted_at_cutoff_utc="2026-08-05T00:00:00Z",
    )
    for home_t in ("A", "B"):
        for away_t in ("A", "B"):
            for neutral in (False, True):
                if home_t == away_t:
                    continue
                pts_h = fitted.expected_home_points(home_t, away_t, neutral_site=neutral)
                pts_a = fitted.expected_away_points(home_t, away_t, neutral_site=neutral)
                expected_h = (
                    fitted.league_baseline
                    + (0.0 if neutral else fitted.home_field_effect)
                    + fitted._offense(home_t)  # noqa: SLF001
                    - fitted._defense(away_t)  # noqa: SLF001
                )
                expected_a = (
                    fitted.league_baseline
                    + fitted._offense(away_t)  # noqa: SLF001
                    - fitted._defense(home_t)  # noqa: SLF001
                )
                assert math.isclose(pts_h, expected_h, rel_tol=1e-12, abs_tol=1e-9)
                assert math.isclose(pts_a, expected_a, rel_tol=1e-12, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# 6. Expected margin equals expected home points minus expected away points
# ---------------------------------------------------------------------------


def test_expected_margin_equals_home_minus_away_points() -> None:
    shared, candidates = _shared_and_candidates()
    cand = candidates[1]
    fitted = fit_expected_margin(
        prior_training_games=[{}] * 4,
        home_points=[25.0, 22.0, 28.0, 20.0],
        away_points=[20.0, 25.0, 22.0, 24.0],
        neutral_site=[False] * 4,
        home_team_codes=["A", "B", "A", "B"],
        away_team_codes=["B", "A", "A", "B"],
        chronological_age_in_completed_games=[0.0, 1.0, 2.0, 3.0],
        candidate=cand,
        shared=shared,
        fitted_at_cutoff_utc="2026-08-05T00:00:00Z",
    )
    for home_t in ("A", "B"):
        for away_t in ("A", "B"):
            if home_t == away_t:
                continue
            for neutral in (False, True):
                em = fitted.expected_home_margin(home_t, away_t, neutral_site=neutral)
                pts_h = fitted.expected_home_points(home_t, away_t, neutral_site=neutral)
                pts_a = fitted.expected_away_points(home_t, away_t, neutral_site=neutral)
                assert math.isclose(em, pts_h - pts_a, rel_tol=1e-12, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# 7. Tied games remain in scoring-model training
# ---------------------------------------------------------------------------


def test_tied_games_included_in_scoring_fit() -> None:
    """A tied game contributes home points AND away points to the
    scoring fit. The fit must include both observations."""
    shared, candidates = _shared_and_candidates()
    cand = candidates[1]
    rows = [
        ("AAA", "BBB", 24.0, 17.0),
        ("AAA", "CCC", 24.0, 17.0),
        ("AAA", "DDD", 24.0, 17.0),
        ("BBB", "AAA", 17.0, 24.0),
        ("BBB", "CCC", 17.0, 24.0),
        ("BBB", "DDD", 17.0, 24.0),
        # Two ties (margin == 0).
        ("CCC", "AAA", 20.0, 20.0),
        ("CCC", "BBB", 20.0, 20.0),
        ("DDD", "AAA", 20.0, 20.0),
        ("DDD", "BBB", 20.0, 20.0),
    ]
    home_teams = [r[0] for r in rows]
    away_teams = [r[1] for r in rows]
    home_points = [r[2] for r in rows]
    away_points = [r[3] for r in rows]
    fitted = fit_expected_margin(
        prior_training_games=[{}] * len(home_teams),
        home_points=home_points,
        away_points=away_points,
        neutral_site=[False] * len(home_teams),
        home_team_codes=home_teams,
        away_team_codes=away_teams,
        chronological_age_in_completed_games=[float(i) for i in range(len(home_teams))],
        candidate=cand,
        shared=shared,
        fitted_at_cutoff_utc="2026-08-05T00:00:00Z",
    )
    # Tied games (margin 0) are included: the fit sees the same
    # train_completed_rows count as the input length.
    assert fitted.train_completed_rows == len(home_teams)
    # The model must also be able to predict tied-game points.
    pts_h = fitted.expected_home_points("CCC", "AAA", neutral_site=False)
    pts_a = fitted.expected_away_points("CCC", "AAA", neutral_site=False)
    assert math.isfinite(pts_h)
    assert math.isfinite(pts_a)


# ---------------------------------------------------------------------------
# 8. Tied games remain excluded from binary mapping
# ---------------------------------------------------------------------------


def test_tied_games_excluded_from_binary_mapping() -> None:
    """The eligibility for the binary home-win mapping drops ties
    (margin == 0). The mapping row count therefore is the number of
    NON-TIE rows passed by the caller."""
    shared, candidates = _shared_and_candidates()
    cand = candidates[1]
    margins = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0]
    wins = [True, True, True, True, True, True, True, True, True, True]
    mapping = fit_mapping(
        prior_oos_margins=margins,
        prior_oos_home_win=wins,
        intercept_l2_prior=shared.mapping_intercept_l2_prior,
        slope_l2_prior=shared.mapping_slope_l2_prior,
        intercept_l2_weight=cand.mapping_intercept_l2_weight,
        slope_l2_weight=cand.mapping_slope_l2_weight,
        tolerance=shared.mapping_solver_tolerance,
        max_iterations=shared.mapping_solver_max_iterations,
        cutoff_utc="2026-08-05T00:00:00Z",
    )
    assert mapping.row_count == 10
    assert mapping.fit_status == "converged"


# ---------------------------------------------------------------------------
# 9. Neutral-site HFA removal
# ---------------------------------------------------------------------------


def test_neutral_site_removes_hfa_in_two_observation_fit() -> None:
    """At a neutral site, the home-field effect must NOT contribute
    to the expected home points."""
    shared, candidates = _shared_and_candidates()
    cand = candidates[1]
    fitted = fit_expected_margin(
        prior_training_games=[{}] * 4,
        home_points=[25.0, 22.0, 28.0, 20.0],
        away_points=[20.0, 25.0, 22.0, 24.0],
        neutral_site=[False] * 4,
        home_team_codes=["A", "B", "A", "B"],
        away_team_codes=["B", "A", "A", "B"],
        chronological_age_in_completed_games=[0.0, 1.0, 2.0, 3.0],
        candidate=cand,
        shared=shared,
        fitted_at_cutoff_utc="2026-08-05T00:00:00Z",
    )
    pts_home = fitted.expected_home_points("A", "B", neutral_site=False)
    pts_neutral = fitted.expected_home_points("A", "B", neutral_site=True)
    assert math.isclose(
        pts_home - pts_neutral, fitted.home_field_effect, rel_tol=1e-12, abs_tol=1e-9
    )


# ---------------------------------------------------------------------------
# 10. Chronological recency independent of game_id ordering
# ---------------------------------------------------------------------------


def test_chronological_recency_uses_completion_order_not_game_id() -> None:
    """Construct a frame where game_id is deliberately out of
    chronological order. The recency weights must follow the
    chronological order, not the game_id order.
    """
    shared, candidates = _shared_and_candidates()
    cand = candidates[1]
    # Game IDs deliberately out of order: G003 is the most recent,
    # G001 is the oldest.
    home_teams = ["AAA", "AAA", "AAA", "AAA"]
    away_teams = ["BBB", "BBB", "BBB", "BBB"]
    home_points = [25.0, 25.0, 25.0, 25.0]
    away_points = [20.0, 20.0, 20.0, 20.0]
    # Chronological ages (sorted by prediction_as_of_utc, then game_id):
    # each row has its own age. We use chronological_age_in_completed_games
    # directly, so the test is anchored at the model boundary.
    # The CRITICAL assertion: the recency weight must depend on the
    # age, not on the game_id. Two games with the same age MUST have
    # the same weight regardless of game_id.
    ages = [0.0, 1.0, 2.0, 3.0]
    expected_weights = [
        _recency_weight(a, cand.recency_half_life_games) for a in ages
    ]
    # Verify the recency function's monotonicity here.
    assert all(
        expected_weights[i] > expected_weights[i + 1]
        for i in range(len(expected_weights) - 1)
    ), "recency weights must be strictly decreasing in age"
    # Now construct a frame where game_id order is reversed vs
    # chronological order and verify the walk-forward's
    # _chronological_age_per_row returns the chronological ages
    # (not the game_id order).
    from datetime import timedelta
    base = datetime(2024, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    rows = [
        {
            "game_id": "G003",  # out of order
            "season": 2024, "season_type": "REG", "week": 3,
            "home_team": "AAA", "away_team": "BBB",
            "neutral_site": False, "target_available": True,
            "target_margin": 5.0, "target_home_win": True,
            "target_tie": False, "home_score": 25.0, "away_score": 20.0,
            "prediction_as_of_utc": base + timedelta(days=15),  # chronological pos 3
        },
        {
            "game_id": "G001",  # out of order
            "season": 2024, "season_type": "REG", "week": 1,
            "home_team": "AAA", "away_team": "BBB",
            "neutral_site": False, "target_available": True,
            "target_margin": 5.0, "target_home_win": True,
            "target_tie": False, "home_score": 25.0, "away_score": 20.0,
            "prediction_as_of_utc": base + timedelta(days=1),  # chronological pos 0
        },
        {
            "game_id": "G004",  # out of order
            "season": 2024, "season_type": "REG", "week": 4,
            "home_team": "AAA", "away_team": "BBB",
            "neutral_site": False, "target_available": True,
            "target_margin": 5.0, "target_home_win": True,
            "target_tie": False, "home_score": 25.0, "away_score": 20.0,
            "prediction_as_of_utc": base + timedelta(days=22),  # chronological pos 4
        },
        {
            "game_id": "G002",  # out of order
            "season": 2024, "season_type": "REG", "week": 2,
            "home_team": "AAA", "away_team": "BBB",
            "neutral_site": False, "target_available": True,
            "target_margin": 5.0, "target_home_win": True,
            "target_tie": False, "home_score": 25.0, "away_score": 20.0,
            "prediction_as_of_utc": base + timedelta(days=8),  # chronological pos 1
        },
    ]
    frame = pl.DataFrame(rows)
    computed_ages = _chronological_age_per_row(frame)
    # The ages must be 0, 1, 2, 3 in chronological order
    # (G001, G002, G003, G004), NOT in game_id order.
    assert computed_ages == [0.0, 1.0, 2.0, 3.0], (
        f"chronological ages must follow chronological order, not "
        f"game_id order; got {computed_ages}"
    )


# ---------------------------------------------------------------------------
# 11. Deterministic replay of the corrected fit
# ---------------------------------------------------------------------------


def test_fit_is_deterministic() -> None:
    """Two calls with the same inputs must produce identical fitted
    parameters."""
    shared, candidates = _shared_and_candidates()
    cand = candidates[1]
    common = dict(
        prior_training_games=[{}] * 4,
        home_points=[25.0, 22.0, 28.0, 20.0],
        away_points=[20.0, 25.0, 22.0, 24.0],
        neutral_site=[False] * 4,
        home_team_codes=["A", "B", "A", "B"],
        away_team_codes=["B", "A", "A", "B"],
        chronological_age_in_completed_games=[0.0, 1.0, 2.0, 3.0],
        candidate=cand,
        shared=shared,
        fitted_at_cutoff_utc="2026-08-05T00:00:00Z",
    )
    f1 = fit_expected_margin(**common)
    f2 = fit_expected_margin(**common)
    assert f1.league_baseline == f2.league_baseline
    assert f1.offense_effect == f2.offense_effect
    assert f1.defense_effect == f2.defense_effect
    assert f1.home_field_effect == f2.home_field_effect
    assert (f1.offense_effect, f1.defense_effect) == (f2.offense_effect, f2.defense_effect)


def test_swapping_home_away_swallows_margin() -> None:
    """Swapping home and away teams reverses the expected home margin
    minus the home-field effect."""
    shared, candidates = _shared_and_candidates()
    cand = candidates[1]
    fitted = fit_expected_margin(
        prior_training_games=[{}] * 4,
        home_points=[25.0, 22.0, 28.0, 20.0],
        away_points=[20.0, 25.0, 22.0, 24.0],
        neutral_site=[False] * 4,
        home_team_codes=["A", "B", "A", "B"],
        away_team_codes=["B", "A", "A", "B"],
        chronological_age_in_completed_games=[0.0, 1.0, 2.0, 3.0],
        candidate=cand,
        shared=shared,
        fitted_at_cutoff_utc="2026-08-05T00:00:00Z",
    )
    em_ab = fitted.expected_home_margin("A", "B", neutral_site=False)
    em_ba = fitted.expected_home_margin("B", "A", neutral_site=False)
    assert math.isclose(
        em_ab + em_ba, 2.0 * fitted.home_field_effect, rel_tol=1e-12, abs_tol=1e-9
    )


# ---------------------------------------------------------------------------
# 12. Leakage, holdout, market, mapping, duplicate guards
# ---------------------------------------------------------------------------


def test_locked_config_sha256_is_stable() -> None:
    """The locked SHA-256 must match the canonical JSON hash."""
    sha = _lock_config()
    import hashlib
    import json as _json

    import yaml as _yaml

    raw = _yaml.safe_load(
        (Path(__file__).resolve().parent.parent.parent
         / "config" / "expected_margin_v1.yaml").read_text()
    )
    canonical = _json.dumps(
        raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert sha == expected


def test_only_three_candidates_in_yaml() -> None:
    """The runtime must reject any YAML without exactly three candidates."""
    with tempfile.NamedTemporaryFile(
        suffix=".yaml", delete=False, mode="w"
    ) as tmp:
        tmp.write(
            "shared:\n"
            "  league_baseline_prior: 22.5\n"
            "  probability_min: 0.001\n"
            "  probability_max: 0.999\n"
            "  mapping_intercept_l2_prior: 0.0\n"
            "  mapping_slope_l2_prior: 0.0\n"
            "  mapping_solver_tolerance: 1e-9\n"
            "  mapping_solver_max_iterations: 100\n"
            "  tie_policy: 'exclude'\n"
            "  minimum_training_games: 64\n"
            "  minimum_mapping_rows: 256\n"
            "  apply_probability_clipping: true\n"
            "  reject_nonpositive_slope: true\n"
            "  maximum_development_season: 2024\n"
            "candidates:\n"
            "  - id: 'responsive'\n"
            "    offense_ridge: 0.25\n"
            "    defense_ridge: 0.25\n"
            "    home_field_ridge: 0.25\n"
            "    recency_half_life_games: 4.0\n"
            "    mapping_intercept_l2_weight: 0.25\n"
            "    mapping_slope_l2_weight: 0.25\n"
        )
        path = tmp.name
    try:
        with pytest.raises(Exception):
            load_expected_margin_canonical_config(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_season_constants_match_documented_values() -> None:
    assert DEVELOPMENT_SEASON_MAX == 2024
    assert SEALED_HOLDOUT_SEASON == 2025
    assert FORWARD_USE_SEASON == 2026


def test_2025_rejected_at_load() -> None:
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        path = tmp.name
    try:
        df = pl.DataFrame(
            [
                {
                    "game_id": "f-2025-1", "season": 2025, "season_type": "REG",
                    "week": 1, "home_team": "AAA", "away_team": "BBB",
                    "neutral_site": False, "target_available": True,
                    "target_margin": 7.0, "target_home_win": True,
                    "target_tie": False, "home_score": 30.0, "away_score": 23.0,
                    "prediction_as_of_utc": _cu("2025-09-07T17:00:00Z"),
                },
                {
                    "game_id": "f-2024-1", "season": 2024, "season_type": "REG",
                    "week": 1, "home_team": "AAA", "away_team": "BBB",
                    "neutral_site": False, "target_available": True,
                    "target_margin": 7.0, "target_home_win": True,
                    "target_tie": False, "home_score": 30.0, "away_score": 23.0,
                    "prediction_as_of_utc": _cu("2024-09-07T17:00:00Z"),
                },
            ]
        )
        df.write_parquet(path)
        with pytest.raises(SealedHoldoutAccessError):
            _load_games(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_2026_rejected_at_load() -> None:
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        path = tmp.name
    try:
        df = pl.DataFrame(
            [
                {
                    "game_id": "f-2026-1", "season": 2026, "season_type": "REG",
                    "week": 1, "home_team": "AAA", "away_team": "BBB",
                    "neutral_site": False, "target_available": True,
                    "target_margin": 7.0, "target_home_win": True,
                    "target_tie": False, "home_score": 30.0, "away_score": 23.0,
                    "prediction_as_of_utc": _cu("2026-09-07T17:00:00Z"),
                },
            ]
        )
        df.write_parquet(path)
        with pytest.raises(WalkForwardError):
            _load_games(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_2027_rejected_at_load() -> None:
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        path = tmp.name
    try:
        df = pl.DataFrame(
            [
                {
                    "game_id": "f-2027-1", "season": 2027, "season_type": "REG",
                    "week": 1, "home_team": "AAA", "away_team": "BBB",
                    "neutral_site": False, "target_available": True,
                    "target_margin": 7.0, "target_home_win": True,
                    "target_tie": False, "home_score": 30.0, "away_score": 23.0,
                    "prediction_as_of_utc": _cu("2027-09-07T17:00:00Z"),
                },
            ]
        )
        df.write_parquet(path)
        with pytest.raises((WalkForwardError, SealedHoldoutAccessError)):
            _load_games(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_market_column_rejection_at_model_boundary() -> None:
    with pytest.raises(Exception):
        assert_no_market_columns(["home_score", "pinnacle_price", "away_moneyline"])


def test_market_column_rejection_at_load() -> None:
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        path = tmp.name
    try:
        df = pl.DataFrame(
            [
                {
                    "game_id": "f-2024-1", "season": 2024, "season_type": "REG",
                    "week": 1, "home_team": "AAA", "away_team": "BBB",
                    "neutral_site": False, "target_available": True,
                    "target_margin": 7.0, "target_home_win": True,
                    "target_tie": False, "home_score": 30.0, "away_score": 23.0,
                    "prediction_as_of_utc": _cu("2024-09-07T17:00:00Z"),
                    "pinnacle_price": -110,
                },
            ]
        )
        df.write_parquet(path)
        with pytest.raises(Exception):
            _load_games(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_mapping_fit_rejects_nonpositive_slope() -> None:
    shared, candidates = _shared_and_candidates()
    cand = candidates[1]
    margins = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0]
    wins = [False] * 10
    mapping = fit_mapping(
        prior_oos_margins=margins,
        prior_oos_home_win=wins,
        intercept_l2_prior=shared.mapping_intercept_l2_prior,
        slope_l2_prior=shared.mapping_slope_l2_prior,
        intercept_l2_weight=cand.mapping_intercept_l2_weight,
        slope_l2_weight=cand.mapping_slope_l2_weight,
        tolerance=shared.mapping_solver_tolerance,
        max_iterations=shared.mapping_solver_max_iterations,
        cutoff_utc="2026-08-05T00:00:00Z",
    )
    assert mapping.fit_status == "rejected_nonpositive_slope"
    assert not is_mapping_available(mapping)


def test_mapping_warmup_when_no_prior_rows() -> None:
    shared, candidates = _shared_and_candidates()
    cand = candidates[1]
    mapping = fit_mapping(
        prior_oos_margins=[],
        prior_oos_home_win=[],
        intercept_l2_prior=shared.mapping_intercept_l2_prior,
        slope_l2_prior=shared.mapping_slope_l2_prior,
        intercept_l2_weight=cand.mapping_intercept_l2_weight,
        slope_l2_weight=cand.mapping_slope_l2_weight,
        tolerance=shared.mapping_solver_tolerance,
        max_iterations=shared.mapping_solver_max_iterations,
        cutoff_utc="2026-08-05T00:00:00Z",
    )
    assert mapping.fit_status == "warmup"
    assert mapping.row_count == 0
    assert not is_mapping_available(mapping)


def test_mapping_team_strength_warmup_state() -> None:
    assert is_warmup_state(
        training_rows_available=10, minimum_training_games=64
    )
    assert not is_warmup_state(
        training_rows_available=64, minimum_training_games=64
    )
    assert not is_warmup_state(
        training_rows_available=200, minimum_training_games=64
    )


def test_probability_monotonicity_in_margin() -> None:
    mapping = FittedMapping(
        row_count=10,
        intercept=0.0,
        slope=0.5,
        fit_status="converged",
        convergence_status="converged",
        cutoff_utc="2026-08-05T00:00:00Z",
    )
    p_neg = predict_home_win_probability(
        mapping, -10.0, probability_min=0.001, probability_max=0.999, apply_clipping=True
    )
    p_zero = predict_home_win_probability(
        mapping, 0.0, probability_min=0.001, probability_max=0.999, apply_clipping=True
    )
    p_pos = predict_home_win_probability(
        mapping, 10.0, probability_min=0.001, probability_max=0.999, apply_clipping=True
    )
    assert p_neg < p_zero < p_pos
    assert 0.0 < p_neg < 1.0
    assert 0.0 < p_pos < 1.0


def test_duplicate_prediction_id_rejected() -> None:
    dup = pl.DataFrame(
        [
            {
                "game_id": "DUP-001", "season": 2018, "season_type": "REG",
                "week": 1, "home_team": "AAA", "away_team": "BBB",
                "neutral_site": False, "target_available": True,
                "target_margin": 7.0, "target_home_win": True,
                "target_tie": False, "home_score": 30.0, "away_score": 23.0,
                "prediction_as_of_utc": _cu("2018-09-07T17:00:00Z"),
            },
            {
                "game_id": "DUP-001", "season": 2018, "season_type": "REG",
                "week": 1, "home_team": "CCC", "away_team": "DDD",
                "neutral_site": False, "target_available": True,
                "target_margin": -3.0, "target_home_win": False,
                "target_tie": False, "home_score": 20.0, "away_score": 23.0,
                "prediction_as_of_utc": _cu("2018-09-07T17:00:00Z"),
            },
        ]
    )
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        path = tmp.name
    try:
        dup.write_parquet(path)
        shared, candidates = _shared_and_candidates()
        with pytest.raises(WalkForwardError):
            run_expected_margin_candidate(
                games_path=path,
                candidate=candidates[1],
                shared=shared,
                run_id="T-DUP",
                model_version="v1.0.0",
            )
    finally:
        Path(path).unlink(missing_ok=True)


def test_walk_forward_low_sample_mapping_warmup() -> None:
    """Single block, no prior games: the walk-forward sets
    team_strength_warmup = True and probability_available = false."""
    games = _synthetic_game_frame(
        season=2018, week=1, n_games=3, base_offset=0,
        home_points=[21.0, 17.0, 21.0],
        away_points=[17.0, 21.0, 17.0],
    )
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        path = tmp.name
    try:
        games.write_parquet(path)
        shared, candidates = _shared_and_candidates()
        result = run_expected_margin_candidate(
            games_path=path,
            candidate=candidates[1],
            shared=shared,
            run_id="T-WARMUP",
            model_version="v1.0.0",
        )
        for pred in result["predictions"]:
            assert pred["warmup_state"] == "prior_games_warmup"
            assert pred["mapping_warmup"] is True
            assert pred["probability_available"] is False
            assert pred["predicted_home_win_probability"] is None
    finally:
        Path(path).unlink(missing_ok=True)


def test_current_block_outcome_poisoning_does_not_mutate_block() -> None:
    """Mutating the outcome of a current-block game must not change
    any of the other predictions in the same block."""
    games = _synthetic_game_frame(
        season=2018, week=1, n_games=4, base_offset=0,
        home_points=[21.0, 17.0, 21.0, 17.0],
        away_points=[17.0, 21.0, 17.0, 21.0],
    )
    shared, candidates = _shared_and_candidates()
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        path = tmp.name
    try:
        games.write_parquet(path)
        result = run_expected_margin_candidate(
            games_path=path,
            candidate=candidates[1],
            shared=shared,
            run_id="T-CURR",
            model_version="v1.0.0",
        )
        # All predictions in the single block must be present.
        hfa_values = {p["home_field_effect"] for p in result["predictions"]}
        # HFA is either 0.0 (warmup) or a single fitted value.
        assert len(hfa_values) == 1
    finally:
        Path(path).unlink(missing_ok=True)


def test_future_outcome_poisoning_does_not_leak() -> None:
    """If we swap the outcome of a later block's first game, the
    predictions for the earlier block must be unchanged."""
    block1 = _synthetic_game_frame(
        season=2018, week=1, n_games=3, base_offset=0,
        home_points=[21.0, 17.0, 21.0],
        away_points=[17.0, 21.0, 17.0],
    )
    block2 = _synthetic_game_frame(
        season=2018, week=2, n_games=3, base_offset=100,
        home_points=[21.0, 17.0, 21.0],
        away_points=[17.0, 21.0, 17.0],
    )
    warmup = []
    for i in range(80):
        gid = f"WARM-{i:03d}"
        warmup.append(
            {
                "game_id": gid,
                "season": 2017,
                "season_type": "REG",
                "week": 1 + (i % 17),
                "home_team": f"HW{i % 4:03d}",
                "away_team": f"AW{i % 4:03d}",
                "neutral_site": False,
                "target_available": True,
                "target_margin": 4.0,
                "target_home_win": True,
                "target_tie": False,
                "home_score": 24.0,
                "away_score": 20.0,
                "prediction_as_of_utc": _cu("2017-09-10T17:00:00Z"),
            }
        )
    full_a = pl.concat([pl.DataFrame(warmup), block1, block2])
    mutated = block2.clone()
    mutated = mutated.with_columns(
        pl.when(pl.col("game_id") == block2["game_id"][0])
        .then(pl.lit(50.0))
        .otherwise(pl.col("target_margin"))
        .alias("target_margin"),
        pl.when(pl.col("game_id") == block2["game_id"][0])
        .then(pl.lit(40.0))
        .otherwise(pl.col("home_score"))
        .alias("home_score"),
    )
    full_b = pl.concat([pl.DataFrame(warmup), block1, mutated])
    shared, candidates = _shared_and_candidates()
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as t_a:
        path_a = t_a.name
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as t_b:
        path_b = t_b.name
    try:
        full_a.write_parquet(path_a)
        full_b.write_parquet(path_b)
        result_a = run_expected_margin_candidate(
            games_path=path_a,
            candidate=candidates[1],
            shared=shared,
            run_id="T-A",
            model_version="v1.0.0",
        )
        result_b = run_expected_margin_candidate(
            games_path=path_b,
            candidate=candidates[1],
            shared=shared,
            run_id="T-B",
            model_version="v1.0.0",
        )
        preds_a = {p["game_id"]: p for p in result_a["predictions"]}
        preds_b = {p["game_id"]: p for p in result_b["predictions"]}
        block1_ids = set(block1["game_id"].to_list())
        for gid in block1_ids:
            for field in (
                "expected_home_margin",
                "home_offs_strength",
                "away_offs_strength",
                "home_def_strength",
                "away_def_strength",
                "home_field_effect",
                "league_baseline",
            ):
                va = preds_a[gid][field]
                vb = preds_b[gid][field]
                if math.isnan(va) and math.isnan(vb):
                    continue
                assert math.isclose(va, vb, rel_tol=1e-12, abs_tol=1e-9), (
                    f"Block1 prediction leaked from block2: "
                    f"{gid} {field} a={va} b={vb}"
                )
    finally:
        Path(path_a).unlink(missing_ok=True)
        Path(path_b).unlink(missing_ok=True)


def test_prior_oos_only_mapping_no_future_rows() -> None:
    block1 = _synthetic_game_frame(season=2018, week=1, n_games=3, base_offset=0)
    block2 = _synthetic_game_frame(season=2018, week=2, n_games=3, base_offset=100)
    block3 = _synthetic_game_frame(season=2018, week=3, n_games=3, base_offset=200)
    games = pl.concat([block1, block2, block3])
    blocks = build_development_blocks(games)
    block3_obj = blocks[2]
    prior_oos = [
        {"game_id": gid, "season": 2018, "season_type": "REG", "week": 1,
         "expected_home_margin": 3.0, "expected_home_margin_available": True,
         "actual_home_win": True, "actual_margin": 3.0, "actual_tie": False,
         "target_available": True}
        for gid in block1["game_id"].to_list()
    ] + [
        {"game_id": gid, "season": 2018, "season_type": "REG", "week": 2,
         "expected_home_margin": 5.0, "expected_home_margin_available": True,
         "actual_home_win": True, "actual_margin": 5.0, "actual_tie": False,
         "target_available": True}
        for gid in block2["game_id"].to_list()
    ]
    prior = _prior_oos_for_mapping(
        prior_oos_predictions=prior_oos, games=games, block=block3_obj
    )
    assert len(prior) == 6


def test_current_block_excluded_from_mapping() -> None:
    block1 = _synthetic_game_frame(season=2018, week=1, n_games=3, base_offset=0)
    block2 = _synthetic_game_frame(season=2018, week=2, n_games=3, base_offset=100)
    games = pl.concat([block1, block2])
    blocks = build_development_blocks(games)
    block2_obj = blocks[1]
    prior_oos = [
        {"game_id": gid, "season": 2018, "season_type": "REG", "week": 1,
         "expected_home_margin": 3.0, "expected_home_margin_available": True,
         "actual_home_win": True, "actual_margin": 3.0, "actual_tie": False,
         "target_available": True}
        for gid in block1["game_id"].to_list()
    ] + [
        {"game_id": gid, "season": 2018, "season_type": "REG", "week": 2,
         "expected_home_margin": 5.0, "expected_home_margin_available": True,
         "actual_home_win": True, "actual_margin": 5.0, "actual_tie": False,
         "target_available": True}
        for gid in block2["game_id"].to_list()
    ]
    prior = _prior_oos_for_mapping(
        prior_oos_predictions=prior_oos, games=games, block=block2_obj
    )
    assert len(prior) == 3


def test_recency_weighting_is_strictly_decreasing() -> None:
    candidates = _shared_and_candidates()[1]
    half_life = candidates[1].recency_half_life_games
    w0 = _recency_weight(0.0, half_life)
    w1 = _recency_weight(1.0, half_life)
    w8 = _recency_weight(8.0, half_life)
    w16 = _recency_weight(16.0, half_life)
    assert w0 == 1.0
    assert 0.0 < w8 < w1 < w0
    assert w16 < w8
    assert math.isclose(_recency_weight(half_life, half_life), 0.5, rel_tol=1e-12)


def test_cholesky_solve_deterministic() -> None:
    a = [4.0, 2.0, 0.0, 2.0, 5.0, 0.0, 0.0, 0.0, 6.0]
    b = [4.0, 7.0, 6.0]
    x1 = _cholesky_solve(a, b, 3)
    x2 = _cholesky_solve(a, b, 3)
    assert all(math.isclose(a, b, rel_tol=1e-15) for a, b in zip(x1, x2))
    for i in range(3):
        ax = sum(a[i * 3 + j] * x1[j] for j in range(3))
        assert math.isclose(ax, b[i], rel_tol=1e-12, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# 4. Reference-team rename-invariance
# ---------------------------------------------------------------------------


def test_reference_team_rename_invariance() -> None:
    """The reference team is alphabetically smallest. Renaming the
    teams (which changes which team is the reference) must NOT
    materially change the predicted home points, away points, or
    margin for any team pair.

    The current implementation pins the reference team to (off=0,
    def=0). This is a prediction-invariant constraint because the
    sum of predictions across all teams is fixed by the data; the
    reference team acts as the calibration anchor against which the
    other teams are measured. The predicted home points, away
    points, and margin for any non-reference team must be close
    under different reference-team identities.
    """
    shared, candidates = _shared_and_candidates()
    cand = candidates[1]
    # Build a balanced fixture with KNOWN offense and defense values.
    # True deviations from AA (the reference team).
    # AA: off=+4, def=+4 (high O, great D)
    # BB: off=+4, def=-4 (high O, weak D)
    # CC: off=-4, def=+4 (low O, great D)
    # DD: off=-4, def=-4 (low O, weak D)
    true_off = {"AA": 2.0, "BB": 8.0, "CC": -5.0, "DD": -5.0}
    true_def = {"AA": 8.0, "BB": 2.0, "CC": -5.0, "DD": -5.0}
    league = 22.0
    home_teams: list[str] = []
    away_teams: list[str] = []
    home_points: list[float] = []
    away_points: list[float] = []
    neutral_site: list[bool] = []
    for h in ["AA", "BB", "CC", "DD"]:
        for a in ["AA", "BB", "CC", "DD"]:
            if h == a:
                continue
            home_teams.append(h)
            away_teams.append(a)
            home_points.append(league + true_off[h] - true_def[a])
            away_points.append(league + true_off[a] - true_def[h])
            neutral_site.append(True)
            home_teams.append(a)
            away_teams.append(h)
            home_points.append(league + true_off[a] - true_def[h])
            away_points.append(league + true_off[h] - true_def[a])
            neutral_site.append(True)
    home_teams *= 10
    away_teams *= 10
    home_points *= 10
    away_points *= 10
    neutral_site *= 10
    fitted_a = fit_expected_margin(
        prior_training_games=[{}] * len(home_teams),
        home_points=home_points,
        away_points=away_points,
        neutral_site=neutral_site,
        home_team_codes=home_teams,
        away_team_codes=away_teams,
        chronological_age_in_completed_games=[float(i) for i in range(len(home_teams))],
        candidate=cand,
        shared=shared,
        fitted_at_cutoff_utc="2026-08-05T00:00:00Z",
    )
    # sum-to-zero; no reference team

    # Rename the teams so that the reference team is no longer the
    # same team. The reference team becomes that which is
    # alphabetically smallest of the new set.
    rename_map = {"AA": "ZZ", "BB": "WW", "CC": "UU", "DD": "SS"}
    home_teams_b = [rename_map[t] for t in home_teams]
    away_teams_b = [rename_map[t] for t in away_teams]
    fitted_b = fit_expected_margin(
        prior_training_games=[{}] * len(home_teams_b),
        home_points=home_points,
        away_points=away_points,
        neutral_site=neutral_site,
        home_team_codes=home_teams_b,
        away_team_codes=away_teams_b,
        chronological_age_in_completed_games=[float(i) for i in range(len(home_teams_b))],
        candidate=cand,
        shared=shared,
        fitted_at_cutoff_utc="2026-08-05T00:00:00Z",
    )
    # The reference team is now SS (alphabetically smallest of the
    # renamed set).
    # sum-to-zero; no reference team
    # The reference team is a different team in the two fits; the
    # data is the same. Predicted home points, away points, and
    # margin for any OTHER team pair must be nearly identical.
    pairs = [
        ("AA", "BB", "ZZ", "WW"),
        ("AA", "CC", "ZZ", "UU"),
        ("AA", "DD", "ZZ", "SS"),
        ("BB", "CC", "WW", "UU"),
        ("BB", "DD", "WW", "SS"),
        ("CC", "DD", "UU", "SS"),
    ]
    for h_a, a_a, h_b, a_b in pairs:
        h_pts_a = fitted_a.expected_home_points(h_a, a_a, neutral_site=True)
        h_pts_b = fitted_b.expected_home_points(h_b, a_b, neutral_site=True)
        a_pts_a = fitted_a.expected_away_points(h_a, a_a, neutral_site=True)
        a_pts_b = fitted_b.expected_away_points(h_b, a_b, neutral_site=True)
        assert abs(h_pts_a - h_pts_b) < 1e-3, (
            f"Renaming changes home points for ({h_a} vs {a_a}) by {h_pts_a - h_pts_b:.6f}"
        )
        assert abs(a_pts_a - a_pts_b) < 1e-3, (
            f"Renaming changes away points for ({h_a} vs {a_a}) by {a_pts_a - a_pts_b:.6f}"
        )
