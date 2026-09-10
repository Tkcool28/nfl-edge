from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from nfl_edge.prospective.card_tracking_v1 import (
    AppendOnlyViolation,
    ProspectiveCardError,
)
from nfl_edge.prospective.persistence_v1 import (
    finalize_week_evidence,
    sync_runtime_evidence,
)
from nfl_edge.prospective.runtime_v1 import capture_published_product

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/contracts/nfl_edge_product_api_v1_week1_mock.json"
OFFICIAL_SCHEMA = ROOT / "schemas/NFL_EDGE_PROSPECTIVE_CARD_OFFICIAL_V1.schema.json"


def _product() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _capture(runtime: Path, *, published_at: str = "2026-09-02T14:00:05Z") -> dict:
    return capture_published_product(
        _product(),
        runtime_root=runtime,
        published_at_utc=published_at,
    )


def test_sync_copies_exact_runtime_bytes_and_derives_episodes(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    evidence = tmp_path / "evidence"
    production = tmp_path / "production"
    production.mkdir()
    _capture(runtime)

    source = next(runtime.rglob("*.json"))
    first = sync_runtime_evidence(
        runtime_root=runtime,
        evidence_root=evidence,
        production_worktree=production,
    )

    target = next((evidence / "prospective/cards/2026/week-01/publications").glob("*.json"))
    assert target.read_bytes() == source.read_bytes()
    assert first["runtime_publications_seen"] == 1
    assert first["publications_copied"] == 1
    assert first["publications_deduplicated"] == 0
    assert first["provider_calls"] == 0
    assert (evidence / "prospective/cards/2026/week-01/episodes.json").is_file()

    second = sync_runtime_evidence(
        runtime_root=runtime,
        evidence_root=evidence,
        production_worktree=production,
    )
    assert second["publications_copied"] == 0
    assert second["publications_deduplicated"] == 1
    assert len(list((evidence / "prospective/cards/2026/week-01/publications").glob("*.json"))) == 1


@pytest.mark.parametrize("evidence_name", ["production", "production/evidence"])
def test_sync_rejects_production_worktree_overlap(tmp_path: Path, evidence_name: str) -> None:
    production = tmp_path / "production"
    production.mkdir()
    evidence = tmp_path / evidence_name
    if evidence != production:
        evidence.mkdir(parents=True)

    with pytest.raises(ProspectiveCardError, match="separate, non-nested"):
        sync_runtime_evidence(
            runtime_root=tmp_path / "runtime",
            evidence_root=evidence,
            production_worktree=production,
        )


def test_sync_rejects_noncanonical_runtime_evidence(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    evidence = tmp_path / "evidence"
    production = tmp_path / "production"
    production.mkdir()
    _capture(runtime)
    source = next(runtime.rglob("*.json"))
    payload = json.loads(source.read_text())
    source.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    with pytest.raises(ProspectiveCardError, match="not canonical deterministic JSON"):
        sync_runtime_evidence(
            runtime_root=runtime,
            evidence_root=evidence,
            production_worktree=production,
        )


def test_sync_rejects_conflicting_repository_publication(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    evidence = tmp_path / "evidence"
    production = tmp_path / "production"
    production.mkdir()
    _capture(runtime)
    source = next(runtime.rglob("*.json"))
    target_dir = evidence / "prospective/cards/2026/week-01/publications"
    target_dir.mkdir(parents=True)
    (target_dir / source.name).write_text('{"conflict": true}\n', encoding="utf-8")

    with pytest.raises(AppendOnlyViolation, match="conflicts with runtime evidence"):
        sync_runtime_evidence(
            runtime_root=runtime,
            evidence_root=evidence,
            production_worktree=production,
        )


def test_finalize_week_is_after_explicit_full_week_boundary_and_append_only(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    evidence = tmp_path / "evidence"
    production = tmp_path / "production"
    production.mkdir()
    _capture(runtime)
    sync_runtime_evidence(
        runtime_root=runtime,
        evidence_root=evidence,
        production_worktree=production,
    )

    week_root = evidence / "prospective/cards/2026/week-01"
    result = finalize_week_evidence(
        evidence_root=evidence,
        season=2026,
        week=1,
        finalized_at_utc="2026-09-07T00:00:00Z",
        week_last_kickoff_at_utc="2026-09-06T23:00:00Z",
    )
    assert result["official_created"] is True
    assert result["results_created"] is True
    assert result["provider_calls"] == 0

    official = json.loads((week_root / "official.json").read_text())
    pending = json.loads((week_root / "results.json").read_text())
    summary = json.loads((week_root / "summary.json").read_text())
    assert official["finalized_at_utc"] == "2026-09-07T00:00:00Z"
    assert official["week_last_kickoff_at_utc"] == "2026-09-06T23:00:00Z"
    assert pending["settlement_status"] == "PENDING"
    assert summary["interpretation"] == "DESCRIPTIVE_PROSPECTIVE_EVIDENCE_ONLY_NO_RETUNING"

    schema = json.loads(OFFICIAL_SCHEMA.read_text())
    errors = list(Draft202012Validator(schema).iter_errors(official))
    assert errors == []

    retry = finalize_week_evidence(
        evidence_root=evidence,
        season=2026,
        week=1,
        finalized_at_utc="2026-09-07T00:00:00Z",
        week_last_kickoff_at_utc="2026-09-06T23:00:00Z",
    )
    assert retry["official_created"] is False
    assert retry["results_created"] is False

    with pytest.raises(AppendOnlyViolation):
        finalize_week_evidence(
            evidence_root=evidence,
            season=2026,
            week=1,
            finalized_at_utc="2026-09-07T00:01:00Z",
            week_last_kickoff_at_utc="2026-09-06T23:00:00Z",
        )


def test_finalize_week_refuses_boundary_that_has_not_passed(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    evidence = tmp_path / "evidence"
    production = tmp_path / "production"
    production.mkdir()
    _capture(runtime)
    sync_runtime_evidence(
        runtime_root=runtime,
        evidence_root=evidence,
        production_worktree=production,
    )

    with pytest.raises(ProspectiveCardError, match="strictly after"):
        finalize_week_evidence(
            evidence_root=evidence,
            season=2026,
            week=1,
            finalized_at_utc="2026-09-06T23:00:00Z",
            week_last_kickoff_at_utc="2026-09-06T23:00:00Z",
        )


def test_finalize_week_refuses_incomplete_last_kickoff_claim(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    evidence = tmp_path / "evidence"
    production = tmp_path / "production"
    production.mkdir()
    _capture(runtime)
    sync_runtime_evidence(
        runtime_root=runtime,
        evidence_root=evidence,
        production_worktree=production,
    )

    with pytest.raises(ProspectiveCardError, match="kickoff exceeds supplied"):
        finalize_week_evidence(
            evidence_root=evidence,
            season=2026,
            week=1,
            finalized_at_utc="2026-09-07T00:00:00Z",
            week_last_kickoff_at_utc="2026-09-06T16:00:00Z",
        )
