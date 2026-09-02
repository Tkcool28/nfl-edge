"""NFL EDGE live product/backend contract V1 public import surface."""
from nfl_edge.contracts.common_v1 import (
    BOOKS,
    EXACT_OFFER_SCHEMA_VERSION,
    FRESHNESS_STATES,
    HEADLINE_STATES,
    LIVE_SCORER_SCHEMA_VERSION,
    MARKET_SCHEMA_VERSION,
    PRODUCT_SCHEMA_VERSION,
    QB_RESOLVER_SCHEMA_VERSION,
    USER_STATE_SCHEMA_VERSION,
    ContractValidationError,
)
from nfl_edge.contracts.market_qb_v1 import (
    validate_freshness,
    validate_market_offer,
    validate_qb_context,
)
from nfl_edge.contracts.product_api_v1 import (
    validate_exact_offer_request,
    validate_exact_offer_response,
    validate_game,
    validate_headline,
    validate_product_snapshot,
)
from nfl_edge.contracts.runtime_interfaces_v1 import (
    ExpectedQBResolution,
    LiveScorerRequest,
    QBOverrideAudit,
    QBStarterChangeEvent,
)
from nfl_edge.contracts.user_state_v1 import (
    RISK_PROFILES,
    UserProfileState,
    profile_update_preserves_recommendation,
    user_specific_stake,
)

API_ENDPOINTS = {
    "GET /api/v1/health": (
        "health and last-refresh metadata; may be stale while prior valid product remains served"
    ),
    "GET /api/v1/product/latest": "latest complete validated NFL_EDGE_PRODUCT_API_V1 snapshot",
    "GET /api/v1/games": "game board from latest complete product snapshot",
    "GET /api/v1/games/{game_id}": "one game from latest complete product snapshot or 404",
    "POST /api/v1/evaluate-offer": "one exact offer through the existing frozen evaluator/product-policy path",
    "GET /api/v1/profile": "persistent NFL_EDGE_USER_STATE_V1",
    "PUT /api/v1/profile": (
        "validated bankroll/risk-profile replacement; units and model/evaluator outputs stay unchanged"
    ),
}

__all__ = [
    "API_ENDPOINTS",
    "BOOKS",
    "ContractValidationError",
    "EXACT_OFFER_SCHEMA_VERSION",
    "ExpectedQBResolution",
    "FRESHNESS_STATES",
    "HEADLINE_STATES",
    "LIVE_SCORER_SCHEMA_VERSION",
    "LiveScorerRequest",
    "MARKET_SCHEMA_VERSION",
    "PRODUCT_SCHEMA_VERSION",
    "QBOverrideAudit",
    "QBStarterChangeEvent",
    "QB_RESOLVER_SCHEMA_VERSION",
    "RISK_PROFILES",
    "USER_STATE_SCHEMA_VERSION",
    "UserProfileState",
    "profile_update_preserves_recommendation",
    "user_specific_stake",
    "validate_exact_offer_request",
    "validate_exact_offer_response",
    "validate_freshness",
    "validate_game",
    "validate_headline",
    "validate_market_offer",
    "validate_product_snapshot",
    "validate_qb_context",
]
