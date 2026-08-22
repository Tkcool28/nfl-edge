"""Safe serialization for frozen Task05F evaluator state."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import MoneylineV4State, PointV3State, ReliabilityState, SupportFeature


def _features_to_dict(features: tuple[SupportFeature, ...]) -> list[dict[str, Any]]:
    return [
        {
            "name": feature.name,
            "min_value": float(feature.min_value),
            "max_value": float(feature.max_value),
            "span": float(feature.span),
        }
        for feature in features
    ]


def _features_from_dict(rows: list[dict[str, Any]]) -> tuple[SupportFeature, ...]:
    return tuple(
        SupportFeature(
            str(row["name"]),
            float(row["min_value"]),
            float(row["max_value"]),
            float(row["span"]),
        )
        for row in rows
    )


def moneyline_state_to_dict(state: MoneylineV4State) -> dict[str, Any]:
    return {
        "market_type": "moneyline",
        "version": state.version,
        "market_intercept": float(state.market_intercept),
        "market_slope": float(state.market_slope),
        "model_weight": float(state.model_weight),
        "training_n": int(state.training_n),
        "prior_ties": int(state.prior_ties),
        "prior_games": int(state.prior_games),
        "support_features": _features_to_dict(state.support_features),
        "config_sha256": state.config_sha256,
    }


def point_state_to_dict(state: PointV3State) -> dict[str, Any]:
    return {
        "market_type": state.market_type,
        "version": state.version,
        "sigma": float(state.sigma),
        "beta": float(state.beta),
        "training_n": int(state.training_n),
        "residuals": [float(value) for value in state.residuals],
        "support_features": _features_to_dict(state.support_features),
        "config_sha256": state.config_sha256,
    }


def reliability_state_to_dict(state: ReliabilityState) -> dict[str, Any]:
    return {
        "radius": None if state.radius is None else float(state.radius),
        "support_n": int(state.support_n),
        "block_count": int(state.block_count),
        "stable": bool(state.stable),
    }


def moneyline_state_from_dict(row: dict[str, Any]) -> MoneylineV4State:
    return MoneylineV4State(
        market_intercept=float(row["market_intercept"]),
        market_slope=float(row["market_slope"]),
        model_weight=float(row["model_weight"]),
        training_n=int(row["training_n"]),
        prior_ties=int(row["prior_ties"]),
        prior_games=int(row["prior_games"]),
        support_features=_features_from_dict(row["support_features"]),
        config_sha256=str(row["config_sha256"]),
        version=str(row.get("version", "ml_v4")),
    )


def point_state_from_dict(row: dict[str, Any]) -> PointV3State:
    return PointV3State(
        market_type=str(row["market_type"]),
        sigma=float(row["sigma"]),
        beta=float(row["beta"]),
        residuals=tuple(float(value) for value in row["residuals"]),
        training_n=int(row["training_n"]),
        support_features=_features_from_dict(row["support_features"]),
        config_sha256=str(row["config_sha256"]),
        version=str(row.get("version", f"{row['market_type']}_v3")),
    )


def reliability_state_from_dict(row: dict[str, Any]) -> ReliabilityState:
    return ReliabilityState(
        None if row.get("radius") is None else float(row["radius"]),
        int(row["support_n"]),
        int(row["block_count"]),
        bool(row["stable"]),
    )


def write_frozen_state(
    path: Path,
    *,
    moneyline: MoneylineV4State,
    spread: PointV3State,
    total: PointV3State,
    reliability: dict[str, ReliabilityState],
    metadata: dict[str, Any],
) -> None:
    payload = {
        "schema_version": "task05f_frozen_evaluator_state_v1",
        "metadata": metadata,
        "evaluators": {
            "moneyline": moneyline_state_to_dict(moneyline),
            "spread": point_state_to_dict(spread),
            "total": point_state_to_dict(total),
        },
        "reliability": {
            market: reliability_state_to_dict(reliability[market])
            for market in ("moneyline", "spread", "total")
        },
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")


def load_frozen_state(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if payload.get("schema_version") != "task05f_frozen_evaluator_state_v1":
        raise ValueError("unsupported evaluator-state schema")
    return {
        "metadata": payload["metadata"],
        "moneyline": moneyline_state_from_dict(payload["evaluators"]["moneyline"]),
        "spread": point_state_from_dict(payload["evaluators"]["spread"]),
        "total": point_state_from_dict(payload["evaluators"]["total"]),
        "reliability": {
            market: reliability_state_from_dict(payload["reliability"][market])
            for market in ("moneyline", "spread", "total")
        },
    }
