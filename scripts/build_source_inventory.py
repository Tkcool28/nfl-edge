#!/usr/bin/env python3
"""Source inventory + PBP provenance + builder source identity for Task05C closeout."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, "/root/workspaces/nfl-edge-totals-feature-contract-v1/src")

W = Path("/root/workspaces/nfl-edge-totals-feature-contract-v1")
PBPROOT = Path("/var/lib/chatgpt-vps-mcp/artifacts/nfl-edge/raw/task05c_pbp_v1")

PBP_MAN = {
    2018: ("play_by_play_2018.parquet", 19072097, "2e6f2dce7c7ebd46e985cabe0c17eb72b39a77f98cb4478409294f50b5820150"),
    2019: ("play_by_play_2019.parquet", 19119729, "60c3067017db2d28a78f66a79b657268be8578d9a5288e6a827efdcd7fe42540"),
    2020: ("play_by_play_2020.parquet", 19311336, "73b7dbf66fa8cb9356f58bf6b1f15a0fee197ecc10cf4983b640cb9679b15cb4"),
    2021: ("play_by_play_2021.parquet", 20249925, "333ad34378e5339d5172717cc83378e908daf02c8699416ab3e17c2ec10f78d8"),
    2022: ("play_by_play_2022.parquet", 20426548, "931121d8897779d7944e2a293e92ed8799c8e5cceef84096ac42339003fedc09"),
    2023: ("play_by_play_2023.parquet", 20534088, "bd3484731408def6b0ec93225bba2bd7b2c65769ca707a2b9444d891abdc6776"),
    2024: ("play_by_play_2024.parquet", 20576368, "6d432dd4308329bfddaef633309ea119f9ca46d52cbb3c09f47172a2e8efcd01"),
}

def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def verify_pbp():
    out = {}
    for s, (fn, sz, sha_exp) in sorted(PBP_MAN.items()):
        p = PBPROOT / fn
        r = {"season": s, "filename": fn, "path": str(p), "exists": p.exists()}
        if p.exists():
            r["byte_size"] = p.stat().st_size
            r["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
            r["byte_ok"] = r["byte_size"] == sz
            r["sha_ok"] = r["sha256"] == sha_exp
        else:
            r["byte_ok"] = r["sha_ok"] = False
        out[str(s)] = r
    return out

def auto_entry(path, classification, relevance, seasons=None, acquisition=None):
    p = W / path if not path.startswith("/") else Path(path)
    r = {"artifact_path": str(p), "format": "parquet", "seasons": seasons,
         "relevance": relevance, "initial_task05c_classification": classification}
    if acquisition:
        r["acquisition_status"] = acquisition
    try:
        df = pl.read_parquet(p)
        r["rows"] = df.height
        r["columns_count"] = df.width
        r["sample_columns"] = df.columns[:10]
        r["sha256"] = sha256(p)
        r["byte_size"] = p.stat().st_size
    except Exception as e:
        r["read_error"] = str(e)
    return r

def main():
    pbp = verify_pbp()
    all_ok = all(v["sha_ok"] and v["byte_ok"] for v in pbp.values())
    print(f"PBP all ok: {all_ok}")

    sources = []

    # PBP entries (SOURCE_REQUIRED with ACQUIRED status)
    for k, v in pbp.items():
        if v.get("exists"):
            sources.append({
                "season": int(k), "artifact_path": v["path"], "format": "parquet",
                "seasons": [int(k)],
                "relevance": "nflverse promoted PBP; canonical source for Totals V1 PBP-derived features",
                "initial_task05c_classification": "SOURCE_REQUIRED",
                "acquisition_status": "ACQUIRED",
                "sha256": v["sha256"], "byte_size": v["byte_size"],
                "byte_ok": v["byte_ok"], "sha_ok": v["sha_ok"],
            })

    # Existing available sources
    sources.append(auto_entry(
        "data/frozen/games/games_2018_2025.parquet", "AVAILABLE_RAW",
        "Canonical games table: identity/block/team/roof mapping + home_score/away_score",
        seasons=[2018,2019,2020,2021,2022,2023,2024,2025]))
    sources.append(auto_entry(
        "data/raw/source_snapshots/v1/schedules_2018_2025_frozen-baseline-v1.parquet", "AVAILABLE_RAW",
        "Frozen schedule: rest/gameday/roof/surface; PBP context projected from this",
        seasons=[2018,2019,2020,2021,2022,2023,2024,2025]))
    sources.append(auto_entry(
        "data/frozen/team_game_stats/team_game_stats_2018_2025.parquet", "AVAILABLE_RAW",
        "Frozen team game stats: passing_epa/rushing_epa (audit cross-check only per contract)",
        seasons=[2018,2019,2020,2021,2022,2023,2024,2025]))
    sources.append(auto_entry(
        "data/frozen/qb_game_stats/qb_game_stats_2018_2025.parquet", "AVAILABLE_RAW",
        "Frozen QB game stats (NOT used for Totals V1 QB state; Oracle interface reused)",
        seasons=[2018,2019,2020,2021,2022,2023,2024,2025]))
    sources.append(auto_entry(
        "data/frozen/rosters/rosters_2018_2025.parquet", "AVAILABLE_RAW",
        "Frozen rosters (not directly used by Totals V1; reference/potential future use)",
        seasons=[2018,2019,2020,2021,2022,2023,2024,2025]))
    sources.append(auto_entry(
        "data/frozen/depth_chart_snapshots/depth_chart_snapshots_2018_2025.parquet", "DEFER",
        "Frozen depth chart snapshots (deferred per contract; not in Totals V1)",
        seasons=[2018,2019,2020,2021,2022,2023,2024,2025]))
    sources.append(auto_entry(
        "data/frozen/venues/venues_2018_2025.parquet", "AVAILABLE_RAW",
        "Frozen venues: venue metadata (not directly used; roof/surface via games or schedules)",
        seasons=[2018,2019,2020,2021,2022,2023,2024,2025]))

    # Derived artifacts
    sources.append(auto_entry(
        "data/derived/oracle_qb_entering_state_v2/oracle_qb_entering_state_game_sides_2018_2024_v2.parquet",
        "DERIVABLE_EXISTING",
        "Accepted Oracle QB entering-state v2 interface: Totals V1 QB features joined from this",
        seasons=[2018,2019,2020,2021,2022,2023,2024]))
    sources.append(auto_entry(
        "data/derived/totals_v1_features_2018_2024.parquet",
        "DERIVABLE_EXISTING",
        "Final Totals V1 90-feature artifact (accepted build output)",
        seasons=[2018,2019,2020,2021,2022,2023,2024]))
    sources.append(auto_entry(
        "data/derived/totals_v1_feature_identity_2018_2024.parquet",
        "DERIVABLE_EXISTING",
        "Final Totals V1 7-col identity artifact (accepted build output)",
        seasons=[2018,2019,2020,2021,2022,2023,2024]))
    sources.append(auto_entry(
        "data/derived/totals_v1_modeling_table_2018_2024.parquet",
        "DERIVABLE_EXISTING",
        "Final Totals V1 modeling table (90 features + 7 identity + home_score + away_score + target_total_points)",
        seasons=[2018,2019,2020,2021,2022,2023,2024]))

    # Expected-Margin inputs (for cross-reference)
    sources.append(auto_entry(
        "data/derived/features_v1/xgboost_development_2018_2024.parquet",
        "DERIVABLE_EXISTING",
        "Prior Expected-Margin XGBoost development table (not Totals V1; cross-reference only)",
        seasons=[2018,2019,2020,2021,2022,2023,2024]))

    inventory = {"schema_version": "task05c_source_inventory_v1",
                  "pbp_manifest": pbp,
                  "pbp_all_integrity_pass": all_ok,
                  "sources": sources}

    out_path = W / "data/manifests/task05c_source_inventory_v1.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(inventory, indent=2, default=str)
    out_path.write_text(txt + "\n")
    print(f"wrote {out_path}")
    print(f"byte_sha256={hashlib.sha256(out_path.read_bytes()).hexdigest()}")

    # ---- Builder source identity (§15) ----
    totals_dir = W / "src/nfl_edge/features/totals_v1"
    py_files = sorted(totals_dir.glob("*.py")) if totals_dir.exists() else []
    # also the context_features and entering_state and other helpers used by totals_v1
    other_helpers = sorted(W.glob("src/nfl_edge/features/*.py"))  # __init__ etc
    source_files = []
    for f in list(py_files) + list(other_helpers):
        if f.suffix == ".py":
            source_files.append(f)
    # dedup
    seen = set()
    source_files_dedup = []
    for f in source_files:
        if str(f) not in seen:
            seen.add(str(f))
            source_files_dedup.append(f)
    source_files_dedup.sort()

    entries = []
    for f in source_files_dedup:
        s = sha256(f)
        entries.append(f"file:{f.relative_to(W)}\t{s}")
        # also record in source inventory
    # aggregate SHA-256 over sorted "path<tab>sha256" manifest
    aggregate = hashlib.sha256("\n".join(entries).encode()).hexdigest()
    builder_identity = {"aggregate_builder_source_hash": aggregate,
                        "file_hashes": [{"path": str(f.relative_to(W)), "sha256": sha256(f)} for f in source_files_dedup]}

    identity_path = W / "data/manifests/task05c_builder_source_identity_v1.json"
    identity_path.write_text(json.dumps(builder_identity, indent=2) + "\n")
    print(f"wrote {identity_path}")
    print(f"builder aggregate hash: {aggregate}")
    print(f"source files: {len(source_files_dedup)}")

    return pbp, all_ok, inventory, builder_identity

if __name__ == "__main__":
    main()