"""Canonical Expected-Margin v1 configuration loader.

Single source of truth for the three locked Task 03B candidate
configurations. Reads ``config/expected_margin_v1.yaml`` and produces
a deterministic, fully-validated dictionary per candidate.

The loader enforces:

- exactly three candidates, with ids drawn from the closed set
  ``{"responsive", "balanced", "stable"}``;
- a fixed, deterministic candidate order (responsive, balanced, stable);
- no unknown keys at any level;
- every parameter required by the spec is present.

The runtime has no in-code defaults: every parameter it consults
originates here. The locked ``configuration_sha256`` is the SHA-256
of the canonical JSON of the three flattened candidate dictionaries
plus the shared parameters in the fixed order, computed
deterministically and used to pin the configuration in the tuning
ledger.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from ..common.errors import ConfigurationError

_REQUIRED_TOP_KEYS: frozenset[str] = frozenset({"shared", "candidates"})
_REQUIRED_SHARED_KEYS: frozenset[str] = frozenset(
    {
        "league_baseline_prior",
        "probability_min",
        "probability_max",
        "mapping_intercept_l2_prior",
        "mapping_slope_l2_prior",
        "mapping_solver_tolerance",
        "mapping_solver_max_iterations",
        "tie_policy",
        "minimum_training_games",
        "minimum_mapping_rows",
        "apply_probability_clipping",
        "reject_nonpositive_slope",
        "maximum_development_season",
    }
)
_REQUIRED_CANDIDATE_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "offense_ridge",
        "defense_ridge",
        "home_field_ridge",
        "recency_half_life_games",
        "mapping_intercept_l2_weight",
        "mapping_slope_l2_weight",
    }
)
_CANDIDATE_ORDER: tuple[str, ...] = ("responsive", "balanced", "stable")


def _check_num(name: str, value: Any, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(
            f"expected_margin_v1.yaml: {name} must be numeric, got {type(value).__name__}"
        )
    fv = float(value)
    if not (lo <= fv <= hi):
        raise ConfigurationError(
            f"expected_margin_v1.yaml: {name}={fv} out of range [{lo}, {hi}]"
        )
    return fv


def _check_bool(name: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ConfigurationError(
            f"expected_margin_v1.yaml: {name} must be boolean, got {type(value).__name__}"
        )
    return value


def _check_enum(name: str, value: Any, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ConfigurationError(
            f"expected_margin_v1.yaml: {name} must be one of {allowed}, got {value!r}"
        )
    return value


def load_expected_margin_canonical_config(
    yaml_path: str | Path,
) -> dict[str, Any]:
    """Load and normalize the canonical Expected-Margin v1 configuration.

    Returns a sorted, fully-validated dictionary with the runtime key
    names. The returned dictionary has the following shape::

        {
            "shared": {
                "league_baseline_prior": float,
                "probability_min": float,
                "probability_max": float,
                "mapping_intercept_l2_prior": float,
                "mapping_slope_l2_prior": float,
                "mapping_solver_tolerance": float,
                "mapping_solver_max_iterations": int,
                "tie_policy": "exclude",
                "minimum_training_games": int,
                "minimum_mapping_rows": int,
                "apply_probability_clipping": bool,
                "reject_nonpositive_slope": bool,
                "maximum_development_season": int,
            },
            "candidates": (
                {"id": "responsive", ...},
                {"id": "balanced", ...},
                {"id": "stable", ...},
            ),
        }

    The ``candidates`` tuple is ordered ``(responsive, balanced, stable)``
    regardless of the order in the YAML file. The loader rejects any
    YAML that does not contain exactly these three ids and no others.
    """
    p = Path(yaml_path)
    if not p.is_file():
        raise ConfigurationError(
            f"expected_margin_v1.yaml not found at {p}"
        )
    raw = yaml.safe_load(p.read_text())
    if not isinstance(raw, dict):
        raise ConfigurationError(
            "expected_margin_v1.yaml: top-level must be a mapping, "
            f"got {type(raw).__name__}"
        )

    # Top-level keys
    unknown_top = set(raw.keys()) - _REQUIRED_TOP_KEYS
    if unknown_top:
        raise ConfigurationError(
            f"expected_margin_v1.yaml: unknown top-level keys: {sorted(unknown_top)}"
        )
    missing_top = _REQUIRED_TOP_KEYS - set(raw.keys())
    if missing_top:
        raise ConfigurationError(
            f"expected_margin_v1.yaml: missing top-level keys: {sorted(missing_top)}"
        )

    # Shared mapping
    shared = raw["shared"]
    if not isinstance(shared, dict):
        raise ConfigurationError(
            "expected_margin_v1.yaml: shared must be a mapping"
        )
    unknown_shared = set(shared.keys()) - _REQUIRED_SHARED_KEYS
    if unknown_shared:
        raise ConfigurationError(
            f"expected_margin_v1.yaml: unknown shared keys: {sorted(unknown_shared)}"
        )
    missing_shared = _REQUIRED_SHARED_KEYS - set(shared.keys())
    if missing_shared:
        raise ConfigurationError(
            f"expected_margin_v1.yaml: missing shared keys: {sorted(missing_shared)}"
        )

    normalized_shared: dict[str, Any] = {}
    normalized_shared["league_baseline_prior"] = _check_num(
        "shared.league_baseline_prior", shared["league_baseline_prior"], 0.0, 100.0
    )
    normalized_shared["probability_min"] = _check_num(
        "shared.probability_min", shared["probability_min"], 1e-9, 0.5
    )
    normalized_shared["probability_max"] = _check_num(
        "shared.probability_max", shared["probability_max"], 0.5, 1.0 - 1e-9
    )
    if normalized_shared["probability_min"] >= normalized_shared["probability_max"]:
        raise ConfigurationError(
            f"expected_margin_v1.yaml: probability_min ({normalized_shared['probability_min']}) "
            f"must be < probability_max ({normalized_shared['probability_max']})"
        )
    normalized_shared["mapping_intercept_l2_prior"] = _check_num(
        "shared.mapping_intercept_l2_prior",
        shared["mapping_intercept_l2_prior"],
        -1.0e6,
        1.0e6,
    )
    normalized_shared["mapping_slope_l2_prior"] = _check_num(
        "shared.mapping_slope_l2_prior",
        shared["mapping_slope_l2_prior"],
        -1.0e6,
        1.0e6,
    )
    normalized_shared["mapping_solver_tolerance"] = _check_num(
        "shared.mapping_solver_tolerance",
        shared["mapping_solver_tolerance"],
        1e-15,
        1e-1,
    )
    normalized_shared["mapping_solver_max_iterations"] = int(
        _check_num(
            "shared.mapping_solver_max_iterations",
            shared["mapping_solver_max_iterations"],
            1.0,
            10000.0,
        )
    )
    normalized_shared["tie_policy"] = _check_enum(
        "shared.tie_policy", shared["tie_policy"], ("exclude",)
    )
    normalized_shared["minimum_training_games"] = int(
        _check_num(
            "shared.minimum_training_games",
            shared["minimum_training_games"],
            1.0,
            1.0e6,
        )
    )
    normalized_shared["minimum_mapping_rows"] = int(
        _check_num(
            "shared.minimum_mapping_rows",
            shared["minimum_mapping_rows"],
            1.0,
            1.0e6,
        )
    )
    normalized_shared["apply_probability_clipping"] = _check_bool(
        "shared.apply_probability_clipping",
        shared["apply_probability_clipping"],
    )
    normalized_shared["reject_nonpositive_slope"] = _check_bool(
        "shared.reject_nonpositive_slope",
        shared["reject_nonpositive_slope"],
    )
    normalized_shared["maximum_development_season"] = int(
        _check_num(
            "shared.maximum_development_season",
            shared["maximum_development_season"],
            2018.0,
            2100.0,
        )
    )

    # Candidates
    candidates_raw = raw["candidates"]
    if not isinstance(candidates_raw, list):
        raise ConfigurationError(
            "expected_margin_v1.yaml: candidates must be a list"
        )
    if len(candidates_raw) != len(_CANDIDATE_ORDER):
        raise ConfigurationError(
            f"expected_margin_v1.yaml: candidates must contain exactly "
            f"{len(_CANDIDATE_ORDER)} entries, got {len(candidates_raw)}"
        )

    normalized_candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, cand in enumerate(candidates_raw):
        if not isinstance(cand, dict):
            raise ConfigurationError(
                f"expected_margin_v1.yaml: candidates[{idx}] must be a mapping"
            )
        unknown_cand = set(cand.keys()) - _REQUIRED_CANDIDATE_KEYS
        if unknown_cand:
            raise ConfigurationError(
                f"expected_margin_v1.yaml: candidates[{idx}] has unknown keys: {sorted(unknown_cand)}"
            )
        missing_cand = _REQUIRED_CANDIDATE_KEYS - set(cand.keys())
        if missing_cand:
            raise ConfigurationError(
                f"expected_margin_v1.yaml: candidates[{idx}] missing keys: {sorted(missing_cand)}"
            )
        cid = _check_enum(
            f"candidates[{idx}].id", cand["id"], _CANDIDATE_ORDER
        )
        if cid in seen_ids:
            raise ConfigurationError(
                f"expected_margin_v1.yaml: duplicate candidate id: {cid}"
            )
        seen_ids.add(cid)
        normalized_candidates.append(
            {
                "id": cid,
                "offense_ridge": _check_num(
                    f"candidates[{idx}].offense_ridge",
                    cand["offense_ridge"],
                    0.0,
                    1.0e6,
                ),
                "defense_ridge": _check_num(
                    f"candidates[{idx}].defense_ridge",
                    cand["defense_ridge"],
                    0.0,
                    1.0e6,
                ),
                "home_field_ridge": _check_num(
                    f"candidates[{idx}].home_field_ridge",
                    cand["home_field_ridge"],
                    0.0,
                    1.0e6,
                ),
                "recency_half_life_games": _check_num(
                    f"candidates[{idx}].recency_half_life_games",
                    cand["recency_half_life_games"],
                    1e-9,
                    1.0e6,
                ),
                "mapping_intercept_l2_weight": _check_num(
                    f"candidates[{idx}].mapping_intercept_l2_weight",
                    cand["mapping_intercept_l2_weight"],
                    0.0,
                    1.0e6,
                ),
                "mapping_slope_l2_weight": _check_num(
                    f"candidates[{idx}].mapping_slope_l2_weight",
                    cand["mapping_slope_l2_weight"],
                    0.0,
                    1.0e6,
                ),
            }
        )

    # Reorder candidates deterministically to the fixed order.
    by_id = {c["id"]: c for c in normalized_candidates}
    ordered = tuple(by_id[name] for name in _CANDIDATE_ORDER)

    return {
        "shared": dict(sorted(normalized_shared.items())),
        "candidates": ordered,
    }


def expected_margin_canonical_config_sha256(
    normalized_config: dict[str, Any],
) -> str:
    """Return SHA-256 of the canonical JSON of the normalized config.

    The canonical JSON is ``json.dumps(d, sort_keys=True, separators=(",", ":"))``
    so the result is byte-stable across runs and operating systems. The
    candidates are serialized in the fixed order enforced by the loader.
    """
    payload = json.dumps(
        normalized_config, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def lock_expected_margin_config(yaml_path: str | Path) -> dict[str, Any]:
    """Load the canonical config and pin its SHA-256 in one call.

    Returns a dictionary containing the normalized config and its
    SHA-256. The SHA-256 is computed over the deterministic canonical
    JSON BEFORE any candidate comparison or evaluation; it is the
    immutable configuration fingerprint used by the tuning ledger.
    """
    cfg = load_expected_margin_canonical_config(yaml_path)
    sha = expected_margin_canonical_config_sha256(cfg)
    return {
        "config": cfg,
        "config_sha256": sha,
        "candidate_ids": tuple(c["id"] for c in cfg["candidates"]),
    }
