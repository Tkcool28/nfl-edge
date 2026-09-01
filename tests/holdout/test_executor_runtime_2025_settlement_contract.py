"""Regression suite for the task05g v2 2025 settlement wager-side contract.

These tests pin down the exact schema mismatch that crashed the preserved
2025-frozen-eval-v1 run on Week 1 (KeyError: 'selected_side' inside
executor_runtime_2025._settlement). The frozen Task05G canonical candidate
surface is defined by ``nfl_edge.value.candidate_table.build_candidate_row``:

    selection               <- wager side
    actionable_line         <- spread / total line
    actionable_price_american  <- decimal-odds input to _unit_profit
    actionable_book         <- sportsbook identity (used only for ordering)

Pre-fix the executor read the legacy Task05F-era names
("selected_side" / "line" / "american_odds" / "sportsbook") which do NOT exist
on the canonical surface. The post-fix executor reads the canonical names,
matching every other layer (policy, staking, headline).

These tests:

* Assert pre-fix _settlement raises KeyError("selected_side") on the frozen
  Week 1 row shape (read straight from the preserved artifacts).
* Assert post-fix _settlement settles every market on the same row shape.
* Assert _settle_rows and _advance_bankroll operate end-to-end on rows that
  carry only the canonical fields.
* Assert a fully no-play week (unique_exposure empty, like the actual
  preserved Week 1) settles to zero wagers, zero profit, and produces no
  fake wager rows.
* Assert the post-fix CSV column lists align with the actual row keys.
* Do NOT modify selectors, staking, bankroll, product policy, methodology,
  or any frozen input data.

Run with::

    pytest tests/holdout/test_executor_runtime_2025_settlement_contract.py -q
"""
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_PATH = REPO_ROOT / "src/nfl_edge/holdout/executor_runtime_2025.py"
PRESERVED_RUN_DIR = (
    REPO_ROOT
    / "artifacts/task05g_2025_holdout_v2/2025-frozen-eval-v1"
)
PRESERVED_WEEK1 = PRESERVED_RUN_DIR / "weeks" / "2025_REG_W01"


# ---------------------------------------------------------------------------
# Module loading helpers (the executor script is invoked lazily by tests, so we
# load it as a regular module and exercise its helpers directly; this does not
# open any sealed 2025 input).
# ---------------------------------------------------------------------------


def _load_executor_module():
    spec = importlib.util.spec_from_file_location(
        "executor_runtime_2025_under_test", EXECUTOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _import_executor():
    """Import from the package (for tests that need package-relative symbols)."""
    from nfl_edge.holdout import executor_runtime_2025  # noqa: PLC0415

    return executor_runtime_2025


# ---------------------------------------------------------------------------
# Test fixtures: a canonical-shape row that mirrors the actual frozen Week 1
# candidate_table.json schema (selection / actionable_line / actionable_price /
# actionable_book), plus revealed-frame helpers.
# ---------------------------------------------------------------------------


def _canonical_row(
    *,
    market_type: str,
    selection: str,
    actionable_line: float | None,
    actionable_price_american: int,
    actionable_book: str,
    game_id: str,
    offer_key: str,
    current_units: float,
) -> dict[str, Any]:
    """Build a row that exactly matches the canonical Task05G surface.

    Intentionally does NOT carry the legacy fields ("selected_side", "line",
    "american_odds", "sportsbook") to prove the consumer side must read the
    canonical names.
    """
    return {
        "game_id": game_id,
        "market_type": market_type,
        "selection": selection,
        "actionable_line": actionable_line,
        "actionable_price_american": actionable_price_american,
        "actionable_book": actionable_book,
        "offer_key": offer_key,
        "current_units": current_units,
    }


def _revealed_frame(games: list[tuple[str, int, int]]) -> pl.DataFrame:
    """Build the revealed outcomes frame consumed by _settle_rows / _advance_bankroll."""
    return pl.DataFrame(
        {
            "game_id": [gid for gid, _, _ in games],
            "home_score": [h for _, h, _ in games],
            "away_score": [a for _, _, a in games],
        }
    )


# ---------------------------------------------------------------------------
# Pre-fix vs post-fix parity on the frozen Week 1 row shape.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def frozen_week1_candidate() -> dict[str, Any]:
    """First candidate row read straight from the preserved Week 1 candidate_table.

    This is the canonical Task05G surface that crashed the runtime with
    KeyError: 'selected_side'. We read it once, here, from disk so the test
    stays faithful to the real failure evidence (no synthetic shortcut).
    """
    path = PRESERVED_WEEK1 / "candidate_table.json"
    assert path.is_file(), f"preserved Week 1 candidate_table.json missing at {path}"
    table = json.loads(path.read_text())
    assert isinstance(table, list) and table, "candidate_table must be a non-empty list"
    first = dict(table[0])
    # Hard-assert the surface the producer actually emitted: the row MUST
    # carry the canonical keys and MUST NOT carry the legacy keys.
    assert "selection" in first, "frozen Week 1 candidate must carry canonical 'selection'"
    assert "actionable_price_american" in first
    assert "actionable_book" in first
    assert "market_type" in first
    assert "selected_side" not in first, (
        "if this ever fails, the producer surface changed; re-audit the contract"
    )
    assert "american_odds" not in first
    assert "sportsbook" not in first
    return first


@pytest.fixture(scope="module")
def executor_module():
    return _load_executor_module()


def _pre_fix_settlement_factory():
    """Re-construct the pre-fix _settlement function inline.

    The pre-fix code (still present on origin/main before this task's
    commit) looked like this::

        def _settlement(row, home, away):
            market, side = str(row["market_type"]), str(row["selected_side"])
            if market == "moneyline":
                return moneyline_settlement(side, home, away)
            if market == "spread":
                return spread_settlement(side, float(row["line"]), home, away)
            if market == "total":
                return total_settlement(side, float(row["line"]), home, away)
    """
    from nfl_edge.holdout.executor_runtime_2025 import (
        AuthorizedHoldoutRuntimeError,
        moneyline_settlement,
        spread_settlement,
        total_settlement,
    )

    def _settlement_pre_fix(row, home, away):
        market, side = str(row["market_type"]), str(row["selected_side"])
        if market == "moneyline":
            return moneyline_settlement(side, home, away)
        if market == "spread":
            return spread_settlement(side, float(row["line"]), home, away)
        if market == "total":
            return total_settlement(side, float(row["line"]), home, away)
        raise AuthorizedHoldoutRuntimeError(f"unknown market {market!r}")

    return _settlement_pre_fix


def test_pre_fix_settlement_raises_keyerror_on_frozen_week1_row(frozen_week1_candidate):
    """The exact KeyError the preserved 2025-frozen-eval-v1 run recorded."""
    pre_fix = _pre_fix_settlement_factory()
    home, away = 24, 17
    with pytest.raises(KeyError) as exc:
        pre_fix(frozen_week1_candidate, home, away)
    assert str(exc.value) == "'selected_side'", (
        "the 2025-frozen-eval-v1 failure recorded KeyError('selected_side'); "
        "this synthetic reproduction must match exactly"
    )


@pytest.mark.parametrize(
    ("market_type", "selection", "actionable_line", "home", "away", "expected"),
    [
        # moneyline
        ("moneyline", "home", None, 27, 14, "WIN"),
        ("moneyline", "home", None, 17, 24, "LOSS"),
        ("moneyline", "away", None, 24, 17, "LOSS"),
        # spread: side=home, line=-3.5 -> value = (home-away) + line
        ("spread", "home", -3.5, 27, 24, "LOSS"),  # 3 + (-3.5) = -0.5
        ("spread", "home", -3.5, 31, 24, "WIN"),  # 7 + (-3.5) = 3.5
        # spread PUSH: line=-3, scores 27-24 -> (3) + (-3) = 0
        ("spread", "home", -3.0, 27, 24, "PUSH"),
        # spread, side=away -> margin = (away-home) + line
        ("spread", "away", 3.0, 27, 24, "PUSH"),  # (24-27) + 3 = 0
        # total: over line=45.5
        ("total", "over", 45.5, 23, 22, "LOSS"),  # 45 - 45.5 = -0.5
        ("total", "under", 45.5, 23, 22, "WIN"),  # 45.5 - 45 = 0.5
        ("total", "over", 45.5, 28, 18, "WIN"),  # 46 - 45.5 = 0.5
        # total PUSH: line=45 with combined 45
        ("total", "over", 45.0, 22, 23, "PUSH"),  # 45 - 45 = 0
        ("total", "under", 45.0, 22, 23, "PUSH"),  # 45 - 45 = 0
    ],
)
def test_post_fix_settlement_handles_canonical_row(
    market_type, selection, actionable_line, home, away, expected, executor_module
):
    """Post-fix _settlement reads the canonical wager side, line, and price.

    Uses canonical-shape rows exclusively. Grading semantics (WIN / LOSS /
    PUSH, spread cover, totals cover, home/away resolution) must be unchanged.
    """
    row = _canonical_row(
        market_type=market_type,
        selection=selection,
        actionable_line=actionable_line,
        actionable_price_american=-110,
        actionable_book="fanduel",
        game_id="2025_01_BAL_BUF",
        offer_key=f"2025_01_BAL_BUF|{market_type}|{selection}|fanduel|{actionable_line}|-110",
        current_units=1.0,
    )
    settled = executor_module._settlement(row, home, away)
    assert settled.value == expected


def test_post_fix_settlement_raises_unknown_market_on_canonical_row(executor_module):
    """Post-fix still rejects unknown markets (no silent fallback)."""
    row = _canonical_row(
        market_type="prop",
        selection="home",
        actionable_line=None,
        actionable_price_american=-110,
        actionable_book="fanduel",
        game_id="2025_01_BAL_BUF",
        offer_key="k",
        current_units=0.0,
    )
    with pytest.raises(executor_module.AuthorizedHoldoutRuntimeError, match="unknown market"):
        executor_module._settlement(row, 24, 17)


# ---------------------------------------------------------------------------
# End-to-end settlement on canonical rows.
# ---------------------------------------------------------------------------


def test_settle_rows_runs_cleanly_on_canonical_rows(executor_module):
    """_settle_rows must not raise on the canonical Task05G surface."""
    rows = [
        _canonical_row(
            market_type="moneyline",
            selection="home",
            actionable_line=None,
            actionable_price_american=-150,
            actionable_book="draftkings",
            game_id="g_home_wins",
            offer_key="k1",
            current_units=1.0,
        ),
        _canonical_row(
            market_type="spread",
            selection="away",
            actionable_line=3.5,
            actionable_price_american=-110,
            actionable_book="fanduel",
            game_id="g_away_covers",
            offer_key="k2",
            current_units=1.0,
        ),
    ]
    revealed = _revealed_frame([("g_home_wins", 24, 17), ("g_away_covers", 17, 24)])
    settled = executor_module._settle_rows(rows, revealed)
    assert [r["settlement"] for r in settled] == ["WIN", "WIN"]
    assert [r["realized_profit"] for r in settled] == pytest.approx(
        [executor_module.american_to_decimal(-150) - 1.0, executor_module.american_to_decimal(-110) - 1.0]
    )
    # Producer-facing settle_rows must NOT add fields it does not own. It must
    # only add settlement + realized_profit on top of the canonical row.
    for row in settled:
        assert "selected_side" not in row
        assert "american_odds" not in row


# ---------------------------------------------------------------------------
# _advance_bankroll: most failure-prone of the three (only path that runs over
# unique_exposure). Cover both empty-exposure (no-play week) and populated
# exposure (a real wager).
# ---------------------------------------------------------------------------


def test_advance_bankroll_handles_empty_unique_exposure(executor_module):
    """The actual Week 1 user_view reported unique_exposure_count=0.

    _advance_bankroll must complete cleanly on empty exposure without
    inserting any fake wager rows.
    """
    revealed = _revealed_frame([("g_a", 24, 17), ("g_b", 17, 24)])
    bankroll = executor_module.BankrollState(
        values={"Cautious": 1000.0, "Conservative": 1000.0, "Normal": 1000.0, "Aggressive": 1000.0, "Ultra": 1000.0},
        peaks={"Cautious": 1000.0, "Conservative": 1000.0, "Normal": 1000.0, "Aggressive": 1000.0, "Ultra": 1000.0},
        max_drawdowns={"Cautious": 0.0, "Conservative": 0.0, "Normal": 0.0, "Aggressive": 0.0, "Ultra": 0.0},
    )
    next_bankroll, scenario_rows, record, weighted, streak, longest = executor_module._advance_bankroll(
        bankroll, [], revealed, entering_streak=0
    )
    assert scenario_rows == [], (
        "empty exposure must produce zero scenario rows; no fake wagers allowed"
    )
    assert record == {"wins": 0, "losses": 0, "pushes": 0}
    assert weighted == 0.0
    assert streak == 0 and longest == 0
    # Bankroll values untouched.
    for name in next_bankroll.values:
        assert next_bankroll.values[name] == 1000.0


def test_advance_bankroll_on_canonical_exposure_unaffected(executor_module):
    """A real canonical wager settles to LOSS (away ML, home wins).

    Specifically, home_score=24, away_score=17 means the away side LOST (LOSS
    not WIN). The grading semantics — decimal-odds unit profit, weighted sum,
    record counter — are unchanged from the pre-fix code path.
    """
    revealed = _revealed_frame([("2025_01_CAR_JAX", 24, 17)])
    bankroll = executor_module.BankrollState(
        values={"Cautious": 1000.0, "Conservative": 1000.0, "Normal": 1000.0, "Aggressive": 1000.0, "Ultra": 1000.0},
        peaks={"Cautious": 1000.0, "Conservative": 1000.0, "Normal": 1000.0, "Aggressive": 1000.0, "Ultra": 1000.0},
        max_drawdowns={"Cautious": 0.0, "Conservative": 0.0, "Normal": 0.0, "Aggressive": 0.0, "Ultra": 0.0},
    )
    exposure = [
        _canonical_row(
            market_type="moneyline",
            selection="away",
            actionable_line=None,
            actionable_price_american=100,  # +100 -> decimal 2.0; WIN +1.0, LOSS -1.0
            actionable_book="draftkings",
            game_id="2025_01_CAR_JAX",
            offer_key="2025_01_CAR_JAX|moneyline|away|draftkings||100",
            current_units=1.0,
        )
    ]
    next_bankroll, scenario_rows, record, weighted, streak, longest = executor_module._advance_bankroll(
        bankroll, exposure, revealed, entering_streak=0
    )
    # Real LOSS — home wins, away selected -> LOSS.
    assert record == {"wins": 0, "losses": 1, "pushes": 0}
    assert weighted == pytest.approx(-1.0)
    # LOSS increments losing streak from 0 -> 1.
    assert streak == 1 and longest == 1
    # Every scenario row carries the canonical columns.
    assert scenario_rows, "real wager must produce a scenario row"
    for row in scenario_rows:
        assert "selection" in row and "actionable_price_american" in row
        assert "selected_side" not in row and "american_odds" not in row
        assert row["settlement"] in {"WIN", "LOSS", "PUSH"}
        assert row["market_type"] == "moneyline"
        assert row["selection"] == "away"
        assert row["actionable_price_american"] == 100
        assert row["actionable_line"] is None  # moneyline -> None


# ---------------------------------------------------------------------------
# Output CSV column lists must match the canonical surface so the writer
# doesn't emit empty columns. We do not exercise _final_outputs end-to-end
# (that would require the full holdout environment); we instead assert the
# exact column lists used inside it.
# ---------------------------------------------------------------------------


def test_holdout_headline_cards_csv_columns_are_canonical(executor_module):
    source = EXECUTOR_PATH.read_text()
    headlines_region = source.split("holdout_headline_cards.csv", 1)[1].split(
        "holdout_weekly_summary.csv", 1
    )[0]
    assert '"selected_side"' not in headlines_region
    assert '"sportsbook"' not in headlines_region
    assert '"selection"' in headlines_region
    assert '"actionable_book"' in headlines_region
    assert '"actionable_line"' in headlines_region
    assert '"actionable_price_american"' in headlines_region


def test_holdout_scenario_ledger_csv_columns_are_canonical(executor_module):
    source = EXECUTOR_PATH.read_text()
    region = source.split("holdout_scenario_ledger.csv", 1)[1].split("integrity", 1)[0]
    assert '"selected_side"' not in region
    assert '"american_odds"' not in region
    assert '"line"' not in region.split(",")[:9]  # 'line' must not appear among the first 9 columns
    assert '"selection"' in region
    assert '"actionable_price_american"' in region
    assert '"actionable_line"' in region


def test_csv_writer_emits_canonical_columns_for_no_play(executor_module, tmp_path: Path):
    """A NO_PLAY headline carries only the canonical fields; the writer must
    not silently drop them onto legacy column names."""
    out = tmp_path / "headline.csv"
    canonical_headline_row = {
        "block_id": "2025_REG_W01",
        "season_type": "REG",
        "week": 1,
        "lane": "hit_rate",
        "headline_action": "NO_PLAY",
        "published": False,
        "current_units": 0.0,
        "game_id": None,
        "market_type": None,
        "selection": None,
        "actionable_book": None,
        "actionable_line": None,
        "actionable_price_american": None,
        "value_at_price_american": None,
        "offer_key": None,
    }
    executor_module._csv(
        out,
        [canonical_headline_row],
        [
            "block_id", "season_type", "week", "lane", "headline_action",
            "published", "current_units", "game_id", "market_type",
            "selection", "actionable_book", "actionable_line",
            "actionable_price_american", "value_at_price_american", "offer_key",
        ],
    )
    with out.open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["headline_action"] == "NO_PLAY"
    assert rows[0]["selection"] in (None, "")
    # No legacy columns present:
    assert "selected_side" not in rows[0]
    assert "american_odds" not in rows[0]


# ---------------------------------------------------------------------------
# Preserved-failure evidence sanity-check: the artifacts directory must NOT
# have been mutated by the test suite.
# ---------------------------------------------------------------------------


def test_preserved_failed_run_artifacts_untouched():
    """The fix must not modify the preserved 2025-frozen-eval-v1 artifacts."""
    for name in (
        "RUN_FAILED.json",
        "RUN_STARTED.json",
        "RUN_TERMINAL.json",
        "RUN_INPUT_VERIFICATION.json",
        "weeks/2025_REG_W01/candidate_table.json",
        "weeks/2025_REG_W01/headline_card.json",
        "weeks/2025_REG_W01/model_output.json",
        "weeks/2025_REG_W01/pre_result_manifest.json",
        "weeks/2025_REG_W01/pre_result_user_view.json",
    ):
        path = PRESERVED_RUN_DIR / name
        assert path.is_file(), f"preserved artifact missing: {path}"
    failed = json.loads((PRESERVED_RUN_DIR / "RUN_FAILED.json").read_text())
    assert failed.get("status") == "RUN_FAILED"
    assert failed["failure"]["type"] == "KeyError"
    assert failed["failure"]["message"] == "'selected_side'", (
        "preserved-failure evidence should still record the exact KeyError('selected_side') "
        "the new test fixes"
    )
