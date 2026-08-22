#!/usr/bin/env python3
"""Task05F Phase F v1.1 exact-offer staking-anchor correction.

This runner reuses the preregistered/audited Phase F v1 chronology, uncertainty,
reliability, immutable evaluator gates, diagnostics, and output contract. The
ONLY wagering-semantic override is the point-market staking anchor: Pinnacle's
V3 line+price distribution is translated to the actionable DK/FD wager's own
exact line before evaluator edge is conservatively shrunk for bankroll sizing.

The superseded Phase F v1 historical run was invalidated before result
inspection. Locked V3/V4 evaluator probabilities, fair price, strict EV, Value,
support, and all frozen football models remain unchanged. 2025 remains sealed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

from nfl_edge.value.locked_reliability import exact_point_market_anchor_probability
from nfl_edge.value.wager_economics import line_allows_push


ROOT = Path(__file__).resolve().parents[1]
DEV = [2020, 2021, 2022, 2023, 2024]
SEALED = {2025}
VERSION = "task05f_reliability_uncertainty_v1_1"
PREREG = ROOT / "config" / "task05f_reliability_uncertainty_v1_1_prereg.yaml"
BASE_RUNNER = ROOT / "scripts" / "task05f_reliability_uncertainty_v1_runner.py"


def _load_base():
    spec = importlib.util.spec_from_file_location(
        "task05f_phase_f_v1_runtime_for_v1_1", BASE_RUNNER
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load Phase F v1 runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = _load_base()


def _exact_offer_market_anchor(row: dict[str, Any]) -> float | None:
    market = str(row["market_type"])
    side = str(row["selected_side"]).lower()

    if market == "moneyline":
        value = row.get("calibrated_market_probability")
        return None if value is None else float(value)

    pin_threshold = row.get("pinnacle_anchor_threshold")
    pin_probability = row.get("pinnacle_anchor_probability")
    market_scale = row.get("market_scale")
    line = row.get("line")
    if any(value is None for value in (pin_threshold, pin_probability, market_scale, line)):
        return None

    action_line = float(line)
    if market == "spread":
        if side == "home":
            actionable_threshold = -action_line
            direction = "above"
        elif side == "away":
            actionable_threshold = action_line
            direction = "below"
        else:
            raise ValueError(f"unknown spread side {side}")
    elif market == "total":
        actionable_threshold = action_line
        if side == "over":
            direction = "above"
        elif side == "under":
            direction = "below"
        else:
            raise ValueError(f"unknown total side {side}")
    else:
        raise ValueError(f"unknown market {market}")

    return exact_point_market_anchor_probability(
        float(pin_threshold),
        float(pin_probability),
        float(market_scale),
        actionable_threshold,
        direction,
        push_possible=line_allows_push(action_line),
    )


def _canonical_immutable_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare immutable evaluator rows independent of Phase F processing order.

    The locked component board historically sorts the string ``week`` field,
    while Phase F intentionally processes zero-padded season-week blocks in true
    chronology. The identity and immutable values must match, but list position
    is not itself an evaluator field.
    """
    fields = list(BASE.IDENTITY_FIELDS) + list(BASE.IMMUTABLE_FIELDS)
    payload = [{field: row.get(field) for field in fields} for row in rows]
    payload.sort(
        key=lambda item: json.dumps(
            {field: item.get(field) for field in BASE.IDENTITY_FIELDS},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return payload


def run(root: Path, config_path: Path, out: Path) -> None:
    # Patch only the downstream market-anchor semantic and order-independent
    # reproduction proof. No evaluator/probability function is replaced.
    BASE._market_anchor = _exact_offer_market_anchor
    BASE._immutable_payload = _canonical_immutable_payload
    BASE.VERSION = VERSION
    BASE.run(root, config_path, out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(PREREG))
    parser.add_argument(
        "--out", default=str(ROOT / "artifacts" / "task05f" / "reliability_v1_1")
    )
    args = parser.parse_args()
    run(ROOT, Path(args.config), Path(args.out))
