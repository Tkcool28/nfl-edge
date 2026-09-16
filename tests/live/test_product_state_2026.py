from __future__ import annotations

import json
from types import SimpleNamespace

import polars as pl
import pytest

from nfl_edge.live import product_state_2026 as product_state
from nfl_edge.live.product_state_2026 import (
    Entering2026ProductStateError,
    advance_live_value_state,
)
from nfl_edge.recommendation.final_selectors_v1 import ValueSelectorState


def _selector_row(
    *,
    market: str,
    game_id: str,
    week: int = 2,
    side: str = "home",
    value: bool = True,
    model_q: float = 0.62,
    edge: float = 0.10,
    gap: float = 0.05,
    margin: float = 2.0,
) -> dict[str, object]:
    return {
        "candidate_id": f"{game_id}|{market}|{side}",
        "game_id": game_id,
        "season": 2026,
        "week": week,
        "market_type": market,
        "selected_side": side,
        "sportsbook": "draftkings",
        "line": None if market == "moneyline" else -2.5,
        "american_odds": -110,
        "supported": True,
        "reliability": "HIGH",
        "model_confidence_supported": True,
        "model_confidence_support_n": 512,
        "model_confidence_probability": model_q,
        "pinnacle_anchor_probability": 0.58,
        "break_even_probability": 0.52,
        "expected_value": 0.08 if value else -0.01,
        "evaluated_edge_probability": edge,
        "price_status": "VALUE" if value else "NO_VALUE",
        "model_candidate_regions": (
            "ML_DOG_VALUE_ZONE_AVG"
            if market == "moneyline"
            else "SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4"
        ),
        "model_price_gap": gap,
        "model_cover_margin_v3": margin,
    }


def _write_proof(
    root,
    *,
    name: str,
    captured_at: str,
    games: list[dict[str, str]],
    rows: list[dict[str, object]],
    week: int = 2,
    outcome: str = "SUCCESS",
) -> None:
    run = root / name
    (run / "product").mkdir(parents=True)
    (run / "run-status.json").write_text(json.dumps({"outcome": outcome}), encoding="utf-8")
    (run / "product" / "deterministic-proof.json").write_text(
        json.dumps(
            {
                "selector_evidence": {
                    "schema_version": "NFL_EDGE_LIVE_SELECTOR_EVIDENCE_V1",
                    "season": 2026,
                    "week": week,
                    "captured_at_utc": captured_at,
                    "games": games,
                    "rows": rows,
                }
            }
        ),
        encoding="utf-8",
    )


def _evidence(*, through_week: int, games: list[dict[str, object]]):
    return SimpleNamespace(through_week=through_week, games=pl.DataFrame(games))


def test_week2_starts_selector_trust_reset_without_week1_backfill(tmp_path):
    evidence = _evidence(
        through_week=1,
        games=[{"game_id": "2026_01_A_B", "home_score": 24, "away_score": 17}],
    )

    state = advance_live_value_state(
        entering=ValueSelectorState(),
        evidence=evidence,
        run_root=tmp_path,
        repository_root=tmp_path,
    )

    assert state == ValueSelectorState()


def test_final_pregame_rows_are_chosen_per_game_not_by_global_week_cutoff(tmp_path):
    games = [
        {"game_id": "2026_02_A_B", "kickoff_at_utc": "2026-09-18T00:15:00Z"},
        {"game_id": "2026_02_C_D", "kickoff_at_utc": "2026-09-20T17:00:00Z"},
    ]

    _write_proof(
        tmp_path,
        name="tue",
        captured_at="2026-09-16T12:00:00Z",
        games=games,
        rows=[
            _selector_row(market="moneyline", game_id="2026_02_A_B", gap=0.04),
            _selector_row(market="moneyline", game_id="2026_02_C_D", gap=0.03),
        ],
    )
    _write_proof(
        tmp_path,
        name="thu-final-a",
        captured_at="2026-09-17T23:00:00Z",
        games=games,
        rows=[
            _selector_row(market="moneyline", game_id="2026_02_A_B", side="away", gap=0.06),
            _selector_row(market="moneyline", game_id="2026_02_C_D", gap=0.05),
        ],
    )
    _write_proof(
        tmp_path,
        name="sun-final-b",
        captured_at="2026-09-20T16:00:00Z",
        games=games,
        rows=[
            # This post-kickoff A row must never overwrite A's Thursday-final state.
            _selector_row(market="moneyline", game_id="2026_02_A_B", side="home", gap=0.20),
            _selector_row(market="moneyline", game_id="2026_02_C_D", side="away", gap=0.07),
        ],
    )

    rows = product_state._final_pregame_selector_rows(
        run_root=tmp_path,
        week=2,
        required_game_ids={"2026_02_A_B", "2026_02_C_D"},
    )
    by_game = {str(row["game_id"]): row for row in rows}

    assert by_game["2026_02_A_B"]["selected_side"] == "away"
    assert by_game["2026_02_A_B"]["model_price_gap"] == 0.06
    assert by_game["2026_02_C_D"]["selected_side"] == "away"
    assert by_game["2026_02_C_D"]["model_price_gap"] == 0.07


def test_pick_that_disappears_before_kickoff_is_not_graded(tmp_path):
    games = [{"game_id": "2026_02_A_B", "kickoff_at_utc": "2026-09-20T17:00:00Z"}]

    _write_proof(
        tmp_path,
        name="early",
        captured_at="2026-09-18T12:00:00Z",
        games=games,
        rows=[_selector_row(market="moneyline", game_id="2026_02_A_B")],
    )
    _write_proof(
        tmp_path,
        name="final",
        captured_at="2026-09-20T16:00:00Z",
        games=games,
        rows=[
            # The offer still exists on the evaluator board, but it is no longer
            # a Value candidate. The earlier Value state must not be graded.
            _selector_row(
                market="moneyline",
                game_id="2026_02_A_B",
                value=False,
            )
        ],
    )

    rows = product_state._final_pregame_selector_rows(
        run_root=tmp_path,
        week=2,
        required_game_ids={"2026_02_A_B"},
    )
    assert len(rows) == 1
    assert rows[0]["price_status"] == "NO_VALUE"

    state = advance_live_value_state(
        entering=ValueSelectorState(),
        evidence=_evidence(
            through_week=2,
            games=[{"game_id": "2026_02_A_B", "home_score": 24, "away_score": 17}],
        ),
        run_root=tmp_path,
    )
    assert state.ml_observations == ()


def test_selector_trust_advances_from_week2_final_game_states_only(tmp_path):
    games = [
        {"game_id": "2026_02_A_B", "kickoff_at_utc": "2026-09-18T00:15:00Z"},
        {"game_id": "2026_02_C_D", "kickoff_at_utc": "2026-09-20T17:00:00Z"},
    ]

    _write_proof(
        tmp_path,
        name="thu-final",
        captured_at="2026-09-17T23:00:00Z",
        games=games,
        rows=[
            _selector_row(market="moneyline", game_id="2026_02_A_B", gap=0.06),
            _selector_row(market="spread", game_id="2026_02_A_B", margin=2.0),
            _selector_row(market="moneyline", game_id="2026_02_C_D", gap=0.03),
            _selector_row(market="spread", game_id="2026_02_C_D", margin=1.0),
        ],
    )
    _write_proof(
        tmp_path,
        name="sun-final",
        captured_at="2026-09-20T16:00:00Z",
        games=games,
        rows=[
            _selector_row(market="moneyline", game_id="2026_02_C_D", gap=0.08),
            _selector_row(market="spread", game_id="2026_02_C_D", margin=3.0),
        ],
    )

    evidence = _evidence(
        through_week=2,
        games=[
            {"game_id": "2026_01_X_Y", "home_score": 20, "away_score": 17},
            {"game_id": "2026_02_A_B", "home_score": 24, "away_score": 17},
            {"game_id": "2026_02_C_D", "home_score": 28, "away_score": 14},
        ],
    )

    state = advance_live_value_state(
        entering=ValueSelectorState(),
        evidence=evidence,
        run_root=tmp_path,
    )

    assert len(state.ml_observations) == 1
    assert len(state.spread_observations) == 1
    assert state.ml_observations[0].realized_edge > 0
    assert state.spread_observations[0].realized_edge > 0


def test_week2_selector_trust_requires_native_final_pregame_coverage_for_every_settled_game(tmp_path):
    games = [
        {"game_id": "2026_02_A_B", "kickoff_at_utc": "2026-09-18T00:15:00Z"},
        {"game_id": "2026_02_C_D", "kickoff_at_utc": "2026-09-20T17:00:00Z"},
    ]
    _write_proof(
        tmp_path,
        name="partial",
        captured_at="2026-09-17T23:00:00Z",
        games=[games[0]],
        rows=[_selector_row(market="moneyline", game_id="2026_02_A_B")],
    )
    evidence = _evidence(
        through_week=2,
        games=[
            {"game_id": "2026_02_A_B", "home_score": 24, "away_score": 17},
            {"game_id": "2026_02_C_D", "home_score": 28, "away_score": 14},
        ],
    )

    with pytest.raises(Entering2026ProductStateError, match="2026_02_C_D"):
        advance_live_value_state(
            entering=ValueSelectorState(),
            evidence=evidence,
            run_root=tmp_path,
        )


def test_unsuccessful_refresh_does_not_replace_last_successful_pregame_state(tmp_path):
    games = [{"game_id": "2026_02_A_B", "kickoff_at_utc": "2026-09-20T17:00:00Z"}]
    _write_proof(
        tmp_path,
        name="good",
        captured_at="2026-09-20T15:00:00Z",
        games=games,
        rows=[_selector_row(market="moneyline", game_id="2026_02_A_B", side="away")],
    )
    _write_proof(
        tmp_path,
        name="failed",
        captured_at="2026-09-20T16:00:00Z",
        games=games,
        rows=[_selector_row(market="moneyline", game_id="2026_02_A_B", side="home")],
        outcome="MATERIALIZATION_FAILED",
    )

    rows = product_state._final_pregame_selector_rows(
        run_root=tmp_path,
        week=2,
        required_game_ids={"2026_02_A_B"},
    )
    assert len(rows) == 1
    assert rows[0]["selected_side"] == "away"
