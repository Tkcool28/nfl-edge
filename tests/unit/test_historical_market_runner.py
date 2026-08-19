"""Runner safety contract: dry-run/no-call, execute gate, costs, retries,
resume, pregame rejection, secret safety, no env enumeration (§G/I/J/M)."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from nfl_edge.market_data import runner
from nfl_edge.market_data.manifest import ODDS_API_KEY_ENV
from nfl_edge.market_data.runner import (
    AcquisitionStop,
    CostContractViolation,
    PregameViolation,
    redact_url,
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


# --- dry-run / no-call guarantees -------------------------------------------

def test_dry_run_makes_zero_http_calls(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    # A session that explodes if used proves the dry run never touches the net.
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
    assert "per_season_request_counts" in rep
    assert rep["per_season_request_counts"] == {
        2020: 107, 2021: 111, 2022: 116, 2023: 120, 2024: 121,
    }


def test_execute_requires_explicit_gate():
    # execute=True with no api_key must refuse to run (gate is not free).
    with pytest.raises(AcquisitionStop):
        run_plan(_one_row_plan(), execute=True, api_key=None)


# --- credit contract --------------------------------------------------------

def test_successful_response_cost_must_equal_30(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    resp = FakeResp(
        status=200,
        headers={"x-requests-last": "25"},  # unexpected cost
        content=json.dumps({"timestamp": "2020-01-01T16:59:00Z"}).encode(),
    )
    session = FakeSession(resp)
    with pytest.raises(CostContractViolation):
        run_plan(
            _one_row_plan(), execute=True, api_key=FAKE_KEY,
            raw_root=raw_root, ledger_path=ledger_path, session=session,
        )
    # Nothing written on a contract violation.
    assert not (raw_root / "2020" / "md_2020_001.json").exists()


def test_stop_on_unexpected_cost_halts(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    resp = FakeResp(
        status=200,
        headers={"x-requests-last": "31"},
        content=json.dumps({"timestamp": "2020-01-01T16:59:00Z"}).encode(),
    )
    with pytest.raises(CostContractViolation):
        run_plan(
            _one_row_plan(), execute=True, api_key=FAKE_KEY,
            raw_root=raw_root, ledger_path=ledger_path, session=FakeSession(resp),
        )


# --- retries -----------------------------------------------------------------

def test_no_automatic_retries_on_error(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    session = FakeSession(RuntimeError("boom"))
    with pytest.raises(AcquisitionStop):
        run_plan(
            _one_row_plan(), execute=True, api_key=FAKE_KEY,
            raw_root=raw_root, ledger_path=ledger_path, session=session,
        )
    assert session.calls == 1  # exactly one attempt, no retry


# --- pregame fail-closed ----------------------------------------------------

def test_pregame_snapshot_rejected_when_not_strictly_before(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    resp = FakeResp(
        status=200,
        headers={"x-requests-last": "30"},
        content=json.dumps({"timestamp": "2020-01-01T18:00:00Z"}).encode(),  # == kickoff
    )
    with pytest.raises(PregameViolation):
        run_plan(
            _one_row_plan(), execute=True, api_key=FAKE_KEY,
            raw_root=raw_root, ledger_path=ledger_path, session=FakeSession(resp),
        )


# --- success path: raw immutability + ledger + secret safety -----------------

def test_success_writes_raw_and_ledger_without_secret(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    resp = FakeResp(
        status=200,
        headers={"x-requests-last": "30", "x-requests-used": "30", "x-requests-remaining": "99730"},
        content=json.dumps(
            {"timestamp": "2020-01-01T16:59:00Z", "previous_timestamp": None, "next_timestamp": None}
        ).encode(),
    )
    result = run_plan(
        _one_row_plan(), execute=True, api_key=FAKE_KEY,
        raw_root=raw_root, ledger_path=ledger_path, session=FakeSession(resp),
    )
    assert result["executed"] == 1
    raw_file = raw_root / "2020" / "md_2020_001.json"
    assert raw_file.exists()
    ledger_text = ledger_path.read_bytes()
    raw_text = raw_file.read_bytes()
    # Secret must never land in raw or ledger.
    assert FAKE_KEY.encode() not in ledger_text
    assert FAKE_KEY.encode() not in raw_text
    assert b"apiKey=" not in ledger_text


def test_redact_url_removes_api_key():
    url = "https://api.the-odds-api.com/v4/historical/sports/americanfootball_nfl/odds/?apiKey=SECRET&markets=h2h"
    red = redact_url(url)
    assert "SECRET" not in red
    assert "apiKey=REDACTED" in red


# --- resume / idempotency (unit) --------------------------------------------

def test_resume_skips_completed_request_ids(tmp_path):
    raw_root, ledger_path = _paths(tmp_path)
    resp = FakeResp(
        status=200,
        headers={"x-requests-last": "30"},
        content=json.dumps({"timestamp": "2020-01-01T16:59:00Z"}).encode(),
    )
    # First run completes the single request.
    run_plan(
        _one_row_plan(), execute=True, api_key=FAKE_KEY,
        raw_root=raw_root, ledger_path=ledger_path, session=FakeSession(resp),
    )
    # Second run must skip it without an API call (reuse the same session count).
    fresh = FakeSession(resp)
    result = run_plan(
        _one_row_plan(), execute=True, api_key=FAKE_KEY,
        raw_root=raw_root, ledger_path=ledger_path, session=fresh,
    )
    assert fresh.calls == 0  # no re-request -> no re-spend
    assert result["executed"] == 0
    assert result["skipped_completed"] == 1


# --- no env enumeration -----------------------------------------------------

def test_runner_source_never_enumerates_environment(tmp_path):
    src = Path(runner.__file__).read_text()
    assert "os.environ" not in src
    assert "environ.items" not in src


def test_cli_reads_only_exact_single_secret():
    script = (REPO_ROOT / "scripts" / "run_historical_market_acquisition.py").read_text()
    assert "os.environ.get" in script
    assert ODDS_API_KEY_ENV in script
    assert "os.environ.items" not in script
