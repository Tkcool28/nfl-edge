from pathlib import Path

def test_no_sportsbook_features_in_frozen_football_model_modules():
 root=Path(__file__).resolve().parents[2]/"src/nfl_edge/models"
 forbidden={"draftkings","fanduel","pinnacle","sportsbook","american_odds","market_price"}
 for p in root.glob("*.py"):
  text=p.read_text().lower();assert not any(x in text for x in forbidden),f"sportsbook token in frozen model module {p}"
def test_manifest_code_never_serializes_environment():
 text=(Path(__file__).resolve().parents[2]/"scripts/market_evaluator_v1_runner.py").read_text().lower()
 assert "os.environ" not in text and "environ.copy" not in text and "api_key" not in text
def test_runner_uses_lazy_season_filter_for_outcomes():
 text=(Path(__file__).resolve().parents[2]/"scripts/market_evaluator_v1_runner.py").read_text()
 assert "pl.scan_parquet" in text and "filter(pl.col(\"season\").is_in(DEV))" in text
