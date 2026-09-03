"""Canonical public/backend product and exact-offer validators V1."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from nfl_edge.contracts.common_v1 import (
    BOOKS,
    GAME_STATUSES,
    HEADLINE_STATES,
    LANES,
    MARKET_TYPES,
    MODEL_OUTPUT_STATUSES,
    PRODUCT_SCHEMA_VERSION,
    RETAIL_BOOKS,
    SLATE_STATUSES,
    SUPPORT_STATES,
    VERDICTS,
    ContractValidationError,
    require_enum,
    require_exact_keys,
    require_map,
    require_number,
    require_string,
    validate_american_odds,
    validate_probability,
    validate_units,
    validate_utc_timestamp,
    validate_warnings,
)
from nfl_edge.contracts.market_qb_v1 import (
    validate_freshness,
    validate_market_board,
    validate_qb_context,
)

TOP_LEVEL_REQUIRED = frozenset({
    "schema_version", "product_version", "generated_at_utc", "prediction_as_of_utc", "season", "week",
    "slate_status", "football_data_version", "qb_snapshot_version", "market_snapshot_version", "model_versions",
    "evaluator_versions", "selector_versions", "freshness", "stale", "warnings", "headlines", "games",
})


def _validate_boundary(value: Any, path: str) -> None:
    if value is None:
        return
    obj = require_map(value, path)
    require_exact_keys(obj, {"line", "price_american"}, path)
    if obj["line"] is not None:
        require_number(obj["line"], f"{path}.line")
    if obj["price_american"] is not None:
        validate_american_odds(obj["price_american"], f"{path}.price_american")


def validate_headline(value: Any, path: str = "headline") -> None:
    obj = require_map(value, path)
    required = {
        "lane", "state", "game_id", "matchup", "market", "selection", "book", "line", "american_odds",
        "model_probability", "trust_probability", "market_probability", "ev", "support", "reliability",
        "recommended_units", "play_through", "value_at", "warnings",
    }
    require_exact_keys(obj, required, path)
    require_enum(obj["lane"], LANES, f"{path}.lane")
    state = require_enum(obj["state"], HEADLINE_STATES, f"{path}.state")
    require_enum(obj["support"], SUPPORT_STATES, f"{path}.support")
    validate_warnings(obj["warnings"], f"{path}.warnings")
    for field in ("model_probability", "trust_probability", "market_probability"):
        validate_probability(obj[field], f"{path}.{field}")
    if obj["ev"] is not None:
        require_number(obj["ev"], f"{path}.ev")
    units = validate_units(obj["recommended_units"], f"{path}.recommended_units")
    if obj["reliability"] is not None:
        require_string(obj["reliability"], f"{path}.reliability")
    _validate_boundary(obj["play_through"], f"{path}.play_through")
    _validate_boundary(obj["value_at"], f"{path}.value_at")
    if obj["matchup"] is not None:
        matchup = require_map(obj["matchup"], f"{path}.matchup")
        require_exact_keys(matchup, {"away_team", "home_team"}, f"{path}.matchup")
        require_string(matchup["away_team"], f"{path}.matchup.away_team")
        require_string(matchup["home_team"], f"{path}.matchup.home_team")
    if state != "BET" and units > 0:
        raise ContractValidationError(f"{path}.recommended_units must be zero unless state=BET")
    if state == "BET":
        for field in ("game_id", "matchup", "market", "selection", "book", "american_odds"):
            if obj[field] is None:
                raise ContractValidationError(f"{path}.{field} is required for BET")
        require_string(obj["game_id"], f"{path}.game_id")
        require_enum(obj["market"], MARKET_TYPES, f"{path}.market")
        require_string(obj["selection"], f"{path}.selection")
        require_enum(obj["book"], BOOKS, f"{path}.book")
        validate_american_odds(obj["american_odds"], f"{path}.american_odds")
        if units <= 0:
            raise ContractValidationError(f"{path}.recommended_units must be positive for BET")
    else:
        if obj["market"] is not None:
            require_enum(obj["market"], MARKET_TYPES, f"{path}.market")
        if obj["book"] is not None:
            require_enum(obj["book"], BOOKS, f"{path}.book")
        if obj["american_odds"] is not None:
            validate_american_odds(obj["american_odds"], f"{path}.american_odds")


_ROOF_RESOLVED_OUTPUT_FIELDS = frozenset({
    "roof_resolution_status",
    "roof_selected_scenario",
    "xgboost_open_probability",
    "xgboost_closed_probability",
})
_ROOF_SCENARIO_OUTPUT_FIELDS = _ROOF_RESOLVED_OUTPUT_FIELDS | frozenset({
    "xgboost_scenario_delta",
    "roof_scenario_downstream",
})
_ROOF_SCENARIO_DOWNSTREAM_FIELDS = frozenset({
    "status", "agreement_status", "open_state", "closed_state", "shared_state"
})


def _validate_roof_scenario_downstream(value: Any, path: str) -> None:
    obj = require_map(value, path)
    require_exact_keys(obj, _ROOF_SCENARIO_DOWNSTREAM_FIELDS, path)
    status = require_enum(
        obj["status"],
        frozenset({"NOT_EVALUATED_MISSING_EVIDENCE", "EVALUATED", "ROOF_SENSITIVE"}),
        f"{path}.status",
    )
    agreement = require_enum(
        obj["agreement_status"],
        frozenset({"NOT_EVALUABLE", "AGREE", "ROOF_SENSITIVE"}),
        f"{path}.agreement_status",
    )
    for field in ("open_state", "closed_state", "shared_state"):
        if obj[field] is not None:
            require_map(obj[field], f"{path}.{field}")
    if status == "NOT_EVALUATED_MISSING_EVIDENCE":
        state_fields = ("open_state", "closed_state", "shared_state")
        if agreement != "NOT_EVALUABLE" or any(obj[field] is not None for field in state_fields):
            raise ContractValidationError(f"{path} missing-evidence state must not invent a downstream state")
    elif status == "EVALUATED":
        state_fields = ("open_state", "closed_state", "shared_state")
        if agreement != "AGREE" or any(obj[field] is None for field in state_fields):
            raise ContractValidationError(
                f"{path} evaluated agreement requires non-null open, closed, and shared states"
            )
        if obj["open_state"] != obj["closed_state"] or obj["shared_state"] != obj["open_state"]:
            raise ContractValidationError(
                f"{path} evaluated agreement requires open_state == closed_state == shared_state"
            )
    elif status == "ROOF_SENSITIVE":
        if agreement != "ROOF_SENSITIVE" or obj["open_state"] is None or obj["closed_state"] is None:
            raise ContractValidationError(
                f"{path} roof-sensitive state requires non-null open and closed states"
            )
        if obj["open_state"] == obj["closed_state"]:
            raise ContractValidationError(f"{path} roof-sensitive state requires open_state != closed_state")
        if obj["shared_state"] is not None:
            raise ContractValidationError(f"{path} roof-sensitive state must not expose a shared state")
    else:
        raise ContractValidationError(f"{path} unknown downstream status {status!r}")


def _validate_model_output(value: Any, path: str) -> None:
    obj = require_map(value, path)
    fields = {"status", "prediction", "support", "input_identity", "artifact_version", "warnings"}
    status_value = obj.get("status")
    has_roof_fields = bool(set(obj) & _ROOF_SCENARIO_OUTPUT_FIELDS)
    is_pending_roof = status_value == "AVAILABLE_WITH_ROOF_SCENARIOS"
    is_resolved_roof = status_value == "AVAILABLE" and has_roof_fields
    if is_pending_roof:
        required_keys = fields | _ROOF_SCENARIO_OUTPUT_FIELDS
    elif is_resolved_roof:
        required_keys = fields | _ROOF_RESOLVED_OUTPUT_FIELDS
    else:
        required_keys = fields
    require_exact_keys(obj, required_keys, path)
    status = require_enum(obj["status"], MODEL_OUTPUT_STATUSES, f"{path}.status")
    require_enum(obj["support"], SUPPORT_STATES, f"{path}.support")
    require_string(obj["input_identity"], f"{path}.input_identity")
    require_string(obj["artifact_version"], f"{path}.artifact_version")
    validate_warnings(obj["warnings"], f"{path}.warnings")
    if status == "AVAILABLE" and obj["prediction"] is None:
        raise ContractValidationError(f"{path}.prediction is required when status=AVAILABLE")
    if obj["prediction"] is not None:
        require_number(obj["prediction"], f"{path}.prediction")
    if is_pending_roof:
        if obj["prediction"] is not None or obj["support"] != "PARTIAL":
            raise ContractValidationError(
                f"{path} roof-scenario availability requires null prediction and PARTIAL support"
            )
        if obj["roof_resolution_status"] != "PENDING" or obj["roof_selected_scenario"] is not None:
            raise ContractValidationError(f"{path} roof-scenario availability requires pending unselected roof state")
        validate_probability(obj["xgboost_open_probability"], f"{path}.xgboost_open_probability")
        validate_probability(obj["xgboost_closed_probability"], f"{path}.xgboost_closed_probability")
        require_number(obj["xgboost_scenario_delta"], f"{path}.xgboost_scenario_delta", -1.0, 1.0)
        _validate_roof_scenario_downstream(obj["roof_scenario_downstream"], f"{path}.roof_scenario_downstream")
    elif is_resolved_roof:
        if obj["support"] != "SUPPORTED":
            raise ContractValidationError(f"{path} resolved roof availability requires SUPPORTED support")
        roof_status = require_enum(
            obj["roof_resolution_status"], frozenset({"OPEN", "CLOSED"}), f"{path}.roof_resolution_status"
        )
        selected = require_enum(
            obj["roof_selected_scenario"], frozenset({"open", "closed"}), f"{path}.roof_selected_scenario"
        )
        expected_selected = roof_status.lower()
        if selected != expected_selected:
            raise ContractValidationError(f"{path}.roof_selected_scenario must match resolved roof status")
        open_probability = validate_probability(obj["xgboost_open_probability"], f"{path}.xgboost_open_probability")
        closed_probability = validate_probability(obj["xgboost_closed_probability"], f"{path}.xgboost_closed_probability")
        selected_probability = open_probability if selected == "open" else closed_probability
        if obj["prediction"] != selected_probability:
            raise ContractValidationError(f"{path}.prediction must equal the selected resolved roof scenario")


def validate_game(value: Any, path: str = "game") -> None:
    obj = require_map(value, path)
    required = {
        "game_id", "season", "week", "home_team", "away_team", "kickoff_at_utc", "game_status", "venue",
        "neutral_site", "updated_at_utc", "quarterbacks", "market_board", "football_outputs", "warnings",
    }
    require_exact_keys(obj, required, path)
    game_id = require_string(obj["game_id"], f"{path}.game_id")
    if not isinstance(obj["season"], int) or isinstance(obj["season"], bool):
        raise ContractValidationError(f"{path}.season must be an integer")
    if not isinstance(obj["week"], int) or isinstance(obj["week"], bool) or obj["week"] < 1:
        raise ContractValidationError(f"{path}.week must be a positive integer")
    require_string(obj["home_team"], f"{path}.home_team")
    require_string(obj["away_team"], f"{path}.away_team")
    validate_utc_timestamp(obj["kickoff_at_utc"], f"{path}.kickoff_at_utc")
    validate_utc_timestamp(obj["updated_at_utc"], f"{path}.updated_at_utc")
    require_enum(obj["game_status"], GAME_STATUSES, f"{path}.game_status")
    if obj["venue"] is not None:
        require_string(obj["venue"], f"{path}.venue")
    if not isinstance(obj["neutral_site"], bool):
        raise ContractValidationError(f"{path}.neutral_site must be boolean")
    validate_warnings(obj["warnings"], f"{path}.warnings")
    qbs = require_map(obj["quarterbacks"], f"{path}.quarterbacks")
    require_exact_keys(qbs, {"home", "away"}, f"{path}.quarterbacks")
    validate_qb_context(qbs["home"], f"{path}.quarterbacks.home")
    validate_qb_context(qbs["away"], f"{path}.quarterbacks.away")
    if qbs["home"]["team"] != obj["home_team"] or qbs["away"]["team"] != obj["away_team"]:
        raise ContractValidationError(f"{path}.quarterbacks team identities must match game teams")
    validate_market_board(obj["market_board"], game_id, f"{path}.market_board")
    outputs = require_map(obj["football_outputs"], f"{path}.football_outputs")
    output_fields = {
        "prediction_as_of_utc", "provenance_id", "qb_elo", "xgboost_v2", "expected_margin", "ridge_totals_r4"
    }
    require_exact_keys(outputs, output_fields, f"{path}.football_outputs")
    validate_utc_timestamp(outputs["prediction_as_of_utc"], f"{path}.football_outputs.prediction_as_of_utc")
    require_string(outputs["provenance_id"], f"{path}.football_outputs.provenance_id")
    for model in ("qb_elo", "xgboost_v2", "expected_margin", "ridge_totals_r4"):
        _validate_model_output(outputs[model], f"{path}.football_outputs.{model}")


def validate_product_snapshot(payload: Any) -> dict[str, Any]:
    obj = require_map(payload, "product")
    require_exact_keys(obj, TOP_LEVEL_REQUIRED, "product")
    if obj["schema_version"] != PRODUCT_SCHEMA_VERSION:
        raise ContractValidationError(f"product.schema_version must equal {PRODUCT_SCHEMA_VERSION}")
    require_string(obj["product_version"], "product.product_version")
    validate_utc_timestamp(obj["generated_at_utc"], "product.generated_at_utc")
    validate_utc_timestamp(obj["prediction_as_of_utc"], "product.prediction_as_of_utc")
    generated = datetime.fromisoformat(obj["generated_at_utc"][:-1] + "+00:00")
    prediction = datetime.fromisoformat(obj["prediction_as_of_utc"][:-1] + "+00:00")
    if generated < prediction:
        raise ContractValidationError("product.generated_at_utc cannot precede prediction_as_of_utc")
    if not isinstance(obj["season"], int) or isinstance(obj["season"], bool):
        raise ContractValidationError("product.season must be an integer")
    if not isinstance(obj["week"], int) or isinstance(obj["week"], bool) or obj["week"] < 1:
        raise ContractValidationError("product.week must be a positive integer")
    require_enum(obj["slate_status"], SLATE_STATUSES, "product.slate_status")
    for field in ("football_data_version", "qb_snapshot_version", "market_snapshot_version"):
        require_string(obj[field], f"product.{field}")
    for field in ("model_versions", "evaluator_versions", "selector_versions"):
        versions = require_map(obj[field], f"product.{field}")
        if not versions:
            raise ContractValidationError(f"product.{field} must not be empty")
        for key, version in versions.items():
            require_string(str(key), f"product.{field}.key")
            require_string(version, f"product.{field}.{key}")
    validate_freshness(obj["freshness"], "product.freshness")
    if not isinstance(obj["stale"], bool):
        raise ContractValidationError("product.stale must be boolean")
    if obj["stale"] != (obj["freshness"]["state"] == "STALE"):
        raise ContractValidationError("product.stale must agree with product.freshness.state")
    validate_warnings(obj["warnings"], "product.warnings")
    headlines = require_map(obj["headlines"], "product.headlines")
    require_exact_keys(headlines, {"hit_rate", "balanced", "value"}, "product.headlines")
    for key, lane in (("hit_rate", "HIT_RATE"), ("balanced", "BALANCED"), ("value", "VALUE")):
        validate_headline(headlines[key], f"product.headlines.{key}")
        if headlines[key]["lane"] != lane:
            raise ContractValidationError(f"product.headlines.{key}.lane must equal {lane}")
    if not isinstance(obj["games"], list):
        raise ContractValidationError("product.games must be an array")
    seen: set[str] = set()
    for index, game in enumerate(obj["games"]):
        validate_game(game, f"product.games[{index}]")
        if game["game_id"] in seen:
            raise ContractValidationError(f"product.games[{index}].game_id is duplicated")
        seen.add(str(game["game_id"]))
    return deepcopy(dict(obj))


def validate_exact_offer_request(payload: Any) -> dict[str, Any]:
    obj = require_map(payload, "request")
    required = {"game_id", "market_type", "selection", "book", "line", "price"}
    require_exact_keys(obj, required, "request")
    require_string(obj["game_id"], "request.game_id")
    market = require_enum(obj["market_type"], MARKET_TYPES, "request.market_type")
    require_string(obj["selection"], "request.selection")
    require_enum(obj["book"], RETAIL_BOOKS, "request.book")
    if market == "MONEYLINE":
        if obj["line"] is not None:
            raise ContractValidationError("request.line must be null for MONEYLINE")
    else:
        require_number(obj["line"], "request.line")
    validate_american_odds(obj["price"], "request.price")
    return deepcopy(dict(obj))


def validate_exact_offer_response(payload: Any) -> dict[str, Any]:
    obj = require_map(payload, "response")
    required = {
        "supported", "probability", "trust_probability", "break_even_probability", "ev", "verdict",
        "recommended_units", "play_through", "value_at", "warnings",
    }
    require_exact_keys(obj, required, "response")
    if not isinstance(obj["supported"], bool):
        raise ContractValidationError("response.supported must be boolean")
    for field in ("probability", "trust_probability", "break_even_probability"):
        validate_probability(obj[field], f"response.{field}")
    if obj["ev"] is not None:
        require_number(obj["ev"], "response.ev")
    require_enum(obj["verdict"], VERDICTS, "response.verdict")
    validate_units(obj["recommended_units"], "response.recommended_units")
    _validate_boundary(obj["play_through"], "response.play_through")
    _validate_boundary(obj["value_at"], "response.value_at")
    validate_warnings(obj["warnings"], "response.warnings")
    return deepcopy(dict(obj))