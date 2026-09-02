from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from nfl_edge.contracts.live_product_v1 import (
    ContractValidationError,
    PRODUCT_SCHEMA_VERSION,
    UserProfileState,
    profile_update_preserves_recommendation,
    validate_exact_offer_request,
    validate_product_snapshot,
)
from nfl_edge.publication.live_product_v1 import promote_validated_snapshot

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/contracts/nfl_edge_product_api_v1_week1_mock.json"
SCHEMA = ROOT / "schemas/NFL_EDGE_PRODUCT_API_V1.schema.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_schema_file_is_versioned_and_parseable() -> None:
    schema = json.loads(SCHEMA.read_text())
    assert schema["$id"] == PRODUCT_SCHEMA_VERSION
    assert schema["properties"]["schema_version"]["const"] == PRODUCT_SCHEMA_VERSION


def test_valid_full_product_parses() -> None:
    parsed = validate_product_snapshot(_fixture())
    assert parsed["schema_version"] == PRODUCT_SCHEMA_VERSION
    assert parsed["games"][0]["game_id"] == "mock-2026-w01-AAA-BBB"


def test_honest_no_play_parses() -> None:
    payload = _fixture()
    payload["headlines"]["hit_rate"]["state"] = "NO_PLAY"
    payload["headlines"]["hit_rate"]["recommended_units"] = 0
    validate_product_snapshot(payload)


@pytest.mark.parametrize("state", ["TARGET_ONLY", "SUPPRESSED"])
def test_value_non_bet_states_parse(state: str) -> None:
    payload = _fixture()
    payload["headlines"]["value"]["state"] = state
    payload["headlines"]["value"]["recommended_units"] = 0
    validate_product_snapshot(payload)


def test_missing_book_is_legal_and_not_fabricated() -> None:
    payload = _fixture()
    total = payload["games"][0]["market_board"]["total"]
    assert "FANDUEL" not in total
    validate_product_snapshot(payload)


def test_stale_qb_is_legal_and_explicit() -> None:
    payload = _fixture()
    qb = payload["games"][0]["quarterbacks"]["away"]
    qb["freshness"] = {
        "state": "STALE",
        "observed_at_utc": "2026-09-01T12:00:00Z",
        "age_seconds": 93600,
        "threshold_seconds": 21600,
    }
    qb["warning_state"] = "STALE_LAST_SUCCESS"
    validate_product_snapshot(payload)


def test_unresolved_qb_is_legal_and_explicit() -> None:
    payload = _fixture()
    qb = payload["games"][0]["quarterbacks"]["away"]
    qb.update(
        expected_starter=None,
        canonical_qb_id=None,
        gsis_id=None,
        resolution_status="UNRESOLVED",
        warning_state="IDENTITY_REVIEW_REQUIRED",
    )
    validate_product_snapshot(payload)


def test_stale_market_offer_is_legal_and_explicit() -> None:
    payload = _fixture()
    offer = payload["games"][0]["market_board"]["moneyline"]["DRAFTKINGS"][0]
    offer["freshness"] = {
        "state": "STALE",
        "observed_at_utc": "2026-09-02T13:40:00Z",
        "age_seconds": 1200,
        "threshold_seconds": 300,
    }
    validate_product_snapshot(payload)


def test_unavailable_model_is_legal_and_explicit() -> None:
    payload = _fixture()
    model = payload["games"][0]["football_outputs"]["xgboost_v2"]
    model.update(status="UNAVAILABLE", prediction=None, support="UNSUPPORTED", warnings=["artifact unavailable"])
    validate_product_snapshot(payload)


def test_bankroll_and_profile_update_cannot_change_recommended_units() -> None:
    before = UserProfileState(
        user_id="local-v1",
        bankroll=1000.00,
        risk_profile="Normal",
        created_at="2026-09-02T14:00:00Z",
        updated_at="2026-09-02T14:00:00Z",
    )
    after = UserProfileState(
        user_id="local-v1",
        bankroll=1500.00,
        risk_profile="Aggressive",
        created_at="2026-09-02T14:00:00Z",
        updated_at="2026-09-02T14:05:00Z",
    )
    units, before_stake, after_stake = profile_update_preserves_recommendation(
        before, after, recommended_units=0.75
    )
    assert units == 0.75
    assert before_stake != after_stake


def test_invalid_risk_profile_fails() -> None:
    with pytest.raises(ContractValidationError, match="risk_profile"):
        UserProfileState(
            user_id="local-v1",
            bankroll=1000.00,
            risk_profile="YOLO",
            created_at="2026-09-02T14:00:00Z",
            updated_at="2026-09-02T14:00:00Z",
        ).validate()


def test_malformed_exact_offer_fails() -> None:
    with pytest.raises(ContractValidationError, match="missing required"):
        validate_exact_offer_request(
            {
                "market_type": "SPREAD",
                "selection": "AAA",
                "book": "DRAFTKINGS",
                "line": 2.5,
                "price": -110,
            }
        )


def test_clicked_and_manual_exact_offer_shape_uses_same_contract() -> None:
    offer = {
        "game_id": "mock-2026-w01-AAA-BBB",
        "market_type": "SPREAD",
        "selection": "AAA",
        "book": "DRAFTKINGS",
        "line": 2.5,
        "price": -110,
    }
    assert validate_exact_offer_request(offer) == offer


def test_duplicate_exact_offer_fails() -> None:
    payload = _fixture()
    offers = payload["games"][0]["market_board"]["moneyline"]["DRAFTKINGS"]
    offers.append(deepcopy(offers[0]))
    with pytest.raises(ContractValidationError, match="duplicates"):
        validate_product_snapshot(payload)


def test_incomplete_snapshot_cannot_replace_latest(tmp_path: Path) -> None:
    valid = _fixture()
    promote_validated_snapshot(valid, tmp_path)
    old_latest = (tmp_path / "latest.json").read_text()

    invalid = _fixture()
    del invalid["schema_version"]
    with pytest.raises(ContractValidationError):
        promote_validated_snapshot(invalid, tmp_path)

    assert (tmp_path / "latest.json").read_text() == old_latest


def test_schema_version_is_required() -> None:
    payload = _fixture()
    del payload["schema_version"]
    with pytest.raises(ContractValidationError, match="schema_version"):
        validate_product_snapshot(payload)


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda p: p.pop("generated_at_utc"), "generated_at_utc"),
        (lambda p: p["games"][0]["quarterbacks"]["home"].pop("provenance_id"), "provenance_id"),
        (lambda p: p["games"][0]["football_outputs"].pop("provenance_id"), "provenance_id"),
    ],
)
def test_required_timestamps_and_provenance_fail_closed(mutation, match: str) -> None:
    payload = _fixture()
    mutation(payload)
    with pytest.raises(ContractValidationError, match=match):
        validate_product_snapshot(payload)


def test_product_stale_flag_must_match_freshness_state() -> None:
    payload = _fixture()
    payload["stale"] = True
    with pytest.raises(ContractValidationError, match="stale"):
        validate_product_snapshot(payload)


def test_live_scorer_rejects_future_history() -> None:
    from nfl_edge.contracts.live_product_v1 import LiveScorerRequest

    with pytest.raises(ContractValidationError, match="history"):
        LiveScorerRequest(
            schedule_version="schedule-v1",
            prediction_as_of_utc="2026-09-02T14:00:00Z",
            completed_football_state_version="football-v1",
            history_complete_through_utc="2026-09-02T14:01:00Z",
            qb_state_version="qb-state-v1",
            qb_snapshot_version="qb-snapshot-v1",
            resolved_expected_qb_version="resolver-v1",
            frozen_model_artifact_versions={"xgboost_v2": "post-v5-v2"},
            feature_state_versions={"features": "v1"},
        ).validate()


def test_starter_change_must_require_rescore_and_distinct_provenance() -> None:
    from nfl_edge.contracts.live_product_v1 import QBStarterChangeEvent

    with pytest.raises(ContractValidationError):
        QBStarterChangeEvent(
            game_id="mock-2026-w01-AAA-BBB",
            team="AAA",
            previous_provenance_id="prov-1",
            new_provenance_id="prov-2",
            previous_canonical_qb_id="qb-1",
            new_canonical_qb_id="qb-2",
            changed_at_utc="2026-09-02T14:00:00Z",
            rescore_required=False,
        ).validate()


def test_qb_override_forbids_silent_provenance_reuse() -> None:
    from nfl_edge.contracts.live_product_v1 import QBOverrideAudit

    with pytest.raises(ContractValidationError, match="silent edit"):
        QBOverrideAudit(
            game_id="mock-2026-w01-AAA-BBB",
            team="AAA",
            previous_canonical_qb_id="qb-1",
            new_canonical_qb_id="qb-2",
            reason="official starter correction",
            evidence_source="official-team-release",
            operator="operator-1",
            changed_at_utc="2026-09-02T14:00:00Z",
            previous_provenance_id="prov-1",
            new_provenance_id="prov-1",
        ).validate()


def test_non_bet_headline_cannot_carry_positive_units() -> None:
    payload = _fixture()
    payload["headlines"]["value"]["state"] = "TARGET_ONLY"
    payload["headlines"]["value"]["recommended_units"] = 0.75
    with pytest.raises(ContractValidationError, match="recommended_units"):
        validate_product_snapshot(payload)


def test_duplicate_exact_observation_with_new_id_fails() -> None:
    payload = _fixture()
    offers = payload["games"][0]["market_board"]["moneyline"]["DRAFTKINGS"]
    duplicate = deepcopy(offers[0])
    duplicate["offer_id"] = "different-id-same-observation"
    offers.append(duplicate)
    with pytest.raises(ContractValidationError, match="duplicates an exact offer observation"):
        validate_product_snapshot(payload)


def test_nonfinite_bankroll_fails() -> None:
    with pytest.raises(ContractValidationError, match="finite"):
        UserProfileState(
            user_id="local-v1",
            bankroll=float("nan"),
            risk_profile="Normal",
            created_at="2026-09-02T14:00:00Z",
            updated_at="2026-09-02T14:00:00Z",
        ).validate()


def test_qb_override_requires_rescore() -> None:
    from nfl_edge.contracts.live_product_v1 import QBOverrideAudit

    with pytest.raises(ContractValidationError, match="rescore"):
        QBOverrideAudit(
            game_id="mock-2026-w01-AAA-BBB",
            team="AAA",
            previous_canonical_qb_id="qb-1",
            new_canonical_qb_id="qb-2",
            reason="official starter correction",
            evidence_source="official-team-release",
            operator="operator-1",
            changed_at_utc="2026-09-02T14:00:00Z",
            previous_provenance_id="prov-1",
            new_provenance_id="prov-2",
            rescore_required=False,
        ).validate()


def test_contract_doc_contains_security_and_request_training_boundaries() -> None:
    doc = (ROOT / "docs/LIVE_PRODUCT_BACKEND_CONTRACT_V1.md").read_text()
    assert "The frontend consumes the product/API contract. It does not consume internal model files directly." in doc
    assert "The API serves already-generated product state. User requests do not train models." in doc
    assert "browser never directly calls paid/private football or sportsbook providers" in doc
