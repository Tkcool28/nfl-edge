"""Outcome-blind 2025 market canonicalization adapter.

Thin holdout-only evidence/path layer around the already-frozen Task05E
normalization and canonicalization implementation. No scores/results/outcomes,
no Odds API calls, and no market-methodology changes occur here.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import polars as pl

from nfl_edge.holdout.market_2025 import (
    HOLDOUT_LEDGER_PATH,
    HOLDOUT_PLAN_MANIFEST_RELATIVE_PATH,
    HOLDOUT_PLAN_RELATIVE_PATH,
    HOLDOUT_PRODUCT_BOOKS,
    HOLDOUT_RAW_BOOKS,
    HOLDOUT_RAW_ROOT,
    HOLDOUT_SEASON,
    validate_holdout_plan_contract,
)
from nfl_edge.market_data.canonical import build_canonical
from nfl_edge.market_data.manifest import MARKETS, SCHEDULE_SOURCE_PATH
from nfl_edge.market_data.normalize import build_normalized

EXPECTED_ACQUISITION_RUN_ID = 33254688086
EXPECTED_ACQUISITION_ARTIFACT_ID = 9715458059
EXPECTED_ACQUISITION_ARTIFACT_DIGEST = (
    "sha256:081be41b05d246e50edf933b27b1ca75c63684d79520fdf73431c9c60009e7af"
)
EXPECTED_ACQUISITION_ZIP_SHA256 = (
    "081be41b05d246e50edf933b27b1ca75c63684d79520fdf73431c9c60009e7af"
)
EXPECTED_PLAN_SHA256 = (
    "d1b1eace49177bf01a22db9c2d9d991d07fe8144d165a9a8a67ba1f29f481425"
)
EXPECTED_SCHEDULE_SLICE_SHA256 = (
    "de36585a681bc79824b8427168ec4a74103fead35e2efc980590077d3eb20228"
)
EXPECTED_LEDGER_SHA256 = (
    "f53e08bb6b84217d8ddd2e1c18f26b1ae9dfe9c7c66bcd977951eda1c0185bab"
)
EXPECTED_RAW_INVENTORY_SHA256 = (
    "86edf9e2b980ed5ba1cfcead33251b34fdd158123785084514aa4ee9919ea81d"
)
EXPECTED_REQUEST_ROWS = 123
EXPECTED_TARGET_GAMES = 285
EXPECTED_CREDITS_SPENT = 3690
EXPECTED_CREDIT_PER_REQUEST = 30

DRY_RUN_RELATIVE_PATH = Path(
    "artifacts/task05g_2025_holdout_v1/market/market_plan_dry_run_2025_v1.json"
)
SCHEDULE_COLUMNS_READ = (
    "game_id",
    "season",
    "gameday",
    "gametime",
    "away_team",
    "home_team",
)


class HoldoutMarketCanonicalizationError(RuntimeError):
    """Raised when acquired evidence cannot be materialized safely."""


def sha256_of(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HoldoutMarketCanonicalizationError(f"invalid JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise HoldoutMarketCanonicalizationError(f"JSON evidence is not an object: {path}")
    return value


def _require_columns(frame: pl.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise HoldoutMarketCanonicalizationError(f"{label} missing columns: {missing}")


def validate_acquisition_bundle(bundle_root: str | Path) -> dict[str, Any]:
    """Verify the exact frozen paid bundle before derivation; no network."""
    root = Path(bundle_root)
    raw_root = root / HOLDOUT_RAW_ROOT
    ledger_path = root / HOLDOUT_LEDGER_PATH
    plan_path = root / HOLDOUT_PLAN_RELATIVE_PATH
    plan_manifest_path = root / HOLDOUT_PLAN_MANIFEST_RELATIVE_PATH
    dry_run_path = root / DRY_RUN_RELATIVE_PATH

    required_paths = [raw_root, ledger_path, plan_path, plan_manifest_path, dry_run_path]
    missing = [str(p) for p in required_paths if not p.exists()]
    if missing:
        raise HoldoutMarketCanonicalizationError(
            "acquisition bundle missing required paths: " + ", ".join(missing)
        )

    plan_sha = sha256_of(plan_path)
    if plan_sha != EXPECTED_PLAN_SHA256:
        raise HoldoutMarketCanonicalizationError(
            f"plan sha256 {plan_sha} != frozen {EXPECTED_PLAN_SHA256}"
        )

    ledger_sha = sha256_of(ledger_path)
    if ledger_sha != EXPECTED_LEDGER_SHA256:
        raise HoldoutMarketCanonicalizationError(
            f"ledger sha256 {ledger_sha} != frozen {EXPECTED_LEDGER_SHA256}"
        )

    plan = pl.read_parquet(plan_path)
    validate_holdout_plan_contract(
        plan, plan_path=plan_path, expected_sha256=EXPECTED_PLAN_SHA256
    )
    if plan.height != EXPECTED_REQUEST_ROWS:
        raise HoldoutMarketCanonicalizationError(
            f"plan rows {plan.height} != {EXPECTED_REQUEST_ROWS}"
        )
    plan_games: list[str] = []
    for cell in plan.get_column("target_game_ids").to_list():
        plan_games.extend(g for g in str(cell).split(",") if g)
    if len(plan_games) != EXPECTED_TARGET_GAMES or len(set(plan_games)) != EXPECTED_TARGET_GAMES:
        raise HoldoutMarketCanonicalizationError(
            f"plan target-game identity is not exactly {EXPECTED_TARGET_GAMES} unique games"
        )

    manifest = _read_json(plan_manifest_path)
    manifest_expectations = {
        "season": HOLDOUT_SEASON,
        "plan_sha256": EXPECTED_PLAN_SHA256,
        "schedule_source_sha256": EXPECTED_SCHEDULE_SLICE_SHA256,
        "request_rows": EXPECTED_REQUEST_ROWS,
        "target_games": EXPECTED_TARGET_GAMES,
        "planned_credit_cap": EXPECTED_CREDITS_SPENT,
    }
    for key, expected in manifest_expectations.items():
        if manifest.get(key) != expected:
            raise HoldoutMarketCanonicalizationError(
                f"plan manifest {key}={manifest.get(key)!r} != frozen {expected!r}"
            )
    if tuple(manifest.get("books") or ()) != HOLDOUT_RAW_BOOKS:
        raise HoldoutMarketCanonicalizationError("plan manifest raw-book contract changed")
    if tuple(manifest.get("markets") or ()) != tuple(MARKETS):
        raise HoldoutMarketCanonicalizationError("plan manifest market contract changed")

    dry_run = _read_json(dry_run_path)
    if dry_run.get("plan_sha256") != EXPECTED_PLAN_SHA256:
        raise HoldoutMarketCanonicalizationError("dry-run plan identity changed")
    if dry_run.get("schedule_slice_sha256") != EXPECTED_SCHEDULE_SLICE_SHA256:
        raise HoldoutMarketCanonicalizationError("dry-run schedule-slice identity changed")
    if dry_run.get("score_or_outcome_columns_read") != []:
        raise HoldoutMarketCanonicalizationError("dry-run evidence reports outcome-column access")

    ledger = pl.read_parquet(ledger_path)
    ledger_required = {
        "request_plan_id", "season", "http_status", "x_requests_last",
        "x_requests_used", "x_requests_remaining", "response_content_sha256",
        "raw_payload_path", "success", "attempt_category", "validation_status",
        "failure_reason", "error_class", "error_message",
    }
    _require_columns(ledger, ledger_required, "ledger")
    if ledger.height != EXPECTED_REQUEST_ROWS:
        raise HoldoutMarketCanonicalizationError(
            f"ledger rows {ledger.height} != {EXPECTED_REQUEST_ROWS}"
        )
    if set(ledger.get_column("request_plan_id").to_list()) != set(
        plan.get_column("request_plan_id").to_list()
    ):
        raise HoldoutMarketCanonicalizationError("ledger request ids != frozen plan request ids")
    if ledger.get_column("request_plan_id").n_unique() != EXPECTED_REQUEST_ROWS:
        raise HoldoutMarketCanonicalizationError("ledger contains duplicate request ids")
    if set(ledger.get_column("season").unique().to_list()) != {HOLDOUT_SEASON}:
        raise HoldoutMarketCanonicalizationError("ledger season differs from 2025")
    if set(ledger.get_column("http_status").unique().to_list()) != {200}:
        raise HoldoutMarketCanonicalizationError("ledger contains non-200 HTTP status")
    if set(ledger.get_column("x_requests_last").unique().to_list()) != {EXPECTED_CREDIT_PER_REQUEST}:
        raise HoldoutMarketCanonicalizationError("provider per-request credit cost changed")
    if ledger.get_column("success").null_count() or not bool(ledger.get_column("success").all()):
        raise HoldoutMarketCanonicalizationError("ledger contains unsuccessful acquisition row")
    if set(ledger.get_column("attempt_category").unique().to_list()) != {"VERIFIED_SUCCESS"}:
        raise HoldoutMarketCanonicalizationError("ledger contains non-VERIFIED_SUCCESS row")
    if set(ledger.get_column("validation_status").unique().to_list()) != {"PASS"}:
        raise HoldoutMarketCanonicalizationError("ledger contains non-PASS validation row")
    if any(
        ledger.get_column(c).null_count() != EXPECTED_REQUEST_ROWS
        for c in ("failure_reason", "error_class", "error_message")
    ):
        raise HoldoutMarketCanonicalizationError("ledger contains failure/error text")
    credits_used_max = int(ledger.get_column("x_requests_used").max())
    if credits_used_max != EXPECTED_CREDITS_SPENT:
        raise HoldoutMarketCanonicalizationError(
            f"provider used-credit terminal value {credits_used_max} != {EXPECTED_CREDITS_SPENT}"
        )

    raw_files = sorted((raw_root / str(HOLDOUT_SEASON)).glob("md_2025_*.json"))
    if len(raw_files) != EXPECTED_REQUEST_ROWS:
        raise HoldoutMarketCanonicalizationError(
            f"raw files {len(raw_files)} != {EXPECTED_REQUEST_ROWS}"
        )
    raw_ids = {p.stem for p in raw_files}
    if raw_ids != set(plan.get_column("request_plan_id").to_list()):
        raise HoldoutMarketCanonicalizationError("raw request ids != frozen plan request ids")

    ledger_hashes = {
        str(r["request_plan_id"]): str(r["response_content_sha256"])
        for r in ledger.select("request_plan_id", "response_content_sha256").to_dicts()
    }
    raw_hashes: dict[str, str] = {}
    raw_bytes = 0
    returned_books: set[str] = set()
    returned_markets: set[str] = set()
    for path in raw_files:
        raw_bytes += path.stat().st_size
        digest = sha256_of(path)
        raw_hashes[path.stem] = digest
        if digest != ledger_hashes.get(path.stem):
            raise HoldoutMarketCanonicalizationError(
                f"raw/ledger hash mismatch for {path.stem}"
            )
        payload = _read_json(path)
        for event in payload.get("data") or []:
            for book in event.get("bookmakers") or []:
                returned_books.add(str(book.get("key")))
                for market in book.get("markets") or []:
                    returned_markets.add(str(market.get("key")))

    unexpected_books = sorted(returned_books - set(HOLDOUT_RAW_BOOKS))
    unexpected_markets = sorted(returned_markets - set(MARKETS))
    if unexpected_books:
        raise HoldoutMarketCanonicalizationError(
            f"provider returned unrequested books: {unexpected_books}"
        )
    if unexpected_markets:
        raise HoldoutMarketCanonicalizationError(
            f"provider returned unrequested markets: {unexpected_markets}"
        )
    if returned_markets != set(MARKETS):
        raise HoldoutMarketCanonicalizationError(
            f"returned market universe {sorted(returned_markets)} != frozen {list(MARKETS)}"
        )

    inventory_lines = [
        f"{p.name}\t{p.stat().st_size}\t{raw_hashes[p.stem]}" for p in raw_files
    ]
    inventory_text = "\n".join(inventory_lines) + "\n"
    raw_inventory_sha = hashlib.sha256(inventory_text.encode("utf-8")).hexdigest()
    if raw_inventory_sha != EXPECTED_RAW_INVENTORY_SHA256:
        raise HoldoutMarketCanonicalizationError(
            f"raw inventory sha256 {raw_inventory_sha} != frozen {EXPECTED_RAW_INVENTORY_SHA256}"
        )

    return {
        "schema_version": "task05g_2025_acquisition_bundle_validation_v1",
        "status": "ACQUISITION_BUNDLE_VERIFIED",
        "season": HOLDOUT_SEASON,
        "request_rows": EXPECTED_REQUEST_ROWS,
        "target_games": EXPECTED_TARGET_GAMES,
        "plan_sha256": plan_sha,
        "schedule_slice_sha256": EXPECTED_SCHEDULE_SLICE_SHA256,
        "ledger_sha256": ledger_sha,
        "raw_file_count": len(raw_files),
        "raw_total_bytes": raw_bytes,
        "raw_inventory_sha256": raw_inventory_sha,
        "unique_raw_sha256": len(set(raw_hashes.values())),
        "credits_spent": credits_used_max,
        "credits_per_request": EXPECTED_CREDIT_PER_REQUEST,
        "provider_remaining_after_final_request": int(
            ledger.get_column("x_requests_remaining").min()
        ),
        "returned_books": sorted(returned_books),
        "returned_markets": sorted(returned_markets),
        "score_or_outcome_columns_read": [],
    }


def _validate_schedule_identity(schedule: pl.DataFrame) -> None:
    """Fail closed if the consumed outcome-blind schedule identity drifts."""
    _require_columns(schedule, set(SCHEDULE_COLUMNS_READ), "2025 schedule")
    if schedule.get_column("game_id").n_unique() != schedule.height:
        raise HoldoutMarketCanonicalizationError("2025 schedule contains duplicate game_id")
    if set(schedule.get_column("season").unique().to_list()) != {HOLDOUT_SEASON}:
        raise HoldoutMarketCanonicalizationError("schedule contains non-2025 rows")
    for row in schedule.select("game_id", "season", "away_team", "home_team").to_dicts():
        game_id = str(row["game_id"])
        parts = game_id.split("_")
        if len(parts) != 4:
            raise HoldoutMarketCanonicalizationError(f"unparseable game_id {game_id!r}")
        if parts[0] != str(HOLDOUT_SEASON) or int(row["season"]) != HOLDOUT_SEASON:
            raise HoldoutMarketCanonicalizationError(f"game_id season mismatch {game_id!r}")
        if str(row["away_team"]) != parts[2] or str(row["home_team"]) != parts[3]:
            raise HoldoutMarketCanonicalizationError(
                f"schedule team identity mismatch for {game_id}: "
                f"away={row['away_team']!r}, home={row['home_team']!r}"
            )


def _book_coverage(bm: pl.DataFrame, book: str) -> dict[str, Any]:
    scoped = bm.filter(pl.col("bookmaker_key") == book)
    result: dict[str, Any] = {"bookmaker": book}
    for market in MARKETS:
        result[f"{market}_games"] = scoped.filter(
            pl.col("market_key") == market
        ).get_column("game_id").n_unique()
    complete = 0
    for game_id in scoped.get_column("game_id").unique().to_list():
        keys = set(
            scoped.filter(pl.col("game_id") == game_id)
            .get_column("market_key").unique().to_list()
        )
        if set(MARKETS) <= keys:
            complete += 1
    result["complete_games"] = complete
    return result


def canonicalize_acquisition_bundle(
    bundle_root: str | Path,
    *,
    schedule_path: str | Path,
    output_root: str | Path,
) -> dict[str, Any]:
    """Validate evidence, derive 2025 market layers, and report structure."""
    bundle = validate_acquisition_bundle(bundle_root)
    root = Path(bundle_root)
    raw_root = root / HOLDOUT_RAW_ROOT
    ledger_path = root / HOLDOUT_LEDGER_PATH
    plan_path = root / HOLDOUT_PLAN_RELATIVE_PATH

    schedule = pl.read_parquet(
        schedule_path,
        columns=list(SCHEDULE_COLUMNS_READ),
    ).filter(pl.col("season") == HOLDOUT_SEASON)
    _validate_schedule_identity(schedule)

    normalized = build_normalized(raw_root, ledger_path, plan_path)
    plan = pl.read_parquet(plan_path)
    games, bm = build_canonical(normalized, plan, schedule)

    if games.height != EXPECTED_TARGET_GAMES:
        raise HoldoutMarketCanonicalizationError(
            f"canonical games {games.height} != {EXPECTED_TARGET_GAMES}"
        )
    if games.get_column("game_id").n_unique() != EXPECTED_TARGET_GAMES:
        raise HoldoutMarketCanonicalizationError("canonical game ids are not unique")
    if set(games.get_column("season").unique().to_list()) != {HOLDOUT_SEASON}:
        raise HoldoutMarketCanonicalizationError("canonical output contains non-2025 season")

    match_counts = Counter(str(v) for v in games.get_column("match_status").to_list())
    if match_counts != Counter({"MATCHED_EXACT": EXPECTED_TARGET_GAMES}):
        raise HoldoutMarketCanonicalizationError(
            f"canonical match statuses are not all MATCHED_EXACT: {dict(match_counts)}"
        )

    lead_values = [float(v) for v in games.get_column("lead_minutes").drop_nulls().to_list()]
    if len(lead_values) != EXPECTED_TARGET_GAMES or min(lead_values) <= 0.0:
        raise HoldoutMarketCanonicalizationError("canonical snapshot is missing or not pregame")

    returned_books = sorted(set(bm.get_column("bookmaker_key").unique().to_list()))
    returned_markets = sorted(set(bm.get_column("market_key").unique().to_list()))
    if set(returned_books) - set(HOLDOUT_RAW_BOOKS):
        raise HoldoutMarketCanonicalizationError("canonical output contains unrequested book")
    if set(returned_markets) != set(MARKETS):
        raise HoldoutMarketCanonicalizationError("canonical output market universe changed")

    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    normalized_path = output / "normalized_book_market_2025.parquet"
    games_path = output / "canonical_games_2025.parquet"
    bm_path = output / "canonical_book_market_2025.parquet"
    normalized.write_parquet(normalized_path, compression="zstd")
    games.write_parquet(games_path, compression="zstd")
    bm.write_parquet(bm_path, compression="zstd")

    flag_counts: Counter[str] = Counter()
    for value in games.get_column("quality_flags").drop_nulls().to_list():
        for flag in str(value).split(","):
            if flag:
                flag_counts[flag] += 1

    product_coverage = {
        book: _book_coverage(bm, book) for book in HOLDOUT_PRODUCT_BOOKS
    }
    complete_intersection = 0
    for game_id in games.get_column("game_id").to_list():
        game_books = set(
            bm.filter(pl.col("game_id") == game_id)
            .get_column("bookmaker_key").unique().to_list()
        )
        if set(HOLDOUT_PRODUCT_BOOKS) <= game_books:
            complete_intersection += 1

    report = {
        "schema_version": "task05g_2025_market_canonicalization_v1",
        "status": "2025_MARKET_CANONICALIZATION_STRUCTURALLY_VALID",
        "season": HOLDOUT_SEASON,
        "acquisition_bundle": bundle,
        "schedule_columns_read": list(SCHEDULE_COLUMNS_READ),
        "schedule_identity_validated_from_game_id": True,
        "score_or_outcome_columns_read": [],
        "normalized_rows": normalized.height,
        "normalized_target_rows": normalized.filter(
            pl.col("is_target_event") == True  # noqa: E712
        ).height,
        "canonical_games": games.height,
        "canonical_book_market_rows": bm.height,
        "match_status_counts": dict(sorted(match_counts.items())),
        "lead_minutes": {"min": min(lead_values), "max": max(lead_values)},
        "returned_books": returned_books,
        "returned_markets": returned_markets,
        "product_book_coverage": product_coverage,
        "product_book_game_intersection": complete_intersection,
        "malformed_market_rows": int(
            bm.filter(pl.col("malformed_market") == True).height  # noqa: E712
        ),
        "quality_flag_game_counts": dict(sorted(flag_counts.items())),
        "outputs": {
            "normalized": str(normalized_path),
            "normalized_sha256": sha256_of(normalized_path),
            "canonical_games": str(games_path),
            "canonical_games_sha256": sha256_of(games_path),
            "canonical_book_market": str(bm_path),
            "canonical_book_market_sha256": sha256_of(bm_path),
        },
        "interpretation": {
            "missing_book_market_rows_are_preserved_not_fabricated": True,
            "coverage_is_reported_not_retuned": True,
            "outcomes_opened": False,
        },
    }
    report_path = output / "structural_validation_2025_v1.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
    report["outputs"]["structural_report"] = str(report_path)
    report["outputs"]["structural_report_sha256"] = sha256_of(report_path)
    return report


def default_schedule_path(repo_root: str | Path) -> Path:
    return Path(repo_root) / SCHEDULE_SOURCE_PATH
