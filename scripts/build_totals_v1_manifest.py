#!/usr/bin/env python3
"""Generate the machine-readable Totals V1 feature manifest.

Produces data/manifests/task05c_totals_feature_manifest_v1.json describing
exactly the accepted 90-CORE_V1 model-input predictor universe, in
EXACT_90_COLUMNS order, plus the DEFER/REJECT candidate-family adjudication.

Frozen-contract rule (Task05C): translate the accepted contract literally; do
not invent families, aliases, minima, windows, or a new safety taxonomy.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, "/root/workspaces/nfl-edge-totals-feature-contract-v1/src")
from nfl_edge.features.totals_v1.feature_table import EXACT_90_COLUMNS

WORKSPACE = Path("/root/workspaces/nfl-edge-totals-feature-contract-v1")
FEATURES = WORKSPACE / "data/derived/totals_v1_features_2018_2024.parquet"
OUT = WORKSPACE / "data/manifests/task05c_totals_feature_manifest_v1.json"

# ---- Pre-game safety classes (ONLY these four labels) ----
SAFE_STATIC = "SAFE_STATIC"      # scheduled context (rest/roof/surface)
SAFE_LAGGED = "SAFE_LAGGED"      # prior-completed-block PBP matchup state
SAFE_SHRUNK = "SAFE_SHRUNK"      # accepted Oracle-QB entering/shrunk state
UNSAFE_TARGET_GAME = "UNSAFE_TARGET_GAME"
UNSAFE_FUTURE = "UNSAFE_FUTURE"

IDENTITY_NON_MODEL = [
    "game_id", "season", "season_type", "week", "home_team", "away_team",
    "block_id", "home_score", "away_score", "target_total_points",
]

# ---- Family templates (A-N original Task05C families) ----
# family -> (primary letter, source_artifact, raw_source_fields, safety_class,
#            history/window rule, denominator/minimum rule, numeric_or_cat)
FAMILY = {
    "rest_scheduling": {
        "letter": "L", "source_artifact": "data/raw/source_snapshots/v1/schedules_2018_2025_frozen-baseline-v1.parquet",
        "raw_source_fields": ["away_rest", "home_rest"],
        "safety": SAFE_STATIC,
        "history": "scheduled pregame rest gap (source integer); side-specific, static context",
        "denom": "none (scheduled value); null + *_missing=1 if absent",
        "cat": False,
    },
    "game_environment": {
        "letter": "K", "source_artifact": "data/frozen/games/games_2018_2025.parquet + raw frozen schedules",
        "raw_source_fields": ["roof_type", "surface"],
        "safety": SAFE_STATIC,
        "history": "venue context; scheduled pregame static categorical",
        "denom": "none; categorical unknown -> 'unknown' + *_missing=1",
        "cat": True,
    },
    "quarterback_context": {
        "letter": "M", "source_artifact": "data/derived/oracle_qb_entering_state_v2/oracle_qb_entering_state_game_sides_2018_2024_v2.parquet",
        "raw_source_fields": ["passing_epa", "passing_cpoe", "sacks_suffered_rate", "interception_rate", "recency_weighted_form", "prior_dropback_or_attempt_volume", "low_sample", "missing_player_id", "*_imputed"],
        "safety": SAFE_SHRUNK,
        "history": "accepted Oracle-QB entering-state v2; prior eligible games, fixed priors, 250-dropback shrinkage, 0.75 decay over last 8 eligible games",
        "denom": "accepted builder shrinkage/sample semantics; quality fields (imputed/low_sample/missing_player_id) as accepted",
        "cat": False,
    },
    "offensive_defensive_efficiency": {
        "letter": "A/B", "source_artifact": "data/derived/totals_v1_features_2018_2024.parquet (from PBP)",
        "raw_source_fields": ["epa", "success", "fixed_drive", "fixed_drive_result", "posteam", "defteam"],
        "safety": SAFE_LAGGED,
        "history": "expanding volume-weighted ratio over eligible prior completed blocks; cross-season retained",
        "denom": "EPA/play & success rate min 20 plays; points/drive & scoring-drive min 5 possessions",
        "cat": False,
    },
    "pace_play_volume": {
        "letter": "C", "source_artifact": "data/derived/totals_v1_features_2018_2024.parquet (from PBP)",
        "raw_source_fields": ["game_seconds_remaining", "qtr", "play_id", "fixed_drive", "posteam", "play_type"],
        "safety": SAFE_LAGGED,
        "history": "expanding volume-weighted ratio over eligible prior completed blocks",
        "denom": "seconds/play min 10 clock intervals",
        "cat": False,
    },
    "passing_environment": {
        "letter": "D", "source_artifact": "data/derived/totals_v1_features_2018_2024.parquet (from PBP)",
        "raw_source_fields": ["pass_attempt", "rush_attempt", "air_yards", "yards_after_catch", "complete_pass", "qb_dropback"],
        "safety": SAFE_LAGGED,
        "history": "expanding volume-weighted ratio over eligible prior completed blocks",
        "denom": "neutral pass rate min 20 attempts; air_yards/attempt min 20 observed-air_yards attempts; YAC/completion min 20 observed-YAC completions",
        "cat": False,
    },
    "rushing_environment": {
        "letter": "E", "source_artifact": "data/derived/totals_v1_features_2018_2024.parquet (from PBP)",
        "raw_source_fields": ["yards_gained", "rush_attempt"],
        "safety": SAFE_LAGGED,
        "history": "expanding volume-weighted ratio over eligible prior completed blocks",
        "denom": "explosive rush min 20 observed-yards kneel-excluded rush attempts",
        "cat": False,
    },
    "explosive_play": {
        "letter": "F", "source_artifact": "data/derived/totals_v1_features_2018_2024.parquet (from PBP)",
        "raw_source_fields": ["yards_gained", "pass_attempt", "rush_attempt"],
        "safety": SAFE_LAGGED,
        "history": "expanding volume-weighted ratio over eligible prior completed blocks",
        "denom": "explosive pass min 20 observed-yards pass attempts; explosive rush min 20 observed-yards rush attempts",
        "cat": False,
    },
    "redzone_finishing": {
        "letter": "G", "source_artifact": "data/derived/totals_v1_features_2018_2024.parquet (from PBP)",
        "raw_source_fields": ["yardline_100", "goal_to_go", "fixed_drive", "fixed_drive_result", "posteam"],
        "safety": SAFE_LAGGED,
        "history": "expanding volume-weighted ratio over eligible prior completed blocks",
        "denom": "red-zone & goal-to-go TD rate min 5 opportunities",
        "cat": False,
    },
    "turnover_environment": {
        "letter": "H", "source_artifact": "data/derived/totals_v1_features_2018_2024.parquet (from PBP)",
        "raw_source_fields": ["interception", "fumble_lost", "fixed_drive", "posteam"],
        "safety": SAFE_LAGGED,
        "history": "expanding volume-weighted ratio over eligible prior completed blocks; one qualifying event per VFP",
        "denom": "turnovers/drive min 5 possessions",
        "cat": False,
    },
    "pressure_sacks": {
        "letter": "I", "source_artifact": "data/derived/totals_v1_features_2018_2024.parquet (from PBP)",
        "raw_source_fields": ["sack", "qb_dropback"],
        "safety": SAFE_LAGGED,
        "history": "expanding volume-weighted ratio over eligible prior completed blocks",
        "denom": "sacks/dropback min 20 dropbacks",
        "cat": False,
    },
}

# Column -> (family, description-prefix) for the 90 predictors.
# Map each EXACT_90 column to its family and a short description.
COL_DESC = {}
def _add(fam, *names):
    for n in names:
        COL_DESC[n] = fam

_add("rest_scheduling", "away_rest_days", "away_rest_days_missing", "home_rest_days", "home_rest_days_missing")
_add("game_environment", "roof_category", "roof_missing", "surface_category", "surface_missing")
_add("quarterback_context",
     "away_qb_passing_epa", "away_qb_passing_epa_imputed", "away_qb_passing_cpoe",
     "away_qb_passing_cpoe_imputed", "away_qb_sacks_suffered_rate", "away_qb_sack_rate_imputed",
     "away_qb_interception_rate", "away_qb_interception_rate_imputed", "away_qb_recency_weighted_form",
     "away_qb_low_sample", "away_qb_missing_player_id",
     "home_qb_passing_epa", "home_qb_passing_epa_imputed", "home_qb_passing_cpoe",
     "home_qb_passing_cpoe_imputed", "home_qb_sacks_suffered_rate", "home_qb_sack_rate_imputed",
     "home_qb_interception_rate", "home_qb_interception_rate_imputed", "home_qb_recency_weighted_form",
     "home_qb_low_sample", "home_qb_missing_player_id")

# Matchup PBP columns: <side>_matchup_<metric>[,_missing]
PBP_SIDE = {
    "offensive_defensive_efficiency": ["epa_per_play", "success_rate", "points_per_drive", "scoring_drive_rate"],
    "pace_play_volume": ["seconds_per_play", "neutral_seconds_per_play"],
    "passing_environment": ["neutral_pass_rate", "air_yards_per_attempt", "yac_per_completion"],
    "rushing_environment": ["explosive_rush_rate"],
    "explosive_play": ["explosive_pass_rate", "explosive_rush_rate"],
    "redzone_finishing": ["red_zone_td_rate", "goal_to_go_td_rate"],
    "turnover_environment": ["turnovers_per_drive"],
    "pressure_sacks": ["sacks_per_dropback"],
}
for fam, metrics in PBP_SIDE.items():
    for side in ("away", "home"):
        for m in metrics:
            _add(fam, f"{side}_matchup_{m}", f"{side}_matchup_{m}_missing")

assert set(COL_DESC.keys()) == set(EXACT_90_COLUMNS), (
    f"COL_DESC key mismatch: extra={set(COL_DESC)-set(EXACT_90_COLUMNS)}, "
    f"missing={set(EXACT_90_COLUMNS)-set(COL_DESC)}"
)

# Also assign a secondary family for G (finishing) overlap on points/scoring-drive
# and F/E overlap on explosive_rush. Contract allows conceptual overlap; primary
# family is used for manifest income; secondary is advisory only.
SECONDARY = {
    "away_matchup_points_per_drive": "redzone_finishing",
    "home_matchup_points_per_drive": "redzone_finishing",
    "away_matchup_scoring_drive_rate": "redzone_finishing",
    "home_matchup_scoring_drive_rate": "redzone_finishing",
    "away_matchup_explosive_rush_rate": "rushing_environment",
    "home_matchup_explosive_rush_rate": "rushing_environment",
}

GEN_DESC = {
    "rest_scheduling": "scheduled rest-days gap (side-specific static context)",
    "game_environment": "scheduled venue categorical context",
    "quarterback_context": "accepted Oracle-QB entering-state v2 numeric/shrunk state",
    "offensive_defensive_efficiency": "expanding prior-block offensive/defensive EPA, success, points/drive, scoring-drive matchup",
    "pace_play_volume": "expanding prior-block pace (seconds/play) matchup",
    "passing_environment": "expanding prior-block pass-rate / air-yards / YAC matchup",
    "rushing_environment": "expanding prior-block explosive-rush matchup",
    "explosive_play": "expanding prior-block explosive pass/rush matchup",
    "redzone_finishing": "expanding prior-block red-zone / goal-to-go TD-rate matchup",
    "turnover_environment": "expanding prior-block turnovers/drive matchup",
    "pressure_sacks": "expanding prior-block sacks/dropback matchup",
}

def num_or_cat(col):
    return "categorical" if col in ("roof_category", "surface_category") else "numeric"

def missing_rule(col, fam):
    if col in ("roof_category", "surface_category"):
        return "null/missing source -> lower-case 'unknown' + *_missing=1"
    if col in ("away_rest_days", "home_rest_days"):
        return "absent rest value -> null + *_missing=1"
    if col.endswith("_missing"):
        return "paired missing indicator (0/1); 1 = state null/below minimum/unavailable"
    if col.startswith(("away_qb_", "home_qb_")) and (col.endswith("_imputed") or col in ("away_qb_low_sample", "away_qb_missing_player_id", "home_qb_low_sample", "home_qb_missing_player_id")):
        return "accepted Oracle quality field; 0/1 flag"
    return "null below metric minimum or unavailable; paired *_missing=1 (no imputation)"

def transformation(col, fam):
    if col in ("roof_category", "surface_category"):
        return "lower-case categorical category from accepted source"
    if col.endswith("_missing"):
        return "indicator (0/1) for state unavailability"
    if col.startswith(("away_qb_", "home_qb_")):
        return "join accepted Oracle-QB entering-state numeric field"
    if col.startswith(("away_matchup_", "home_matchup_")):
        return "(offense_X + opponent_defense_allowed_X)/2 matchup blend; side-inverted, accepted formula"
    return "source integer rest gap"

def load_dtypes():
    f = pl.read_parquet(FEATURES)
    return {c: str(f.schema[c]) for c in f.columns}

def main():
    dtypes = load_dtypes()
    records = []
    for ordinal, col in enumerate(EXACT_90_COLUMNS, start=1):
        fam = COL_DESC[col]
        fm = FAMILY[fam]
        secondary = SECONDARY.get(col)
        rec = {
            "ordinal": ordinal,
            "feature_name": col,
            "description": f"{fm['letter']}-family: {GEN_DESC[fam]} ({col})",
            "feature_family": fam,
            "original_family_letter": fm["letter"],
            "secondary_family": secondary,
            "source_artifact": fm["source_artifact"],
            "raw_source_fields": fm["raw_source_fields"],
            "transformation": transformation(col, fam),
            "history_window_rule": fm["history"],
            "denominator_minimum_rule": fm["denom"],
            "pregame_safety_class": fm["safety"],
            "datatype": dtypes[col],
            "missing_value_rule": missing_rule(col, fam),
            "numeric_or_categorical": num_or_cat(col),
            "seasons_covered": [2018, 2019, 2020, 2021, 2022, 2023, 2024],
            "inclusion_status": "CORE_V1",
            "production_parity_status": "PENDING",
            "model_input": True,
        }
        records.append(rec)

    assert len(records) == 90, f"expected 90 records, got {len(records)}"
    assert [r["feature_name"] for r in records] == list(EXACT_90_COLUMNS)

    adjudication = [
        {
            "family": "interception_rate",
            "classification": "DEFERRED",
            "reason": "Legitimate PBP definition exists but redundant with turnover rate and accepted Oracle QB interception rate in simple V1; no implementation authorized.",
            "letter": "H",
        },
        {
            "family": "lost_fumble_rate",
            "classification": "DEFERRED",
            "reason": "Legitimate PBP definition exists but sparse and redundant with turnover rate; no implementation authorized.",
            "letter": "H",
        },
        {
            "family": "weekly_frozen_direct_stat_representations",
            "classification": "DEFERRED",
            "reason": "Weekly/frozen EPA totals, CPOE, attempts/carries/yards, and scoring history preserved for audit/cross-check only; PBP rates or Oracle interface are the selected canonical V1 representations (avoids duplicate representations).",
            "letter": "A/B/D/E/J",
        },
        {
            "family": "lagged_snap_participation",
            "classification": "DEFERRED",
            "reason": "Frozen snap counts, prior eligible games only, could support a future participation proxy but is player-selection-dependent; no stable totals aggregation selected.",
            "letter": "N",
        },
        {
            "family": "current_injuries_depth",
            "classification": "DEFERRED",
            "reason": "No accepted pregame historical timestamp semantics for injuries/depth; would risk postgame/batch leakage.",
            "letter": "N",
        },
        {
            "family": "qb_hits_per_dropback",
            "classification": "DEFERRED",
            "reason": "Nullable qb_hit 0/1 is a legitimate hit proxy but excluded for redundancy; never pressure/hurry. If ever enabled name must be qb_hits_per_dropback / qb_hits_allowed_per_dropback.",
            "letter": "I",
        },
        {
            "family": "true_pressure_hurry",
            "classification": "REJECTED",
            "reason": "No legitimate source field; qb_hit is only a named proxy; must not mislabel a proxy as pressure/hurry.",
            "letter": "I",
        },
        {
            "family": "realized_historical_temperature_wind",
            "classification": "REJECTED",
            "reason": "Schedule/PBP temp and wind are realized historical results, not pregame predictors; result-derived context prohibited.",
            "letter": "K",
        },
    ]

    manifest = {
        "schema_version": "totals_v1_feature_manifest_v1",
        "base_commit_sha": "bc1d85414dd2c7c8fafb572946706c1cc0394345",
        "contract_sha256": "becc6fb9211ea56527cf580f3bad168998c23e2c4f868de226becfce6546e061",
        "feature_artifact_sha256": "d33d88cb97756e0074408ea4e859b6ae30e5ae7cfa428b3080799613c042a9f6",
        "identity_artifact_sha256": "67db18cd117fa2c789153d322807ae987159ea321e3c98ff56e077bbe1e8bf61",
        "feature_artifact_path": "data/derived/totals_v1_features_2018_2024.parquet",
        "identity_artifact_path": "data/derived/totals_v1_feature_identity_2018_2024.parquet",
        "num_core_v1": 90,
        "num_optional_v1": 0,
        "num_deferred": 6,
        "num_rejected": 2,
        "inclusion_statuses": {"CORE_V1": 90, "OPTIONAL_V1": 0, "DEFERRED": 6, "REJECTED": 2},
        "pregame_safety_classes_used": ["SAFE_STATIC", "SAFE_LAGGED", "SAFE_SHRUNK"],
        "not_model_features": {
            "note": "The following are NOT model features and must never be in the 90-column model-input projection.",
            "identity_columns": ["game_id", "season", "season_type", "week", "home_team", "away_team", "block_id"],
            "target_diagnostic_columns": ["home_score", "away_score", "target_total_points"],
        },
        "candidate_family_adjudication": adjudication,
        "feature_records": records,
    }

    # deterministic logical fingerprint over the records (stable ordering)
    canon = json.dumps(manifest, indent=2, sort_keys=True)
    logical_fp = hashlib.sha256(canon.encode()).hexdigest()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(canon + "\n")
    byte_sha = hashlib.sha256(OUT.read_bytes()).hexdigest()
    print(f"wrote {OUT}")
    print(f"records={len(records)} core_v1={len(records)} optional_v1=0")
    print(f"logical_fingerprint_sha256={logical_fp}")
    print(f"byte_sha256={byte_sha}")

if __name__ == "__main__":
    main()
