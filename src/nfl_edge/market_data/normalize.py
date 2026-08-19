"""Outcome-blind normalization of the raw historical sportsbook acquisition.

Produces the NORMALIZED layer from the immutable RAW acquisition:
one long-form observation per (provider event, bookmaker, market, outcome),
carrying full provenance back to its raw file and ledger entry.

Rules (Task 05E-D2, Phase B):
* RAW is immutable — never read-write, always read-only from production.
* BOOK-SPECIFIC observations only — no consensus, no averaging, no weights,
  no vig removal here. Raw odds semantics are preserved verbatim.
* Outcome-blind — no scores, results, or derived-edge values are consulted,
  computed, or stored.
* Target vs non-target events are marked but never conflated; canonical
  target-game identity is resolved deterministically in canonical.py.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import polars as pl

from .matching import MatchError, resolve_event_identity
from .manifest import ALLOWED_BOOKS, MARKETS

UTC_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


@dataclass(frozen=True)
class ParseResult:
    """Parsing outcome for one bookmaker market block."""

    market: str
    outcome_rows: list[dict]
    malformed: bool = False
    malformed_reason: str | None = None


class NormalizationError(RuntimeError):
    """Raised on a normalization failure that must stop the pipeline."""


def _norm_ts(value: str | None) -> str | None:
    """Normalize a provider timestamp to a canonical ISO-8601 UTC string."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # strip fractional seconds for stability
    s = re.sub(r"(\.\d+)(?=[+-]\d{2}:?\d{2}$|$)", "", s)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None  # require aware timestamps; fail closed
    return dt.isoformat()


def parse_market(market: dict) -> ParseResult:
    """Parse one bookmaker market block into long-form outcome rows.

    Handles h2h, spreads, totals with orientation rules but does NOT alter
    prices or points; malformed structures are flagged, never silently fixed.
    """
    mkey = market.get("key")
    outcomes = market.get("outcomes") or []
    rows: list[dict] = []
    malformed = False
    reason: str | None = None

    if mkey == "h2h":
        # two-way: outcome name == team name, price = american odds
        for o in outcomes:
            rows.append({"side": "team", "name": o.get("name"), "point": None, "price": _int(o.get("price"))})
        if len(outcomes) != 2:
            malformed, reason = True, f"h2h pair has {len(outcomes)} outcomes (expected 2)"
    elif mkey == "spreads":
        for o in outcomes:
            rows.append({"side": "team", "name": o.get("name"), "point": _num(o.get("point")), "price": _int(o.get("price"))})
        pts = [r["point"] for r in rows if r["point"] is not None]
        if len(outcomes) != 2:
            malformed, reason = True, f"spread pair has {len(outcomes)} outcomes (expected 2)"
        elif len(pts) == 2 and abs(pts[0] + pts[1]) > 1e-6:
            malformed, reason = True, f"spread points not symmetric ({pts[0]}, {pts[1]})"
    elif mkey == "totals":
        for o in outcomes:
            rows.append({"side": str(o.get("name") or "").lower(), "name": o.get("name"), "point": _num(o.get("point")), "price": _int(o.get("price"))})
        pts = [r["point"] for r in rows if r["point"] is not None]
        if len(outcomes) != 2:
            malformed, reason = True, f"totals pair has {len(outcomes)} outcomes (expected 2)"
        elif len(pts) == 2 and abs(pts[0] - pts[1]) > 1e-6:
            malformed, reason = True, f"totals points disagree ({pts[0]}, {pts[1]})"
    else:
        malformed, reason = True, f"unexpected market key {mkey!r}"

    return ParseResult(market=mkey, outcome_rows=rows, malformed=malformed, malformed_reason=reason)


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _num(v):
    try:
        f = float(v)
        return f if f == int(f) else f
    except (TypeError, ValueError):
        return None


def sha256_of(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_normalized(
    raw_root: str | Path,
    ledger_path: str | Path,
    request_plan_path: str | Path,
) -> pl.DataFrame:
    """Build the normalized long-form frame from RAW + ledger + plan.

    Reads RAW read-only. Returns a polars frame with one row per outcome
    observation. Does NOT write anything; the caller persists it.
    """
    raw_root = Path(raw_root)
    plan = pl.read_parquet(request_plan_path)
    # plan: request_plan_id -> season, requested_target_timestamp_utc, expected_earliest_kickoff_utc, target_game_ids
    plan_map = {str(r["request_plan_id"]): r for r in plan.to_dicts()}

    # index ledger by request_plan_id
    led = pl.read_parquet(ledger_path)
    led_map = {str(r["request_plan_id"]): r for r in led.to_dicts()}

    check = raw_root / "__check__"
    rows: list[dict] = []

    for season_dir in sorted(p for p in raw_root.iterdir() if p.is_dir()):
        season = season_dir.name
        for f in sorted(season_dir.glob("*.json")):
            rid = f.stem
            prow = plan_map.get(rid)
            if prow is None:
                raise NormalizationError(f"raw file {f} has no plan row for {rid}")
            lrow = led_map.get(rid)
            if lrow is None:
                raise NormalizationError(f"raw file {f} has no ledger entry for {rid}")
            target_ts = prow["requested_target_timestamp_utc"]
            earliest_kickoff = prow["expected_earliest_kickoff_utc"]
            target_games = [g for g in str(prow["target_game_ids"]).split(",") if g]
            raw_sha = sha256_of(f)
            if lrow.get("response_content_sha256") and raw_sha != lrow["response_content_sha256"]:
                raise NormalizationError(
                    f"raw hash mismatch {f}: on-disk {raw_sha[:12]} != ledger {lrow['response_content_sha256'][:12]}"
                )
            payload = json.loads(f.read_text("utf-8"))
            snap_ts = _norm_ts(payload.get("timestamp"))
            if snap_ts is None:
                raise NormalizationError(f"{rid}: payload timestamp invalid/missing")
            events = payload.get("data") or []
            # build target game identity map for this cluster
            target_pairs = {}
            for gid in target_games:
                target_pairs[gid] = _target_pair(gid)
            for ev in events:
                ev_id = ev.get("id")
                ev_commence = _norm_ts(ev.get("commence_time"))
                ident = resolve_event_identity(ev.get("home_team"), ev.get("away_team"))
                pair = frozenset((ident.home_abbr, ident.away_abbr)) if ident.matched_exact else None
                # which target games does this event match?
                matched_targets = [g for g, p in target_pairs.items() if p == pair] if pair else []
                is_target = len(matched_targets) > 0
                for bm in ev.get("bookmakers") or []:
                    bkey = bm.get("key")
                    btitle = bm.get("title")
                    b_lu = _norm_ts(bm.get("last_update"))
                    for mkt in bm.get("markets") or []:
                        pr = parse_market(mkt)
                        for orow in pr.outcome_rows:
                            rows.append({
                                "request_plan_id": rid,
                                "season": int(season),
                                "raw_file_path": str(f.relative_to(raw_root)),
                                "raw_file_sha256": raw_sha,
                                "requested_snapshot_timestamp_utc": target_ts,
                                "actual_snapshot_timestamp_utc": snap_ts,
                                "expected_earliest_kickoff_utc": earliest_kickoff,
                                "provider_event_id": ev_id,
                                "event_commence_time_utc": ev_commence,
                                "provider_home_team": ev.get("home_team"),
                                "provider_away_team": ev.get("away_team"),
                                "home_abbr": ident.home_abbr,
                                "away_abbr": ident.away_abbr,
                                "is_target_event": is_target,
                                "matched_target_game_ids": ",".join(sorted(matched_targets)) if matched_targets else None,
                                "bookmaker_key": bkey,
                                "bookmaker_title": btitle,
                                "bookmaker_last_update_utc": b_lu,
                                "market_key": mkt.get("key"),
                                "market_last_update_utc": _norm_ts(mkt.get("last_update")),
                                "side": orow["side"],
                                "outcome_name": orow["name"],
                                "point": orow["point"],
                                "american_price": orow["price"],
                                "malformed_market": pr.malformed,
                                "malformed_reason": pr.malformed_reason,
                            })

    df = pl.DataFrame(
        rows,
        strict=False,
        schema={
            "request_plan_id": pl.Utf8,
            "season": pl.Int32,
            "raw_file_path": pl.Utf8,
            "raw_file_sha256": pl.Utf8,
            "requested_snapshot_timestamp_utc": pl.Utf8,
            "actual_snapshot_timestamp_utc": pl.Utf8,
            "expected_earliest_kickoff_utc": pl.Utf8,
            "provider_event_id": pl.Utf8,
            "event_commence_time_utc": pl.Utf8,
            "provider_home_team": pl.Utf8,
            "provider_away_team": pl.Utf8,
            "home_abbr": pl.Utf8,
            "away_abbr": pl.Utf8,
            "is_target_event": pl.Boolean,
            "matched_target_game_ids": pl.Utf8,
            "bookmaker_key": pl.Utf8,
            "bookmaker_title": pl.Utf8,
            "bookmaker_last_update_utc": pl.Utf8,
            "market_key": pl.Utf8,
            "market_last_update_utc": pl.Utf8,
            "side": pl.Utf8,
            "outcome_name": pl.Utf8,
            "point": pl.Float64,
            "american_price": pl.Int32,
            "malformed_market": pl.Boolean,
            "malformed_reason": pl.Utf8,
        },
    )
    return df


def _target_pair(game_id: str) -> frozenset[str]:
    from .matching import game_id_abbr_pair
    return game_id_abbr_pair(game_id)


def write_normalized_frame(df: pl.DataFrame, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path, compression="zstd")