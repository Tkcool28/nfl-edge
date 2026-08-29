"""Authorization-only 2025 historical-market plan and acquisition adapter.

This module does not read the sealed schedule and does not read credentials on
import. It is a pure plan/validation layer until an already-authorized caller
passes a schedule frame and, separately, an API key.

The adapter intentionally does not change the frozen 2020-2024 acquisition
contract. It reuses the same T-60 clock derivation, plan schema, paid-response
preservation, ledger/no-retry behavior, and exclusive acquisition lock while
applying the separately frozen 2025-only raw-book contract.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import polars as pl

from nfl_edge.market_data.kickoffs import Cluster, gameday_gametime_to_utc
from nfl_edge.market_data.locking import acquisition_lock
from nfl_edge.market_data.manifest import (
    ANCHOR_LEAD_MINUTES,
    CLUSTER_MAX_SPAN_MINUTES,
    EXPECTED_COST_PER_SUCCESSFUL_REQUEST,
    INITIAL_PLANNED_CREDIT_CAP,
    MARKETS,
)
from nfl_edge.market_data.plan import PLAN_SCHEMA, plan_frame
from nfl_edge.market_data.runner import run_plan

HOLDOUT_SEASON = 2025
HOLDOUT_RAW_BOOKS: tuple[str, ...] = (
    "draftkings",
    "fanduel",
    "pinnacle",
    "betmgm",
    "williamhill_us",
    "caesars",
    "betrivers",
    "pointsbetus",
    "wynnbet",
    "unibet_us",
)
HOLDOUT_PRODUCT_BOOKS: tuple[str, ...] = ("draftkings", "fanduel", "pinnacle")
HOLDOUT_RAW_ROOT = Path("data/market_data/holdout_2025/raw")
HOLDOUT_LEDGER_PATH = Path(
    "data/market_data/holdout_2025/ledger/historical_acquisition_ledger_v1.parquet"
)
HOLDOUT_LOCK_DIR = Path("data/market_data/holdout_2025/lock")
HOLDOUT_PLAN_RELATIVE_PATH = Path(
    "artifacts/task05g_2025_holdout_v1/market/historical_market_request_plan_2025_v1.parquet"
)
HOLDOUT_PLAN_MANIFEST_RELATIVE_PATH = Path(
    "artifacts/task05g_2025_holdout_v1/market/historical_market_request_plan_2025_v1.json"
)


class HoldoutMarketContractError(RuntimeError):
    """Raised before network when a 2025 market-plan invariant is violated."""


def _fmt_utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise HoldoutMarketContractError(f"invalid UTC timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HoldoutMarketContractError(f"naive timestamp prohibited: {value!r}")
    return parsed.astimezone(timezone.utc)


def _make_cluster(
    season: int,
    seq: int,
    group: list[tuple[str, int, str, datetime]],
) -> Cluster:
    """Construct one cluster using the frozen market-data naming/lead rules."""
    earliest = min(r[3] for r in group)
    anchor = earliest - timedelta(minutes=ANCHOR_LEAD_MINUTES)
    game_ids = tuple(sorted(r[0] for r in group))
    leads = tuple(
        round((r[3] - anchor).total_seconds() / 60.0, 4) for r in group
    )
    width = round(
        (max(r[3] for r in group) - earliest).total_seconds() / 60.0,
        4,
    )
    idx = seq + 1
    return Cluster(
        cluster_id=f"{season}_{idx:03d}",
        request_plan_id=f"md_{season}_{idx:03d}",
        season=season,
        gameday=group[0][2],
        earliest_kickoff_utc=earliest,
        anchor_utc=anchor,
        game_ids=game_ids,
        lead_minutes=leads,
        width_minutes=width,
        game_count=len(game_ids),
    )


def build_clusters_for_seasons(
    frame: pl.DataFrame,
    *,
    seasons: Iterable[int],
) -> list[Cluster]:
    """Apply the frozen natural-kickoff clustering to an explicit season set.

    The function is deliberately I/O-free. Tests can therefore prove its
    behavior against exposed 2020-2024 data without opening the real holdout.
    The authorized executor is responsible for supplying a real 2025 frame
    only after the Master authorization gate has passed.
    """
    required = {"game_id", "season", "gameday", "gametime"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise HoldoutMarketContractError(
            f"schedule frame missing required kickoff columns: {missing}"
        )

    season_tuple = tuple(sorted({int(s) for s in seasons}))
    if not season_tuple:
        raise HoldoutMarketContractError("at least one target season is required")

    scoped = frame.filter(pl.col("season").is_in(list(season_tuple))).select(
        "game_id", "season", "gameday", "gametime"
    )
    if scoped.height == 0:
        raise HoldoutMarketContractError(
            f"no schedule rows for requested seasons {list(season_tuple)}"
        )
    actual_seasons = sorted({int(s) for s in scoped["season"].unique().to_list()})
    if actual_seasons != list(season_tuple):
        raise HoldoutMarketContractError(
            f"schedule seasons present {actual_seasons} != requested {list(season_tuple)}"
        )
    if scoped["game_id"].null_count() or scoped["gameday"].null_count() or scoped["gametime"].null_count():
        raise HoldoutMarketContractError("kickoff identity/time fields cannot be null")
    if scoped["game_id"].n_unique() != scoped.height:
        raise HoldoutMarketContractError("duplicate game_id in kickoff frame")

    rows: list[tuple[str, int, str, datetime]] = []
    for rec in scoped.iter_rows(named=True):
        kick = gameday_gametime_to_utc(str(rec["gameday"]), str(rec["gametime"]))
        rows.append((str(rec["game_id"]), int(rec["season"]), str(rec["gameday"]), kick))
    rows.sort(key=lambda r: (r[1], r[2], r[3], r[0]))

    per_season_day: dict[tuple[int, str], list[tuple[str, int, str, datetime]]] = {}
    for row in rows:
        per_season_day.setdefault((row[1], row[2]), []).append(row)

    clusters: list[Cluster] = []
    for season in season_tuple:
        seq = 0
        days = sorted(day for s, day in per_season_day if s == season)
        for gameday in days:
            day_rows = per_season_day[(season, gameday)]
            group: list[tuple[str, int, str, datetime]] = []
            for row in day_rows:
                if not group:
                    group = [row]
                    continue
                span = (row[3] - group[0][3]).total_seconds() / 60.0
                if span <= CLUSTER_MAX_SPAN_MINUTES:
                    group.append(row)
                else:
                    clusters.append(_make_cluster(season, seq, group))
                    seq += 1
                    group = [row]
            if group:
                clusters.append(_make_cluster(season, seq, group))
                seq += 1
    return clusters


def build_holdout_market_plan(schedule_2025: pl.DataFrame) -> pl.DataFrame:
    """Build the deterministic 2025 T-60 plan from an authorized schedule frame."""
    clusters = build_clusters_for_seasons(schedule_2025, seasons=(HOLDOUT_SEASON,))
    plan = plan_frame(clusters).with_columns(
        pl.lit(",".join(HOLDOUT_RAW_BOOKS)).alias("requested_bookmaker_keys")
    )
    validate_holdout_plan_contract(plan)
    return plan


def _plan_games(plan: pl.DataFrame) -> list[str]:
    games: list[str] = []
    for cell in plan.get_column("target_game_ids").to_list():
        games.extend(g for g in str(cell).split(",") if g)
    return games


def validate_holdout_plan_contract(
    plan: pl.DataFrame,
    *,
    plan_path: str | Path | None = None,
    expected_sha256: str | None = None,
) -> None:
    """Fail closed on any 2025 request-plan violation before network access."""
    errors: list[str] = []
    if plan.height <= 0:
        errors.append("plan is empty")

    if plan.columns != list(PLAN_SCHEMA):
        errors.append("plan columns/order differ from frozen PLAN_SCHEMA")
    else:
        for name, dtype in PLAN_SCHEMA.items():
            if plan.schema[name] != dtype:
                errors.append(
                    f"plan dtype {name}={plan.schema[name]} != frozen {dtype}"
                )

    if "season" in plan.columns:
        seasons = sorted({int(s) for s in plan["season"].unique().to_list()})
        if seasons != [HOLDOUT_SEASON]:
            errors.append(f"seasons {seasons} != [{HOLDOUT_SEASON}]")

    if "request_plan_id" in plan.columns and plan["request_plan_id"].n_unique() != plan.height:
        errors.append("duplicate request_plan_id")
    if "cluster_id" in plan.columns and plan["cluster_id"].n_unique() != plan.height:
        errors.append("duplicate cluster_id")

    if {"request_plan_id", "cluster_id"}.issubset(plan.columns):
        for row in plan.select("request_plan_id", "cluster_id").iter_rows(named=True):
            if not str(row["request_plan_id"]).startswith("md_2025_"):
                errors.append("non-2025 request_plan_id")
                break
            if not str(row["cluster_id"]).startswith("2025_"):
                errors.append("non-2025 cluster_id")
                break

    if "target_game_ids" in plan.columns:
        games = _plan_games(plan)
        if len(games) != len(set(games)):
            errors.append("duplicate game assignment across clusters")
        if "game_count" in plan.columns:
            declared = int(plan["game_count"].sum())
            if declared != len(games):
                errors.append(
                    f"declared game_count sum {declared} != assigned games {len(games)}"
                )
            for row in plan.select("game_count", "target_game_ids").iter_rows(named=True):
                actual = len([g for g in str(row["target_game_ids"]).split(",") if g])
                if actual != int(row["game_count"]):
                    errors.append("cluster game_count does not match target_game_ids")
                    break

    if "requested_bookmaker_keys" in plan.columns:
        books = plan["requested_bookmaker_keys"].unique().to_list()
        if books != [",".join(HOLDOUT_RAW_BOOKS)]:
            errors.append("bookmaker allowlist differs from frozen 2025 10-book acquisition set")
    if "requested_markets" in plan.columns:
        markets = plan["requested_markets"].unique().to_list()
        if markets != [",".join(MARKETS)]:
            errors.append("markets differ from frozen h2h,spreads,totals set")

    if "expected_credits" in plan.columns:
        costs = plan["expected_credits"].unique().to_list()
        if costs != [EXPECTED_COST_PER_SUCCESSFUL_REQUEST]:
            errors.append("per-request credit contract changed")
        total = int(plan["expected_credits"].sum())
        if total != plan.height * EXPECTED_COST_PER_SUCCESSFUL_REQUEST:
            errors.append("projected credit total is inconsistent")
        if total > INITIAL_PLANNED_CREDIT_CAP:
            errors.append(
                f"2025 projected credits {total} exceed global frozen safety cap "
                f"{INITIAL_PLANNED_CREDIT_CAP}"
            )

    if "cluster_width_minutes" in plan.columns and plan.height:
        width_min = float(plan["cluster_width_minutes"].min())
        width_max = float(plan["cluster_width_minutes"].max())
        if width_min < 0.0 or width_max > CLUSTER_MAX_SPAN_MINUTES:
            errors.append(
                f"cluster width range [{width_min}, {width_max}] violates 0..{CLUSTER_MAX_SPAN_MINUTES}"
            )
    if {"expected_lead_min", "expected_lead_max"}.issubset(plan.columns) and plan.height:
        lead_min = float(plan["expected_lead_min"].min())
        lead_max = float(plan["expected_lead_max"].max())
        expected_max = ANCHOR_LEAD_MINUTES + CLUSTER_MAX_SPAN_MINUTES
        if lead_min < ANCHOR_LEAD_MINUTES or lead_max > expected_max:
            errors.append(
                f"observation lead range [{lead_min}, {lead_max}] violates "
                f"[{ANCHOR_LEAD_MINUTES}, {expected_max}]"
            )

    time_cols = {"requested_target_timestamp_utc", "expected_earliest_kickoff_utc"}
    if time_cols.issubset(plan.columns):
        for row in plan.select(*sorted(time_cols)).iter_rows(named=True):
            target = _parse_utc(row["requested_target_timestamp_utc"])
            kickoff = _parse_utc(row["expected_earliest_kickoff_utc"])
            if target >= kickoff:
                errors.append("request target is not strictly pregame")
                break
            if abs((kickoff - target).total_seconds() / 60.0 - ANCHOR_LEAD_MINUTES) > 1e-9:
                errors.append("request target is not exactly T-60 from earliest kickoff")
                break

    if plan_path is not None:
        path = Path(plan_path)
        if expected_sha256 is None:
            errors.append("expected_sha256 required when validating a persisted plan")
        elif not path.exists():
            errors.append(f"persisted plan missing: {path}")
        else:
            actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual_sha != expected_sha256:
                errors.append(
                    f"persisted plan sha256 {actual_sha} != expected {expected_sha256}"
                )

    if errors:
        raise HoldoutMarketContractError(
            "2025 market plan contract violated; stopping before network: "
            + "; ".join(errors)
        )


def write_holdout_market_plan(
    plan: pl.DataFrame,
    *,
    plan_path: str | Path,
    manifest_path: str | Path,
    schedule_source_sha256: str,
) -> str:
    """Persist the post-authorization plan and immutable identity manifest."""
    validate_holdout_plan_contract(plan)
    plan_path = Path(plan_path)
    manifest_path = Path(manifest_path)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    plan.write_parquet(plan_path)
    digest = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    validate_holdout_plan_contract(
        plan, plan_path=plan_path, expected_sha256=digest
    )
    payload = {
        "schema_version": "historical_market_request_plan_2025_v1",
        "season": HOLDOUT_SEASON,
        "provider": "the_odds_api",
        "snapshot_policy": "T-60_NATURAL_KICKOFF_CLUSTER_SNAPSHOT",
        "cluster_max_span_minutes": CLUSTER_MAX_SPAN_MINUTES,
        "anchor_lead_minutes": ANCHOR_LEAD_MINUTES,
        "books": list(HOLDOUT_RAW_BOOKS),
        "markets": list(MARKETS),
        "request_rows": plan.height,
        "target_games": len(_plan_games(plan)),
        "credits_per_request": EXPECTED_COST_PER_SUCCESSFUL_REQUEST,
        "planned_credit_cap": plan.height * EXPECTED_COST_PER_SUCCESSFUL_REQUEST,
        "global_safety_cap": INITIAL_PLANNED_CREDIT_CAP,
        "schedule_source_sha256": schedule_source_sha256,
        "plan_path": str(plan_path),
        "plan_sha256": digest,
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return digest


def holdout_market_dry_run_report(plan: pl.DataFrame) -> dict[str, object]:
    """Return a zero-I/O, zero-credential summary of an already-built plan."""
    validate_holdout_plan_contract(plan)
    games = _plan_games(plan)
    return {
        "season": HOLDOUT_SEASON,
        "request_plan_rows": plan.height,
        "target_games": len(games),
        "books": list(HOLDOUT_RAW_BOOKS),
        "product_books": list(HOLDOUT_PRODUCT_BOOKS),
        "markets": list(MARKETS),
        "snapshot_policy": "T-60_NATURAL_KICKOFF_CLUSTER_SNAPSHOT",
        "expected_observation_lead_minutes": {
            "min": float(plan["expected_lead_min"].min()),
            "max": float(plan["expected_lead_max"].max()),
        },
        "planned_credit_cap": plan.height * EXPECTED_COST_PER_SUCCESSFUL_REQUEST,
        "network_calls": 0,
        "credential_reads": 0,
    }


def run_holdout_market_acquisition(
    plan: pl.DataFrame,
    *,
    plan_path: str | Path,
    plan_sha256: str,
    api_key: str,
    raw_root: str | Path = HOLDOUT_RAW_ROOT,
    ledger_path: str | Path = HOLDOUT_LEDGER_PATH,
    lock_dir: str | Path = HOLDOUT_LOCK_DIR,
    session: object | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, object]:
    """Execute a verified 2025 plan using the frozen safe acquisition core.

    The caller must already have passed the Master authorization gate. This
    function validates the persisted 2025 plan before acquiring the same
    fail-fast lock used by development acquisition, then delegates individual
    paid requests to the existing runner. The dynamic 2025 planned cap is
    always <= the pre-existing global 17,250-credit safety ceiling.
    """
    if not api_key:
        raise HoldoutMarketContractError("ODDS_API_KEY must be non-empty in execute mode")
    validate_holdout_plan_contract(
        plan, plan_path=plan_path, expected_sha256=plan_sha256
    )
    dynamic_cap = plan.height * EXPECTED_COST_PER_SUCCESSFUL_REQUEST
    if dynamic_cap > INITIAL_PLANNED_CREDIT_CAP:
        raise HoldoutMarketContractError(
            f"dynamic holdout cap {dynamic_cap} exceeds global safety cap "
            f"{INITIAL_PLANNED_CREDIT_CAP}"
        )
    with acquisition_lock(
        lock_dir, kind="holdout_2025_live_acquisition", lock_timeout_seconds=0.0
    ):
        result = run_plan(
            plan,
            execute=True,
            api_key=api_key,
            raw_root=raw_root,
            ledger_path=ledger_path,
            session=session,
            timeout_seconds=timeout_seconds,
        )
    result = dict(result)
    result["credit_cap"] = dynamic_cap
    result["global_safety_cap"] = INITIAL_PLANNED_CREDIT_CAP
    result["holdout_season"] = HOLDOUT_SEASON
    return result
