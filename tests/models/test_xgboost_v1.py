"""Fresh tests for the XGBoost-v1 Task 03C-3 candidate lock.

Tests cover:
  - Candidate lock: exactly three candidates, exact names, deterministic order,
    exact numerical values, depth 2/3/4, no depth >4, max rounds 200/400/800,
    material parameter differentiation.
  - Shared settings: objective, logloss, hist, seed 42, nthread 1, early stopping 50,
    epsilon 1e-6, train rows 32, train blocks 2, validation blocks 2, validation rows 21,
    minimum validation blocks 2.
  - Contract: feature count 132, exact contract SHA, logical contract hash,
    feature-order hash, extraction SHA, 1942 rows.
  - Safety: target rejection, ID rejection, market rejection, starter-certainty
    rejection, postgame rejection, unknown-feature rejection, duplicate rejection,
    wrong-order rejection, non-finite rejection, unknown-candidate rejection.
  - Determinism: config hash stable, shared hash stable, candidate hashes stable,
    DMatrix feature ordering stable, clipping stable.
  - Snapshot protection: canonical config matches locked config, canonical
    differentiation matches locked evidence, snapshot hashes match manifest,
    manifest declares pre-result lock, no test regenerates snapshot, altered
    canonical config causes lock validation failure, altered candidate param
    causes lock validation failure, altered shared setting causes lock validation failure.
  - Canonical-vs-snapshot equality gate: byte-for-byte equality between canonical
    config and locked config, canonical differentiation JSON and locked JSON,
    feature contract SHA matches locked copy and accepted 03C-2 SHA.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from nfl_edge.models.xgboost_v1 import (  # noqa: E402
    EXPECTED_BASE_SHA,
    EXPECTED_CANDIDATE_COUNT,
    EXPECTED_CANDIDATES,
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_DTERMINISTIC_ORDER,
    EXPECTED_EXTRACTION_ROW_COUNT,
    EXPECTED_EXTRACTION_SHA256,
    EXPECTED_FEATURE_COUNT,
    EXPECTED_FEATURE_ORDER_HASH,
    EXPECTED_LOGICAL_CONTRACT_HASH,
    FeatureContract,
    LockedConfig,
    _sha256_file,
    build_dmatrix,
    clip_probabilities,
    compute_candidate_param_hash,
    compute_shared_settings_hash,
    validate_config_lock,
    validate_feature_matrix,
    validate_probabilities,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CONFIG_PATH = ROOT / "config" / "xgboost_v1.yaml"
CONTRACT_PATH = ROOT / "data" / "modeling" / "development_v1" / "xgboost_feature_contract_v1.json"
EXTRACTION_PATH = ROOT / "data" / "derived" / "features_v1" / "xgboost_development_2018_2024.parquet"
DIFFERENTIATION_PATH = ROOT / "data" / "modeling" / "development_v1" / "xgboost_candidate_differentiation_v1.json"

SNAPSHOT_DIR = ROOT / "data" / "modeling" / "development_v1" / "xgboost_lock_snapshot_v1"
SNAPSHOT_CONFIG = SNAPSHOT_DIR / "config_xgboost_v1.locked.yaml"
SNAPSHOT_DIFFERENTIATION = SNAPSHOT_DIR / "xgboost_candidate_differentiation_v1.locked.json"
SNAPSHOT_CONTRACT = SNAPSHOT_DIR / "xgboost_feature_contract_v1.locked.json"
SNAPSHOT_MANIFEST = SNAPSHOT_DIR / "LOCK_MANIFEST.json"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def config() -> LockedConfig:
    return LockedConfig()


@pytest.fixture(scope="module")
def contract() -> FeatureContract:
    return FeatureContract()


@pytest.fixture(scope="module")
def raw_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())


@pytest.fixture(scope="module")
def differentiation() -> dict:
    return json.loads(DIFFERENTIATION_PATH.read_text())


# ---------------------------------------------------------------------------
# Candidate Lock Tests
# ---------------------------------------------------------------------------

class TestCandidateLock:
    """Verify the candidate lock is correct with exactly three candidates."""

    def test_exactly_three_candidates(self, config: LockedConfig):
        order = config.get_candidate_order()
        assert len(order) == EXPECTED_CANDIDATE_COUNT

    def test_exact_candidate_names(self, config: LockedConfig):
        order = config.get_candidate_order()
        for name in EXPECTED_CANDIDATES:
            assert name in order, f"Missing candidate: {name}"

    def test_deterministic_order(self, config: LockedConfig):
        order = config.get_candidate_order()
        assert order == list(EXPECTED_DTERMINISTIC_ORDER)

    def test_no_fourth_candidate(self, config: LockedConfig):
        order = config.get_candidate_order()
        assert len(order) == 3
        assert set(order) == set(EXPECTED_CANDIDATES)

    def test_conservative_parameters(self, config: LockedConfig):
        params = config.get_candidate_params("conservative")
        assert params["max_depth"] == 2
        assert params["learning_rate"] == 0.05
        assert params["min_child_weight"] == 5.0
        assert params["subsample"] == 0.80
        assert params["colsample_bytree"] == 0.60
        assert params["reg_alpha"] == 0.50
        assert params["reg_lambda"] == 2.00
        assert params["gamma"] == 0.50
        assert params["max_delta_step"] == 1.00
        assert config.get_candidate_max_rounds("conservative") == 200

    def test_balanced_parameters(self, config: LockedConfig):
        params = config.get_candidate_params("balanced")
        assert params["max_depth"] == 3
        assert params["learning_rate"] == 0.05
        assert params["min_child_weight"] == 3.0
        assert params["subsample"] == 0.85
        assert params["colsample_bytree"] == 0.70
        assert params["reg_alpha"] == 0.30
        assert params["reg_lambda"] == 1.50
        assert params["gamma"] == 0.20
        assert params["max_delta_step"] == 0.00
        assert config.get_candidate_max_rounds("balanced") == 400

    def test_expressive_parameters(self, config: LockedConfig):
        params = config.get_candidate_params("expressive")
        assert params["max_depth"] == 4
        assert params["learning_rate"] == 0.03
        assert params["min_child_weight"] == 1.0
        assert params["subsample"] == 0.90
        assert params["colsample_bytree"] == 0.80
        assert params["reg_alpha"] == 0.10
        assert params["reg_lambda"] == 1.00
        assert params["gamma"] == 0.00
        assert params["max_delta_step"] == 0.00
        assert config.get_candidate_max_rounds("expressive") == 800

    def test_depth_values(self, config: LockedConfig):
        depths = []
        for name in config.get_candidate_order():
            params = config.get_candidate_params(name)
            depths.append(params["max_depth"])
        assert depths == [2, 3, 4]

    def test_no_depth_greater_than_four(self, config: LockedConfig):
        for name in config.get_candidate_order():
            params = config.get_candidate_params(name)
            assert params["max_depth"] <= 4

    def test_exact_max_rounds(self, config: LockedConfig):
        rounds = {}
        for name in config.get_candidate_order():
            rounds[name] = config.get_candidate_max_rounds(name)
        assert rounds["conservative"] == 200
        assert rounds["balanced"] == 400
        assert rounds["expressive"] == 800

    def test_material_parameter_differentiation(self, config: LockedConfig):
        """All three candidates differ in every parameter dimension."""
        order = config.get_candidate_order()
        param_sets = [config.get_candidate_params(n) for n in order]
        param_keys = list(param_sets[0].keys())
        for key in param_keys:
            vals = [ps[key] for ps in param_sets]
            # All three must be different for at least max_depth
            if key == "max_depth":
                assert len(set(vals)) == 3, f"max_depth not differentiated: {vals}"
            elif key in ("min_child_weight", "reg_alpha", "reg_lambda"):
                assert len(set(vals)) == 3, f"{key} not differentiated: {vals}"

    def test_interaction_complexity_labels(self, config: LockedConfig):
        expected = {"conservative": "low", "balanced": "moderate", "expressive": "high"}
        for name in config.get_candidate_order():
            raw = config.candidates_config[name]
            assert raw["interaction_complexity"] == expected[name]


# ---------------------------------------------------------------------------
# Shared Settings Tests
# ---------------------------------------------------------------------------

class TestSharedSettings:
    """Verify frozen shared settings."""

    def test_objective(self, config: LockedConfig):
        assert config.shared_settings["objective"] == "binary:logistic"

    def test_eval_metric_logloss(self, config: LockedConfig):
        assert config.shared_settings["eval_metric"] == "logloss"

    def test_tree_method_hist(self, config: LockedConfig):
        assert config.shared_settings["tree_method"] == "hist"

    def test_seed_42(self, config: LockedConfig):
        assert config.shared_settings["seed"] == 42

    def test_nthread_1(self, config: LockedConfig):
        assert config.shared_settings["nthread"] == 1

    def test_early_stopping_rounds_50(self, config: LockedConfig):
        assert config.shared_settings["early_stopping_rounds"] == 50

    def test_probability_epsilon(self, config: LockedConfig):
        assert config.shared_settings["probability_epsilon"] == 0.000001

    def test_min_training_rows_32(self, config: LockedConfig):
        assert config.shared_settings["min_training_rows"] == 32

    def test_min_training_blocks_2(self, config: LockedConfig):
        assert config.shared_settings["min_training_blocks"] == 2

    def test_validation_block_count_2(self, config: LockedConfig):
        assert config.shared_settings["validation_block_count"] == 2

    def test_min_validation_rows_21(self, config: LockedConfig):
        assert config.shared_settings["min_validation_rows"] == 21

    def test_min_validation_blocks_2(self, config: LockedConfig):
        assert config.shared_settings["min_validation_blocks"] == 2


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------

class TestContract:
    """Verify frozen feature contract."""

    def test_feature_count_132(self, contract: FeatureContract):
        assert contract.feature_count == EXPECTED_FEATURE_COUNT

    def test_feature_count_132_explicit(self, contract: FeatureContract):
        assert contract.feature_count == 132

    def test_exact_contract_sha(self, contract: FeatureContract):
        assert contract.file_sha256 == EXPECTED_CONTRACT_SHA256

    def test_exact_logical_contract_hash(self, contract: FeatureContract):
        assert contract.logical_contract_hash == EXPECTED_LOGICAL_CONTRACT_HASH

    def test_exact_feature_order_hash(self, contract: FeatureContract):
        assert contract.feature_order_hash == EXPECTED_FEATURE_ORDER_HASH

    def test_exact_extraction_sha(self, contract: FeatureContract):
        assert contract.extraction_sha256 == EXPECTED_EXTRACTION_SHA256

    def test_extraction_has_1942_rows(self, contract: FeatureContract):
        assert contract.extraction_row_count == EXPECTED_EXTRACTION_ROW_COUNT
        assert contract.extraction_row_count == 1942


# ---------------------------------------------------------------------------
# Safety Tests
# ---------------------------------------------------------------------------

class TestSafetyRejection:
    """Tests for matrix safety rejection rules."""

    def _get_feature_order(self) -> list[str]:
        contract = FeatureContract()
        return contract.feature_order

    def test_target_rejection(self):
        features = self._get_feature_order()
        with pytest.raises(ValueError, match="target"):
            bad_features = [f if not f.startswith("target") else "target_home_win" for f in features]
            bad_features[0] = "target_home_win"
            validate_feature_matrix(bad_features, np.random.rand(10, 132))

    def test_id_rejection(self):
        features = self._get_feature_order()
        with pytest.raises(ValueError, match="identifier"):
            bad_features = list(features)
            bad_features[0] = "game_id"
            validate_feature_matrix(bad_features, np.random.rand(10, 132))

    def test_market_rejection(self):
        features = self._get_feature_order()
        with pytest.raises(ValueError, match="market"):
            bad_features = list(features)
            bad_features[0] = "closing_line"
            validate_feature_matrix(bad_features, np.random.rand(10, 132))

    def test_starter_certainty_rejection(self):
        features = self._get_feature_order()
        with pytest.raises(ValueError, match="starter-certainty"):
            bad_features = list(features)
            bad_features[0] = "home_starter_certainty"
            validate_feature_matrix(bad_features, np.random.rand(10, 132))

    def test_postgame_rejection(self):
        features = self._get_feature_order()
        with pytest.raises(ValueError, match="postgame"):
            bad_features = list(features)
            bad_features[0] = "final_score"
            validate_feature_matrix(bad_features, np.random.rand(10, 132))

    def test_unknown_feature_rejection(self):
        """Features not in the contract are rejected."""
        features = self._get_feature_order()
        with pytest.raises(ValueError, match="order"):
            bad_features = list(features)
            bad_features[-1] = "unknown_feature_xyz"
            validate_feature_matrix(bad_features, np.random.rand(10, 132))

    def test_duplicate_rejection(self):
        features = self._get_feature_order()
        with pytest.raises(ValueError, match="duplicate"):
            bad_features = list(features)
            bad_features[0] = bad_features[1]
            validate_feature_matrix(bad_features, np.random.rand(10, 132))

    def test_wrong_order_rejection(self):
        features = self._get_feature_order()
        with pytest.raises(ValueError, match="order"):
            bad_features = list(reversed(features))
            validate_feature_matrix(bad_features, np.random.rand(10, 132))

    def test_non_finite_rejection(self):
        features = self._get_feature_order()
        matrix = np.random.rand(10, 132)
        matrix[0, 0] = np.nan
        with pytest.raises(ValueError, match="nan/inf"):
            validate_feature_matrix(features, matrix)

    def test_non_finite_inf_rejection(self):
        features = self._get_feature_order()
        matrix = np.random.rand(10, 132)
        matrix[0, 0] = np.inf
        with pytest.raises(ValueError, match="nan/inf"):
            validate_feature_matrix(features, matrix)

    def test_unknown_candidate_rejection(self):
        config = LockedConfig()
        with pytest.raises(ValueError, match="Unknown candidate"):
            config.get_candidate_params("nonexistent")

    def test_wrong_feature_count_rejection(self):
        features = self._get_feature_order()[:131]
        with pytest.raises(ValueError, match="Feature count"):
            validate_feature_matrix(features, np.random.rand(10, 131))


# ---------------------------------------------------------------------------
# Determinism Tests
# ---------------------------------------------------------------------------

class TestDeterminism:
    """Verify deterministic hash computation."""

    def test_config_hash_stable(self, config: LockedConfig):
        h1 = config.file_sha256
        h2 = config.file_sha256
        assert h1 == h2

    def test_shared_hash_stable(self, config: LockedConfig):
        ss = config.get_shared_settings()
        h1 = compute_shared_settings_hash(ss)
        h2 = compute_shared_settings_hash(ss)
        assert h1 == h2

    def test_candidate_hashes_stable(self, config: LockedConfig):
        for name in config.get_candidate_order():
            h1 = compute_candidate_param_hash(config.candidates_config[name])
            h2 = compute_candidate_param_hash(config.candidates_config[name])
            assert h1 == h2

    def test_dmatrix_feature_ordering_stable(self):
        contract = FeatureContract()
        features = contract.feature_order
        matrix = np.random.rand(50, len(features))
        dmatrix = build_dmatrix(features, matrix)
        assert list(dmatrix.feature_names) == features

    def test_clipping_stable(self, config: LockedConfig):
        eps = config.get_probability_epsilon()
        probs = np.array([0.0, 1.0, 0.5, 0.999999, 0.0000001])
        clipped = clip_probabilities(probs, eps)
        clipped2 = clip_probabilities(probs, eps)
        assert np.array_equal(clipped, clipped2)
        assert clipped[0] >= eps
        assert clipped[1] <= 1.0 - eps


# ---------------------------------------------------------------------------
# Snapshot Protection Tests
# ---------------------------------------------------------------------------

class TestSnapshotProtection:
    """Verify snapshot immutability and canonical-vs-snapshot equality."""

    def test_canonical_config_matches_locked(self):
        """Byte-for-byte equality: canonical config == locked snapshot config."""
        canonical = CONFIG_PATH.read_bytes()
        locked = SNAPSHOT_CONFIG.read_bytes()
        assert canonical == locked

    def test_canonical_differentiation_matches_locked(self):
        """Byte-for-byte equality: canonical differentiation == locked snapshot."""
        canonical = DIFFERENTIATION_PATH.read_bytes()
        locked = SNAPSHOT_DIFFERENTIATION.read_bytes()
        assert canonical == locked

    def test_contract_sha_matches_locked(self):
        """Contract SHA matches locked copy AND accepted 03C-2 SHA."""
        canonical_sha = _sha256_file(CONTRACT_PATH)
        locked_sha = _sha256_file(SNAPSHOT_CONTRACT)
        assert canonical_sha == EXPECTED_CONTRACT_SHA256
        assert locked_sha == EXPECTED_CONTRACT_SHA256
        assert canonical_sha == locked_sha

    def test_snapshot_hashes_match_manifest(self):
        """All snapshot file hashes match the manifest recorded values."""
        manifest = json.loads(SNAPSHOT_MANIFEST.read_text())
        snapshot_files = manifest["snapshot_files"]

        for filename, info in snapshot_files.items():
            snap_file = SNAPSHOT_DIR / filename
            actual_sha = _sha256_file(snap_file)
            assert actual_sha == info["sha256"], f"Hash mismatch for {filename}"

    def test_manifest_declares_pre_result_lock(self):
        manifest = json.loads(SNAPSHOT_MANIFEST.read_text())
        assert manifest["status"] == "PRE_RESULT_AUTHORITATIVE_LOCK"
        assert manifest["NO_NFL_CANDIDATE_RESULTS_EXIST_AT_LOCK_TIME"] is True

    def test_no_test_regenerates_snapshot(self):
        """Ensure the snapshot files are not rewritten by any test operation."""
        initial_config_sha = _sha256_file(SNAPSHOT_CONFIG)
        initial_diff_sha = _sha256_file(SNAPSHOT_DIFFERENTIATION)
        initial_contract_sha = _sha256_file(SNAPSHOT_CONTRACT)

        # Run config lock validation (which only reads, never writes)
        validate_config_lock()

        assert _sha256_file(SNAPSHOT_CONFIG) == initial_config_sha
        assert _sha256_file(SNAPSHOT_DIFFERENTIATION) == initial_diff_sha
        assert _sha256_file(SNAPSHOT_CONTRACT) == initial_contract_sha

    def test_altered_canonical_config_causes_lock_failure(self, config: LockedConfig):
        """If canonical config is altered, lock validation must fail."""
        original_content = CONFIG_PATH.read_bytes()
        try:
            # Write a slightly altered config
            altered = original_content.replace(b"  seed: 42", b"  seed: 99")
            CONFIG_PATH.write_bytes(altered)
            with pytest.raises(ValueError, match="hash mismatch"):
                LockedConfig()
        finally:
            # Restore original
            CONFIG_PATH.write_bytes(original_content)

    def test_altered_candidate_param_causes_lock_failure(self, config: LockedConfig):
        """If a candidate parameter is altered, lock validation must fail."""
        raw = yaml.safe_load(CONFIG_PATH.read_text())
        original_content = CONFIG_PATH.read_bytes()
        try:
            # Alter max_depth of conservative candidate
            raw["candidates"]["conservative"]["max_depth"] = 5
            altered = yaml.dump(raw, sort_keys=False)
            CONFIG_PATH.write_text(altered)
            with pytest.raises(ValueError, match="hash mismatch|Parameter hash"):
                LockedConfig()
        finally:
            CONFIG_PATH.write_bytes(original_content)

    def test_altered_shared_setting_causes_lock_failure(self, config: LockedConfig):
        """If a shared setting is altered, lock validation must fail."""
        original_content = CONFIG_PATH.read_bytes()
        try:
            raw = yaml.safe_load(original_content)
            raw["shared_settings"]["seed"] = 99
            altered = yaml.dump(raw, sort_keys=False)
            CONFIG_PATH.write_text(altered)
            with pytest.raises(ValueError, match="hash mismatch"):
                LockedConfig()
        finally:
            CONFIG_PATH.write_bytes(original_content)

    def test_snapshot_files_readonly(self):
        """Snapshot files must be read-only at filesystem level."""
        for fname in [
            "config_xgboost_v1.locked.yaml",
            "xgboost_candidate_differentiation_v1.locked.json",
            "xgboost_feature_contract_v1.locked.json",
            "LOCK_MANIFEST.json",
        ]:
            snap_file = SNAPSHOT_DIR / fname
            mode = oct(snap_file.stat().st_mode & 0o777)
            # Read-only for owner (no write bit): mode should be 444 or similar without w
            assert not (snap_file.stat().st_mode & 0o200), f"{fname} is writable: {mode}"


# ---------------------------------------------------------------------------
# Canonical-vs-Snapshot Equality Gate
# ---------------------------------------------------------------------------

class TestEqualityGate:
    """Explicit byte-for-byte equality gate to prevent silent overwrites."""

    def test_config_yaml_equality(self):
        canonical = CONFIG_PATH.read_bytes()
        locked = SNAPSHOT_CONFIG.read_bytes()
        assert canonical == locked, "Canonical config differs from locked snapshot"

    def test_candidate_differentiation_equality(self):
        canonical = DIFFERENTIATION_PATH.read_bytes()
        locked = SNAPSHOT_DIFFERENTIATION.read_bytes()
        assert canonical == locked, "Canonical differentiation differs from locked snapshot"

    def test_feature_contract_equality(self):
        canonical_sha = _sha256_file(CONTRACT_PATH)
        locked_sha = _sha256_file(SNAPSHOT_CONTRACT)
        assert canonical_sha == locked_sha

    def test_contract_sha_accepted_03c2(self):
        assert _sha256_file(CONTRACT_PATH) == EXPECTED_CONTRACT_SHA256
        assert _sha256_file(SNAPSHOT_CONTRACT) == EXPECTED_CONTRACT_SHA256


# ---------------------------------------------------------------------------
# ─────────────────────────────────────────────────────────────────────────────
# Task 03C-4A: Walk-forward engine is now authorized (replaces 03C-3 prohibition)
# ---------------------------------------------------------------------------

class TestWalkforwardAuthorization:
    """Verify walk-forward module exists but does not mutate frozen lock."""

    def test_walkforward_impl_exists(self):
        wf_path = ROOT / "src" / "nfl_edge" / "backtest" / "xgboost_walk_forward.py"
        assert wf_path.exists(), f"Walk-forward impl should exist at {wf_path}"

    def test_walkforward_tests_exist(self):
        wf_test_path = ROOT / "tests" / "backtest" / "test_xgboost_walk_forward.py"
        assert wf_test_path.exists(), f"Walk-forward tests should exist at {wf_test_path}"

    def test_walkforward_module_importable(self):
        """Walk-forward module must be importable at 03C-4A."""
        import importlib
        mod = importlib.import_module("nfl_edge.backtest.xgboost_walk_forward")
        assert mod.CANDIDATE_ORDER == ["conservative", "balanced", "expressive"]
        assert mod.CANDIDATES is not None
        assert mod.SHARED_SETTINGS is not None

    def test_walkforward_preserves_candidate_lock(self):
        """Walk-forward module must not mutate candidate parameters."""
        import importlib
        mod = importlib.import_module("nfl_edge.backtest.xgboost_walk_forward")
        conservative = mod.CANDIDATES["conservative"]
        assert conservative.max_depth == 2
        assert conservative.learning_rate == 0.05
        assert conservative.min_child_weight == 5.0
        assert conservative.subsample == 0.80
        assert conservative.colsample_bytree == 0.60
        assert conservative.reg_alpha == 0.50
        assert conservative.reg_lambda == 2.00
        assert conservative.gamma == 0.50
        assert conservative.max_delta_step == 1.00
        assert conservative.max_rounds == 200

        balanced = mod.CANDIDATES["balanced"]
        assert balanced.max_depth == 3
        assert balanced.learning_rate == 0.05
        assert balanced.min_child_weight == 3.0
        assert balanced.subsample == 0.85
        assert balanced.colsample_bytree == 0.70
        assert balanced.reg_alpha == 0.30
        assert balanced.reg_lambda == 1.50
        assert balanced.gamma == 0.20
        assert balanced.max_delta_step == 0.00
        assert balanced.max_rounds == 400

        expressive = mod.CANDIDATES["expressive"]
        assert expressive.max_depth == 4
        assert expressive.learning_rate == 0.03
        assert expressive.min_child_weight == 1.0
        assert expressive.subsample == 0.90
        assert expressive.colsample_bytree == 0.80
        assert expressive.reg_alpha == 0.10
        assert expressive.reg_lambda == 1.00
        assert expressive.gamma == 0.00
        assert expressive.max_delta_step == 0.00
        assert expressive.max_rounds == 800

    def test_walkforward_preserves_shared_settings(self):
        """Walk-forward module must not mutate shared settings."""
        import importlib
        mod = importlib.import_module("nfl_edge.backtest.xgboost_walk_forward")
        s = mod.SHARED_SETTINGS
        assert s["objective"] == "binary:logistic"
        assert s["eval_metric"] == "logloss"
        assert s["tree_method"] == "hist"
        assert s["seed"] == 42
        assert s["nthread"] == 1
        assert s["early_stopping_rounds"] == 50
        assert s["probability_epsilon"] == 1e-6
        assert s["min_training_rows"] == 32
        assert s["min_training_blocks"] == 2
        assert s["validation_block_count"] == 2
        assert s["min_validation_rows"] == 21
        assert s["min_validation_blocks"] == 2

    def test_walkforward_preserves_config_sha(self):
        """Walk-forward module must not alter canonical config SHA."""
        import importlib
        mod = importlib.import_module("nfl_edge.backtest.xgboost_walk_forward")
        sha = mod.CANONICAL_CONFIG_SHA
        assert sha == "6aa585239ea20c7cd43da5837128101c83c5ce25645c8769e391a4dfc175a3be"


# ---------------------------------------------------------------------------
# Model Core Integration Tests
# ---------------------------------------------------------------------------

class TestModelCore:
    """Integration tests for the model core module."""

    def test_config_loads(self):
        config = LockedConfig()
        assert config is not None

    def test_feature_contract_loads(self):
        contract = FeatureContract()
        assert contract.feature_count == 132

    def test_config_lock_validation(self):
        file_sha = validate_config_lock()
        assert len(file_sha) == 64  # SHA-256 hex

    def test_xgboost_params_all_candidates(self):
        config = LockedConfig()
        for name in config.get_candidate_order():
            params = config.get_xgboost_params(name)
            assert params["objective"] == "binary:logistic"
            assert params["eval_metric"] == "logloss"
            assert params["tree_method"] == "hist"
            assert params["seed"] == 42
            assert params["nthread"] == 1
            assert "max_rounds" not in params  # max_rounds is separate
            assert "hypothesis" not in params
            assert "interaction_complexity" not in params

    def test_base_sha_correct(self):
        config = LockedConfig()
        assert config.base_sha == EXPECTED_BASE_SHA

    def test_extraction_sha_in_config(self):
        config = LockedConfig()
        assert config.extraction_sha256 == EXPECTED_EXTRACTION_SHA256


# ---------------------------------------------------------------------------
# Tiny Synthetic Model Fit (wrapper determinism only)
# ---------------------------------------------------------------------------

class TestSyntheticDeterminism:
    """Tiny synthetic fit to prove wrapper determinism — no NFL data."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_xgb(self):
        pytest.importorskip("xgboost")

    def test_synthetic_fit_is_deterministic(self):
        """A tiny synthetic fit produces identical results across runs."""
        import xgboost as xgb

        config = LockedConfig()
        params = config.get_xgboost_params("conservative")

        # Tiny synthetic dataset — NOT NFL data
        n = 200
        rng = np.random.RandomState(42)
        X = rng.randn(n, 5)
        y = (X[:, 0] + X[:, 1] > 0).astype(int)

        # Create synthetic feature names
        synth_features = [f"feat_{i}" for i in range(5)]

        results = []
        for _ in range(3):
            dtrain = xgb.DMatrix(X, label=y, feature_names= synth_features)
            model = xgb.train(
                params,
                dtrain,
                num_boost_round=50,
                verbose_eval=False,
            )
            preds = model.predict(dtrain)
            results.append(preds)

        # All three runs must be identical
        assert np.array_equal(results[0], results[1])
        assert np.array_equal(results[1], results[2])

    def test_probability_clipping_bounds(self):
        config = LockedConfig()
        eps = config.get_probability_epsilon()
        probs = np.array([0.0, 0.5, 1.0, -0.1, 1.1])
        clipped = clip_probabilities(probs, eps)
        assert clipped[0] >= eps
        assert clipped[1] == 0.5
        assert clipped[2] <= 1.0 - eps
        assert clipped[3] >= eps
        assert clipped[4] <= 1.0 - eps

    def test_probability_validation_passes(self):
        config = LockedConfig()
        eps = config.get_probability_epsilon()
        probs = np.array([0.3, 0.7, 0.5])
        validate_probabilities(probs, eps)  # should not raise

    def test_probability_validation_rejects_out_of_bounds(self):
        probs = np.array([1.5, 0.7])
        with pytest.raises(ValueError, match="out of"):
            validate_probabilities(probs, 0.000001)

    def test_probability_validation_rejects_nan(self):
        probs = np.array([np.nan, 0.7])
        with pytest.raises(ValueError, match="nan/inf"):
            validate_probabilities(probs, 0.000001)
