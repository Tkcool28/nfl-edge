"""Domain exceptions and error helpers for the NFL Edge modeling stack.

Errors are deliberately specific so that the 2025 sealed holdout cannot be
reached by accident and so that drive-by failures carry an actionable
message during the development walk-forward.
"""

from __future__ import annotations

from datetime import datetime


class SealedHoldoutAccessError(RuntimeError):
    """Raised when any development code path is asked to fit, predict, score,
    calibrate, print, or report a row whose season is the sealed holdout
    (2025). Every code path that consumes rows at the model-input boundary
    must filter to the development window *and* trap this exception if a
    2025 row somehow survives the filter."""

    def __init__(self, season: int, where: str, detail: str = "") -> None:
        prefix = f"sealed holdout season {season} cannot enter {where}"
        if detail:
            prefix = f"{prefix}: {detail}"
        super().__init__(prefix)
        self.season = int(season)
        self.where = str(where)


class WalkForwardError(RuntimeError):
    """Raised when the expanding weekly walk-forward engine encounters a
    chronology, duplicate, or contract violation. The message is the
    actionable diagnostic; the call sites must not catch these silently."""

    def __init__(self, where: str, detail: str) -> None:
        super().__init__(f"walk-forward violation at {where}: {detail}")
        self.where = str(where)


class ConfigurationError(ValueError):
    """Raised when a configuration value is missing, mistyped, or out of
    range. Distinct from ValueError so model code can raise the same
    exception class for all configuration mistakes."""


class StateLedgerCorruptionError(RuntimeError):
    """Raised when the persisted state ledger is internally inconsistent.

    The walk-forward engine runs a hard correctness gate against the
    state ledger before writing it to disk. The gate enforces:

    - exactly two rows per completed game (one home, one away);
    - no duplicate side per game;
    - per-game ``home_change + away_change == 0`` within tolerance;
    - per-game ``(home_after + away_after) - (home_before + away_before) == 0``;
    - the home and away update records share the same K factor and
      MOV multiplier;
    - ``expected_home + expected_away == 1``;
    - ``actual_home + actual_away == 1``.

    The same exception is also raised by the independent Elo replay
    when a persisted ``elo_after`` does not match a recalculated
    value. The two error sites share a single class so callers can
    trap corruption uniformly.

    Any violation raises this error and prevents the ledger from
    being written.
    """

    def __init__(
        self,
        where: str = "",
        problems: list[str] | None = None,
    ) -> None:
        problems = list(problems or [])
        if not problems:
            problems = ["(unspecified)"]
        if where:
            prefix = f"state-ledger corruption at {where}"
        else:
            prefix = "State ledger failed correctness gate"
        super().__init__(
            f"{prefix}: {len(problems)} mismatch(es); first: {problems[0]}"
            + (
                f" (+{len(problems) - 1} more)"
                if len(problems) > 1
                else ""
            )
        )
        self.where = str(where)
        self.problems = list(problems)


class MarketColumnError(ValueError):
    """Raised when a market-named column is detected at any model-input
    boundary. Matches the existing ``assert_no_market_columns`` contract but
    is the runtime exception for code that does not have a frame handy."""


def assert_season_in_window(
    *,
    season: int,
    allowed_max: int,
    where: str,
    detail: str = "",
) -> None:
    """Hard-fail helper for any boundary that crosses into the sealed holdout.

    The development window is ``season <= allowed_max``. The forward-use
    season is intentionally *not* allowed for development model operations:
    2025 is sealed and 2026 belongs to the live forward-use task."""
    if not isinstance(season, int):
        raise WalkForwardError(where, f"season must be int, got {type(season).__name__}")
    if season > allowed_max:
        raise SealedHoldoutAccessError(season, where, detail)


def assert_aware_utc(value: datetime, name: str) -> datetime:
    """Reject naive datetimes. Re-export of the same helper used by the
    features pipeline so backtest code can avoid importing pipeline internals."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value
