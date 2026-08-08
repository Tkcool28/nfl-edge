"""Generate the XGBoost development extraction and feature contract.

Deterministic extraction + frozen feature contract for Task 03C-2.

Produces:
    data/derived/features_v1/xgboost_development_2018_2024.parquet
    data/modeling/development_v1/xgboost_feature_contract_v1.json
    config/xgboost_v1.yaml
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import polars as pl

BASE_SHA = "a93bfe1f7ffaaac7bff8758bf278af1ce07149db"
DEVELOPMENT_SEASON_MIN = 2018
DEVELOPMENT_SEASON_MAX = 2024

SOURCE_GAME_FEATURES = "data/derived/features_v1/game_features_2018_2025.parquet"
SOURCE_QB_FEATURES = "data/derived/features_v1/qb_pregame_features_2018_2025.parquet"
SOURCE_STARTER_CERTAINTY = "data/derived/features_v1/starter_certainty_2018_2025.parquet"

OUTPUT_PARQUET = "data/derived/features_v1/xgboost_development_2018_2024.parquet"
OUTPUT_CONTRACT = "data/modeling/development_v1/xgboost_feature_contract_v1.json"
OUTPUT_CONFIG_YAML = "config/xgboost_v1.yaml"

# Columns kept as metadata (never model features)
IDENTITY_COLUMNS = ["game_id", "season", "season_type", "week", "home_team", "away_team"]
TIMESTAMP_COLUMNS = ["feature_as_of_utc", "prediction_as_of_utc", "source_available_at_utc", "scheduled_start_utc"]
TARGET_COLUMNS = ["target_home_win", "target_margin", "target_tie", "target_available"]
PROVENANCE_COLUMNS = ["availability_rule", "feature_version", "data_version"]

# Columns dropped entirely from the extraction (never enter the parquet)
DROP_COLUMNS = {
    "venue_id",
    "expected_home_qb_id",
    "expected_away_qb_id",
    "qb_status",
    "home_is_home",
    "away_is_home",
    "home_away_is_home",
    "away_away_is_home",
}

# offensent_total_epa = passing_epa + rushing_epa — deterministic identity.
# Dropped to avoid duplication; passing_epa and rushing_epa are retained separately.
REDUNDANT_METRIC_COLUMNS = {
    "home_roll4_offensive_total_epa", "away_roll4_offensive_total_epa",
    "home_roll8_offensive_total_epa", "away_roll8_offensive_total_epa",
    "home_season_to_date_offensive_total_epa", "away_season_to_date_offensive_total_epa",
}

# starter_reason_codes and starter_certainty string columns are postgame evidence
# metadata (categorical audit values: "POSTGAME_ONLY_EVIDENCE", "UNKNOWN").
# These are audit/metadata only — never numeric model features because their
# values are resolved from postgame evidence and their specific string depends
# on postgame-only QB evidence IDs. Dropped from extraction parquet.
TEXT_COLUMNS = {
    "starter_reason_codes",
    "starter_certainty",
    "home_starter_certainty",
    "away_starter_certainty",
}

# QB pregame columns retained as model features (candidate_rank=1 only).
# Excluded: observed/prior/sample_size/volume (constant at priors in this base;
#  redundant with shrunk values + missingness flags).
# Excluded: *_imputed flags (all True — constant, uninformative in this base).
QB_FEATURE_COLUMNS = [
    "passing_epa",
    "passing_cpoe",
    "sacks_suffered_rate",
    "interception_rate",
    "recency_weighted_form",
    "season_to_date_form",
    "career_to_date_form",
    "passing_epa_shrinkage_weight",
    "low_sample",
    "rookie_or_zero_sample",
    "missing_player_id",
]

# Starter certainty columns are text/metadata audit values only (POSTGAME_ONLY_EVIDENCE, UNKNOWN).
# They are dropped from the extraction parquet as they derive from postgame evidence.
STARTER_CERTAINTY_FEATURES = []

MARKET_TOKENS = (
    "moneyline", "spread_line", "total_line", "closing_", "pinnacle",
    "draftkings", "fanduel", "clv", "implied_probability",
    "market_probability", "market_price", "line_movement",
    "american_odds", "decimal_odds",
)
POSTGAME_TOKENS = ("postgame", "final_", "actual_")
ID_TOKENS = ("game_id", "prediction_id", "venue_id", "player_id", "team_id")


def _reject_columns(columns: list[str]) -> None:
    """Hard validation: no market, postgame, identifier, timestamp, or target columns."""
    for c in columns:
        low = c.lower()
        for token in MARKET_TOKENS:
            if token in low:
                raise ValueError(f"market column leaked into features: {c}")
        for token in POSTGAME_TOKENS:
            if token in low:
                raise ValueError(f"postgame column leaked into features: {c}")
        if c in ID_TOKENS:
            raise ValueError(f"identifier column leaked into features: {c}")
        if c.endswith("_utc"):
            raise ValueError(f"timestamp column leaked into features: {c}")
        if c in TARGET_COLUMNS:
            raise ValueError(f"target column leaked into features: {c}")


def _is_metadata_column(col: str) -> bool:
    return col in set(IDENTITY_COLUMNS + TIMESTAMP_COLUMNS + TARGET_COLUMNS + PROVENANCE_COLUMNS) or col in DROP_COLUMNS or col in TEXT_COLUMNS or col in REDUNDANT_METRIC_COLUMNS


def _is_model_feature(col: str) -> bool:
    """Determine whether a column is a model feature (not metadata, not redundant)."""
    if _is_metadata_column(col):
        return False
    # Drop team _missing / _imputed flags (values already imputed to priors)
    if (col.startswith("home_roll") or col.startswith("away_roll")
        or col.startswith("home_season_to_date") or col.startswith("away_season_to_date")):
        if col.endswith("_missing") or col.endswith("_imputed"):
            return False
    return True


def _infer_window(col: str) -> str:
    if "roll4" in col:
        return "last_4_eligible_games"
    if "roll8" in col:
        return "last_8_eligible_games"
    if "season_to_date" in col:
        return "current_season_prior_eligible_games"
    if "prior_season_carryover" in col:
        return "prior_season_carryover"
    if col in (
        "passing_epa_shrinkage_weight", "low_sample",
        "rookie_or_zero_sample", "missing_player_id",
    ):
        return "none"
    return "none"


def _football_interpretation(col: str) -> str:
    if col.startswith("home_qb_") or col.startswith("away_qb_"):
        base = col.split("_qb_", 1)[1]
        return f"leakage-safe pregame QB metric: {base}"
    if col == "neutral_site":
        return "neutral-site game indicator"
    if col == "venue_missing":
        return "whether venue information was missing"
    if col == "roof_category":
        return "roof type (dome/open/outdoors/closed)"
    if col == "roof_missing":
        return "whether roof type was missing"
    if col.endswith("_rest_or_week_gap"):
        return "rest/week-gap since last completed game"
    if col.endswith("_week_gap_proxy"):
        return "week-gap proxy (weeks since last game)"
    if col.endswith("_bye_week_proxy"):
        return "bye-week indicator (proxy)"
    if col.endswith("_early_season_sample"):
        return "early-season small-sample flag"
    if col.endswith("_prior_season_carryover_used"):
        return "whether prior-season carryover data was used"
    if col.endswith("_prior_season_carryover_games"):
        return "count of prior-season games carried over"
    if col.endswith("_games_played_before_current_game"):
        return "games played before current game"
    if col.endswith("_prior_games"):
        return "count of eligible prior games in window"
    if col.endswith("_minimum_sample_met"):
        return "minimum sample threshold met flag"
    if col.endswith("_missing"):
        return "missingness flag (primary value was imputed)"
    if col.endswith("_imputed"):
        return "imputation flag (value filled from prior)"
    if col.endswith("_std"):
        return "population std dev of rolling metric (variability)"
    if col.endswith("_std_missing"):
        return "missingness flag for std dev"
    if col.endswith("_win"):
        return "binary win in rolling window"
    if col.endswith("_loss"):
        return "binary loss in rolling window"
    if col.endswith("_tie"):
        return "binary tie in rolling window"
    if col.endswith("_win_rate"):
        return "win rate in rolling window"
    if col.endswith("_points_scored"):
        return "avg points scored per game in rolling window"
    if col.endswith("_points_allowed"):
        return "avg points allowed per game in rolling window"
    if col.endswith("_point_differential"):
        return "avg point differential in rolling window"
    if col.endswith("_passing_epa"):
        return "EPA per pass attempt (rolling)"
    if col.endswith("_rushing_epa"):
        return "EPA per rush attempt (rolling)"
    if col.endswith("_defensive_epa_allowed"):
        return "opponent EPA allowed = defensive strength (rolling)"
    if col.endswith("_passing_yards"):
        return "avg passing yards per game in rolling window"
    if col.endswith("_rushing_yards"):
        return "avg rushing yards per game in rolling window"
    if col.endswith("_shrinkage_weight"):
        return "shrinkage weight (observed data proportion)"
    return "team performance metric"


def _inclusion_reason(col: str) -> str:
    if col.startswith("home_qb_") or col.startswith("away_qb_"):
        return "Approved QB pregame metric from config/features.yaml qb_features"
    if col in ("neutral_site", "venue_missing", "roof_category", "roof_missing"):
        return "Approved game-context from config/features.yaml team_features"
    if col.endswith("_minimum_sample_met"):
        return "Minimum-sample flag (config rolling_windows.minimum_games=3)"
    if col.endswith("_missing") or col.endswith("_imputed"):
        return "Missingness flag (config missingness.add_indicators=true)"
    if col.endswith("_std") or col.endswith("_std_missing"):
        return "Volatility measure (roll4/roll8 only, approved in pipeline)"
    if col.endswith("_prior_games"):
        return "Sample-size context for rolling metric interpretation"
    if col.startswith("away_") or col.startswith("home_"):
        return "Approved team rolling metric (shift-before-rolling, fixed priors)"
    return "Approved feature from frozen v1 pipeline"


def _redundancy_decision(col: str) -> str:
    if col.endswith("_prior_games"):
        return "retained: sample-size context"
    if col.endswith("_minimum_sample_met"):
        return "retained: hard gate flag"
    if col.endswith("_missing") or col.endswith("_imputed"):
        return "retained: explicit boolean flag (not redundant)"
    return "retained: distinct football information (no deterministic redundancy)"


def _build_feature_entries(model_feature_cols: list[str]) -> list[dict[str, Any]]:
    entries = []
    for idx, col in enumerate(model_feature_cols):
        if col.startswith("home_qb_") or col.startswith("away_qb_"):
            source_field = col.split("_qb_", 1)[1]
            source_artifact = SOURCE_QB_FEATURES
            reg_class = "quarterback"
        elif col in ("neutral_site", "venue_missing", "roof_category", "roof_missing"):
            source_field = col
            source_artifact = SOURCE_GAME_FEATURES
            reg_class = "game_context"
        else:
            source_field = col
            source_artifact = SOURCE_GAME_FEATURES
            if col.endswith("_minimum_sample_met"):
                reg_class = "sample_size"
            elif col.endswith("_missing") or col.endswith("_imputed"):
                reg_class = "missingness"
            elif col.endswith("_std") or col.endswith("_std_missing"):
                reg_class = "variability"
            elif any(x in col for x in (
                "rest_or_week_gap", "week_gap_proxy", "bye_week_proxy",
                "early_season_sample", "prior_season_carryover_used",
                "prior_season_carryover_games",
                "games_played_before_current_game",
            )):
                reg_class = "game_context"
            elif col.endswith("_prior_games"):
                reg_class = "sample_size"
            else:
                reg_class = "team_performance"

        if col.endswith("_missing") or col.endswith("_imputed") or col.endswith("_met") or col.endswith("_std_missing"):
            numeric_type = "boolean"
            encoding = "native (0/1)"
            missing_policy = "native_missing (boolean flag)"
        elif col in ("roof_category",):
            numeric_type = "categorical"
            encoding = "one-hot or ordinal"
            missing_policy = "categorical_unknown"
        else:
            numeric_type = "float64"
            encoding = "native numeric"
            missing_policy = "fixed_documented_priors or native_missing"

        structural_type = "flag" if numeric_type == "boolean" else (
            "level" if numeric_type == "float64" else
            ("count" if reg_class == "sample_size" and col.endswith("_prior_games") else
             "level")
        )
        if col.endswith("_std"):
            structural_type = "level"

        entries.append({
            "model_feature_index": idx,
            "model_feature_name": col,
            "source_field": source_field,
            "source_artifact": source_artifact,
            "transformation": "shift_before_rolling_then_fixed_prior_if_missing; shrinkage per qb_config",
            "numeric_type": numeric_type,
            "encoding": encoding,
            "missing_value_policy": missing_policy,
            "registry_classification": reg_class,
            "registry_window": _infer_window(col),
            "football_interpretation": _football_interpretation(col),
            "reason_for_inclusion": _inclusion_reason(col),
            "redundancy_decision": _redundancy_decision(col),
            "structural_type": structural_type,
        })
    return entries


CONFIG_YAML = """\
base_sha: a93bfe1f7ffaaac7bff8758bf278af1ce07149db
extraction:
  source_artifacts:
    - data/derived/features_v1/game_features_2018_2025.parquet
    - data/derived/features_v1/qb_pregame_features_2018_2025.parquet
    - data/derived/features_v1/starter_certainty_2018_2025.parquet
  output_artifact: data/derived/features_v1/xgboost_development_2018_2024.parquet
  development_seasons: [2018-2024]
  season_gate_policy: reject 2025+ (sealed holdout) and 2026+ (forward-use)
  season_gate_enforcement: hard rejection at extraction boundary

target_policy:
  target: "P(home team wins)"
  encoding: home_win=1, away_win=0, tie=excluded, unknown=excluded
  columns: [target_home_win, target_margin, target_tie, target_available]
  note: "Targets preserved in extraction parquet; never enter model matrix"

exclusions:
  identifiers: "game_id, team names, venue_id, player_ids — metadata only"
  timestamps: "feature_as_of_utc, prediction_as_of_utc, source_available_at_utc, scheduled_start_utc"
  market_data: "no market columns in source; market tokens rejected at extraction"
  postgame_outcomes: "home_score, away_score, target_margin — postgame, excluded from features"
  qb_player_ids: "expected_home_qb_id, expected_away_qb_id — Null/raw IDs, excluded"
  qb_status: "qb_status is POSTGAME_ONLY_EVIDENCE for all rows — not forward-looking"
  postgame_qb_evidence_ids: "postgame evidence IDs excluded from model matrix"
  qb_observed_prior_constants: "passing_epa_observed, passing_epa_prior, passing_epa_sample_size, prior_dropback_or_attempt_volume, prior_games — constant at priors in base commit, redundant with shrunk values + flags"
  qb_imputed_flags: "*_imputed flags for QB metrics — all True (constant), uninformative in base commit"
  offensive_total_epa: "deterministic identity (passing_epa + rushing_epa); excluded to avoid duplication"
  is_home: "home_is_home/away_is_home constant per side; excluded (redundant with team identity)"
  starter_certainty_text: "starter_certainty, home_starter_certainty, away_starter_certainty — string-valued postgame evidence audit, not numeric features"

feature_contract:
  column_order: "identity -> timestamp -> provenance -> context -> team metrics -> QB -> targets"
  row_order: "season ASC, week ASC, game_id ASC"

determinism:
  xgboost_random_seed: 42
  xgboost_nthread: 1
  xgboost_tree_method: hist

feature_count_target:
  min: 80
  max: 140
"""


def _build_config_yaml(feature_count: int, extraction_sha256: str, hash_values: dict[str, str]) -> str:
    yaml = CONFIG_YAML
    yaml += f"feature_count_actual: {feature_count}\n"
    yaml += f"extraction_sha256: {extraction_sha256}\n"
    yaml += "hashes:\n"
    for key, val in hash_values.items():
        yaml += f"  {key}: {val}\n"
    return yaml


def generate(root: Path | None = None) -> dict[str, Any]:
    if root is None:
        root = Path(__file__).resolve().parent.parent.parent.parent

    games = pl.read_parquet(root / SOURCE_GAME_FEATURES)
    qb = pl.read_parquet(root / SOURCE_QB_FEATURES)

    # --- Season gate: 2018-2024 only, reject 2025+ ---
    dev_games = games.filter(
        pl.col("season").is_between(DEVELOPMENT_SEASON_MIN, DEVELOPMENT_SEASON_MAX)
    )

    # Reject duplicates
    dup_count = dev_games["game_id"].is_duplicated().sum()
    if dup_count > 0:
        raise ValueError(f"duplicate game_id count: {dup_count}")

    # --- Join QB features (candidate_rank=1, per side, only retained QB columns) ---
    qb_dev = qb.filter(
        pl.col("season").is_between(DEVELOPMENT_SEASON_MIN, DEVELOPMENT_SEASON_MAX)
    ).filter(pl.col("candidate_rank") == 1)

    qb_select_cols = ["game_id", "side"] + QB_FEATURE_COLUMNS
    qb_home = qb_dev.filter(pl.col("side") == "home").select(qb_select_cols).rename(
        {col: f"home_qb_{col}" for col in QB_FEATURE_COLUMNS}
    ).select(["game_id"] + [f"home_qb_{c}" for c in QB_FEATURE_COLUMNS])
    qb_away = qb_dev.filter(pl.col("side") == "away").select(qb_select_cols).rename(
        {col: f"away_qb_{col}" for col in QB_FEATURE_COLUMNS}
    ).select(["game_id"] + [f"away_qb_{c}" for c in QB_FEATURE_COLUMNS])

    dev = dev_games.join(qb_home, on="game_id", how="left")
    dev = dev.join(qb_away, on="game_id", how="left")

    # --- Drop non-feature columns ---
    cols_to_drop = [c for c in DROP_COLUMNS if c in dev.columns]
    if cols_to_drop:
        dev = dev.drop(cols_to_drop)

    # --- Drop redundant metric columns ---
    cols_redundant = [c for c in REDUNDANT_METRIC_COLUMNS if c in dev.columns]
    if cols_redundant:
        dev = dev.drop(cols_redundant)

    # --- Drop text columns from the parquet (kept in contract as excluded) ---
    cols_text = [c for c in TEXT_COLUMNS if c in dev.columns]
    if cols_text:
        dev = dev.drop(cols_text)

    # --- Determine model feature columns ---
    model_feature_cols = [c for c in dev.columns if _is_model_feature(c)]
    _reject_columns(model_feature_cols)

    # --- Reorder columns deterministically ---
    ordered: list[str] = []
    ordered.extend([c for c in IDENTITY_COLUMNS if c in dev.columns])
    ordered.extend([c for c in TIMESTAMP_COLUMNS if c in dev.columns])
    ordered.extend([c for c in PROVENANCE_COLUMNS if c in dev.columns])

    # Context columns
    context_cols = sorted(
        c for c in dev.columns
        if c in ("neutral_site", "venue_missing", "roof_category", "roof_missing")
        or any(c.startswith(p) for p in (
            "away_games_played_before_current_game", "home_games_played_before_current_game",
            "away_prior_season_carryover_used", "home_prior_season_carryover_used",
            "away_prior_season_carryover_games", "home_prior_season_carryover_games",
            "away_early_season_sample", "home_early_season_sample",
            "away_rest_or_week_gap", "home_rest_or_week_gap",
            "away_week_gap_proxy", "home_week_gap_proxy",
            "away_bye_week_proxy", "home_bye_week_proxy",
        ))
    )
    ordered.extend(context_cols)

    # QB features
    qb_cols = sorted(c for c in dev.columns if c.startswith("home_qb_") or c.startswith("away_qb_"))
    ordered.extend(qb_cols)

    # Team rolling metrics — deterministic order: away then home, roll4 then roll8 then season_to_date
    team_cols = []
    for prefix_base in ("away", "home"):
        for window in ("roll4", "roll8", "season_to_date"):
            prefix = f"{prefix_base}_{window}_"
            window_cols = sorted(c for c in dev.columns if c.startswith(prefix))
            team_cols.extend(window_cols)
    ordered.extend(team_cols)

    # Target columns
    target_cols = [c for c in TARGET_COLUMNS if c in dev.columns]
    ordered.extend(target_cols)

    # Any remaining
    remaining = [c for c in dev.columns if c not in ordered]
    ordered.extend(remaining)
    ordered = list(dict.fromkeys(ordered))

    dev = dev.select(ordered)

    # --- Sort rows deterministically ---
    dev = dev.sort(["season", "week", "game_id"])

    # --- Final validation ---
    model_feature_cols = [c for c in dev.columns if _is_model_feature(c)]
    _reject_columns(model_feature_cols)

    # Validate no 2025+ rows
    season_check = dev["season"].unique().sort()
    assert season_check[0] >= DEVELOPMENT_SEASON_MIN
    assert season_check[-1] <= DEVELOPMENT_SEASON_MAX

    # --- Write parquet ---
    output_path = root / OUTPUT_PARQUET
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dev.write_parquet(
        output_path,
        compression="zstd",
        statistics=True,
        row_group_size=65536,
        use_pyarrow=False,
    )

    sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()

    # Logical content hash (path-independent)
    logical = hashlib.sha256()
    logical.update(json.dumps(dev.columns).encode())
    logical.update(json.dumps(dev["game_id"].sort().to_list()).encode())
    logical_hash = logical.hexdigest()

    # --- Build feature contract ---
    feature_entries = _build_feature_entries(model_feature_cols)
    source_fields = sorted(set(e["source_field"] for e in feature_entries))
    feature_order_list = [e["model_feature_name"] for e in feature_entries]

    excluded_groups = {
        "identifiers": "game_id, team names, venue_id, player_ids — metadata only",
        "targets": "target_home_win, target_margin, target_tie, target_available — preserved separately",
        "timestamps": "feature_as_of_utc, prediction_as_of_utc, source_available_at_utc, scheduled_start_utc",
        "market_data": "no market columns in source; market tokens rejected at extraction",
        "postgame_outcomes": "home_score, away_score, target_margin — postgame, excluded from features",
        "qb_player_ids": "expected_home_qb_id, expected_away_qb_id — Null/raw IDs, excluded",
        "qb_status": "qb_status is POSTGAME_ONLY_EVIDENCE for all rows — not forward-looking",
        "postgame_qb_evidence_ids": "postgame evidence IDs excluded from model matrix",
        "venue_id": "venue_id — raw venue identifier, excluded",
        "qb_observed_prior_constants": "passing_epa_observed, passing_epa_prior, passing_epa_sample_size, prior_dropback_or_attempt_volume, prior_games — constant at priors in base commit, redundant with shrunk values + flags",
        "qb_imputed_flags": "*_imputed flags for QB metrics — all True (constant), uninformative in base commit",
        "offensive_total_epa": "deterministic identity (passing_epa + rushing_epa); excluded to avoid duplication",
        "is_home": "home_is_home/away_is_home constant per side; excluded (redundant with team identity)",
        "starter_certainty_text": "starter_certainty, home_starter_certainty, away_starter_certainty — string-valued postgame evidence audit columns, not numeric features",
    }

    feature_order_hash = hashlib.sha256(
        json.dumps(feature_order_list, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    source_field_hash = hashlib.sha256(
        json.dumps(source_fields, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    transform_specs = [
        {"field": e["model_feature_name"], "source_field": e["source_field"],
         "source_artifact": e["source_artifact"], "transformation": e["transformation"]}
        for e in feature_entries
    ]
    transformation_hash = hashlib.sha256(
        json.dumps(transform_specs, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    logical_contract_hash = hashlib.sha256(
        json.dumps(feature_order_list + source_fields, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    exclusion_hash = hashlib.sha256(
        json.dumps({
            "identity_columns": sorted(IDENTITY_COLUMNS),
            "timestamp_columns": sorted(TIMESTAMP_COLUMNS),
            "target_columns": sorted(TARGET_COLUMNS),
            "provenance_columns": sorted(PROVENANCE_COLUMNS),
            "drop_columns": sorted(DROP_COLUMNS),
            "text_columns": sorted(TEXT_COLUMNS),
            "redundant_metric_columns": sorted(REDUNDANT_METRIC_COLUMNS),
            "qb_excluded_columns": sorted([
                "passing_epa_observed", "passing_epa_prior",
                "passing_epa_sample_size", "prior_dropback_or_attempt_volume",
                "prior_games", "passing_epa_imputed",
                "passing_cpoe_imputed", "sack_rate_imputed",
                "interception_rate_imputed",
            ]),
        }, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    hash_values = {
        "feature_order_hash": feature_order_hash,
        "source_field_hash": source_field_hash,
        "transformation_hash": transformation_hash,
        "logical_contract_hash": logical_contract_hash,
        "exclusion_hash": exclusion_hash,
    }

    contract = {
        "contract_version": "xgboost_v1",
        "base_sha": BASE_SHA,
        "development_seasons": list(range(DEVELOPMENT_SEASON_MIN, DEVELOPMENT_SEASON_MAX + 1)),
        "source_artifacts": [SOURCE_GAME_FEATURES, SOURCE_QB_FEATURES, SOURCE_STARTER_CERTAINTY],
        "extraction_artifact": OUTPUT_PARQUET,
        "model_feature_count": len(feature_entries),
        "source_field_count": len(source_fields),
        "deterministic_ordering": {
            "row_order": "season ASC, week ASC, game_id ASC",
            "column_order": "identity -> timestamp -> provenance -> context -> QB -> team metrics -> targets",
            "feature_order": feature_order_list,
        },
        "hashes": hash_values,
        "logical_content_hash": logical_hash,
        "extraction_provenance": {
            "sha256": sha256,
            "row_count": dev.height,
            "column_count": dev.width,
            "byte_size": output_path.stat().st_size,
            "season_min": DEVELOPMENT_SEASON_MIN,
            "season_max": DEVELOPMENT_SEASON_MAX,
            "duplicate_game_count": 0,
            "feature_count_target_min": 80,
            "feature_count_target_max": 140,
            "feature_count_in_range": 80 <= len(feature_entries) <= 140,
        },
        "excluded_groups": excluded_groups,
        "features": feature_entries,
    }

    # Write contract JSON
    contract_path = root / OUTPUT_CONTRACT
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")

    # Write YAML config
    yaml_path = root / OUTPUT_CONFIG_YAML
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_content = _build_config_yaml(len(feature_entries), sha256, hash_values)
    yaml_path.write_text(yaml_content)

    return contract


if __name__ == "__main__":
    result = generate()
    print(f"Extraction: {result['extraction_artifact']}")
    print(f"  rows={result['extraction_provenance']['row_count']}, cols={result['extraction_provenance']['column_count']}")
    print(f"  sha256={result['extraction_provenance']['sha256']}")
    print(f"  logical_hash={result['logical_content_hash']}")
    print(f"  feature_count_in_range={result['extraction_provenance']['feature_count_in_range']}")
    print(f"Model features: {result['model_feature_count']}")
    print(f"Source fields: {result['source_field_count']}")
    print(f"Feature order hash: {result['hashes']['feature_order_hash']}")
    print(f"Source field hash: {result['hashes']['source_field_hash']}")
    print(f"Transformation hash: {result['hashes']['transformation_hash']}")
    print(f"Exclusion hash: {result['hashes']['exclusion_hash']}")
    print(f"Contract written to: {OUTPUT_CONTRACT}")
    print(f"Config written to: {OUTPUT_CONFIG_YAML}")
