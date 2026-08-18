"""Frozen, serial-only configuration for the future Task05D totals bake-off.

This module deliberately does not load data, construct features, rebuild
chronology, or fit models.  It accepts only blocks already prepared by
``totals_walk_forward.run_totals_walk_forward``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import Any, Literal, Mapping, MutableMapping

import polars as pl

from ..common.errors import ConfigurationError
from ..features.totals_v1.feature_table import EXACT_90_COLUMNS
from .totals_walk_forward import TotalsWalkForwardBlock, TotalsWalkForwardRun


@dataclass(frozen=True)
class ScoringUniverseContract:
    """Expected downstream accounting after the established warm-up period."""

    scoring_blocks: int
    scoring_rows: int
    warmup_rows: int
    earliest_block_id: str
    latest_block_id: str


SCORING_UNIVERSE = ScoringUniverseContract(
    scoring_blocks=146,
    scoring_rows=1864,
    warmup_rows=78,
    earliest_block_id="2018_REG_W06",
    latest_block_id="2024_SB_W22",
)
MINIMUM_ELIGIBLE_PRIOR_ROWS = 64

SERIAL_ENVIRONMENT: Mapping[str, str] = MappingProxyType(
    {
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }
)


SAFE_MANIFEST_ENV_KEYS: tuple[str, ...] = (
    "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS",
    "TERMINAL_CONTAINER_CPU", "TERMINAL_CONTAINER_MEMORY",
)


def safe_manifest_environment(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return only explicitly allowed non-secret resource metadata for manifests."""
    source = os.environ if environment is None else environment
    return {key: str(source[key]) for key in SAFE_MANIFEST_ENV_KEYS if key in source}


@dataclass(frozen=True)
class SerialExecutionContract:
    """The process settings required for reproducible serial Ridge runs."""

    environment: Mapping[str, str]
    multiprocessing_enabled: bool


SERIAL_EXECUTION = SerialExecutionContract(
    environment=SERIAL_ENVIRONMENT,
    multiprocessing_enabled=False,
)

def configure_serial_execution(environment: MutableMapping[str, str] | None = None) -> None:
    """Overwrite the required thread limits before any future estimator imports."""
    target = os.environ if environment is None else environment
    target.update(SERIAL_EXECUTION.environment)


@dataclass(frozen=True)
class TotalsCandidateSpec:
    """An immutable model candidate specification; construction happens later."""

    candidate_id: str
    family: Literal["ridge"]
    parameters: tuple[tuple[str, float | int | str], ...]

    @property
    def model_kwargs(self) -> Mapping[str, float | int | str]:
        """Return a fresh parameter mapping with serial settings included."""
        parameters = dict(self.parameters)
        return MappingProxyType(parameters)


CANDIDATES: tuple[TotalsCandidateSpec, ...] = (
    TotalsCandidateSpec("R1", "ridge", (("alpha", 0.1),)),
    TotalsCandidateSpec("R2", "ridge", (("alpha", 1),)),
    TotalsCandidateSpec("R3", "ridge", (("alpha", 10),)),
    TotalsCandidateSpec("R4", "ridge", (("alpha", 100),)),
)
CANDIDATE_IDS = tuple(candidate.candidate_id for candidate in CANDIDATES)
CATEGORICAL_PREDICTORS: tuple[str, str] = ("roof_category", "surface_category")
NUMERIC_PREDICTORS: tuple[str, ...] = tuple(
    column for column in EXACT_90_COLUMNS if column not in CATEGORICAL_PREDICTORS
)
MODEL_RANDOM_SEED = 20_240_505


@dataclass(frozen=True)
class CandidateMetricResult:
    """Already-computed out-of-bag metrics for one candidate.

    OOB RMSE is primary. MAE, Pearson, Spearman, and lower-is-better stability
    (the OOB-RMSE standard deviation) provide deterministic tie-breaks.
    """

    candidate_id: str
    oob_rmse: float
    mae: float
    pearson: float
    spearman: float
    stability: float

    def __post_init__(self) -> None:
        if self.candidate_id not in CANDIDATE_IDS:
            raise ConfigurationError(f"unknown totals bake-off candidate: {self.candidate_id}")
        if not all(isfinite(value) for value in (self.oob_rmse, self.mae, self.pearson, self.spearman, self.stability)):
            raise ConfigurationError("totals bake-off metrics must be finite")


def scoring_blocks_from_prepared(run: TotalsWalkForwardRun) -> tuple[TotalsWalkForwardBlock, ...]:
    """Apply only the row-floor gate to chronology prepared by the accepted core."""
    if not isinstance(run, TotalsWalkForwardRun):
        raise TypeError("run must be a TotalsWalkForwardRun from totals_walk_forward")
    return tuple(block for block in run.blocks if block.training_rows.height >= MINIMUM_ELIGIBLE_PRIOR_ROWS)


@dataclass(frozen=True)
class CandidatePredictionRecord:
    """One deterministic scored game, retained for later metric calculation."""

    identity: Mapping[str, object]
    observed_target: float
    predicted_total: float


@dataclass(frozen=True)
class CandidateRunResult:
    """The bounded serial output for one frozen candidate."""

    candidate_id: str
    records: tuple[CandidatePredictionRecord, ...]


def candidate_spec(candidate_id: str) -> TotalsCandidateSpec:
    """Resolve a frozen candidate identifier, rejecting all unknown families."""
    for spec in CANDIDATES:
        if spec.candidate_id == candidate_id:
            return spec
    raise ConfigurationError(f"unknown totals bake-off candidate: {candidate_id}")


def build_candidate_model(candidate: TotalsCandidateSpec | str) -> Any:
    """Lazily construct exactly one CPU-only frozen candidate estimator."""
    spec = candidate_spec(candidate) if isinstance(candidate, str) else candidate
    if spec.candidate_id not in CANDIDATE_IDS or candidate_spec(spec.candidate_id) != spec:
        raise ConfigurationError("candidate must be one of the frozen totals bake-off specifications")
    configure_serial_execution()
    if spec.family == "ridge":
        from sklearn.compose import ColumnTransformer
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import Ridge
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder, StandardScaler

        numeric = Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())])
        categorical = Pipeline(
            [("impute", SimpleImputer(strategy="most_frequent")), ("one_hot", OneHotEncoder(handle_unknown="ignore"))]
        )
        return Pipeline(
            [
                (
                    "features",
                    ColumnTransformer(
                        (
                            ("numeric", numeric, list(NUMERIC_PREDICTORS)),
                            ("categorical", categorical, list(CATEGORICAL_PREDICTORS)),
                        ),
                        remainder="drop",
                    ),
                ),
                ("model", Ridge(**dict(spec.model_kwargs))),
            ]
        )
    raise ConfigurationError(f"unknown totals bake-off candidate family: {spec.family}")


def _require_frame_columns(frame: pl.DataFrame, expected: tuple[str, ...], where: str) -> None:
    if tuple(frame.columns) != expected:
        raise ConfigurationError(f"{where} must have exactly ordered columns {expected}")


def _pandas_predictors(frame: pl.DataFrame, family: str):
    import pandas as pd

    _require_frame_columns(frame, EXACT_90_COLUMNS, "predictor frame")
    result = frame.to_pandas().loc[:, list(EXACT_90_COLUMNS)].copy()
    for column in NUMERIC_PREDICTORS:
        values = pd.to_numeric(result[column], errors="coerce")
        if values.isin([float("inf"), float("-inf")]).any():
            raise ConfigurationError(f"predictor frame has non-finite numeric value in {column}")
        result[column] = values
    for column in CATEGORICAL_PREDICTORS:
        values = result[column]
        if not values.map(lambda value: value is None or isinstance(value, str)).all():
            raise ConfigurationError(f"predictor frame has non-string categorical value in {column}")
    return result


def _validated_block_frames(block: TotalsWalkForwardBlock, family: str):
    training_expected = (
        "game_id",
        "season",
        "season_type",
        "week",
        "home_team",
        "away_team",
        "block_id",
        *EXACT_90_COLUMNS,
        "home_score",
        "away_score",
        "target_total_points",
    )
    identity = ("game_id", "season", "season_type", "week", "home_team", "away_team", "block_id")
    _require_frame_columns(block.training_rows, training_expected, "training_rows")
    _require_frame_columns(block.prediction_rows, identity + EXACT_90_COLUMNS, "prediction_rows")
    if block.outcome_rows is None:
        raise ConfigurationError("prepared block must provide a separate outcome_rows surface")
    _require_frame_columns(block.outcome_rows, identity + ("target_total_points",), "outcome_rows")
    if block.prediction_rows.height != block.outcome_rows.height:
        raise ConfigurationError("prediction_rows and outcome_rows must have equal row counts")
    if block.prediction_rows.select(list(identity)).rows() != block.outcome_rows.select(list(identity)).rows():
        raise ConfigurationError("prediction_rows and outcome_rows identities must match in order")
    training_target = block.training_rows["target_total_points"]
    outcome_target = block.outcome_rows["target_total_points"]
    if not training_target.dtype.is_numeric() or not outcome_target.dtype.is_numeric():
        raise ConfigurationError("training and observed targets must use numeric dtypes")
    target = training_target.cast(pl.Float64, strict=True)
    observed = outcome_target.cast(pl.Float64, strict=True)
    if target.null_count() or observed.null_count() or not all(isfinite(value) for value in [*target, *observed]):
        raise ConfigurationError("training and observed targets must be finite numbers")
    training = _pandas_predictors(block.training_rows.select(list(EXACT_90_COLUMNS)), family)
    prediction = _pandas_predictors(block.prediction_rows.select(list(EXACT_90_COLUMNS)), family)
    return training, prediction, target.to_list(), observed.to_list(), identity


def run_candidate_on_prepared(candidate: TotalsCandidateSpec | str, run: TotalsWalkForwardRun) -> CandidateRunResult:
    """Fit serially on eligible prepared blocks only; no chronology or I/O occurs here."""
    if not isinstance(run, TotalsWalkForwardRun):
        raise TypeError("run must be a TotalsWalkForwardRun from totals_walk_forward")
    spec = candidate_spec(candidate) if isinstance(candidate, str) else candidate
    if candidate_spec(spec.candidate_id) != spec:
        raise ConfigurationError("candidate must be a frozen totals bake-off specification")
    records: list[CandidatePredictionRecord] = []
    for block in scoring_blocks_from_prepared(run):
        training, prediction, target, observed, identity_columns = _validated_block_frames(block, spec.family)
        model = build_candidate_model(spec)
        model.fit(training, target)
        predictions = model.predict(prediction)
        if len(predictions) != len(observed) or not all(isfinite(float(value)) for value in predictions):
            raise ConfigurationError("candidate produced malformed or non-finite predictions")
        outcome_identities = block.outcome_rows.select(list(identity_columns)).rows()
        for identity, actual, predicted in zip(outcome_identities, observed, predictions, strict=True):
            records.append(
                CandidatePredictionRecord(
                    identity=MappingProxyType(dict(zip(identity_columns, identity, strict=True))),
                    observed_target=float(actual),
                    predicted_total=float(predicted),
                )
            )
    return CandidateRunResult(candidate_id=spec.candidate_id, records=tuple(records))


def metric_selection_key(result: CandidateMetricResult) -> tuple[float, float, float, float, float, int]:
    """Return the frozen ascending selection key, including the candidate ID order."""
    return (
        result.oob_rmse,
        result.mae,
        -result.pearson,
        -result.spearman,
        result.stability,
        CANDIDATE_IDS.index(result.candidate_id),
    )


def rank_candidates(results: tuple[CandidateMetricResult, ...]) -> tuple[CandidateMetricResult, ...]:
    """Rank a complete candidate result set without fitting or recomputing metrics."""
    result_ids = tuple(result.candidate_id for result in results)
    if set(result_ids) != set(CANDIDATE_IDS) or len(result_ids) != len(CANDIDATE_IDS):
        raise ConfigurationError("results must contain exactly one metric result for every frozen candidate")
    return tuple(sorted(results, key=metric_selection_key))
