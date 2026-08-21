"""Provenance for the corrected Market Edge scorer run, incl. superseded markers."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..common import fingerprint as fp

PINNED_FINGERPRINT = "d195340940e5c9d6c9f62bbfbb8f8f50836013e05334e870f0905d3592d62e5c"
LOCK_HASH_FIELD = "candidate_lock_sha256"
EXPECTED_LOCK_HASH = "41c909823a58e9fb5d7de6a4be8c4de55537974d61ddaedffd12acd8c119ead0"


def verify_lock_hash(lock_path: str | Path) -> None:
    """Recompute the canonical candidate-lock hash (neutralizing the self field)."""
    text = Path(lock_path).read_text(encoding="utf-8")
    canon = "\n".join(l for l in text.splitlines()
                      if not l.strip().startswith(f'"{LOCK_HASH_FIELD}"'))
    d = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    if d != EXPECTED_LOCK_HASH:
        raise RuntimeError(f"candidate lock canonical hash mismatch: got {d}")


def superseded_note(old_paths: list[str]) -> dict:
    """Provenance entry marking the old D4/D5 artifacts as superseded."""
    return {
        "status": "SUPERSEDED_INVALID_IMPLEMENTATION",
        "note": ("Preserved unmodified for audit; implementation superseded by the "
                 "repo-native scorer (`src/nfl_edge/market_edge`) applying the five "
                 "mechanical corrections. Not deleted on instruction."),
        "old_artifacts": old_paths,
    }


def build_provenance(*, repo_root: Path, ledgers: dict, summaries: list,
                     comparison: str, old_artifacts: list[str],
                     superseded: list[str]) -> dict:
    """Assemble the corrected-run provenance document with artifact hashes."""
    hashes = {name: fp.sha256_file(Path(repo_root) / p) for name, p in
              {"config": "config/market_edge_validation_v1.yaml",
               "lock": "reports/task_05e_d5_candidate_lock.json"}.items()}
    return {
        "task": "05E remediation — permanent repo-native scorer/replay",
        "prereg_fingerprint": PINNED_FINGERPRINT,
        "candidate_lock_hash": EXPECTED_LOCK_HASH,
        "method": "src/nfl_edge/market_edge (scoring/shopping/candidates/aggregate)",
        "corrections": {
            "1_avg_both_constituents": "AVG exists only when QB-Elo AND XGBoost predictions both exist for the game; no fallback",
            "2_spread_shopping": "selected-side best number first, then better price, then deterministic tie-break",
            "3_exact_raw_boundaries": "buckets/dog-zone/price boundaries use exact raw numeric values, no rounded/report bins",
            "4_one_row_ledger": "single authoritative row-ledger feeds all grading and reporting",
            "5_deterministic_grading": "same-side W/L/P from game_id/final score; actual DK/FD actionable prices; Pinnacle benchmark only",
        },
        "periods_run_separately": ["DISCOVERY 2020-2022", "CONFIRMATION 2023-2024"],
        "sealed_2025": {"touched": False, "policy": "HARD_REJECT"},
        "ledger_artifact_hashes": {name: fp.sha256_file(path) for name, path in ledgers.items()},
        "superseded_invalid_implementation": superseded,
        "old_artifact_hashes": {name: fp.sha256_file(Path(repo_root) / p) for name, p in
                                [("d4", "reports/task_05e_d4_discovery_results.csv"),
                                 ("d5.csv", "reports/task_05e_d5_confirmation_results.csv"),
                                 ("d5.md", "reports/task_05e_d5_confirmation_results.md"),
                                 ("d5_scored", "data/modeling/development_v1/market_edge_confirmation_scored_v1.parquet"),
                                 ("d4_scored", "data/modeling/development_v1/market_edge_discovery_scored_v1.parquet")]},
    }