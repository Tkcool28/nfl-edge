"""Production expected-QB resolver backed by the existing Sleeper QB audit.

The resolver is deliberately source-only: it never calls Sleeper, never reads
markets, and never guesses an identity. It consumes the normalized artifacts
already produced by ``scripts/collect_sleeper_qbs.py`` and fails closed when
stable identity or expected-starter evidence is insufficient.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import polars as pl
import yaml

from nfl_edge.contracts.runtime_interfaces_v1 import (
    ExpectedQBResolution,
    QBOverrideAudit,
    QBStarterChangeEvent,
)
from nfl_edge.data.integrity import normalize_team

SOURCE_NAME = "sleeper_qb_audit_v1"
OVERRIDE_SCHEMA_VERSION = "nfl-edge-live-qb-overrides-v1"
DEFAULT_AUDIT_ROOT = Path("data/source_audits/sleeper_qb_v1")
DEFAULT_CONFIG = Path("config/sleeper_qb_audit_v1.yaml")
DEFAULT_OVERRIDES = Path("config/live_qb_overrides_v1.json")
STABLE_MATCH_METHODS = frozenset({
    "exact_sleeper_id", "exact_gsis_id", "exact_espn_id", "exact_other_provider_id",
})
EXPECTED_TOP_STATES = frozenset({
    "DEPTH_CHART_EXPECTED_HEALTHY",
    "DEPTH_CHART_EXPECTED_LIMITED",
    "DEPTH_CHART_EXPECTED_QUESTIONABLE",
})
UNAVAILABLE_TOP_STATES = frozenset({
    "DEPTH_CHART_EXPECTED_DOUBTFUL", "DEPTH_CHART_EXPECTED_OUT",
})
SOURCE_FAILURE_OUTCOMES = frozenset({
    "TRANSPORT_FAILURE", "INCOMPLETE_RESPONSE", "NORMALIZATION_FAILURE",
    "REFERENCE_FAILURE", "PERSISTENCE_FAILURE", "LOCK_FAILURE",
})


class LiveQBResolverError(RuntimeError):
    """Raised when the live Sleeper source contract cannot be consumed safely."""


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise LiveQBResolverError(f"expected UTC timestamp, got {value!r}")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise LiveQBResolverError(f"invalid UTC timestamp: {value!r}") from exc


def _canonical_json_sha(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _nonnull(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip()
    return None if not token or token.lower() in {"none", "null", "nan"} else token


def _depth_order(row: Mapping[str, Any]) -> int | None:
    value = row.get("depth_chart_order")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes"}


def _empty_frame(columns: Iterable[str]) -> pl.DataFrame:
    return pl.DataFrame({name: [] for name in columns})


@dataclass(frozen=True)
class SleeperQBSource:
    audit_root: Path
    snapshot_id: str
    observed_at_utc: str
    staleness_threshold_seconds: float
    freshness_state: str
    age_seconds: float | None
    source_warning_state: str | None
    snapshots: pl.DataFrame
    crosswalk: pl.DataFrame
    evidence: pl.DataFrame
    changes: pl.DataFrame

    @classmethod
    def load(
        cls,
        repo_root: str | Path,
        *,
        prediction_as_of_utc: str,
        config_path: str | Path = DEFAULT_CONFIG,
    ) -> "SleeperQBSource":
        root = Path(repo_root)
        config = yaml.safe_load((root / config_path).read_text(encoding="utf-8"))
        if config.get("version") != "sleeper-qb-audit-config-v1":
            raise LiveQBResolverError("Sleeper audit config version drift")
        audit_root = root / str(config.get("audit_root") or DEFAULT_AUDIT_ROOT)
        threshold = float(config["staleness_threshold_seconds"])
        if threshold <= 0:
            raise LiveQBResolverError("Sleeper staleness threshold must be positive")

        pointer_path = audit_root / "latest_snapshot.json"
        if not pointer_path.is_file():
            raise LiveQBResolverError(f"missing Sleeper latest pointer: {pointer_path}")
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        snapshot_id = _nonnull(pointer.get("snapshot_id"))
        if snapshot_id is None:
            raise LiveQBResolverError("Sleeper latest pointer has no snapshot_id")

        normalized = audit_root / "normalized"
        snapshots = pl.read_parquet(normalized / "qb_snapshots.parquet").filter(
            pl.col("snapshot_id").cast(pl.Utf8) == snapshot_id
        )
        crosswalk = pl.read_parquet(normalized / "qb_identity_crosswalk.parquet").filter(
            pl.col("snapshot_id").cast(pl.Utf8) == snapshot_id
        )
        evidence = pl.read_parquet(normalized / "qb_evidence_states.parquet").filter(
            pl.col("snapshot_id").cast(pl.Utf8) == snapshot_id
        )
        change_path = normalized / "qb_change_ledger.parquet"
        changes = pl.read_parquet(change_path) if change_path.is_file() else _empty_frame(())
        if snapshots.is_empty():
            raise LiveQBResolverError(f"Sleeper snapshot {snapshot_id} has no normalized QB rows")
        if snapshots["sleeper_player_id"].n_unique() != snapshots.height:
            raise LiveQBResolverError(f"Sleeper snapshot {snapshot_id} has duplicate player rows")
        if evidence.select("sleeper_player_id").n_unique() != evidence.height:
            raise LiveQBResolverError(f"Sleeper snapshot {snapshot_id} has duplicate evidence rows")
        if crosswalk.select("sleeper_player_id").n_unique() != crosswalk.height:
            raise LiveQBResolverError(f"Sleeper snapshot {snapshot_id} has duplicate crosswalk rows")

        observed_values = sorted({
            str(value) for value in snapshots["fetched_at_utc"].drop_nulls().unique().to_list()
        })
        if len(observed_values) != 1:
            raise LiveQBResolverError(
                f"Sleeper snapshot {snapshot_id} must have one fetched_at_utc; got {observed_values}"
            )
        observed = observed_values[0]
        prediction = _parse_utc(prediction_as_of_utc)
        observed_dt = _parse_utc(observed)
        age = max(0.0, (prediction - observed_dt).total_seconds())

        warning = None
        status_path = audit_root / "latest_run_status.json"
        if status_path.is_file():
            status = json.loads(status_path.read_text(encoding="utf-8"))
            outcome = _nonnull(status.get("run_outcome") or status.get("outcome"))
            if outcome and outcome != "SUCCESS":
                warning = outcome
        if warning in SOURCE_FAILURE_OUTCOMES:
            freshness = "UNAVAILABLE"
            age_for_contract = None
        elif age < threshold * 0.5:
            freshness = "FRESH"
            age_for_contract = age
        elif age <= threshold:
            freshness = "AGING"
            age_for_contract = age
        else:
            freshness = "STALE"
            age_for_contract = age
        return cls(
            audit_root=audit_root,
            snapshot_id=snapshot_id,
            observed_at_utc=observed,
            staleness_threshold_seconds=threshold,
            freshness_state=freshness,
            age_seconds=age_for_contract,
            source_warning_state=warning,
            snapshots=snapshots,
            crosswalk=crosswalk,
            evidence=evidence,
            changes=changes,
        )

    def freshness_contract(self) -> dict[str, Any]:
        if self.freshness_state == "UNAVAILABLE":
            return {
                "state": "UNAVAILABLE",
                "observed_at_utc": None,
                "age_seconds": None,
                "threshold_seconds": self.staleness_threshold_seconds,
            }
        return {
            "state": self.freshness_state,
            "observed_at_utc": self.observed_at_utc,
            "age_seconds": float(self.age_seconds or 0.0),
            "threshold_seconds": self.staleness_threshold_seconds,
        }


def load_overrides(path: str | Path) -> dict[tuple[str, str], dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return {}
    payload = json.loads(p.read_text(encoding="utf-8"))
    if payload.get("schema_version") != OVERRIDE_SCHEMA_VERSION:
        raise LiveQBResolverError("live QB override schema drift")
    rows = payload.get("overrides")
    if not isinstance(rows, list):
        raise LiveQBResolverError("live QB overrides must be an array")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    required = {
        "game_id", "team", "expected_starter", "sleeper_player_id", "canonical_qb_id",
        "gsis_id", "reason", "evidence_source", "operator", "changed_at_utc",
    }
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != required:
            raise LiveQBResolverError(f"override[{index}] fields drift")
        key = (str(row["game_id"]), str(normalize_team(row["team"])))
        if key in result:
            raise LiveQBResolverError(f"duplicate live QB override: {key}")
        for field in ("game_id", "team", "expected_starter", "canonical_qb_id", "reason", "evidence_source", "operator"):
            if not _nonnull(row.get(field)):
                raise LiveQBResolverError(f"override[{index}].{field} is required")
        _parse_utc(str(row["changed_at_utc"]))
        result[key] = dict(row)
    return result


class SleeperExpectedQBResolver:
    def __init__(
        self,
        source: SleeperQBSource,
        *,
        overrides: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
    ) -> None:
        self.source = source
        self.overrides = {tuple(key): dict(value) for key, value in (overrides or {}).items()}
        self._evidence = {
            str(row["sleeper_player_id"]): str(row["evidence_state"])
            for row in source.evidence.to_dicts()
        }
        self._crosswalk = {
            str(row["sleeper_player_id"]): row for row in source.crosswalk.to_dicts()
        }

    def _provenance(self, payload: Mapping[str, Any]) -> str:
        return f"sleeper-qb-live:{_canonical_json_sha(payload)[:24]}"

    def _last_changed(self, *, team: str, sleeper_player_id: str | None) -> str | None:
        if sleeper_player_id is None or self.source.changes.is_empty():
            return None
        needed = {"sleeper_player_id", "team", "first_observed_changed_at_utc"}
        if not needed.issubset(self.source.changes.columns):
            return None
        rows = self.source.changes.filter(
            (pl.col("sleeper_player_id").cast(pl.Utf8) == sleeper_player_id)
            & (pl.col("team").cast(pl.Utf8) == team)
        )
        if rows.is_empty():
            return None
        values = [str(x) for x in rows["first_observed_changed_at_utc"].drop_nulls().to_list()]
        return max(values) if values else None

    def _unresolved(
        self,
        *,
        game_id: str,
        team: str,
        status: str,
        warning: str,
        row: Mapping[str, Any] | None = None,
    ) -> ExpectedQBResolution:
        row = row or {}
        pid = _nonnull(row.get("sleeper_player_id"))
        payload = {
            "snapshot_id": self.source.snapshot_id,
            "game_id": game_id,
            "team": team,
            "pid": pid,
            "status": status,
            "warning": warning,
        }
        return ExpectedQBResolution(
            team=team,
            game_id=game_id,
            expected_starter=_nonnull(row.get("full_name")),
            sleeper_player_id=pid,
            canonical_qb_id=None,
            gsis_id=_nonnull(row.get("gsis_id")),
            model_qb_state_id=None,
            depth_designation=(
                f"{_nonnull(row.get('depth_chart_position')) or 'QB'}:{_depth_order(row)}"
                if _depth_order(row) is not None else _nonnull(row.get("depth_chart_position"))
            ),
            injury_status=_nonnull(row.get("injury_status")),
            source_snapshot_at_utc=self.source.observed_at_utc,
            provenance_id=self._provenance(payload),
            resolution_status=status,
            freshness_state=self.source.freshness_state,
            source_warning_state=warning,
        ).validate()

    def _choose_candidate(
        self, game_id: str, team: str
    ) -> tuple[Mapping[str, Any] | None, str | None, str | None]:
        rows = [
            row for row in self.source.snapshots.to_dicts()
            if normalize_team(row.get("team")) == team
        ]
        if not rows:
            return None, "MISSING_EVIDENCE", "NO_TEAM_QB_EVIDENCE"
        enriched = []
        for row in rows:
            item = dict(row)
            item["_evidence_state"] = self._evidence.get(
                str(row.get("sleeper_player_id")), "UNKNOWN"
            )
            enriched.append(item)
        top = [row for row in enriched if _depth_order(row) == 1]
        if any(row["_evidence_state"] == "AMBIGUOUS" for row in top):
            return None, "AMBIGUOUS", "SLEEPER_TOP_DEPTH_CONFLICT"
        viable = [row for row in top if row["_evidence_state"] in EXPECTED_TOP_STATES]
        if len(viable) == 1:
            return viable[0], None, None
        if len(viable) > 1:
            return None, "AMBIGUOUS", "MULTIPLE_TOP_DEPTH_QBS"
        if top and all(row["_evidence_state"] in UNAVAILABLE_TOP_STATES for row in top):
            backups = [
                row for row in enriched
                if (_depth_order(row) or 999) >= 2
                and row["_evidence_state"] == "BACKUP_CANDIDATE"
                and str(row.get("injury_status") or "").strip().lower()
                not in {"out", "doubtful"}
            ]
            if backups:
                best_order = min(_depth_order(row) or 999 for row in backups)
                best = [row for row in backups if (_depth_order(row) or 999) == best_order]
                if len(best) == 1:
                    return best[0], None, "DEPTH1_UNAVAILABLE_BACKUP_PROMOTION"
                return None, "AMBIGUOUS", "MULTIPLE_BACKUP_CANDIDATES"
        if top:
            return None, "UNRESOLVED", "TOP_DEPTH_QB_NOT_ACTIONABLE"
        return None, "MISSING_EVIDENCE", "NO_DEPTH1_QB_EVIDENCE"

    def _stable_identity(
        self, row: Mapping[str, Any]
    ) -> tuple[str | None, str, str | None]:
        pid = str(row["sleeper_player_id"])
        xwalk = self._crosswalk.get(pid)
        if xwalk is not None:
            conflict = _nonnull(xwalk.get("conflict_reason"))
            if conflict:
                return None, "AMBIGUOUS", f"IDENTITY_CONFLICT:{conflict}"
            method = str(xwalk.get("match_method") or "")
            matched = _bool(xwalk.get("is_matched"))
            review = _bool(xwalk.get("review_required"))
            if matched and not review and method in STABLE_MATCH_METHODS:
                canonical = _nonnull(xwalk.get("gsis_id")) or _nonnull(
                    xwalk.get("nflverse_player_id")
                )
                if canonical:
                    return canonical, "RESOLVED", None
            if method == "name_team_fallback" or review:
                return None, "UNRESOLVED", "NON_STABLE_IDENTITY_REQUIRES_REVIEW"
        source_gsis = _nonnull(row.get("gsis_id"))
        years_exp = row.get("years_exp")
        try:
            rookie = years_exp is not None and int(years_exp) == 0
        except (TypeError, ValueError):
            rookie = False
        if source_gsis and rookie:
            return source_gsis, "NEW_PLAYER", "NEW_PLAYER_DIRECT_GSIS_ID"
        return None, "UNRESOLVED", "NO_STABLE_CANONICAL_IDENTITY"

    def resolve_team(
        self, *, game_id: str, team: str
    ) -> tuple[ExpectedQBResolution, QBOverrideAudit | None]:
        canonical_team = str(normalize_team(team))
        selected, terminal, candidate_warning = self._choose_candidate(game_id, canonical_team)
        if selected is None:
            base = self._unresolved(
                game_id=game_id,
                team=canonical_team,
                status=terminal or "UNRESOLVED",
                warning=candidate_warning or "UNRESOLVED_QB",
            )
        else:
            canonical_id, status, identity_warning = self._stable_identity(selected)
            if canonical_id is None:
                base = self._unresolved(
                    game_id=game_id,
                    team=canonical_team,
                    status=status,
                    warning=identity_warning or candidate_warning or "UNRESOLVED_QB",
                    row=selected,
                )
            else:
                pid = _nonnull(selected.get("sleeper_player_id"))
                warning_parts = [
                    x for x in (
                        candidate_warning,
                        identity_warning,
                        self.source.source_warning_state,
                    ) if x
                ]
                warning = ";".join(warning_parts) if warning_parts else None
                payload = {
                    "snapshot_id": self.source.snapshot_id,
                    "game_id": game_id,
                    "team": canonical_team,
                    "pid": pid,
                    "canonical_id": canonical_id,
                    "status": status,
                    "warning": warning,
                }
                base = ExpectedQBResolution(
                    team=canonical_team,
                    game_id=game_id,
                    expected_starter=_nonnull(selected.get("full_name")),
                    sleeper_player_id=pid,
                    canonical_qb_id=canonical_id,
                    gsis_id=_nonnull(selected.get("gsis_id")) or canonical_id,
                    model_qb_state_id=canonical_id,
                    depth_designation=(
                        f"{_nonnull(selected.get('depth_chart_position')) or 'QB'}:{_depth_order(selected)}"
                    ),
                    injury_status=_nonnull(selected.get("injury_status")),
                    source_snapshot_at_utc=self.source.observed_at_utc,
                    provenance_id=self._provenance(payload),
                    resolution_status=status,
                    freshness_state=self.source.freshness_state,
                    source_warning_state=warning,
                ).validate()

        override = self.overrides.get((game_id, canonical_team))
        if override is None:
            return base, None
        previous_provenance = base.provenance_id
        new_id = str(override["canonical_qb_id"])
        override_payload = {
            "base_provenance": previous_provenance,
            "snapshot_id": self.source.snapshot_id,
            **dict(override),
        }
        new_provenance = f"sleeper-qb-override:{_canonical_json_sha(override_payload)[:24]}"
        resolved = replace(
            base,
            expected_starter=str(override["expected_starter"]),
            sleeper_player_id=_nonnull(override.get("sleeper_player_id")),
            canonical_qb_id=new_id,
            gsis_id=_nonnull(override.get("gsis_id")) or new_id,
            model_qb_state_id=new_id,
            provenance_id=new_provenance,
            resolution_status="OVERRIDDEN",
            source_warning_state="MANUAL_OVERRIDE",
        ).validate()
        audit = QBOverrideAudit(
            game_id=game_id,
            team=canonical_team,
            previous_canonical_qb_id=base.canonical_qb_id,
            new_canonical_qb_id=new_id,
            reason=str(override["reason"]),
            evidence_source=str(override["evidence_source"]),
            operator=str(override["operator"]),
            changed_at_utc=str(override["changed_at_utc"]),
            previous_provenance_id=previous_provenance,
            new_provenance_id=new_provenance,
        ).validate()
        return resolved, audit

    def resolve_game(self, game: Mapping[str, Any]) -> dict[str, Any]:
        game_id = str(game["game_id"])
        home, home_override = self.resolve_team(
            game_id=game_id, team=str(game["home_team"])
        )
        away, away_override = self.resolve_team(
            game_id=game_id, team=str(game["away_team"])
        )
        return {
            "home": home,
            "away": away,
            "overrides": [
                audit for audit in (home_override, away_override) if audit is not None
            ],
        }

    def to_product_context(self, resolution: ExpectedQBResolution) -> dict[str, Any]:
        last_changed = self._last_changed(
            team=resolution.team, sleeper_player_id=resolution.sleeper_player_id
        )
        return {
            "team": resolution.team,
            "game_id": resolution.game_id,
            "expected_starter": resolution.expected_starter,
            "sleeper_player_id": resolution.sleeper_player_id,
            "canonical_qb_id": resolution.canonical_qb_id,
            "gsis_id": resolution.gsis_id,
            "depth_designation": resolution.depth_designation,
            "injury_status": resolution.injury_status,
            "source": SOURCE_NAME,
            "source_snapshot_at_utc": resolution.source_snapshot_at_utc,
            "provenance_id": resolution.provenance_id,
            "resolution_status": resolution.resolution_status,
            "freshness": self.source.freshness_contract(),
            "warning_state": resolution.source_warning_state,
            "last_changed_at_utc": last_changed,
        }


def detect_starter_change(
    previous: ExpectedQBResolution,
    current: ExpectedQBResolution,
    *,
    changed_at_utc: str,
) -> QBStarterChangeEvent | None:
    if previous.game_id != current.game_id or previous.team != current.team:
        raise LiveQBResolverError("starter-change comparison identities do not match")
    if (
        previous.canonical_qb_id == current.canonical_qb_id
        and previous.provenance_id == current.provenance_id
    ):
        return None
    return QBStarterChangeEvent(
        game_id=current.game_id,
        team=current.team,
        previous_provenance_id=previous.provenance_id,
        new_provenance_id=current.provenance_id,
        previous_canonical_qb_id=previous.canonical_qb_id,
        new_canonical_qb_id=current.canonical_qb_id,
        changed_at_utc=changed_at_utc,
    ).validate()
