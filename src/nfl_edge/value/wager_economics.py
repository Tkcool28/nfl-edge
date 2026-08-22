"""Exact wager settlement and three-way probability economics."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isclose
from typing import Iterable, Literal

from .market_math import american_to_decimal, decimal_to_american


class Settlement(str, Enum):
    WIN = "WIN"
    PUSH = "PUSH"
    LOSS = "LOSS"


@dataclass(frozen=True)
class OutcomeProbabilities:
    p_win: float
    p_push: float
    p_loss: float

    def __post_init__(self) -> None:
        vals = (float(self.p_win), float(self.p_push), float(self.p_loss))
        if any(v < 0.0 or v > 1.0 for v in vals):
            raise ValueError("outcome probabilities must be in [0,1]")
        if not isclose(sum(vals), 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("p_win + p_push + p_loss must equal 1")

    @property
    def conditional_nonpush_probability(self) -> float:
        den = float(self.p_win) + float(self.p_loss)
        if den <= 0:
            raise ValueError("zero non-push mass")
        return float(self.p_win) / den


def expected_value_three_way(prob: OutcomeProbabilities, american_price: int | float) -> float:
    return float(prob.p_win) * (american_to_decimal(american_price) - 1.0) - float(prob.p_loss)


def fair_decimal_three_way(prob: OutcomeProbabilities) -> float:
    if prob.p_win <= 0.0:
        raise ValueError("fair price undefined when p_win <= 0")
    return 1.0 + float(prob.p_loss) / float(prob.p_win)


def fair_american_three_way(prob: OutcomeProbabilities) -> int:
    return decimal_to_american(fair_decimal_three_way(prob))


def moneyline_settlement(side: str, home_score: int, away_score: int) -> Settlement:
    side_l = side.lower()
    if side_l not in {"home", "away"}:
        raise ValueError("moneyline side must be home or away")
    if int(home_score) == int(away_score):
        return Settlement.PUSH
    home_win = int(home_score) > int(away_score)
    selected_win = home_win if side_l == "home" else not home_win
    return Settlement.WIN if selected_win else Settlement.LOSS


def spread_settlement(side: str, line: float, home_score: int, away_score: int) -> Settlement:
    margin = (home_score - away_score) if side.lower() == "home" else (away_score - home_score)
    value = float(margin) + float(line)
    if abs(value) < 1e-9:
        return Settlement.PUSH
    return Settlement.WIN if value > 0 else Settlement.LOSS


def total_settlement(side: str, line: float, home_score: int, away_score: int) -> Settlement:
    total = float(home_score + away_score)
    value = total - float(line) if side.lower() == "over" else float(line) - total
    if abs(value) < 1e-9:
        return Settlement.PUSH
    return Settlement.WIN if value > 0 else Settlement.LOSS


def moneyline_outcome_probabilities(
    conditional_win_probability: float,
    *,
    prior_ties: int,
    prior_games: int,
) -> OutcomeProbabilities:
    q = float(conditional_win_probability)
    if not 0.0 <= q <= 1.0:
        raise ValueError("conditional win probability must be in [0,1]")
    n = int(prior_games)
    t = int(prior_ties)
    if n < 0 or t < 0 or t > n:
        raise ValueError("invalid prior tie counts")
    p_push = (t + 0.5) / (n + 1.0)
    nonpush = 1.0 - p_push
    return OutcomeProbabilities(nonpush * q, p_push, nonpush * (1.0 - q))


def line_allows_push(line: float, *, atol: float = 1e-9) -> bool:
    return isclose(float(line), round(float(line)), rel_tol=0.0, abs_tol=atol)


def spread_residual_threshold(expected_home_margin: float, side: str, line: float) -> tuple[float, Literal["gt", "lt"]]:
    if side.lower() == "home":
        return -(float(expected_home_margin) + float(line)), "gt"
    if side.lower() == "away":
        return float(line) - float(expected_home_margin), "lt"
    raise ValueError("spread side must be home or away")


def total_residual_threshold(predicted_total: float, side: str, line: float) -> tuple[float, Literal["gt", "lt"]]:
    threshold = float(line) - float(predicted_total)
    if side.lower() == "over":
        return threshold, "gt"
    if side.lower() == "under":
        return threshold, "lt"
    raise ValueError("total side must be over or under")


def _jeffreys_probabilities(win: int, push: int, loss: int, *, push_possible: bool) -> OutcomeProbabilities:
    if push_possible:
        den = float(win + push + loss) + 1.5
        return OutcomeProbabilities((win + 0.5) / den, (push + 0.5) / den, (loss + 0.5) / den)
    den = float(win + loss) + 1.0
    return OutcomeProbabilities((win + 0.5) / den, 0.0, (loss + 0.5) / den)


def empirical_lattice_outcome_probabilities(
    residuals: Iterable[float],
    threshold: float,
    direction: Literal["gt", "lt"],
    *,
    push_possible: bool,
) -> OutcomeProbabilities:
    vals = [float(x) for x in residuals]
    if not vals:
        raise ValueError("at least one prior residual is required")
    t = float(threshold)
    win = push = loss = 0
    if not push_possible:
        for r in vals:
            won = r > t if direction == "gt" else r < t
            if won:
                win += 1
            else:
                loss += 1
    else:
        lo, hi = t - 0.5, t + 0.5
        for r in vals:
            if lo <= r < hi:
                push += 1
            elif direction == "gt":
                if r >= hi:
                    win += 1
                else:
                    loss += 1
            else:
                if r < lo:
                    win += 1
                else:
                    loss += 1
    return _jeffreys_probabilities(win, push, loss, push_possible=push_possible)


def empirical_spread_probabilities(
    residuals: Iterable[float],
    expected_home_margin: float,
    side: str,
    line: float,
) -> OutcomeProbabilities:
    threshold, direction = spread_residual_threshold(expected_home_margin, side, line)
    return empirical_lattice_outcome_probabilities(
        residuals,
        threshold,
        direction,
        push_possible=line_allows_push(line),
    )


def empirical_total_probabilities(
    residuals: Iterable[float],
    predicted_total: float,
    side: str,
    line: float,
) -> OutcomeProbabilities:
    threshold, direction = total_residual_threshold(predicted_total, side, line)
    return empirical_lattice_outcome_probabilities(
        residuals,
        threshold,
        direction,
        push_possible=line_allows_push(line),
    )
