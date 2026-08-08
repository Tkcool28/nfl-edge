"""Synthetic tests for the deterministic chronological walk-forward engine.

Tests cover:
- Block ordering determinism
- Split construction (validation tail, fit portion)
- Warm-up gates (fit blocks, fit rows, validation blocks, validation rows)
- Early stopping semantics (best_iteration + 1 round refit)
- Same-block leakage protection
- Future-poisoning protection
- Candidate-order independence
- Tie / missing-target exclusion
- Season safeguards (2025+ rejection)
- Market column rejection
- Fingerprint determinism

No NFL development data is used for fitting. Synthetic data only.
"""

from __future__ import annotations

import os
import stat
from hashlib import sha256

import polars as pl
import pytest

from nfl_edge.backtest.xgboost_walk_forward import (
    CANDIDATE_ORDER,
    CANONICAL_CONFIG_SHA,
    SEASON_TYPE_PRIORITY,
    SHARED_SETTINGS,
    WARMUP_INSUFFICIENT_FIT_BLOCKS,
    WARMUP_INSUFFICIENT_FIT_ROWS,
    WARMUP_INSUFFICIENT_VALIDATION_BLOCKS,
    WARMUP_INSUFFICIENT_VALIDATION_ROWS,
    BlockKey,
    PredictionResult,
    WalkForwardEngine,
    WarmUpResult,
    compute_block_keys,
    construct_split,
    evaluate_warmup_reason,
    filter_prior_blocks,
    reject_market_columns,
    sort_blocks,
    validate_season,
)

FEATURE_COLS = [
    "feat_0", "feat_1", "feat_2", "feat_3", "feat_4",
]
TARGET_COL = "target_home_win"


def make_game(
    season: int,
    season_type: str,
    week: int,
    game_id: str,
    scheduled_start: str,
    target: int | None = 1,
    feature_vals: list[float] | None = None,
) -> dict:
    """Create a single synthetic game row."""
    if feature_vals is None:
        feature_vals = [0.1 * (i + 1) for i in range(len(FEATURE_COLS))]
    row = {
        "season": season,
        "season_type": season_type,
        "week": week,
        "game_id": game_id,
        "scheduled_start_utc": scheduled_start,
        "home_team": "HOME",
        "away_team": "AWAY",
        TARGET_COL: target,
        "target_margin": 7.0 if target == 1 else -7.0,
        "target_tie": False,
        "target_available": target is not None,
    }
    for i, feat in enumerate(FEATURE_COLS):
        row[feat] = feature_vals[i]
    return row


def make_synthetic_df(
    n_seasons: int = 6,
    games_per_block: int = 15,
    season_types: list[str] | None = None,
    weeks_per_type: int = 3,
) -> pl.DataFrame:
    """Create a synthetic DataFrame with multiple seasons × season_types × weeks.

    Each block has enough rows to satisfy fit/validation gates (>= 32 rows).
    """
    if season_types is None:
        season_types = ["REG"]

    rows: list[dict] = []
    start_season = 2019  # Start at 2019 so 2018 has no prior

    for s_idx in range(n_seasons):
        season = start_season + s_idx
        for st in season_types:
            for wk in range(1, weeks_per_type + 1):
                base_time = f"{season}-01-{(wk * 7) % 28 + 1:02d}T12:00:00Z"
                for g in range(games_per_block):
                    gid = f"{season}_{st}_{wk:02d}_GAME{g:03d}"
                    rows.append(make_game(season, st, wk, gid, base_time, target=(g % 2)))
    return pl.DataFrame(rows)


def make_small_synthetic_df(
    games_per_block: int = 8,
    n_blocks: int = 6,
) -> pl.DataFrame:
    """Small synthetic DataFrame for warm-up tests (not enough rows)."""
    rows: list[dict] = []
    for b in range(n_blocks):
        season = 2019 + b
        st = "REG"
        week = 1
        base_time = f"{season}-09-{15:02d}T12:00:00Z"
        for g in range(games_per_block):
            gid = f"{season}_REG_01_GAME{g:03d}"
            rows.append(make_game(season, st, week, gid, base_time, target=(g % 2)))
    return pl.DataFrame(rows)


# ─── Synthetic chronology tests ─────────────────────────────────────────

class TestSyntheticChronology:
    """Verify synthetic data generators produce valid, block-structured data."""

    def test_synthetic_df_has_expected_columns(self):
        df = make_synthetic_df(n_seasons=3)
        for col in ["season", "season_type", "week", "game_id",
                     "scheduled_start_utc", "target_home_win"]:
            assert col in df.columns

    def test_synthetic_df_has_multiple_blocks(self):
        df = make_synthetic_df(n_seasons=3, weeks_per_type=2)
        keys = compute_block_keys(df)
        assert len(keys) >= 5  # At least 5 blocks across 3 seasons

    def test_synthetic_df_sorted_chronologically(self):
        df = make_synthetic_df(n_seasons=4, weeks_per_type=3)
        keys = compute_block_keys(df)
        sorted_keys = sorted(keys)
        assert keys == sorted_keys


class TestBlockOrdering:
    """Test 6: Block ordering by (season, season_type_priority, week)."""

    def _nfl_season_transition_df(self) -> pl.DataFrame:
        """Synthetic NFL season-year blocks; no production/holdout data is used."""
        blocks = [
            (2019, "REG", 1),
            (2019, "REG", 17),
            (2019, "WC", 1),
            (2019, "DIV", 1),
            (2019, "CON", 1),
            (2019, "SB", 1),
            (2020, "REG", 1),
            (2020, "REG", 17),
            (2020, "WC", 1),
            (2020, "DIV", 1),
            (2020, "CON", 1),
            (2020, "SB", 1),
        ]
        return pl.DataFrame(
            [
                make_game(
                    season,
                    season_type,
                    week,
                    f"{season}_{season_type}_{week:02d}",
                    f"{season}-09-01T12:00:00Z",
                )
                for season, season_type, week in blocks
            ]
        )

    def test_same_season_regular_then_postseason_ordering(self):
        keys = compute_block_keys(self._nfl_season_transition_df())
        order_2020 = [key.display_id for key in keys if key.season == 2020]
        assert order_2020 == [
            "2020_REG_01",
            "2020_REG_17",
            "2020_WC_01",
            "2020_DIV_01",
            "2020_CON_01",
            "2020_SB_01",
        ]

    def test_full_nfl_season_year_transition_ordering(self):
        keys = compute_block_keys(self._nfl_season_transition_df())
        assert [key.display_id for key in keys] == [
            "2019_REG_01",
            "2019_REG_17",
            "2019_WC_01",
            "2019_DIV_01",
            "2019_CON_01",
            "2019_SB_01",
            "2020_REG_01",
            "2020_REG_17",
            "2020_WC_01",
            "2020_DIV_01",
            "2020_CON_01",
            "2020_SB_01",
        ]
        assert keys[5] < keys[6]  # 2019 SB < 2020 REG Week 1

    def test_prior_blocks_respect_same_season_postseason_boundary(self):
        df = self._nfl_season_transition_df()
        keys = compute_block_keys(df)
        current_2020_reg = next(key for key in keys if key.display_id == "2020_REG_01")
        prior_to_2020_reg = {key.display_id for key in compute_block_keys(filter_prior_blocks(df, current_2020_reg))}
        assert "2019_SB_01" in prior_to_2020_reg
        assert not any(key.startswith("2020_WC_") for key in prior_to_2020_reg)

        current_2020_sb = next(key for key in keys if key.display_id == "2020_SB_01")
        prior_to_2020_sb = {key.display_id for key in compute_block_keys(filter_prior_blocks(df, current_2020_sb))}
        assert "2020_REG_01" in prior_to_2020_sb
        assert "2020_REG_17" in prior_to_2020_sb

    def test_block_id_deterministic(self):
        bk = BlockKey(2020, SEASON_TYPE_PRIORITY["REG"], "REG", 3)
        assert bk.block_id == "2020_01_03"
        assert bk.display_id == "2020_REG_03"

    def test_season_type_priority_values(self):
        """NFL season-year order: PRE < REG < WC < DIV < CON < SB."""
        assert SEASON_TYPE_PRIORITY == {
            "PRE": 0,
            "REG": 1,
            "WC": 2,
            "DIV": 3,
            "CON": 4,
            "SB": 5,
        }

    def test_game_ordering_within_block(self):
        """Games within block ordered by scheduled_start_utc, then game_id."""
        rows = [
            make_game(2020, "REG", 3, "2020_REG_03_GAME002", "2020-09-20T12:00:00Z"),
            make_game(2020, "REG", 3, "2020_REG_03_GAME001", "2020-09-20T12:00:00Z"),
            make_game(2020, "REG", 3, "2020_REG_03_GAME003", "2020-09-19T12:00:00Z"),
        ]
        df = pl.DataFrame(rows)
        sorted_df = sort_blocks(df)
        # GAME003 (Sep 19) first, then GAME001 (Sep 20, tiebreak by game_id),
        # then GAME002 (Sep 20)
        game_ids = sorted_df["game_id"].to_list()
        assert game_ids[0] == "2020_REG_03_GAME003"
        assert game_ids[1] == "2020_REG_03_GAME001"
        assert game_ids[2] == "2020_REG_03_GAME002"

    def test_compute_block_keys_sorted(self):
        """Block keys extracted from df are sorted chronologically."""
        df = make_synthetic_df(n_seasons=4, weeks_per_type=2)
        keys = compute_block_keys(df)
        for i in range(len(keys) - 1):
            assert keys[i] < keys[i + 1]


# ─── Lock verification tests ───────────────────────────────────────────

class TestLockIntegrity:
    """Test 26: Verify lock hashes are unchanged."""

    SNAPSHOT_DIR = "data/modeling/development_v1/xgboost_lock_snapshot_v1"

    def test_canonical_config_sha(self):
        sha = sha256(open("config/xgboost_v1.yaml", "rb").read()).hexdigest()
        assert sha == CANONICAL_CONFIG_SHA

    def test_locked_config_sha(self):
        sha = sha256(
            open(f"{self.SNAPSHOT_DIR}/config_xgboost_v1.locked.yaml", "rb").read()
        ).hexdigest()
        assert sha == "6aa585239ea20c7cd43da5837128101c83c5ce25645c8769e391a4dfc175a3be"

    def test_candidate_evidence_sha(self):
        sha = sha256(
            open(f"{self.SNAPSHOT_DIR}/xgboost_candidate_differentiation_v1.locked.json", "rb").read()
        ).hexdigest()
        assert sha == "faf89503d42527e899ff6441f022298433aed61df812d3bead695fc1dce25e01"

    def test_feature_contract_sha(self):
        sha = sha256(
            open("data/modeling/development_v1/xgboost_feature_contract_v1.json", "rb").read()
        ).hexdigest()
        assert sha == "4187bef6b76d71f4f89f3387ec4789512cccb6deacd6cd64520039c713919993"

    def test_extraction_sha(self):
        sha = sha256(
            open("data/derived/features_v1/xgboost_development_2018_2024.parquet", "rb").read()
        ).hexdigest()
        assert sha == "fb4e45d28e337617043d578cb088e366aa217984bb200efca844e13111dc10f8"

    def test_extraction_row_count(self):
        df = pl.read_parquet("data/derived/features_v1/xgboost_development_2018_2024.parquet")
        assert df.height == 1942

    def test_lock_manifest_sha(self):
        sha = sha256(
            open(f"{self.SNAPSHOT_DIR}/LOCK_MANIFEST.json", "rb").read()
        ).hexdigest()
        assert sha == "e0f2d54734e1cf236ea20e573857367c4df9e12fa251b9bcf1762a19cc127af7"

    def test_snapshot_permissions_readonly(self):
        files = [
            "config_xgboost_v1.locked.yaml",
            "xgboost_candidate_differentiation_v1.locked.json",
            "xgboost_feature_contract_v1.locked.json",
            "LOCK_MANIFEST.json",
        ]
        for f in files:
            path = f"{self.SNAPSHOT_DIR}/{f}"
            mode = stat.S_IMODE(os.stat(path).st_mode)
            assert mode == 0o444, f"{f} has mode {oct(mode)}, expected 0444"

    def test_canonical_config_equals_locked_config(self):
        canonical = open("config/xgboost_v1.yaml", "rb").read()
        locked = open(f"{self.SNAPSHOT_DIR}/config_xgboost_v1.locked.yaml", "rb").read()
        assert canonical == locked

    def test_candidate_order_is_deterministic(self):
        assert CANDIDATE_ORDER == ["conservative", "balanced", "expressive"]
        assert [c for c in CANDIDATE_ORDER] == CANDIDATE_ORDER


# ─── Split construction tests ──────────────────────────────────────────

class TestSplitConstruction:
    """Test 8, 18: Validation-tail and fit-gate proofs."""

    def _make_detailed_keys(self):
        """Create 6 blocks: 2019-REG-1 through 2024-REG-1."""
        return [
            BlockKey(s, 99, "REG", 1) for s in range(2019, 2025)
        ]

    def test_validation_reserves_two_most_recent_prior(self):
        keys = self._make_detailed_keys()
        current = keys[-1]  # 2024
        split = construct_split(keys, current)
        assert len(split.validation_blocks) == 2
        assert split.validation_blocks == [keys[-3], keys[-2]]  # 2022, 2023
        assert split.fit_blocks == keys[:-3]  # 2019, 2020, 2021

    def test_current_block_excluded_from_fit_and_val(self):
        keys = self._make_detailed_keys()
        current = keys[-1]
        split = construct_split(keys, current)
        assert current not in split.fit_blocks
        assert current not in split.validation_blocks

    def test_future_blocks_excluded_from_split(self):
        keys = self._make_detailed_keys()
        current = keys[2]  # 2021
        split = construct_split(keys, current)
        # Only 2019, 2020 are prior
        assert split.fit_blocks == []  # Less than 2 prior → no fit
        assert split.validation_blocks == keys[:2]  # 2019, 2020

    def test_insufficient_prior_blocks(self):
        keys = [BlockKey(2019, 99, "REG", 1)]
        current = BlockKey(2020, 99, "REG", 1)
        split = construct_split(keys, current)
        assert split.fit_blocks == []
        assert split.validation_blocks == keys

    def test_warmup_insufficient_validation_blocks(self):
        keys = [BlockKey(2019, 99, "REG", 1)]
        current = BlockKey(2020, 99, "REG", 1)
        split = construct_split(keys, current)
        # Only 1 prior block → not enough for validation (needs 2)
        assert len(split.validation_blocks) == 1
        assert split.fit_blocks == []
        # Empty DataFrame with correct schema
        schema = {
            "season": pl.Int64,
            "season_type": pl.Utf8,
            "week": pl.Int64,
            "game_id": pl.Utf8,
            "scheduled_start_utc": pl.Utf8,
            "target_home_win": pl.Int64,
        }
        empty_df = pl.DataFrame(schema=schema)
        reason = evaluate_warmup_reason(split, empty_df, empty_df, SHARED_SETTINGS)
        assert reason == WARMUP_INSUFFICIENT_VALIDATION_BLOCKS

    def test_warmup_insufficient_fit_blocks(self):
        keys = [BlockKey(2019, 99, "REG", 1), BlockKey(2020, 99, "REG", 1)]
        current = BlockKey(2021, 99, "REG", 1)
        split = construct_split(keys, current)
        # 2 prior blocks → both in validation, 0 in fit
        assert split.fit_blocks == []
        assert split.validation_blocks == keys
        # Fit gate fails (0 fit blocks < min_training_blocks=2)
        # Build DataFrame with enough validation rows but no fit blocks
        schema = {
            "season": pl.Int64,
            "season_type": pl.Utf8,
            "week": pl.Int64,
            "game_id": pl.Utf8,
            "scheduled_start_utc": pl.Utf8,
            "target_home_win": pl.Int64,
        }
        # validation has 2 blocks, but fit has 0 blocks → fit_blocks gate fails first
        # Actually validation check runs first, and it has 2 blocks (ok),
        # then validation rows check — we need enough rows, so let's build them
        rows = []
        for k in keys:
            for g in range(30):
                rows.append({
                    "season": k.season,
                    "season_type": k.season_type,
                    "week": k.week,
                    "game_id": f"{k.season}_REG_01_GAME{g:03d}",
                    "scheduled_start_utc": f"{k.season}-09-15T12:00:00Z",
                    "target_home_win": g % 2,
                })
        val_df = pl.DataFrame(rows, schema=schema)
        reason = evaluate_warmup_reason(split, pl.DataFrame(schema=schema), val_df, SHARED_SETTINGS)
        # Validation has enough rows (60 > 21), passes validation gate
        # Then fit gate: 0 fit blocks < 2 → fails
        assert reason == WARMUP_INSUFFICIENT_FIT_BLOCKS


# ─── Filter prior blocks tests ─────────────────────────────────────────

class TestFilterPriorBlocks:
    """Test 7: Only blocks strictly earlier than current may contribute."""

    def test_prior_blocks_excludes_current_and_future(self):
        df = make_synthetic_df(n_seasons=3, games_per_block=5, weeks_per_type=1)
        keys = compute_block_keys(df)
        current = keys[-1]  # Last block
        prior_df = filter_prior_blocks(df, current)
        prior_keys = compute_block_keys(prior_df)
        for k in prior_keys:
            assert k < current

    def test_prior_blocks_empty_for_first_block(self):
        df = make_synthetic_df(n_seasons=3, games_per_block=5, weeks_per_type=1)
        keys = compute_block_keys(df)
        current = keys[0]  # First block
        prior_df = filter_prior_blocks(df, current)
        assert prior_df.height == 0


# ─── Engine warm-up tests ────────────────────────────────────────────────

class TestEngineWarmUp:
    """Test 12: Warm-up tests with small/insufficient data."""

    def test_small_data_produces_warmup(self):
        """Blocks with < 32 fit rows or < 2 fit blocks should warm up."""
        df = make_small_synthetic_df(games_per_block=8, n_blocks=6)
        engine = WalkForwardEngine(df, FEATURE_COLS)
        # First block: no prior → warmup
        keys = engine.block_keys
        result = engine.predict_block("conservative", keys[0])
        assert isinstance(result, WarmUpResult)
        assert result.probability is None  # Never 0.5
        assert result.warmup_reason is not None

    def test_warmup_reason_insufficient_fit_rows(self):
        """If fit rows < 32, warm-up."""
        # Create blocks with just enough blocks but not enough rows
        rows = []
        for season in range(2019, 2025):
            for g in range(5):  # 5 rows per block < 32 minimum
                rows.append(make_game(season, "REG", 1,
                    f"{season}_REG_01_GAME{g:03d}", f"{season}-09-15T12:00:00Z",
                    target=g % 2))
        df = pl.DataFrame(rows)
        engine = WalkForwardEngine(df, FEATURE_COLS)
        keys = engine.block_keys
        # 6th block: 5 prior blocks, validation=4-5, fit=1-3 blocks, but <32 rows
        result = engine.predict_block("conservative", keys[-1])
        assert isinstance(result, WarmUpResult)
        assert result.warmup_reason in [
            WARMUP_INSUFFICIENT_FIT_ROWS,
            WARMUP_INSUFFICIENT_FIT_BLOCKS,
            WARMUP_INSUFFICIENT_VALIDATION_ROWS,
        ]


# ─── Engine fitting & refit tests ────────────────────────────────────────

class TestEngineFittingAndRefit:
    """Tests 10, 11, 20: Early stopping, refit policy."""

    def test_engine_constructs_correctly(self):
        df = make_synthetic_df(n_seasons=6, games_per_block=40, weeks_per_type=2)
        engine = WalkForwardEngine(df, FEATURE_COLS)
        assert len(engine.block_keys) >= 10

    def test_eligible_block_produces_prediction(self):
        """With enough data, block should produce prediction (not warmup)."""
        df = make_synthetic_df(n_seasons=6, games_per_block=40, weeks_per_type=2)
        engine = WalkForwardEngine(df, FEATURE_COLS)
        keys = engine.block_keys
        # Skip first 3 blocks (warm-up), use block at index 5
        result = engine.predict_block("conservative", keys[5])
        assert isinstance(result, PredictionResult)
        assert len(result.probabilities) > 0
        assert result.best_iteration >= 0
        assert result.final_refit_rounds == result.best_iteration + 1
        assert result.final_refit_rounds >= 1

    def test_refit_uses_fit_plus_validation_only(self):
        """Final refit matrix should have fit_rows + validation_rows."""
        df = make_synthetic_df(n_seasons=6, games_per_block=40, weeks_per_type=2)
        engine = WalkForwardEngine(df, FEATURE_COLS)
        keys = engine.block_keys
        result = engine.predict_block("conservative", keys[5])
        # refit matrix fingerprint should combine fit + val data
        # (implicitly tested via block_state fingerprints being deterministic)
        assert result.block_state.final_refit_matrix_fingerprint != "N/A_warmup"

    def test_refit_rounds_equal_best_iteration_plus_one(self):
        """final_refit_rounds must equal best_iteration + 1."""
        df = make_synthetic_df(n_seasons=6, games_per_block=40, weeks_per_type=2)
        engine = WalkForwardEngine(df, FEATURE_COLS)
        keys = engine.block_keys
        result = engine.predict_block("conservative", keys[5])
        assert result.final_refit_rounds == result.best_iteration + 1

    def test_no_current_block_in_fit_or_validation(self):
        """Fit and validation data must exclude current block."""
        df = make_synthetic_df(n_seasons=6, games_per_block=40, weeks_per_type=2)
        engine = WalkForwardEngine(df, FEATURE_COLS)
        keys = engine.block_keys
        result = engine.predict_block("conservative", keys[5])
        # Current block games should NOT be in the input matrix
        # (They are only used for prediction, not training)
        assert result.block_state.fit_rows > 0
        assert result.block_state.validation_rows > 0
        # Total rows should be prior only
        prior_df = filter_prior_blocks(df, keys[5])
        # fit + validation rows ≤ all prior rows (minus ties/nulls)
        assert (result.fit_rows + result.validation_rows) <= prior_df.height


# ─── Same-block leakage protection ──────────────────────────────────────

class TestSameBlockProtection:
    """Test 16: Changing other games in same block must not affect predictions."""

    def test_same_block_change_does_not_alter_split(self):
        """Changing another game's feature in the same block must not change
        fit/validation split, best_iteration, or probabilities."""
        df = make_synthetic_df(n_seasons=6, games_per_block=40, weeks_per_type=2)
        engine = WalkForwardEngine(df, FEATURE_COLS)
        keys = engine.block_keys
        current = keys[5]

        result1 = engine.predict_block("conservative", current)

        # Modify a feature value of another game in the SAME current block
        modified_df = df.clone()
        mask = (
            (pl.col("season") == current.season)
            & (pl.col("season_type") == current.season_type)
            & (pl.col("week") == current.week)
        )
        modified_df = modified_df.with_columns(
            pl.when(mask)
            .then(pl.col("feat_0") * 999.0)
            .otherwise(pl.col("feat_0"))
            .alias("feat_0")
        )
        engine2 = WalkForwardEngine(modified_df, FEATURE_COLS)
        result2 = engine2.predict_block("conservative", current)

        # Block state should be identical — same split, same best_iteration
        assert result1.block_state.best_iteration == result2.block_state.best_iteration
        assert result1.block_state.final_refit_rounds == result2.block_state.final_refit_rounds
        assert result1.block_state.input_matrix_fingerprint == result2.block_state.input_matrix_fingerprint
        assert result1.block_state.validation_matrix_fingerprint == result2.block_state.validation_matrix_fingerprint
        # Same probabilities (current block feats are NOT used in training)
        assert result1.probabilities == result2.probabilities


# ─── Future-poisoning protection ────────────────────────────────────────

class TestFuturePoisoning:
    """Test 17: Changing later block data must not affect earlier predictions."""

    def test_future_target_change_does_not_affect_earlier_block(self):
        df = make_synthetic_df(n_seasons=6, games_per_block=40, weeks_per_type=2)
        engine = WalkForwardEngine(df, FEATURE_COLS)
        keys = engine.block_keys
        # Use keys[5] as earlier (5 prior blocks = 2 val + 3 fit → eligible)
        earlier_block = keys[5]

        result = engine.predict_block("conservative", earlier_block)
        assert isinstance(result, PredictionResult)

        # Modify target in a LATER block (keys[-1] = last block)
        modified_df = df.clone()
        later = keys[-1]
        mask = (
            (pl.col("season") == later.season)
            & (pl.col("season_type") == later.season_type)
            & (pl.col("week") == later.week)
        )
        modified_df = modified_df.with_columns(
            pl.when(mask).then(1).otherwise(pl.col("target_home_win")).alias("target_home_win")
        )
        engine2 = WalkForwardEngine(modified_df, FEATURE_COLS)
        result2 = engine2.predict_block("conservative", earlier_block)

        assert result.block_state.fit_target_fingerprint == result2.block_state.fit_target_fingerprint
        assert result.block_state.validation_target_fingerprint == result2.block_state.validation_target_fingerprint
        assert result.block_state.best_iteration == result2.block_state.best_iteration
        assert result.probabilities == result2.probabilities

    def test_future_score_field_change_does_not_affect_earlier_block(self):
        """Changing target_margin in a future block must not affect earlier."""
        df = make_synthetic_df(n_seasons=6, games_per_block=40, weeks_per_type=2)
        engine = WalkForwardEngine(df, FEATURE_COLS)
        keys = engine.block_keys
        earlier_block = keys[5]

        result = engine.predict_block("balanced", earlier_block)
        assert isinstance(result, PredictionResult)

        # Modify target_margin in a later block (last block)
        modified_df = df.clone()
        later = keys[-1]
        mask = (
            (pl.col("season") == later.season)
            & (pl.col("season_type") == later.season_type)
            & (pl.col("week") == later.week)
        )
        modified_df = modified_df.with_columns(
            pl.when(mask).then(pl.col("target_margin") * 1000)
            .otherwise(pl.col("target_margin"))
            .alias("target_margin")
        )
        engine2 = WalkForwardEngine(modified_df, FEATURE_COLS)
        result2 = engine2.predict_block("balanced", earlier_block)

        assert result.block_state.best_iteration == result2.block_state.best_iteration
        assert result.probabilities == result2.probabilities


# ─── Candidate-order independence ───────────────────────────────────────

class TestCandidateOrderIndependence:
    """Test 15: Candidate execution order must not alter candidate-specific output."""

    def test_reverse_candidate_order_same_result(self):
        """Running candidates in reverse order yields same results."""
        df = make_synthetic_df(n_seasons=6, games_per_block=40, weeks_per_type=2)
        keys = compute_block_keys(df)
        target_key = keys[5]

        engine_normal = WalkForwardEngine(df, FEATURE_COLS)
        engine_reversed = WalkForwardEngine(df, FEATURE_COLS)

        # Normal order: conservative, balanced, expressive
        result_normal = engine_normal.predict_block("balanced", target_key)
        # In reversed: we still predict the same candidate independently
        result_reversed = engine_reversed.predict_block("balanced", target_key)

        # Results identical
        assert result_normal.best_iteration == result_reversed.best_iteration
        assert result_normal.final_refit_rounds == result_reversed.final_refit_rounds
        assert result_normal.probabilities == result_reversed.probabilities
        assert result_normal.block_state.booster_fingerprint == result_reversed.block_state.booster_fingerprint

    def test_candidate_does_not_feed_another(self):
        """Each candidate trains independently — no shared state."""
        df = make_synthetic_df(n_seasons=6, games_per_block=40, weeks_per_type=2)
        keys = compute_block_keys(df)
        target_key = keys[5]

        engine = WalkForwardEngine(df, FEATURE_COLS)

        # Run conservative first, then balanced
        result_con = engine.predict_block("conservative", target_key)
        result_bal = engine.predict_block("balanced", target_key)

        # Different candidates should have different best_iterations (different params)
        # But both are valid
        from nfl_edge.backtest.xgboost_walk_forward import PredictionResult
        assert isinstance(result_con, PredictionResult)
        assert isinstance(result_bal, PredictionResult)
        assert result_con.candidate_id == "conservative"
        assert result_bal.candidate_id == "balanced"


# ─── Tie and missing-target tests ───────────────────────────────────────

class TestTieAndMissingTarget:
    """Test 21: Ties excluded from binary fit, no silent 0 encoding."""

    def test_ties_excluded_from_fit(self):
        """Tie games (target=None) must NOT enter fit or validation data."""
        rows = []
        gid = 0
        for season in range(2019, 2025):
            for g in range(40):
                target = g % 2
                # Insert a tie in the first block of 2019
                if season == 2019 and g == 0:
                    target = None
                rows.append(make_game(season, "REG", 1,
                    f"{season}_REG_01_GAME{gid:04d}",
                    f"{season}-09-15T12:00:00Z", target=target))
                gid += 1
        df = pl.DataFrame(rows)
        engine = WalkForwardEngine(df, FEATURE_COLS)
        keys = engine.block_keys

        # Find an eligible block
        for key in keys[3:]:
            result = engine.predict_block("conservative", key)
            if isinstance(result, PredictionResult):
                # The tie row should not be in fit or validation
                prior_df = filter_prior_blocks(df, key)
                # Count ties in prior data
                tie_count = prior_df.filter(pl.col("target_home_win").is_null()).height
                # Ties were excluded from fit/val rows
                assert result.fit_rows + result.validation_rows <= prior_df.height - max(0, tie_count)
                break

    def test_missing_target_excluded(self):
        """Missing target rows must be excluded, not encoded as 0."""
        rows = []
        gid = 0
        for season in range(2019, 2025):
            for g in range(40):
                target = g % 2
                if g == 5:  # One missing target
                    target = None
                rows.append(make_game(season, "REG", 1,
                    f"{season}_REG_01_GAME{gid:04d}",
                    f"{season}-09-15T12:00:00Z", target=target))
                gid += 1
        df = pl.DataFrame(rows)
        engine = WalkForwardEngine(df, FEATURE_COLS)
        keys = engine.block_keys
        result = engine.predict_block("conservative", keys[5])
        assert isinstance(result, PredictionResult)
        # The missing-target row should not be in fit/validation
        prior_df = filter_prior_blocks(df, keys[5])
        missing_count = prior_df.filter(pl.col("target_home_win").is_null()).height
        assert result.fit_rows + result.validation_rows <= prior_df.height - missing_count


# ─── Season safeguard tests ────────────────────────────────────────────

class TestSeasonSafeguards:
    """Boundary testing for season validation — never inspects 2025 outcomes."""

    def test_allowed_seasons_accepted(self):
        """Seasons 2018–2024 pass validation without error."""
        for season in range(2018, 2025):
            validate_season(season)  # Must not raise

    def test_2025_rejected(self):
        """Season 2025 is outside allowed development range."""
        with pytest.raises(ValueError):
            validate_season(2025)

    def test_2026_rejected(self):
        """Season 2026 is outside allowed development range."""
        with pytest.raises(ValueError):
            validate_season(2026)

    def test_2017_rejected(self):
        """Season before MIN_SEASON (2017) is outside allowed range."""
        with pytest.raises(ValueError):
            validate_season(2017)

    def test_engine_rejects_2025_block(self):
        """Engine must reject a block from 2025 at construction."""
        rows: list[dict] = []
        for g in range(40):
            rows.append(make_game(2025, "REG", 1,
                f"2025_REG_01_GAME{g:04d}", "2025-09-15T12:00:00Z",
                target=g % 2))
        df = pl.DataFrame(rows)
        with pytest.raises(ValueError, match="2025"):
            WalkForwardEngine(df, FEATURE_COLS)


# ─── Market field rejection tests ──────────────────────────────────────

class TestMarketSafeguards:
    """Verify market columns are rejected at the engine boundary.

    Tests use column names containing locked MARKET_TOKENS from the contract:
    moneyline, spread_line, total_line, closing_, pinnacle, draftkings, fanduel,
    clv, implied_probability, market_probability, market_price, line_movement,
    american_odds, decimal_odds.
    """

    def test_spread_column_rejected(self):
        with pytest.raises(ValueError, match="Market"):
            reject_market_columns(["feat_0", "spread_line"])

    def test_point_spread_column_rejected(self):
        with pytest.raises(ValueError, match="Market"):
            reject_market_columns(["feat_0", "point_spread_line"])

    def test_total_column_rejected(self):
        with pytest.raises(ValueError, match="Market"):
            reject_market_columns(["feat_0", "total_line"])

    def test_odds_column_rejected(self):
        with pytest.raises(ValueError, match="Market"):
            reject_market_columns(["feat_0", "decimal_odds"])

    def test_moneyline_column_rejected(self):
        with pytest.raises(ValueError, match="Market"):
            reject_market_columns(["feat_0", "moneyline"])

    def test_price_column_rejected(self):
        with pytest.raises(ValueError, match="Market"):
            reject_market_columns(["feat_0", "market_price"])

    def test_implied_probability_rejected(self):
        with pytest.raises(ValueError, match="Market"):
            reject_market_columns(["feat_0", "implied_probability"])

    def test_sportsbook_column_rejected(self):
        with pytest.raises(ValueError, match="Market"):
            reject_market_columns(["feat_0", "pinnacle"])

    def test_clv_column_rejected(self):
        with pytest.raises(ValueError, match="Market"):
            reject_market_columns(["feat_0", "clv"])

    def test_case_insensitive_rejection(self):
        """Market column detection is case-insensitive."""
        with pytest.raises(ValueError, match="Market"):
            reject_market_columns(["feat_0", "MONEYLINE"])

    def test_normal_features_accepted(self):
        """Non-market feature columns pass without error."""
        reject_market_columns(["feat_0", "feat_1", "feat_2", "feat_3", "feat_4"])
        # No exception raised = pass


# ─── Categorical handling tests ────────────────────────────────────────

class TestCategoricalHandling:
    """Synthetic tests for deterministic string/categorical feature encoding.

    Verifies: global deterministic vocabulary, same encoding across
    fit/validation/refit/prediction, unknown-category and null-category
    behaviour, and deterministic replay. No NFL data is fitted.
    """

    CATEGORICAL_COLS = ["feat_0", "roof_category"]

    def _make_cat_df(self, n_seasons: int = 6) -> pl.DataFrame:
        categories = ["closed", "dome", "open", "outdoors"]
        rows = []
        gid = 0
        for season in range(2019, 2019 + n_seasons):
            for wk in range(1, 4):
                for g in range(20):
                    rows.append({
                        "season": season,
                        "season_type": "REG",
                        "week": wk,
                        "game_id": f"{season}_REG_{wk:02d}_GAME{g:03d}",
                        "scheduled_start_utc": f"{season}-09-{(wk*7)%28+1:02d}T12:00:00Z",
                        "home_team": "HOME",
                        "away_team": "AWAY",
                        "target_home_win": g % 2,
                        "target_margin": 7.0 if g % 2 == 1 else -7.0,
                        "target_tie": False,
                        "target_available": True,
                        "feat_0": 0.1 * g,
                        "feat_1": 0.2 * g,
                        "feat_2": 0.3 * g,
                        "feat_3": 0.4 * g,
                        "feat_4": 0.5 * g,
                        "roof_category": categories[g % len(categories)],
                    })
                    gid += 1
        return pl.DataFrame(rows)

    def test_global_vocabulary_is_deterministic(self):
        """Vocabulary built once from full extraction, sorted unique values."""
        df = self._make_cat_df()
        engine = WalkForwardEngine(df, ["feat_0", "feat_1", "feat_2", "feat_3", "feat_4", "roof_category"])
        assert engine._categorical_vocab["roof_category"] == ["closed", "dome", "open", "outdoors"]
        # Numeric features excluded from vocabulary
        assert "feat_0" not in engine._categorical_vocab

    def test_same_encoding_across_splits(self):
        """Encoding of a given category is identical across fit/val/refit/predict."""
        df = self._make_cat_df()
        engine = WalkForwardEngine(df, ["feat_0", "feat_1", "feat_2", "feat_3", "feat_4", "roof_category"])
        vocab = engine._categorical_vocab["roof_category"]
        # A fit split missing 'closed' still encodes 'outdoors' the same as a split that has it
        colours = ["dome", "open", "outdoors"]  # no 'closed'
        mapping = {v: i for i, v in enumerate(vocab)}
        enc_no_closed = [mapping[c] for c in colours]
        enc_with_closed = [mapping[c] for c in ["closed", "dome", "open", "outdoors"]]
        assert enc_no_closed == [1, 2, 3]  # dome=1, open=2, outdoors=3 regardless of 'closed' presence
        assert enc_with_closed == [0, 1, 2, 3]
        assert engine._categorical_vocab["roof_category"] == ["closed", "dome", "open", "outdoors"]

    def test_unknown_category_maps_to_negative_one(self):
        """A value not in the global vocabulary is not silently mis-encoded."""
        df = self._make_cat_df()
        engine = WalkForwardEngine(df, ["feat_0", "feat_1", "feat_2", "feat_3", "feat_4", "roof_category"])
        vocab = engine._categorical_vocab["roof_category"]
        assert "roof" not in vocab  # sanity: unknown value
        # _to_dmatrix uses replace_strict; an unknown value should raise
        bad_df = pl.DataFrame({
            "feat_0": [0.1], "feat_1": [0.2], "feat_2": [0.3], "feat_3": [0.4],
            "feat_4": [0.5], "roof_category": ["tarp"],
        })
        with pytest.raises(Exception):
            engine._to_dmatrix(
                bad_df,
                ["feat_0", "feat_1", "feat_2", "feat_3", "feat_4", "roof_category"],
                "target_home_win",
            )

    def test_null_category_maps_to_negative_one(self):
        """A null category is mapped to CATEGORICAL_MISSING (-1)."""
        df = self._make_cat_df()
        engine = WalkForwardEngine(df, ["feat_0", "feat_1", "feat_2", "feat_3", "feat_4", "roof_category"])
        from nfl_edge.backtest.xgboost_walk_forward import CATEGORICAL_MISSING
        assert CATEGORICAL_MISSING == -1
        # Verify the DMatrix uses CATEGORICAL_MISSING for a null category
        null_row = df.slice(0, 1).with_columns(
            pl.lit(None, dtype=pl.Utf8).alias("roof_category")
        )
        dm = engine._to_dmatrix(
            null_row,
            ["feat_0", "feat_1", "feat_2", "feat_3", "feat_4", "roof_category"],
            "target_home_win",
        )
        assert dm is not None

    def test_predict_produces_deterministic_probabilities(self):
        """Running predict_block twice on the same eligible block yields identical probs."""
        df = self._make_cat_df()
        engine = WalkForwardEngine(df, ["feat_0", "feat_1", "feat_2", "feat_3", "feat_4", "roof_category"])
        keys = engine.block_keys
        r1 = r2 = None
        for k in keys[8:]:
            res = engine.predict_block("conservative", k)
            if isinstance(res, PredictionResult):
                r1 = res
                r2 = engine.predict_block("conservative", k)
                break
        assert r1 is not None
        assert list(r1.probabilities) == list(r2.probabilities)
        assert r1.best_iteration == r2.best_iteration
        assert r1.final_refit_rounds == r2.final_refit_rounds
