"""Immutable prospective publication capture from an already-published canonical product."""
from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from nfl_edge.contracts.live_product_v1 import validate_product_snapshot
from nfl_edge.prospective.common_v1 import (
    BUILDER_VERSION,
    LANE_ORDER,
    PUBLICATION_SCHEMA_VERSION,
    AppendOnlyViolation,
    ProspectiveCardError,
    canonical_json_bytes,
    exact_offer_identity,
    exact_offer_tuple,
    logical_identity,
    parse_utc,
    source_product_sha256,
    wager_identity,
)

_SAFE_STAMP = re.compile(r"[^0-9A-Za-z_.-]+")
_CAPTURE_MODES = {
    "NATIVE_PROSPECTIVE",
    "RECONSTRUCTED_FROM_ARCHIVED_PRODUCTION_ARTIFACT",
    "REPO_SIMULATION",
}


def _game_index(product: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for game in product["games"]:
        game_id = str(game["game_id"])
        if game_id in out:
            raise ProspectiveCardError(f"duplicate canonical game_id {game_id}")
        out[game_id] = game
    return out


def _canonical_side(headline: Mapping[str, Any], game: Mapping[str, Any] | None) -> str | None:
    if any(headline.get(field) is None for field in ("game_id", "market", "selection")):
        return None
    if game is None:
        raise ProspectiveCardError(f"headline references unknown game {headline.get('game_id')!r}")
    market = str(headline["market"]).upper()
    selection = str(headline["selection"])
    if market in {"MONEYLINE", "SPREAD"}:
        if selection == str(game["home_team"]):
            return "home"
        if selection == str(game["away_team"]):
            return "away"
        raise ProspectiveCardError(
            f"canonical {market} selection {selection!r} does not match either game team"
        )
    if market == "TOTAL" and selection.lower() in {"over", "under"}:
        return selection.lower()
    raise ProspectiveCardError(f"unsupported canonical headline market/selection: {market} {selection!r}")


def _roof_state(game: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if game is None:
        return None
    xgb = dict((game.get("football_outputs") or {}).get("xgboost_v2") or {})
    if not xgb:
        return None
    fields = (
        "status",
        "support",
        "roof_resolution_status",
        "roof_selected_scenario",
        "xgboost_open_probability",
        "xgboost_closed_probability",
        "xgboost_scenario_delta",
        "roof_scenario_downstream",
    )
    return {key: deepcopy(xgb[key]) for key in fields if key in xgb}


def _lane_record(
    lane_key: str,
    headline: Mapping[str, Any],
    game: Mapping[str, Any] | None,
    selector_version: str | None,
) -> dict[str, Any]:
    normalized_selection = None if headline.get("selection") is None else str(headline["selection"])
    row: dict[str, Any] = {
        "lane_key": lane_key,
        "lane": str(headline["lane"]),
        "state": str(headline["state"]),
        "game_id": None if headline.get("game_id") is None else str(headline["game_id"]),
        "away_team": None if game is None else str(game["away_team"]),
        "home_team": None if game is None else str(game["home_team"]),
        "kickoff_at_utc": None if game is None else str(game["kickoff_at_utc"]),
        "market": None if headline.get("market") is None else str(headline["market"]),
        "selection": normalized_selection,
        "normalized_selection": normalized_selection,
        "normalized_side": _canonical_side(headline, game),
        "book": None if headline.get("book") is None else str(headline["book"]),
        "line": headline.get("line"),
        "american_odds": headline.get("american_odds"),
        "recommended_units": float(headline.get("recommended_units") or 0.0),
        "play_through": deepcopy(headline.get("play_through")),
        "value_at": deepcopy(headline.get("value_at")),
        "model_probability": headline.get("model_probability"),
        "trust_probability": headline.get("trust_probability"),
        "market_probability": headline.get("market_probability"),
        "ev": headline.get("ev"),
        "support": headline.get("support"),
        "reliability": headline.get("reliability"),
        "warnings": deepcopy(headline.get("warnings") or []),
        "selector_version": selector_version,
        "roof_state": _roof_state(game),
        "canonical_headline": deepcopy(dict(headline)),
        "portfolio_duplicate_of_lane": None,
        "portfolio_stake_suppressed_reason": None,
    }
    row["logical_recommendation_id"] = logical_identity(lane_key, row)
    row["wager_identity_id"] = wager_identity(lane_key, row)
    row["exact_offer_identity_id"] = exact_offer_identity(row)
    return row


def build_publication_snapshot(
    product: Mapping[str, Any],
    *,
    published_at_utc: str,
    source_commit_sha: str | None = None,
    capture_mode: str = "NATIVE_PROSPECTIVE",
) -> dict[str, Any]:
    """Build evidence only from an already-published canonical NFL EDGE product."""
    if capture_mode not in _CAPTURE_MODES:
        raise ProspectiveCardError(f"unsupported capture_mode {capture_mode!r}")
    validated = validate_product_snapshot(deepcopy(dict(product)))
    if parse_utc(published_at_utc) < parse_utc(str(validated["generated_at_utc"])):
        raise ProspectiveCardError("publication timestamp cannot precede product generated_at_utc")

    source_sha = source_product_sha256(validated)
    games = _game_index(validated)
    selector_versions = dict(validated["selector_versions"])
    lanes: dict[str, dict[str, Any]] = {}
    for lane_key in LANE_ORDER:
        headline = dict(validated["headlines"][lane_key])
        game_id = headline.get("game_id")
        game = None if game_id is None else games.get(str(game_id))
        lanes[lane_key] = _lane_record(
            lane_key,
            headline,
            game,
            None if lane_key not in selector_versions else str(selector_versions[lane_key]),
        )

    primary_for_offer: dict[tuple[Any, ...], str] = {}
    for lane_key in LANE_ORDER:
        row = lanes[lane_key]
        if row["state"] != "BET":
            continue
        exact = exact_offer_tuple(row)
        if exact is None:
            continue
        primary = primary_for_offer.setdefault(exact, lane_key)
        if primary != lane_key:
            row["portfolio_duplicate_of_lane"] = primary
            row["portfolio_stake_suppressed_reason"] = "DUPLICATE_EXACT_OFFER"

    return {
        "schema_version": PUBLICATION_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "capture_mode": capture_mode,
        "publication_id": f"publication-{source_sha[:24]}",
        "season": int(validated["season"]),
        "week": int(validated["week"]),
        "product_generated_at_utc": str(validated["generated_at_utc"]),
        "published_at_utc": str(published_at_utc),
        "source_product_version": str(validated["product_version"]),
        "source_product_sha256": source_sha,
        "source_commit_sha": None if source_commit_sha is None else str(source_commit_sha),
        "product_freshness": deepcopy(validated["freshness"]),
        "product_stale": bool(validated["stale"]),
        "product_warnings": deepcopy(validated["warnings"]),
        "source_provenance": {
            "football_data_version": str(validated["football_data_version"]),
            "qb_snapshot_version": str(validated["qb_snapshot_version"]),
            "market_snapshot_version": str(validated["market_snapshot_version"]),
            "prediction_as_of_utc": str(validated["prediction_as_of_utc"]),
            "model_versions": deepcopy(validated["model_versions"]),
            "evaluator_versions": deepcopy(validated["evaluator_versions"]),
            "selector_versions": deepcopy(validated["selector_versions"]),
        },
        "field_availability": {
            "evaluator_probability": "NOT_EXPOSED_BY_CANONICAL_PRODUCT_V1",
            "backend_user_overlay": "EXCLUDED_USER_SPECIFIC_DATA",
        },
        "lanes": lanes,
        "creation_provenance": {
            "source": "CANONICAL_PUBLISHED_PRODUCT",
            "provider_calls": 0,
            "user_specific_data_included": False,
        },
    }


def publication_filename(publication: Mapping[str, Any]) -> str:
    generated = _SAFE_STAMP.sub(
        "-",
        str(publication["product_generated_at_utc"]).replace(":", ""),
    )
    source_sha = str(publication["source_product_sha256"])
    return f"{generated}--{source_sha[:16]}.json"


def _same_existing_product(path: Path, publication: Mapping[str, Any]) -> bool:
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AppendOnlyViolation(f"existing prospective record is unreadable: {path}") from exc
    return (
        existing.get("schema_version") == PUBLICATION_SCHEMA_VERSION
        and existing.get("publication_id") == publication.get("publication_id")
        and existing.get("source_product_sha256") == publication.get("source_product_sha256")
    )


def write_publication_snapshot(
    publication: Mapping[str, Any],
    publications_dir: str | Path,
) -> tuple[Path, bool]:
    """Create immutable evidence, or idempotently return the same product record."""
    if publication.get("schema_version") != PUBLICATION_SCHEMA_VERSION:
        raise ProspectiveCardError("unsupported prospective publication schema")
    source_sha = str(publication.get("source_product_sha256") or "")
    if len(source_sha) != 64 or any(ch not in "0123456789abcdef" for ch in source_sha):
        raise ProspectiveCardError("source_product_sha256 must be lowercase SHA-256 hex")

    root = Path(publications_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = root / publication_filename(publication)
    payload = canonical_json_bytes(dict(publication))

    if target.exists():
        if _same_existing_product(target, publication):
            return target, False
        raise AppendOnlyViolation(f"immutable prospective path conflicts with existing evidence: {target}")

    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    except FileExistsError:
        if _same_existing_product(target, publication):
            return target, False
        raise AppendOnlyViolation(f"immutable prospective path raced with conflicting evidence: {target}")

    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target, True


def load_publications(publications_dir: str | Path) -> list[dict[str, Any]]:
    root = Path(publications_dir)
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for path in sorted(root.glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("schema_version") != PUBLICATION_SCHEMA_VERSION:
            raise ProspectiveCardError(f"unexpected publication schema in {path}")
        source_sha = str(row["source_product_sha256"])
        if source_sha in seen_hashes:
            raise ProspectiveCardError(f"duplicate source product hash in prospective history: {source_sha}")
        seen_hashes.add(source_sha)
        parse_utc(str(row["published_at_utc"]))
        rows.append(row)
    return sorted(rows, key=lambda row: (str(row["published_at_utc"]), str(row["publication_id"])))
