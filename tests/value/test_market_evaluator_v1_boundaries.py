import ast
from pathlib import Path

def test_frozen_football_models_do_not_import_market_evaluator_layer():
 root=Path(__file__).resolve().parents[2]/"src/nfl_edge/models"
 for p in root.glob("*.py"):
  tree=ast.parse(p.read_text())
  for node in ast.walk(tree):
   if isinstance(node,ast.Import):
    assert all(not a.name.startswith("nfl_edge.value") for a in node.names),f"value-layer import in {p}"
   elif isinstance(node,ast.ImportFrom):
    assert not (node.module or "").startswith("nfl_edge.value"),f"value-layer import in {p}"
def test_manifest_code_never_serializes_environment():
 text=(Path(__file__).resolve().parents[2]/"scripts/market_evaluator_v1_runner.py").read_text().lower()
 assert "os.environ" not in text and "environ.copy" not in text and "api_key" not in text
def test_runner_uses_lazy_season_filter_for_outcomes():
 text=(Path(__file__).resolve().parents[2]/"scripts/market_evaluator_v1_runner.py").read_text()
 assert "pl.scan_parquet" in text and "filter(pl.col(\"season\").is_in(DEV))" in text
