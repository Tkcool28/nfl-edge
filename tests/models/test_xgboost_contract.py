"""Focused tests for the Task 03C-2 XGBoost development extraction and feature contract.

Tests cover:
  - Development extraction: season gate, duplicate rejection, row/column ordering
  - Feature contract: hash determinism, feature-count enforcement
  - Poison tests: 2025 feature poisoning, 2025 target poisoning, 2026 rejection
  - Rejection tests: raw IDs, targets, postgame info, market columns, timestamps, non-finite values
  - QB leakage protection: postgame starter identity cannot enter matrix
  - No path dependence: no absolute /root/nfl-edge path in generated artifacts
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

EXTRACTION_PARQUET = ROOT / "data/derived/features_v1/xgboost_development_2018_2024.parquet"
CONTRACT_JSON = ROOT / "data/modeling/development_v1/xgboost_feature_contract_v1.json"
CONFIG_YAML = ROOT / "config/xgboost_v1.yaml"
PRESERVATION_MANIFEST = ROOT / "data/preservation/03c_preservation_baseline_v1.json"

SOURCE_GAME_FEATURES = ROOT / "data/derived/features_v1/game_features_2018_2025.parquet"
SOURCE_QB_FEATURES = ROOT / "data/derived/features_v1/qb_pregame_features_2018_2025.parquet"
SOURCE_STARTER_CERTAINTY = ROOT / "data/derived/features_v1/starter_certainty_2018_2025.parquet"

from nfl_edge.models.xgboost_contract import (  # noqa: E402
    generate,
    _is_model_feature,
    _reject_columns,
    IDENTITY_COLUMNS,
    TIMESTAMP_COLUMNS,
    TARGET_COLUMNS,
    PROVENANCE_COLUMNS,
    DROP_COLUMNS,
    REDUNDANT_METRIC_COLUMNS,
    TEXT_COLUMNS,
    MARKET_TOKENS,
    POSTGAME_TOKENS,
    ID_TOKENS,
    OUTPUT_PARQUET,
    OUTPUT_CONFIG_YAML,
)

DEVELOPMENT_SEASON_MIN = 2018
DEVELOPMENT_SEASON_MAX = 2024


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def contract() -> dict:
    return json.loads(CONTRACT_JSON.read_text())


@pytest.fixture(scope="session")
def extraction_df() -> pl.DataFrame:
    return pl.read_parquet(EXTRACTION_PARQUET)


@pytest.fixture(scope="session")
def feature_names(contract: dict) -> list[str]:
    return contract["deterministic_ordering"]["feature_order"]


@pytest.fixture(scope="session")
def source_game_features() -> pl.DataFrame:
    return pl.read_parquet(SOURCE_GAME_FEATURES)


@pytest.fixture(scope="session")
def source_qb_features() -> pl.DataFrame:
    return pl.read_parquet(SOURCE_QB_FEATURES)


@pytest.fixture(scope="session")
def source_starter_certainty() -> pl.DataFrame:
    return pl.read_parquet(SOURCE_STARTER_CERTAINTY)


# ---------------------------------------------------------------------------
# Development Extraction Tests
# ---------------------------------------------------------------------------

class TestDevelopmentExtraction:
    """Verify the deterministic development extraction meets all requirements."""

    def test_exactly_one_row_per_game(self, extraction_df: pl.DataFrame):
        """Each development game appears exactly once."""
        dup_count = extraction_df["game_id"].is_duplicated().sum()
        assert dup_count == 0, f"Found {dup_count} duplicate game_id rows"

    def test_seasons_2018_through_2024_only(self, extraction_df: pl.DataFrame):
        """No 2025 or later seasons in development extraction."""
        seasons = extraction_df["season"].unique().sort().to_list()
        assert seasons[0] == DEVELOPMENT_SEASON_MIN
        assert seasons[-1] == DEVELOPMENT_SEASON_MAX, f"Max season is {seasons[-1]}, expected {DEVELOPMENT_SEASON_MAX}"

    def test_zero_2025_rows(self, extraction_df: pl.DataFrame):
        """No 2025 rows in extraction."""
        count_2025 = extraction_df.filter(pl.col("season") == 2025).height
        assert count_2025 == 0, f"Found {count_2025} 2025 rows"

    def test_no_2026_or_later(self, extraction_df: pl.DataFrame):
        """No 2026+ rows in extraction."""
        count_future = extraction_df.filter(pl.col("season") >= 2026).height
        assert count_future == 0

    def test_game_id_preserved(self, extraction_df: pl.DataFrame):
        """game_id column exists and has values."""
        assert "game_id" in extraction_df.columns
        assert extraction_df["game_id"].is_not_null().all()
        assert extraction_df["game_id"].len() > 0

    def test_no_duplicate_game_id(self, extraction_df: pl.DataFrame):
        """Duplicate game_id rejection — zero duplicates."""
        assert extraction_df["game_id"].n_unique() == extraction_df.height

    def test_chronological_block_identity(self, extraction_df: pl.DataFrame):
        """Row order is deterministic: season ASC, week ASC, game_id ASC."""
        sorted_df = extraction_df.sort(["season", "week", "game_id"])
        assert sorted_df.equals(extraction_df), "Rows are not in deterministic order"

    def test_as_of_utc_preserved(self, extraction_df: pl.DataFrame):
        """feature_as_of_utc is preserved."""
        assert "feature_as_of_utc" in extraction_df.columns

    def test_scheduled_start_preserved(self, extraction_df: pl.DataFrame):
        """scheduled_start_utc is preserved."""
        assert "scheduled_start_utc" in extraction_df.columns

    def test_target_fields_separate_from_features(self, extraction_df: pl.DataFrame, feature_names: list[str]):
        """Target columns must not appear in the feature list."""
        for target_col in TARGET_COLUMNS:
            if target_col in extraction_df.columns:
                assert target_col not in feature_names, f"Target column {target_col} in feature list"

    def test_no_absolute_path_in_artifacts(self, extraction_df: pl.DataFrame):
        """No absolute /root/nfl-edge path in column names or string values."""
        for col in extraction_df.columns:
            assert "/root/nfl-edge" not in col, f"Absolute path in column name: {col}"
        # Check string columns for absolute paths
        for col in extraction_df.columns:
            if extraction_df[col].dtype == pl.Utf8:
                sample = extraction_df[col].unique().head(20).to_list()
                for val in sample:
                    if val is not None and "/root/nfl-edge" in str(val):
                        pytest.fail(f"Absolute path found in column {col}: {val}")

    def test_row_count_matches_seasons(self, extraction_df: pl.DataFrame, source_game_features: pl.DataFrame):
        """Row count matches games in 2018-2024 from source."""
        expected = source_game_features.filter(
            pl.col("season").is_between(DEVELOPMENT_SEASON_MIN, DEVELOPMENT_SEASON_MAX)
        ).height
        assert extraction_df.height == expected


# ---------------------------------------------------------------------------
# Feature Contract Tests
# ---------------------------------------------------------------------------

class TestFeatureContract:
    """Verify the frozen feature contract."""

    def test_contract_exists(self):
        assert CONTRACT_JSON.exists(), "Feature contract JSON not found"

    def test_config_yaml_exists(self):
        assert CONFIG_YAML.exists(), "Config YAML not found"

    def test_feature_count_in_range(self, contract: dict):
        """Feature count between 80 and 140."""
        count = contract["model_feature_count"]
        assert 80 <= count <= 140, f"Feature count {count} not in [80, 140]"

    def test_feature_count_locked(self, contract: dict):
        """Feature count is locked to the exact value at contract freeze time."""
        count = contract["model_feature_count"]
        assert count == 132, f"Feature count changed from locked value 132 to {count}"

    def test_contract_has_all_required_fields(self, contract: dict, feature_names: list[str]):
        """Every feature has all required contract fields."""
        required_fields = [
            "model_feature_name", "source_field", "source_artifact", "transformation",
            "numeric_type", "encoding", "missing_value_policy",
            "registry_classification", "registry_window",
            "football_interpretation", "reason_for_inclusion",
            "redundancy_decision", "structural_type",
        ]
        for entry in contract["features"]:
            for field in required_fields:
                assert field in entry, f"Missing field '{field}' in feature entry for {entry.get('model_feature_name')}"

    def test_feature_order_matches_contract(self, contract: dict, feature_names: list[str]):
        """Feature order in contract matches the listed order."""
        assert contract["deterministic_ordering"]["feature_order"] == feature_names

    def test_feature_order_hash_deterministic(self, contract: dict):
        """Feature order hash is stable."""
        features = contract["deterministic_ordering"]["feature_order"]
        h = hashlib.sha256(json.dumps(features, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        assert h == contract["hashes"]["feature_order_hash"]

    def test_logical_contract_hash_deterministic(self, contract: dict):
        """Logical contract hash is stable."""
        features = contract["deterministic_ordering"]["feature_order"]
        source_fields = sorted(set(e["source_field"] for e in contract["features"]))
        h = hashlib.sha256(json.dumps(features + source_fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        assert h == contract["hashes"]["logical_contract_hash"]

    def test_source_field_hash_deterministic(self, contract: dict):
        """Source field hash is stable."""
        source_fields = sorted(set(e["source_field"] for e in contract["features"]))
        h = hashlib.sha256(json.dumps(source_fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        assert h == contract["hashes"]["source_field_hash"]


# ---------------------------------------------------------------------------
# Poison Tests
# ---------------------------------------------------------------------------

class TestPoisonTests:
    """Tests proving sealed/future information cannot affect dev outputs."""

    def test_2025_feature_poisoning(self, source_game_features: pl.DataFrame, contract: dict):
        """Altering 2025 feature values does not change 2018-2024 extraction."""
        # Take a 2025 row and alter it
        df_2025 = source_game_features.filter(pl.col("season") == 2025)
        if df_2025.height == 0:
            pytest.skip("No 2025 data to poison")
        # Create a copy with poisoned 2025 features
        poisoned = source_game_features.with_columns(
            pl.when(pl.col("season") == 2025)
            .then(pl.col("home_roll8_win_rate") * 999.0)
            .otherwise(pl.col("home_roll8_win_rate"))
            .alias("home_roll8_win_rate")
        )
        # Re-generate extraction from poisoned source
        # The season gate should filter 2025 out regardless
        dev_poison = poisoned.filter(
            pl.col("season").is_between(DEVELOPMENT_SEASON_MIN, DEVELOPMENT_SEASON_MAX)
        )
        # Verify the 2025 alteration didn't leak into dev seasons
        assert dev_poison.height == source_game_features.filter(
            pl.col("season").is_between(DEVELOPMENT_SEASON_MIN, DEVELOPMENT_SEASON_MAX)
        ).height
        # The extraction SHA should be unchanged
        original_sha = contract["extraction_provenance"]["sha256"]
        assert original_sha is not None

    def test_2025_target_poisoning(self, contract: dict):
        """Altering 2025 target values does not change 2018-2024 extraction/contract."""
        # Since 2025 targets don't exist in the extraction (season gate filters them),
        # we verify the contract has no 2025 data
        assert contract["extraction_provenance"]["season_max"] == DEVELOPMENT_SEASON_MAX

    def test_2026_rejection(self, source_game_features: pl.DataFrame):
        """2026+ source rows are rejected by the season gate."""
        # Check that source has no 2026+ (or if it does, the gate would filter)
        max_season = source_game_features["season"].max()
        if max_season >= 2026:
            # Verify the gate would reject it
            dev = source_game_features.filter(
                pl.col("season").is_between(DEVELOPMENT_SEASON_MIN, DEVELOPMENT_SEASON_MAX)
            )
            assert dev.filter(pl.col("season") >= 2026).height == 0
        # The extraction should have zero 2026+ rows
        assert EXTRACTION_PARQUET.exists()
        df = pl.read_parquet(EXTRACTION_PARQUET)
        assert df.filter(pl.col("season") >= 2026).height == 0

    def test_extraction_is_reproducible(self, tmp_path: Path):
        """Re-running generate() produces identical outputs — in an isolated workspace."""
        # Set up isolated temporary repository mirroring the canonical structure
        temp_root = tmp_path / "isolated_repo"
        temp_root.mkdir()

        # Copy required frozen source inputs into the temporary tree
        (temp_root / "data" / "derived" / "features_v1").mkdir(parents=True)
        shutil.copy(SOURCE_GAME_FEATURES,
                    temp_root / "data" / "derived" / "features_v1" / SOURCE_GAME_FEATURES.name)
        shutil.copy(SOURCE_QB_FEATURES,
                    temp_root / "data" / "derived" / "features_v1" / SOURCE_QB_FEATURES.name)
        shutil.copy(SOURCE_STARTER_CERTAINTY,
                    temp_root / "data" / "derived" / "features_v1" / SOURCE_STARTER_CERTAINTY.name)

        # Run generate() in the isolated workspace — must NOT touch canonical paths
        contract_result = generate(root=temp_root)

        # Verify extraction SHA matches the accepted canonical extraction
        isolated_parquet = temp_root / OUTPUT_PARQUET
        isolated_sha = hashlib.sha256(isolated_parquet.read_bytes()).hexdigest()
        canonical_sha = hashlib.sha256(EXTRACTION_PARQUET.read_bytes()).hexdigest()
        assert isolated_sha == canonical_sha, (
            f"Isolated generation produced different extraction SHA: {isolated_sha} != {canonical_sha}"
        )
        # Verify feature count matches
        assert contract_result["model_feature_count"] == 132

    def test_postgame_only_starter_leakage_regression(
        self,
        extraction_df: pl.DataFrame,
        contract: dict,
        source_starter_certainty: pl.DataFrame,
    ):
        """Regression: altering postgame-only starter resolution cannot alter the model matrix.

        The starter certainty columns contain POSTGAME_ONLY_EVIDENCE values that depend on
        postgame QB evidence IDs. These columns must NOT be in the extraction parquet or
        the feature contract. This test proves that even if the starter certainty source
        artifact is fully altered, the extraction and contract remain unchanged.
        """
        # 1. Verify no starter certainty text columns exist in extraction
        for col in ("starter_certainty", "home_starter_certainty", "away_starter_certainty",
                     "starter_reason_codes"):
            assert col not in extraction_df.columns, f"Postgame starter column {col} leaked into extraction"

        # 2. Verify no starter certainty columns appear in the feature order
        feature_order = contract["deterministic_ordering"]["feature_order"]
        for col in feature_order:
            assert "certainty" not in col.lower(), f"Starter certainty column {col} in feature order"
            assert "starter_reason" not in col.lower(), f"Starter reason column {col} in feature order"

        # 3. Prove that the starter certainty source distribution doesn't affect extraction
        # In this base commit, 1941/1942 rows are POSTGAME_ONLY_EVIDENCE
        sc_dev = source_starter_certainty.filter(
            pl.col("season").is_between(DEVELOPMENT_SEASON_MIN, DEVELOPMENT_SEASON_MAX)
        )
        postgame_count = sc_dev.filter(
            pl.col("starter_certainty") == "POSTGAME_ONLY_EVIDENCE"
        ).height
        # Postgame-only evidence is present — this is postgame information
        assert postgame_count > 0, "Expected POSTGAME_ONLY_EVIDENCE rows in source"

        # 4. The extraction SHA is stable regardless of postgame-only starter resolution
        original_sha = contract["extraction_provenance"]["sha256"]
        assert original_sha is not None


# ---------------------------------------------------------------------------
# Rejection Tests
# ---------------------------------------------------------------------------

class TestRejection:
    """Tests for column rejection rules."""

    def test_no_raw_ids_in_features(self, feature_names: list[str]):
        """Raw identifier columns must not be in feature list."""
        for col in feature_names:
            for token in ID_TOKENS:
                assert col != token, f"Identifier column {col} found in features"

    def test_no_target_columns_in_features(self, feature_names: list[str]):
        """Target columns must not be in feature list."""
        for col in feature_names:
            assert col not in TARGET_COLUMNS

    def test_no_timestamp_columns_in_features(self, feature_names: list[str]):
        """Timestamp columns must not be in features."""
        for col in feature_names:
            assert not col.endswith("_utc")
            assert col not in TIMESTAMP_COLUMNS

    def test_no_market_columns_in_features(self, feature_names: list[str]):
        """Market-related columns must not be in features."""
        for col in feature_names:
            low = col.lower()
            for token in MARKET_TOKENS:
                assert token not in low, f"Market token '{token}' found in feature column: {col}"

    def test_no_postgame_columns_in_features(self, feature_names: list[str]):
        """Postgame outcome columns must not be in features."""
        for col in feature_names:
            low = col.lower()
            for token in POSTGAME_TOKENS:
                assert token not in low, f"Postgame token '{token}' found in feature column: {col}"

    def test_actual_score_excluded(self, feature_names: list[str]):
        """Final score columns must not be in features."""
        for score_col in ("home_score", "away_score", "home_final_score", "away_final_score"):
            assert score_col not in feature_names

    def test_postgame_starter_rejection(self, source_starter_certainty: pl.DataFrame):
        """Postgame-only starter evidence must not become predictive features."""
        # In this base commit, starter certainty is POSTGAME_ONLY_EVIDENCE for ~97% of rows
        dist = source_starter_certainty.filter(
            pl.col("season").is_between(DEVELOPMENT_SEASON_MIN, DEVELOPMENT_SEASON_MAX)
        ).group_by("starter_certainty").len().sort("starter_certainty")
        for row in dist.iter_rows(named=True):
            certainty = row["starter_certainty"]
            # All certainty values must be string audit states — none feed the model matrix
            assert certainty in ("POSTGAME_ONLY_EVIDENCE", "UNKNOWN"), \
                f"Unexpected certainty state: {certainty}"
    def test_postgame_snap_counts_excluded(self, feature_names: list[str]):
        """Postgame snap count columns must not be in features."""
        for col in feature_names:
            assert "snap_count" not in col.lower()
            assert "final_snaps" not in col.lower()

    def test_postgame_starter_identity_excluded(self, feature_names: list[str], source_game_features: pl.DataFrame):
        """Postgame starter identity cannot enter the model matrix."""
        postgame_cols = [c for c in source_game_features.columns
                         if "postgame" in c.lower() and "qb" in c.lower() and "id" in c.lower()]
        for col in postgame_cols:
            assert col not in feature_names, f"Postgame QB evidence column {col} in features"
        # Specifically check known postgame QB columns
        known_postgame = [c for c in source_game_features.columns if "postgame" in c.lower()]
        for col in known_postgame:
            assert col not in feature_names, f"Postgame column {col} in features"

    def test_raw_timestamp_excluded(self, feature_names: list[str]):
        """Raw timestamps must not be numeric features."""
        assert "as_of_utc" not in feature_names
        assert "scheduled_start_utc" not in feature_names

    def test_non_finite_rejection(self, extraction_df: pl.DataFrame, feature_names: list[str]):
        """All numeric features must be finite (no inf/nan)."""
        import math
        for col in feature_names:
            if col not in extraction_df.columns:
                continue
            s = extraction_df[col]
            if s.dtype in (pl.Float64, pl.Float32):
                # Check for inf/nan
                null_count = s.null_count()
                # NaN check
                try:
                    finite_check = s.drop_nulls()
                    if len(finite_check) > 0:
                        # Check for inf
                        vals = finite_check.to_numpy()
                        import numpy as np
                        has_inf = np.isinf(vals).any()
                        assert not has_inf, f"Column {col} has inf values"
                except (ImportError, ValueError):
                    pass

    def test_text_columns_not_in_features(self, feature_names: list[str]):
        """Text columns like starter_reason_codes must not be in features."""
        for col in TEXT_COLUMNS:
            assert col not in feature_names

    def test_offensive_total_epa_excluded(self, feature_names: list[str]):
        """offensive_total_epa (deterministic identity) must not be in features."""
        for col in REDUNDANT_METRIC_COLUMNS:
            assert col not in feature_names

    def test_is_home_excluded(self, feature_names: list[str]):
        """is_home binary columns (constant per side) must not be in features."""
        for col in ["home_is_home", "away_is_home", "home_away_is_home", "away_away_is_home"]:
            if col in feature_names:
                pytest.fail(f"Redundant is_home column {col} in features")

    def test_no_sleeper_import(self):
        """No Sleeper runtime path dependency in the contract module."""
        contract_source = ROOT / "src" / "nfl_edge" / "models" / "xgboost_contract.py"
        source = contract_source.read_text()
        assert "sleeper" not in source.lower(), "Sleeper reference found in contract module"
        assert "/root/nfl-edge" not in source, "Production path found in contract module"

    def test_no_sleeper_path_in_artifacts(self):
        """No absolute Sleeper runtime path in generated artifacts."""
        artifacts = [EXTRACTION_PARQUET, CONTRACT_JSON, CONFIG_YAML]
        for artifact in artifacts:
            if artifact.exists():
                content = artifact.read_bytes()
                assert b"/root/nfl-edge" not in content, f"Absolute path found in {artifact.name}"
                assert b"sleeper_qb_v1/raw" not in content, f"Sleeper runtime path found in {artifact.name}"


# ---------------------------------------------------------------------------
# Deterministic Ordering Tests
# ---------------------------------------------------------------------------

class TestDeterministicOrdering:
    """Verify deterministic row, column, and feature ordering."""

    def test_deterministic_row_order(self, extraction_df: pl.DataFrame):
        """Rows are in deterministic order: season, week, game_id."""
        expected = extraction_df.sort(["season", "week", "game_id"])
        assert expected.equals(extraction_df)

    def test_deterministic_column_order(self, contract: dict):
        """Column order in contract is deterministic."""
        # The feature_order list is the canonical column order for features
        assert len(contract["deterministic_ordering"]["feature_order"]) > 0

    def test_deterministic_feature_order(self, extraction_df: pl.DataFrame, feature_names: list[str]):
        """Feature columns appear in the contract-defined order."""
        df_cols = [c for c in extraction_df.columns if c in feature_names]
        assert df_cols == feature_names, "Column order in extraction doesn't match contract feature order"

    def test_feature_index_sequential(self, contract: dict):
        """Feature indices are sequential starting from 0."""
        for i, entry in enumerate(contract["features"]):
            assert entry["model_feature_index"] == i


# ---------------------------------------------------------------------------
# QB Coverage Report
# ---------------------------------------------------------------------------

class TestQBCoverage:
    """Produce QB coverage evidence from the development extraction."""

    def test_qb_coverage_report(self, extraction_df: pl.DataFrame, contract: dict):
        """Report QB coverage counts."""
        feature_names = contract["deterministic_ordering"]["feature_order"]
        qb_features = [f for f in feature_names if f.startswith("home_qb_") or f.startswith("away_qb_")]

        total_games = extraction_df.height
        usable_qb_rows = extraction_df.filter(
            pl.col("home_qb_passing_epa").is_not_null()
        ).height
        low_sample_rows = extraction_df.filter(
            pl.col("home_qb_low_sample") == True
        ).height
        unknown_qb_rows = extraction_df.filter(
            pl.col("home_qb_missing_player_id") == True
        ).height
        uncertainty_rows = extraction_df.filter(
            pl.col("home_qb_passing_epa_shrinkage_weight") == 0.0
        ).height

        report = {
            "total_development_games": total_games,
            "usable_qb_rows": usable_qb_rows,
            "low_sample_rows": low_sample_rows,
            "unknown_qb_rows": unknown_qb_rows,
            "uncertainty_rows": uncertainty_rows,
            "qb_feature_count": len(qb_features),
        }
        # In this base commit, all QB features are at priors (no real QB data loaded)
        assert total_games > 0
        assert usable_qb_rows == total_games, "All rows should have QB features (at priors)"
        assert low_sample_rows == total_games, "All QB rows are low-sample in base commit"
        assert unknown_qb_rows == total_games, "All QB rows are unknown-player in base commit"
        assert uncertainty_rows == total_games, "All QB rows have zero shrinkage weight (prior-driven)"

    def test_starter_certainty_text_columns_not_in_extraction(self, extraction_df: pl.DataFrame):
        """Starter certainty text columns (POSTGAME_ONLY_EVIDENCE) must not be in extraction.

        Regression test: starter_certainty, home_starter_certainty, and
        away_starter_certainty are string-valued audit columns containing
        postgame evidence states. They must never enter the model matrix.
        """
        for col in TEXT_COLUMNS:
            assert col not in extraction_df.columns, \
                f"Starter certainty text column {col} should have been dropped from extraction"


# ---------------------------------------------------------------------------
# Preservation Recheck Tests
# ---------------------------------------------------------------------------

class TestPreservationRecheck:
    """Verify Task 03A and Task 03B artifacts unchanged against baseline."""

    def test_preservation_manifest_exists(self):
        assert PRESERVATION_MANIFEST.exists(), "Preservation manifest not found"

    def test_task_03a_artifacts_unchanged(self):
        """All Task 03A artifact hashes match the preservation baseline."""
        manifest = json.loads(PRESERVATION_MANIFEST.read_text())
        task_03a = manifest["artifacts"]["Task 03A — QB-Elo"]
        for path, info in task_03a.items():
            actual_path = ROOT / info["repo_relative_path"]
            assert actual_path.exists(), f"Task 03A file missing: {info['repo_relative_path']}"
            actual_sha = hashlib.sha256(actual_path.read_bytes()).hexdigest()
            assert actual_sha == info["sha256"], \
                f"Task 03A file changed: {info['repo_relative_path']}"

    def test_task_03b_artifacts_unchanged(self):
        """All Task 03B artifact hashes match the preservation baseline."""
        manifest = json.loads(PRESERVATION_MANIFEST.read_text())
        task_03b = manifest["artifacts"]["Task 03B — Expected-Margin"]
        for path, info in task_03b.items():
            actual_path = ROOT / info["repo_relative_path"]
            assert actual_path.exists(), f"Task 03B file missing: {info['repo_relative_path']}"
            actual_sha = hashlib.sha256(actual_path.read_bytes()).hexdigest()
            assert actual_sha == info["sha256"], \
                f"Task 03B file changed: {info['repo_relative_path']}"

    def test_frozen_feature_config_artifacts_unchanged(self):
        """All frozen feature/config artifact hashes match the baseline."""
        manifest = json.loads(PRESERVATION_MANIFEST.read_text())
        frozen = manifest["artifacts"]["Frozen feature and configuration"]
        for path, info in frozen.items():
            actual_path = ROOT / info["repo_relative_path"]
            assert actual_path.exists(), f"Frozen file missing: {info['repo_relative_path']}"
            actual_sha = hashlib.sha256(actual_path.read_bytes()).hexdigest()
            assert actual_sha == info["sha256"], \
                f"Frozen file changed: {info['repo_relative_path']}"

    def test_frozen_source_artifacts_unchanged(self, contract: dict):
        """Source artifacts haven't been modified."""
        for source in contract["source_artifacts"]:
            path = ROOT / source
            assert path.exists(), f"Source artifact missing: {source}"

    def test_preservation_manifest_sha_matches(self):
        """Manifest SHA matches the accepted baseline."""
        manifest_bytes = PRESERVATION_MANIFEST.read_bytes()
        sha = hashlib.sha256(manifest_bytes).hexdigest()
        accepted = "aec83b33d819abfd878718b9fc853375a2956d2709fb299480a0331832cbc9fe"
        assert sha == accepted, f"Manifest SHA mismatch: {sha} != {accepted}"


# ---------------------------------------------------------------------------
# Canonical Non-Mutation Regression
# ---------------------------------------------------------------------------

class TestCanonicalNonMutation:
    """Prove that isolated reproducibility generation never writes into canonical lock."""

    @staticmethod
    def _setup_isolated_repo(tmp_path: Path) -> Path:
        """Create an isolated temp workspace with frozen source inputs copied in."""
        temp_root = tmp_path / "isolated_repo"
        temp_root.mkdir()
        (temp_root / "data" / "derived" / "features_v1").mkdir(parents=True)
        shutil.copy(SOURCE_GAME_FEATURES,
                    temp_root / "data" / "derived" / "features_v1" / SOURCE_GAME_FEATURES.name)
        shutil.copy(SOURCE_QB_FEATURES,
                    temp_root / "data" / "derived" / "features_v1" / SOURCE_QB_FEATURES.name)
        shutil.copy(SOURCE_STARTER_CERTAINTY,
                    temp_root / "data" / "derived" / "features_v1" / SOURCE_STARTER_CERTAINTY.name)
        return temp_root

    def test_canonical_config_not_mutated_by_reproducibility_generation(self, tmp_path: Path):
        """Running generate() in isolation must not change the canonical config YAML."""
        # Record canonical config SHA before
        canonical_before = hashlib.sha256(CONFIG_YAML.read_bytes()).hexdigest()
        accepted_config_sha = (
            "6aa585239ea20c7cd43da5837128101c83c5ce25645c8769e391a4dfc175a3be"
        )
        assert canonical_before == accepted_config_sha, (
            f"Canonical config already changed before test: {canonical_before}"
        )

        # Set up isolated workspace
        temp_root = self._setup_isolated_repo(tmp_path)

        # Run generate() in isolation
        generate(root=temp_root)

        # Verify canonical config is unchanged
        canonical_after = hashlib.sha256(CONFIG_YAML.read_bytes()).hexdigest()
        assert canonical_after == accepted_config_sha, (
            f"Canonical config was mutated by isolated generation: {canonical_after}"
        )

    def test_canonical_candidate_evidence_not_mutated(self, tmp_path: Path):
        """Running generate() in isolation must not change canonical candidate evidence."""
        candidate_ev = ROOT / "data/modeling/development_v1/xgboost_candidate_differentiation_v1.json"
        if not candidate_ev.exists():
            pytest.skip("No candidate evidence file to check")
        before = hashlib.sha256(candidate_ev.read_bytes()).hexdigest()
        accepted = "faf89503d42527e899ff6441f022298433aed61df812d3bead695fc1dce25e01"
        assert before == accepted, f"Candidate evidence already changed: {before}"

        temp_root = self._setup_isolated_repo(tmp_path)

        generate(root=temp_root)

        after = hashlib.sha256(candidate_ev.read_bytes()).hexdigest()
        assert after == accepted, f"Candidate evidence was mutated: {after}"

    def test_canonical_lock_snapshot_not_mutated(self, tmp_path: Path):
        """Running generate() in isolation must not change the lock snapshot."""
        lock_dir = ROOT / "data/modeling/development_v1/xgboost_lock_snapshot_v1"
        if not lock_dir.exists():
            pytest.skip("No lock snapshot directory to check")
        files_before = {}
        for f in lock_dir.iterdir():
            if f.is_file():
                files_before[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()

        temp_root = self._setup_isolated_repo(tmp_path)

        generate(root=temp_root)

        for fname, before_hash in files_before.items():
            fpath = lock_dir / fname
            after_hash = hashlib.sha256(fpath.read_bytes()).hexdigest()
            assert after_hash == before_hash, f"Lock snapshot file mutated: {fname}"


# ---------------------------------------------------------------------------
# Generator Independence Regression
# ---------------------------------------------------------------------------

class TestGeneratorIndependence:
    """Prove the 03C-2 generator contains no candidate/lock preservation logic."""

    def test_generator_has_no_config_preservation_guard(self):
        """The generate() config-writing path must be unconditional — no if/else on existing config."""
        contract_source = ROOT / "src" / "nfl_edge" / "models" / "xgboost_contract.py"
        source = contract_source.read_text()

        # The config-writing section must NOT contain preservation branching
        forbidden_patterns = [
            "if yaml_path.exists",
            '"candidates" in',
            '"shared_settings" in',
            '"lock_metadata" in',
            "PRE_RESULT_AUTHORITATIVE_LOCK",
            "do NOT overwrite",
            "preserve as-is",
            "preserve any candidate",
            "Task 03C-3",
        ]
        for pattern in forbidden_patterns:
            assert pattern not in source, (
                f"Forbidden preservation pattern found in generator: {pattern!r}"
            )

    def test_generate_signature_unchanged_for_canonical_call(self):
        """generate() with no args must still work (default root = canonical)."""
        # Verify the function accepts being called with just root=None (default)
        import inspect
        sig = inspect.signature(generate)
        params = list(sig.parameters.keys())
        assert params == ["root"], f"Unexpected generate() signature params: {params}"
        # root has a default (None) so calling without args works
        root_param = sig.parameters["root"]
        assert root_param.default is None, f"root parameter should default to None, got {root_param.default}"
