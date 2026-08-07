"""Fresh XGBoost-v1 model core for NFL Edge Task 03C-3 recovery.

This module loads the prospectively locked configuration from
``config/xgboost_v1.yaml`` and the frozen feature contract from
``data/modeling/development_v1/xgboost_feature_contract_v1.json``.

It enforces:
  - Candidate lock: exactly three candidates, deterministic ordering
  - Feature-contract integrity: 132 features, exact order, exact SHA
  - Matrix safety: reject targets, IDs, market data, timestamps, postgame,
    starter-certainty, unknown/missing/duplicate features, wrong order,
    non-finite values
  - Deterministic DMatrix construction
  - Probability clipping and probability-bound validation
  - Configuration-lock validation (hashes must match embedded lock hashes)

It does NOT implement chronological walk-forward logic.
No NFL data is fit by this module.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import yaml

try:
    import xgboost as xgb
except ImportError:  # pragma: no cover
    xgb = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXPECTED_FEATURE_COUNT = 132
EXPECTED_CANDIDATE_COUNT = 3
EXPECTED_CANDIDATES = ("conservative", "balanced", "expressive")
EXPECTED_DTERMINISTIC_ORDER = ["conservative", "balanced", "expressive"]

EXPECTED_CONTRACT_SHA256 = (
    "4187bef6b76d71f4f89f3387ec4789512cccb6deacd6cd64520039c713919993"
)
EXPECTED_FEATURE_ORDER_HASH = (
    "e33c5154a7ba3e9b89b8da55bf41dd6b8358b49b09baee14f0d9106c1cf4a09c"
)
EXPECTED_LOGICAL_CONTRACT_HASH = (
    "ebfcc2dc63c857c2ddc1db7eaaf1b374ebe2308decb5df7bd4794ad834ef8793"
)
EXPECTED_EXTRACTION_SHA256 = (
    "fb4e45d28e337617043d578cb088e366aa217984bb200efca844e13111dc10f8"
)
EXPECTED_EXTRACTION_ROW_COUNT = 1942

EXPECTED_BASE_SHA = "a93bfe1f7ffaaac7bff8758bf278af1ce07149db"

# Token rejection sets for matrix safety
MARKET_TOKENS = (
    "moneyline", "spread_line", "total_line", "closing_", "pinnacle",
    "draftkings", "fanduel", "clv", "implied_probability",
    "market_probability", "market_price", "line_movement",
    "american_odds", "decimal_odds",
)
POSTGAME_TOKENS = ("postgame", "final_", "actual_")
ID_TOKENS = ("game_id", "prediction_id", "venue_id", "player_id", "team_id")
TARGET_TOKENS = (
    "target_home_win", "target_margin", "target_tie", "target_available",
)
TIMESTAMP_SUFFIX = "_utc"
STARTER_CERTAINTY_TOKENS = (
    "starter_certainty", "home_starter_certainty", "away_starter_certainty",
    "starter_reason_codes",
)

# Candidate parameter specification (must match config exactly)
CANDIDATE_PARAM_SPEC = {
    "conservative": {
        "max_depth": int,
        "learning_rate": float,
        "min_child_weight": float,
        "subsample": float,
        "colsample_bytree": float,
        "reg_alpha": float,
        "reg_lambda": float,
        "gamma": float,
        "max_delta_step": float,
        "max_rounds": int,
    },
    "balanced": {
        "max_depth": int,
        "learning_rate": float,
        "min_child_weight": float,
        "subsample": float,
        "colsample_bytree": float,
        "reg_alpha": float,
        "reg_lambda": float,
        "gamma": float,
        "max_delta_step": float,
        "max_rounds": int,
    },
    "expressive": {
        "max_depth": int,
        "learning_rate": float,
        "min_child_weight": float,
        "subsample": float,
        "colsample_bytree": float,
        "reg_alpha": float,
        "reg_lambda": float,
        "gamma": float,
        "max_delta_step": float,
        "max_rounds": int,
    },
}

# Parameter keys that are NOT passed to XGBoost (metadata)
_NON_XGB_PARAM_KEYS = {
    "hypothesis",
    "interaction_complexity",
    "max_rounds",
}


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _workspace_root() -> Path:
    """Resolve the NFL Edge worktree root from this module's location."""
    # src/nfl_edge/models/xgboost_v1.py -> worktree root
    return Path(__file__).resolve().parent.parent.parent.parent


def _config_path() -> Path:
    return _workspace_root() / "config" / "xgboost_v1.yaml"


def _contract_path() -> Path:
    return _workspace_root() / "data" / "modeling" / "development_v1" / "xgboost_feature_contract_v1.json"


def _extraction_path() -> Path:
    return _workspace_root() / "data" / "derived" / "features_v1" / "xgboost_development_2018_2024.parquet"


# ---------------------------------------------------------------------------
# Hash utilities
# ---------------------------------------------------------------------------

def _canonical_json(obj: Any) -> bytes:
    """Deterministic JSON serialization: sorted keys, compact separators."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_hex(path.read_bytes())


def _sha256_obj(obj: Any) -> str:
    return _sha256_hex(_canonical_json(obj))


# ---------------------------------------------------------------------------
# Candidate parameter hash computation
# ---------------------------------------------------------------------------

def _extract_candidate_params(candidate_dict: dict[str, Any]) -> dict[str, Any]:
    """Extract only the numeric XGBoost parameter values (no metadata)."""
    return {
        k: v for k, v in candidate_dict.items()
        if k not in _NON_XGB_PARAM_KEYS
    }


def compute_shared_settings_hash(shared_settings: dict[str, Any]) -> str:
    """Compute deterministic hash of the shared settings dict."""
    return _sha256_obj(shared_settings)


def compute_candidate_definition_hash(candidates: dict[str, Any]) -> str:
    """Compute deterministic hash of all candidate definitions (ordered)."""
    ordered = {
        "order": list(candidates.get("deterministic_order", [])),
        "definitions": {
            name: {
                "hypothesis": candidates[name].get("hypothesis", ""),
                "params": _extract_candidate_params(candidates[name]),
                "interaction_complexity": candidates[name].get("interaction_complexity", ""),
            }
            for name in candidates.get("deterministic_order", [])
            if name in candidates
        },
    }
    return _sha256_obj(ordered)


def compute_candidate_param_hash(candidate: dict[str, Any]) -> str:
    """Compute deterministic hash of a single candidate's parameter values."""
    return _sha256_obj(_extract_candidate_params(candidate))


def compute_logical_config_hash(
    shared_settings: dict[str, Any],
    candidates: dict[str, Any],
    lock_metadata: dict[str, Any],
) -> str:
    """Compute deterministic logical config hash from semantic content."""
    ordered_candidates = {
        "order": list(candidates.get("deterministic_order", [])),
        "definitions": {
            name: {
                "hypothesis": candidates[name].get("hypothesis", ""),
                "params": _extract_candidate_params(candidates[name]),
                "interaction_complexity": candidates[name].get("interaction_complexity", ""),
            }
            for name in candidates.get("deterministic_order", [])
            if name in candidates
        },
    }
    payload = {
        "shared_settings": shared_settings,
        "candidates": ordered_candidates,
        "lock_status": lock_metadata.get("status", ""),
        "candidate_count": lock_metadata.get("candidate_count", 0),
        "max_depth_absolute_max": lock_metadata.get("max_depth_absolute_max", 0),
    }
    return _sha256_obj(payload)


# ---------------------------------------------------------------------------
# Configuration loader and validator
# ---------------------------------------------------------------------------

class LockedConfig:
    """Loads and validates the locked XGBoost-v1 configuration."""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or _config_path()
        self._raw: dict[str, Any] = self._load_yaml()
        self._validate_structure()
        self._validate_lock()
        self._validate_candidates()
        self._validate_shared_settings()

    def _load_yaml(self) -> dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config not found: {self.config_path}")
        content = self.config_path.read_text()
        config = yaml.safe_load(content)
        if not isinstance(config, dict):
            raise ValueError("Config YAML root must be a mapping")
        return config

    @property
    def raw(self) -> dict[str, Any]:
        return self._raw

    @property
    def base_sha(self) -> str:
        return self._raw["base_sha"]

    @property
    def feature_count_actual(self) -> int:
        return self._raw["feature_count_actual"]

    @property
    def extraction_sha256(self) -> str:
        return self._raw["extraction_sha256"]

    @property
    def contract_hashes(self) -> dict[str, str]:
        return self._raw["hashes"]

    @property
    def shared_settings(self) -> dict[str, Any]:
        return self._raw["shared_settings"]

    @property
    def candidates_config(self) -> dict[str, Any]:
        return self._raw["candidates"]

    @property
    def lock_metadata(self) -> dict[str, Any]:
        return self._raw["lock_metadata"]

    @property
    def lock_hashes(self) -> dict[str, str]:
        return self._raw["lock_hashes"]

    @property
    def deterministic_order(self) -> list[str]:
        return self._raw["candidates"]["deterministic_order"]

    @property
    def file_sha256(self) -> str:
        return _sha256_file(self.config_path)

    # --- Validation ---

    def _validate_structure(self) -> None:
        for key in ("base_sha", "extraction", "target_policy", "exclusions",
                     "feature_contract", "determinism", "feature_count_target",
                     "feature_count_actual", "extraction_sha256", "hashes",
                     "shared_settings", "candidates", "walkforward_policy",
                     "lock_metadata", "lock_hashes"):
            if key not in self._raw:
                raise ValueError(f"Missing top-level config section: {key}")

    def _validate_lock(self) -> None:
        if self._raw["base_sha"] != EXPECTED_BASE_SHA:
            raise ValueError(
                f"Base SHA mismatch: {self._raw['base_sha']} != {EXPECTED_BASE_SHA}"
            )
        if self._raw["feature_count_actual"] != EXPECTED_FEATURE_COUNT:
            raise ValueError(
                f"Feature count mismatch: {self._raw['feature_count_actual']} != {EXPECTED_FEATURE_COUNT}"
            )
        if self._raw["extraction_sha256"] != EXPECTED_EXTRACTION_SHA256:
            raise ValueError(
                f"Extraction SHA mismatch: {self._raw['extraction_sha256']} != {EXPECTED_EXTRACTION_SHA256}"
            )
        contract_hashes = self.lock_hashes
        expected = {
            "shared_settings_hash": compute_shared_settings_hash(self.shared_settings),
            "logical_config_hash": compute_logical_config_hash(
                self.shared_settings, self.candidates_config, self.lock_metadata
            ),
            "candidate_definition_hash": compute_candidate_definition_hash(self.candidates_config),
        }
        for ck, cv in expected.items():
            embedded = contract_hashes.get(ck)
            if embedded != cv:
                raise ValueError(
                    f"Lock hash mismatch for {ck}:\n"
                    f"  embedded={embedded}\n  computed={cv}"
                )

    def _validate_candidates(self) -> None:
        cand = self.candidates_config
        order = cand.get("deterministic_order", [])
        if order != EXPECTED_DTERMINISTIC_ORDER:
            raise ValueError(
                f"Candidate order mismatch: {order} != {EXPECTED_DTERMINISTIC_ORDER}"
            )
        if len(order) != EXPECTED_CANDIDATE_COUNT:
            raise ValueError(
                f"Candidate count {len(order)} != {EXPECTED_CANDIDATE_COUNT}"
            )
        for name in EXPECTED_CANDIDATES:
            if name not in cand:
                raise ValueError(f"Missing candidate: {name}")
        # Verify per-candidate param hashes
        for name in EXPECTED_CANDIDATES:
            candidate = cand[name]
            computed_hash = compute_candidate_param_hash(candidate)
            embedded_key = f"{name}_parameter_hash"
            embedded = self.lock_hashes.get(embedded_key)
            if embedded != computed_hash:
                raise ValueError(
                    f"Parameter hash mismatch for {name}:\n"
                    f"  embedded={embedded}\n  computed={computed_hash}"
                )
            # Verify interaction complexity
            expected_complexity = {
                "conservative": "low",
                "balanced": "moderate",
                "expressive": "high",
            }
            if candidate.get("interaction_complexity") != expected_complexity[name]:
                raise ValueError(
                    f"Interaction complexity mismatch for {name}: "
                    f"{candidate.get('interaction_complexity')}"
                )
            # Verify max_depth not > 4
            if candidate["max_depth"] > 4:
                raise ValueError(
                    f"max_depth {candidate['max_depth']} exceeds absolute max of 4"
                )
            # Verify max_rounds
            expected_rounds = {"conservative": 200, "balanced": 400, "expressive": 800}
            if candidate["max_rounds"] != expected_rounds[name]:
                raise ValueError(
                    f"max_rounds mismatch for {name}: "
                    f"{candidate['max_rounds']} != {expected_rounds[name]}"
                )

    def _validate_shared_settings(self) -> None:
        ss = self.shared_settings
        expected = {
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "tree_method": "hist",
            "seed": 42,
            "nthread": 1,
            "early_stopping_rounds": 50,
            "probability_epsilon": 0.000001,
            "min_training_rows": 32,
            "min_training_blocks": 2,
            "validation_block_count": 2,
            "min_validation_rows": 21,
            "min_validation_blocks": 2,
        }
        for key, val in expected.items():
            if key not in ss:
                raise ValueError(f"Missing shared setting: {key}")
            if ss[key] != val:
                raise ValueError(
                    f"Shared setting mismatch for {key}: {ss[key]} != {val}"
                )
        # Verify shared settings hash
        computed = compute_shared_settings_hash(ss)
        embedded = self.lock_hashes.get("shared_settings_hash")
        if embedded != computed:
            raise ValueError(
                f"Shared settings hash mismatch:\n"
                f"  embedded={embedded}\n  computed={computed}"
            )

    # --- Accessors ---

    def get_candidate_order(self) -> list[str]:
        """Return deterministic candidate ordering."""
        return list(self.deterministic_order)

    def get_candidate_names(self) -> list[str]:
        """Alias for deterministic order."""
        return self.get_candidate_order()

    def get_candidate_params(self, candidate_name: str) -> dict[str, Any]:
        """Return the XGBoost parameter dict for a candidate (without max_rounds)."""
        if candidate_name not in self.candidates_config:
            raise ValueError(f"Unknown candidate: {candidate_name}")
        candidate = self.candidates_config[candidate_name]
        params = _extract_candidate_params(candidate)
        # Remove max_rounds — it's not an XGBoost per-tree param
        params.pop("max_rounds", None)
        return params

    def get_candidate_max_rounds(self, candidate_name: str) -> int:
        """Return the locked max_rounds for a candidate."""
        if candidate_name not in self.candidates_config:
            raise ValueError(f"Unknown candidate: {candidate_name}")
        return self.candidates_config[candidate_name]["max_rounds"]

    def get_shared_settings(self) -> dict[str, Any]:
        """Return shared settings dict."""
        return dict(self.shared_settings)

    def get_xgboost_params(self, candidate_name: str) -> dict[str, Any]:
        """Construct full XGBoost parameter dict (shared + candidate-specific)."""
        params = self.get_candidate_params(candidate_name)
        ss = self.get_shared_settings()
        # Shared settings that are XGBoost params:
        params["objective"] = ss["objective"]
        params["eval_metric"] = ss["eval_metric"]
        params["tree_method"] = ss["tree_method"]
        params["seed"] = ss["seed"]
        params["nthread"] = ss["nthread"]
        # max_rounds is handled separately (num_boost_round)
        return params

    def get_probability_epsilon(self) -> float:
        return float(self.shared_settings["probability_epsilon"])


# ---------------------------------------------------------------------------
# Feature contract loader and validator
# ---------------------------------------------------------------------------

class FeatureContract:
    """Loads and validates the frozen feature-contract JSON."""

    def __init__(self, contract_path: Path | None = None) -> None:
        self.contract_path = contract_path or _contract_path()
        self._raw: dict[str, Any] = self._load()
        self._validate()

    def _load(self) -> dict[str, Any]:
        if not self.contract_path.exists():
            raise FileNotFoundError(f"Feature contract not found: {self.contract_path}")
        return json.loads(self.contract_path.read_text())

    def _validate(self) -> None:
        if self._raw.get("model_feature_count") != EXPECTED_FEATURE_COUNT:
            raise ValueError(
                f"Feature count mismatch: "
                f"{self._raw.get('model_feature_count')} != {EXPECTED_FEATURE_COUNT}"
            )
        file_sha = _sha256_file(self.contract_path)
        if file_sha != EXPECTED_CONTRACT_SHA256:
            raise ValueError(
                f"Contract SHA mismatch: {file_sha} != {EXPECTED_CONTRACT_SHA256}"
            )
        hashes = self._raw.get("hashes", {})
        if hashes.get("feature_order_hash") != EXPECTED_FEATURE_ORDER_HASH:
            raise ValueError("Feature order hash mismatch")
        if hashes.get("logical_contract_hash") != EXPECTED_LOGICAL_CONTRACT_HASH:
            raise ValueError("Logical contract hash mismatch")

    @property
    def raw(self) -> dict[str, Any]:
        return self._raw

    @property
    def feature_order(self) -> list[str]:
        """Return the canonical feature order (deterministic)."""
        return list(self._raw["deterministic_ordering"]["feature_order"])

    @property
    def feature_count(self) -> int:
        return self._raw["model_feature_count"]

    @property
    def file_sha256(self) -> str:
        return _sha256_file(self.contract_path)

    @property
    def logical_contract_hash(self) -> str:
        return self._raw["hashes"]["logical_contract_hash"]

    @property
    def feature_order_hash(self) -> str:
        return self._raw["hashes"]["feature_order_hash"]

    @property
    def logical_content_hash(self) -> str:
        return self._raw["logical_content_hash"]

    @property
    def extraction_sha256(self) -> str:
        return self._raw["extraction_provenance"]["sha256"]

    @property
    def extraction_row_count(self) -> int:
        return self._raw["extraction_provenance"]["row_count"]


# ---------------------------------------------------------------------------
# Matrix safety
# ---------------------------------------------------------------------------

def _check_no_token_leak(col: str, tokens: tuple[str, ...], error_prefix: str) -> None:
    low = col.lower()
    for token in tokens:
        if token in low:
            raise ValueError(f"{error_prefix}: column '{col}' contains token '{token}'")


def validate_feature_matrix(
    features: list[str],
    feature_matrix: np.ndarray,
) -> None:
    """Validate a feature matrix against the frozen contract.

    Parameters
    ----------
    features : list[str]
        Feature column names in row/column order.
    feature_matrix : np.ndarray
        2D array of shape (n_rows, n_features).

    Raises
    ------
    ValueError if any safety rule is violated.
    """
    # --- Reject against token rules ---
    for col in features:
        _check_no_token_leak(col, MARKET_TOKENS, "market feature rejected")
        _check_no_token_leak(col, POSTGAME_TOKENS, "postgame feature rejected")
        _check_no_token_leak(col, STARTER_CERTAINTY_TOKENS, "starter-certainty feature rejected")
        if col.endswith(TIMESTAMP_SUFFIX):
            raise ValueError(f"timestamp feature rejected: '{col}'")
        # Exact-match token rejections (not substring — avoids false positives
        # on legitimate features like away_qb_missing_player_id)
        if col in ID_TOKENS:
            raise ValueError(f"identifier column rejected: '{col}'")
        if col in TARGET_TOKENS:
            raise ValueError(f"target column rejected: '{col}'")

    # --- Enforce feature count ---
    if len(features) != EXPECTED_FEATURE_COUNT:
        raise ValueError(
            f"Feature count {len(features)} != {EXPECTED_FEATURE_COUNT}"
        )

    # --- Enforce exact uniqueness (no duplicates) ---
    seen: set[str] = set()
    for col in features:
        if col in seen:
            raise ValueError(f"duplicate feature rejected: '{col}'")
        seen.add(col)

    # --- Enforce exact feature order ---
    contract = FeatureContract()
    expected_order = contract.feature_order
    if features != expected_order:
        # Find first mismatch
        for i, (actual, expected) in enumerate(zip(features, expected_order)):
            if actual != expected:
                raise ValueError(
                    f"Feature order mismatch at index {i}: "
                    f"'{actual}' != '{expected}'"
                )
        raise ValueError(
            f"Feature order length mismatch: {len(features)} != {len(expected_order)}"
        )

    # --- Enforce matrix shape ---
    if feature_matrix.ndim != 2:
        raise ValueError(f"Feature matrix must be 2D, got {feature_matrix.ndim}D")
    if feature_matrix.shape[1] != len(features):
        raise ValueError(
            f"Matrix shape {feature_matrix.shape} doesn't match "
            f"feature count {len(features)}"
        )

    # --- Non-finite check ---
    arr = np.asarray(feature_matrix, dtype=np.float64)
    if not np.all(np.isfinite(arr)):
        raise ValueError("nan/inf in feature matrix not covered by locked policy")


def build_dmatrix(
    features: list[str],
    feature_matrix: np.ndarray,
) -> Any:
    """Construct a deterministic XGBoost DMatrix.

    Validates the feature list and matrix before constructing.
    """
    validate_feature_matrix(features, feature_matrix)
    if xgb is None:
        raise ImportError("xgboost is not installed; install with 'pip install xgboost==2.1.4'")
    # DMatrix with explicit feature_names for deterministic ordering
    dmatrix = xgb.DMatrix(
        feature_matrix,
        feature_names=features,
    )
    # Verify feature name ordering was preserved
    actual_names = list(dmatrix.feature_names or [])
    if actual_names != features:
        raise ValueError(
            f"DMatrix feature order mismatch: {actual_names} != {features}"
        )
    return dmatrix


# ---------------------------------------------------------------------------
# Probability clipping and validation
# ---------------------------------------------------------------------------

def clip_probabilities(probs: np.ndarray, epsilon: float | None = None) -> np.ndarray:
    """Clip probabilities to [epsilon, 1-epsilon] for numerical safety."""
    if epsilon is None:
        epsilon = LockedConfig().get_probability_epsilon()
    eps = float(epsilon)
    return np.clip(probs, eps, 1.0 - eps)


def validate_probabilities(probs: np.ndarray, epsilon: float | None = None) -> None:
    """Validate that probabilities are in [0, 1] and finite."""
    if epsilon is None:
        epsilon = LockedConfig().get_probability_epsilon()
    eps = float(epsilon)
    arr = np.asarray(probs, dtype=np.float64)
    if not np.all(np.isfinite(arr)):
        raise ValueError("probabilities contain nan/inf")
    if arr.ndim != 1:
        raise ValueError(f"probabilities must be 1D, got {arr.ndim}D")
    if np.any(arr < 0.0) or np.any(arr > 1.0):
        raise ValueError("probabilities out of [0, 1] range")
    # Verify clipping works
    clipped = clip_probabilities(arr, eps)
    if not np.all(np.isfinite(clipped)):
        raise ValueError("clipped probabilities contain nan/inf")
    if np.any(clipped < eps) or np.any(clipped > (1.0 - eps)):
        raise ValueError("clipped probabilities out of bounds")


# ---------------------------------------------------------------------------
# Configuration-lock validation
# ---------------------------------------------------------------------------

def validate_config_lock(config_path: Path | None = None) -> str:
    """Validate the canonical config against the lock checkpoint.

    Returns the file SHA-256 of the canonical config on success.
    Raises if any lock check fails.
    """
    config_path = config_path or _config_path()
    config = LockedConfig(config_path)

    # Verify feature contract integrity
    contract = FeatureContract()
    if contract.file_sha256 != EXPECTED_CONTRACT_SHA256:
        raise ValueError(
            f"Contract file SHA changed: {contract.file_sha256}"
        )
    if contract.feature_order_hash != EXPECTED_FEATURE_ORDER_HASH:
        raise ValueError("Contract feature_order_hash changed")
    if contract.logical_contract_hash != EXPECTED_LOGICAL_CONTRACT_HASH:
        raise ValueError("Contract logical_contract_hash changed")

    # Verify extraction integrity
    extraction = _extraction_path()
    if extraction.exists():
        ext_sha = _sha256_file(extraction)
        if ext_sha != contract.extraction_sha256:
            raise ValueError(
                f"Extraction SHA mismatch: {ext_sha} != {contract.extraction_sha256}"
            )

    file_sha = config.file_sha256
    return file_sha
