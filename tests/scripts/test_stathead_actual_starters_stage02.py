from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

path = Path(__file__).resolve().parents[2] / "scripts/stathead_actual_starters/inventory_stage02_exceptions.py"
spec = spec_from_file_location("inventory", path)
assert spec is not None and spec.loader is not None
module = module_from_spec(spec)
spec.loader.exec_module(module)


def test_structural_diagnoses_and_no_selection_api():
    games = [{"game_date": "2024-09-01", "away_team": "AAA", "home_team": "BBB"}]
    location_row = {"reconciliation_reason": "raw home location", "raw_date": "x", "raw_team": "AAA", "raw_opp": "BBB"}
    opponent_row = {"reconciliation_reason": "none", "raw_date": "2024-09-01", "raw_team": "AAA", "raw_opp": "CCC"}
    assert module.diagnose(location_row, games) == "LOCATION_MISMATCH"
    assert module.diagnose(opponent_row, games) == "OPPONENT_MISMATCH"
    assert not hasattr(module, "select_starter")
