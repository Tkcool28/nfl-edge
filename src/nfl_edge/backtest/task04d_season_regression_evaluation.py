"""Bounded Team-Elo season-regression evaluation harness (Task 04D).

Task 04D tests whether regressing team Elo toward the canonical center at
each NFL-season transition changes Week 1-4 probability quality while
preserving acceptable full-season performance. It builds directly on the
validated Task 04C oracle-QB configuration.

Key facts inherited from the Chunk 1 audit:

- The existing engine ALREADY regresses every known team toward the
  canonical center at the first block of each new NFL season, via
  ``nfl_edge.models.qb_elo.apply_season_carryover``.
- The canonical center (league-average Elo) is ``initial_rating = 1500.0``.
- The amount of regression is ``EloConfig.season_mean_reversion_fraction``,
  frozen at ``0.333`` (33.3%) in ``config/qb_elo_v1.yaml``.
- The engine formula ``rating + fr * (target - rating)`` is exactly
  equivalent to ``new_R = M + (1 - f) * (R - M)``, so the fraction ``f``
  *is* ``season_mean_reversion_fraction``.

This harness therefore REUSES the canonical ``apply_season_carryover`` math
(no second implementation) and driver parameter by overriding only
``season_mean_reversion_fraction`` in a candidate-specific EloConfig. The
single candidate-dependent model parameter is that fraction; everything else
is byte/logically identical across candidates.

Candidate/reference grid (labels are fixed and used everywhere):

- ``regression_000``            -> 0.00 (task-specified 0% CONTROL)
- ``regression_025``            -> 0.25
- ``regression_040``            -> 0.40
- ``regression_060``            -> 0.60
- ``task04c_reference_0333``    -> 0.333 (TASK04C_REFERENCE / incumbent)

The 0% control answers "what does the oracle-QB Elo model do with no
offseason team-strength regression?" --- it is NOT the historical Task04C
model. The 33.3% reference is the already-validated Task04C incumbent and is
used to prove the harness reproduces Task04C exactly (identity gate).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping

import polars as pl

from ..common.errors import WalkForwardError

# ---------------------------------------------------------------------------
# Canonical constants
# ---------------------------------------------------------------------------

#: Canonical league-average / Elo center. Matches ``EloConfig.initial_rating``
#: (config/qb_elo_v1.yaml:: initial_rating) which is also the team
#: initialization value and the ``apply_season_carryover`` regression target.
REGRESSION_CENTER: float = 1500.0

#: Frozen Task04C incumbent season-regression fraction.
TASK04C_REFERENCE_FRACTION: float = 0.333

#: Ordered candidate grid: control first, then required candidates, then the
#: Task04C reference. Order is stable across runs/reports.
CANDIDATE_LABELS: tuple[str, ...] = (
    "regression_000",
    "regression_025",
    "regression_040",
    "regression_060",
    "task04c_reference_0333",
)

#: label -> season_mean_reversion_fraction
CANDIDATE_FRACTIONS: dict[str, float] = {
    "regression_000": 0.00,
    "regression_025": 0.25,
    "regression_040": 0.40,
    "regression_060": 0.60,
    "task04c_reference_0333": TASK04C_REFERENCE_FRACTION,
}

#: Season type priority, mirroring blocks.py ST_PRIORITY for ordering.
_ST_PRIORITY: dict[str, int] = {"REG": 0, "WC": 1, "DIV": 2, "CON": 3, "SB": 4}

#: Audit ledger column schema.
AUDIT_LEDGER_COLUMNS: tuple[str, ...] = (
    "candidate_label",
    "regression_fraction",
    "team",
    "previous_season",
    "new_season",
    "prior_season_ending_elo",
    "canonical_mean",
    "expected_new_elo",
    "actual_new_elo",
    "difference",
    "transition_block_id",
    "first_prediction_block_id",
    "first_prediction_game_id",
    "prior_team_state_exists",
    "status",
)


# ---------------------------------------------------------------------------
# Formula helpers (thin, reuse the canonical engine math)
# ---------------------------------------------------------------------------


def regression_expected(
    prior_ending_elo: float,
    fraction: float,
    center: float = REGRESSION_CENTER,
) -> float:
    """Expected post-regression Elo.

    Mirrors ``apply_season_carryover`` exactly:

    ``new_R = center + (1 - fraction) * (prior_ending_elo - center)``

    This is the single, canonical season-regression formula. Callers must not
    implement a second variant; the audit ledger and tests both use this, and
    a dedicated test proves ``apply_season_carryover`` equals this helper.
    """
    return center + (1.0 - float(fraction)) * (float(prior_ending_elo) - center)


def build_candidate_config(
    base_config: Mapping[str, Any],
    fraction: float,
) -> dict[str, Any]:
    """Return a canonical config dict changing ONLY the regression fraction.

    ``base_config`` is the canonical normalized config (as returned by
    ``load_qb_elo_canonical_config``). The returned dict is identical except
    ``season_mean_reversion_fraction`` is replaced with ``fraction``. This is
    the only candidate-dependent model parameter.
    """
    cfg = dict(base_config)
    cfg["season_mean_reversion_fraction"] = float(fraction)
    return cfg


def load_canonical_config(project_root: str | Path) -> dict[str, Any]:
    """Load the frozen primary QB-Elo canonical config from the YAML."""
    from ..models.qb_elo_config import load_qb_elo_canonical_config

    return load_qb_elo_canonical_config(Path(project_root) / "config/qb_elo_v1.yaml")


# ---------------------------------------------------------------------------
# Season-boundary audit ledger
# ---------------------------------------------------------------------------

_AUDIT_TOL = 1e-6


def _block_order_key(row: Mapping[str, Any]) -> tuple[int, int, int, str]:
    """Chronological block ordering key for a prediction row."""
    st_prio = _ST_PRIORITY.get(str(row["season_type"]).upper(), 99)
    return (
        int(row["season"]),
        st_prio,
        int(row["week"]),
        str(row["game_id"]),
    )


def build_season_boundary_audit(
    predictions: pl.DataFrame,
    state: pl.DataFrame,
    fraction: float,
    *,
    candidate_label: str = "",
    center: float = REGRESSION_CENTER,
) -> pl.DataFrame:
    """Build a deterministic per-(team, season-transition) audit ledger.

    derived purely from the two persisted ledgers of a single walk-forward
    run (prediction + state). It never mutates prediction state.

    For every NFL-season transition ``S-1 -> S`` (S in 2019..2024):

    - ``prior_season_ending_elo`` = that team's last state-update ``elo_after``
      in season S-1 (its true prior-season ending rating).
    - ``expected_new_elo`` = ``regression_expected(prior_ending, fraction)``.
    - ``actual_new_elo`` = the team's ``elo_before`` at its FIRST prediction
      of season S (post-regression value observed by the engine).
    - ``difference`` = actual - expected; status PASS iff |diff| <= tol.
    - ``transition_block_id`` = first block of season S (carryover applied
      before it). ``first_prediction_*`` = where the team's new-season state
      first becomes prediction-active.

    Teams with no prior-season state (new identifiers) get a
    ``NO_PRIOR_STATE`` row (no regression; they initialize at the center).
    """
    if predictions.height == 0:
        raise WalkForwardError(
            "task04d.build_season_boundary_audit", "empty predictions frame"
        )
    seasons = sorted(int(s) for s in set(predictions["season"].to_list()))
    if len(seasons) < 1:
        return pl.DataFrame(
            [], schema=AUDIT_LEDGER_COLUMNS
        )

    pred_rows = predictions.to_dicts()
    state_rows = state.to_dicts()

    # Chronologically first prediction block per season (carryover applied
    # before that block) and first prediction occurrence per (season, team).
    first_block_state: dict[int, dict[str, Any]] = {}
    first_pred_by_team: dict[tuple[int, str], dict[str, Any]] = {}
    for r in pred_rows:
        s = int(r["season"])
        cur = first_block_state.get(s)
        if cur is None or _block_order_key(r) < _block_order_key(cur):
            first_block_state[s] = r
        for team_slot in ("home_team", "away_team"):
            team = str(r[team_slot])
            tkey = (s, team)
            curp = first_pred_by_team.get(tkey)
            if curp is None or _block_order_key(r) < _block_order_key(curp):
                first_pred_by_team[tkey] = r
    first_block_by_season: dict[int, str] = {
        s: str(r["prediction_block_id"]) for s, r in first_block_state.items()
    }

    # Prior-season ending Elo per team: the last (max state_update_order)
    # state-update elo_after in each season.
    ending_candidates: dict[tuple[int, str], list[tuple[int, float]]] = {}
    for r in state_rows:
        ending_candidates.setdefault(
            (int(r["season"]), str(r["team"])), []
        ).append((int(r["state_update_order"]), float(r["elo_after"])))
    ending_elo: dict[tuple[int, str], float] = {
        k: max(v, key=lambda x: x[0])[1] for k, v in ending_candidates.items()
    }

    records: list[dict[str, Any]] = []
    transitions = list(zip(seasons[:-1], seasons[1:]))
    for prev_s, new_s in transitions:
        # All teams that appear in the new season.
        new_season_teams: set[str] = set()
        for r in pred_rows:
            if int(r["season"]) == new_s:
                new_season_teams.add(str(r["home_team"]))
                new_season_teams.add(str(r["away_team"]))
        for team in sorted(new_season_teams):
            prior_exists = (prev_s, team) in ending_elo
            curr = first_pred_by_team.get((new_s, team))
            if curr is None:
                continue
            actual = (
                float(curr["home_elo_before"])
                if str(curr["home_team"]) == team
                else float(curr["away_elo_before"])
            )
            if prior_exists:
                prior = ending_elo[(prev_s, team)]
                expected = regression_expected(prior, fraction, center)
                diff = actual - expected
                status = "PASS" if abs(diff) <= _AUDIT_TOL else "FAIL"
                prior_val = prior
                expected_val = expected
            else:
                prior_val = None
                expected_val = None
                diff = None
                status = "NO_PRIOR_STATE"
            records.append(
                {
                    "candidate_label": candidate_label,
                    "regression_fraction": float(fraction),
                    "team": team,
                    "previous_season": prev_s,
                    "new_season": new_s,
                    "prior_season_ending_elo": prior_val,
                    "canonical_mean": float(center),
                    "expected_new_elo": expected_val,
                    "actual_new_elo": actual,
                    "difference": diff,
                    "transition_block_id": first_block_by_season.get(new_s, ""),
                    "first_prediction_block_id": str(curr["prediction_block_id"]),
                    "first_prediction_game_id": str(curr["game_id"]),
                    "prior_team_state_exists": prior_exists,
                    "status": status,
                }
            )
    if records:
        return pl.DataFrame(
            records,
            schema=AUDIT_LEDGER_COLUMNS,
            infer_schema_length=len(records),
        )
    return pl.DataFrame([], schema=AUDIT_LEDGER_COLUMNS)


# ---------------------------------------------------------------------------
# Segment metrics (used by the identity gate and later candidate reporting)
# ---------------------------------------------------------------------------


def scored_rows(predictions: pl.DataFrame) -> pl.DataFrame:
    """Task04C-compatible scored set: all target-available rows.

    The validated Task04C evaluation scores every development game (1942),
    encoding a tie as a home non-win (outcome 0.0) --- identical to the
    ``target_outcome`` column of the Task04C oracle predictions parquet
    (which holds only 0.0/1.0 for all 1,942 rows, ties forced to 0.0).
    Using the same convention keeps Task04D candidate metrics comparable to
    the accepted Task04C baseline.
    """
    return predictions.filter(pl.col("target_available") == True)  # noqa: E712


def _home_win_outcome(predictions: pl.DataFrame) -> list[float]:
    """Outcome encoding matching Task04C ``target_outcome``: home win -> 1.0,
    away win OR tie -> 0.0."""
    return [1.0 if b else 0.0 for b in predictions["actual_home_win"].to_list()]


def _metrics_on_scored(df: pl.DataFrame) -> dict[str, float | None]:
    """Brier / log loss / accuracy over an already-scored subset (tie->0.0)."""
    n = df.height
    if n == 0:
        return {"n_scored": 0.0, "brier": None, "log_loss": None, "accuracy": None}
    y = _home_win_outcome(df)
    p = df["predicted_home_win_probability"].to_list()
    brier = sum((py - yny) ** 2 for py, yny in zip(p, y)) / n
    ll = sum(
        -(yny * math.log(py) + (1 - yny) * math.log(1.0 - py))
        for py, yny in zip(p, y)
    ) / n
    acc = sum(1 for py, yny in zip(p, y) if (py > 0.5) == bool(yny)) / n
    return {"n_scored": float(n), "brier": brier, "log_loss": ll, "accuracy": acc}


def metrics_for(predictions: pl.DataFrame) -> dict[str, float | None]:
    """Brier / log loss / accuracy over the Task04C-compatible scored set.

    y = home win (1.0) else 0.0 (tie and away win both 0.0), p = predicted
    home-win prob. This reproduces the accepted Task04C aggregate metrics
    (brier 0.221918210006 / log_loss 0.635506991355 / accuracy 0.647785787848).
    """
    return _metrics_on_scored(scored_rows(predictions))


def week1_4_metrics_for(predictions: pl.DataFrame) -> dict[str, float | None]:
    """Brier / log loss over REG weeks 1-4 (the Task04D primary metric)."""
    return _metrics_on_scored(
        scored_rows(predictions).filter(
            (pl.col("week") <= 4) & (pl.col("season_type") == "REG")
        )
    )


def segment_metrics(
    predictions: pl.DataFrame,
    *,
    season: int | None = None,
    season_types: tuple[str, ...] | list[str] | None = None,
    week_min: int | None = None,
    week_max: int | None = None,
) -> dict[str, float | None]:
    """Brier / log loss / accuracy over an arbitrary scored sub-segment.

    Filters are applied to the Task04C-compatible scored set (target
    available, tie -> 0.0). All filters are optional and additive.
    """
    df = scored_rows(predictions)
    if season is not None:
        df = df.filter(pl.col("season") == int(season))
    if season_types:
        df = df.filter(pl.col("season_type").is_in(list(season_types)))
    if week_min is not None:
        df = df.filter(pl.col("week") >= int(week_min))
    if week_max is not None:
        df = df.filter(pl.col("week") <= int(week_max))
    return _metrics_on_scored(df)


def reg_metrics_for(predictions: pl.DataFrame) -> dict[str, float | None]:
    """REG-season metrics (season_type == REG)."""
    return segment_metrics(predictions, season_types=("REG",))


def weeks5plus_metrics_for(predictions: pl.DataFrame) -> dict[str, float | None]:
    """REG weeks 5+ metrics."""
    return segment_metrics(predictions, season_types=("REG",), week_min=5)


def postseason_metrics_for(predictions: pl.DataFrame) -> dict[str, float | None]:
    """Postseason metrics (WC + DIV + CON + SB)."""
    return segment_metrics(predictions, season_types=("WC", "DIV", "CON", "SB"))


def season_week1_4_metrics(predictions: pl.DataFrame, season: int) -> dict[str, float | None]:
    """REG weeks 1-4 metrics for one NFL season."""
    return segment_metrics(
        predictions, season=int(season), season_types=("REG",), week_min=1, week_max=4
    )


def metric_deltas(metrics: dict[str, float], base: dict[str, float]) -> dict[str, float | None]:
    """candidate - base deltas for brier / log loss / accuracy."""
    return {
        "brier_delta": (metrics["brier"] - base["brier"])
        if metrics["brier"] is not None and base["brier"] is not None
        else None,
        "log_loss_delta": (metrics["log_loss"] - base["log_loss"])
        if metrics["log_loss"] is not None and base["log_loss"] is not None
        else None,
        "accuracy_delta": (metrics["accuracy"] - base["accuracy"])
        if metrics["accuracy"] is not None and base["accuracy"] is not None
        else None,
    }


# ---------------------------------------------------------------------------
# Official prediction artifact (per-candidate, pairable)
# ---------------------------------------------------------------------------

PREDICTION_ARTIFACT_COLUMNS: tuple[str, ...] = (
    "game_id",
    "season",
    "week",
    "season_type",
    "block_id",
    "home_team",
    "away_team",
    "target_outcome",
    "predicted_home_win_probability",
    "home_elo_before",
    "away_elo_before",
    "home_qb_adjustment",
    "away_qb_adjustment",
    "candidate_label",
    "regression_fraction",
)


def build_prediction_artifact(
    predictions: pl.DataFrame,
    candidate_label: str,
    fraction: float,
) -> pl.DataFrame:
    """Build the per-candidate official prediction artifact.

    Adds ``candidate_label``, ``regression_fraction``, a canonical
    ``block_id``, and ``target_outcome`` (home win -> 1, else 0, tie forced to
    0 to match Task04C), then selects the pairable columns. Sorted by
    (season, week, game_id) for deterministic cross-run comparison.
    """
    df = predictions.with_columns(
        [
            pl.lit(candidate_label).alias("candidate_label"),
            pl.lit(float(fraction)).alias("regression_fraction"),
            pl.col("actual_home_win")
            .fill_null(False)
            .cast(pl.Int8)
            .alias("target_outcome"),
            pl.col("prediction_block_id").alias("block_id"),
        ]
    )
    return df.select(list(PREDICTION_ARTIFACT_COLUMNS)).sort(
        ["season", "week", "game_id"]
    )
