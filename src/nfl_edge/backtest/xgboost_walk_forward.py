"""Deterministic chronological walk-forward engine for XGBoost-v1 (Task 03C-4A).

This engine implements the chronological walk-forward machinery against the
accepted immutable lock from Task 03C-3. It provides deterministic block
ordering, leakage-safe split construction, early-stopping semantics, and a
refit policy -- all validated against synthetic chronologies.

No NFL candidate fitting is performed here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

import polars as pl
import xgboost as xgb

# ─── Season-type ordering (explicit, stable, documented) ────────────────
#
# Priority is the sort key, lower = earlier within the NFL season-year:
#   PRE → 0  (preseason; never used for 03C development)
#   REG → 1  (regular season)
#   WC  → 2  (wild-card)
#   DIV → 3  (divisional)
#   CON → 4  (conference / championship)
#   SB  → 5  (Super Bowl)
#
# The authoritative chronological identity is (season, season_type_priority,
# week): REG(S) < postseason(S) < REG(S+1). The ``season`` column is the NFL
# season-year, not the calendar year in which postseason games were played.
#
# Games within a block ordered by:
#   1. scheduled_start_utc (ascending)
#   2. game_id (ascending) as deterministic tiebreaker
#
SEASON_TYPE_PRIORITY: dict[str, int] = {
    "PRE": 0,
    "REG": 1,
    "WC": 2,
    "DIV": 3,
    "CON": 4,
    "SB": 5,
}

MIN_SEASON = 2018
MAX_SEASON = 2024

# Sentinel used when an ordinal-encoded category is null/unknown.
# Kept separate from the numeric feature domain (-1 cannot collide with
# 0..N-1 category indices).
CATEGORICAL_MISSING = -1


# ─── Candidate configuration (frozen from accepted lock) ────────────────

@dataclass(frozen=True)
class CandidateParams:
    """XGBoost parameters for a single candidate, frozen from the lock."""

    candidate_id: str
    max_depth: int
    learning_rate: float
    min_child_weight: float
    subsample: float
    colsample_bytree: float
    reg_alpha: float
    reg_lambda: float
    gamma: float
    max_delta_step: float
    max_rounds: int

    @property
    def parameter_hash(self) -> str:
        payload = asdict(self)
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


CANDIDATES: dict[str, CandidateParams] = {
    "conservative": CandidateParams(
        candidate_id="conservative", max_depth=2, learning_rate=0.05,
        min_child_weight=5.0, subsample=0.80, colsample_bytree=0.60,
        reg_alpha=0.50, reg_lambda=2.00, gamma=0.50, max_delta_step=1.00,
        max_rounds=200,
    ),
    "balanced": CandidateParams(
        candidate_id="balanced", max_depth=3, learning_rate=0.05,
        min_child_weight=3.0, subsample=0.85, colsample_bytree=0.70,
        reg_alpha=0.30, reg_lambda=1.50, gamma=0.20, max_delta_step=0.00,
        max_rounds=400,
    ),
    "expressive": CandidateParams(
        candidate_id="expressive", max_depth=4, learning_rate=0.03,
        min_child_weight=1.0, subsample=0.90, colsample_bytree=0.80,
        reg_alpha=0.10, reg_lambda=1.00, gamma=0.00, max_delta_step=0.00,
        max_rounds=800,
    ),
}

CANDIDATE_ORDER: list[str] = ["conservative", "balanced", "expressive"]

SHARED_SETTINGS: dict[str, Any] = {
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "tree_method": "hist",
    "seed": 42,
    "nthread": 1,
    "early_stopping_rounds": 50,
    "probability_epsilon": 1e-6,
    "min_training_rows": 32,
    "min_training_blocks": 2,
    "validation_block_count": 2,
    "min_validation_rows": 21,
    "min_validation_blocks": 2,
}

CANONICAL_CONFIG_SHA = "6aa585239ea20c7cd43da5837128101c83c5ce25645c8769e391a4dfc175a3be"


def shared_settings_hash() -> str:
    return hashlib.sha256(
        json.dumps(SHARED_SETTINGS, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


# ─── Deterministic fingerprinting ────────────────────────────────────────

def fingerprint(data: Any) -> str:
    """SHA-256 of JSON-serializable data (key-sorted, no path/ID/timestamp)."""
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def dataframe_fingerprint(df: pl.DataFrame) -> str:
    """Deterministic content fingerprint of a polars DataFrame."""
    data = df.to_dict(as_series=False)
    return fingerprint(data)


def feature_order_hash(feature_names: list[str]) -> str:
    """SHA-256 of exact feature column list (order-sensitive)."""
    return fingerprint(feature_names)


def parameter_hash(params: dict[str, Any]) -> str:
    """SHA-256 of candidate parameter dict (order-independent)."""
    return fingerprint(params)


# ─── Block ordering ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class BlockKey:
    """Immutable, comparable, hashable key for a chronological block."""

    season: int
    season_type_priority: int
    season_type: str
    week: int

    @property
    def block_id(self) -> str:
        return f"{self.season}_{self.season_type_priority:02d}_{self.week:02d}"

    @property
    def display_id(self) -> str:
        return f"{self.season}_{self.season_type}_{self.week:02d}"

    def __lt__(self, other):  # type: ignore[override]
        return (self.season, self.season_type_priority, self.week) < (
            other.season, other.season_type_priority, other.week,
        )


def sort_blocks(df: pl.DataFrame) -> pl.DataFrame:
    """Sort by (season, priority, week, scheduled_start_utc, game_id)."""
    return (
        df.with_columns(
            pl.col("season_type")
            .replace_strict(SEASON_TYPE_PRIORITY, return_dtype=pl.Int32)
            .alias("_priority")
        )
        .sort(["season", "_priority", "week", "scheduled_start_utc", "game_id"])
        .drop("_priority")
    )


def compute_block_keys(df: pl.DataFrame) -> list[BlockKey]:
    """Extract unique, sorted BlockKeys from a DataFrame."""
    blocks = (
        df.select(["season", "season_type", "week"])
        .unique()
        .with_columns(
            pl.col("season_type")
            .replace_strict(SEASON_TYPE_PRIORITY, return_dtype=pl.Int32)
            .alias("_priority")
        )
        .sort(["season", "_priority", "week"])
    )
    keys: list[BlockKey] = []
    for row in blocks.iter_rows(named=True):
        keys.append(
            BlockKey(
                season=row["season"],
                season_type_priority=SEASON_TYPE_PRIORITY[row["season_type"]],
                season_type=row["season_type"],
                week=row["week"],
            )
        )
    return keys


# ─── Season safeguards ─────────────────────────────────────────────────

def validate_season(season: int) -> None:
    """Reject seasons outside 2018–2024. Hard block for 2025+."""
    if season < MIN_SEASON or season > MAX_SEASON:
        raise ValueError(
            f"Season {season} outside allowed range [{MIN_SEASON}, {MAX_SEASON}]"
        )


def reject_market_columns(columns: list[str]) -> None:
    """Reject market-related fields at the engine boundary.

    Inspects every supplied column name (case-insensitive) and rejects
    any that contain a prohibited market concept. The token set matches
    the locked ``MARKET_TOKENS`` in ``xgboost_contract.py`` exactly.
    """
    market_tokens = {
        "moneyline", "spread_line", "total_line", "closing_", "pinnacle",
        "draftkings", "fanduel", "clv", "implied_probability",
        "market_probability", "market_price", "line_movement",
        "american_odds", "decimal_odds",
    }
    found = set()
    for col in columns:
        lower_col = col.lower()
        for token in market_tokens:
            if token in lower_col:
                found.add(col)
    if found:
        raise ValueError(f"Market columns rejected at engine boundary: {found}")


# ─── Warm-up reasons ───────────────────────────────────────────────────

WARMUP_INSUFFICIENT_FIT_BLOCKS = "insufficient_fit_blocks"
WARMUP_INSUFFICIENT_FIT_ROWS = "insufficient_fit_rows"
WARMUP_INSUFFICIENT_VALIDATION_BLOCKS = "insufficient_validation_blocks"
WARMUP_INSUFFICIENT_VALIDATION_ROWS = "insufficient_validation_rows"


# ─── BlockState schema ─────────────────────────────────────────────────

@dataclass
class BlockState:
    """Per-block, per-candidate state record.

    Schema for the future parquet ledger
    ``data/modeling/development_v1/xgboost_block_state_2018_2024.parquet``.
    """

    candidate_id: str
    block_id: str
    display_block_id: str
    season: int
    season_type_priority: int
    season_type: str
    week: int
    prediction_cutoff_identity: str
    fit_status: str
    warmup_reason: str | None
    fit_rows: int
    fit_blocks: int
    validation_rows: int
    validation_blocks: int
    max_rounds: int
    best_iteration: int | None
    final_refit_rounds: int | None
    early_stopping_status: str
    feature_count: int
    feature_order_hash: str
    parameter_hash: str
    shared_settings_hash: str
    config_sha256: str
    input_matrix_fingerprint: str
    validation_matrix_fingerprint: str
    fit_target_fingerprint: str
    validation_target_fingerprint: str
    final_refit_matrix_fingerprint: str
    booster_fingerprint: str | None
    xgboost_version: str
    seed: int
    nthread: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ─── Warm-up result ────────────────────────────────────────────────────

@dataclass
class WarmUpResult:
    """Explicit warm-up evidence — no probability, no fake 0.5."""

    candidate_id: str
    block_key: BlockKey
    fit_rows: int
    fit_blocks: int
    validation_rows: int
    validation_blocks: int
    warmup_reason: str
    probability: None = None  # Never 0.5

    def to_block_state(self, feature_names: list[str]) -> BlockState:
        return BlockState(
            candidate_id=self.candidate_id,
            block_id=self.block_key.block_id,
            display_block_id=self.block_key.display_id,
            season=self.block_key.season,
            season_type_priority=self.block_key.season_type_priority,
            season_type=self.block_key.season_type,
            week=self.block_key.week,
            prediction_cutoff_identity=self.block_key.display_id,
            fit_status="warmup",
            warmup_reason=self.warmup_reason,
            fit_rows=self.fit_rows,
            fit_blocks=self.fit_blocks,
            validation_rows=self.validation_rows,
            validation_blocks=self.validation_blocks,
            max_rounds=CANDIDATES[self.candidate_id].max_rounds,
            best_iteration=None,
            final_refit_rounds=None,
            early_stopping_status="n/a",
            feature_count=len(feature_names),
            feature_order_hash=feature_order_hash(feature_names),
            parameter_hash=CANDIDATES[self.candidate_id].parameter_hash,
            shared_settings_hash=shared_settings_hash(),
            config_sha256=CANONICAL_CONFIG_SHA,
            input_matrix_fingerprint="N/A_warmup",
            validation_matrix_fingerprint="N/A_warmup",
            fit_target_fingerprint="N/A_warmup",
            validation_target_fingerprint="N/A_warmup",
            final_refit_matrix_fingerprint="N/A_warmup",
            booster_fingerprint=None,
            xgboost_version=xgb.__version__,
            seed=SHARED_SETTINGS["seed"],
            nthread=SHARED_SETTINGS["nthread"],
        )


# ─── Prediction result ─────────────────────────────────────────────────

@dataclass
class PredictionResult:
    """Result of predicting a single chronological block for a candidate."""

    candidate_id: str
    block_key: BlockKey
    game_ids: list[str]
    probabilities: list[float]
    fit_rows: int
    fit_blocks: int
    validation_rows: int
    validation_blocks: int
    best_iteration: int
    final_refit_rounds: int
    early_stopping_status: str
    block_state: BlockState
    booster_fingerprint: str


# ─── Block filter ───────────────────────────────────────────────────────

def filter_block(
    df: pl.DataFrame,
    block_key: BlockKey,
    feature_cols: list[str],
    target_col: str = "target_home_win",
) -> pl.DataFrame:
    """Extract rows for a single block, sorted by (scheduled_start_utc, game_id)."""
    filtered = df.filter(
        (pl.col("season") == block_key.season)
        & (pl.col("season_type") == block_key.season_type)
        & (pl.col("week") == block_key.week)
    ).sort(["scheduled_start_utc", "game_id"])
    return filtered


def filter_prior_blocks(
    df: pl.DataFrame,
    current_block: BlockKey,
) -> pl.DataFrame:
    """Return only rows from blocks strictly earlier than current_block.

    Uses strict chronological comparison via BlockKey.__lt__.
    """
    block_keys = compute_block_keys(df)
    prior_keys = [k for k in block_keys if k < current_block]
    if not prior_keys:
        return df.head(0)
    prior_weeks = {(k.season, k.season_type, k.week) for k in prior_keys}
    mask = [
        (row["season"], row["season_type"], row["week"]) in prior_weeks
        for row in df.select(["season", "season_type", "week"]).iter_rows(named=True)
    ]
    return df.filter(pl.Series(mask, dtype=pl.Boolean)).pipe(sort_blocks)


# ─── Split construction ────────────────────────────────────────────────

@dataclass
class BlockSplit:
    """Chronological split: fit blocks, validation blocks, current block."""

    fit_blocks: list[BlockKey]
    validation_blocks: list[BlockKey]
    current_block: BlockKey

    @property
    def validation_tail(self) -> list[BlockKey]:
        return self.validation_blocks

    def __lt__(self, other):
        # Split comparison based on current block ordering
        return self.current_block < other.current_block


def construct_split(
    all_block_keys: list[BlockKey],
    current_block: BlockKey,
) -> BlockSplit:
    """Construct chronological fit/validation/current split.

    - Collect all prior eligible blocks (strictly earlier than current).
    - Reserve the two most recent prior blocks as validation tail.
    - Use everything earlier as fit data.

    Validation requires: 2 blocks, ≥21 validation rows.
    Fit requires: ≥2 blocks, ≥32 fit rows.

    If any gate fails, the block is marked warm-up.
    """
    prior_blocks = [k for k in all_block_keys if k < current_block]

    if len(prior_blocks) < 2:
        # Not enough prior blocks for validation reservation + fit minimum
        return BlockSplit(
            fit_blocks=[],
            validation_blocks=prior_blocks,
            current_block=current_block,
        )

    # Reserve the two most recent prior blocks as validation
    validation_blocks = prior_blocks[-2:]
    fit_blocks = prior_blocks[:-2]

    return BlockSplit(
        fit_blocks=fit_blocks,
        validation_blocks=validation_blocks,
        current_block=current_block,
    )


def evaluate_warmup_reason(
    split: BlockSplit,
    fit_df: pl.DataFrame,
    validation_df: pl.DataFrame,
    settings: dict[str, Any],
) -> str | None:
    """Determine if a block should be warm-up. Returns reason or None."""
    min_fit_blocks = settings["min_training_blocks"]
    min_fit_rows = settings["min_training_rows"]
    min_val_blocks = settings["min_validation_blocks"]
    min_val_rows = settings["min_validation_rows"]

    # Validation gates
    if len(split.validation_blocks) < min_val_blocks:
        return WARMUP_INSUFFICIENT_VALIDATION_BLOCKS
    if len(validation_df) < min_val_rows:
        return WARMUP_INSUFFICIENT_VALIDATION_ROWS

    # Fit gates
    if len(split.fit_blocks) < min_fit_blocks:
        return WARMUP_INSUFFICIENT_FIT_BLOCKS
    if len(fit_df) < min_fit_rows:
        return WARMUP_INSUFFICIENT_FIT_ROWS

    return None  # Eligible for fitting


# ─── Engine ─────────────────────────────────────────────────────────────

class WalkForwardEngine:
    """Deterministic chronological walk-forward engine for XGBoost-v1.

    The engine processes blocks in chronological order. For each block and
    candidate:

    1. Identify all prior eligible blocks (strictly before current block).
    2. Reserve the 2 most recent prior blocks as validation tail.
    3. Use everything earlier as fit data.
    4. If gates fail → warm-up (no probability, no training).
    5. Train candidate on fit data, early-stop on validation tail.
    6. Refit on (fit + validation) for exactly best_iteration + 1 rounds.
    7. Predict the complete current block from the refit booster.

    No current-block or future-block data ever enters fit or validation.
    """

    def __init__(
        self,
        df: pl.DataFrame,
        feature_cols: list[str],
        target_col: str = "target_home_win",
        seed: int = SHARED_SETTINGS["seed"],
        nthread: int = SHARED_SETTINGS["nthread"],
    ) -> None:
        self.df = sort_blocks(df)
        self.feature_cols = feature_cols
        self.target_col = target_col
        self.seed = seed
        self.nthread = nthread
        self._block_keys = compute_block_keys(self.df)
        reject_market_columns(list(self.df.columns))
        # Season safeguards: reject 2025+ at construction
        for bk in self._block_keys:
            validate_season(bk.season)

        # Global categorical vocabulary built once from the full extraction.
        # Used identically across fit, validation, refit, and prediction so the
        # ordinal encoding is deterministic and split-independent.  Vocabulary
        # order is the sorted unique values of each string feature column.
        self._categorical_vocab: dict[str, list[str]] = {}
        for col_name in self.feature_cols:
            if col_name in self.df.columns and self.df[col_name].dtype == pl.Utf8:
                self._categorical_vocab[col_name] = sorted(
                    self.df[col_name].drop_nulls().unique().to_list()
                )

    @property
    def block_keys(self) -> list[BlockKey]:
        return list(self._block_keys)

    @staticmethod
    def _filter_by_keys(
        df: pl.DataFrame, keys: list[tuple[int, str, int]]
    ) -> pl.DataFrame:
        """Filter rows matching composite (season, season_type, week) keys."""
        if not keys:
            return df.head(0)
        # Build a filter expression: match any of the key tuples
        # Use tuple-based approach via pl.map or conditional filter
        key_set = set(keys)
        mask = [
            (row["season"], row["season_type"], row["week"]) in key_set
            for row in df.select(["season", "season_type", "week"]).iter_rows(named=True)
        ]
        return df.filter(pl.Series(mask, dtype=pl.Boolean))

    def _to_dmatrix(
        self,
        data: pl.DataFrame,
        feature_cols: list[str],
        label_col: str,
    ) -> xgb.DMatrix:
        """Convert polars DataFrame to XGBoost DMatrix.

        Handles string/categorical columns by ordinal-encoding them against the
        engine's GLOBAL vocabulary (built once from the full extraction), so the
        encoding is identical across fit, validation, refit, and prediction.
        Nulls/unknown categories map to -1.
        """
        X_df = data.select(feature_cols)
        for col_name in feature_cols:
            if col_name in self._categorical_vocab:
                vocab = self._categorical_vocab[col_name]
                mapping = {v: i for i, v in enumerate(vocab)}
                X_df = X_df.with_columns(
                    pl.col(col_name).replace_strict(
                        mapping, return_dtype=pl.Int64
                    ).fill_null(CATEGORICAL_MISSING).alias(col_name)
                )
        X = X_df.to_numpy()
        y = data.select(label_col).to_numpy().ravel()
        return xgb.DMatrix(X, label=y, feature_names=feature_cols)

    def _predict_dmatrix(
        self,
        data: pl.DataFrame,
        feature_cols: list[str],
    ) -> xgb.DMatrix:
        """Build a label-free DMatrix for prediction, encoding categoricals
        against the same global vocabulary."""
        X_df = data.select(feature_cols)
        for col_name in feature_cols:
            if col_name in self._categorical_vocab:
                vocab = self._categorical_vocab[col_name]
                mapping = {v: i for i, v in enumerate(vocab)}
                X_df = X_df.with_columns(
                    pl.col(col_name).replace_strict(
                        mapping, return_dtype=pl.Int64
                    ).fill_null(CATEGORICAL_MISSING).alias(col_name)
                )
        X = X_df.to_numpy()
        return xgb.DMatrix(X, feature_names=feature_cols)

    def _train_with_early_stopping(
        self,
        candidate: CandidateParams,
        fit_dmatrix: xgb.DMatrix,
        val_dmatrix: xgb.DMatrix,
    ) -> tuple[xgb.Booster, int, str]:
        """Train with early stopping on validation tail.

        Returns (booster, best_iteration, early_stopping_status).
        best_iteration is zero-based from XGBoost.
        """
        params = {
            "objective": SHARED_SETTINGS["objective"],
            "eval_metric": SHARED_SETTINGS["eval_metric"],
            "tree_method": SHARED_SETTINGS["tree_method"],
            "seed": self.seed,
            "nthread": self.nthread,
            "max_depth": candidate.max_depth,
            "learning_rate": candidate.learning_rate,
            "min_child_weight": candidate.min_child_weight,
            "subsample": candidate.subsample,
            "colsample_bytree": candidate.colsample_bytree,
            "reg_alpha": candidate.reg_alpha,
            "reg_lambda": candidate.reg_lambda,
            "gamma": candidate.gamma,
            "max_delta_step": candidate.max_delta_step,
        }

        evals_result: dict[str, dict[str, list[float]]] = {}
        evals = [(fit_dmatrix, "fit"), (val_dmatrix, "validation")]

        booster = xgb.train(
            params=params,
            dtrain=fit_dmatrix,
            num_boost_round=candidate.max_rounds,
            evals=evals,
            evals_result=evals_result,
            early_stopping_rounds=SHARED_SETTINGS["early_stopping_rounds"],
            verbose_eval=False,
        )

        best_iter = booster.best_iteration
        if best_iter < candidate.max_rounds - 1:
            status = "early_stopped"
        else:
            status = "completed_all_rounds"

        return booster, best_iter, status

    def _refit_full(
        self,
        candidate: CandidateParams,
        full_dmatrix: xgb.DMatrix,
        rounds: int,
    ) -> xgb.Booster:
        """Refit from scratch using all prior eligible rows for exactly `rounds`.

        No early stopping during final refit.
        """
        params = {
            "objective": SHARED_SETTINGS["objective"],
            "eval_metric": SHARED_SETTINGS["eval_metric"],
            "tree_method": SHARED_SETTINGS["tree_method"],
            "seed": self.seed,
            "nthread": self.nthread,
            "max_depth": candidate.max_depth,
            "learning_rate": candidate.learning_rate,
            "min_child_weight": candidate.min_child_weight,
            "subsample": candidate.subsample,
            "colsample_bytree": candidate.colsample_bytree,
            "reg_alpha": candidate.reg_alpha,
            "reg_lambda": candidate.reg_lambda,
            "gamma": candidate.gamma,
            "max_delta_step": candidate.max_delta_step,
        }
        return xgb.train(
            params=params,
            dtrain=full_dmatrix,
            num_boost_round=rounds,
            verbose_eval=False,
        )

    def _booster_fingerprint(self, booster: xgb.Booster) -> str:
        """Deterministic fingerprint of a booster model.

        Uses XGBoost's saved model state (not Python object ID).
        """
        state = booster.save_raw(raw_format="json")
        return hashlib.sha256(bytes(state)).hexdigest()

    def predict_block(
        self,
        candidate_id: str,
        block_key: BlockKey,
    ) -> PredictionResult | WarmUpResult:
        """Predict a single block for a single candidate.

        Implements the full chronological walk-forward pipeline:
        split construction → gate evaluation → early-stop training →
        refit → prediction. Returns WarmUpResult if gates fail.
        """
        validate_season(block_key.season)

        candidate = CANDIDATES[candidate_id]

        # 1. Collect prior eligible rows (strictly before current block)
        prior_df = filter_prior_blocks(self.df, block_key)

        # 2. Construct chronological split
        split = construct_split(self._block_keys, block_key)

        # Build composite-key filters to avoid cross-block leakage
        fit_keys = [(k.season, k.season_type, k.week) for k in split.fit_blocks]
        val_keys = [(k.season, k.season_type, k.week) for k in split.validation_blocks]

        fit_df = self._filter_by_keys(prior_df, fit_keys)
        val_df = self._filter_by_keys(prior_df, val_keys)

        # 3. Evaluate warm-up gates
        warmup_reason = evaluate_warmup_reason(split, fit_df, val_df, SHARED_SETTINGS)
        if warmup_reason is not None:
            return WarmUpResult(
                candidate_id=candidate_id,
                block_key=block_key,
                fit_rows=len(fit_df),
                fit_blocks=len(split.fit_blocks),
                validation_rows=len(val_df),
                validation_blocks=len(split.validation_blocks),
                warmup_reason=warmup_reason,
            )

        # 4. Train with early stopping on fit + validation tail
        # Only binary targets (1/0), no ties
        binary_fit = fit_df.filter(
            (pl.col(self.target_col) == 1) | (pl.col(self.target_col) == 0)
        ).select(self.feature_cols + [self.target_col])

        binary_val = val_df.filter(
            (pl.col(self.target_col) == 1) | (pl.col(self.target_col) == 0)
        ).select(self.feature_cols + [self.target_col])

        fit_dmatrix = self._to_dmatrix(binary_fit, self.feature_cols, self.target_col)
        val_dmatrix = self._to_dmatrix(binary_val, self.feature_cols, self.target_col)

        booster, best_iteration, early_stopping_status = (
            self._train_with_early_stopping(candidate, fit_dmatrix, val_dmatrix)
        )

        # 5. Final refit: combine fit + validation, refit for exactly best_iteration + 1 rounds
        final_rounds = best_iteration + 1
        assert final_rounds >= 1, "Final refit must use at least 1 round when fit succeeds"

        combined_df = pl.concat([binary_fit, binary_val], how="vertical")
        full_dmatrix = self._to_dmatrix(combined_df, self.feature_cols, self.target_col)

        refit_booster = self._refit_full(candidate, full_dmatrix, final_rounds)

        # 6. Predict the complete current block
        current_block_df = filter_block(
            self.df, block_key, self.feature_cols + [self.target_col]
        )
        # Prediction DMatrix: label-free, categoricals encoded against the
        # same global vocabulary (ties/None targets never become NaN labels).
        current_dmatrix = self._predict_dmatrix(
            current_block_df, self.feature_cols
        )

        raw_probs = refit_booster.predict(current_dmatrix)
        eps = SHARED_SETTINGS["probability_epsilon"]
        clipped_probs = [
            max(eps, min(1.0 - eps, float(p))) for p in raw_probs
        ]

        booster_fp = self._booster_fingerprint(refit_booster)

        game_ids = current_block_df["game_id"].to_list()

        # Build block state
        block_state = BlockState(
            candidate_id=candidate_id,
            block_id=block_key.block_id,
            display_block_id=block_key.display_id,
            season=block_key.season,
            season_type_priority=block_key.season_type_priority,
            season_type=block_key.season_type,
            week=block_key.week,
            prediction_cutoff_identity=block_key.display_id,
            fit_status="fitted",
            warmup_reason=None,
            fit_rows=len(binary_fit),
            fit_blocks=len(split.fit_blocks),
            validation_rows=len(binary_val),
            validation_blocks=len(split.validation_blocks),
            max_rounds=candidate.max_rounds,
            best_iteration=best_iteration,
            final_refit_rounds=final_rounds,
            early_stopping_status=early_stopping_status,
            feature_count=len(self.feature_cols),
            feature_order_hash=feature_order_hash(self.feature_cols),
            parameter_hash=candidate.parameter_hash,
            shared_settings_hash=shared_settings_hash(),
            config_sha256=CANONICAL_CONFIG_SHA,
            input_matrix_fingerprint=dataframe_fingerprint(
                binary_fit.select(self.feature_cols)
            ),
            validation_matrix_fingerprint=dataframe_fingerprint(
                binary_val.select(self.feature_cols)
            ),
            fit_target_fingerprint=dataframe_fingerprint(
                binary_fit.select([self.target_col])
            ),
            validation_target_fingerprint=dataframe_fingerprint(
                binary_val.select([self.target_col])
            ),
            final_refit_matrix_fingerprint=dataframe_fingerprint(
                combined_df.select(self.feature_cols)
            ),
            booster_fingerprint=booster_fp,
            xgboost_version=xgb.__version__,
            seed=self.seed,
            nthread=self.nthread,
        )

        return PredictionResult(
            candidate_id=candidate_id,
            block_key=block_key,
            game_ids=game_ids,
            probabilities=clipped_probs,
            fit_rows=len(binary_fit),
            fit_blocks=len(split.fit_blocks),
            validation_rows=len(binary_val),
            validation_blocks=len(split.validation_blocks),
            best_iteration=best_iteration,
            final_refit_rounds=final_rounds,
            early_stopping_status=early_stopping_status,
            block_state=block_state,
            booster_fingerprint=booster_fp,
        )

    def run_all_candidates(self) -> list[PredictionResult | WarmUpResult]:
        """Run walk-forward for all candidates across all blocks in order.

        Candidates are processed in deterministic order
        (conservative, balanced, expressive). Each candidate's
        execution is independent — no candidate's state feeds another.
        """
        results: list[PredictionResult | WarmUpResult] = []
        for block_key in self._block_keys:
            for candidate_id in CANDIDATE_ORDER:
                result = self.predict_block(candidate_id, block_key)
                results.append(result)
        return results

    def run_candidate(self, candidate_id: str) -> list[PredictionResult | WarmUpResult]:
        """Run walk-forward for a single candidate across all blocks."""
        results: list[PredictionResult | WarmUpResult] = []
        for block_key in self._block_keys:
            result = self.predict_block(candidate_id, block_key)
            results.append(result)
        return results
