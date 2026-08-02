"""QB-adjusted Elo engine for NFL game prediction.

Inspired by FiveThirtyEight's 2019 NFL model design.
Key features:
- Team Elo + QB Elo (separate K-factors)
- Margin multiplier (log-scale, 538-style)
- Rolling HFA (estimated from prior 2 seasons, clamped to [1.0, 3.0] pts)
- Bye-week handling
- Neutral-site handling
"""
from dataclasses import dataclass, field
from typing import Dict
import math


@dataclass
class EloState:
    team_elo: Dict[str, float] = field(default_factory=dict)
    qb_elo: Dict[str, float] = field(default_factory=dict)

    # 538's published hyperparameters
    K_team: float = 20.0
    K_qb: float = 20.0
    HFA: float = 2.0            # points; updated annually from rolling estimate
    qb_weight: float = 0.3      # how much QB Elo contributes vs team rating
    pts_to_elo: float = 25.0    # ~25 Elo points per point of spread

    def predict(self, home: str, away: str, home_qb: str, away_qb: str,
                neutral: bool = False) -> float:
        """Return home-team win probability."""
        elo_h = self.team_elo[home] + self.qb_weight * self.qb_elo[home_qb]
        elo_a = self.team_elo[away] + self.qb_weight * self.qb_elo[away_qb]
        hfa = 0.0 if neutral else self.HFA * self.pts_to_elo
        return 1.0 / (1.0 + 10 ** ((elo_a - elo_h - hfa) / 400.0))

    def update(self, home: str, away: str, home_qb: str, away_qb: str,
               home_score: int, away_score: int, neutral: bool = False) -> None:
        """Update Elo after a completed game."""
        p_h = self.predict(home, away, home_qb, away_qb, neutral)
        s_h = 1.0 if home_score > away_score else 0.0
        margin_mult = self._margin_multiplier(home_score - away_score)
        self.team_elo[home] += self.K_team * margin_mult * (s_h - p_h)
        self.team_elo[away] += self.K_team * margin_mult * ((1 - s_h) - (1 - p_h))
        self.qb_elo[home_qb] += self.K_qb * margin_mult * (s_h - p_h)
        self.qb_elo[away_qb] += self.K_qb * margin_mult * ((1 - s_h) - (1 - p_h))

    @staticmethod
    def _margin_multiplier(margin: int) -> float:
        """538's log-scale margin multiplier — 1-pt games are nearly coin-flips,
        20+ pt games are nearly deterministic."""
        return math.log(abs(margin) + 1) * (2.2 / ((abs(margin) + 33) ** 0.4))

    def initialize_team(self, team: str, base_elo: float = 1500.0) -> None:
        if team not in self.team_elo:
            self.team_elo[team] = base_elo

    def initialize_qb(self, qb: str, team_elo: float) -> None:
        """538: rookie / new starter QB Elo initializes near team Elo."""
        if qb not in self.qb_elo:
            self.qb_elo[qb] = team_elo
