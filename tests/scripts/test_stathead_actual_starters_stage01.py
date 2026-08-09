"""Focused identity-only tests for Stathead Stage 01 reconciliation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts/stathead_actual_starters/reconcile_canonical_games.py"
_spec = importlib.util.spec_from_file_location("stathead_stage01", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
stage01 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stage01)


def game(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "game_id": "2024_01_AAA_BBB",
        "season": 2024,
        "season_type": "REG",
        "week": 1,
        "game_date": "2024-09-08",
        "away_team": "AAA",
        "home_team": "BBB",
    }
    return base | overrides


def row(**overrides: object) -> dict[str, object]:
    base = {
        "Rk": "1",
        "Player": "Quarterback",
        "Date": "2024-09-08",
        "Team": "AAA",
        "": "@",
        "Opp": "BBB",
        "Pos.": "QB",
        "Player-additional": "QuarQu00",
    }
    return base | overrides


def test_normal_away_and_home_matches() -> None:
    canonical = [game()]
    reconciled = stage01.reconcile_rows([row(), row(Rk="2", Team="BBB", **{"": "", "Opp": "AAA"})], canonical)
    assert [item["team_side"] for item in reconciled] == ["away", "home"]
    assert all(item["match_status"] == "MATCHED_CANONICAL_GAME" for item in reconciled)


def test_historical_abbreviation_normalization() -> None:
    canonical = [
        game(game_id="2018_17_KC_LV", season=2018, week=17, game_date="2018-12-30", away_team="KC", home_team="LV")
    ]
    reconciled = stage01.reconcile_rows([row(Date="2018-12-30", Team="OAK", **{"Opp": "KAN", "": ""})], canonical)
    assert reconciled[0]["canonical_game_id"] == "2018_17_KC_LV"
    assert reconciled[0]["team_side"] == "home"


def test_neutral_site_uses_canonical_team_identity_only() -> None:
    canonical = [game(away_team="AAA", home_team="BBB")]
    reconciled = stage01.reconcile_rows([row(**{"": "N"})], canonical)
    assert reconciled[0]["match_status"] == "MATCHED_CANONICAL_GAME"
    assert reconciled[0]["team_side"] == "away"


def test_bye_is_retained_as_non_game() -> None:
    reconciled = stage01.reconcile_rows([row(Rk="732", **{"": "", "Opp": "BYE"})], [game()])
    assert reconciled[0]["match_status"] == "NON_GAME_BYE"
    assert reconciled[0]["canonical_game_id"] == ""


def test_unmatched_row_is_explicit() -> None:
    reconciled = stage01.reconcile_rows([row(Opp="CCC")], [game()])
    assert reconciled[0]["match_status"] == "UNMATCHED"


def test_multiple_candidates_group_without_adjudication() -> None:
    canonical = [game()]
    reconciled = stage01.reconcile_rows(
        [row(Rk="1"), row(Rk="2", Player="Other QB", **{"Player-additional": "OtheQu00"})], canonical
    )
    groups = stage01.build_game_side_candidates(canonical, reconciled)
    away = next(item for item in groups if item["team_side"] == "away")
    assert away["candidate_count"] == 2
    assert away["candidate_ranks"] == "1|2"


def test_january_2025_date_maps_to_2024_postseason() -> None:
    canonical = [game(game_id="2024_19_AAA_BBB", season=2024, season_type="WC", week=19, game_date="2025-01-12")]
    reconciled = stage01.reconcile_rows([row(Date="2025-01-12")], canonical)
    assert reconciled[0]["canonical_season"] == 2024
    assert reconciled[0]["canonical_season_type"] == "WC"


def test_actual_2025_season_canonical_input_is_rejected() -> None:
    try:
        stage01.validate_canonical_games([game(season=2025)])
    except ValueError as exc:
        assert "2025" in str(exc)
    else:
        raise AssertionError("2025 canonical season must be rejected")
