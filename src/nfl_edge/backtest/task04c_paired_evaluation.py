"""Evaluation-only minimal paired QB-Elo harness (Task 04C-3).

This module does NOT modify QB-Elo, does NOT rebuild QB history, and does
NOT write the final 1942-game output artifacts. It layers an explicit
mode seam (BASELINE vs ORACLE) onto the existing two-pass walk-forward
engine via the optional ``qb_adjustment_resolver`` parameter added to
:func:`nfl_edge.backtest.walk_forward` internals, then builds an
evaluation-only team-transition audit ledger that proves both modes share
byte-identical team-Elo state transitions.

The ONLY prediction-path difference between the two modes is the QB
adjustment values delivered to ``elo_probability_home``:

- BASELINE: ``home_qb_adj = 0.0``, ``away_qb_adj = 0.0``
- ORACLE:   frozen v2 ``home_qb_adjustment_elo`` / ``away_qb_adjustment_elo``
            joined by canonical ``game_id``

All model semantics (initial Elo, HFA, K, MOV, probability transform,
team update, season reset, chronology) are the existing values. The team
state transition path (``update_state_with_margin``) never references the
QB adjustment, so baseline and oracle transitions must match exactly
row-for-row.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import polars as pl

from ..common.errors import WalkForwardError

# ---------------------------------------------------------------------------
# Adjustment providers
# ---------------------------------------------------------------------------


class OracleAdjustmentError(WalkForwardError):
    """Raised when the frozen oracle artifact violates the Task 04C
    fail-closed contract (missing/duplicate/null/additional game_id)."""

    def __init__(self, where: str, detail: str) -> None:
        super().__init__(where=f"task04c.oracle.{where}", detail=detail)


class OracleQBAdjustments:
    """RUN B / ORACLE: frozen v2 oracle adjustments keyed by game_id.

    Fail-closed: construction validates the artifact and any resolution of
    an unknown game_id raises rather than silently zero-filling.
    """

    def __init__(self, oracle_parquet: str | Path) -> None:
        self._path = Path(oracle_parquet)
        self._frame = pl.read_parquet(self._path)
        self._validate_artifact()
        pairs = self._frame.select(
            ["game_id", "home_qb_adjustment_elo", "away_qb_adjustment_elo"]
        ).to_dicts()
        self._by_game: dict[str, tuple[float, float]] = {
            str(r["game_id"]): (
                float(r["home_qb_adjustment_elo"]),
                float(r["away_qb_adjustment_elo"]),
            )
            for r in pairs
        }
        self._game_ids: set[str] = set(self._by_game.keys())

    def _validate_artifact(self) -> None:
        frame = self._frame
        # Required columns.
        missing = [
            c for c in ("game_id", "home_qb_adjustment_elo", "away_qb_adjustment_elo")
            if c not in frame.columns
        ]
        if missing:
            raise OracleAdjustmentError(
                "schema", f"missing required columns: {missing}"
            )
        # Null game_id.
        null_gid = int(frame.filter(pl.col("game_id").is_null()).height)
        if null_gid:
            raise OracleAdjustmentError(
                "null_game_id", f"{null_gid} oracle rows have null game_id"
            )
        # Duplicate game_id.
        dupes = frame.group_by("game_id").len().filter(pl.col("len") > 1)
        if dupes.height:
            raise OracleAdjustmentError(
                "duplicate_game_id",
                f"{dupes.height} duplicated game_ids: {dupes['game_id'].to_list()[:5]}",
            )
        # Null adjustments.
        null_home = int(frame.filter(pl.col("home_qb_adjustment_elo").is_null()).height)
        null_away = int(frame.filter(pl.col("away_qb_adjustment_elo").is_null()).height)
        if null_home or null_away:
            raise OracleAdjustmentError(
                "null_adjustment",
                f"null home={null_home} null away={null_away}",
            )

    @property
    def game_ids(self) -> set[str]:
        return set(self._game_ids)

    @property
    def n_rows(self) -> int:
        return int(self._frame.height)

    def __call__(self, game_id: str) -> tuple[float, float]:
        if game_id not in self._by_game:
            raise OracleAdjustmentError(
                "missing_game_id", f"no oracle row for canonical game_id={game_id}"
            )
        return self._by_game[game_id]

    def assert_coverage(
        self, canonical_game_ids: Iterable[str], *, where: str = "coverage"
    ) -> None:
        """Fail closed unless the oracle covers exactly the canonical
        universe: one row per canonical game_id and no extras."""
        canon = set(canonical_game_ids)
        missing = sorted(canon - self._game_ids)
        extra = sorted(self._game_ids - canon)
        problems = []
        if missing:
            problems.append(f"missing canonical game_ids: {missing[:10]} ({len(missing)})")
        if extra:
            problems.append(f"extra oracle game_ids outside universe: {extra[:10]} ({len(extra)})")
        if problems:
            raise OracleAdjustmentError(where, "; ".join(problems))


def make_resolver(
    mode: str,
    oracle: OracleQBAdjustments | None = None,
) -> "Callable[[str], tuple[float, float]] | None":
    """Return the adjustment resolver for the requested mode.

    BASELINE returns ``None``: the engine's default path supplies
    ``home_qb_adj = 0.0`` / ``away_qb_adj = 0.0`` with an ``UNKNOWN``
    certainty label — byte-identical to the pre-existing QB-Elo run.
    ORACLE returns the frozen-artifact provider (CONFIRMED semantics).
    """
    mode = mode.upper()
    if mode == "BASELINE":
        return None
    if mode == "ORACLE":
        if oracle is None:
            raise WalkForwardError(
                "task04c.make_resolver",
                "ORACLE mode requires an OracleQBAdjustments instance",
            )
        return oracle
    raise WalkForwardError(
        "task04c.make_resolver", f"unknown mode: {mode!r}"
    )


# ---------------------------------------------------------------------------
# Evaluation-only transition audit ledger
# ---------------------------------------------------------------------------


TRANSITION_LEDGER_COLUMNS: tuple[str, ...] = (
    "row_pos",
    "block_id",
    "game_id",
    "season",
    "season_type",
    "week",
    "home_team",
    "away_team",
    "pregame_home_elo",
    "pregame_away_elo",
    "actual_result_home",     # actual game result input used by the update
    "actual_margin",
    "update_multiplier",      # MOV-derived quantity actually used by update
    "k_factor",
    "expected_result_home",   # expected score actually used by update_state_with_margin
    "delta",
    "postgame_home_elo",
    "postgame_away_elo",
)


def build_transition_audit_ledger(state_rows: Iterable[Mapping[str, Any]]) -> pl.DataFrame:
    """Pivot the canonical per-team state ledger into one audit row per
    completed game, capturing the exact transition inputs/outputs shared
    by baseline and oracle."""
    records: list[dict[str, Any]] = []
    home: dict[str, Mapping[str, Any]] = {}
    away: dict[str, Mapping[str, Any]] = {}
    for row in state_rows:
        gid = str(row["game_id"])
        if row["side"] == "home":
            home[gid] = row
        else:
            away[gid] = row
    for gid in sorted(home.keys() & away.keys()):
        h = home[gid]
        a = away[gid]
        records.append(
            {
                "row_pos": int(h["state_update_order"]),
                "block_id": str(h["prediction_block_id"]),
                "game_id": gid,
                "season": int(h["season"]),
                "season_type": str(h["season_type"]),
                "week": int(h["week"]),
                "home_team": str(h["team"]),
                "away_team": str(a["team"]),
                "pregame_home_elo": float(h["elo_before"]),
                "pregame_away_elo": float(a["elo_before"]),
                "actual_result_home": float(h["actual_result"]),
                "actual_margin": int(h["actual_margin"]),
                "update_multiplier": float(h["update_multiplier"]),
                "k_factor": float(h["k_factor"]),
                "expected_result_home": float(h["expected_result"]),
                "delta": float(h["elo_change"]),
                "postgame_home_elo": float(h["elo_after"]),
                "postgame_away_elo": float(a["elo_after"]),
            }
        )
    return pl.DataFrame(records, schema=TRANSITION_LEDGER_COLUMNS)


def assert_transition_ledgers_equal(
    baseline: pl.DataFrame,
    oracle: pl.DataFrame,
) -> None:
    """Prove oracle QB information never changes team-Elo state."""
    if baseline.height != oracle.height:
        raise WalkForwardError(
            "task04c.transition_equal",
            f"row count differs baseline={baseline.height} oracle={oracle.height}",
        )
    sort_key = ["row_pos", "game_id"]
    b = baseline.sort(sort_key)
    o = oracle.sort(sort_key)
    for col in TRANSITION_LEDGER_COLUMNS:
        bv = b[col].to_list()
        ov = o[col].to_list()
        for i, (x, y) in enumerate(zip(bv, ov)):
            if x != y:
                raise WalkForwardError(
                    "task04c.transition_equal",
                    f"column {col!r} row {i} baseline={x} oracle={y}",
                )
