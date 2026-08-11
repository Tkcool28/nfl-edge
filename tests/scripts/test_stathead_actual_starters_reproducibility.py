"""Focused integrity tests for the hardened Task04A final builder and the
deterministic v2 resolution ledger generation."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DERIVED = REPO_ROOT / "data" / "derived" / "stathead_actual_starters_v1"
SCRIPT_DIR = REPO_ROOT / "scripts" / "stathead_actual_starters"

SUBSET_SHA = "d554c7c2ab5114bc70d0f04a46feba0ef46ab53c717769f8c04f88b98e976742"
V2_SHA = "333a399288bda0405e6e8c10ac391740b681cf2de9b55ecc87afe60222df022d"


def _load(name: str):
    path = SCRIPT_DIR / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tree(tmp_path: Path, subdir: str = "data/derived/stathead_actual_starters_v1") -> Path:
    """Copy frozen derived tree into tmp so mutations never touch repo files."""
    target = tmp_path / subdir
    shutil.copytree(DERIVED, target)
    return target


def _outdir(b: Path) -> Path:
    o = b / "final_oracle_starters"
    o.mkdir(parents=True, exist_ok=True)
    return o


# ---------------------------------------------------------------------------
# Crosswalk subset integrity
# ---------------------------------------------------------------------------
def test_crosswalk_subset_contains_exactly_required_ids():
    subset = DERIVED / "identity_crosswalk" / "task04a_player_crosswalk_v1.csv"
    assert subset.exists()
    assert hashlib.sha256(subset.read_bytes()).hexdigest() == SUBSET_SHA
    with open(subset, newline="") as f:
        rows = list(csv.DictReader(f))
    assert set(rows[0]) == {"pfr_id", "gsis_id", "display_name", "position"}
    pfr = [r["pfr_id"] for r in rows]
    assert len(rows) == 138
    assert len(set(pfr)) == 138, "duplicate PFR ids in subset"
    assert all(r["pfr_id"] for r in rows), "blank PFR"
    assert all(r["gsis_id"] for r in rows), "blank GSIS for consumed identity"


def test_missing_crosswalk_identity_fails(tmp_path):
    builder = _load("build_final_oracle_starters.py")
    b = _tree(tmp_path)
    subset = b / "identity_crosswalk" / "task04a_player_crosswalk_v1.csv"
    with open(subset, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pfr_id", "gsis_id", "display_name", "position"])
        w.writerow(["HintKe00", "00-0035864", "Kendall Hinton", "WR"])
    _outdir(b)
    with pytest.raises((AssertionError, KeyError)):
        builder.main(B=b)


# ---------------------------------------------------------------------------
# Resolution ledger integrity
# ---------------------------------------------------------------------------
def test_duplicate_resolution_key_fails(tmp_path):
    builder = _load("build_final_oracle_starters.py")
    b = _tree(tmp_path)
    v2 = b / "manual_starter_review" / "web_researched_starter_resolutions_v2.csv"
    rows = list(csv.DictReader(open(v2, newline="")))
    assert len(rows) == 99
    rows.append(dict(rows[0]))  # duplicate key
    with open(v2, "w", newline="") as f:
        _write(f, rows)
    _outdir(b)
    with pytest.raises(AssertionError):
        builder.main(B=b)


def test_extra_resolution_key_fails(tmp_path):
    builder = _load("build_final_oracle_starters.py")
    b = _tree(tmp_path)
    v2 = b / "manual_starter_review" / "web_researched_starter_resolutions_v2.csv"
    rows = list(csv.DictReader(open(v2, newline="")))
    extra = dict(rows[0])
    s1 = b / "stage01_canonical_reconciliation" / "game_side_candidates.csv"
    sd = {(r["game_id"], r["team_side"]): r for r in csv.DictReader(open(s1, newline=""))}
    sing = next(k for k, v in sd.items() if v["candidate_count"] == "1")
    extra["game_id"], extra["team_side"] = sing
    rows.append(extra)
    with open(v2, "w", newline="") as f:
        _write(f, rows)
    _outdir(b)
    with pytest.raises(AssertionError):
        builder.main(B=b)


def test_missing_expected_exception_key_fails(tmp_path):
    builder = _load("build_final_oracle_starters.py")
    b = _tree(tmp_path)
    v2 = b / "manual_starter_review" / "web_researched_starter_resolutions_v2.csv"
    rows = list(csv.DictReader(open(v2, newline="")))
    rows = rows[:-1]  # drop the last exception key
    with open(v2, "w", newline="") as f:
        _write(f, rows)
    _outdir(b)
    with pytest.raises(AssertionError):
        builder.main(B=b)


def test_canonical_team_mismatch_fails(tmp_path):
    builder = _load("build_final_oracle_starters.py")
    b = _tree(tmp_path)
    v2 = b / "manual_starter_review" / "web_researched_starter_resolutions_v2.csv"
    rows = list(csv.DictReader(open(v2, newline="")))
    rows[0]["canonical_team"] = "WRONG"
    with open(v2, "w", newline="") as f:
        _write(f, rows)
    _outdir(b)
    with pytest.raises(AssertionError):
        builder.main(B=b)


def test_2025_stage01_row_fails(tmp_path):
    builder = _load("build_final_oracle_starters.py")
    b = _tree(tmp_path)
    s1 = b / "stage01_canonical_reconciliation" / "game_side_candidates.csv"
    rows = list(csv.DictReader(open(s1, newline="")))
    rows[0]["season"] = "2025"
    with open(s1, "w", newline="") as f:
        _write(f, rows)
    _outdir(b)
    with pytest.raises(AssertionError):
        builder.main(B=b)


def test_duplicate_final_side_fails(tmp_path):
    builder = _load("build_final_oracle_starters.py")
    b = _tree(tmp_path)
    s1 = b / "stage01_canonical_reconciliation" / "game_side_candidates.csv"
    rows = list(csv.DictReader(open(s1, newline="")))
    rows.append(dict(rows[0]))  # duplicate (game_id, team_side)
    with open(s1, "w", newline="") as f:
        _write(f, rows)
    _outdir(b)
    with pytest.raises(AssertionError):
        builder.main(B=b)


# ---------------------------------------------------------------------------
# Kendall Hinton + v2 deterministic generation
# ---------------------------------------------------------------------------
def _stage_copy(tmp_path: Path, name: str):
    root = tmp_path / name
    shutil.copytree(REPO_ROOT / "scripts", root / "scripts")
    shutil.copytree(DERIVED, root / "data" / "derived" / "stathead_actual_starters_v1")
    return root


def test_kendall_hinton_special_case_generates_correctly(tmp_path):
    resolv = _load("validate_web_starter_resolutions.py")
    root = _stage_copy(tmp_path, "repo")
    resolv.main(R_=root)
    v2 = (root / "data" / "derived" / "stathead_actual_starters_v1" / "manual_starter_review"
          / "web_researched_starter_resolutions_v2.csv")
    rows = list(csv.DictReader(open(v2, newline="")))
    hinton = next(r for r in rows if r["game_id"] == "2020_12_NO_DEN" and r["team_side"] == "home")
    assert hinton["actual_starting_qb_name"] == "Kendall Hinton"
    assert hinton["actual_starting_qb_pfr_id"] == "HintKe00"
    assert hinton["actual_starting_qb_gsis_id"] == "00-0035864"
    assert hinton["identity_mapping_status"].startswith("SPECIAL")


def test_v2_ledger_generation_reproduces_expected_hash(tmp_path):
    resolv = _load("validate_web_starter_resolutions.py")
    root = _stage_copy(tmp_path, "repo")
    resolv.main(R_=root)
    v2 = (root / "data" / "derived" / "stathead_actual_starters_v1" / "manual_starter_review"
          / "web_researched_starter_resolutions_v2.csv")
    assert hashlib.sha256(v2.read_bytes()).hexdigest() == V2_SHA
    rep2 = v2.with_name("web_researched_starter_resolution_report_v2.json")
    assert rep2.exists()


def _write(f, rows) -> None:
    w = csv.DictWriter(f, rows[0])
    w.writeheader()
    w.writerows(rows)