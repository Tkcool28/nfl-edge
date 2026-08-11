"""Narrow Task04C oracle-vs-baseline comparison report generator.

Rebuilds the oracle-vs-baseline comparison report from the FROZEN prediction,
transition, and per-game diagnostic parquets. It does NOT regenerate
predictions or transitions and does NOT modify any frozen data artifact.

Fail-closed gates enforced before scoring:
  - oracle adjustment coverage of the canonical development-game universe
    (``OracleQBAdjustments.assert_coverage``);
  - baseline/oracle paired game-universe equality (same rows, same game_ids,
    no duplicates, no 2025 rows).

Binary scoring policy: canonical coverage universe stays 1,942 games. Tied
games (7) remain part of coverage/alignment/identity validation but are
EXCLUDED from binary win-probability metrics in every score block
(Brier / log loss / accuracy / deltas / BSS). Binary scored population = 1,935.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import polars as pl

from nfl_edge.backtest.task04c_paired_evaluation import OracleQBAdjustments

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = REPO_ROOT / "data/derived/qb_elo_oracle_comparison_v1"
ORACLE_PARQUET = (
    REPO_ROOT
    / "data/derived/oracle_qb_entering_state_v2"
    / "oracle_qb_pregame_adjustments_by_game_2018_2024_v2.parquet"
)
STARTER_LEDGER = (
    REPO_ROOT
    / "data/derived/stathead_actual_starters_v1/final_oracle_starters"
    / "actual_starting_qb_game_sides_2018_2024_v1.csv"
)
CONFIG_YAML = REPO_ROOT / "config/qb_elo_v1.yaml"
GAME_SIDES = (
    REPO_ROOT
    / "data/derived/oracle_qb_entering_state_v2"
    / "oracle_qb_entering_state_game_sides_2018_2024_v2.parquet"
)

ORACLE_PARQUET_SHA = "268368c81913e183d7e9ea5050c0da0a01be619790b75c5bab9362c97349e886"
STARTER_LEDGER_SHA = "38732823861bb1def3c216ce9189b651a2dc4d0737d2f65f88f17e97f40b2a1a"

# Repo-relative provenance paths (deterministic across checkouts).
ORACLE_INPUT_REL = "data/derived/oracle_qb_entering_state_v2/oracle_qb_pregame_adjustments_by_game_2018_2024_v2.parquet"
STARTER_LEDGER_REL = (
    "data/derived/stathead_actual_starters_v1/final_oracle_starters/"
    "actual_starting_qb_game_sides_2018_2024_v1.csv"
)
BASE_REL = "data/derived/qb_elo_oracle_comparison_v1"
BASELINE_PREDS_REL = f"{BASE_REL}/qb_elo_baseline_predictions_2018_2024.parquet"
ORACLE_PREDS_REL = f"{BASE_REL}/qb_elo_oracle_predictions_2018_2024.parquet"
BASELINE_TRANS_REL = f"{BASE_REL}/qb_elo_baseline_transitions_2018_2024.parquet"
ORACLE_TRANS_REL = f"{BASE_REL}/qb_elo_oracle_transitions_2018_2024.parquet"
EVALUATOR_SOURCE_REL = "scripts/task04c_build_oracle_comparison_report.py"

TIE_GAME_IDS = [
    "2018_01_PIT_CLE", "2018_02_MIN_GB", "2019_01_DET_ARI", "2020_03_CIN_PHI",
    "2021_10_DET_PIT", "2022_01_IND_HOU", "2022_13_WAS_NYG",
]


def _sha256_bytes(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _current_git_head() -> str:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, timeout=10,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _metrics(p: list[float], y: list[float]) -> dict[str, float]:
    n = len(y)
    assert n > 0, "empty scored population"
    brier = sum((pi - yi) ** 2 for pi, yi in zip(p, y)) / n
    ll = 0.0
    for pi, yi in zip(p, y):
        pi = max(1e-15, min(1.0 - 1e-15, float(pi)))
        ll += -(yi * math.log(pi) + (1 - yi) * math.log(1 - pi))
    ll /= n
    acc = sum(1 for pi, yi in zip(p, y) if (pi >= 0.5) == (yi == 1.0)) / n
    return {"brier": brier, "logloss": ll, "accuracy": acc}


class PairedFrame:
    """Row-aligned baseline/oracle over the canonical game universe."""

    def __init__(self, base: pl.DataFrame, oracle: pl.DataFrame) -> None:
        self.gids = oracle["game_id"].to_list()
        self.base_p = dict(zip(base["game_id"].to_list(), base["predicted_home_win_probability"].to_list()))
        self.ora_p = dict(zip(oracle["game_id"].to_list(), oracle["predicted_home_win_probability"].to_list()))
        self.ora_y = dict(zip(oracle["game_id"].to_list(), oracle["target_outcome"].to_list()))
        self.ora_margin = dict(zip(oracle["game_id"].to_list(), oracle["target_margin"].to_list()))
        self.week = dict(zip(oracle["game_id"].to_list(), oracle["week"].to_list()))
        self.st = dict(zip(oracle["game_id"].to_list(), oracle["season_type"].to_list()))

    def block(self, gid_mask) -> dict[str, object]:
        gs = [g for g, keep in zip(self.gids, gid_mask) if keep]
        margin = [self.ora_margin[g] for g in gs]
        cov = len(gs)
        ties = sum(1 for m in margin if m == 0.0)
        # binary scored = coverage mask minus ties
        bin_gs = [g for g, m in zip(gs, margin) if m != 0.0]
        if not bin_gs:
            return {
                "coverage_games": cov, "tied_games": ties, "binary_scored_games": 0,
                "mean_abs_delta_p": None, "baseline_brier": None, "baseline_logloss": None,
                "baseline_accuracy": None, "oracle_brier": None, "oracle_logloss": None,
                "oracle_accuracy": None,
            }
        p_b2 = [self.base_p[g] for g in bin_gs]
        p_o2 = [self.ora_p[g] for g in bin_gs]
        y2 = [self.ora_y[g] for g in bin_gs]
        mb = _metrics(p_b2, y2)
        mo = _metrics(p_o2, y2)
        delta = [abs(self.ora_p[g] - self.base_p[g]) for g in gs]
        return {
            "coverage_games": cov,
            "tied_games": ties,
            "binary_scored_games": len(bin_gs),
            "mean_abs_delta_p": float(sum(delta) / len(delta)),
            "baseline_brier": mb["brier"],
            "baseline_logloss": mb["logloss"],
            "baseline_accuracy": mb["accuracy"],
            "oracle_brier": mo["brier"],
            "oracle_logloss": mo["logloss"],
            "oracle_accuracy": mo["accuracy"],
        }


def main() -> dict[str, object]:
    baseline = pl.read_parquet(BASE / "qb_elo_baseline_predictions_2018_2024.parquet")
    oracle = pl.read_parquet(BASE / "qb_elo_oracle_predictions_2018_2024.parquet")
    per_game = pl.read_parquet(BASE / "qb_elo_oracle_comparison_by_game_2018_2024.parquet")

    # ---- paired-alignment + oracle coverage gate (fail closed) ----
    enforce_task04c_gates(baseline, oracle, oracle_parquet=ORACLE_PARQUET)
    assert _sha256_bytes(ORACLE_PARQUET) == ORACLE_PARQUET_SHA, "oracle parquet SHA mismatch"
    # Transitions must be byte-identical between modes.
    bt = pl.read_parquet(BASE / "qb_elo_baseline_transitions_2018_2024.parquet")
    ot = pl.read_parquet(BASE / "qb_elo_oracle_transitions_2018_2024.parquet")
    assert bt.height == ot.height
    assert _sha256_bytes(BASE / "qb_elo_baseline_transitions_2018_2024.parquet") == \
        _sha256_bytes(BASE / "qb_elo_oracle_transitions_2018_2024.parquet"), \
        "baseline/oracle transitions must be byte-identical"

    # ---- tie accounting ----
    margin_by = dict(zip(oracle["game_id"].to_list(), oracle["target_margin"].to_list()))
    tie_ids_sorted = sorted(g for g in margin_by if margin_by[g] == 0.0)
    assert tie_ids_sorted == sorted(TIE_GAME_IDS), (
        f"tie game ids mismatch: {tie_ids_sorted}"
    )
    pf = PairedFrame(baseline, oracle)
    gids = oracle["game_id"].to_list()

    # ---- primary (all universe, binary tie-excluded) ----
    primary = pf.block([True] * len(gids))
    brier_delta = primary["oracle_brier"] - primary["baseline_brier"]
    ll_delta = primary["oracle_logloss"] - primary["baseline_logloss"]
    acc_delta = primary["oracle_accuracy"] - primary["baseline_accuracy"]
    bss = 1.0 - primary["oracle_brier"] / primary["baseline_brier"]

    def mask_season(s: int) -> list[bool]:
        return [int(g.split("_")[0]) == s for g in gids]

    def mask_regpost(post: bool) -> list[bool]:
        return [pf.st[g] != "REG" if post else pf.st[g] == "REG" for g in gids]

    def mask_weeks14(s: int) -> list[bool]:
        return [int(g.split("_")[0]) == s and int(pf.week[g]) <= 4 for g in gids]

    season_blocks = {str(s): pf.block(mask_season(s)) for s in range(2018, 2025)}
    regpost_blocks = {
        "POST": pf.block(mask_regpost(True)),
        "REG": pf.block(mask_regpost(False)),
    }
    weeks_blocks = {str(s): pf.block(mask_weeks14(s)) for s in range(2018, 2025)}
    weeks_agg_mask = [int(g.split("_")[0]) in range(2018, 2025) and int(pf.week[g]) <= 4 for g in gids]
    weeks_agg = pf.block(weeks_agg_mask)

    # ---- zero-history groups ----
    sides = pl.read_parquet(GAME_SIDES)
    zero_keys = set(
        sides.filter(pl.col("prior_games") == 0)
        .select(
            pl.col("game_id") + pl.lit(":") + pl.col("team_side")
        ).to_series().to_list()
    )
    zero_game_ids = {k.split(":")[0] for k in zero_keys}
    group_a_mask = [g in zero_game_ids for g in gids]
    group_b_mask = [g not in zero_game_ids for g in gids]
    group_a = pf.block(group_a_mask)
    group_b = pf.block(group_b_mask)

    # ---- zero-history descriptive counts (from oracle game-sides, full universe) ----
    sides_by_game = sides.filter(pl.col("game_id").is_in(set(gids)))
    two_zero = int(sides_by_game.filter(pl.col("prior_games") == 0)
                   .group_by("game_id").len()
                   .filter(pl.col("len") == 2).height)
    one_zero = int(sides_by_game.filter(pl.col("prior_games") == 0)
                   .group_by("game_id").len()
                   .filter(pl.col("len") == 1).height)
    zero_sides_total = int(sides_by_game.filter(pl.col("prior_games") == 0).height)

    # ---- favorite flips / probability impact (frozen per-game diagnostics) ----
    per = per_game.to_pandas()
    fav_flips = {
        "baseline_eq_0.50": int((per["baseline_home_win_probability"] == 0.50).sum()),
        "flip_count": int(per["favorite_flip"].sum()),
        "oracle_eq_0.50": int((per["oracle_home_win_probability"] == 0.50).sum()),
    }
    dabs = per["absolute_delta_p"].tolist()
    prob_impact = {
        "changed": int((per["absolute_delta_p"] > 0).sum()),
        "unchanged": int((per["absolute_delta_p"] == 0).sum()),
        "count_ge_0.02": int((per["absolute_delta_p"] >= 0.02).sum()),
        "count_ge_0.05": int((per["absolute_delta_p"] >= 0.05).sum()),
        "count_ge_0.10": int((per["absolute_delta_p"] >= 0.10).sum()),
        "max_abs_delta_p": float(max(dabs)),
        "mean_abs_delta_p": float(sum(dabs) / len(dabs)),
        "median_abs_delta_p": float(sorted(dabs)[len(dabs) // 2]),
    }

    # ---- provenance / deterministic repository-state id ----
    source_path = REPO_ROOT / "scripts" / "task04c_build_oracle_comparison_report.py"
    source_sha = _sha256_bytes(source_path)
    gen_head = _current_git_head()
    repo_state_id = hashlib.sha256(
        ("|".join([
            source_sha,
            _sha256_bytes(ORACLE_PARQUET),
            _sha256_bytes(STARTER_LEDGER),
            _sha256_bytes(CONFIG_YAML),
            _sha256_bytes(BASE / "qb_elo_baseline_predictions_2018_2024.parquet"),
            _sha256_bytes(BASE / "qb_elo_baseline_transitions_2018_2024.parquet"),
        ])).encode()
    ).hexdigest()

    season_counts = {}
    for s in range(2018, 2025):
        season_counts[str(s)] = int(oracle.filter(pl.col("season") == s).height)

    report: dict[str, object] = {
        "dataset": "task04c_oracle_vs_baseline_v1",
        "coverage_games": 1942,
        "tied_games": 7,
        "binary_scored_games": 1935,
        "binary_scoring_policy": "EXCLUDE_TIED_GAMES",
        "tie_game_ids": sorted(TIE_GAME_IDS),
        "games_2025_target": 0,
        "official_verdict": "RESERVED_FOR_MASTER_REVIEW",
        "coverage": {
            "games": 1942,
            "games_2025_target": 0,
            "post": int(oracle.filter(pl.col("season_type") != "REG").height),
            "reg": int(oracle.filter(pl.col("season_type") == "REG").height),
            "season_counts": season_counts,
        },
        "favorite_flips": fav_flips,
        "probability_impact": prob_impact,
        "primary_scorecard": {
            "baseline_brier": primary["baseline_brier"],
            "baseline_logloss": primary["baseline_logloss"],
            "baseline_accuracy": primary["baseline_accuracy"],
            "oracle_brier": primary["oracle_brier"],
            "oracle_logloss": primary["oracle_logloss"],
            "oracle_accuracy": primary["oracle_accuracy"],
            "brier_delta": brier_delta,
            "logloss_delta": ll_delta,
            "accuracy_delta": acc_delta,
            "bss": bss,
        },
        "reg_post": regpost_blocks,
        "season": season_blocks,
        "weeks_1_4": weeks_blocks,
        "weeks_1_4_aggregate": weeks_agg,
        "zero_history": {
            "games_exactly_one_zero_side": one_zero,
            "games_two_zero_sides": two_zero,
            "nonzero_history_sides": 3884 - zero_sides_total,
            "zero_history_sides": zero_sides_total,
            "group_A": group_a,
            "group_B": group_b,
        },
        "input_artifact_hashes": {
            "baseline_file": _sha256_bytes(BASE / "qb_elo_baseline_predictions_2018_2024.parquet"),
            "oracle_file": _sha256_bytes(BASE / "qb_elo_oracle_predictions_2018_2024.parquet"),
        },
        "provenance": {
            "repository_state_id": repo_state_id,
            "evaluator_source_path": EVALUATOR_SOURCE_REL,
            "evaluator_source_sha256": source_sha,
            "git_commit_sha": gen_head,
            "qb_elo_config_path": "config/qb_elo_v1.yaml",
            "qb_elo_config_sha256": _sha256_bytes(CONFIG_YAML),
            "oracle_input_path": ORACLE_INPUT_REL,
            "oracle_input_sha256": _sha256_bytes(ORACLE_PARQUET),
            "starter_ledger_path": STARTER_LEDGER_REL,
            "starter_ledger_sha256": _sha256_bytes(STARTER_LEDGER),
            "baseline_predictions_path": BASELINE_PREDS_REL,
            "baseline_predictions_sha256": _sha256_bytes(BASE / "qb_elo_baseline_predictions_2018_2024.parquet"),
            "oracle_predictions_path": ORACLE_PREDS_REL,
            "oracle_predictions_sha256": _sha256_bytes(BASE / "qb_elo_oracle_predictions_2018_2024.parquet"),
            "baseline_transitions_path": BASELINE_TRANS_REL,
            "baseline_transitions_sha256": _sha256_bytes(BASE / "qb_elo_baseline_transitions_2018_2024.parquet"),
            "oracle_transitions_path": ORACLE_TRANS_REL,
            "oracle_transitions_sha256": _sha256_bytes(BASE / "qb_elo_oracle_transitions_2018_2024.parquet"),
        },
    }

    out_path = BASE / "qb_elo_oracle_comparison_report_v1.json"
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["primary_scorecard"], indent=2))
    print("written:", out_path)
    return report


def enforce_task04c_gates(
    baseline: pl.DataFrame,
    oracle: pl.DataFrame,
    oracle_adjustments: OracleQBAdjustments | None = None,
    *,
    oracle_parquet: Path | None = None,
) -> OracleQBAdjustments:
    """Fail-closed paired-alignment + oracle coverage gate for Task04C.

    Validates that baseline and oracle predictions share exactly the same
    canonical development-game universe (no duplicates, no 2025 rows) and that
    the oracle adjustment artifact covers exactly that universe. Returns the
    oracle adjustment provider so the caller can resolve adjustments during
    scoring. This must run before any paired scoring/report generation.
    """
    for name, f in (("baseline", baseline), ("oracle", oracle)):
        assert int(f.height) == 1942, f"{name} must have 1942 rows, got {f.height}"
        assert int(f.filter(pl.col("season") > 2024).height) == 0, f"{name} contains 2025 rows"
        gids = f["game_id"].to_list()
        assert len(gids) == len(set(gids)), f"{name} has duplicate game_ids"
    assert set(baseline["game_id"].to_list()) == set(oracle["game_id"].to_list()), \
        "baseline/oracle game universes differ"
    universe = sorted(set(oracle["game_id"].to_list()))
    assert len(universe) == 1942

    if oracle_parquet is not None:
        oracle_adjustments = OracleQBAdjustments(oracle_parquet)
    assert oracle_adjustments is not None, "an oracle adjustment provider is required"
    oracle_adjustments.assert_coverage(universe, where="task04c.comparison.coverage")
    return oracle_adjustments


if __name__ == "__main__":
    main()