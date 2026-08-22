"""Public contracts for the frozen Task05F market-evaluation layer."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

MARKET_TYPES = ("moneyline", "spread", "total")
RELIABILITY_TIERS = ("HIGH", "MEDIUM", "LOW", "UNSUPPORTED")
SEALED_SEASONS = {2025}


@dataclass(frozen=True)
class NormalizedOffer:
    market_type: str
    side: str
    book: str
    price_american: int
    line: float | None = None
    snapshot_utc: str | None = None
    source: str = "stored"

    def __post_init__(self) -> None:
        market = self.market_type.lower()
        side = self.side.lower()
        valid_sides = {
            "moneyline": {"home", "away"},
            "spread": {"home", "away"},
            "total": {"over", "under"},
        }
        if market not in valid_sides:
            raise ValueError(f"unsupported market_type={self.market_type}")
        if side not in valid_sides[market]:
            raise ValueError(f"invalid {market} side={self.side}")
        if not str(self.book).strip():
            raise ValueError("book/source required")
        if int(self.price_american) == 0:
            raise ValueError("American odds cannot be 0")
        if market != "moneyline" and self.line is None:
            raise ValueError("spread/total offer requires line")


@dataclass(frozen=True)
class GameState:
    game_id: str
    season: int
    week: str
    kickoff_utc: str | None
    qbelo_home: float | None = None
    xgb_home: float | None = None
    expected_home_margin: float | None = None
    predicted_total_r4: float | None = None
    football_model_version: str = "frozen_task05f_inputs"


@dataclass(frozen=True)
class SupportFeature:
    name: str
    min_value: float
    max_value: float
    span: float


@dataclass(frozen=True)
class MoneylineV4State:
    market_intercept: float
    market_slope: float
    model_weight: float
    training_n: int
    prior_ties: int
    prior_games: int
    support_features: tuple[SupportFeature, ...]
    config_sha256: str
    version: str = "ml_v4"


@dataclass(frozen=True)
class PointV3State:
    market_type: str
    sigma: float
    beta: float
    residuals: tuple[float, ...]
    training_n: int
    support_features: tuple[SupportFeature, ...]
    config_sha256: str
    version: str = "v3"

    def __post_init__(self) -> None:
        if self.market_type not in {"spread", "total"}:
            raise ValueError("PointV3State market_type must be spread or total")
        if self.sigma <= 0:
            raise ValueError("sigma must be positive")
        if not 0.0 <= self.beta <= 1.0:
            raise ValueError("beta must be in [0,1]")
        if not self.residuals:
            raise ValueError("residual state cannot be empty")


@dataclass(frozen=True)
class MarketAnchor:
    """Pinnacle benchmark needed to evaluate one accepted family.

    Moneyline uses ``home_no_vig_probability``. Point markets use a canonical
    threshold and the conditional-on-nonpush probability of finishing above it.
    """

    market_type: str
    home_no_vig_probability: float | None = None
    threshold: float | None = None
    probability_above_nonpush: float | None = None
    push_possible: bool = False
    book: str = "pinnacle"


@dataclass(frozen=True)
class ReliabilityState:
    radius: float | None
    support_n: int
    block_count: int
    stable: bool


@dataclass(frozen=True)
class EvaluationResult:
    p_win: float | None
    p_push: float | None
    p_loss: float | None
    actionable_probability: float | None
    conditional_nonpush_probability: float | None
    staking_probability: float | None
    staking_anchor_probability: float | None
    fair_price_american: int | None
    expected_value: float | None
    strict_positive_value: bool
    break_even_probability: float | None
    evaluated_edge_probability: float | None
    staking_edge_probability: float | None
    reliability: str
    uncertainty: float | None
    support_n: int
    support_distance: float | None
    evaluator_version: str
    supported: bool = True
    reason: str | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)


def as_safe_dict(obj: Any) -> dict[str, Any]:
    return asdict(obj)
