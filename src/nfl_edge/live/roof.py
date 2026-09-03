"""Narrow live roof-state resolution for frozen football inference."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

ROOF_STRUCTURES = frozenset({"FIXED", "OUTDOOR", "RETRACTABLE"})
ROOF_STATUSES = frozenset({"OPEN", "CLOSED", "PENDING"})
FROZEN_RETRACTABLE_CATEGORIES = {"OPEN": "open", "CLOSED": "closed"}
FIXED_CATEGORIES = frozenset({"dome", "outdoors"})
DEFAULT_ROOF_STATUS_PATH = Path("config/live_roof_status_v1.json")


class LiveRoofError(RuntimeError):
    pass


@dataclass(frozen=True)
class RoofResolution:
    game_id: str
    structure: str
    status: str
    source: str
    source_at_utc: str
    model_category: str | None
    override_applied: bool = False

    def provenance(self) -> dict[str, Any]:
        return {
            "roof_structure": self.structure,
            "roof_resolution_status": self.status,
            "roof_source": self.source,
            "roof_source_at_utc": self.source_at_utc,
            "roof_model_category": self.model_category,
            "roof_override_applied": self.override_applied,
        }


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise LiveRoofError(f"{field} must be a non-empty string")
    return text


def load_roof_statuses(path: str | Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "NFL_EDGE_LIVE_ROOF_STATUS_V1":
        raise LiveRoofError("live roof-status schema drift")
    records = payload.get("games")
    if not isinstance(records, list):
        raise LiveRoofError("live roof-status games must be a list")
    result: dict[str, dict[str, Any]] = {}
    required = {"game_id", "status", "source", "source_at_utc"}
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != required:
            raise LiveRoofError(f"roof status[{index}] fields drift")
        game_id = _required_text(record["game_id"], f"roof status[{index}].game_id")
        if game_id in result:
            raise LiveRoofError(f"duplicate roof status for {game_id}")
        status = str(record["status"]).upper()
        if status not in ROOF_STATUSES:
            raise LiveRoofError(f"unsupported roof status {record['status']!r}")
        result[game_id] = {
            "status": status,
            "source": _required_text(record["source"], f"roof status[{index}].source"),
            "source_at_utc": _required_text(
                record["source_at_utc"], f"roof status[{index}].source_at_utc"
            ),
        }
    return result


class RoofResolver:
    """Resolve static venue structure separately from current roof position."""

    def __init__(
        self,
        statuses: Mapping[str, Mapping[str, Any]],
        *,
        overrides: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self._statuses = {str(k): dict(v) for k, v in statuses.items()}
        self._overrides = {str(k): dict(v) for k, v in (overrides or {}).items()}

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        overrides: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> "RoofResolver":
        return cls(load_roof_statuses(path), overrides=overrides)

    def resolve(self, game: Mapping[str, Any]) -> RoofResolution:
        game_id = str(game["game_id"])
        structure = str(game.get("roof_structure") or "").upper()
        if structure not in ROOF_STRUCTURES:
            raise LiveRoofError(f"{game_id}: unsupported roof structure {structure!r}")

        static_category = game.get("roof_type")
        if structure == "OUTDOOR":
            if static_category != "outdoors":
                raise LiveRoofError(f"{game_id}: OUTDOOR venue must use outdoors")
            return RoofResolution(
                game_id, structure, "OPEN", "static venue structure",
                str(game["context_source_at_utc"]), "outdoors"
            )
        if structure == "FIXED":
            if static_category != "dome":
                raise LiveRoofError(f"{game_id}: FIXED venue must use dome")
            return RoofResolution(
                game_id, structure, "CLOSED", "static venue structure",
                str(game["context_source_at_utc"]), "dome"
            )
        if static_category is not None:
            raise LiveRoofError(f"{game_id}: RETRACTABLE venue cannot carry a fixed roof_type")

        record = self._overrides.get(game_id) or self._statuses.get(game_id)
        override_applied = game_id in self._overrides
        if record is None:
            raise LiveRoofError(f"{game_id}: retractable roof status is missing")
        status = str(record.get("status") or "").upper()
        if status not in ROOF_STATUSES:
            raise LiveRoofError(f"{game_id}: unsupported roof status {status!r}")
        source = _required_text(record.get("source"), f"{game_id}.source")
        source_at = _required_text(record.get("source_at_utc"), f"{game_id}.source_at_utc")
        return RoofResolution(
            game_id=game_id,
            structure=structure,
            status=status,
            source=source,
            source_at_utc=source_at,
            model_category=FROZEN_RETRACTABLE_CATEGORIES.get(status),
            override_applied=override_applied,
        )
