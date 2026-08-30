"""Frozen-data Oracle QB resolver for the authorized 2025 holdout.

This module is intentionally a narrow bridge between the PR70 Oracle-QB input
artifact and the already-frozen QB-Elo holdout adapter.  It does not infer a
starter, calculate a new QB adjustment, read results, or authorize the
holdout.  Construction reads the supplied 2025 parquet, so callers must create
this resolver only *after* the one-shot authorization/spend gate has opened the
holdout.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

import polars as pl

EXPECTED_ARTIFACT_RELATIVE_PATH = (
    "data/derived/oracle_qb_entering_state_2025_v1/"
    "oracle_qb_pregame_adjustments_by_game_2025_v1.parquet"
)
EXPECTED_ARTIFACT_SHA256 = (
    "8e73dfab9ffd84bf4a926f55dd757de2c59ca81d0462a0ed422ac6c53e58d84d"
)
EXPECTED_GAMES = 285
EXPECTED_HISTORICAL_MODEL_USAGE = "ORACLE_STARTER_IDENTITY_ONLY"
EXPECTED_STARTER_EVIDENCE_CLASS = "POSTGAME_ACTUAL_STARTER"
IMPLEMENTATION = "TASK05G_2025_FROZEN_ORACLE_ARTIFACT_RESOLVER_V1"

_REQUIRED_COLUMNS = {
    "game_id",
    "away_qb_adjustment_elo",
    "home_qb_adjustment_elo",
    "historical_model_usage",
    "starter_evidence_class",
}


class OracleQBResolver2025Error(RuntimeError):
    """Raised when the frozen PR70 Oracle-QB artifact contract drifts."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FrozenOracleQBGameResolver2025:
    """Callable game-id -> ``(home_adjustment, away_adjustment)`` resolver.

    The object implements the provenance/coverage protocol consumed by
    ``predict_oracle_qb_elo_block``.  Only the two already-materialized Elo
    adjustments are exposed to the QB-Elo predictor.
    """

    def __init__(self, artifact_path: str | Path, *, repo_root: str | Path | None = None) -> None:
        self._path = Path(artifact_path)
        if not self._path.is_file():
            raise OracleQBResolver2025Error(f"Oracle QB artifact not found: {self._path}")
        digest = _sha256(self._path)
        if digest != EXPECTED_ARTIFACT_SHA256:
            raise OracleQBResolver2025Error(
                f"Oracle QB artifact SHA-256 {digest} != frozen {EXPECTED_ARTIFACT_SHA256}"
            )

        frame = pl.read_parquet(
            self._path,
            columns=sorted(_REQUIRED_COLUMNS),
        )
        missing = sorted(_REQUIRED_COLUMNS - set(frame.columns))
        if missing:
            raise OracleQBResolver2025Error(f"Oracle QB artifact missing columns: {missing}")
        if frame.height != EXPECTED_GAMES or frame["game_id"].n_unique() != EXPECTED_GAMES:
            raise OracleQBResolver2025Error(
                f"Oracle QB artifact must contain {EXPECTED_GAMES} unique games: rows={frame.height}"
            )
        if frame["game_id"].null_count():
            raise OracleQBResolver2025Error("Oracle QB artifact contains null game_id")
        if frame["home_qb_adjustment_elo"].null_count() or frame["away_qb_adjustment_elo"].null_count():
            raise OracleQBResolver2025Error("Oracle QB artifact contains null Elo adjustment")
        if set(str(x) for x in frame["historical_model_usage"].unique().to_list()) != {
            EXPECTED_HISTORICAL_MODEL_USAGE
        }:
            raise OracleQBResolver2025Error("Oracle QB historical_model_usage drift")
        if set(str(x) for x in frame["starter_evidence_class"].unique().to_list()) != {
            EXPECTED_STARTER_EVIDENCE_CLASS
        }:
            raise OracleQBResolver2025Error("Oracle QB starter_evidence_class drift")

        self._adjustments = {
            str(row["game_id"]): (
                float(row["home_qb_adjustment_elo"]),
                float(row["away_qb_adjustment_elo"]),
            )
            for row in frame.select(
                "game_id", "home_qb_adjustment_elo", "away_qb_adjustment_elo"
            ).to_dicts()
        }
        root = None if repo_root is None else Path(repo_root).resolve()
        try:
            relative = str(self._path.resolve().relative_to(root)) if root is not None else str(self._path)
        except ValueError:
            relative = str(self._path)
        self._artifact_identity = relative.replace("\\", "/")

    def __call__(self, game_id: str) -> tuple[float, float]:
        gid = str(game_id)
        try:
            return self._adjustments[gid]
        except KeyError as exc:
            raise OracleQBResolver2025Error(f"Oracle QB adjustment missing game_id {gid}") from exc

    def assert_coverage(self, game_ids: Iterable[str], *, where: str = "oracle_qb_2025") -> None:
        requested = [str(game_id) for game_id in game_ids]
        if len(requested) != len(set(requested)):
            raise OracleQBResolver2025Error(f"{where}: duplicate requested game_id")
        missing = sorted(set(requested) - set(self._adjustments))
        if missing:
            raise OracleQBResolver2025Error(f"{where}: missing Oracle QB game_id values: {missing[:12]}")

    def manifest_identity(self) -> dict[str, Any]:
        return {
            "mode": "ORACLE",
            "implementation": IMPLEMENTATION,
            "oracle_artifact_path": self._artifact_identity,
            "oracle_artifact_sha256": EXPECTED_ARTIFACT_SHA256,
            "historical_model_usage": EXPECTED_HISTORICAL_MODEL_USAGE,
            "starter_evidence_class": EXPECTED_STARTER_EVIDENCE_CLASS,
        }
