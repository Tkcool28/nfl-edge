from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from nfl_edge.contracts.live_product_v1 import ContractValidationError, validate_product_snapshot

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/contracts/nfl_edge_product_api_v1_week1_mock.json"
SCHEMA = ROOT / "schemas/NFL_EDGE_PRODUCT_API_V1.schema.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _xgb(payload: dict) -> dict:
    return payload["games"][0]["football_outputs"]["xgboost_v2"]


def _pending_payload() -> dict:
    payload = _fixture()
    model = _xgb(payload)
    model.update(
        status="AVAILABLE_WITH_ROOF_SCENARIOS",
        prediction=None,
        support="PARTIAL",
        warnings=["roof state pending; scenario predictions available"],
        roof_resolution_status="PENDING",
        roof_selected_scenario=None,
        xgboost_open_probability=0.51,
        xgboost_closed_probability=0.57,
        xgboost_scenario_delta=0.06,
        roof_scenario_downstream={
            "status": "NOT_EVALUATED_MISSING_EVIDENCE",
            "agreement_status": "NOT_EVALUABLE",
            "open_state": None,
            "closed_state": None,
            "shared_state": None,
        },
    )
    return payload


def _resolved_payload(status: str) -> dict:
    payload = _fixture()
    model = _xgb(payload)
    open_probability = 0.51
    closed_probability = 0.57
    selected = status.lower()
    model.update(
        status="AVAILABLE",
        prediction=open_probability if selected == "open" else closed_probability,
        support="SUPPORTED",
        warnings=[],
        roof_resolution_status=status,
        roof_selected_scenario=selected,
        xgboost_open_probability=open_probability,
        xgboost_closed_probability=closed_probability,
    )
    return payload


def test_canonical_schema_and_runtime_accept_valid_pending_roof_scenario() -> None:
    payload = _pending_payload()
    _validator().validate(payload)
    validate_product_snapshot(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda model: model.__setitem__("roof_selected_scenario", "open"),
        lambda model: model.__setitem__("prediction", 0.51),
        lambda model: model.__setitem__("support", "SUPPORTED"),
        lambda model: model.__setitem__("roof_resolution_status", "OPEN"),
        lambda model: model.pop("xgboost_scenario_delta"),
    ],
)
def test_schema_and_runtime_reject_malformed_pending_states(mutation) -> None:
    payload = _pending_payload()
    mutation(_xgb(payload))
    with pytest.raises(ValidationError):
        _validator().validate(payload)
    with pytest.raises(ContractValidationError):
        validate_product_snapshot(payload)


def test_schema_and_runtime_reject_evaluated_with_missing_states() -> None:
    payload = _pending_payload()
    _xgb(payload)["roof_scenario_downstream"] = {
        "status": "EVALUATED",
        "agreement_status": "AGREE",
        "open_state": None,
        "closed_state": None,
        "shared_state": None,
    }
    with pytest.raises(ValidationError):
        _validator().validate(payload)
    with pytest.raises(ContractValidationError):
        validate_product_snapshot(payload)


def test_schema_and_runtime_reject_roof_sensitive_with_missing_states() -> None:
    payload = _pending_payload()
    _xgb(payload)["roof_scenario_downstream"] = {
        "status": "ROOF_SENSITIVE",
        "agreement_status": "ROOF_SENSITIVE",
        "open_state": None,
        "closed_state": None,
        "shared_state": None,
    }
    with pytest.raises(ValidationError):
        _validator().validate(payload)
    with pytest.raises(ContractValidationError):
        validate_product_snapshot(payload)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_pending_scenario_probability_cannot_validate_or_publish(value: float) -> None:
    payload = _pending_payload()
    _xgb(payload)["xgboost_open_probability"] = value
    with pytest.raises(ContractValidationError):
        validate_product_snapshot(payload)
    with pytest.raises(ValueError):
        json.dumps(payload, allow_nan=False)


@pytest.mark.parametrize("value", [float("inf"), float("-inf")])
def test_schema_rejects_out_of_range_nonfinite_probability(value: float) -> None:
    payload = _pending_payload()
    _xgb(payload)["xgboost_open_probability"] = value
    with pytest.raises(ValidationError):
        _validator().validate(payload)


def test_ordinary_available_output_remains_canonical_and_rejects_roof_only_fields() -> None:
    payload = _fixture()
    _validator().validate(payload)
    validate_product_snapshot(payload)

    malformed = deepcopy(payload)
    _xgb(malformed)["roof_resolution_status"] = "OPEN"
    with pytest.raises(ValidationError):
        _validator().validate(malformed)
    with pytest.raises(ContractValidationError):
        validate_product_snapshot(malformed)


@pytest.mark.parametrize("roof_status", ["OPEN", "CLOSED"])
def test_resolved_roof_output_validates_as_available(roof_status: str) -> None:
    payload = _resolved_payload(roof_status)
    _validator().validate(payload)
    validate_product_snapshot(payload)


def test_resolved_roof_selection_must_match_status() -> None:
    payload = _resolved_payload("OPEN")
    _xgb(payload)["roof_selected_scenario"] = "closed"
    with pytest.raises(ValidationError):
        _validator().validate(payload)
    with pytest.raises(ContractValidationError):
        validate_product_snapshot(payload)


def test_resolved_roof_prediction_must_match_selected_probability_at_runtime() -> None:
    payload = _resolved_payload("OPEN")
    _xgb(payload)["prediction"] = 0.57
    _validator().validate(payload)
    with pytest.raises(ContractValidationError):
        validate_product_snapshot(payload)


def test_pending_extra_undeclared_field_still_fails_closed() -> None:
    payload = _pending_payload()
    _xgb(payload)["roof_guess"] = "open"
    with pytest.raises(ValidationError):
        _validator().validate(payload)
    with pytest.raises(ContractValidationError):
        validate_product_snapshot(payload)
