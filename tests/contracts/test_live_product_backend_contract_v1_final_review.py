from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from nfl_edge.contracts.live_product_v1 import ContractValidationError, validate_product_snapshot
from nfl_edge.publication.live_product_v1 import promote_validated_snapshot

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/contracts/nfl_edge_product_api_v1_week1_mock.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_top_level_unknown_field_is_rejected() -> None:
    payload = _fixture()
    payload["prediction_as_of_utcc"] = payload["prediction_as_of_utc"]
    with pytest.raises(ContractValidationError, match="unknown field"):
        validate_product_snapshot(payload)


def test_nested_misspelled_fixed_field_is_rejected() -> None:
    payload = _fixture()
    freshness = payload["games"][0]["quarterbacks"]["home"]["freshness"]
    freshness["age_secondz"] = freshness["age_seconds"]
    with pytest.raises(ContractValidationError, match="unknown field"):
        validate_product_snapshot(payload)


def test_unknown_field_cannot_replace_latest(tmp_path: Path) -> None:
    valid = _fixture()
    promote_validated_snapshot(valid, tmp_path)
    old_latest = (tmp_path / "latest.json").read_text()

    candidate = deepcopy(valid)
    candidate["generated_at_utc"] = "2026-09-02T14:01:00Z"
    candidate["games"][0]["football_outputs"]["qb_elo"]["predicton"] = 0.535
    with pytest.raises(ContractValidationError, match="unknown field"):
        promote_validated_snapshot(candidate, tmp_path)

    assert (tmp_path / "latest.json").read_text() == old_latest


def test_base_dependency_contract_publication_import_smoke() -> None:
    """Contracts/publication must import with model-development extras unavailable."""
    code = r'''
import importlib.abc
import json
import pathlib
import sys

BLOCKED = {"xgboost", "sklearn", "pandas", "pyarrow"}

class BlockModelDevelopment(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in BLOCKED:
            raise ModuleNotFoundError(f"blocked optional model-development dependency: {fullname}")
        return None

sys.meta_path.insert(0, BlockModelDevelopment())
from nfl_edge.contracts.live_product_v1 import validate_product_snapshot
from nfl_edge.publication.live_product_v1 import promote_validated_snapshot
assert "nfl_edge.recommendation" not in sys.modules
fixture = json.loads(pathlib.Path(sys.argv[1]).read_text())
validate_product_snapshot(fixture)
assert callable(promote_validated_snapshot)
print("BASE_DEPENDENCY_IMPORT_SMOKE_OK")
'''
    env = os.environ.copy()
    src = str(ROOT / "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    completed = subprocess.run(
        [sys.executable, "-c", code, str(FIXTURE)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "BASE_DEPENDENCY_IMPORT_SMOKE_OK" in completed.stdout
