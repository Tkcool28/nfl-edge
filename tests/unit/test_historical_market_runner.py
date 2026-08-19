"""Runner safety contract: dry-run/no-call, execute gate, paid-response
preservation, PAID_REJECTED resume, lock, plan-contract, credit cap, secret
safety, no env enumeration (§G/I/J/M + pre-pull remediation)."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from nfl_edge.market_data import runner
from nfl_edge.market_data.ledger import (
    CATEGORY_PAID_REJECTED,
    CATEGORY_REQUEST_FAILED,
    CATEGORY_VERIFIED_SUCCESS,
)
from nfl_edge.market_data.locking import LockFailure, acquisition_lock
from nfl_edge.market_data.manifest import ODDS_API_KEY_ENV
from nfl_edge.market_data.plan import PlanContractError
from nfl_edge.market_data.runner import (
    AcquisitionStop,
    CostContractViolation,
    OperatorRemediationRequired,
    PregameViolation,
    redact_url,
    run_live_acquisition,
    run_plan,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FAKE_KEY = "FAKEKEY_0123456789abcdef"
REAL_PLAN = REPO_ROOT / "data/manifests/historical_market_request_plan_v1.parquet"


class FakeResp:
    def __init__(self, status=200, headers=None, content=b"{}"):
        self.status_code = status
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.content = content

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")


class FakeSession:
    def __init__(self, resp):
        self.resp = resp
        self.calls = 0

    def get(self, url, timeout=None, allow_redirects=None):
        self.calls += 1
        if isinstance(self.resp, Exception):
            raise self.resp
        return self.resp


def _one_row_plan(earliest="2020-01-01T18:00:00Z", target="2020-01-01T17:00:00Z"):
    return pl.DataFrame(
        {
            "request_plan_id": ["md_2020_001"],
            "cluster_id": ["2020_001"],
            "season": [2020],
            "requested_target_timestamp_utc": [target],
            "expected_earliest_kickoff_utc": [earliest],
            "target_game_ids": ["2020_01_A_B"],
            "requested_bookmaker_keys": ["draftkings,fanduel"],
            "requested_markets": ["h2h,spreads,totals"],
        }
    )


def _paths(tmp_path):
    return tmp_path / "raw", tmp_path / "ledger" / "ledger.parquet"


def _ok_200(timestamp="2020-01-01T16:59:00Z", headers=None):
    h = {"x-requests-last": "30"}
    if headers:
        h.update(headers)
    return FakeResp(status=200, headers=h, content=json.dumps({"timestamp": timestamp}).encode())


def _ledger_rows(ledger_path, plan_id):
    return pl.read_parquet(ledger_path).filter(
        pl.col("request_plan_id") == plan_id
    ).to_dicts()


# --- dry-run / no-call guarantees -------------------------------------------

def test_dry_run_makes_zero_http_calls(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    session = FakeSession(RuntimeError("must not hit the network"))
    plan = pl.read_parquet(REAL_PLAN)
    rep = run_plan(
        plan, execute=False, raw_root=raw_root, ledger_path=ledger_path, session=session
    )
    assert session.calls == 0
    assert rep["request_plan_rows"] == 575
    assert rep["current_existing_completed_request_count"] == 0


def test_default_invocation_is_dry_run(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    plan = pl.read_parquet(REAL_PLAN)
    rep = run_plan(plan, execute=False, raw_root=raw_root, ledger_path=ledger_path)
    assert rep["per_season_request_counts"] == {
        2020: 107, 2021: 111, 2022: 116, 2023: 120, 2024: 121,
    }


def test_execute_requires_explicit_gate():
    with pytest.raises(AcquisitionStop):
        run_plan(_one_row_plan(), execute=True, api_key=None)


# --- paid 2xx preservation: every paid response is kept + ledgered FIRST ----

def test_paid_2xx_wrong_cost_preserved_ledgered_stops_no_requery(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    resp = FakeResp(
        status=200,
        headers={"x-requests-last": "25"},  # unexpected cost, still paid
        content=json.dumps({"timestamp": "2020-01-01T16:59:00Z"}).encode(),
    )
    with pytest.raises(CostContractViolation):
        run_plan(
            _one_row_plan(), execute=True, api_key=FAKE_KEY,
            raw_root=raw_root, ledger_path=ledger_path, session=FakeSession(resp),
        )
    raw_file = raw_root / "2020" / "md_2020_001.json"
    assert raw_file.exists()  # paid response preserved
    rows = _ledger_rows(ledger_path, "md_2020_001")
    assert rows[0]["attempt_category"] == CATEGORY_PAID_REJECTED
    assert rows[0]["success"] is False
    assert rows[0]["validation_status"] == "COST_MISMATCH"
    assert rows[0]["response_content_sha256"] is not None  # hash recorded
    assert rows[0]["raw_payload_path"] == "2020/md_2020_001.json"

    # Resume must STOP (operator remediation) and NOT re-query the paid id.
    fresh = FakeSession(_ok_200())
    with pytest.raises(OperatorRemediationRequired):
        run_plan(
            _one_row_plan(), execute=True, api_key=FAKE_KEY,
            raw_root=raw_root, ledger_path=ledger_path, session=fresh,
        )
    assert fresh.calls == 0  # no re-purchase


def test_paid_2xx_missing_timestamp_preserved_and_rejected(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    resp = FakeResp(status=200, headers={"x-requests-last": "30"}, content=b'{"data": []}')
    with pytest.raises(PregameViolation):
        run_plan(
            _one_row_plan(), execute=True, api_key=FAKE_KEY,
            raw_root=raw_root, ledger_path=ledger_path, session=FakeSession(resp),
        )
    assert (raw_root / "2020" / "md_2020_001.json").exists()
    row = _ledger_rows(ledger_path, "md_2020_001")[0]
    assert row["attempt_category"] == CATEGORY_PAID_REJECTED
    assert row["success"] is False
    assert row["validation_status"] == "MISSING_TIMESTAMP"


def test_paid_2xx_invalid_timestamp_preserved_and_rejected(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    resp = FakeResp(
        status=200,
        headers={"x-requests-last": "30"},
        content=json.dumps({"timestamp": "not-a-timestamp"}).encode(),
    )
    with pytest.raises(PregameViolation):
        run_plan(
            _one_row_plan(), execute=True, api_key=FAKE_KEY,
            raw_root=raw_root, ledger_path=ledger_path, session=FakeSession(resp),
        )
    assert (raw_root / "2020" / "md_2020_001.json").exists()
    row = _ledger_rows(ledger_path, "md_2020_001")[0]
    assert row["attempt_category"] == CATEGORY_PAID_REJECTED
    assert row["validation_status"] == "INVALID_TIMESTAMP"


def test_paid_2xx_snapshot_not_pregame_preserved_and_rejected(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    # timestamp == earliest kickoff -> not strictly pregame
    resp = FakeResp(
        status=200,
        headers={"x-requests-last": "30"},
        content=json.dumps({"timestamp": "2020-01-01T18:00:00Z"}).encode(),
    )
    with pytest.raises(PregameViolation):
        run_plan(
            _one_row_plan(), execute=True, api_key=FAKE_KEY,
            raw_root=raw_root, ledger_path=ledger_path, session=FakeSession(resp),
        )
    assert (raw_root / "2020" / "md_2020_001.json").exists()
    row = _ledger_rows(ledger_path, "md_2020_001")[0]
    assert row["attempt_category"] == CATEGORY_PAID_REJECTED
    assert row["validation_status"] == "SNAPSHOT_NOT_PREGAME"


def test_valid_2xx_is_verified_success_and_immutable(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    resp = _ok_200()
    result = run_plan(
        _one_row_plan(), execute=True, api_key=FAKE_KEY,
        raw_root=raw_root, ledger_path=ledger_path, session=FakeSession(resp),
    )
    assert result["executed"] == 1
    raw_file = raw_root / "2020" / "md_2020_001.json"
    assert raw_file.exists()
    row = _ledger_rows(ledger_path, "md_2020_001")[0]
    assert row["attempt_category"] == CATEGORY_VERIFIED_SUCCESS
    assert row["success"] is True
    assert row["validation_status"] == "PASS"
    assert row["response_content_sha256"] is not None


def test_non_2xx_stops_no_retry_no_paid_snapshot(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    resp = FakeResp(status=429, headers={}, content=b"{}")
    session = FakeSession(resp)
    with pytest.raises(AcquisitionStop):
        run_plan(
            _one_row_plan(), execute=True, api_key=FAKE_KEY,
            raw_root=raw_root, ledger_path=ledger_path, session=session,
        )
    assert session.calls == 1  # no retry
    assert not (raw_root / "2020" / "md_2020_001.json").exists()  # no paid snapshot
    row = _ledger_rows(ledger_path, "md_2020_001")[0]
    assert row["attempt_category"] == CATEGORY_REQUEST_FAILED


# --- resume / idempotency ---------------------------------------------------

def test_resume_skips_verified_success_ids(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    resp = _ok_200()
    run_plan(
        _one_row_plan(), execute=True, api_key=FAKE_KEY,
        raw_root=raw_root, ledger_path=ledger_path, session=FakeSession(resp),
    )
    fresh = FakeSession(resp)
    result = run_plan(
        _one_row_plan(), execute=True, api_key=FAKE_KEY,
        raw_root=raw_root, ledger_path=ledger_path, session=fresh,
    )
    assert fresh.calls == 0
    assert result["executed"] == 0
    assert result["skipped_completed"] == 1


# --- single acquisition worker (exclusive lock) -----------------------------

def test_second_concurrent_worker_blocked_before_http(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    plan = pl.read_parquet(REAL_PLAN)
    lock_dir = tmp_path / "lock"
    with acquisition_lock(lock_dir, kind="holder", lock_timeout_seconds=0.0):
        session = FakeSession(RuntimeError("must not hit the net"))
        with pytest.raises(LockFailure):
            run_live_acquisition(
                plan, plan_path=REAL_PLAN, api_key=FAKE_KEY,
                raw_root=raw_root, ledger_path=ledger_path,
                lock_dir=lock_dir, session=session,
            )
    assert session.calls == 0  # blocked before HTTP


# --- runtime plan contract (validated before network) -----------------------

def test_mutated_plan_with_576_rows_blocked_before_http(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    plan = pl.read_parquet(REAL_PLAN)
    # Duplicate one row to make 576 rows while keeping structure otherwise.
    extra = plan.slice(0, 1).with_columns(pl.lit("md_x_999").alias("request_plan_id"))
    bad = pl.concat([plan, extra])
    session = FakeSession(RuntimeError("must not hit the net"))
    with pytest.raises(PlanContractError):
        run_live_acquisition(
            bad, plan_path=REAL_PLAN, api_key=FAKE_KEY,
            raw_root=raw_root, ledger_path=ledger_path, session=session,
        )
    assert session.calls == 0


def test_wrong_plan_sha256_blocked_before_http(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    plan = pl.read_parquet(REAL_PLAN)
    # Same rows but a mutated cell -> valid structure, different SHA.
    mutated = plan.with_columns(
        pl.when(pl.col("request_plan_id") == "md_2020_001")
        .then(pl.lit("2020-09-10T23:19:00Z"))
        .otherwise(pl.col("requested_target_timestamp_utc"))
        .alias("requested_target_timestamp_utc")
    )
    mutated_path = tmp_path / "mutated_plan.parquet"
    mutated.write_parquet(mutated_path)
    session = FakeSession(RuntimeError("must not hit the net"))
    with pytest.raises(PlanContractError):
        run_live_acquisition(
            mutated, plan_path=mutated_path, api_key=FAKE_KEY,
            raw_root=raw_root, ledger_path=ledger_path, session=session,
        )
    assert session.calls == 0


def test_2025_row_blocked_before_http(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    plan = pl.read_parquet(REAL_PLAN)
    bad = plan.with_columns(
        pl.when(pl.col("request_plan_id") == "md_2020_001")
        .then(pl.lit(2025))
        .otherwise(pl.col("season"))
        .alias("season")
    )
    bad_path = tmp_path / "leak_plan.parquet"
    bad.write_parquet(bad_path)
    session = FakeSession(RuntimeError("must not hit the net"))
    with pytest.raises(PlanContractError):
        run_live_acquisition(
            bad, plan_path=bad_path, api_key=FAKE_KEY,
            raw_root=raw_root, ledger_path=ledger_path, session=session,
        )
    assert session.calls == 0


# --- secret safety / env enumeration ----------------------------------------

def test_redact_url_removes_api_key():
    url = "https://api.the-odds-api.com/v4/historical/sports/americanfootball_nfl/odds/?apiKey=SECRET&markets=h2h"
    red = redact_url(url)
    assert "SECRET" not in red
    assert "apiKey=REDACTED" in red


def test_success_writes_raw_and_ledger_without_secret(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    resp = FakeResp(
        status=200,
        headers={"x-requests-last": "30", "x-requests-used": "30", "x-requests-remaining": "99730"},
        content=json.dumps(
            {"timestamp": "2020-01-01T16:59:00Z", "previous_timestamp": None, "next_timestamp": None}
        ).encode(),
    )
    run_plan(
        _one_row_plan(), execute=True, api_key=FAKE_KEY,
        raw_root=raw_root, ledger_path=ledger_path, session=FakeSession(resp),
    )
    ledger_text = ledger_path.read_bytes()
    raw_text = (raw_root / "2020" / "md_2020_001.json").read_bytes()
    assert FAKE_KEY.encode() not in ledger_text
    assert FAKE_KEY.encode() not in raw_text
    assert b"apiKey=" not in ledger_text


def test_runner_source_never_enumerates_environment(tmp_path):
    src = Path(runner.__file__).read_text()
    assert "os.environ" not in src
    assert "environ.items" not in src


def test_cli_reads_only_exact_single_secret():
    script = (REPO_ROOT / "scripts" / "run_historical_market_acquisition.py").read_text()
    assert "os.environ.get" in script
    assert ODDS_API_KEY_ENV in script
    assert "os.environ.items" not in script
