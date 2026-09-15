"""Runtime ingestion contract for settled 2026 football evidence.

This module deliberately separates postgame evidence from pregame scoring.
Only fully completed REG weeks strictly before the active week are eligible.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import polars as pl
import requests

from nfl_edge.contracts.runtime_interfaces_v1 import ExpectedQBResolution
from nfl_edge.features.pipeline import FeatureInputs
from nfl_edge.features.totals_v1.pbp_semantics import REQUIRED_PBP_COLUMNS
from nfl_edge.live.schedule_materializer_2026 import (
    NFLVERSE_GAMES_URL,
    build_week_schedule,
    choose_active_schedule,
    fetch_nflverse_rows,
)

PLAYER_STATS_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2026.parquet"
)
TEAM_STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_2026.parquet"
PBP_URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_2026.parquet"
EVIDENCE_SCHEMA = "nfl-edge-settled-2026-evidence-v1"

# nflverse weekly team/player tables already use the frozen feature builders'
# canonical names. Keep that direct mapping explicit, and reject an upstream
# schema change instead of silently substituting null features.
REQUIRED_TEAM_STAT_COLUMNS = frozenset(
    {
        "game_id",
        "season",
        "week",
        "team",
        "passing_epa",
        "rushing_epa",
        "passing_yards",
        "rushing_yards",
    }
)
REQUIRED_QB_STAT_COLUMNS = frozenset(
    {
        "game_id",
        "season",
        "week",
        "team",
        "player_id",
        "position",
        "attempts",
        "sacks_suffered",
        "passing_epa",
        "passing_cpoe",
        "passing_interceptions",
    }
)


class SettledEvidenceError(RuntimeError):
    """Raised when current-season evidence is incomplete or internally inconsistent."""


@contextmanager
def _evidence_lock(root: Path, *, exclusive: bool):
    """Coordinate the materializer and production reader as one evidence set."""
    import fcntl

    root.mkdir(parents=True, exist_ok=True)
    with (root / ".live-inputs.lock").open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True)
class SettledSeasonEvidence:
    root: Path
    through_week: int
    observed_at_utc: str
    games: pl.DataFrame
    team_stats: pl.DataFrame
    qb_stats: pl.DataFrame
    pbp: pl.DataFrame
    manifest: dict[str, Any]

    def feature_inputs(self) -> FeatureInputs:
        return FeatureInputs(
            games=self.games,
            team_stats=self.team_stats,
            qb_stats=self.qb_stats,
            depth_charts=pl.DataFrame(),
            rosters=pl.DataFrame(),
        )


class SettledActualQBResolver:
    """Postgame-only resolver for advancing future model state.

    Actual starters are never exposed to the same game's live prediction.
    They are consumed only after the complete week is settled.
    """

    def __init__(self, games: pl.DataFrame, *, observed_at_utc: str) -> None:
        self.observed_at_utc = observed_at_utc
        self._games = {str(row["game_id"]): row for row in games.to_dicts()}

    def _side(self, *, game_id: str, team: str, side: str) -> ExpectedQBResolution:
        row = self._games.get(game_id)
        if row is None:
            raise SettledEvidenceError(f"settled QB resolver missing game {game_id}")
        qb_id = str(row.get(f"{side}_qb_id") or "").strip()
        qb_name = str(row.get(f"{side}_qb_name") or "").strip()
        if not qb_id or not qb_name:
            raise SettledEvidenceError(f"settled QB identity missing for {game_id} {side} ({team})")
        identity = f"{game_id}|{team}|{qb_id}|{self.observed_at_utc}".encode()
        provenance = "settled-actual-qb:" + hashlib.sha256(identity).hexdigest()[:24]
        return ExpectedQBResolution(
            team=team,
            game_id=game_id,
            expected_starter=qb_name,
            sleeper_player_id=None,
            canonical_qb_id=qb_id,
            gsis_id=qb_id,
            model_qb_state_id=qb_id,
            depth_designation="POSTGAME_ACTUAL_STARTER",
            injury_status=None,
            source_snapshot_at_utc=self.observed_at_utc,
            provenance_id=provenance,
            resolution_status="RESOLVED",
            freshness_state="FRESH",
            source_warning_state=None,
        ).validate()

    def resolve_game(self, game: Mapping[str, Any]) -> dict[str, Any]:
        game_id = str(game["game_id"])
        return {
            "home": self._side(game_id=game_id, team=str(game["home_team"]), side="home"),
            "away": self._side(game_id=game_id, team=str(game["away_team"]), side="away"),
            "overrides": [],
        }

    def to_product_context(self, resolution: ExpectedQBResolution) -> dict[str, Any]:
        return {
            "team": resolution.team,
            "game_id": resolution.game_id,
            "expected_starter": resolution.expected_starter,
            "sleeper_player_id": None,
            "canonical_qb_id": resolution.canonical_qb_id,
            "gsis_id": resolution.gsis_id,
            "depth_designation": resolution.depth_designation,
            "injury_status": None,
            "source": "NFLVERSE_SETTLED_ACTUAL_QB",
            "source_snapshot_at_utc": resolution.source_snapshot_at_utc,
            "provenance_id": resolution.provenance_id,
            "resolution_status": resolution.resolution_status,
            "freshness": {
                "state": "FRESH",
                "observed_at_utc": self.observed_at_utc,
                "age_seconds": 0.0,
                "threshold_seconds": 0.0,
            },
            "warning_state": None,
            "last_changed_at_utc": None,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _download_parquet(url: str, *, session: requests.Session | None = None) -> tuple[pl.DataFrame, str]:
    client = session or requests.Session()
    response = client.get(url, timeout=60)
    response.raise_for_status()
    raw = response.content
    if not raw:
        raise SettledEvidenceError(f"empty upstream parquet: {url}")
    try:
        frame = pl.read_parquet(io.BytesIO(raw))
    except Exception as exc:  # pragma: no cover - dependency-specific parse errors
        raise SettledEvidenceError(f"cannot parse upstream parquet: {url}") from exc
    return frame, _sha(raw)


def _write_parquet_atomic(path: Path, frame: pl.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}-", delete=False) as handle:
            temp = Path(handle.name)
        frame.write_parquet(temp)
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}-", delete=False) as handle:
            temp = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def _canonical_games(rows: list[Mapping[str, Any]], *, through_week: int) -> pl.DataFrame:
    selected: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("season") or "") != "2026" or str(row.get("game_type") or "").upper() != "REG":
            continue
        week = int(float(str(row.get("week") or "0")))
        if week < 1 or week > through_week:
            continue
        home_score = row.get("home_score")
        away_score = row.get("away_score")
        if home_score in (None, "") or away_score in (None, ""):
            raise SettledEvidenceError(f"2026 REG Week {week} is not fully settled")
        away = str(row.get("away_team") or "").strip()
        home = str(row.get("home_team") or "").strip()
        if not away or not home:
            raise SettledEvidenceError("settled game is missing canonical teams")
        selected.append(
            {
                "game_id": f"2026_{week:02d}_{away}_{home}",
                "season": 2026,
                "season_type": "REG",
                "week": week,
                "gameday": str(row.get("gameday") or "")[:10],
                "home_team": home,
                "away_team": away,
                "home_score": int(float(str(home_score))),
                "away_score": int(float(str(away_score))),
                "target_available": True,
                "target_margin": int(float(str(home_score))) - int(float(str(away_score))),
                "target_home_win": int(float(str(home_score))) > int(float(str(away_score))),
                "target_tie": int(float(str(home_score))) == int(float(str(away_score))),
                "target_total_points": int(float(str(home_score))) + int(float(str(away_score))),
                "home_qb_id": str(row.get("home_qb_id") or "").strip() or None,
                "away_qb_id": str(row.get("away_qb_id") or "").strip() or None,
                "home_qb_name": str(row.get("home_qb_name") or "").strip() or None,
                "away_qb_name": str(row.get("away_qb_name") or "").strip() or None,
                "roof_actual": str(row.get("roof") or "").strip().lower() or None,
            }
        )
    frame = pl.DataFrame(selected)
    if through_week == 0:
        return frame
    weeks = sorted(set(frame["week"].to_list())) if frame.height else []
    if weeks != list(range(1, through_week + 1)):
        raise SettledEvidenceError(f"settled 2026 game evidence has week gaps: expected 1..{through_week}, got {weeks}")
    duplicates = frame.group_by("game_id").len().filter(pl.col("len") > 1)
    if duplicates.height:
        raise SettledEvidenceError("settled game evidence has duplicate game_id")
    return frame.sort(["week", "game_id"])


def _filter_stats(
    frame: pl.DataFrame,
    *,
    game_ids: set[str],
    kind: str,
) -> pl.DataFrame:
    required = REQUIRED_QB_STAT_COLUMNS if kind == "player" else REQUIRED_TEAM_STAT_COLUMNS
    missing = sorted(required - set(frame.columns))
    if missing:
        raise SettledEvidenceError(f"{kind} stats missing required columns: {missing}")
    selected = frame.filter((pl.col("season") == 2026) & pl.col("game_id").cast(pl.Utf8).is_in(sorted(game_ids)))
    if kind == "player":
        if "position" in selected.columns:
            selected = selected.filter(pl.col("position").cast(pl.Utf8).str.to_uppercase() == "QB")
    return selected


def validate_settled_evidence(
    *,
    games: pl.DataFrame,
    team_stats: pl.DataFrame,
    qb_stats: pl.DataFrame,
    pbp: pl.DataFrame,
    through_week: int,
) -> None:
    if through_week == 0:
        return
    game_ids = set(str(x) for x in games["game_id"].to_list())
    expected_team_keys = {
        (str(row["game_id"]), str(team))
        for row in games.iter_rows(named=True)
        for team in (row["home_team"], row["away_team"])
    }
    actual_team_keys = set(
        (str(row["game_id"]), str(row["team"])) for row in team_stats.select("game_id", "team").iter_rows(named=True)
    )
    if actual_team_keys != expected_team_keys:
        missing = sorted(expected_team_keys - actual_team_keys)
        extra = sorted(actual_team_keys - expected_team_keys)
        raise SettledEvidenceError(f"team-stat coverage drift: missing={missing[:5]} extra={extra[:5]}")
    if not {"game_id", "player_id", "team"}.issubset(qb_stats.columns):
        raise SettledEvidenceError("QB stats contract missing identity columns")
    if qb_stats.filter(pl.col("player_id").is_not_null()).select("game_id", "team", "player_id").is_duplicated().sum():
        raise SettledEvidenceError("QB stats contain duplicate game/team/player rows")
    if "game_id" not in pbp.columns:
        raise SettledEvidenceError("PBP is missing game_id")
    missing_pbp_columns = sorted(set(REQUIRED_PBP_COLUMNS) - set(pbp.columns))
    if missing_pbp_columns:
        raise SettledEvidenceError(f"PBP is missing required totals columns: {missing_pbp_columns}")
    pbp_ids = set(str(x) for x in pbp["game_id"].drop_nulls().unique().to_list())
    missing_pbp = sorted(game_ids - pbp_ids)
    if missing_pbp:
        raise SettledEvidenceError(f"PBP coverage missing completed games: {missing_pbp[:5]}")
    incomplete_pbp = []
    for game_id in sorted(game_ids):
        game_pbp = pbp.filter(pl.col("game_id").cast(pl.Utf8) == game_id)
        final_rows = game_pbp.filter(
            (pl.col("qtr").cast(pl.Int64, strict=False) >= 4)
            & (pl.col("game_seconds_remaining").cast(pl.Float64, strict=False) == 0.0)
        )
        if final_rows.is_empty():
            incomplete_pbp.append(game_id)
    if incomplete_pbp:
        raise SettledEvidenceError(
            "PBP completion invariant missing final-clock row for completed games: "
            f"{incomplete_pbp[:5]}"
        )


def _materialize_settled_evidence(
    *,
    output_dir: str | Path,
    active_as_of_utc: str | None = None,
    session: requests.Session | None = None,
    schedule_rows: list[Mapping[str, Any]] | None = None,
) -> SettledSeasonEvidence:
    observed = _now()
    active_as_of = active_as_of_utc or observed
    rows = list(schedule_rows) if schedule_rows is not None else fetch_nflverse_rows(session=session)
    active = choose_active_schedule(
        rows,
        season=2026,
        active_as_of_utc=active_as_of,
        observed_at_utc=observed,
    )
    active_week = int(active["week"])
    through_week = active_week - 1

    root = Path(output_dir)
    # Preserve every schedule required for deterministic replay plus the active slate.
    for week in range(1, active_week + 1):
        payload = build_week_schedule(rows, season=2026, week=week, observed_at_utc=observed)
        _write_json_atomic(root / f"week{week}_schedule_v1.json", payload)

    games = _canonical_games(rows, through_week=through_week)
    if through_week == 0:
        empties = {
            "games": pl.DataFrame(
                {
                    "game_id": [],
                    "season": [],
                    "season_type": [],
                    "week": [],
                }
            ),
            "team_stats": pl.DataFrame(
                {
                    "game_id": [],
                    "season": [],
                    "week": [],
                    "team": [],
                }
            ),
            "qb_stats": pl.DataFrame(
                {
                    "game_id": [],
                    "season": [],
                    "week": [],
                    "team": [],
                    "player_id": [],
                }
            ),
            "pbp": pl.DataFrame({"game_id": []}),
        }
        manifest = {
            "schema_version": EVIDENCE_SCHEMA,
            "season": 2026,
            "active_week": active_week,
            "through_week": 0,
            "observed_at_utc": observed,
            "source_urls": {"schedule": NFLVERSE_GAMES_URL},
            "row_counts": {"games": 0, "team_stats": 0, "qb_stats": 0, "pbp": 0},
        }
        for name, frame in empties.items():
            _write_parquet_atomic(root / f"settled_{name}.parquet", frame)
        _write_json_atomic(root / "settled_evidence_manifest.json", manifest)
        return _load_settled_evidence(root)

    game_ids = set(str(x) for x in games["game_id"].to_list())
    team_raw, team_sha = _download_parquet(TEAM_STATS_URL, session=session)
    player_raw, player_sha = _download_parquet(PLAYER_STATS_URL, session=session)
    pbp_raw, pbp_sha = _download_parquet(PBP_URL, session=session)
    team_stats = _filter_stats(team_raw, game_ids=game_ids, kind="team")
    qb_stats = _filter_stats(player_raw, game_ids=game_ids, kind="player")
    pbp = pbp_raw.filter(pl.col("game_id").cast(pl.Utf8).is_in(sorted(game_ids)))

    validate_settled_evidence(
        games=games,
        team_stats=team_stats,
        qb_stats=qb_stats,
        pbp=pbp,
        through_week=through_week,
    )
    _write_parquet_atomic(root / "settled_games.parquet", games)
    _write_parquet_atomic(root / "settled_team_stats.parquet", team_stats)
    _write_parquet_atomic(root / "settled_qb_stats.parquet", qb_stats)
    _write_parquet_atomic(root / "settled_pbp.parquet", pbp)
    manifest = {
        "schema_version": EVIDENCE_SCHEMA,
        "season": 2026,
        "active_week": active_week,
        "through_week": through_week,
        "observed_at_utc": observed,
        "source_urls": {
            "schedule": NFLVERSE_GAMES_URL,
            "team_stats": TEAM_STATS_URL,
            "player_stats": PLAYER_STATS_URL,
            "pbp": PBP_URL,
        },
        "source_sha256": {
            "team_stats": team_sha,
            "player_stats": player_sha,
            "pbp": pbp_sha,
        },
        "row_counts": {
            "games": games.height,
            "team_stats": team_stats.height,
            "qb_stats": qb_stats.height,
            "pbp": pbp.height,
        },
    }
    _write_json_atomic(root / "settled_evidence_manifest.json", manifest)
    return _load_settled_evidence(root)


def materialize_settled_evidence(
    *,
    output_dir: str | Path,
    active_as_of_utc: str | None = None,
    session: requests.Session | None = None,
    schedule_rows: list[Mapping[str, Any]] | None = None,
) -> SettledSeasonEvidence:
    root = Path(output_dir)
    with _evidence_lock(root, exclusive=True):
        return _materialize_settled_evidence(
            output_dir=root,
            active_as_of_utc=active_as_of_utc,
            session=session,
            schedule_rows=schedule_rows,
        )


def _load_settled_evidence(root: str | Path) -> SettledSeasonEvidence:
    base = Path(root)
    manifest_path = base / "settled_evidence_manifest.json"
    if not manifest_path.is_file():
        raise SettledEvidenceError(f"missing settled evidence manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != EVIDENCE_SCHEMA or int(manifest.get("season", -1)) != 2026:
        raise SettledEvidenceError("settled evidence manifest identity drift")
    through_week = int(manifest.get("through_week", -1))
    if not 0 <= through_week <= 17:
        raise SettledEvidenceError("settled evidence through_week is invalid")
    frames = {}
    for name in ("games", "team_stats", "qb_stats", "pbp"):
        path = base / f"settled_{name}.parquet"
        if not path.is_file():
            raise SettledEvidenceError(f"missing settled evidence artifact: {path}")
        frames[name] = pl.read_parquet(path)
        expected = int(manifest.get("row_counts", {}).get(name, -1))
        if frames[name].height != expected:
            raise SettledEvidenceError(f"settled {name} row-count drift")
    validate_settled_evidence(
        games=frames["games"],
        team_stats=frames["team_stats"],
        qb_stats=frames["qb_stats"],
        pbp=frames["pbp"],
        through_week=through_week,
    )
    return SettledSeasonEvidence(
        root=base,
        through_week=through_week,
        observed_at_utc=str(manifest["observed_at_utc"]),
        games=frames["games"],
        team_stats=frames["team_stats"],
        qb_stats=frames["qb_stats"],
        pbp=frames["pbp"],
        manifest=manifest,
    )


def load_settled_evidence(root: str | Path) -> SettledSeasonEvidence:
    base = Path(root)
    with _evidence_lock(base, exclusive=False):
        return _load_settled_evidence(base)
