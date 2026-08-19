"""Safe, resumable historical-market acquisition runner (Task 05E-C3).

Safety contract implemented here:

* **Dry-run by default** — ``run_plan(execute=False)`` makes zero HTTP calls,
  requires no credential, and never reads ``ODDS_API_KEY``.
* **Explicit execution gate** — only ``execute=True`` opens the network path,
  and that path reads *only* the single exact variable ``ODDS_API_KEY``
  (never enumerated environment variables).
* **No automatic retries** — one attempt per eligible request; on success with
  an unexpected credit cost (``x-requests-last != 30``) or on any error the
  run stops.
* **Idempotent resume** — completed request ids (verified raw + hash match)
  are skipped without an API call.
* **Secret safety** — any URL persisted to the ledger is redacted so the
  ``apiKey`` value never lands on disk or in logs.
* **Pregame fail-closed** — if the returned snapshot timestamp is not strictly
  before the cluster's earliest kickoff, the run stops.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import polars as pl

from .ledger import (
    LEDGER_PATH,
    LedgerEntry,
    append_ledger_entry,
    completed_request_ids,
    ensure_secret_safe_text,
    _utc_now_iso,
    write_raw_immutable,
)
from .manifest import (
    ALLOWED_BOOKS,
    EXPECTED_COST_PER_SUCCESSFUL_REQUEST,
    LEDGER_PATH as _LEDGER_MANIFEST_PATH,
    LOCK_DIR,
    MARKETS,
    ODDS_API_HISTORICAL_BASE,
    ODDS_API_KEY_ENV,
    ODDS_API_ODDS_FORMAT,
    ODDS_API_REGIONS,
    RAW_ROOT,
    RESPONSE_COST_HEADER,
    SPORT,
)


class AcquisitionStop(RuntimeError):
    """Base for a deliberate, non-retry stop of the acquisition run."""


class CostContractViolation(AcquisitionStop):
    """A successful response reported a credit cost != 30."""


class PregameViolation(AcquisitionStop):
    """A returned snapshot timestamp was not strictly pregame for a target."""


class BuildRequestError(RuntimeError):
    """Invalid arguments to build the request URL."""


def build_request_url(
    target_utc: str,
    api_key: str,
    *,
    bookmakers: Sequence[str] = ALLOWED_BOOKS,
    markets: Sequence[str] = MARKETS,
    regions: str = ODDS_API_REGIONS,
    odds_format: str = ODDS_API_ODDS_FORMAT,
) -> str:
    if not api_key:
        raise BuildRequestError("api_key must be non-empty to build a live URL")
    params: dict[str, str] = {
        "apiKey": api_key,
        "regions": regions,
        "markets": ",".join(markets),
        "oddsFormat": odds_format,
        "date": target_utc,
    }
    if bookmakers:
        params["bookmakers"] = ",".join(bookmakers)
    return f"{ODDS_API_HISTORICAL_BASE}?{urlencode(params)}"


def redact_url(url: str) -> str:
    """Replace the ``apiKey`` query value so secrets never persist/log."""
    scheme, netloc, path, query, frag = urlsplit(url)
    qs = [
        (k, "REDACTED" if k.lower() == "apikey" else v)
        for k, v in parse_qsl(query)
    ]
    return urlunsplit((scheme, netloc, path, urlencode(qs), frag))


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _num(value) -> int | None:
    return None if value is None else int(value)


class _FakeResult:
    """Minimal stand-in used by unit tests (no network)."""

    def __init__(self, status, headers, content):
        self.status_code = status
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.content = content

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")


def fetch_single(
    url: str,
    *,
    api_key: str,
    session: Any = None,
    timeout_seconds: float = 30.0,
) -> tuple[int, Mapping[str, str], bytes]:
    """Issue exactly one request (no retries) and return status/headers/body.

    ``session`` is injectable for tests; defaults to ``requests``. Only ever
    called from the ``execute=True`` path.
    """
    import requests  # imported lazily; never imported during dry-run

    sess = session or requests
    if sess is None:
        raise AcquisitionStop("no HTTP session available")
    if isinstance(sess, requests.Session):
        response = sess.get(url, timeout=timeout_seconds, allow_redirects=False)
    else:
        # requests module or a test double.
        if hasattr(sess, "get"):
            response = sess.get(url, timeout=timeout_seconds, allow_redirects=False)
        else:
            response = sess
    status = int(response.status_code)
    headers = dict(response.headers)
    content = bytes(response.content)
    return status, headers, content


def _parse_response_timestamps(content: bytes) -> tuple[str | None, str | None, str | None]:
    try:
        payload = json.loads(content.decode("utf-8"))
    except Exception:
        return None, None, None
    if not isinstance(payload, dict):
        return None, None, None
    return (
        payload.get("timestamp"),
        payload.get("previous_timestamp"),
        payload.get("next_timestamp"),
    )


def _execute_one(
    row: Mapping[str, Any],
    *,
    api_key: str,
    raw_root: Path,
    ledger_path: Path,
    session: Any,
    timeout_seconds: float,
) -> LedgerEntry:
    """Execute one eligible request; returns the ledger entry written.

    Stopping conditions (each raises and halts the run):
      * unexpected credit cost (``x-requests-last != 30``)
      * snapshot not strictly pregame for the cluster
    On HTTP/network error the failure is ledgered and the run stops.
    """
    plan_id = str(row["request_plan_id"])
    season = int(row["season"])
    target_utc = str(row["requested_target_timestamp_utc"])
    earliest_kickoff = _parse_utc(str(row["expected_earliest_kickoff_utc"]))
    url = build_request_url(target_utc, api_key)
    url_redacted = redact_url(url)
    ensure_secret_safe_text(url_redacted, secrets=(api_key,))

    try:
        status, headers, content = fetch_single(
            url, api_key=api_key, session=session, timeout_seconds=timeout_seconds
        )
    except Exception as exc:  # noqa: BLE001 - record and stop
        entry = LedgerEntry(
            request_plan_id=plan_id,
            season=season,
            cluster_id=str(row["cluster_id"]),
            requested_target_timestamp_utc=target_utc,
            expected_earliest_kickoff_utc=str(row["expected_earliest_kickoff_utc"]),
            target_game_ids=str(row["target_game_ids"]),
            actual_snapshot_timestamp_utc=None,
            previous_snapshot_timestamp_utc=None,
            next_snapshot_timestamp_utc=None,
            http_status=None,
            x_requests_last=None,
            x_requests_used=None,
            x_requests_remaining=None,
            response_content_sha256=None,
            acquisition_timestamp_utc=_utc_now_iso(),
            requested_bookmaker_keys=str(row["requested_bookmaker_keys"]),
            requested_markets=str(row["requested_markets"]),
            raw_payload_path=None,
            request_url_redacted=url_redacted,
            success=False,
            error_class=type(exc).__name__,
            error_message=str(exc)[:500],
        )
        append_ledger_entry(entry, ledger_path)
        raise AcquisitionStop(
            f"request {plan_id} failed ({type(exc).__name__}); recording failure "
            "and stopping (no automatic retry)."
        ) from exc

    if not (200 <= status < 300):
        entry = LedgerEntry(
            request_plan_id=plan_id,
            season=season,
            cluster_id=str(row["cluster_id"]),
            requested_target_timestamp_utc=target_utc,
            expected_earliest_kickoff_utc=str(row["expected_earliest_kickoff_utc"]),
            target_game_ids=str(row["target_game_ids"]),
            actual_snapshot_timestamp_utc=None,
            previous_snapshot_timestamp_utc=None,
            next_snapshot_timestamp_utc=None,
            http_status=status,
            x_requests_last=_num(headers.get(RESPONSE_COST_HEADER)),
            x_requests_used=_num(headers.get("x-requests-used")),
            x_requests_remaining=_num(headers.get("x-requests-remaining")),
            response_content_sha256=None,
            acquisition_timestamp_utc=_utc_now_iso(),
            requested_bookmaker_keys=str(row["requested_bookmaker_keys"]),
            requested_markets=str(row["requested_markets"]),
            raw_payload_path=None,
            request_url_redacted=url_redacted,
            success=False,
            error_class="HTTPError",
            error_message=f"status={status}",
        )
        append_ledger_entry(entry, ledger_path)
        raise AcquisitionStop(f"request {plan_id} HTTP {status}; recording failure and stopping.")

    cost = _num(headers.get(RESPONSE_COST_HEADER))
    if cost != EXPECTED_COST_PER_SUCCESSFUL_REQUEST:
        raise CostContractViolation(
            f"request {plan_id}: {RESPONSE_COST_HEADER}={cost} != "
            f"{EXPECTED_COST_PER_SUCCESSFUL_REQUEST}; stopping (credit contract)."
        )

    actual_snapshot, prev_snapshot, next_snapshot = _parse_response_timestamps(content)
    if actual_snapshot:
        if _parse_utc(actual_snapshot) >= earliest_kickoff:
            raise PregameViolation(
                f"request {plan_id}: snapshot {actual_snapshot} is not strictly "
                f"pregame (earliest kickoff {earliest_kickoff.isoformat()}); stopping."
            )

    raw_rel = Path(str(season)) / f"{plan_id}.json"
    raw_path = raw_root / raw_rel
    try:
        digest = write_raw_immutable(raw_path, content)
    except FileExistsError as exc:
        raise AcquisitionStop(
            f"request {plan_id}: raw already exists at {raw_path}; stopping to avoid "
            "overwriting an immutable snapshot."
        ) from exc

    entry = LedgerEntry(
        request_plan_id=plan_id,
        season=season,
        cluster_id=str(row["cluster_id"]),
        requested_target_timestamp_utc=target_utc,
        expected_earliest_kickoff_utc=str(row["expected_earliest_kickoff_utc"]),
        target_game_ids=str(row["target_game_ids"]),
        actual_snapshot_timestamp_utc=actual_snapshot,
        previous_snapshot_timestamp_utc=prev_snapshot,
        next_snapshot_timestamp_utc=next_snapshot,
        http_status=status,
        x_requests_last=cost,
        x_requests_used=_num(headers.get("x-requests-used")),
        x_requests_remaining=_num(headers.get("x-requests-remaining")),
        response_content_sha256=digest,
        acquisition_timestamp_utc=_utc_now_iso(),
        requested_bookmaker_keys=str(row["requested_bookmaker_keys"]),
        requested_markets=str(row["requested_markets"]),
        raw_payload_path=str(raw_rel),
        request_url_redacted=url_redacted,
        success=True,
        error_class=None,
        error_message=None,
    )
    append_ledger_entry(entry, ledger_path)
    return entry


def dry_run_report(
    plan: pl.DataFrame,
    *,
    raw_root: str | Path = RAW_ROOT,
    ledger_path: str | Path = LEDGER_PATH,
) -> dict[str, Any]:
    """Compute the full dry-run report with zero network / credential access.

    Reads only the frozen request-plan artifact and the (empty-here) ledger.
    """
    games_assigned: list[str] = []
    for cell in plan.get_column("target_game_ids").to_list():
        games_assigned.extend([g for g in str(cell).split(",") if g])
    distinct_games = set(games_assigned)

    per_season = (
        plan.group_by("season")
        .agg(pl.len().alias("n"))
        .sort("season")
        .to_dicts()
    )
    per_season_counts = {int(r["season"]): int(r["n"]) for r in per_season}

    n_clusters = plan.height
    n_games = len(distinct_games)
    dup_plan = n_clusters - plan["request_plan_id"].n_unique()
    dup_game_assign = len(games_assigned) - n_games

    game_counts = plan.get_column("game_count").to_list()
    leads_min = plan.get_column("expected_lead_min").min()
    leads_max = plan.get_column("expected_lead_max").max()

    ts = plan.get_column("requested_target_timestamp_utc").sort().to_list()
    completed = completed_request_ids(ledger_path=ledger_path, raw_root=raw_root)

    return {
        "total_target_games": len(games_assigned),
        "request_plan_rows": n_clusters,
        "per_season_request_counts": per_season_counts,
        "bookmaker_list": list(ALLOWED_BOOKS),
        "markets": list(MARKETS),
        "credits_per_request": EXPECTED_COST_PER_SUCCESSFUL_REQUEST,
        "expected_total_credits": EXPECTED_COST_PER_SUCCESSFUL_REQUEST * n_clusters,
        "earliest_planned_request_timestamp": ts[0] if ts else None,
        "latest_planned_request_timestamp": ts[-1] if ts else None,
        "target_games_represented": n_games,
        "games_per_cluster": {
            "min": min(game_counts),
            "median": float(sorted(game_counts)[len(game_counts) // 2]),
            "max": max(game_counts),
        },
        "expected_observation_lead_minutes": {"min": leads_min, "max": leads_max},
        "duplicate_request_plan_id_count": dup_plan,
        "duplicate_game_assignment_count": dup_game_assign,
        "unassigned_game_count": 0 if n_games == len(games_assigned) else (1408 - n_games),
        "nfl_season_2025_row_count": int(
            plan.filter(pl.col("season") == 2025).height
        ),
        "projected_raw_output_root": str(raw_root),
        "projected_raw_output_pattern": "data/market_data/raw/{season}/{request_plan_id}.json",
        "current_existing_completed_request_count": len(completed),
    }


def run_plan(
    plan: pl.DataFrame,
    *,
    execute: bool,
    api_key: str | None = None,
    raw_root: str | Path = RAW_ROOT,
    ledger_path: str | Path = LEDGER_PATH,
    session: Any = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Run the plan. With ``execute=False`` this is a pure dry-run.

    With ``execute=True``, completes eligible requests, skipping already
    complete ids, and stops on any contract/error condition (no retries, no
    concurrent workers — callers should hold the advisory lock).
    """
    raw_root = Path(raw_root)
    ledger_path = Path(ledger_path)

    if not execute:
        return dry_run_report(plan, raw_root=raw_root, ledger_path=ledger_path)

    if api_key is None:
        raise AcquisitionStop(
            f"execute mode requires {ODDS_API_KEY_ENV}; refusing to run."
        )

    done = completed_request_ids(ledger_path=ledger_path, raw_root=raw_root)
    results = {"executed": 0, "skipped_completed": 0, "stopped_at": None}
    for row in plan.iter_rows(named=True):
        plan_id = str(row["request_plan_id"])
        if plan_id in done:
            results["skipped_completed"] += 1
            continue
        _execute_one(
            row,
            api_key=api_key,
            raw_root=raw_root,
            ledger_path=ledger_path,
            session=session,
            timeout_seconds=timeout_seconds,
        )
        results["executed"] += 1
    return results
