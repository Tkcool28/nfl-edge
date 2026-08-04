"""Canonical QB-Elo configuration loader.

Single source of truth for the primary QB-Elo run. Reads
``config/qb_elo_v1.yaml`` and normalizes nested YAML fields into the
flat runtime keys consumed by :class:`nfl_edge.models.qb_elo.EloConfig`.

The canonical normalized dictionary is:

- validated against required keys (unknown keys are rejected);
- validated against missing keys (a required key absent raises);
- validated against numeric ranges (out-of-range raises);
- sorted deterministically (so the SHA-256 is stable);
- used by the walk-forward runtime;
- used by the tuning ledger;
- used by replay and scorecard configuration reporting.

The runtime has no independent defaults; the loader is the only
authoritative source of the primary configuration values.

Mapping
-------

YAML nested fields are flattened to runtime keys:

- ``initial_rating``                  -> ``initial_rating``
- ``home_field_elo``                  -> ``home_field_elo``
- ``k_factor_regular``                -> ``k_factor_regular``
- ``k_factor_postseason``             -> ``k_factor_postseason``
- ``season_mean_reversion_fraction``  -> ``season_mean_reversion_fraction``
- ``margin_of_victory.divisor``       -> ``mov_divisor``
- ``margin_of_victory.cap``           -> ``mov_cap``
- ``probability.min``                 -> ``prob_min``
- ``probability.max``                 -> ``prob_max``
- ``qb_adjustment.scale_elo_per_shrunk_epa``         -> ``qb_adjustment_scale_elo_per_shrunk_epa``
- ``qb_adjustment.max_abs_elo``                      -> ``qb_adjustment_max_abs_elo``
- ``qb_adjustment.replacement_passing_epa``          -> ``qb_adjustment_replacement_passing_epa``
- ``qb_adjustment.sample_k``                         -> ``qb_adjustment_sample_k``
- ``qb_adjustment.unknown_returns_zero``             -> ``qb_adjustment_unknown_returns_zero``
- ``qb_adjustment.supported_uses_replacement_scenario`` -> ``qb_adjustment_supported_uses_replacement_scenario``
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from .qb_elo import EloConfig

from ..common.errors import ConfigurationError

# Required top-level YAML keys. Unknown keys are rejected.
_REQUIRED_TOP_KEYS: frozenset[str] = frozenset(
    {
        "initial_rating",
        "home_field_elo",
        "k_factor_regular",
        "k_factor_postseason",
        "season_mean_reversion_fraction",
        "margin_of_victory",
        "probability",
        "qb_adjustment",
    }
)

# Required nested keys (all must be present in their parent dict).
_REQUIRED_MOV_KEYS: frozenset[str] = frozenset({"divisor", "cap"})
_REQUIRED_PROB_KEYS: frozenset[str] = frozenset({"min", "max"})
_REQUIRED_QB_KEYS: frozenset[str] = frozenset(
    {
        "scale_elo_per_shrunk_epa",
        "max_abs_elo",
        "replacement_passing_epa",
        "sample_k",
        "unknown_returns_zero",
        "supported_uses_replacement_scenario",
    }
)

# Numeric ranges for the keys that have well-defined ranges.
_NUMERIC_RANGES: dict[str, tuple[float, float]] = {
    "initial_rating": (0.0, 5000.0),
    "home_field_elo": (0.0, 200.0),
    "k_factor_regular": (0.0, 100.0),
    "k_factor_postseason": (0.0, 100.0),
    "season_mean_reversion_fraction": (0.0, 1.0),
    "mov_divisor": (0.1, 100.0),
    "mov_cap": (0.0, 10.0),
    "prob_min": (1e-9, 0.5),
    "prob_max": (0.5, 1.0 - 1e-9),
    "qb_adjustment_scale_elo_per_shrunk_epa": (0.0, 5000.0),
    "qb_adjustment_max_abs_elo": (0.0, 500.0),
    "qb_adjustment_replacement_passing_epa": (-5.0, 5.0),
    "qb_adjustment_sample_k": (1.0, 10000.0),
}


def _check_num(name: str, value: Any) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigurationError(
            f"qb_elo_v1.yaml: {name} must be numeric, got {type(value).__name__}"
        )
    fv = float(value)
    lo, hi = _NUMERIC_RANGES[name]
    if not (lo <= fv <= hi):
        raise ConfigurationError(
            f"qb_elo_v1.yaml: {name}={fv} out of range [{lo}, {hi}]"
        )


def _check_bool(name: str, value: Any) -> None:
    if not isinstance(value, bool):
        raise ConfigurationError(
            f"qb_elo_v1.yaml: {name} must be boolean, got {type(value).__name__}"
        )


def load_qb_elo_canonical_config(
    yaml_path: str | Path,
) -> dict[str, Any]:
    """Load and normalize the canonical QB-Elo configuration.

    Returns a sorted, fully-validated dictionary with the runtime key
    names. The returned dictionary is the single source of truth that
    the walk-forward runtime, tuning ledger, replay, and scorecard all
    read from. SHA-256 of the canonical JSON is the model config hash.
    """
    p = Path(yaml_path)
    if not p.is_file():
        raise ConfigurationError(f"qb_elo_v1.yaml not found at {p}")
    raw = yaml.safe_load(p.read_text())
    if not isinstance(raw, dict):
        raise ConfigurationError(
            f"qb_elo_v1.yaml: top-level must be a mapping, got {type(raw).__name__}"
        )
    # Reject unknown top-level keys.
    unknown_top = set(raw.keys()) - _REQUIRED_TOP_KEYS
    if unknown_top:
        raise ConfigurationError(
            f"qb_elo_v1.yaml: unknown top-level keys: {sorted(unknown_top)}"
        )
    # All required top-level keys must be present.
    missing_top = _REQUIRED_TOP_KEYS - set(raw.keys())
    if missing_top:
        raise ConfigurationError(
            f"qb_elo_v1.yaml: missing top-level keys: {sorted(missing_top)}"
        )

    normalized: dict[str, Any] = {}

    # Scalars
    for name in (
        "initial_rating",
        "home_field_elo",
        "k_factor_regular",
        "k_factor_postseason",
        "season_mean_reversion_fraction",
    ):
        _check_num(name, raw[name])
        normalized[name] = float(raw[name])

    # Nested margin_of_victory -> mov_divisor, mov_cap
    mov = raw["margin_of_victory"]
    if not isinstance(mov, dict):
        raise ConfigurationError(
            "qb_elo_v1.yaml: margin_of_victory must be a mapping"
        )
    unknown_mov = set(mov.keys()) - _REQUIRED_MOV_KEYS
    if unknown_mov:
        raise ConfigurationError(
            f"qb_elo_v1.yaml: unknown margin_of_victory keys: {sorted(unknown_mov)}"
        )
    missing_mov = _REQUIRED_MOV_KEYS - set(mov.keys())
    if missing_mov:
        raise ConfigurationError(
            f"qb_elo_v1.yaml: missing margin_of_victory keys: {sorted(missing_mov)}"
        )
    _check_num("mov_divisor", mov["divisor"])
    _check_num("mov_cap", mov["cap"])
    normalized["mov_divisor"] = float(mov["divisor"])
    normalized["mov_cap"] = float(mov["cap"])

    # Nested probability -> prob_min, prob_max
    prob = raw["probability"]
    if not isinstance(prob, dict):
        raise ConfigurationError(
            "qb_elo_v1.yaml: probability must be a mapping"
        )
    unknown_prob = set(prob.keys()) - _REQUIRED_PROB_KEYS
    if unknown_prob:
        raise ConfigurationError(
            f"qb_elo_v1.yaml: unknown probability keys: {sorted(unknown_prob)}"
        )
    missing_prob = _REQUIRED_PROB_KEYS - set(prob.keys())
    if missing_prob:
        raise ConfigurationError(
            f"qb_elo_v1.yaml: missing probability keys: {sorted(missing_prob)}"
        )
    _check_num("prob_min", prob["min"])
    _check_num("prob_max", prob["max"])
    if prob["min"] >= prob["max"]:
        raise ConfigurationError(
            f"qb_elo_v1.yaml: probability.min ({prob['min']}) must be < probability.max ({prob['max']})"
        )
    normalized["prob_min"] = float(prob["min"])
    normalized["prob_max"] = float(prob["max"])

    # Nested qb_adjustment -> qb_adjustment_*
    qb = raw["qb_adjustment"]
    if not isinstance(qb, dict):
        raise ConfigurationError(
            "qb_elo_v1.yaml: qb_adjustment must be a mapping"
        )
    unknown_qb = set(qb.keys()) - _REQUIRED_QB_KEYS
    if unknown_qb:
        raise ConfigurationError(
            f"qb_elo_v1.yaml: unknown qb_adjustment keys: {sorted(unknown_qb)}"
        )
    missing_qb = _REQUIRED_QB_KEYS - set(qb.keys())
    if missing_qb:
        raise ConfigurationError(
            f"qb_elo_v1.yaml: missing qb_adjustment keys: {sorted(missing_qb)}"
        )
    _check_num("qb_adjustment_scale_elo_per_shrunk_epa", qb["scale_elo_per_shrunk_epa"])
    _check_num("qb_adjustment_max_abs_elo", qb["max_abs_elo"])
    _check_num("qb_adjustment_replacement_passing_epa", qb["replacement_passing_epa"])
    _check_num("qb_adjustment_sample_k", qb["sample_k"])
    normalized["qb_adjustment_scale_elo_per_shrunk_epa"] = float(
        qb["scale_elo_per_shrunk_epa"]
    )
    normalized["qb_adjustment_max_abs_elo"] = float(qb["max_abs_elo"])
    normalized["qb_adjustment_replacement_passing_epa"] = float(
        qb["replacement_passing_epa"]
    )
    normalized["qb_adjustment_sample_k"] = float(qb["sample_k"])
    _check_bool("qb_adjustment_unknown_returns_zero", qb["unknown_returns_zero"])
    _check_bool(
        "qb_adjustment_supported_uses_replacement_scenario",
        qb["supported_uses_replacement_scenario"],
    )
    normalized["qb_adjustment_unknown_returns_zero"] = bool(
        qb["unknown_returns_zero"]
    )
    normalized["qb_adjustment_supported_uses_replacement_scenario"] = bool(
        qb["supported_uses_replacement_scenario"]
    )

    # Sort deterministically by key.
    return dict(sorted(normalized.items()))


def canonical_config_sha256(normalized_config: dict[str, Any]) -> str:
    """Return the SHA-256 of the canonical JSON of the normalized config.

    The canonical JSON is ``json.dumps(d, sort_keys=True, separators=(",", ":"))``
    so the result is byte-stable across runs and operating systems.
    """
    payload = json.dumps(
        normalized_config, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_qb_elo_canonical_config_with_hash(
    yaml_path: str | Path,
) -> tuple[dict[str, Any], str]:
    """Convenience: load + compute hash in one call.

    Returns ``(normalized_config, sha256)``.
    """
    cfg = load_qb_elo_canonical_config(yaml_path)
    return cfg, canonical_config_sha256(cfg)


def canonical_config_to_elo_config_input(
    normalized_config: dict[str, Any],
) -> dict[str, Any]:
    """Convert a canonical normalized config into the input shape
    expected by :func:`nfl_edge.models.qb_elo.config_from_dict`.

    The canonical loader produces flat ``qb_adjustment_*`` keys. The
    Elo construction API expects a single ``qb_adjustment`` mapping
    nested under that key. This helper does that nested-grouping
    conversion without ever introducing a different value.
    """
    out: dict[str, Any] = dict(normalized_config)
    # Remove the flat qb_adjustment_* keys and group them under
    # ``qb_adjustment`` in the nested shape that config_from_dict
    # expects.
    qb_nested: dict[str, Any] = {}
    flat_qb_keys = [
        k for k in out if k.startswith("qb_adjustment_")
    ]
    for k in flat_qb_keys:
        v = out.pop(k)
        suffix = k[len("qb_adjustment_"):]
        qb_nested[suffix] = v
    if qb_nested:
        out["qb_adjustment"] = qb_nested
    return out


def canonical_config_to_eloconfig(
    normalized_config: dict[str, Any],
) -> "EloConfig":
    """Build an :class:`EloConfig` from a canonical normalized config.

    Unlike :func:`canonical_config_to_elo_config_input`, this
    function returns a fully-constructed :class:`EloConfig` with the
    nested ``QBAdjustmentConfig`` field properly instantiated. Used
    by tests that need to access ``elo.qb_adjustment.scale_...``
    attributes directly.
    """
    from .qb_elo import config_from_dict
    return config_from_dict(
        canonical_config_to_elo_config_input(normalized_config)
    )
