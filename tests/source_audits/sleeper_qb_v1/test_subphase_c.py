"""Sub-phase C correctness tests for the Sleeper audit.

These tests cover:

* the crosswalk's exact-ID collision detection for every
  supported exact-ID class (Sleeper, GSIS, ESPN, sportradar /
  yahoo / fantasy_data / rotowire);
* the clean-clone contract: a fresh checkout with only the
  shipped reference fixtures and the manifest must be auditable
  without external setup;
* the reference manifest's checksum enforcement
  (a tampered fixture fails the run with REFERENCE_FAILURE);
* the reference-manifest path is wired through the YAML config
  and the CLI so the audit verifies fixtures automatically.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import polars as pl
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"


# ---------------------------------------------------------------------------
# 1. Exact-ID collision detection for every exact-ID class
# ---------------------------------------------------------------------------


def _fake_nflverse_table(
    *,
    sleeper_id: str | None = None,
    gsis_id: str | None = None,
    espn_id: str | None = None,
    sportradar_id: str | None = None,
    yahoo_id: str | None = None,
    fantasy_data_id: str | None = None,
    rotowire_id: str | None = None,
    nflverse_id: str = "nflv-1",
    merge_name: str = "Test Player",
    team: str | None = "KC",
) -> pl.DataFrame:
    """Build a one-row nflverse reference frame with the
    columns the crosswalk's ``build_nflverse_indexes`` reads:

    ``player_id`` (the nflverse id), ``sleeper_id_str``, ``gsis_id``,
    ``espn_id``, ``sportradar_id``, ``yahoo_id``, ``fantasy_data_id``,
    ``rotowire_id``, ``full_name``, ``team``, ``position``,
    ``db_season``.

    The orchestrator synthesizes ``sleeper_id_str`` from ``sleeper_id``;
    we set both columns to keep the helper honest.
    """
    return pl.DataFrame(
        {
            "player_id": [nflverse_id],
            "sleeper_id": [int(sleeper_id) if sleeper_id is not None else None],
            "sleeper_id_str": [sleeper_id],
            "gsis_id": [gsis_id],
            "espn_id": [int(espn_id) if espn_id is not None else None],
            "sportradar_id": [sportradar_id],
            "yahoo_id": [yahoo_id],
            "fantasy_data_id": [
                int(fantasy_data_id) if fantasy_data_id is not None else None
            ],
            "rotowire_id": [
                int(rotowire_id) if rotowire_id is not None else None
            ],
            "full_name": [merge_name],
            "first_name": [merge_name.split(" ")[0] if " " in merge_name else merge_name],
            "last_name": [merge_name.split(" ")[-1] if " " in merge_name else ""],
            "team": [team],
            "position": ["QB"],
            "db_season": [2024],
        }
    )


def _crosswalk_row(
    nflverse: pl.DataFrame, sleeper_record: dict[str, Any]
) -> dict[str, Any]:
    """Helper: build the five lookup indexes from ``nflverse``
    and invoke ``_row_for_sleeper`` with explicit keyword
    arguments (the function takes 5 dict args).
    """
    sys.path.insert(0, str(SRC_DIR.parent))
    from nfl_edge.source_audits.sleeper_qb_v1.crosswalk import (
        _row_for_sleeper,
        build_nflverse_indexes,
    )

    gsis_idx, espn_idx, provider_idx, name_team_idx, sleeper_idx = (
        build_nflverse_indexes(nflverse)
    )
    return _row_for_sleeper(
        snapshot_id="snap-1",
        sleeper_record=sleeper_record,
        gsis_to_nflverse=gsis_idx,
        espn_to_nflverse=espn_idx,
        provider_to_nflverse=provider_idx,
        name_team_to_nflverse=name_team_idx,
        sleeper_to_nflverse=sleeper_idx,
    )


def test_sleeper_id_collision_marks_review_required() -> None:
    """Two nflverse rows sharing one Sleeper id must emit
    ``is_matched=False``, ``review_required=True``, and a
    descriptive conflict reason labelled ``exact_sleeper_id``.
    """
    base = _fake_nflverse_table(
        sleeper_id="1234",
        gsis_id="00-0038125",
        nflverse_id="nflv-A",
        merge_name="Patrick Mahomes",
        team="KC",
    )
    second = _fake_nflverse_table(
        sleeper_id="1234",
        gsis_id="00-0038125",
        nflverse_id="nflv-B",
        merge_name="Patrick Mahomes",
        team="KC",
    )
    nflverse = pl.concat([base, second], how="vertical")
    sleeper_record = {
        "sleeper_player_id": "1234",
        "first_name": "Patrick",
        "last_name": "Mahomes",
        "full_name": "Patrick Mahomes",
        "team": "KC",
        "gsis_id": "00-0038125",
    }
    row = _crosswalk_row(nflverse, sleeper_record)
    assert row["is_matched"] is False
    assert row["review_required"] is True
    assert "multiple_nflverse_for_exact_sleeper_id" in row["conflict_reason"]
    assert row["nflverse_player_id"] is None or row["nflverse_player_id"] == ""


def test_gsis_id_collision_marks_review_required() -> None:
    """Two nflverse rows sharing one GSIS id (and no Sleeper
    id) must emit ``is_matched=False`` and a conflict reason
    labelled ``exact_gsis``.
    """
    a = _fake_nflverse_table(
        sleeper_id=None,
        gsis_id="00-0038125",
        nflverse_id="nflv-A",
        merge_name="Player A",
        team="KC",
    )
    b = _fake_nflverse_table(
        sleeper_id=None,
        gsis_id="00-0038125",
        nflverse_id="nflv-B",
        merge_name="Player B",
        team="KC",
    )
    nflverse = pl.concat([a, b], how="vertical")
    sleeper_record = {
        "sleeper_player_id": "9999",
        "first_name": "Patrick",
        "last_name": "Mahomes",
        "full_name": "Patrick Mahomes",
        "team": "KC",
        "gsis_id": "00-0038125",
    }
    row = _crosswalk_row(nflverse, sleeper_record)
    assert row["is_matched"] is False
    assert row["review_required"] is True
    assert "multiple_nflverse_for_exact_gsis" in row["conflict_reason"]


def test_espn_id_collision_marks_review_required() -> None:
    """Two nflverse rows sharing one ESPN id (and no Sleeper /
    GSIS ids) must emit ``is_matched=False`` and a conflict
    reason labelled ``exact_espn``.
    """
    a = _fake_nflverse_table(
        sleeper_id=None,
        gsis_id=None,
        espn_id="3918291",
        nflverse_id="nflv-A",
        merge_name="Player A",
        team="KC",
    )
    b = _fake_nflverse_table(
        sleeper_id=None,
        gsis_id=None,
        espn_id="3918291",
        nflverse_id="nflv-B",
        merge_name="Player B",
        team="KC",
    )
    nflverse = pl.concat([a, b], how="vertical")
    sleeper_record = {
        "sleeper_player_id": "9999",
        "first_name": "Patrick",
        "last_name": "Mahomes",
        "full_name": "Patrick Mahomes",
        "team": "KC",
        "gsis_id": "00-0038125",
        "espn_id": "3918291",
    }
    row = _crosswalk_row(nflverse, sleeper_record)
    assert row["is_matched"] is False
    assert row["review_required"] is True
    assert "multiple_nflverse_for_exact_espn" in row["conflict_reason"]


@pytest.mark.parametrize(
    "provider_label,field",
    [
        ("sportradar", "sportradar_id"),
        ("yahoo", "yahoo_id"),
        ("fantasy_data", "fantasy_data_id"),
        ("rotowire", "rotowire_id"),
    ],
)
def test_other_stable_id_collision_marks_review_required(
    provider_label: str, field: str
) -> None:
    """For each ``exact_other_stable`` provider, a duplicate id
    must yield ``is_matched=False`` and a conflict reason
    labelled ``exact_other_stable_<provider>``.
    """
    collision_value = f"id-for-{provider_label}"
    a = _fake_nflverse_table(
        sleeper_id=None,
        gsis_id=None,
        espn_id=None,
        nflverse_id="nflv-A",
        merge_name="Player A",
        team="KC",
    ).with_columns(pl.lit(collision_value).alias(field))
    b = _fake_nflverse_table(
        sleeper_id=None,
        gsis_id=None,
        espn_id=None,
        nflverse_id="nflv-B",
        merge_name="Player B",
        team="KC",
    ).with_columns(pl.lit(collision_value).alias(field))
    nflverse = pl.concat([a, b], how="vertical")
    sleeper_record = {
        "sleeper_player_id": "9999",
        "first_name": "Patrick",
        "last_name": "Mahomes",
        "full_name": "Patrick Mahomes",
        "team": "KC",
        field: collision_value,
    }
    row = _crosswalk_row(nflverse, sleeper_record)
    assert row["is_matched"] is False
    assert row["review_required"] is True
    expected = f"multiple_nflverse_for_exact_other_stable_{provider_label}"
    assert expected in row["conflict_reason"], (
        f"expected {expected!r} in {row['conflict_reason']!r}"
    )


def test_clean_unique_exact_match_succeeds() -> None:
    """When an exact id matches a single nflverse row, the
    crosswalk returns ``is_matched=True`` and
    ``review_required=False``.
    """
    nflverse = _fake_nflverse_table(
        sleeper_id="1234",
        gsis_id="00-0038125",
        nflverse_id="nflv-A",
        merge_name="Patrick Mahomes",
        team="KC",
    )
    sleeper_record = {
        "sleeper_player_id": "1234",
        "first_name": "Patrick",
        "last_name": "Mahomes",
        "full_name": "Patrick Mahomes",
        "team": "KC",
        "gsis_id": "00-0038125",
    }
    row = _crosswalk_row(nflverse, sleeper_record)
    assert row["is_matched"] is True
    assert row["review_required"] is False
    assert row["match_method"] == "exact_sleeper_id"
    assert row["nflverse_player_id"] == "nflv-A"
    assert row["conflict_reason"] is None or row["conflict_reason"] == ""


# ---------------------------------------------------------------------------
# 2. Reference manifest enforcement
# ---------------------------------------------------------------------------


def test_verify_reference_manifest_passes_for_shipped_fixtures() -> None:
    """The shipped ``manifest.json`` enumerates the two tracked
    reference fixtures with their exact SHA-256s. The
    verify helper must return ``(True, [])`` when checked
    against the on-disk files.
    """
    sys.path.insert(0, str(SRC_DIR.parent))
    from nfl_edge.source_audits.sleeper_qb_v1.atomic_io import (
        ReferenceArtifact,
        verify_reference_manifest,
    )

    manifest_dir = REPO_ROOT / "data/source_audits/sleeper_qb_v1/reference"
    manifest_json = manifest_dir / "manifest.json"
    raw = json.loads(manifest_json.read_text())
    artifacts = [
        ReferenceArtifact(
            path=str(e["path"]),
            sha256=str(e["sha256"]),
            row_count=int(e["row_count"]),
        )
        for e in raw["artifacts"]
    ]
    ok, errors = verify_reference_manifest(manifest_dir, artifacts)
    assert ok, f"errors: {errors}"
    assert errors == []


def test_verify_reference_manifest_rejects_tampered_fixture(tmp_path: Path) -> None:
    """A tampered fixture (one byte changed) must fail
    verification with a checksum mismatch error.
    """
    sys.path.insert(0, str(SRC_DIR.parent))
    from nfl_edge.source_audits.sleeper_qb_v1.atomic_io import (
        ReferenceArtifact,
        verify_reference_manifest,
    )

    src = REPO_ROOT / "data/source_audits/sleeper_qb_v1/reference"
    dst = tmp_path / "reference"
    shutil.copytree(src, dst)
    target = dst / "hof_game_2026_fixture.parquet"
    bytes_ = target.read_bytes()
    flipped = bytearray(bytes_)
    flipped[0] ^= 0xFF
    target.write_bytes(bytes(flipped))
    expected_sha = hashlib.sha256(bytes_).hexdigest()
    nflverse_actual = hashlib.sha256(
        (dst / "nflverse_player_identity_pre2025.parquet").read_bytes()
    ).hexdigest()
    artifacts = [
        ReferenceArtifact(
            path="hof_game_2026_fixture.parquet",
            sha256=expected_sha,
            row_count=1,
        ),
        ReferenceArtifact(
            path="nflverse_player_identity_pre2025.parquet",
            sha256=nflverse_actual,
            row_count=12470,
        ),
    ]
    ok, errors = verify_reference_manifest(dst, artifacts)
    assert not ok
    assert any("mismatch" in e.lower() for e in errors)


def test_verify_reference_manifest_rejects_missing_fixture(tmp_path: Path) -> None:
    """A missing fixture must fail verification with a
    missing-file error.
    """
    sys.path.insert(0, str(SRC_DIR.parent))
    from nfl_edge.source_audits.sleeper_qb_v1.atomic_io import (
        ReferenceArtifact,
        verify_reference_manifest,
    )

    dst = tmp_path / "reference"
    dst.mkdir()
    artifacts = [
        ReferenceArtifact(
            path="hof_game_2026_fixture.parquet",
            sha256="0" * 64,
            row_count=1,
        ),
    ]
    ok, errors = verify_reference_manifest(dst, artifacts)
    assert not ok
    assert any("missing" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# 3. CLI integration: clean-clone contract
# ---------------------------------------------------------------------------


def test_cli_clean_clone_reference_check_succeeds(tmp_path: Path) -> None:
    """From a clean checkout of the repo (the test runner is
    the clean checkout), the CLI must:

    * successfully locate the shipped manifest via the YAML
      config;
    * successfully verify every shipped reference fixture;
    * execute an end-to-end run against the fake-session
      shim and exit 0.

    The "clean clone" pre-condition: copy the shipped
    reference fixtures from the repo into ``audit_root/reference``
    so the manifest's relative paths resolve. This is the same
    operation ``make audit-ready`` would perform in a
    production deployment.
    """
    env = {
        "PYTHONPATH": (
            f"{tmp_path}:{SRC_DIR}:{REPO_ROOT / 'tests'}:{REPO_ROOT}"
        ),
    }
    audit_root = tmp_path / "audit"
    audit_root.mkdir(parents=True, exist_ok=True)
    # Stage the fake-session shim into tmp_path/scripts so the
    # CLI's sitecustomize can import it.
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    shim = scripts_dir / "_sleeper_fake_session.py"
    shim.write_text(
        "import tests.source_audits.sleeper_qb_v1._fake_session as _upstream\n"
        "FakeSleeperSession = _upstream.FakeSleeperSession\n"
        "FakeSleeperResponse = _upstream.FakeSleeperResponse\n"
        "_fake_player_map = _upstream._fake_player_map\n"
    )
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text("import scripts._sleeper_fake_session\n")

    # "Clean clone" precondition: copy the shipped reference
    # fixtures into audit_root/reference/.
    shipped_ref = REPO_ROOT / "data/source_audits/sleeper_qb_v1/reference"
    audit_ref = audit_root / "reference"
    shutil.copytree(shipped_ref, audit_ref)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "version: sleeper-qb-audit-config-v1",
                "endpoint: https://api.sleeper.app/v1/players/nfl",
                f"audit_root: {audit_root}",
                f"nflverse_qb_path: {audit_ref / 'nflverse_player_identity_pre2025.parquet'}",
                "staleness_threshold_seconds: 21600",
                f"reference_manifest: {REPO_ROOT / 'data/source_audits/sleeper_qb_v1/reference/manifest.json'}",
            ]
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "collect_sleeper_qbs.py"),
            "--config",
            str(config_path),
            "--kind",
            "scheduled",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"returncode={result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    payload = json.loads(result.stdout)
    assert payload["run_outcome"] == "SUCCESS"
    assert payload["exit_code"] == 0
    # When the reference-manifest verification succeeds, the
    # orchestrator does not emit a ReferenceVerificationError
    # error_class (the failure path returns that class as the
    # run outcome).
    assert payload.get("error_class") in (None, "None")
    # The audit must have actually run end-to-end, not just
    # verified the manifest.
    assert (audit_root / "fetch_ledger.parquet").exists()
    assert (audit_root / "normalized" / "qb_snapshots.parquet").exists()
