"""Corrected HHR-only staking audit using frozen selector_trust. Does not select wagers."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping

MIN_UNITS = 0.25
WARNING_PRESSURE = 0.08

@dataclass(frozen=True)
class HHRStake:
    base_units: float
    price_pressure: float
    haircut_units: float
    recommended_units: float
    heavily_juiced: bool


def _f(row: Mapping[str, Any], key: str) -> float:
    v = row.get(key)
    if v is None:
        raise ValueError(f"missing {key}")
    return float(v)


def base_units(selector_trust: float) -> float:
    q = float(selector_trust)
    if q >= 0.70:
        return 1.25
    if q >= 0.65:
        return 1.00
    if q >= 0.60:
        return 0.75
    return 0.50


def hhr_stake(row: Mapping[str, Any]) -> HHRStake:
    if not bool(row.get("supported")) or not bool(row.get("model_confidence_supported")):
        raise ValueError("HHR staking audit requires a supported already-selected HHR row")
    trust = _f(row, "selector_trust")
    be = _f(row, "break_even_probability")
    pressure = be - trust
    base = base_units(trust)
    if pressure <= 0.0:
        haircut = 0.0
        units = base
    elif pressure <= 0.04:
        haircut = 0.25
        units = max(MIN_UNITS, base - haircut)
    elif pressure <= 0.08:
        haircut = 0.50
        units = max(MIN_UNITS, base - haircut)
    elif pressure <= 0.10:
        haircut = 0.75
        units = max(MIN_UNITS, base - haircut)
    else:
        haircut = max(0.0, base - MIN_UNITS)
        units = MIN_UNITS
    return HHRStake(base, pressure, haircut, units, pressure >= WARNING_PRESSURE)
