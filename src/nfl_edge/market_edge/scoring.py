"""Pure, deterministic market-edge grading primitives for Task 05E.

These functions are intentionally free of any data dependency so they can be
unit-tested in isolation and reused unchanged for BOTH the discovery
(2020-2022) and confirmation (2023-2024) periods. 2025 is never passed here.

Grading conventions (verified against the frozen games outcome table and the
preregistered `market_edge_validation_v1.yaml` returns/staking rules):

* flat 1-unit flat stakes (`unit_stake: 1.0`)
* return price is the ACTUAL actionable DK/FD decimal price (never Pinnacle)
* win  -> profit = decimal - 1
* loss -> profit = -1
* push -> profit = 0  (moneyline tie; spread covers exactly; total pushes)
* hit rate = wins / N  where N includes pushes (a push is not a loss but does
  not count as a win).
"""

from __future__ import annotations


def american_to_decimal(american: int | float | None) -> float | None:
    """American odds -> decimal odds. American 0 or None -> None (not priced)."""
    if american is None or american == 0:
        return None
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(float(american))


def moneyline_grading(
    selected_side: str,
    home_score: int,
    away_score: int,
    price_decimal: float,
) -> tuple[int, int, float]:
    """Grade a selected-side moneyline bet.

    Returns (win, push, profit); win and push are 0/1 flags with push
    exclusive of win (a tie is a push, not a win and not a loss).
    """
    margin_home = float(home_score) - float(away_score)
    side_margin = margin_home if selected_side == "home" else -margin_home
    if side_margin == 0:
        return 0, 1, 0.0
    if side_margin > 0:
        return 1, 0, round(price_decimal - 1.0, 6)
    return 0, 0, -1.0


def spread_grading(
    selected_side: str,
    home_score: int,
    away_score: int,
    act_line: float,
    price_decimal: float,
) -> tuple[int, int, float]:
    """Grade a selected-side spread bet against the actual actionable line.

    ``act_line`` is the selected-side spread as offered (positive => the
    selected side receives points; negative => gives points). The selected
    side covers when selected-side margin + act_line > 0.
    """
    margin_home = float(home_score) - float(away_score)
    side_margin = margin_home if selected_side == "home" else -margin_home
    cover = side_margin + float(act_line)
    if abs(cover) < 1e-9:
        return 0, 1, 0.0
    if cover > 0:
        return 1, 0, round(price_decimal - 1.0, 6)
    return 0, 0, -1.0


def total_grading(
    selected_side: str,
    home_score: int,
    away_score: int,
    act_line: float,
    price_decimal: float,
) -> tuple[int, int, float]:
    """Grade an OVER/UNDER total bet against the actual actionable total line.

    ``act_line`` is the total O/U line (a push when the total equals the line).
    """
    total = float(home_score) + float(away_score)
    margin_diff = (total - act_line) if selected_side == "over" else (act_line - total)
    if abs(margin_diff) < 1e-9:
        return 0, 1, 0.0
    if margin_diff > 0:
        return 1, 0, round(price_decimal - 1.0, 6)
    return 0, 0, -1.0


def breakeven_from_decimal(price_decimal: float) -> float:
    """Implicit breakeven probability implied by a decimal price."""
    if price_decimal is None or price_decimal <= 1.0:
        raise ValueError("breakeven requires a decimal price > 1.0")
    return 1.0 / price_decimal


# Ordered actionability source (frozen, deterministic; never Pinnacle for action)
ACTIONABLE_BOOK_ORDER = ("draftkings", "fanduel")