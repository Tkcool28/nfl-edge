from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from nfl_edge.prospective.card_tracking_v1 import (
    build_pending_results,
    build_publication_snapshot,
    build_summary,
    derive_episodes,
    resolve_official,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/contracts/nfl_edge_product_api_v1_week1_mock.json"
SCHEMAS = ROOT / "schemas"


def _schema(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def _validate(name: str, payload: dict) -> None:
    validator = Draft202012Validator(_schema(name))
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.absolute_path))
    assert not errors, "\n".join(
        f"{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
        for error in errors
    )


def test_generated_prospective_artifacts_validate_against_v1_schemas() -> None:
    product = json.loads(FIXTURE.read_text(encoding="utf-8"))
    publication = build_publication_snapshot(
        product,
        published_at_utc="2026-09-02T14:00:05Z",
        capture_mode="REPO_SIMULATION",
    )
    episodes = derive_episodes([publication])
    official = resolve_official([publication])
    results = build_pending_results(official)
    summary = build_summary(official=official, results=results, episodes=episodes)

    _validate("NFL_EDGE_PROSPECTIVE_CARD_PUBLICATION_V1.schema.json", publication)
    _validate("NFL_EDGE_PROSPECTIVE_CARD_EPISODES_V1.schema.json", episodes)
    _validate("NFL_EDGE_PROSPECTIVE_CARD_OFFICIAL_V1.schema.json", official)
    _validate("NFL_EDGE_PROSPECTIVE_CARD_RESULT_V1.schema.json", results)
    _validate("NFL_EDGE_PROSPECTIVE_CARD_SUMMARY_V1.schema.json", summary)
