from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from nfl_edge.holdout.one_shot_2025 import ReplayState


def _load_v2(repo_root: Path):
    path = repo_root / "scripts/task05g_2025_evaluation_v2.py"
    spec = importlib.util.spec_from_file_location("task05g_evaluation_v2_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v2_run_directory_isolated_and_collision_fails_closed(tmp_path: Path, monkeypatch):
    gate = _load_v2(Path(__file__).resolve().parents[2])
    monkeypatch.setattr(gate, "OUTPUT_BASE", tmp_path / "runs")

    first = gate.create_run_started("alpha-01", authorization_mode="synthetic")
    assert first["run_id"] == "alpha-01"
    assert (tmp_path / "runs/alpha-01/RUN_STARTED.json").exists()
    assert not (tmp_path / "runs/beta-02").exists()

    second = gate.create_run_started("beta-02", authorization_mode="synthetic")
    assert second["run_id"] == "beta-02"
    with pytest.raises(gate.RunScopedHoldoutError, match="RUN_OUTPUT_ALREADY_EXISTS"):
        gate.create_run_started("alpha-01", authorization_mode="synthetic")


def test_v2_lifecycle_completed_and_failed_never_overwrite(tmp_path: Path, monkeypatch):
    gate = _load_v2(Path(__file__).resolve().parents[2])
    monkeypatch.setattr(gate, "OUTPUT_BASE", tmp_path / "runs")
    started = gate.create_run_started("complete", authorization_mode="synthetic")
    completed = gate.complete_run(started, {"completed_blocks": 3})
    assert completed["status"] == "RUN_COMPLETED"
    assert json.loads((tmp_path / "runs/complete/RUN_COMPLETED.json").read_text())["completed_blocks"] == 3
    terminal = json.loads((tmp_path / "runs/complete/RUN_TERMINAL.json").read_text())
    assert terminal["status"] == "RUN_COMPLETED"
    assert not (tmp_path / "runs/complete/RUN_FAILED.json").exists()
    with pytest.raises(gate.RunScopedHoldoutError, match="lifecycle already terminal"):
        gate.fail_run(started, RuntimeError("later"))

    failed_started = gate.create_run_started("failed", authorization_mode="synthetic")
    failed = gate.fail_run(failed_started, ValueError("synthetic failure"))
    assert failed["status"] == "RUN_FAILED"
    assert failed["failure"]["type"] == "ValueError"
    failed_terminal = json.loads((tmp_path / "runs/failed/RUN_TERMINAL.json").read_text())
    assert failed_terminal["status"] == "RUN_FAILED"
    assert (tmp_path / "runs/failed/RUN_FAILED.json").is_file()
    assert not (tmp_path / "runs/failed/RUN_COMPLETED.json").exists()


def test_v2_execute_legacy_marker_does_not_block_or_modify_it(tmp_path: Path, monkeypatch):
    gate = _load_v2(Path(__file__).resolve().parents[2])
    legacy = tmp_path / "legacy/HOLDOUT_SPENT.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b'{"historical":true}\n')
    before = legacy.read_bytes()
    monkeypatch.setattr(gate, "OUTPUT_BASE", tmp_path / "runs")
    monkeypatch.setattr(gate, "LEGACY_SPEND_MARKER", legacy)
    monkeypatch.setattr(gate, "preflight", lambda: {"status": "SEALED_PREFLIGHT_PASS"})
    monkeypatch.setattr(gate, "_verify_authorization", lambda value: None)
    monkeypatch.setattr(gate, "prepare_development_state", lambda **_: {"development": "only"})
    calls = []

    def fake_runtime(**kwargs):
        calls.append(kwargs)
        return ReplayState(completed_blocks=("synthetic",))

    monkeypatch.setattr(gate, "run_authorized_holdout", fake_runtime)
    gate.execute("safe-run", "authorization", market_root=tmp_path / "market", historical_board=tmp_path / "board")
    assert legacy.read_bytes() == before
    assert calls[0]["output_root"] == tmp_path / "runs/safe-run"
    assert calls[0]["opened_marker_identity"]["run_id"] == "safe-run"
    assert json.loads((tmp_path / "runs/safe-run/RUN_COMPLETED.json").read_text())["completed_blocks"] == 1


def test_v2_started_provenance_has_exact_frozen_identities(tmp_path: Path, monkeypatch):
    gate = _load_v2(Path(__file__).resolve().parents[2])
    monkeypatch.setattr(gate, "OUTPUT_BASE", tmp_path / "runs")
    monkeypatch.setattr(gate, "LEGACY_SPEND_MARKER", tmp_path / "absent-legacy-marker")
    started = gate.create_run_started("identity-proof", authorization_mode="synthetic")
    provenance = started["provenance"]
    assert provenance["schema_version"] == gate.RUN_SCHEMA_VERSION
    assert provenance["authorization_mode"] == "synthetic"
    assert provenance["task05f_historical_board_sha256"] == gate.HISTORICAL_BOARD_SHA256
    assert provenance["canonical_book_market_sha256"] == gate.MARKET_CANONICAL_SHA256
    assert provenance["canonical_market_games_sha256"] == gate.MARKET_GAMES_SHA256
    pbp = provenance["frozen_task05c_pbp"]
    assert pbp["promoted_pre2025_sha256"] == gate.PRE2025_PBP_IDENTITIES
    assert pbp["evaluation_2025"]["sha256"] == gate.PBP_EXPECTED_SHA256
    assert provenance["frozen_task05c_game_observations"]["sha256"] == gate.OBSERVATIONS_EXPECTED_SHA256
    assert (
        provenance["config_identities"]["evaluation_v2_sha256"]
        == hashlib.sha256(gate.CONFIG_PATH.read_bytes()).hexdigest()
    )
    assert provenance["legacy_v1_spend_marker_present"] is False


def test_v2_preflight_requires_frozen_integrity_audit(monkeypatch):
    gate = _load_v2(Path(__file__).resolve().parents[2])
    calls: list[str] = []
    monkeypatch.setattr(gate, "_run_frozen_integrity_audit", lambda: calls.append("audit"))
    result = gate.preflight()
    assert result["status"] == "SEALED_V2_PREFLIGHT_PASS"
    assert result["2025_data_read"] is False
    assert calls == ["audit"]


def test_v2_execute_failure_preserves_partial_run_with_failed_marker(tmp_path: Path, monkeypatch):
    gate = _load_v2(Path(__file__).resolve().parents[2])
    monkeypatch.setattr(gate, "OUTPUT_BASE", tmp_path / "runs")
    monkeypatch.setattr(gate, "preflight", lambda: {"status": "SEALED_PREFLIGHT_PASS"})
    monkeypatch.setattr(gate, "_verify_authorization", lambda value: None)
    monkeypatch.setattr(gate, "prepare_development_state", lambda **_: {"development": "only"})

    def fail_runtime(**kwargs):
        (kwargs["output_root"] / "partial-proof.txt").write_text("preserve me", encoding="utf-8")
        raise RuntimeError("synthetic runtime failure")

    monkeypatch.setattr(gate, "run_authorized_holdout", fail_runtime)
    with pytest.raises(RuntimeError, match="synthetic runtime failure"):
        gate.execute(
            "partial-run", "authorization", market_root=tmp_path / "market", historical_board=tmp_path / "board"
        )
    root = tmp_path / "runs/partial-run"
    assert (root / "RUN_STARTED.json").is_file()
    assert (root / "RUN_FAILED.json").is_file()
    assert (root / "partial-proof.txt").read_text(encoding="utf-8") == "preserve me"
    assert not (root / "RUN_COMPLETED.json").exists()
    with pytest.raises(gate.RunScopedHoldoutError, match="RUN_OUTPUT_ALREADY_EXISTS"):
        gate.create_run_started("partial-run", authorization_mode="synthetic")


def test_v2_accepts_intended_safe_run_id():
    gate = _load_v2(Path(__file__).resolve().parents[2])
    assert gate.validate_run_id("2025-frozen-main-c616666-v1") == "2025-frozen-main-c616666-v1"


@pytest.mark.parametrize("run_id", ["", ".", "..", "../escape", "/absolute", "a/b", "has space", "a" * 81])
def test_v2_rejects_unsafe_run_ids(run_id: str):
    gate = _load_v2(Path(__file__).resolve().parents[2])
    with pytest.raises(gate.RunScopedHoldoutError, match="safe --run-id"):
        gate.validate_run_id(run_id)
