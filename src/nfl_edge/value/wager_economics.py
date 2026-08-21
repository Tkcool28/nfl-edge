"""Task05F exact-wager probability and price semantics.

This module is downstream-only. It does not fit or alter football models.

Key contracts:
- point markets may have WIN / PUSH / LOSS probability mass;
- every wager is evaluated at its own exact line;
- EV treats push as zero-unit return;
- VALUE means strict EV > 0;
- PLAYABLE is a separate Play Through presentation status and never changes
  the strict mathematical value label.
"""
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


class PriceStatus(str, Enum):
    VALUE = "VALUE"
    PLAYABLE = "PLAYABLE"
    LEAN = "LEAN"
    PASS = "PASS"


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
    def actionable_probability(self) -> float:
        """Selected wager win probability; pushes remain separate."""
        return float(self.p_win)


@dataclass(frozen=True)
class PriceAssessment:
    expected_value: float
    strict_positive_value: bool
    current_price_american: int
    play_through_price_american: int | None
    status: PriceStatus


def expected_value_three_way(prob: OutcomeProbabilities, american_price: int | float) -> float:
    """Expected profit per 1-unit stake. Push contributes exactly zero."""
    win_profit = american_to_decimal(american_price) - 1.0
    return float(prob.p_win) * win_profit - float(prob.p_loss)


def fair_decimal_three_way(prob: OutcomeProbabilities) -> float:
    """Zero-EV decimal price under explicit push economics."""
    if prob.p_win <= 0.0:
        raise ValueError("fair price undefined when p_win <= 0")
    return 1.0 + float(prob.p_loss) / float(prob.p_win)


def fair_american_three_way(prob: OutcomeProbabilities) -> int:
    return decimal_to_american(fair_decimal_three_way(prob))


def classify_price(
    prob: OutcomeProbabilities,
    current_price_american: int,
    *,
    supported: bool = True,
    has_football_signal: bool = True,
    play_through_price_american: int | None = None,
) -> PriceAssessment:
    """Classify current price without conflating Play Through with Value.

    American prices are monotone in bettor quality: +125 > +120 and -105 > -110.
    A supplied play-through price is therefore a minimum acceptable price.

    This function does NOT derive the play-through price. The derivation remains
    deliberately separate until the core evaluator probability layer is accepted.
    """
    ev = expected_value_three_way(prob, current_price_american)
    strict = ev > 0.0
    if not supported or not has_football_signal:
        status = PriceStatus.PASS
    elif strict:
        status = PriceStatus.VALUE
    elif play_through_price_american is not None and current_price_american >= play_through_price_american:
        status = PriceStatus.PLAYABLE
    else:
        status = PriceStatus.LEAN
    return PriceAssessment(
        expected_value=ev,
        strict_positive_value=strict,
        current_price_american=int(current_price_american),
        play_through_price_american=play_through_price_american,
        status=status,
    )


def moneyline_settlement(side: str, home_score: int, away_score: int) -> Settlement:
    """NFL moneyline settlement convention used by Task05F historical grading.

    A tied final score is represented as PUSH for evaluator economics rather than
    silently encoded as a selected-side loss.
    """
    side_l = side.lower()
    if side_l not in {"home", "away"}:
        raise ValueError("moneyline side must be home or away")
    if int(home_score) == int(away_score):
        return Settlement.PUSH
    home_win = int(home_score) > int(away_score)
    selected_win = home_win if side_l == "home" else not home_win
    return Settlement.WIN if selected_win else Settlement.LOSS


def spread_residual_threshold(
    expected_home_margin: float,
    side: str,
    line: float,
) -> tuple[float, Literal["gt", "lt"]]:
    """Return residual threshold/direction for this exact spread offer.

    Let actual_home_margin = expected_home_margin + residual.
    HOME line L wins when residual > -(expected_home_margin + L).
    AWAY line L wins when residual < L - expected_home_margin.
    """
    side_l = side.lower()
    if side_l == "home":
        return -(float(expected_home_margin) + float(line)), "gt"
    if side_l == "away":
        return float(line) - float(expected_home_margin), "lt"
    raise ValueError("spread side must be home or away")


def total_residual_threshold(
    predicted_total: float,
    side: str,
    line: float,
) -> tuple[float, Literal["gt", "lt"]]:
    """Return residual threshold/direction for this exact total offer.

    Let actual_total = predicted_total + residual.
    OVER wins when residual > line - predicted_total.
    UNDER wins when residual < line - predicted_total.
    """
    side_l = side.lower()
    threshold = float(line) - float(predicted_total)
    if side_l == "over":
        return threshold, "gt"
    if side_l == "under":
        return threshold, "lt"
    raise ValueError("total side must be over or under")


def line_allows_push(line: float, *, atol: float = 1e-9) -> bool:
    """NFL score/margin totals are integers, so only integer point lines can push."""
    x = float(line)
    return isclose(x, round(x), rel_tol=0.0, abs_tol=atol)


def empirical_outcome_probabilities(
    residuals: Iterable[float],
    threshold: float,
    direction: Literal["gt", "lt"],
    *,
    atol: float = 1e-9,
) -> OutcomeProbabilities:
    """Empirical WIN/PUSH/LOSS probabilities using exact threshold equality.

    This generic primitive is useful when the residual support itself is discrete.
    Point-market helpers below use an integer-lattice continuity bin for push mass.
    """
    vals = [float(x) for x in residuals]
    if not vals:
        raise ValueError("at least one prior residual is required")
    win = push = loss = 0
    t = float(threshold)
    for r in vals:
        if isclose(r, t, rel_tol=0.0, abs_tol=atol):
            push += 1
        elif (r > t) if direction == "gt" else (r < t):
            win += 1
        else:
            loss += 1
    n = float(len(vals))
    return OutcomeProbabilities(win / n, push / n, loss / n)


def _jeffreys_probabilities(win: int, push: int, loss: int, *, push_possible: bool) -> OutcomeProbabilities:
    """Preregistered fixed Jeffreys smoothing; never fitted to ROI."""
    if push_possible:
        # Symmetric Dirichlet(1/2, 1/2, 1/2) over WIN/PUSH/LOSS.
        den = float(win + push + loss) + 1.5
        return OutcomeProbabilities((win + 0.5) / den, (push + 0.5) / den, (loss + 0.5) / den)
    # Push is structurally impossible: Jeffreys Beta(1/2,1/2) over WIN/LOSS.
    den = float(win + loss) + 1.0
    return OutcomeProbabilities((win + 0.5) / den, 0.0, (loss + 0.5) / den)


def empirical_lattice_outcome_probabilities(
    residuals: Iterable[float],
    threshold: float,
    direction: Literal["gt", "lt"],
    *,
    push_possible: bool,
) -> OutcomeProbabilities:
    """Empirical probabilities with a one-score-point continuity bin for pushes.

    Football margins/totals live on the integer score lattice while model residuals
    are continuous because model predictions are continuous. For an integer line,
    a push is the single integer outcome centered at `threshold`; in residual space
    that integer cell is represented by [threshold-0.5, threshold+0.5).

    For half-point/non-integer lines push is impossible and the exact threshold
    splits win/loss mass directly. Fixed Jeffreys smoothing is then applied exactly
    as preregistered in config/task05f_evaluator_rebuild_v1.yaml.
    """
    vals = [float(x) for x in residuals]
    if not vals:
        raise ValueError("at least one prior residual is required")
    t = float(threshold)
    win = push = loss = 0
    if not push_possible:
        for r in vals:
            won = (r > t) if direction == "gt" else (r < t)
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
