"""Prospective scorer and Sleeper expected-QB resolver interfaces V1."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from nfl_edge.contracts.common_v1 import (
    FRESHNESS_STATES,
    LIVE_SCORER_SCHEMA_VERSION,
    QB_RESOLUTION_STATUSES,
    QB_RESOLVER_SCHEMA_VERSION,
    ContractValidationError,
    require_enum,
    require_string,
    validate_utc_timestamp,
)


@dataclass(frozen=True)
class LiveScorerRequest:
    """Market-independent prospective scorer input identity."""

    schedule_version: str
    prediction_as_of_utc: str
    completed_football_state_version: str
    history_complete_through_utc: str
    qb_state_version: str
    qb_snapshot_version: str
    resolved_expected_qb_version: str
    frozen_model_artifact_versions: Mapping[str, str]
    feature_state_versions: Mapping[str, str]
    schema_version: str = LIVE_SCORER_SCHEMA_VERSION

    def validate(self) -> "LiveScorerRequest":
        if self.schema_version != LIVE_SCORER_SCHEMA_VERSION:
            raise ContractValidationError(f"scorer.schema_version must equal {LIVE_SCORER_SCHEMA_VERSION}")
        for name, value in (
            ("schedule_version", self.schedule_version),
            ("completed_football_state_version", self.completed_football_state_version),
            ("qb_state_version", self.qb_state_version),
            ("qb_snapshot_version", self.qb_snapshot_version),
            ("resolved_expected_qb_version", self.resolved_expected_qb_version),
        ):
            require_string(value, f"scorer.{name}")
        validate_utc_timestamp(self.prediction_as_of_utc, "scorer.prediction_as_of_utc")
        validate_utc_timestamp(self.history_complete_through_utc, "scorer.history_complete_through_utc")
        prediction = datetime.fromisoformat(self.prediction_as_of_utc[:-1] + "+00:00")
        history = datetime.fromisoformat(self.history_complete_through_utc[:-1] + "+00:00")
        if history > prediction:
            raise ContractValidationError("completed football history cannot extend past prediction_as_of_utc")
        for field, versions in (
            ("frozen_model_artifact_versions", self.frozen_model_artifact_versions),
            ("feature_state_versions", self.feature_state_versions),
        ):
            if not isinstance(versions, Mapping) or not versions:
                raise ContractValidationError(f"scorer.{field} must be a non-empty mapping")
            for key, value in versions.items():
                require_string(str(key), f"scorer.{field}.key")
                require_string(value, f"scorer.{field}.{key}")
        return self


@dataclass(frozen=True)
class ExpectedQBResolution:
    team: str
    game_id: str
    expected_starter: str | None
    sleeper_player_id: str | None
    canonical_qb_id: str | None
    gsis_id: str | None
    model_qb_state_id: str | None
    depth_designation: str | None
    injury_status: str | None
    source_snapshot_at_utc: str | None
    provenance_id: str
    resolution_status: str
    freshness_state: str
    source_warning_state: str | None = None
    schema_version: str = QB_RESOLVER_SCHEMA_VERSION

    def validate(self) -> "ExpectedQBResolution":
        if self.schema_version != QB_RESOLVER_SCHEMA_VERSION:
            raise ContractValidationError(f"qb.schema_version must equal {QB_RESOLVER_SCHEMA_VERSION}")
        require_string(self.team, "qb.team")
        require_string(self.game_id, "qb.game_id")
        require_string(self.provenance_id, "qb.provenance_id")
        require_enum(self.resolution_status, QB_RESOLUTION_STATUSES, "qb.resolution_status")
        require_enum(self.freshness_state, FRESHNESS_STATES, "qb.freshness_state")
        validate_utc_timestamp(self.source_snapshot_at_utc, "qb.source_snapshot_at_utc", nullable=True)
        if self.resolution_status in {"RESOLVED", "OVERRIDDEN"}:
            if not self.expected_starter or not self.canonical_qb_id or not self.model_qb_state_id:
                raise ContractValidationError(
                    "resolved expected QB requires expected_starter, canonical_qb_id, and model_qb_state_id"
                )
        return self


@dataclass(frozen=True)
class QBStarterChangeEvent:
    game_id: str
    team: str
    previous_provenance_id: str
    new_provenance_id: str
    previous_canonical_qb_id: str | None
    new_canonical_qb_id: str | None
    changed_at_utc: str
    rescore_required: bool = True

    def validate(self) -> "QBStarterChangeEvent":
        for name, value in (
            ("game_id", self.game_id),
            ("team", self.team),
            ("previous_provenance_id", self.previous_provenance_id),
            ("new_provenance_id", self.new_provenance_id),
        ):
            require_string(value, f"qb_change.{name}")
        validate_utc_timestamp(self.changed_at_utc, "qb_change.changed_at_utc")
        if self.previous_provenance_id == self.new_provenance_id:
            raise ContractValidationError("starter change must preserve distinct old and new provenance")
        if not self.rescore_required:
            raise ContractValidationError("starter change must mark the affected game for rescore")
        return self


@dataclass(frozen=True)
class QBOverrideAudit:
    game_id: str
    team: str
    previous_canonical_qb_id: str | None
    new_canonical_qb_id: str
    reason: str
    evidence_source: str
    operator: str
    changed_at_utc: str
    previous_provenance_id: str
    new_provenance_id: str
    rescore_required: bool = True

    def validate(self) -> "QBOverrideAudit":
        for name, value in (
            ("game_id", self.game_id),
            ("team", self.team),
            ("new_canonical_qb_id", self.new_canonical_qb_id),
            ("reason", self.reason),
            ("evidence_source", self.evidence_source),
            ("operator", self.operator),
            ("previous_provenance_id", self.previous_provenance_id),
            ("new_provenance_id", self.new_provenance_id),
        ):
            require_string(value, f"qb_override.{name}")
        validate_utc_timestamp(self.changed_at_utc, "qb_override.changed_at_utc")
        if self.previous_provenance_id == self.new_provenance_id:
            raise ContractValidationError("override must create new provenance; silent edit is forbidden")
        if not self.rescore_required:
            raise ContractValidationError("QB override must mark the affected game for rescore")
        return self
