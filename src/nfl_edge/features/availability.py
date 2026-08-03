"""UTC and deterministic weekly availability primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import polars as pl

from .validation import canonical_json_sha256

UTC = timezone.utc
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_AVAILABILITY_CACHE: dict[tuple[str, str], pl.DataFrame] = {}


@dataclass(frozen=True)
class AvailabilityPolicy:
    """Conservative publication boundary configuration."""

    weekday: int = 1  # Tuesday, Monday=0.
    hour: int = 12
    minute: int = 0
    timezone_name: str = "UTC"
    unusual_date_policy: str = "STRICTLY_FOLLOWING_BOUNDARY"

    def __post_init__(self) -> None:
        if self.timezone_name != "UTC":
            raise ValueError("weekly availability timezone must be UTC")
        if not 0 <= self.weekday <= 6:
            raise ValueError("weekday must be between 0 and 6")
        if not 0 <= self.hour <= 23 or not 0 <= self.minute <= 59:
            raise ValueError("invalid weekly boundary time")

    @property
    def rule_name(self) -> str:
        weekday = WEEKDAY_NAMES[self.weekday].upper()
        return f"WEEK_COMPLETE_{weekday}_{self.hour:02d}{self.minute:02d}_UTC_V1"


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.astimezone(UTC).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _boundary_on(day: date, policy: AvailabilityPolicy) -> datetime:
    return datetime.combine(day, time(policy.hour, policy.minute), tzinfo=UTC)


def publication_boundary_after(value: Any, policy: AvailabilityPolicy) -> datetime:
    """Return the configured boundary strictly after an event date."""

    event_date = _as_date(value)
    days = (policy.weekday - event_date.weekday()) % 7
    if days == 0:
        days = 7
    return _boundary_on(event_date + timedelta(days=days), policy)


def prediction_boundary_before(value: Any, policy: AvailabilityPolicy) -> datetime:
    """Return the configured boundary strictly before a week begins."""

    event_date = _as_date(value)
    days = (event_date.weekday() - policy.weekday) % 7
    if days == 0:
        days = 7
    return _boundary_on(event_date - timedelta(days=days), policy)


def _require_aware_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def record_is_eligible(source_available_at: datetime, prediction_as_of: datetime) -> bool:
    """Inclusive source cutoff: records at or before as-of are eligible."""

    source = _require_aware_utc(source_available_at, "source_available_at")
    cutoff = _require_aware_utc(prediction_as_of, "prediction_as_of")
    return source <= cutoff


def build_weekly_availability(games: pl.DataFrame, policy: AvailabilityPolicy) -> pl.DataFrame:
    """Build one deterministic availability row per season/type/week.

    ``gameday`` is a date-level field. ``week_completed_at_boundary_utc``
    intentionally names a conservative eligibility boundary, not an asserted
    exact final-whistle timestamp.
    """

    required = {"game_id", "season", "season_type", "week", "gameday"}
    missing = sorted(required - set(games.columns))
    if missing:
        raise ValueError(f"games missing availability columns: {missing}")
    duplicates = games.group_by("game_id").len().filter(pl.col("len") > 1)
    if duplicates.height:
        raise ValueError(f"duplicate game rows: {duplicates['game_id'].to_list()[:5]}")
    if games["gameday"].null_count():
        raise ValueError("gameday cannot be null for weekly availability")

    payload = games.select(["game_id", "season", "season_type", "week", "gameday"])
    input_fingerprint = canonical_json_sha256(payload.to_dict(as_series=False))
    policy_fingerprint = canonical_json_sha256(
        {
            "weekday": policy.weekday,
            "hour": policy.hour,
            "minute": policy.minute,
            "timezone_name": policy.timezone_name,
            "unusual_date_policy": policy.unusual_date_policy,
        }
    )
    cache_key = (input_fingerprint, policy_fingerprint)
    cached = _AVAILABILITY_CACHE.get(cache_key)
    if cached is not None:
        return cached.clone()

    rows: list[dict[str, Any]] = []
    grouped = games.sort(["season", "week", "game_id"]).group_by(
        ["season", "season_type", "week"], maintain_order=True
    )
    for key, week_games in grouped:
        season, season_type, week = key
        days = [_as_date(value) for value in week_games["gameday"].to_list()]
        week_start = min(days)
        week_end = max(days)
        publication = publication_boundary_after(week_end, policy)
        prediction = prediction_boundary_before(week_start, policy)
        unusual = week_end.weekday() not in {0, 1, 3, 5, 6}
        postseason = str(season_type).upper() != "REG"
        quality_parts = ["CONSERVATIVE_WEEKLY_BATCH"]
        if postseason:
            quality_parts.append("POSTSEASON")
        if unusual or week_end.weekday() == policy.weekday:
            quality_parts.append("UNUSUAL_DATE_STRICTLY_FOLLOWING")
        rows.append(
            {
                "season": int(season),
                "season_type": str(season_type),
                "week": int(week),
                "week_first_game_date": week_start,
                "week_last_game_date": week_end,
                "prediction_as_of_utc": prediction,
                "week_completed_at_boundary_utc": publication,
                "eligible_for_features_at_utc": publication,
                "availability_rule": policy.rule_name,
                "availability_quality": ";".join(quality_parts),
            }
        )
    schema = {
        "season": pl.Int32,
        "season_type": pl.String,
        "week": pl.Int32,
        "week_first_game_date": pl.Date,
        "week_last_game_date": pl.Date,
        "prediction_as_of_utc": pl.Datetime("us", "UTC"),
        "week_completed_at_boundary_utc": pl.Datetime("us", "UTC"),
        "eligible_for_features_at_utc": pl.Datetime("us", "UTC"),
        "availability_rule": pl.String,
        "availability_quality": pl.String,
    }
    result = pl.DataFrame(rows, schema=schema).sort(["season", "week", "season_type"])
    _AVAILABILITY_CACHE[cache_key] = result.clone()
    return result
