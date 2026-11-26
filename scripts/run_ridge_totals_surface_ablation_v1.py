#!/usr/bin/env python3
"""Replay Task05D and run the frozen, offline 2018–2024 surface ablation."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
from threadpoolctl import threadpool_limits

from nfl_edge.backtest.totals_bake_off import (
    MINIMUM_ELIGIBLE_PRIOR_ROWS,
    _validated_block_frames,
    build_candidate_model,
    scoring_blocks_from_prepared,
)
from nfl_edge.backtest.totals_walk_forward import IDENTITY_COLUMNS, run_totals_walk_forward

ROOT = Path(__file__).resolve().parents[1]
TASK05D = ROOT / "reports/task05d"
DERIVED = ROOT / "data/derived"
REPORT = ROOT / "reports/ridge_totals_surface_ablation_v1"
ARMS = ("A", "B", "C")
CONTRASTS = (("B", "A"), ("C", "A"), ("C", "B"))
METRICS = ("mae", "rmse", "bias")
MARGINS = (0.10, 0.15, 0.25)
GROUPS = ("venue", "home_team")
STRENGTH = ("roll8_offensive_total_epa", "roll8_defensive_epa_allowed")
SURFACE_MAP = {
    "grass": "grass",
    "fieldturf": "artificial",
    "matrixturf": "artificial",
    "astroturf": "artificial",
    "sportturf": "artificial",
    "a_turf": "artificial",
}
REPLICATES = 5000
SEED = 20261126


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_parquet(path, sha, **kwargs):
    if digest(path) != sha:
        raise ValueError(f"Input checksum mismatch: {path}")
    return pl.read_parquet(path, **kwargs) if not kwargs else (
        pl.scan_parquet(path)
        .filter(pl.col("season").is_between(2018, 2024))
        .select(kwargs["columns"])
        .collect()
    )


def load_prepared():
    manifest = json.loads((TASK05D / "task05d_ridge_run_manifest.json").read_text())
    table = verified_parquet(
        DERIVED / "totals_v1_modeling_table_2018_2024.parquet",
        manifest["inputs"]["modeling_table"]["byte_sha256"],
    )
    availability = verified_parquet(
        DERIVED / "features_v1/weekly_availability_2018_2024.parquet",
        manifest["inputs"]["weekly_availability"]["byte_sha256"],
    )
    if sorted(table["season"].unique()) != list(range(2018, 2025)):
        raise ValueError("Unexpected development seasons")
    run = run_totals_walk_forward(table, availability)
    blocks = scoring_blocks_from_prepared(run)
    if (
        table.height != 1942
        or len(run.blocks) != 151
        or sum(block.prediction_rows.height for block in blocks) != 1864
        or [str(block.target_block.block_id) for block in blocks] != manifest["scoring_universe"]["block_ids"]
    ):
        raise ValueError("Task05D evaluation universe drift")
    return table, blocks, manifest


def development_context():
    schedule = json.loads((ROOT / "data/manifests/schedules_frozen-baseline-v1.json").read_text())
    weather = verified_parquet(
        ROOT / schedule["file_name"], schedule["sha256"], columns=["game_id", "temp", "wind"],
    )
    games = (
        pl.scan_parquet(ROOT / "data/frozen/games/games_2018_2025.parquet")
        .filter(pl.col("season").is_between(2018, 2024))
        .select("game_id", "venue_id", "venue_name")
        .collect()
        .with_columns(pl.coalesce("venue_id", "venue_name").alias("venue"))
    )
    teams = (
        pl.scan_parquet(DERIVED / "features_v1/team_pregame_features_2018_2025.parquet")
        .filter(pl.col("season").is_between(2018, 2024))
        .select("game_id", "side", *STRENGTH)
        .collect()
    )
    context = games.join(weather, on="game_id", how="left", validate="1:1")
    for side in ("home", "away"):
        side_rows = teams.filter(pl.col("side") == side).drop("side")
        context = context.join(
            side_rows.rename({field: f"{side}_{field}" for field in STRENGTH}),
            on="game_id", how="left", validate="1:1",
        )
    return context.to_pandas().set_index("game_id")


def binary_label(surface):
    return SURFACE_MAP.get(surface.strip().lower(), "unknown") if isinstance(surface, str) else "unknown"


def prepare_arm(frame, arm):
    if arm == "A":
        return frame
    if arm == "B":
        return frame.assign(surface_category=frame["surface_category"].map(binary_label))
    return frame.drop(columns=["surface_category", "surface_missing"])


def new_model(arm):
    model = build_candidate_model("R4")
    if arm == "C":
        features = model["features"]
        features.transformers = [
            (name, transformer, [col for col in columns if col not in {"surface_category", "surface_missing"}])
            for name, transformer, columns in features.transformers
        ]
    if model["model"].alpha != 100:
        raise ValueError("Accepted R4 alpha drift")
    return model


def fit_predict(training, scoring, target, arm):
    model = new_model(arm).fit(training, target)
    prediction = model.predict(scoring)
    if prediction.shape != (len(scoring),) or not np.isfinite(prediction).all():
        raise ValueError("Unexpected prediction shape or nonfinite prediction")
    names = model["features"].get_feature_names_out()
    coefficients = {}
    for name, value in zip(names, model["model"].coef_, strict=True):
        if name.startswith("categorical__surface_category_"):
            coefficients[name.removeprefix("categorical__surface_category_")] = float(value)
        elif name == "numeric__surface_missing":
            coefficients["<surface_missing_indicator>"] = float(value)
    return prediction, coefficients


def fold(group):
    if pd.isna(group) or not str(group).strip():
        return -1
    return int.from_bytes(hashlib.sha256(str(group).encode()).digest()[:8], "big") % 5


def fit_blocks(prepared, context, arms, grouping=None):
    predictions = []
    coefficients = []
    for block, training, scoring, target, observed in prepared:
        rows = block.prediction_rows.select(list(IDENTITY_COLUMNS)).to_pandas()
        rows["observed"] = observed
        rows["surface_category"] = scoring["surface_category"]
        rows["binary_surface"] = scoring["surface_category"].map(binary_label)
        rows["roof_category"] = scoring["roof_category"]
        rows = rows.join(context, on="game_id", validate="1:1")
        if grouping is None:
            train_folds = np.zeros(len(training), dtype=int)
            test_folds = np.zeros(len(scoring), dtype=int)
            groups = (0,)
        else:
            history_ids = block.training_rows["game_id"].to_list()
            train_groups = (
                context["venue"].reindex(history_ids)
                if grouping == "venue" else block.training_rows["home_team"].to_list()
            )
            train_folds = np.array([fold(group) for group in train_groups])
            test_folds = rows[grouping].map(fold).to_numpy()
            groups = range(5)

        target = np.asarray(target)
        for group in groups:
            train = np.ones(len(training), dtype=bool) if grouping is None else (
                (train_folds >= 0) & (train_folds != group)
            )
            test = test_folds == group
            if train.sum() < MINIMUM_ELIGIBLE_PRIOR_ROWS or not test.any():
                continue
            scored = rows.loc[test].copy()
            scored["training_games"] = int(train.sum())
            scored["fold"] = group
            for arm in arms:
                scored[arm], surface_coefs = fit_predict(
                    prepare_arm(training.loc[train], arm), prepare_arm(scoring.loc[test], arm), target[train], arm,
                )
                coefficients.extend(
                    {
                        "block_id": scored["block_id"].iat[0], "season": int(scored["season"].iat[0]),
                        "fold": group, "training_games": int(train.sum()), "arm": arm,
                        "category": category, "coefficient": value,
                    }
                    for category, value in surface_coefs.items()
                )
            predictions.append(scored)
    return pd.concat(predictions, ignore_index=True), pd.DataFrame(coefficients)


def assert_baseline(predictions):
    frozen = (
        pl.scan_parquet(TASK05D / "task05d_ridge_predictions.parquet")
        .filter((pl.col("season").is_between(2018, 2024)) & (pl.col("candidate_id") == "R4"))
        .collect()
        .to_pandas()
    )
    joined = predictions.merge(frozen, on=list(IDENTITY_COLUMNS), how="outer", validate="1:1", indicator=True)
    if not joined["_merge"].eq("both").all() or not joined["observed"].eq(joined["observed_total"]).all():
        raise ValueError("Baseline ledger identity or target mismatch")
    maximum = float((joined["A"] - joined["predicted_total"]).abs().max())
    if maximum > 1e-7:
        raise ValueError(f"Baseline replay deviates from the ledger by {maximum:.12g} points")
    return maximum


def loss_sums(rows):
    errors = rows[list(ARMS)].to_numpy() - rows["observed"].to_numpy()[:, None]
    values = np.concatenate([np.abs(errors), errors ** 2, errors], axis=1)
    return pd.DataFrame(values, index=rows.index, columns=range(9)).assign(n=1)


def metrics_from_sums(sums):
    means = sums[..., :9].reshape(*sums.shape[:-1], 3, 3) / sums[..., -1, None, None]
    means[..., 1, :] = np.sqrt(means[..., 1, :])
    return means


def bootstrap_weights(timeline):
    rng = np.random.default_rng(SEED)
    seasons = timeline["season"].to_numpy()
    unique_seasons = np.unique(seasons)
    n_blocks = len(timeline)
    weeks = np.zeros((REPLICATES, n_blocks), dtype=np.int16)
    for season in unique_seasons:
        indices = np.flatnonzero(seasons == season)
        n = len(indices)
        starts = rng.integers(n, size=(REPLICATES, (n + 3) // 4, 1))
        sample = (starts + np.arange(4)).reshape(REPLICATES, -1)[:, :n] % n
        np.add.at(weeks, (np.arange(REPLICATES)[:, None], indices[sample]), 1)
    draws = rng.choice(unique_seasons, size=(REPLICATES, len(unique_seasons)), replace=True)
    season_counts = (draws[:, :, None] == unique_seasons).sum(axis=1)
    return weeks, season_counts[:, np.searchsorted(unique_seasons, seasons)]


def quantiles(values, probabilities):
    return np.quantile(values, probabilities).tolist()


def interval(values):
    return quantiles(values[np.isfinite(values)], [0.025, 0.975])


def named_metrics(scores):
    return {arm: dict(zip(METRICS, scores[:, i].tolist(), strict=True)) for i, arm in enumerate(ARMS)}


def summarize(rows, timeline, weights, infer=True):
    counts = {"games": len(rows), "seasons": rows["season"].nunique(), "weeks": rows["block_id"].nunique()}
    if not infer and counts["games"] < 150:
        return counts
    losses = loss_sums(rows)
    scores = metrics_from_sums(losses.sum().to_numpy())
    result = {**counts, "metrics": named_metrics(scores), "paired": {}}
    bootstrap = {}
    if infer:
        by_week = losses.groupby(rows["block_id"]).sum().reindex(timeline.index, fill_value=0).to_numpy()
        for name, weight in zip(("weeks_ci", "seasons_ci"), weights, strict=True):
            draws = weight @ by_week
            bootstrap[name] = metrics_from_sums(draws[draws[:, -1] > 0])
    for left, right in CONTRASTS:
        li, ri = ARMS.index(left), ARMS.index(right)
        shift = (rows[left] - rows[right]).to_numpy()
        delta_abs = (losses[li] - losses[ri]).to_numpy()
        delta_sq = (losses[3 + li] - losses[3 + ri]).to_numpy()
        stats = {
            "delta": dict(zip(METRICS, (scores[:, li] - scores[:, ri]).tolist(), strict=True)),
            "shift_abs_p95": float(np.quantile(np.abs(shift), 0.95)),
            "quantiles_0_5_25_50_75_95_100_pct": {
                key: quantiles(values, [0, .05, .25, .5, .75, .95, 1])
                for key, values in {"prediction_and_signed_error": shift, "absolute_error": delta_abs,
                                    "squared_error": delta_sq}.items()
            },
        }
        for name, draws in bootstrap.items():
            stats[name] = {
                metric: interval(draws[:, i, li] - draws[:, i, ri]) for i, metric in enumerate(METRICS)
            }
        if infer:
            stats["decision_ci"] = {
                metric: [
                    min(stats[name][metric][0] for name in bootstrap),
                    max(stats[name][metric][1] for name in bootstrap),
                ] for metric in METRICS
            }
        result["paired"][f"{left}-{right}"] = stats
    return result


def subgroups(rows, column, timeline, weights):
    results = {}
    for key, subgroup in rows.groupby(column, dropna=False, sort=True):
        counts = {"games": len(subgroup), "seasons": subgroup["season"].nunique(),
                  "weeks": subgroup["block_id"].nunique()}
        supported = counts["games"] >= 75 and counts["seasons"] >= 3 and counts["weeks"] >= 8
        results[repr(key)] = summarize(subgroup, timeline, weights) if supported else counts
    return results


def context_diagnostics(rows):
    results = {}
    for column in (*GROUPS, "roof_category", "season"):
        cross = pd.crosstab(rows[column], rows["surface_category"], dropna=True)
        results[column] = {
            "known": int(cross.to_numpy().sum()),
            "groups": len(cross),
            "weighted_modal_subtype_share": float(cross.max(axis=1).sum() / cross.to_numpy().sum()),
            "single_subtype_groups": int(cross.gt(0).sum(axis=1).eq(1).sum()),
            "counts_by_group": cross.to_dict(orient="index"),
        }
    results["continuous_by_subtype"] = {}
    numeric = ["temp", "wind", *(f"{side}_{field}" for field in STRENGTH for side in ("home", "away"))]
    for category, group in rows.groupby("surface_category", dropna=False):
        results["continuous_by_subtype"][repr(category)] = {
            col: {"n": int(group[col].count()), "mean": float(group[col].mean()) if group[col].count() else None}
            for col in numeric
        }
    results["leave_one_group_out_mae_deltas"] = {}
    for column in (*GROUPS, "season"):
        omitted = {}
        for key, group in rows.groupby(column):
            other = rows.drop(index=group.index)
            mae = other[list(ARMS)].sub(other["observed"], axis=0).abs().mean()
            omitted[str(key)] = {f"{left}-{right}": float(mae[left] - mae[right]) for left, right in CONTRASTS}
        results["leave_one_group_out_mae_deltas"][column] = omitted
    return results


def coefficient_summary(coefficients):
    return [
        {
            "arm": arm, "category": category, "fits": len(group),
            "min": float(group["coefficient"].min()), "max": float(group["coefficient"].max()),
            "last_fit": float(group["coefficient"].iat[-1]),
        }
        for (arm, category), group in coefficients.groupby(["arm", "category"], sort=True)
    ]


def classify(overall, seasons, groups, diagnostics):
    if overall["games"] < 1200 or overall["seasons"] < 6 or overall["weeks"] < 100:
        return "INCONCLUSIVE", {}

    def qualifies(contrast):
        stats = overall["paired"][contrast]
        limits = stats["decision_ci"]
        equivalent = {
            metric: low > -margin and high < margin
            for metric, margin in zip(METRICS, MARGINS, strict=True)
            for low, high in [limits[metric]]
        }
        favorable = {
            metric: equivalent[metric] or limits[metric][1] < -margin
            for metric, margin in zip(METRICS[:2], MARGINS[:2], strict=True)
        }
        bad_seasons = [
            key for key, season in seasons.items()
            if season.get("paired", {}).get(contrast, {}).get("delta", {}).get("mae", 0) > .35
        ]
        eligible = {**groups, **{
            key: stats for key, stats in diagnostics.items()
            if stats["games"] >= 500 and stats["seasons"] >= 4 and stats["groups"] >= 15
        }}
        bad_groups = []
        for key, group in eligible.items():
            paired = group.get("paired", {}).get(contrast)
            if paired and paired["delta"]["mae"] > .35 and paired["weeks_ci"]["mae"][0] > 0:
                bad_groups.append(key)
        passed = (all(favorable.values()) and equivalent["bias"] and stats["shift_abs_p95"] <= .50
                  and len(bad_seasons) < 2 and not bad_groups)
        return {"qualifies": passed, "equivalent": equivalent, "error_gate": favorable,
                "shift_gate": stats["shift_abs_p95"] <= .50, "bad_seasons": bad_seasons,
                "bad_groups": bad_groups}

    decisions = {key: qualifies(key) for key in overall["paired"]}
    binary = decisions["B-A"]["qualifies"]
    no_surface = decisions["C-A"]["qualifies"] and (not binary or decisions["C-B"]["qualifies"])
    if no_surface:
        return "SURFACE_FEATURE_NOT_SUPPORTED", decisions
    if binary:
        return "BINARY_SURFACE_PREFERRED", decisions
    venue = diagnostics["venue"]
    if venue["games"] < 500 or venue["seasons"] < 4 or venue["groups"] < 15:
        return "INCONCLUSIVE", decisions
    supported = all(
        overall["paired"][contrast]["decision_ci"]["mae"][0] > .10
        and overall["paired"][contrast]["decision_ci"]["rmse"][1] >= -.15
        and sum(s.get("paired", {}).get(contrast, {}).get("delta", {}).get("mae", 0) > 0 for s in seasons.values()) >= 5
        for contrast in ("B-A", "C-A")
    ) and venue["paired"]["B-A"]["weeks_ci"]["mae"][0] > 0
    return ("SUBTYPE_VALUE_SUPPORTED" if supported else "INCONCLUSIVE"), decisions


def write_paired_csv(rows, path):
    ledger = rows.copy()
    for arm in ARMS:
        ledger[f"signed_error_{arm}"] = ledger[arm] - ledger["observed"]
    for left, right in CONTRASTS:
        a, b = ledger[f"signed_error_{left}"], ledger[f"signed_error_{right}"]
        ledger[f"prediction_delta_{left}_{right}"] = a - b
        ledger[f"absolute_error_delta_{left}_{right}"] = a.abs() - b.abs()
        ledger[f"squared_error_delta_{left}_{right}"] = a ** 2 - b ** 2
    ledger.to_csv(path, index=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory for research outputs")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("--output must be a new directory")
    table, blocks, manifest = load_prepared()
    context = development_context()
    prepared = [(block, *_validated_block_frames(block, "ridge")[:4]) for block in blocks]
    with threadpool_limits(limits=1):
        baseline, baseline_coefs = fit_blocks(prepared, context, ("A",))
        replay = assert_baseline(baseline)
        print(f"Baseline verified on {len(baseline)} games, max deviation {replay:.3g}", flush=True)
        challengers, challenger_coefs = fit_blocks(prepared, context, ("B", "C"))
        rows = baseline.merge(challengers[["game_id", "B", "C"]], on="game_id", validate="1:1")
        if len(rows) != len(baseline):
            raise ValueError("Primary arms do not share identical scoring games")
        coefficients = pd.concat([baseline_coefs, challenger_coefs], ignore_index=True)
        grouped = {key: fit_blocks(prepared, context, ARMS, key) for key in GROUPS}
    timeline = rows[["season", "block_id"]].drop_duplicates().set_index("block_id")
    weights = bootstrap_weights(timeline)
    overall = summarize(rows, timeline, weights)
    seasons = {str(key): summarize(group, timeline, weights, infer=False) for key, group in rows.groupby("season")}
    groups = {
        key: subgroups(rows, key, timeline, weights)
        for key in ("surface_category", "binary_surface")
    }
    diagnostics = {
        key: {**summarize(frame, timeline, weights), "groups": frame[key].nunique(),
              "omitted_games": len(rows) - len(frame), "coefficients": coefficient_summary(coefs)}
        for key, (frame, coefs) in grouped.items()
    }
    outcome, gates = classify(
        overall, seasons, {f"{key}:{label}": group for key, values in groups.items()
                           for label, group in values.items()}, diagnostics,
    )
    args.output.mkdir(parents=True, exist_ok=False)
    write_paired_csv(rows, args.output / "paired_games.csv")
    coefficients.to_csv(args.output / "weekly_coefficients.csv", index=False)
    for key, (frame, coefs) in grouped.items():
        write_paired_csv(frame, args.output / f"{key}_held_out_games.csv")
        coefs.to_csv(args.output / f"{key}_held_out_coefficients.csv", index=False)
    result = {
        "classification": outcome, "gates": gates, "contract_sha256": digest(REPORT / "contract.md"),
        "runtime": {"python": platform.python_version(), **{
            name: version(name) for name in ("numpy", "polars", "pyarrow", "pandas", "scipy", "scikit-learn")
        }},
        "baseline_replay_max_abs_difference": replay, "accepted": manifest["final_selection"],
        "warmup_games": table.height - len(rows),
        "block_training_counts": rows.groupby("block_id", sort=False)["training_games"].first().to_dict(),
        "input_category_counts": {repr(key): value for key, value in
                                  table["surface_category"].to_pandas().value_counts(dropna=False).items()},
        "overall": overall, "seasons": seasons, "subgroups": groups, "grouped": diagnostics,
        "confounding": context_diagnostics(rows), "coefficient_summary": coefficient_summary(coefficients),
    }
    (args.output / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(outcome)


if __name__ == "__main__":
    main()
