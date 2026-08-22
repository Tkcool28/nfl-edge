from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

RELIABILITY_TIERS = ("HIGH", "MEDIUM", "LOW", "UNSUPPORTED")
MARKET_TYPES = ("moneyline", "spread", "total")

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
        if self.market_type not in MARKET_TYPES:
            raise ValueError(f"unsupported market_type={self.market_type}")
        if not self.book:
            raise ValueError("book/source required")
        if self.price_american == 0:
            raise ValueError("American odds cannot be 0")
        if self.market_type != "moneyline" and self.line is None:
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
    span: float  # safe floor applied at construction

@dataclass(frozen=True)
class EvaluatorState:
    market_type: str
    family: str
    version: str
    training_n: int
    parameters: Mapping[str, Any]
    support_min: float | None = None
    support_max: float | None = None
    uncertainty: float | None = None
    config_sha256: str = ""
    stable_blocks: bool = True
    support_features: tuple[SupportFeature, ...] = ()

@dataclass(frozen=True)
class EvaluationResult:
    actionable_probability: float | None
    staking_probability: float | None
    fair_price_american: int | None
    expected_value: float | None
    reliability: str
    uncertainty: float | None
    support_n: int
    evaluator_version: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    supported: bool = True
    reason: str | None = None

CANDIDATE_COLUMNS = (
    "game_id","season","week","kickoff_utc","market_type","selected_side",
    "primary_model","raw_model_output","corroborating_outputs",
    "sportsbook","line","american_odds","decimal_odds",
    "pinnacle_benchmark_line","pinnacle_benchmark_price_american","pinnacle_no_vig_probability",
    "actionable_probability","staking_probability","fair_price_american","expected_value",
    "reliability","uncertainty","evaluator_version","support_n","evidence",
    "football_model_version","market_snapshot_timestamp","evaluator_config_sha256",
)

def candidate_row(**kwargs: Any) -> dict[str, Any]:
    missing = [c for c in CANDIDATE_COLUMNS if c not in kwargs]
    extra = [k for k in kwargs if k not in CANDIDATE_COLUMNS]
    if missing or extra:
        raise ValueError(f"candidate schema mismatch missing={missing} extra={extra}")
    return {c: kwargs[c] for c in CANDIDATE_COLUMNS}

def as_safe_dict(obj: Any) -> dict[str, Any]:
    return asdict(obj)
