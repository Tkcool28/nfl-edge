"""Rereview 4851615980 final-rereview fixes — focused tests.

This file groups six focused tests (one per defect in the
rereview) so the rereview's explicit per-defect checklist can be
exercised as a unit.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import polars as pl
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"
SCRIPTS_DIR = REPO_ROOT / "scripts"
TEST_DIR = REPO_ROOT / "tests"
SHIPPED_REF_DIR = (
    REPO_ROOT
    / "data"
    / "source_audits"
    / "sleeper_qb_v1"
    / "reference"
)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from nfl_edge.source_audits.sleeper_qb_v1.crosswalk import (  # noqa: E402
    build_nflverse_indexes,
)
from nfl_edge.source_audits.sleeper_qb_v1.freshness import (  # noqa: E402
    FreshnessInputs,
    derive_freshness_state,
)
from nfl_edge.source_audits.sleeper_qb_v1.ho_game import (  # noqa: E402
    build_observation_record,
)

# ------------------------------------------------------------------ #
# Fix 1 — HOF union + null preservation
# ------------------------------------------------------------------ #


def _make_qb_row(
    sleeper_id: str, team: str, **extra: object
) -> dict[str, object]:
    row: dict[str, object] = {
        "sleeper_player_id": sleeper_id,
        "team": team,
        "depth_chart_order": 1,
        "injury_status": "Healthy",
        "practice_participation": "Full",
    }
    row.update(extra)
    return row


def test_hof_union_preserves_pregame_only_and_postgame_only_qbs() -> None:
    """The HOF observation union must keep BOTH pregame-only and
    postgame-only QBs; pregame and postgame fields for the other
    side must be null.
    """
    home = "KC"
    away = "DET"
    other_team = "TB"
    # Pregame: Mahomes (KC) is in pregame only.
    pregame = pl.DataFrame(
        [
            _make_qb_row("1042", home, first_name="Patrick", last_name="Mahomes"),
            _make_qb_row("9999", other_team),
        ]
    )
    pregame_evidence = pl.DataFrame(
        {"sleeper_player_id": ["1042"], "evidence_state": ["DEPTH_CHART_EXPECTED_HEALTHY"]}
    )
    # Postgame: Goff (DET) is in postgame only.
    postgame = pl.DataFrame(
        [
            _make_qb_row("1042", home, injury_status="Out"),
            _make_qb_row("4242", away, first_name="Jared", last_name="Goff"),
        ]
    )
    postgame_evidence = pl.DataFrame(
        {"sleeper_player_id": ["4242"], "evidence_state": ["DEPTH_CHART_EXPECTED_OUT"]}
    )
    game = {
        "game_id": "g-rereview",
        "home_team": home,
        "away_team": away,
        "scheduled_start_utc": "2026-08-06T01:30:00Z",
        "scheduled_start_local": "2026-08-06T01:30:00Z",
    }
    record = build_observation_record(
        observation_id="obs-rereview",
        game=game,
        relevant_qb_rows=postgame,
        pregame_snapshot_id="pregame-1",
        postgame_snapshot_id="postgame-1",
        pregame_evidence_frame=pregame_evidence,
        postgame_evidence_frame=postgame_evidence,
        pregame_normalized_frame=pregame,
        postgame_normalized_frame=postgame,
        all_snapshot_ids=["pregame-1", "postgame-1"],
    )
    # The union has 1042 (Mahomes, pregame+postgame) and 4242
    # (Goff, postgame-only). The other-team 9999 is excluded.
    assert set(record["relevant_sleeper_qbs"]) == {"1042", "4242"}
    # Per-QB position in the lists is sorted by sleeper_player_id,
    # so the order is ["1042", "4242"].
    # Index 0 = Mahomes.
    assert record["pregame_depth_order"][0] == "1"
    assert record["pregame_injury_status"][0] == "Healthy"
    assert record["pregame_evidence_state"][0] == "DEPTH_CHART_EXPECTED_HEALTHY"
    # Postgame also present (Mahomes flipped to Out).
    assert record["observed_injury_status"][0] == "Out"
    assert record["derived_evidence_state"][0] is None  # postgame evidence is on 4242
    # Index 1 = Goff (postgame-only).
    # Pregame fields for Goff are null (he was not in pregame).
    assert record["pregame_depth_order"][1] is None
    assert record["pregame_injury_status"][1] is None
    assert record["pregame_practice_participation"][1] is None
    assert record["pregame_evidence_state"][1] is None
    # Postgame fields for Goff are populated.
    assert record["observed_depth_order"][1] == "1"
    assert record["observed_injury_status"][1] == "Healthy"
    assert record["derived_evidence_state"][1] == "DEPTH_CHART_EXPECTED_OUT"


def test_hof_postgame_only_qb_does_not_synthesize_pregame_history() -> None:
    """A QB present only in the postgame frame must NEVER have
    pregame fields copied from the postgame row. The audit must
    not invent a historical signal it never observed.
    """
    home, away = "KC", "DET"
    postgame = pl.DataFrame([_make_qb_row("4242", away)])
    # Empty pregame.
    pregame = pl.DataFrame(
        schema={
            "sleeper_player_id": pl.Utf8,
            "team": pl.Utf8,
            "depth_chart_order": pl.Int64,
            "injury_status": pl.Utf8,
            "practice_participation": pl.Utf8,
        }
    )
    game = {
        "game_id": "g-only-postgame",
        "home_team": home,
        "away_team": away,
        "scheduled_start_utc": "2026-08-06T01:30:00Z",
        "scheduled_start_local": "2026-08-06T01:30:00Z",
    }
    record = build_observation_record(
        observation_id="obs-only-postgame",
        game=game,
        relevant_qb_rows=postgame,
        pregame_snapshot_id="pregame-empty",
        postgame_snapshot_id="postgame-1",
        pregame_evidence_frame=pl.DataFrame(
            {"sleeper_player_id": pl.Series([], dtype=pl.Utf8), "evidence_state": pl.Series([], dtype=pl.Utf8)}
        ),
        postgame_evidence_frame=pl.DataFrame(
            {"sleeper_player_id": ["4242"], "evidence_state": ["DEPTH_CHART_EXPECTED_OUT"]}
        ),
        pregame_normalized_frame=pregame,
        postgame_normalized_frame=postgame,
        all_snapshot_ids=["pregame-empty", "postgame-1"],
    )
    assert record["relevant_sleeper_qbs"] == ["4242"]
    # All pregame fields must be None — no synthetic fallback.
    assert record["pregame_depth_order"] == [None]
    assert record["pregame_injury_status"] == [None]
    assert record["pregame_practice_participation"] == [None]
    assert record["pregame_evidence_state"] == [None]
    # Postgame fields are populated normally.
    assert record["observed_depth_order"] == ["1"]
    assert record["derived_evidence_state"] == ["DEPTH_CHART_EXPECTED_OUT"]


# ------------------------------------------------------------------ #
# Fix 2 — typed-outcome gaps + mandatory reference manifest
# ------------------------------------------------------------------ #


@pytest.fixture
def stage_clean_audit_root(tmp_path: Path):
    """Copy the shipped reference fixtures into a temp audit root
    and yield the audit_root + manifest paths.
    """

    def _stage() -> tuple[Path, Path]:
        import hashlib

        audit_root = tmp_path / "audit"
        audit_root.mkdir(parents=True, exist_ok=True)
        ref_dir = audit_root / "reference"
        ref_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = ref_dir / "manifest.json"
        artifacts: list[dict[str, object]] = []
        for name in (
            "hof_game_2026_fixture.parquet",
            "nflverse_player_identity_pre2025.parquet",
        ):
            src = SHIPPED_REF_DIR / name
            dst = ref_dir / name
            shutil.copyfile(src, dst)
            sha = hashlib.sha256(dst.read_bytes()).hexdigest()
            rc = pl.read_parquet(dst).height
            artifacts.append({"path": name, "sha256": sha, "row_count": rc})
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "description": "Rereview clean-clone test manifest.",
                    "artifacts": artifacts,
                }
            )
        )
        return audit_root, manifest_path

    return _stage


def _write_cfg(audit_root: Path, manifest_path: Path) -> Path:
    cfg = audit_root.parent / "cfg.yaml"
    cfg.write_text(
        "\n".join(
            [
                f"audit_root: {audit_root.as_posix()}",
                "endpoint: https://api.sleeper.app/v1/players/nfl",
                "staleness_threshold_seconds: 21600",
                f"reference_manifest: {manifest_path.as_posix()}",
            ]
        )
        + "\n"
    )
    return cfg


def _run_cli(
    cfg_path: Path,
    extra_args: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        str(Path("/root/nfl-edge/.venv/bin/python3.11")),
        str(SCRIPTS_DIR / "collect_sleeper_qbs.py"),
        "--config",
        str(cfg_path),
        "--use-fake-session",
    ] + extra_args
    base_env = {
        "PYTHONPATH": (
            f"{REPO_ROOT}:{SRC_DIR}:{TEST_DIR}:{REPO_ROOT / 'tests'}"
        )
    }
    if env:
        base_env.update(env)
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, env=base_env
    )


def test_cli_missing_reference_manifest_yields_reference_failure(
    stage_clean_audit_root: "callable",
) -> None:
    audit_root, _ = stage_clean_audit_root()
    cfg = audit_root.parent / "cfg-no-manifest.yaml"
    cfg.write_text(
        f"audit_root: {audit_root.as_posix()}\n"
        "endpoint: https://api.sleeper.app/v1/players/nfl\n"
        "staleness_threshold_seconds: 21600\n"
    )
    result = _run_cli(cfg, ["--kind=scheduled"], timeout=30.0)
    assert result.returncode == 21, f"stderr={result.stderr!r}"
    stderr = json.loads(result.stderr)
    assert stderr["run_outcome"] == "REFERENCE_FAILURE"
    assert stderr["exit_code"] == 21
    assert "missing reference_manifest" in stderr["error_message"]


def test_cli_malformed_reference_manifest_yields_reference_failure(
    stage_clean_audit_root: "callable",
    tmp_path: Path,
) -> None:
    audit_root, _ = stage_clean_audit_root()
    bad_manifest = tmp_path / "bad.json"
    bad_manifest.write_text("{this is not valid json")
    cfg = audit_root.parent / "cfg-bad-manifest.yaml"
    cfg.write_text(
        f"audit_root: {audit_root.as_posix()}\n"
        "endpoint: https://api.sleeper.app/v1/players/nfl\n"
        "staleness_threshold_seconds: 21600\n"
        f"reference_manifest: {bad_manifest.as_posix()}\n"
    )
    result = _run_cli(cfg, ["--kind=scheduled"], timeout=30.0)
    assert result.returncode == 21, f"stderr={result.stderr!r}"
    stderr = json.loads(result.stderr)
    assert stderr["run_outcome"] == "REFERENCE_FAILURE"
    assert "malformed reference manifest JSON" in stderr["error_message"]


def test_cli_missing_reference_manifest_file_yields_reference_failure(
    stage_clean_audit_root: "callable",
    tmp_path: Path,
) -> None:
    audit_root, _ = stage_clean_audit_root()
    absent = tmp_path / "absent.json"
    cfg = audit_root.parent / "cfg-absent-manifest.yaml"
    cfg.write_text(
        f"audit_root: {audit_root.as_posix()}\n"
        "endpoint: https://api.sleeper.app/v1/players/nfl\n"
        "staleness_threshold_seconds: 21600\n"
        f"reference_manifest: {absent.as_posix()}\n"
    )
    result = _run_cli(cfg, ["--kind=scheduled"], timeout=30.0)
    assert result.returncode == 21, f"stderr={result.stderr!r}"
    stderr = json.loads(result.stderr)
    assert stderr["run_outcome"] == "REFERENCE_FAILURE"
    assert "missing reference manifest file" in stderr["error_message"]


def test_cli_empty_artifacts_list_yields_reference_failure(
    stage_clean_audit_root: "callable",
) -> None:
    audit_root, manifest_path = stage_clean_audit_root()
    # Replace the manifest with an empty artifacts list.
    manifest_path.write_text(json.dumps({"schema_version": 1, "artifacts": []}))
    cfg = _write_cfg(audit_root, manifest_path)
    result = _run_cli(cfg, ["--kind=scheduled"], timeout=30.0)
    assert result.returncode == 21, f"stderr={result.stderr!r}"
    stderr = json.loads(result.stderr)
    assert stderr["run_outcome"] == "REFERENCE_FAILURE"
    assert "empty or missing 'artifacts'" in stderr["error_message"]


def test_cli_missing_config_yields_normalization_failure(tmp_path: Path) -> None:
    absent = tmp_path / "no-such-config.yaml"
    result = _run_cli(
        absent, ["--kind=scheduled"], timeout=30.0
    )
    assert result.returncode == 12, f"stderr={result.stderr!r}"
    stderr = json.loads(result.stderr)
    assert stderr["run_outcome"] == "NORMALIZATION_FAILURE"
    assert "not found" in stderr["error_message"]


# ------------------------------------------------------------------ #
# Fix 3 — transport freshness distinction
# ------------------------------------------------------------------ #


def test_transport_failure_state_is_not_incomplete_response() -> None:
    inputs = FreshnessInputs(
        last_success_at_utc=None,
        last_failure_at_utc="2026-08-04T00:00:00Z",
        last_attempt_success=False,
        change_count=0,
        last_payload_sha256=None,
        prior_payload_sha256=None,
        parsed_ok=False,
        present_fields=frozenset(),
    )
    state = derive_freshness_state(inputs, staleness_threshold_seconds=3600)
    assert state == "FETCH_FAILED_USING_NO_FALLBACK"


def test_parse_level_failure_with_http_success_is_incomplete_response() -> None:
    inputs = FreshnessInputs(
        last_success_at_utc="2026-08-04T00:00:00Z",
        last_failure_at_utc=None,
        last_attempt_success=True,
        change_count=0,
        last_payload_sha256=None,
        prior_payload_sha256=None,
        parsed_ok=False,
        present_fields=frozenset(),
    )
    state = derive_freshness_state(inputs, staleness_threshold_seconds=3600)
    assert state == "INCOMPLETE_RESPONSE"


# ------------------------------------------------------------------ #
# Fix 4 — terminal run-history reconciliation
# ------------------------------------------------------------------ #


def test_run_history_success_recorded_only_for_terminal_success(
    stage_clean_audit_root: "callable",
) -> None:
    """A successful HTTP attempt followed by a downstream failure
    must NOT count as a successful run. The terminal outcome is
    the only source of truth for the rolling metric.
    """
    from nfl_edge.source_audits.sleeper_qb_v1.metrics import (
        build_runs_from_disk,
        compute_reliability_metrics,
    )

    audit_root, manifest_path = stage_clean_audit_root()
    cfg = _write_cfg(audit_root, manifest_path)
    # 1. Successful run.
    r1 = _run_cli(cfg, ["--kind=scheduled"], timeout=60.0)
    assert r1.returncode == 0, f"stderr={r1.stderr!r}"
    # 2. Failed run via timeout exhaustion.
    sitecustomize = audit_root.parent / "sitecustomize.py"
    sitecustomize.write_text(
        "import scripts._sleeper_fake_session as _f\n"
        "from scripts._sleeper_fake_session import FakeSleeperSession\n"
        "_orig_init = FakeSleeperSession.__init__\n"
        "def _patched_init(self, *a, **kw):\n"
        "    _orig_init(self, *a, **kw)\n"
        "    self.raise_timeout = True\n"
        "FakeSleeperSession.__init__ = _patched_init\n"
    )
    env = {
        "PYTHONPATH": (
            f"{audit_root.parent}:{SRC_DIR}:{TEST_DIR}:{REPO_ROOT / 'tests'}:{REPO_ROOT}"
        )
    }
    r2 = _run_cli(cfg, ["--kind=scheduled"], env=env, timeout=60.0)
    assert r2.returncode == 10, f"stderr={r2.stderr!r}"
    # Read the run history.
    history_path = audit_root / "run_history.jsonl"
    assert history_path.exists()
    rows = [json.loads(line) for line in history_path.read_text().splitlines()]
    outcomes = [r["outcome"] for r in rows]
    # Exactly one SUCCESS and one TRANSPORT_FAILURE, in that order.
    assert outcomes == ["SUCCESS", "TRANSPORT_FAILURE"]
    # The metrics build must derive successful_run_count from
    # the terminal outcome only.
    runs, change_ledger = build_runs_from_disk(audit_root)
    metrics = compute_reliability_metrics(runs=runs, change_ledger=change_ledger)
    assert metrics["successful_run_count"] == 1
    assert metrics["failed_run_count"] == 1
    assert metrics["scheduled_run_count"] == 2
    # Attempt count is the max of attempt_count across runs.
    assert metrics["attempted_fetch_count"] >= 1


# ------------------------------------------------------------------ #
# Fix 5 — atomic durability ordering
# ------------------------------------------------------------------ #


def test_atomic_write_bytes_temp_fsync_then_replace_then_dir_fsync(
    tmp_path: Path,
) -> None:
    """``atomic_write_bytes`` must:
    1. write temp file
    2. flush temp
    3. fsync temp
    4. os.replace(temp, target)
    5. fsync parent directory AFTER replace
    """
    from nfl_edge.source_audits.sleeper_qb_v1.atomic_io import (
        atomic_write_bytes,
    )

    target = tmp_path / "out.bin"
    calls: list[str] = []
    real_replace = os.replace
    real_fsync = os.fsync

    def spy_replace(src: str, dst: str) -> None:
        calls.append(f"replace({os.path.basename(src)} -> {os.path.basename(dst)})")
        real_replace(src, dst)

    def spy_fsync(fd: int) -> None:
        try:
            path = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            path = f"fd={fd}"
        calls.append(f"fsync({path})")
        real_fsync(fd)

    os.replace = spy_replace  # type: ignore[assignment]
    os.fsync = spy_fsync  # type: ignore[assignment]
    try:
        atomic_write_bytes(target, b"hello world")
    finally:
        os.replace = real_replace  # type: ignore[assignment]
        os.fsync = real_fsync  # type: ignore[assignment]
    replace_indices = [i for i, c in enumerate(calls) if c.startswith("replace(")]
    assert replace_indices, f"no replace in {calls}"
    replace_idx = replace_indices[0]
    # The parent-dir fsync must come AFTER the replace.
    after_replace = [
        c for c in calls[replace_idx + 1 :] if c.startswith("fsync(")
    ]
    assert after_replace, (
        f"no fsync AFTER replace in {calls}; expected parent-dir fsync after os.replace"
    )
    # And there must be a fsync BEFORE replace for the temp file.
    before_replace = [
        c for i, c in enumerate(calls[:replace_idx]) if c.startswith("fsync(")
    ]
    assert before_replace, (
        f"no fsync BEFORE replace in {calls}; expected temp-file fsync before os.replace"
    )


def test_atomic_write_parquet_replace_after_fsync_dir_fsync_after_replace(
    tmp_path: Path,
) -> None:
    """``atomic_write_parquet`` must fsync the temp file BEFORE
    os.replace and fsync the parent directory AFTER os.replace.
    """
    from nfl_edge.source_audits.sleeper_qb_v1.atomic_io import (
        atomic_write_parquet,
    )

    target = tmp_path / "out.parquet"
    df = pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    calls: list[str] = []
    real_replace = os.replace
    real_fsync = os.fsync

    def spy_replace(src: str, dst: str) -> None:
        calls.append(f"replace({os.path.basename(src)} -> {os.path.basename(dst)})")
        real_replace(src, dst)

    def spy_fsync(fd: int) -> None:
        try:
            path = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            path = f"fd={fd}"
        calls.append(f"fsync({path})")
        real_fsync(fd)

    os.replace = spy_replace  # type: ignore[assignment]
    os.fsync = spy_fsync  # type: ignore[assignment]
    try:
        atomic_write_parquet(target, df)
    finally:
        os.replace = real_replace  # type: ignore[assignment]
        os.fsync = real_fsync  # type: ignore[assignment]
    replace_indices = [i for i, c in enumerate(calls) if c.startswith("replace(")]
    assert replace_indices
    replace_idx = replace_indices[0]
    # Parent-dir fsync after replace.
    after_replace = [
        c for c in calls[replace_idx + 1 :] if c.startswith("fsync(")
    ]
    assert after_replace
    # Temp-file fsync before replace.
    before_replace = [
        c for i, c in enumerate(calls[:replace_idx]) if c.startswith("fsync(")
    ]
    assert before_replace


def test_atomic_write_forced_failure_before_replace_preserves_old_target(
    tmp_path: Path,
) -> None:
    """A forced failure before ``os.replace`` must leave the
    existing target byte-identical.
    """
    from nfl_edge.source_audits.sleeper_qb_v1.atomic_io import (
        atomic_write_bytes,
    )

    target = tmp_path / "out.bin"
    target.write_bytes(b"original content")
    before_sha = hashlib.sha256(target.read_bytes()).hexdigest()

    real_replace = os.replace

    def fail_replace(src: str, dst: str) -> None:
        raise OSError("simulated ENOSPC during replace")

    os.replace = fail_replace  # type: ignore[assignment]
    try:
        with pytest.raises(OSError, match="simulated ENOSPC"):
            atomic_write_bytes(target, b"new content")
    finally:
        os.replace = real_replace  # type: ignore[assignment]
    after_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    assert before_sha == after_sha, "target bytes must be unchanged"
    assert target.read_bytes() == b"original content"


# ------------------------------------------------------------------ #
# Fix 6 — terminal exact-ID conflicts
# ------------------------------------------------------------------ #


def _make_nflverse(
    *rows: dict[str, object], db_season: int = 2024
) -> pl.DataFrame:
    columns = [
        "player_id",
        "sleeper_player_id",
        "gsis_id",
        "espn_id",
        "sportradar_id",
        "yahoo_id",
        "fantasy_data_id",
        "rotowire_id",
        "full_name",
        "first_name",
        "last_name",
        "team",
        "position",
        "db_season",
    ]
    # Build the frame; missing columns default to null.
    rows_full: list[dict[str, object]] = []
    for r in rows:
        full: dict[str, object] = {col: None for col in columns}
        full.update(r)
        full["db_season"] = db_season
        full["position"] = full.get("position") or "QB"
        rows_full.append(full)
    return pl.DataFrame(rows_full, schema=columns)


def _crosswalk_row(
    nflverse: pl.DataFrame, sleeper_record: dict[str, object]
) -> dict[str, object]:
    indexes = build_nflverse_indexes(nflverse)
    from nfl_edge.source_audits.sleeper_qb_v1.crosswalk import (
        _row_for_sleeper,
    )

    return _row_for_sleeper(
        snapshot_id="snap-test",
        sleeper_record=sleeper_record,
        gsis_to_nflverse=indexes[0],
        espn_to_nflverse=indexes[1],
        other_stable_to_nflverse=indexes[2],
        sleeper_to_nflverse=indexes[4],
        name_team_to_nflverse=indexes[3],
    )


def test_sleeper_conflict_blocks_lower_priorities() -> None:
    """A multi-match at priority 0 (Sleeper id) must block every
    lower-priority identifier and the name+team fallback.
    """
    nflverse = _make_nflverse(
        {
            "player_id": "nflv-A",
            "sleeper_player_id": "7523",
            "full_name": "Test A",
            "first_name": "Test",
            "last_name": "A",
            "team": "KC",
        },
        {
            "player_id": "nflv-B",
            "sleeper_player_id": "7523",
            "full_name": "Test B",
            "first_name": "Test",
            "last_name": "B",
            "team": "KC",
        },
    )
    sleeper_record = {
        "player_id": "7523",
        "sleeper_player_id": "7523",
        "gsis_id": "00-CLEAN",
        "espn_id": "1",
        "first_name": "Test",
        "last_name": "Z",
        "team": "KC",
    }
    row = _crosswalk_row(nflverse, sleeper_record)
    assert row["is_matched"] is False
    assert row["nflverse_player_id"] is None
    assert row["review_required"] is True
    assert "multiple_nflverse_for_exact_sleeper_id" in row["conflict_reason"]


def test_gsis_conflict_blocks_lower_priorities() -> None:
    nflverse = _make_nflverse(
        {
            "player_id": "nflv-A",
            "sleeper_player_id": "111",
            "gsis_id": "00-999",
            "full_name": "X A",
            "first_name": "X",
            "last_name": "A",
            "team": "KC",
        },
        {
            "player_id": "nflv-B",
            "sleeper_player_id": "222",
            "gsis_id": "00-999",
            "full_name": "X B",
            "first_name": "X",
            "last_name": "B",
            "team": "KC",
        },
    )
    sleeper_record = {
        "player_id": "333",
        "sleeper_player_id": "333",
        "gsis_id": "00-999",
        "espn_id": "9",
        "first_name": "X",
        "last_name": "Z",
        "team": "KC",
    }
    row = _crosswalk_row(nflverse, sleeper_record)
    assert row["is_matched"] is False
    assert row["nflverse_player_id"] is None
    assert row["review_required"] is True
    assert "multiple_nflverse_for_exact_gsis" in row["conflict_reason"]


def test_espn_conflict_blocks_other_stable_id() -> None:
    nflverse = _make_nflverse(
        {
            "player_id": "nflv-A",
            "sleeper_player_id": "111",
            "gsis_id": "00-A",
            "espn_id": "12345",
            "full_name": "Y A",
            "first_name": "Y",
            "last_name": "A",
            "team": "KC",
        },
        {
            "player_id": "nflv-B",
            "sleeper_player_id": "222",
            "gsis_id": "00-B",
            "espn_id": "12345",
            "sportradar_id": "SR-CLEAN",
            "full_name": "Y B",
            "first_name": "Y",
            "last_name": "B",
            "team": "KC",
        },
    )
    sleeper_record = {
        "player_id": "333",
        "sleeper_player_id": "333",
        "gsis_id": "00-Z",
        "espn_id": "12345",
        "sportradar_id": "SR-CLEAN",
        "first_name": "Y",
        "last_name": "Z",
        "team": "KC",
    }
    row = _crosswalk_row(nflverse, sleeper_record)
    assert row["is_matched"] is False
    assert row["nflverse_player_id"] is None
    assert row["review_required"] is True
    assert "multiple_nflverse_for_exact_espn" in row["conflict_reason"]


def test_other_stable_conflict_blocks_name_fallback() -> None:
    nflverse = _make_nflverse(
        {
            "player_id": "nflv-A",
            "sleeper_player_id": "111",
            "gsis_id": "00-A",
            "espn_id": "11",
            "sportradar_id": "SR-CONFLICT",
            "full_name": "Z A",
            "first_name": "Z",
            "last_name": "A",
            "team": "KC",
        },
        {
            "player_id": "nflv-B",
            "sleeper_player_id": "222",
            "gsis_id": "00-B",
            "espn_id": "22",
            "sportradar_id": "SR-CONFLICT",
            "full_name": "Z B",
            "first_name": "Z",
            "last_name": "B",
            "team": "KC",
        },
    )
    sleeper_record = {
        "player_id": "333",
        "sleeper_player_id": "333",
        "gsis_id": "00-Z",
        "espn_id": "99",
        "sportradar_id": "SR-CONFLICT",
        "first_name": "Z",
        "last_name": "Z",
        "team": "KC",
    }
    row = _crosswalk_row(nflverse, sleeper_record)
    assert row["is_matched"] is False
    assert row["nflverse_player_id"] is None
    assert row["review_required"] is True
    assert "multiple_nflverse_for_exact_other_stable_sportradar" in row["conflict_reason"]


def test_clean_unique_match_succeeds() -> None:
    nflverse = _make_nflverse(
        {
            "player_id": "nflv-A",
            "sleeper_player_id": "7523",
            "gsis_id": "00-1",
            "espn_id": "1",
            "sportradar_id": "SR-1",
            "full_name": "Clean A",
            "first_name": "Clean",
            "last_name": "A",
            "team": "KC",
        },
    )
    sleeper_record = {
        "player_id": "7523",
        "sleeper_player_id": "7523",
        "gsis_id": "00-1",
        "espn_id": "1",
        "sportradar_id": "SR-1",
        "first_name": "Clean",
        "last_name": "A",
        "team": "KC",
    }
    row = _crosswalk_row(nflverse, sleeper_record)
    assert row["is_matched"] is True
    assert row["nflverse_player_id"] == "nflv-A"
    assert row["review_required"] is False