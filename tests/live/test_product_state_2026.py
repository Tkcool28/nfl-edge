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


@pytest.fixture
def week9_gap_history(tmp_path, monkeypatch):
    import hashlib

    games = []
    for week in range(2, 9):
        gid = f"2026_{week:02}_A_B"
        games.append(dict(game_id=gid, season=2026, season_type="REG", week=week, home_score=24, away_score=17))
        rows = [_selector_row(market="spread", game_id=gid, week=week)]
        if week == 2:
            rows.append(_selector_row(market="moneyline", game_id=gid, week=week))
        _write_proof(
            tmp_path, name=f"week{week}", week=week, captured_at="2026-09-01T00:00:00Z",
            games=[{"game_id": gid, "kickoff_at_utc": "2026-11-01T00:00:00Z"}], rows=rows,
        )
    for gid in sorted(product_state._WEEK9_GAME_IDS):
        games.append(dict(game_id=gid, season=2026, season_type="REG", week=9, home_score=24, away_score=17))
    failed_run = tmp_path / "week9-reviewed-failure"
    failed_run.mkdir()
    status = failed_run / "run-status.json"
    status.write_text(json.dumps({"outcome": "MARKET_ACQUISITION_FAILED", "week": 9}))
    monkeypatch.setattr(
        product_state, "_WEEK9_FAILED_STATUS_SHA256", {failed_run.name: hashlib.sha256(status.read_bytes()).hexdigest()}
    )
    evidence = _evidence(through_week=9, games=games)
    evidence.manifest = {"season": 2026, "schedule_checkpoints": {"9": product_state._WEEK9_CHECKPOINT}}
    return evidence, status


def test_week9_gap_carries_the_exact_week8_state_and_emits_deterministic_audit(tmp_path, week9_gap_history):
    evidence, _ = week9_gap_history
    entering = ValueSelectorState()
    week8 = advance_live_value_state(
        entering=entering, evidence=_evidence(through_week=8, games=evidence.games.to_dicts()), run_root=tmp_path,
    )
    assert (len(week8.ml_observations), len(week8.spread_observations)) == (1, 7)
    results = []
    for _ in range(2):
        audit = []
        state = advance_live_value_state(entering=entering, evidence=evidence, run_root=tmp_path, recovery_audit=audit)
        assert state == week8
        results.append(audit)
    assert results[0] == results[1]
    record, = results[0]
    assert record["reason"] == "NO_AUTHENTIC_PREGAME_MARKET_OBSERVATION"
    assert len(record["settled_game_ids"]) == 15
    assert record["accepted_pregame_games"] == 0
    assert record["observations_appended"] == {"moneyline": 0, "spread": 0}
    assert record["selector_state_before_sha256"] == record["selector_state_after_sha256"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("missing_status", "outage status missing or changed"),
        ("changed_status", "outage status missing or changed"),
        ("market_artifact", "acquisition artifacts require review"),
        ("foreign_season", "mismatched settled evidence"),
        ("foreign_game", "mismatched settled evidence"),
        ("foreign_week", "mismatched settled evidence"),
        ("wrong_season_type", "mismatched settled evidence"),
        ("wrong_checkpoint", "mismatched settled evidence"),
        ("missing_week8", "settled Week 8"),
        ("unreviewed_status", "unreviewed Week 9"),
    ],
)
def test_week9_gap_fails_closed_when_evidence_changes(tmp_path, week9_gap_history, change, message):
    evidence, status = week9_gap_history
    gid = min(product_state._WEEK9_GAME_IDS)
    if change == "missing_status":
        status.unlink()
    elif change == "changed_status":
        status.write_text("{}")
    elif change == "market_artifact":
        (status.parent / "market").mkdir()
    elif change == "foreign_season":
        evidence.manifest["season"] = 2025
    elif change in {"foreign_game", "foreign_week", "wrong_season_type"}:
        changes = {
            "foreign_game": {"game_id": "2026_09_X_Y"},
            "foreign_week": {"week": 10},
            "wrong_season_type": {"season_type": "POST"},
        }
        evidence.games = pl.DataFrame([
            {**row, **changes[change]} if row["game_id"] == gid else row for row in evidence.games.to_dicts()
        ])
    elif change == "wrong_checkpoint":
        evidence.manifest["schedule_checkpoints"]["9"] = "f" * 64
    elif change == "missing_week8":
        (tmp_path / "week8/product/deterministic-proof.json").unlink()
    else:
        run = tmp_path / "unknown"
        run.mkdir()
        (run / "run-status.json").write_text('{"week":9,"outcome":"SUCCESS"}')
    with pytest.raises(Entering2026ProductStateError, match=message):
        advance_live_value_state(entering=ValueSelectorState(), evidence=evidence, run_root=tmp_path)


@pytest.mark.parametrize(
    ("outcome", "message"),
    [("SUCCESS", "partial Week 9 selector coverage"), ("MATERIALIZATION_FAILED", "selector proof requires review")],
)
def test_week9_gap_does_not_hide_partial_or_conflicting_records(tmp_path, week9_gap_history, outcome, message):
    evidence, _ = week9_gap_history
    gid = min(product_state._WEEK9_GAME_IDS)
    _write_proof(
        tmp_path, name="week9-surviving-record", captured_at="2026-11-04T00:00:00Z", week=9,
        games=[{"game_id": gid, "kickoff_at_utc": "2026-11-09T00:00:00Z"}],
        rows=[_selector_row(market="moneyline", game_id=gid, week=9)], outcome=outcome,
    )
    with pytest.raises(Entering2026ProductStateError, match=message):
        advance_live_value_state(entering=ValueSelectorState(), evidence=evidence, run_root=tmp_path)


def test_complete_week9_native_coverage_takes_the_normal_path(tmp_path, week9_gap_history):
    evidence, status = week9_gap_history
    status.unlink()
    gids = sorted(product_state._WEEK9_GAME_IDS)
    _write_proof(
        tmp_path, name="week9-complete", week=9, captured_at="2026-11-04T00:00:00Z",
        games=[{"game_id": gid, "kickoff_at_utc": "2026-11-09T00:00:00Z"} for gid in gids],
        rows=[_selector_row(market="moneyline", game_id=gids[0], week=9)],
    )
    audit = []
    state = advance_live_value_state(
        entering=ValueSelectorState(), evidence=evidence, run_root=tmp_path, recovery_audit=audit,
    )
    assert len(state.ml_observations) == 2
    assert audit == []


def test_week_after_gap_still_requires_and_advances_native_evidence(tmp_path, week9_gap_history):
    week9, _ = week9_gap_history
    gid = "2026_10_A_B"
    evidence = _evidence(
        through_week=10,
        games=[*week9.games.to_dicts(), dict(
            game_id=gid, season=2026, season_type="REG", week=10, home_score=24, away_score=17,
        )],
    )
    evidence.manifest = week9.manifest
    with pytest.raises(Entering2026ProductStateError, match="settled Week 10"):
        advance_live_value_state(entering=ValueSelectorState(), evidence=evidence, run_root=tmp_path)
    _write_proof(
        tmp_path, name="week10", week=10, captured_at="2026-11-12T00:00:00Z",
        games=[{"game_id": gid, "kickoff_at_utc": "2026-11-16T00:00:00Z"}],
        rows=[_selector_row(market="spread", game_id=gid, week=10)],
    )
    state = advance_live_value_state(entering=ValueSelectorState(), evidence=evidence, run_root=tmp_path)
    assert (len(state.ml_observations), len(state.spread_observations)) == (1, 8)


@pytest.fixture
def week10_gap_history(tmp_path, monkeypatch, week9_gap_history):
    week9, _ = week9_gap_history
    excluded = product_state._WEEK10_EXCLUDED_GAME
    schedule = [
        {"game_id": gid, "kickoff_at_utc": kickoff}
        for gid, kickoff in product_state._WEEK10_KICKOFFS.items()
    ]
    rows = [
        _selector_row(market=market, side=side, game_id=gid, week=10)
        for gid in product_state._WEEK10_KICKOFFS if gid != excluded
        for market in ("moneyline", "spread", "total")
        for side in ("home", "away")
    ]
    _write_proof(
        tmp_path, name="week10-reviewed-success", week=10, captured_at="2026-11-15T12:08:38Z",
        games=schedule, rows=rows,
    )
    status = tmp_path / "week10-reviewed-success/run-status.json"
    status.write_text(json.dumps({"week": 10, "outcome": "SUCCESS"}))
    proof = status.parent / "product/deterministic-proof.json"
    failed = tmp_path / "week10-reviewed-failure/run-status.json"
    failed.parent.mkdir()
    failed.write_text(json.dumps({"week": 10, "outcome": "FOOTBALL_STATE_NOT_READY"}))
    pins = {
        status.parent.name: (product_state._sha256(status), product_state._sha256(proof)),
        failed.parent.name: (product_state._sha256(failed), None),
    }
    monkeypatch.setattr(product_state, "_WEEK10_RUN_HASHES", pins)
    evidence = _evidence(through_week=10, games=[
        *week9.games.to_dicts(),
        *[
            dict(game_id=gid, season=2026, season_type="REG", week=10,
                 home_score=21 if gid == excluded else 24, away_score=24 if gid == excluded else 17)
            for gid in product_state._WEEK10_KICKOFFS
        ],
    ])
    evidence.manifest = week9.manifest
    evidence.manifest["schedule_checkpoints"]["10"] = product_state._WEEK10_CHECKPOINT
    return evidence, status, proof, pins


def test_week10_gap_advances_existing_selector_with_13_games_and_preserves_all_settlement(
    tmp_path, week10_gap_history,
):
    evidence, _, _, _ = week10_gap_history
    settled = evidence.games.clone()
    results = []
    for _ in range(2):
        audit = []
        state = advance_live_value_state(
            entering=ValueSelectorState(), evidence=evidence, run_root=tmp_path, recovery_audit=audit,
        )
        results.append((state, audit))
    assert results[0] == results[1]
    assert evidence.games.equals(settled)
    state, (week9_record, week10_record) = results[0]
    assert (len(state.ml_observations), len(state.spread_observations)) == (2, 8)
    assert week9_record["selector_state_after_sha256"] == week10_record["selector_state_before_sha256"]
    assert week10_record["entering_observations"] == {"moneyline": 1, "spread": 7}
    assert week10_record["exiting_observations"] == {"moneyline": 2, "spread": 8}
    assert week10_record["football_settlement_complete"]
    excluded = product_state._WEEK10_EXCLUDED_GAME
    assert week10_record["excluded_market_observation_game_id"] == excluded
    assert week10_record["excluded_game_kickoff_at_utc"] == "2026-11-13T01:15:00Z"
    assert len(week10_record["settled_game_ids"]) == 14
    assert set(week10_record["accepted_pregame_game_ids"]) == set(week10_record["settled_game_ids"]) - {excluded}
    assert week10_record["accepted_evaluator_rows"] == 78
    assert week10_record["accepted_market_settlement_rows"] == 52
    assert week10_record["synthetic_market_observations"] == 0


@pytest.mark.parametrize(("change", "message"), [
    ("wrong_checkpoint", "mismatched settled evidence"),
    ("lost_settlement", "mismatched settled evidence"),
    ("wrong_final", "mismatched WAS"),
    ("missing_proof", "proof missing"),
    ("changed_proof", "proof changed"),
    ("changed_status", "status missing or changed"),
    ("conflicting_status", "status conflicts"),
    ("missing_rows", "six authentic evaluator rows"),
    ("wrong_missing_game", "identity or timing requires review"),
    ("wrong_kickoff", "identity or timing requires review"),
    ("post_kickoff", "settled Week 10"),
    ("new_valid_was_proof", "unreviewed Week 10 selector status"),
    ("new_proof_without_status", "unreviewed Week 10 selector proof"),
    ("week11_missing", "settled Week 11"),
])
def test_week10_gap_rejects_evidence_drift(tmp_path, week10_gap_history, change, message):
    evidence, status, proof, pins = week10_gap_history
    excluded = product_state._WEEK10_EXCLUDED_GAME
    if change == "wrong_checkpoint":
        evidence.manifest["schedule_checkpoints"]["10"] = "f" * 64
    elif change == "lost_settlement":
        evidence.games = evidence.games.filter(pl.col("game_id") != excluded)
    elif change == "wrong_final":
        evidence.games = evidence.games.with_columns(
            pl.when(pl.col("game_id") == excluded).then(20).otherwise(pl.col("home_score")).alias("home_score"),
        )
    elif change == "missing_proof":
        proof.unlink()
    elif change == "changed_proof":
        proof.write_text("{}")
    elif change in {"changed_status", "conflicting_status"}:
        status.write_text(json.dumps({"week": 10, "outcome": "MATERIALIZATION_FAILED"}))
        if change == "conflicting_status":
            pins[status.parent.name] = (product_state._sha256(status), product_state._sha256(proof))
    elif change in {"missing_rows", "wrong_missing_game", "wrong_kickoff", "post_kickoff"}:
        payload = json.loads(proof.read_text())
        selector = payload["selector_evidence"]
        if change in {"missing_rows", "wrong_missing_game"}:
            missing = "2026_10_BUF_NYJ"
            selector["rows"] = [row for row in selector["rows"] if row["game_id"] != missing]
            if change == "wrong_missing_game":
                selector["rows"].append(_selector_row(market="moneyline", game_id=excluded, week=10))
        elif change == "wrong_kickoff":
            next(game for game in selector["games"] if game["game_id"] == excluded)["kickoff_at_utc"] = (
                "2026-11-13T02:15:00Z"
            )
        else:
            selector["captured_at_utc"] = "2026-11-15T14:30:00Z"
        proof.write_text(json.dumps(payload))
        pins[status.parent.name] = (product_state._sha256(status), product_state._sha256(proof))
    elif change.startswith("new_"):
        _write_proof(
            tmp_path, name="week10-discovered", week=10, captured_at="2026-11-13T00:00:00Z",
            games=[{"game_id": excluded, "kickoff_at_utc": "2026-11-13T01:15:00Z"}],
            rows=[_selector_row(market="moneyline", game_id=excluded, week=10)],
        )
        if change == "new_proof_without_status":
            (tmp_path / "week10-discovered/run-status.json").unlink()
        else:
            (tmp_path / "week10-discovered/run-status.json").write_text('{"week": 10, "outcome": "SUCCESS"}')
    else:
        evidence.through_week = 11
        evidence.games = pl.DataFrame([*evidence.games.to_dicts(), dict(
            game_id="2026_11_A_B", season=2026, season_type="REG", week=11, home_score=24, away_score=17,
        )])
    with pytest.raises(Entering2026ProductStateError, match=message):
        advance_live_value_state(entering=ValueSelectorState(), evidence=evidence, run_root=tmp_path)


def test_week10_gap_audit_matches_production_and_offline_preprovider(
    tmp_path, monkeypatch, capsys, week10_gap_history,
):
    from nfl_edge.operations import production_refresh_v1 as refresh
    from scripts import verify_live_2026_preprovider_v1 as preprovider

    evidence, _, _, _ = week10_gap_history
    evidence.feature_inputs = lambda: evidence.games
    active = SimpleNamespace(
        path=tmp_path / "week11_schedule_v1.json",
        payload={"schedule_version": "fixture"},
        rollover_at_utc="2026-11-17T06:00:00Z",
        season=2026,
        week=11,
    )
    advanced = SimpleNamespace(
        state_version="fixture",
        completed_2026_blocks=list(range(1, 11)),
        summary=lambda: {},
    )
    sleeper = SimpleNamespace(
        freshness_state="FRESH", source_warning_state=None, snapshot_id="fixture",
        observed_at_utc="2026-11-18T00:00:00Z", freshness_contract=lambda: {},
    )
    football = {"games": [], "snapshot_sha256": "fixture"}
    for caller in (refresh, preprovider):
        monkeypatch.setattr(caller, "resolve_active_schedule", lambda *args, **kwargs: active)
        monkeypatch.setattr(caller, "load_settled_evidence", lambda root: evidence)
        monkeypatch.setattr(caller, "advance_entering_state_through_settled_weeks", lambda **kwargs: advanced)
        monkeypatch.setattr(caller, "load_overrides", lambda path: {})
        monkeypatch.setattr(caller, "SleeperExpectedQBResolver", lambda *args, **kwargs: object())
        monkeypatch.setattr(caller, "score_week", lambda **kwargs: football)
        monkeypatch.setattr(caller, "load_entering_2026_product_state", lambda path: {"value_state": ValueSelectorState()})
    monkeypatch.setattr(refresh, "_validate_sleeper", lambda config: sleeper)
    monkeypatch.setattr(refresh, "_validate_football", lambda path: football)
    monkeypatch.setattr(preprovider, "SleeperQBSource", SimpleNamespace(load=lambda *args, **kwargs: sleeper))

    def stop_at_market_seam(*args, **kwargs):
        raise RuntimeError("fixture ends at the pre-provider gate")

    monkeypatch.setattr(refresh, "load_capture", stop_at_market_seam)
    monkeypatch.setattr(refresh, "acquire_live_response", lambda **kwargs: pytest.fail("provider called"))
    as_of = "2026-11-18T00:05:00Z"
    monkeypatch.setattr("sys.argv", [
        "verify_live_2026_preprovider_v1.py", "--repository-root", str(tmp_path),
        "--schedule-root", str(tmp_path), "--evidence-root", str(tmp_path),
        "--run-root", str(tmp_path), "--prediction-as-of-utc", as_of,
    ])
    assert preprovider.main() == 0
    offline = json.loads(capsys.readouterr().out)
    outcome, production = refresh.run_refresh(refresh.RefreshConfig(
        repository_root=tmp_path, run_root=tmp_path, publication_dir=tmp_path / "publication",
        prediction_as_of_utc=as_of, live=False, market_response=tmp_path / "unused.json", evidence_root=tmp_path,
    ))
    assert outcome is refresh.RefreshOutcome.MARKET_ACQUISITION_FAILED
    assert production["provider_request_count"] == offline["provider_request_count"] == 0
    assert production["selector_state_observations"] == offline["selector_state_observations"] == {
        "moneyline": 2, "spread": 8,
    }
    assert production["selector_recovery"] == offline["selector_recovery"]
    status = json.loads((tmp_path / "latest-status.json").read_text())
    assert status["selector_recovery"] == offline["selector_recovery"]
