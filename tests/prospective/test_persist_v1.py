from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nfl_edge.prospective.capture_v1 import load_publications
from nfl_edge.prospective.persist_v1 import EvidencePersistenceError, sync_runtime_week
from nfl_edge.prospective.runtime_v1 import capture_published_product, runtime_publications_dir

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/contracts/nfl_edge_product_api_v1_week1_mock.json"


def _product() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _evidence_repo(tmp_path: Path) -> Path:
    root = tmp_path / "evidence"
    root.mkdir()
    shutil.copytree(ROOT / "schemas", root / "schemas")
    return root


def test_sync_runtime_week_copies_immutable_publication_and_derives_week_artifacts(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    evidence = _evidence_repo(tmp_path)
    capture_published_product(
        _product(),
        runtime_root=runtime,
        published_at_utc="2026-09-02T14:00:05Z",
    )

    first = sync_runtime_week(
        runtime_root=runtime,
        evidence_repo_root=evidence,
        season=2026,
        week=1,
    )
    week_root = evidence / "prospective/cards/2026/week-01"
    before = {path.name: path.read_bytes() for path in week_root.glob("*.json")}

    second = sync_runtime_week(
        runtime_root=runtime,
        evidence_repo_root=evidence,
        season=2026,
        week=1,
    )
    after = {path.name: path.read_bytes() for path in week_root.glob("*.json")}

    assert first["status"] == "SYNCED"
    assert first["created_publication_count"] == 1
    assert second["created_publication_count"] == 0
    assert before == after
    assert sorted(before) == ["episodes.json", "official.json", "results.json", "summary.json"]

    runtime_rows = load_publications(runtime_publications_dir(runtime, season=2026, week=1))
    repo_rows = load_publications(week_root / "publications")
    assert repo_rows == runtime_rows
    assert len(repo_rows) == 1
    assert repo_rows[0]["capture_mode"] == "NATIVE_PROSPECTIVE"
    assert repo_rows[0]["creation_provenance"]["provider_calls"] == 0
    assert repo_rows[0]["creation_provenance"]["user_specific_data_included"] is False


def test_sync_runtime_week_preserves_settled_result_identity_on_rerun(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    evidence = _evidence_repo(tmp_path)
    capture_published_product(
        _product(),
        runtime_root=runtime,
        published_at_utc="2026-09-02T14:00:05Z",
    )
    sync_runtime_week(runtime_root=runtime, evidence_repo_root=evidence, season=2026, week=1)

    results_path = evidence / "prospective/cards/2026/week-01/results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    assert len(results["lane_results"]) == 1
    results["lane_results"][0].update(
        grade="WIN",
        official_score={"away": 20, "home": 24},
        result_source="TEST_OFFICIAL_SOURCE",
        result_source_provenance={"fixture": True},
        settled_at_utc="2026-09-06T20:00:00Z",
        realized_units=0.6521739130434783,
    )
    results_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    sync_runtime_week(runtime_root=runtime, evidence_repo_root=evidence, season=2026, week=1)
    preserved = json.loads(results_path.read_text(encoding="utf-8"))
    assert preserved["lane_results"][0]["grade"] == "WIN"
    assert preserved["lane_results"][0]["realized_units"] == pytest.approx(0.6521739130434783)
    assert preserved["lane_results"][0]["settled_at_utc"] == "2026-09-06T20:00:00Z"


def test_sync_runtime_week_rejects_non_native_runtime_capture(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    evidence = _evidence_repo(tmp_path)
    capture_published_product(
        _product(),
        runtime_root=runtime,
        published_at_utc="2026-09-02T14:00:05Z",
    )
    publication_path = next(runtime.rglob("*.json"))
    payload = json.loads(publication_path.read_text(encoding="utf-8"))
    payload["capture_mode"] = "RECONSTRUCTED_FROM_ARCHIVED_PRODUCTION_ARTIFACT"
    publication_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(EvidencePersistenceError, match="only NATIVE_PROSPECTIVE"):
        sync_runtime_week(runtime_root=runtime, evidence_repo_root=evidence, season=2026, week=1)


def test_sync_runtime_week_rejects_schema_invalid_runtime_record(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    evidence = _evidence_repo(tmp_path)
    capture_published_product(
        _product(),
        runtime_root=runtime,
        published_at_utc="2026-09-02T14:00:05Z",
    )
    publication_path = next(runtime.rglob("*.json"))
    payload = json.loads(publication_path.read_text(encoding="utf-8"))
    del payload["lanes"]
    publication_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(EvidencePersistenceError, match="schema validation failed"):
        sync_runtime_week(runtime_root=runtime, evidence_repo_root=evidence, season=2026, week=1)


def test_sync_runtime_week_no_runtime_publications_is_clean_noop(tmp_path: Path) -> None:
    evidence = _evidence_repo(tmp_path)
    result = sync_runtime_week(
        runtime_root=tmp_path / "runtime",
        evidence_repo_root=evidence,
        season=2026,
        week=1,
    )
    assert result["status"] == "NO_RUNTIME_PUBLICATIONS"
    assert result["created_publication_count"] == 0
    assert not (evidence / "prospective/cards").exists()
