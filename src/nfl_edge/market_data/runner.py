"""Safe, resumable historical-market acquisition runner (Task 05E-C3).

Safety contract implemented here:

* **Dry-run by default** — ``run_plan(execute=False)`` makes zero HTTP calls,
  requires no credential, and never reads ``ODDS_API_KEY``.
* **Explicit execution gate** — only ``execute=True`` opens the network path,
  and that path reads *only* the single exact variable ``ODDS_API_KEY``
  (never enumerated environment variables).
* **Preserve every paid 2xx response** — the exact raw bytes of any 2xx
  response are persisted immutably and ledgered BEFORE any post-response
  semantic validation that could stop the run, so a paid-but-invalid response
  never disappears and is never re-purchased.
* **Resume distinguishes three states** — ``VERIFIED_SUCCESS`` (skip),
  ``PAID_REJECTED`` (stop; operator remediation required, never re-query),
  ``REQUEST_FAILED`` (stop; no automatic retry).
* **Fail-closed snapshot** — a 2xx response must be a valid JSON object with a
  timezone-aware UTC ``timestamp`` strictly before the cluster's earliest
  kickoff, else it is preserved + ledgered as ``PAID_REJECTED`` and the run
  stops.
* **Single worker** — live execution is wrapped in an exclusive fail-fast
  acquisition lock; a concurrent worker is blocked before any API call.
* **Runtime plan contract** — ``run_live_acquisition`` validates the loaded
  plan (rows, seasons, counts, uniqueness, 1,408 games, books, markets,
  credits, SHA-256) BEFORE the first network call, and enforces the 17,250
  credit ceiling via the remaining-eligible × 30 projection.
* **Secret safety** — any URL persisted to the ledger is redacted so the
  ``apiKey`` value never lands on disk or in logs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import polars as pl

from .ledger import (
    CATEGORY_PAID_REJECTED,
    CATEGORY_REQUEST_FAILED,
    CATEGORY_VERIFIED_SUCCESS,
    LEDGER_PATH,
    LedgerEntry,
    append_ledger_entry,
    classify_request,
    completed_request_ids,
    ensure_secret_safe_text,
    _utc_now_iso,
    write_raw_immutable,
)
from .locking import acquisition_lock
from .manifest import (
    ALLOWED_BOOKS,
    EXPECTED_COST_PER_SUCCESSFUL_REQUEST,
    INITIAL_PLANNED_CREDIT_CAP,
    LOCK_DIR,
    MARKETS,
    ODDS_API_HISTORICAL_BASE,
    ODDS_API_KEY_ENV,
    ODDS_API_ODDS_FORMAT,
    ODDS_API_REGIONS,
    RAW_ROOT,
    RESPONSE_COST_HEADER,
)
from .plan import validate_plan_contract


class AcquisitionStop(RuntimeError):
    """Base for a deliberate, non-retry stop of the acquisition run."""


class CostContractViolation(AcquisitionStop):
    """A 2xx response reported a credit cost != 30 (raw preserved + PAID_REJECTED)."""


class PregameViolation(AcquisitionStop):
    """A 2xx snapshot timestamp failed validation (raw preserved + PAID_REJECTED)."""


class OperatorRemediationRequired(AcquisitionStop):
    """A PAID_REJECTED request must be resolved by an operator, not re-queried."""


class BuildRequestError(RuntimeError):
    """Invalid arguments to build the request URL."""


# Validation status values recorded on ledger rows.
VALIDATION_PASS = "PASS"
VALIDATION_COST_MISMATCH = "COST_MISMATCH"
VALIDATION_INVALID_JSON = "INVALID_JSON"
VALIDATION_MISSING_TIMESTAMP = "MISSING_TIMESTAMP"
VALIDATION_INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
VALIDATION_SNAPSHOT_NOT_PREGAME = "SNAPSHOT_NOT_PREGAME"
VALIDATION_REQUEST_ERROR = "REQUEST_ERROR"


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


def _parse_strict_utc(value: str) -> datetime | None:
    """Parse an ISO-8601 UTC timestamp, returning None unless tz-aware.

    A ``Z`` suffix becomes ``+00:00``; a string with no explicit offset is
    naive and is rejected (``None``).
    """
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _num(value) -> int | None:
    return None if value is None else int(value)


def _fetch_error(failure_reason: str) -> str:
    return failure_reason[:500]


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


def _parse_2xx_payload(content: bytes) -> tuple[bool, str | None, str | None, str | None]:
    """Return ``(is_valid_json_object, timestamp, previous, next)``."""
    try:
        payload = json.loads(content.decode("utf-8"))
    except Exception:
        return False, None, None, None
    if not isinstance(payload, dict):
        return False, None, None, None
    return (
        True,
        payload.get("timestamp"),
        payload.get("previous_timestamp"),
        payload.get("next_timestamp"),
    )


def _validate_2xx(
    headers: Mapping[str, str],
    content: bytes,
    earliest_kickoff: datetime,
) -> tuple[bool, str, str | None, str | None, str | None, str | None]:
    """Validate a paid 2xx response; returns
    ``(ok, status, reason, actual, prev, next)``.

    Fail-closed requirements: valid JSON object, present timestamp, timestamp
    parses as timezone-aware UTC, timestamp < earliest kickoff. Any failure
    leaves ``ok=False`` and a specific ``status``/``reason`` so the caller can
    ledger it as PAID_REJECTED.
    """
    cost = _num(headers.get(RESPONSE_COST_HEADER))
    if cost != EXPECTED_COST_PER_SUCCESSFUL_REQUEST:
        return (
            False,
            VALIDATION_COST_MISMATCH,
            f"{RESPONSE_COST_HEADER}={cost} != {EXPECTED_COST_PER_SUCCESSFUL_REQUEST}",
            None,
            None,
            None,
        )
    valid_json, actual, prev, next_ = _parse_2xx_payload(content)
    if not valid_json:
        return False, VALIDATION_INVALID_JSON, "payload is not a valid JSON object", None, None, None
    if not actual:
        return False, VALIDATION_MISSING_TIMESTAMP, "payload missing timestamp", None, prev, next_
    parsed = _parse_strict_utc(actual)
    if parsed is None:
        return (
            False,
            VALIDATION_INVALID_TIMESTAMP,
            f"timestamp is not timezone-aware UTC: {actual!r}",
            actual,
            prev,
            next_,
        )
    if parsed >= earliest_kickoff:
        return (
            False,
            VALIDATION_SNAPSHOT_NOT_PREGAME,
            f"snapshot {actual} is not strictly before earliest kickoff "
            f"{earliest_kickoff.isoformat()}",
            actual,
            prev,
            next_,
        )
    return True, VALIDATION_PASS, None, actual, prev, next_


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

    For every paid 2xx response the exact raw bytes are preserved immutably
    and ledgered BEFORE any semantic validation. If validation fails the
    response is ledgered as ``PAID_REJECTED`` (success=False) and the run
    stops — the paid response is never discarded and never re-purchased.
    """
    plan_id = str(row["request_plan_id"])
    season = int(row["season"])
    target_utc = str(row["requested_target_timestamp_utc"])
    earliest_raw = str(row["expected_earliest_kickoff_utc"])
    earliest_kickoff = _parse_strict_utc(earliest_raw)
    if earliest_kickoff is None:
        raise AcquisitionStop(f"request {plan_id}: invalid earliest kickoff {earliest_raw!r}")
    bookmakers = tuple(
        key for key in str(row["requested_bookmaker_keys"]).split(",") if key
    )
    markets = tuple(key for key in str(row["requested_markets"]).split(",") if key)
    url = build_request_url(
        target_utc, api_key, bookmakers=bookmakers, markets=markets
    )
    url_redacted = redact_url(url)
    ensure_secret_safe_text(url_redacted, secrets=(api_key,))

    common = {
        "request_plan_id": plan_id,
        "season": season,
        "cluster_id": str(row["cluster_id"]),
        "requested_target_timestamp_utc": target_utc,
        "expected_earliest_kickoff_utc": earliest_raw,
        "target_game_ids": str(row["target_game_ids"]),
        "requested_bookmaker_keys": str(row["requested_bookmaker_keys"]),
        "requested_markets": str(row["requested_markets"]),
        "request_url_redacted": url_redacted,
    }

    try:
        status, headers, content = fetch_single(
            url, api_key=api_key, session=session, timeout_seconds=timeout_seconds
        )
    except Exception as exc:  # noqa: BLE001 - record and stop, no paid snapshot
        append_ledger_entry(
            LedgerEntry(
                **common,
                actual_snapshot_timestamp_utc=None,
                previous_snapshot_timestamp_utc=None,
                next_snapshot_timestamp_utc=None,
                http_status=None,
                x_requests_last=None,
                x_requests_used=None,
                x_requests_remaining=None,
                response_content_sha256=None,
                acquisition_timestamp_utc=_utc_now_iso(),
                raw_payload_path=None,
                success=False,
                attempt_category=CATEGORY_REQUEST_FAILED,
                validation_status=VALIDATION_REQUEST_ERROR,
                failure_reason=_fetch_error(f"{type(exc).__name__}: {exc}"),
                error_class=type(exc).__name__,
                error_message=str(exc)[:500],
            ),
            ledger_path,
        )
        raise AcquisitionStop(
            f"request {plan_id} failed ({type(exc).__name__}); recording REQUEST_FAILED "
            "and stopping (no automatic retry, no paid snapshot accepted)."
        ) from exc

    if not (200 <= status < 300):
        append_ledger_entry(
            LedgerEntry(
                **common,
                actual_snapshot_timestamp_utc=None,
                previous_snapshot_timestamp_utc=None,
                next_snapshot_timestamp_utc=None,
                http_status=status,
                x_requests_last=_num(headers.get(RESPONSE_COST_HEADER)),
                x_requests_used=_num(headers.get("x-requests-used")),
                x_requests_remaining=_num(headers.get("x-requests-remaining")),
                response_content_sha256=None,
                acquisition_timestamp_utc=_utc_now_iso(),
                raw_payload_path=None,
                success=False,
                attempt_category=CATEGORY_REQUEST_FAILED,
                validation_status=f"HTTP_{status}",
                failure_reason=f"non-2xx status {status}",
                error_class="HTTPError",
                error_message=f"status={status}",
            ),
            ledger_path,
        )
        raise AcquisitionStop(
            f"request {plan_id} HTTP {status}; recording REQUEST_FAILED and stopping."
        )

    # ---- 2xx: preserve the paid response immutably FIRST ----
    raw_rel = Path(str(season)) / f"{plan_id}.json"
    raw_path = raw_root / raw_rel
    try:
        digest = write_raw_immutable(raw_path, content)
    except FileExistsError as exc:
        raise AcquisitionStop(
            f"request {plan_id}: raw already exists at {raw_path}; stopping. A prior "
            "paid attempt exists without a verified ledger row — operator remediation required."
        ) from exc

    ok, validation_status, failure_reason, actual, prev, next_ = _validate_2xx(
        headers, content, earliest_kickoff
    )
    cost = _num(headers.get(RESPONSE_COST_HEADER))
    entry = LedgerEntry(
        **common,
        actual_snapshot_timestamp_utc=actual,
        previous_snapshot_timestamp_utc=prev,
        next_snapshot_timestamp_utc=next_,
        http_status=status,
        x_requests_last=cost,
        x_requests_used=_num(headers.get("x-requests-used")),
        x_requests_remaining=_num(headers.get("x-requests-remaining")),
        response_content_sha256=digest,
        acquisition_timestamp_utc=_utc_now_iso(),
        raw_payload_path=str(raw_rel),
        success=ok,
        attempt_category=CATEGORY_VERIFIED_SUCCESS if ok else CATEGORY_PAID_REJECTED,
        validation_status=validation_status,
        failure_reason=failure_reason,
        error_class=None if ok else "ValidationError",
        error_message=None if ok else failure_reason,
    )
    append_ledger_entry(entry, ledger_path)

    if not ok:
        if validation_status == VALIDATION_COST_MISMATCH:
            raise CostContractViolation(
                f"request {plan_id}: {failure_reason}; raw preserved + ledgered "
                "as PAID_REJECTED. Stopping (credit contract)."
            )
        raise PregameViolation(
            f"request {plan_id}: {failure_reason}; raw preserved + ledgered as "
            "PAID_REJECTED. Stopping."
        )
    return entry


def dry_run_report(
    plan: pl.DataFrame,
    *,
    raw_root: str | Path = RAW_ROOT,
    ledger_path: str | Path = LEDGER_PATH,
) -> dict[str, Any]:
    """Compute the full dry-run report with zero network / credential access.

    Reads only the frozen request-plan artifact and the ledger.
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

    With ``execute=True``, classifies every request id against the ledger and:

    * stops (``OperatorRemediationRequired``) if any id is PAID_REJECTED;
    * stops (``AcquisitionStop``) if any id is REQUEST_FAILED;
    * skips VERIFIED_SUCCESS ids without an API call;
    * issues only ELIGIBLE ids, enforcing the 17,250 credit ceiling via
      ``remaining_eligible × 30``.

    Callers of the live path should use :func:`run_live_acquisition`, which
    also validates the plan contract and holds the exclusive lock.
    """
    raw_root = Path(raw_root)
    ledger_path = Path(ledger_path)

    if not execute:
        return dry_run_report(plan, raw_root=raw_root, ledger_path=ledger_path)

    if api_key is None:
        raise AcquisitionStop(
            f"execute mode requires {ODDS_API_KEY_ENV}; refusing to run."
        )

    # Classify every id up front (reads ledger only; zero network).
    categories: dict[str, str] = {}
    for rid in plan.get_column("request_plan_id").unique().to_list():
        categories[rid] = classify_request(
            rid, ledger_path=ledger_path, raw_root=raw_root
        )

    paid_rejected = sorted(
        rid for rid, cat in categories.items() if cat == CATEGORY_PAID_REJECTED
    )
    if paid_rejected:
        raise OperatorRemediationRequired(
            "PAID_REJECTED request(s) require operator remediation before any "
            "resume; refusing to re-query: " + ", ".join(paid_rejected)
        )
    failed = sorted(
        rid for rid, cat in categories.items() if cat == CATEGORY_REQUEST_FAILED
    )
    if failed:
        raise AcquisitionStop(
            "request(s) previously failed without an accepted paid snapshot; "
            "no automatic retry: " + ", ".join(failed)
        )

    eligible_ids = {rid for rid, cat in categories.items() if cat == "ELIGIBLE"}
    done_count = sum(1 for cat in categories.values() if cat == CATEGORY_VERIFIED_SUCCESS)
    projected = len(eligible_ids) * EXPECTED_COST_PER_SUCCESSFUL_REQUEST
    if projected > INITIAL_PLANNED_CREDIT_CAP:
        raise AcquisitionStop(
            f"projected credits {projected} exceed planned cap "
            f"{INITIAL_PLANNED_CREDIT_CAP}; stopping."
        )

    results: dict[str, Any] = {
        "executed": 0,
        "skipped_completed": done_count,
        "remaining_eligible_requests": len(eligible_ids),
        "projected_max_credits": projected,
        "credit_cap": INITIAL_PLANNED_CREDIT_CAP,
    }

    for row in plan.iter_rows(named=True):
        plan_id = str(row["request_plan_id"])
        if plan_id not in eligible_ids:
            continue  # VERIFIED_SUCCESS (failed/paid_rejected already stopped)
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


def run_live_acquisition(
    plan: pl.DataFrame,
    *,
    plan_path: str | Path,
    api_key: str,
    raw_root: str | Path = RAW_ROOT,
    ledger_path: str | Path = LEDGER_PATH,
    lock_dir: str | Path = LOCK_DIR,
    session: Any = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Run the live acquisition safely: validate the plan, then hold the lock.

    Order guarantees:
    1. ``validate_plan_contract(plan, plan_path)`` — STOP BEFORE NETWORK on any
       contract violation (rows/seasons/counts/unique/1408/books/markets/
       credits/SHA-256).
    2. Acquire the exclusive fail-fast acquisition lock — a concurrent live
       worker is blocked before any API call.
    3. Delegate to ``run_plan(execute=True)`` which enforces resume semantics
       and the 17,250-credit ceiling.
    """
    validate_plan_contract(plan, plan_path)
    with acquisition_lock(lock_dir, kind="live_acquisition", lock_timeout_seconds=0.0):
        return run_plan(
            plan,
            execute=True,
            api_key=api_key,
            raw_root=raw_root,
            ledger_path=ledger_path,
            session=session,
            timeout_seconds=timeout_seconds,
        )
