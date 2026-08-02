"""Edge calculator — converts model probabilities to +EV picks.

Key functions:
- expected_value(model_prob, decimal_odds) -> EV in % of stake
- best_bet_for_game(picks_df) -> best +EV pick
- color_vs_pinnacle(dk_odds, fd_odds, pin_odds) -> color code
"""
from typing import Optional
import pandas as pd


def expected_value(model_prob: float, decimal_odds: float) -> float:
    """EV per unit staked. Positive = +EV bet."""
    return model_prob * (decimal_odds - 1) - (1 - model_prob)


def kelly_fraction(model_prob: float, decimal_odds: float) -> float:
    """Full Kelly. Half-Kelly is recommended in practice."""
    b = decimal_odds - 1
    q = 1 - model_prob
    f = (b * model_prob - q) / b
    return max(0.0, f)


def best_pick_from_games(games_df: pd.DataFrame,
                         min_prob: float = 0.50,
                         min_ev: float = 0.03,
                         max_decimal: float = 4.5) -> Optional[pd.Series]:
    """Return the game with the highest +EV, or None if no qualifying picks.

    games_df must have columns: model_prob, decimal_odds, ev_pct.
    """
    df = games_df.copy()
    df = df[df["model_prob"] >= min_prob]
    df = df[df["ev_pct"] >= min_ev]
    df = df[df["decimal_odds"] <= max_decimal]
    if df.empty:
        return None
    return df.loc[df["ev_pct"].idxmax()]


def color_vs_pinnacle(dk_odds: int, fd_odds: int, pin_odds: int) -> dict:
    """Return color codes for DK and FD vs Pinnacle.

    Returns dict like {"dk": ("green"/"red"/"neutral", odds), ...}
    """
    out = {}
    for name, odds in [("dk", dk_odds), ("fd", fd_odds)]:
        if odds is None or pin_odds is None:
            out[name] = ("neutral", odds)
            continue
        # In American odds, "better" = larger number for underdogs,
        # smaller absolute value for favorites. We compare implied prob.
        def implied(o):
            if o > 0:
                return 100.0 / (o + 100)
            return abs(o) / (abs(o) + 100)
        diff = implied(odds) - implied(pin_odds)
        if diff < -0.01:
            out[name] = ("green", odds)   # better than sharp
        elif diff > 0.01:
            out[name] = ("red", odds)     # worse than sharp
        else:
            out[name] = ("neutral", odds)
    return out
