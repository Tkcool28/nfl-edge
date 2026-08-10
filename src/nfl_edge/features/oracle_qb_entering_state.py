"""Pure prior-block QB entering-state reconstruction for oracle identities."""
from __future__ import annotations

from dataclasses import dataclass


PRIORITY = {"REG": 0, "WC": 1, "DIV": 2, "CON": 3, "SB": 4}


def block_key(season: int, season_type: str, week: int) -> tuple[int, int, int]:
    return int(season), PRIORITY[str(season_type).upper()], int(week)


@dataclass(frozen=True)
class QBState:
    games: int
    dropbacks: int
    total_epa: float
    observed_epa: float | None
    weight: float
    shrunk_epa: float
    adjustment: float
    earliest_game: str
    latest_game: str
    latest_end: str


def entering_state(rows: list[dict], target: tuple[int, int, int], cfg) -> QBState:
    eligible = [r for r in rows if r["block"] < target and int(r["season"]) <= 2024]
    dropbacks = sum(int(r["attempts"]) + int(r["sacks_suffered"]) for r in eligible)
    total = sum(float(r["passing_epa"]) for r in eligible)
    if not dropbacks:
        return QBState(0, 0, 0.0, None, 0.0, cfg.replacement_passing_epa, 0.0, "", "", "")
    observed = total / dropbacks
    weight = dropbacks / (dropbacks + cfg.sample_k)
    shrunk = weight * observed + (1 - weight) * cfg.replacement_passing_epa
    adjustment = max(-cfg.max_abs_elo, min(cfg.max_abs_elo, (shrunk - cfg.replacement_passing_epa) * cfg.scale_elo_per_shrunk_epa))
    return QBState(len(eligible), dropbacks, total, observed, weight, shrunk, adjustment, eligible[0]["game_id"], eligible[-1]["game_id"], eligible[-1]["game_end_utc"])
