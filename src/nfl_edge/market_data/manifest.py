"""Frozen market-source acquisition manifest (Task 05E-C3).

Single source of truth for the *authoritative historical sportsbook
acquisition* contract. These constants are serialized to
``data/manifests/historical_market_acquisition_v1.json`` by the build script
so the frozen artifact and the code can never drift.

Architecture firewall (enforced downstream, not here): sportsbook market data
is DOWNSTREAM-ONLY. It must never become a feature/training input to any
frozen football model (Oracle QB-Elo, XGBoost, Expected-Margin, Ridge Totals).
This module only *prepares* RAW acquisition; it contains no outcome scoring.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# --- Source -----------------------------------------------------------------
PROVIDER = "the_odds_api"
SPORT = "americanfootball_nfl"
ODDS_API_HISTORICAL_BASE = (
    "https://api.the-odds-api.com/v4/historical/sports/americanfootball_nfl/odds/"
)
ODDS_API_REGIONS = "us"
ODDS_API_ODDS_FORMAT = "american"

# --- Coverage ---------------------------------------------------------------
ACQUISITION_SEASONS: tuple[int, ...] = (2020, 2021, 2022, 2023, 2024)
# 2018-2019 deliberately excluded: authoritative sportsbook history is not
# available in this acquisition phase and nflverse market-like fields must
# NOT be substituted as authoritative sportsbook history.
UNRESOLVED_SEASONS: tuple[int, ...] = (2018, 2019)
# Future preregistered split (recorded without scoring, if 2018-2019 remain
# unavailable before edge scoring):
FUTURE_DISCOVERY_SEASONS: tuple[int, ...] = (2020, 2021, 2022)
FUTURE_CONFIRMATION_SEASONS: tuple[int, ...] = (2023, 2024)

# --- Schedule (kickoff) source ----------------------------------------------
SCHEDULE_SOURCE_PATH = (
    "data/raw/source_snapshots/v1/schedules_2018_2025_frozen-baseline-v1.parquet"
)
KICKOFF_TZ = "America/New_York"
CLUSTER_MAX_SPAN_MINUTES = 30
ANCHOR_LEAD_MINUTES = 60

# Reproduced acceptance counts (verified against the frozen schedule).
EXPECTED_GAMES_BY_SEASON = {2020: 269, 2021: 285, 2022: 284, 2023: 285, 2024: 285}
EXPECTED_TOTAL_GAMES = 1408
EXPECTED_TOTAL_CLUSTERS = 575
EXPECTED_CLUSTERS_BY_SEASON = {2020: 107, 2021: 111, 2022: 116, 2023: 120, 2024: 121}

# --- Bookmaker set (frozen, exact) ------------------------------------------
BOOKS_ACTIONABLE: tuple[str, ...] = ("draftkings", "fanduel")
BOOKS_BENCHMARK: tuple[str, ...] = ("pinnacle",)
BOOKS_SECONDARY: tuple[str, ...] = ("betonlineag",)
BOOKS_OTHER: tuple[str, ...] = ("williamhill_us", "betmgm", "betrivers", "bovada", "lowvig", "betus")
ALLOWED_BOOKS: tuple[str, ...] = (
    BOOKS_ACTIONABLE + BOOKS_BENCHMARK + BOOKS_SECONDARY + BOOKS_OTHER
)

BOOK_ROLES: dict[str, str] = {
    "draftkings": "ACTIONABLE_RETAIL",
    "fanduel": "ACTIONABLE_RETAIL",
    "pinnacle": "PRIMARY_SHARP_BENCHMARK",
    "betonlineag": "SECONDARY_INDEPENDENT_REFERENCE",
    "williamhill_us": "OTHER_CONSENSUS_INPUT",
    "betmgm": "OTHER_CONSENSUS_INPUT",
    "betrivers": "OTHER_CONSENSUS_INPUT",
    "bovada": "OTHER_CONSENSUS_INPUT",
    "lowvig": "OTHER_CONSENSUS_INPUT",
    "betus": "OTHER_CONSENSUS_INPUT",
}

# --- Markets (frozen, exact) ------------------------------------------------
MARKETS: tuple[str, ...] = ("h2h", "spreads", "totals")

# --- Credit contract --------------------------------------------------------
EXPECTED_COST_PER_SUCCESSFUL_REQUEST = 30
INITIAL_PLANNED_MAX_SUCCESSFUL_REQUESTS = 575
INITIAL_PLANNED_CREDIT_CAP = 17250
NO_AUTOMATIC_RETRIES = True
RESPONSE_COST_HEADER = "x-requests-last"

# --- Secret handling --------------------------------------------------------
ODDS_API_KEY_ENV = "ODDS_API_KEY"

# --- Raw / ledger layout ----------------------------------------------------
RAW_ROOT = "data/market_data/raw"
LEDGER_PATH = "data/market_data/ledger/historical_acquisition_ledger_v1.parquet"
LOCK_DIR = "data/market_data/lock"
LOCK_FILENAME = "acquisition.lock"

MANIFEST_REQUEST_PLAN_PATH = "data/manifests/historical_market_request_plan_v1.parquet"
MANIFEST_REQUEST_PLAN_JSON = "data/manifests/historical_market_request_plan_v1.json"

# Frozen SHA-256 of the deterministic request-plan artifact. Enforced in
# executable code before any live network call (see validate_plan_contract).
EXPECTED_PLAN_SHA256 = (
    "1591542e16cfeaa7eeef6d6e04a87db00c67ec8b988b1559c6645b9a06d20e4a"
)


def manifest_dict() -> dict[str, Any]:
    """Serialize the frozen manifest to a plain dict (JSON-able)."""
    return {
        "version": "historical-market-acquisition-manifest-v1",
        "provider": PROVIDER,
        "sport": SPORT,
        "coverage_seasons": list(ACQUISITION_SEASONS),
        "unresolved_seasons": list(UNRESOLVED_SEASONS),
        "future_preregistered_split": {
            "discovery": list(FUTURE_DISCOVERY_SEASONS),
            "confirmation": list(FUTURE_CONFIRMATION_SEASONS),
            "note": (
                "Recorded as a downstream consequence only; deferred until "
                "authoritative 2018-2019 coverage is resolved or ruled out. "
                "No outcomes are scored in this task."
            ),
        },
        "schedule_source": {
            "path": SCHEDULE_SOURCE_PATH,
            "kickoff_columns": ["gameday", "gametime"],
            "kickoff_timezone": KICKOFF_TZ,
        },
        "clustering": {
            "policy": "T-60_NATURAL_KICKOFF_CLUSTER_SNAPSHOT",
            "cluster_max_span_minutes": CLUSTER_MAX_SPAN_MINUTES,
            "anchor_lead_minutes": ANCHOR_LEAD_MINUTES,
            "expected_total_clusters": EXPECTED_TOTAL_CLUSTERS,
            "expected_clusters_by_season": dict(EXPECTED_CLUSTERS_BY_SEASON),
        },
        "books": {
            "actionable": list(BOOKS_ACTIONABLE),
            "benchmark": list(BOOKS_BENCHMARK),
            "secondary": list(BOOKS_SECONDARY),
            "other": list(BOOKS_OTHER),
            "allowed_books": list(ALLOWED_BOOKS),
            "roles": dict(BOOK_ROLES),
        },
        "markets": list(MARKETS),
        "credit_contract": {
            "expected_cost_per_successful_request": EXPECTED_COST_PER_SUCCESSFUL_REQUEST,
            "initial_planned_max_successful_requests": INITIAL_PLANNED_MAX_SUCCESSFUL_REQUESTS,
            "initial_planned_credit_cap": INITIAL_PLANNED_CREDIT_CAP,
            "no_automatic_retries": NO_AUTOMATIC_RETRIES,
            "response_cost_header": RESPONSE_COST_HEADER,
        },
        "architecture_firewall": (
            "Market data is DOWNSTREAM-ONLY. It must never be a feature or "
            "training input to any frozen football model (Oracle QB-Elo, "
            "XGBoost, Expected-Margin, Ridge Totals). No outcomes are "
            "inspected or scored in this task; 2025 stays sealed."
        ),
        "secret": {"environment_variable": ODDS_API_KEY_ENV},
        "request_plan": {
            "path": MANIFEST_REQUEST_PLAN_PATH,
            "expected_rows": EXPECTED_TOTAL_CLUSTERS,
            "expected_sha256": EXPECTED_PLAN_SHA256,
        },
        "raw": {
            "root": RAW_ROOT,
            "immutable": True,
            "ledger_path": LEDGER_PATH,
            "lock_dir": LOCK_DIR,
        },
    }


def _schema_representation(schema: "Any") -> list[dict[str, str]]:
    """Ordered list of ``{name, dtype}`` for every column.

    Column order is significant (a reordered schema is a different schema),
    so this list is *not* sorted and is serialized in-place.
    """
    return [{"name": str(name), "dtype": str(dtype)} for name, dtype in schema.items()]


def _schema_canonical_bytes(schema: "Any") -> bytes:
    """Deterministic compact-JSON serialization of the ordered schema.

    Contains only column names and dtypes — no paths, timestamps, row values,
    or environment info — so the fingerprint is stable across rebuilds.
    """
    cols = _schema_representation(schema)
    canonical = json.dumps(cols, separators=(",", ":"), ensure_ascii=True)
    return canonical.encode("utf-8")


def schema_sha256_of(path: str | Path) -> str:
    """SHA-256 over the deterministic serialization of a parquet schema."""
    import polars as pl

    schema = pl.read_parquet(path).schema
    return hashlib.sha256(_schema_canonical_bytes(schema)).hexdigest()


def build_schedule_source_metadata(
    path: str | Path = SCHEDULE_SOURCE_PATH,
) -> dict[str, Any]:
    """Compute the frozen schedule source metadata (file + schema hashes).

    Returns a dict ready to merge into the manifest's ``schedule_source``
    block, including the full-file SHA-256, a deterministic schema SHA-256,
    and the structured ordered-schema representation so the fingerprint can
    be reproduced.
    """
    import polars as pl

    file_sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    schema = pl.read_parquet(path).schema
    canonical = _schema_canonical_bytes(schema).decode("utf-8")
    schema_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "path": str(path),
        "kickoff_columns": ["gameday", "gametime"],
        "kickoff_timezone": KICKOFF_TZ,
        "source_file_sha256": file_sha,
        "source_schema_sha256": schema_sha,
        "source_schema_canonical": canonical,
        "source_schema": _schema_representation(schema),
    }


def write_manifest(
    path: str | Path,
    *,
    schedule_source_meta: dict[str, Any] | None = None,
) -> None:
    payload = manifest_dict()
    if schedule_source_meta:
        schedule_source = dict(payload["schedule_source"])
        schedule_source.update(schedule_source_meta)
        payload["schedule_source"] = schedule_source
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
