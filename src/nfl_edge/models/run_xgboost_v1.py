"""Canonical XGBoost V1 selected-model runner.

Task 03C-6: prove a canonical selected-model runner reproduces the accepted
XGBoost V1 development output deterministically from frozen inputs and the
frozen selected specification.

The runner:
- loads the frozen development extraction, 132-feature contract, original
  config, the selected-V1 lock, and the accepted walk-forward engine;
- derives the selected candidate from the selected lock (must be the
  authorized frozen candidate ``conservative`` for V1);
- verifies authority/lock hashes, feature count/order, selected parameter
  hash, shared-settings hash, and extraction SHA before executing;
- rejects 2025+ input and market columns (delegated to the engine);
- preserves the accepted deterministic ``roof_category`` global-vocabulary
  mapping and missing/tie target handling (both live in the engine);
- uses the accepted chronological walk-forward engine unchanged;
- writes, to a caller-specified output directory:
    xgboost_v1_predictions.parquet   (selected candidate only)
    xgboost_v1_block_state.parquet
    xgboost_v1_run_manifest.json

It reads performance/report artifacts (scorecard metrics, bootstrap, etc.)
ONLY if present for provenance; it never uses them as model inputs. The runner
remains executable when those report files are absent, so long as the selected
lock and required model/data inputs are present.

No training logic is altered.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import polars as pl

# --- Authority constants (recorded at Task 03C-5, frozen) ------------------
SELECTED_ARTIFACT_SHA = "357c975539f8b14a7e7668275cf6919cf323f578478a33a5c9025a1c046531d5"
SCORECARD_JSON_SHA = "1450a5da294a6ccaaa9e45c000ce9da6fb45a40fe2a641662462b317280c3af1"
SELECTED_LOCK_SHA = "c4c048c917e53226b1876315a5fd4caddafe81353f3ebfe7d18f06ca44e59da1"

CANONICAL_CONFIG_SHA = "6aa585239ea20c7cd43da5837128101c83c5ce25645c8769e391a4dfc175a3be"
CANDIDATE_EVIDENCE_SHA = "faf89503d42527e899ff6441f022298433aed61df812d3bead695fc1dce25e01"
ORIGINAL_LOCK_MANIFEST_SHA = "e0f2d54734e1cf236ea20e573857367c4df9e12fa251b9bcf1762a19cc127af7"
FEATURE_CONTRACT_SHA = "4187bef6b76d71f4f89f3387ec4789512cccb6deacd6cd64520039c713919993"
EXTRACTION_SHA = "fb4e45d28e337617043d578cb088e366aa217984bb200efca844e13111dc10f8"
EXTRACTION_LOGICAL_HASH = "5753e15c907e6c4da2e9dce7570064158f8fb7d574afb2e3d4d62b661ab8613c"
FEATURE_ORDER_HASH = "e33c5154a7ba3e9b89b8da55bf41dd6b8358b49b09baee14f0d9106c1cf4a09c"
SHARED_SETTINGS_HASH = "b1bf9d17f0747f264f4d6dfec3323133e753106009890224d79c7527d034cf97"
SELECTED_PARAM_HASH = "a044ba76fd138bde1a52e364fd7fce5de042a2ddfdb6cdac22e592d4819ed58b"
AUTHORIZED_V1_CANDIDATE = "conservative"


def _workspace_root() -> Path:
    # src/nfl_edge/models/run_xgboost_v1.py -> worktree root
    return Path(__file__).resolve().parent.parent.parent.parent


def _canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_hex(path.read_bytes())


def _load_json(path: Path):
    return json.loads(path.read_text())


def logical_hash_predictions(df: pl.DataFrame, key_col: str) -> str:
    """Deterministic hash over the prediction frame (no paths/timestamps).

    All cell values are canonicalized to strings uniformly so floating-point
    serialization across runs is deterministic.
    """
    rows = df.sort(key_col).to_dict(as_series=False)
    payload = {}
    for col in rows:
        if col == "scheduled_start":
            continue  # timestamp/ID — noncanonical for reproducibility
        payload[col] = [
            None if v is None else str(v) for v in rows[col]
        ]
    return _sha256_hex(_canonical_json(payload))


def logical_hash_block_state(df: pl.DataFrame) -> str:
    payload = {}
    s = df.sort(["candidate_id", "block_id"])
    for c in s.columns:
        payload[c] = [None if v is None else str(v) for v in s.select(c).to_series().to_list()]
    return _sha256_hex(_canonical_json(payload))


class XgboostV1CanonicalRunner:
    """Canonical selected-model runner: verifies authority, runs engine, writes artifacts."""

    def __init__(self, workspace_root: Path | None = None) -> None:
        self.root = workspace_root or _workspace_root()
        self.dev_dir = self.root / "data" / "modeling" / "development_v1"
        self.extraction_path = (
            self.root / "data" / "derived" / "features_v1" / "xgboost_development_2018_2024.parquet"
        )
        self.contract_path = self.dev_dir / "xgboost_feature_contract_v1.json"
        self.config_path = self.root / "config" / "xgboost_v1.yaml"
        self.selected_candidate_path = self.dev_dir / "xgboost_selected_candidate_v1.json"
        self.selected_lock_path = (
            self.dev_dir / "xgboost_selected_v1_lock" / "SELECTED_V1_LOCK_MANIFEST.json"
        )
        self.scorecard_json_path = self.dev_dir / "xgboost_v1_scorecard.json"
        sys.path.insert(0, str(self.root / "src"))

    # -- Verification -----------------------------------------------------
    def verify_authority(self, require_scorecard: bool = False) -> dict:
        """Verify the selected-model authority.

        The selected lock and selected-candidate artifact are MANDATORY inputs.
        The scorecard is a reporting artifact — it is checked for provenance
        only when present, so the runner stays executable without report files.
        """
        checks = {
            "selected_artifact": _sha256_file(self.selected_candidate_path),
            "selected_lock": _sha256_file(self.selected_lock_path),
        }
        expected = {
            "selected_artifact": SELECTED_ARTIFACT_SHA,
            "selected_lock": SELECTED_LOCK_SHA,
        }
        if self.scorecard_json_path.exists():
            checks["scorecard_json"] = _sha256_file(self.scorecard_json_path)
            expected["scorecard_json"] = SCORECARD_JSON_SHA
        elif require_scorecard:
            raise ValueError("Scorecard report artifact required but absent")
        mismatches = {k: (v, expected[k]) for k, v in checks.items() if v != expected[k]}
        if mismatches:
            raise ValueError(f"Selected-model authority mismatch: {mismatches}")
        return checks

    def verify_original_lock(self) -> dict:
        checks = {
            "canonical_config": _sha256_file(self.config_path),
            "candidate_evidence": _sha256_file(self.dev_dir / "xgboost_lock_snapshot_v1"
                                                / "xgboost_candidate_differentiation_v1.locked.json"),
            "original_lock_manifest": _sha256_file(self.dev_dir / "xgboost_lock_snapshot_v1"
                                                       / "LOCK_MANIFEST.json"),
            "feature_contract": _sha256_file(self.contract_path),
            "extraction": _sha256_file(self.extraction_path),
        }
        expected = {
            "canonical_config": CANONICAL_CONFIG_SHA,
            "candidate_evidence": CANDIDATE_EVIDENCE_SHA,
            "original_lock_manifest": ORIGINAL_LOCK_MANIFEST_SHA,
            "feature_contract": FEATURE_CONTRACT_SHA,
            "extraction": EXTRACTION_SHA,
        }
        mismatches = {k: (v, expected[k]) for k, v in checks.items() if v != expected[k]}
        if mismatches:
            raise ValueError(f"Original lock mismatch: {mismatches}")
        return checks

    def _derive_selected_candidate(self) -> str:
        lock = _load_json(self.selected_lock_path)
        sel = lock.get("selected_candidate")
        if sel != AUTHORIZED_V1_CANDIDATE:
            raise ValueError(
                f"Selected candidate '{sel}' is not the authorized frozen V1 "
                f"candidate '{AUTHORIZED_V1_CANDIDATE}'."
            )
        return sel

    def _verify_contract_and_hash(self, contract: dict, feature_cols: list[str]) -> None:
        if contract.get("model_feature_count") != 132:
            raise ValueError(f"Feature count mismatch: {contract.get('model_feature_count')}")
        if len(feature_cols) != 132:
            raise ValueError(f"Feature list length mismatch: {len(feature_cols)}")
        # feature-order hash
        from nfl_edge.backtest.xgboost_walk_forward import feature_order_hash
        foh = feature_order_hash(feature_cols)
        if foh != FEATURE_ORDER_HASH:
            raise ValueError(f"Feature-order hash mismatch: {foh}")
        # shared-settings hash
        from nfl_edge.backtest.xgboost_walk_forward import shared_settings_hash
        ssh = shared_settings_hash()
        if ssh != SHARED_SETTINGS_HASH:
            raise ValueError(f"Shared-settings hash mismatch: {ssh}")
        # selected parameter hash: validate against the engine's frozen conservative params
        from nfl_edge.backtest.xgboost_walk_forward import CANDIDATES, parameter_hash
        cand = CANDIDATES[AUTHORIZED_V1_CANDIDATE]
        param_payload = {
            "colsample_bytree": cand.colsample_bytree,
            "gamma": cand.gamma,
            "learning_rate": cand.learning_rate,
            "max_delta_step": cand.max_delta_step,
            "max_depth": cand.max_depth,
            "min_child_weight": cand.min_child_weight,
            "reg_alpha": cand.reg_alpha,
            "reg_lambda": cand.reg_lambda,
            "subsample": cand.subsample,
        }
        if parameter_hash(param_payload) != SELECTED_PARAM_HASH:
            raise ValueError("Selected parameter hash does not match frozen conservative params")

    def run(self, output_dir: Path, silent: bool = False) -> dict:
        """Execute the canonical walk-forward for the selected candidate."""
        self.verify_authority()
        self.verify_original_lock()

        selected = self._derive_selected_candidate()

        contract = _load_json(self.contract_path)
        feature_cols = list(contract["deterministic_ordering"]["feature_order"])
        self._verify_contract_and_hash(contract, feature_cols)

        df = pl.read_parquet(self.extraction_path)
        if df.height != 1942:
            raise ValueError(f"Extraction row count mismatch: {df.height}")
        if 2025 in df["season"].unique().to_list():
            raise ValueError("2025+ rows present in extraction input")

        from nfl_edge.backtest.xgboost_walk_forward import (
            CANDIDATES,
            PredictionResult,
            WalkForwardEngine,
            WarmUpResult,
            feature_order_hash,
            shared_settings_hash,
        )

        engine = WalkForwardEngine(df, feature_cols, target_col="target_home_win")
        block_keys = engine.block_keys
        cand = CANDIDATES[selected]

        all_prediction_rows = []
        all_block_states = []

        for block_key in block_keys:
            result = engine.predict_block(selected, block_key)
            if isinstance(result, PredictionResult):
                for gid, prob in zip(result.game_ids, result.probabilities):
                    row_data = df.filter(pl.col("game_id") == gid).row(0, named=True)
                    all_prediction_rows.append({
                        "candidate_id": selected,
                        "game_id": gid,
                        "season": block_key.season,
                        "season_type": block_key.season_type,
                        "season_type_priority": block_key.season_type_priority,
                        "week": block_key.week,
                        "block_id": block_key.block_id,
                        "scheduled_start": row_data.get("scheduled_start_utc"),
                        "target": row_data.get("target_home_win"),
                        "binary_score_eligible": row_data.get("target_home_win") is not None
                        and bool(row_data.get("target_home_win")) in (True, False),
                        "prediction_probability": float(prob),
                        "warmup": False,
                        "warmup_reason": None,
                        "fit_rows": result.fit_rows,
                        "fit_blocks": result.fit_blocks,
                        "validation_rows": result.validation_rows,
                        "validation_blocks": result.validation_blocks,
                        "best_iteration": result.best_iteration,
                        "final_refit_rounds": result.final_refit_rounds,
                        "config_sha": CANONICAL_CONFIG_SHA,
                        "candidate_parameter_hash": cand.parameter_hash,
                        "shared_settings_hash": shared_settings_hash(),
                        "feature_order_hash": feature_order_hash(feature_cols),
                        "source_extraction_sha": EXTRACTION_SHA,
                    })
                all_block_states.append(result.block_state.to_dict())
            elif isinstance(result, WarmUpResult):
                block_df = df.filter(
                    (pl.col("season") == block_key.season)
                    & (pl.col("season_type") == block_key.season_type)
                    & (pl.col("week") == block_key.week)
                )
                for row_data in block_df.iter_rows(named=True):
                    all_prediction_rows.append({
                        "candidate_id": selected,
                        "game_id": row_data["game_id"],
                        "season": block_key.season,
                        "season_type": block_key.season_type,
                        "season_type_priority": block_key.season_type_priority,
                        "week": block_key.week,
                        "block_id": block_key.block_id,
                        "scheduled_start": row_data.get("scheduled_start_utc"),
                        "target": row_data.get("target_home_win"),
                        "binary_score_eligible": False,
                        "prediction_probability": None,
                        "warmup": True,
                        "warmup_reason": result.warmup_reason,
                        "fit_rows": result.fit_rows,
                        "fit_blocks": result.fit_blocks,
                        "validation_rows": result.validation_rows,
                        "validation_blocks": result.validation_blocks,
                        "best_iteration": None,
                        "final_refit_rounds": None,
                        "config_sha": CANONICAL_CONFIG_SHA,
                        "candidate_parameter_hash": cand.parameter_hash,
                        "shared_settings_hash": shared_settings_hash(),
                        "feature_order_hash": feature_order_hash(feature_cols),
                        "source_extraction_sha": EXTRACTION_SHA,
                    })
                all_block_states.append(result.to_block_state(feature_cols).to_dict())

        pred_df = pl.DataFrame(all_prediction_rows)
        bs_df = pl.DataFrame(all_block_states)

        output_dir.mkdir(parents=True, exist_ok=True)
        pred_out = output_dir / "xgboost_v1_predictions.parquet"
        bs_out = output_dir / "xgboost_v1_block_state.parquet"
        manifest_out = output_dir / "xgboost_v1_run_manifest.json"

        pred_df.write_parquet(pred_out, compression="zstd")
        bs_df.write_parquet(bs_out, compression="zstd")

        pred_hash = logical_hash_predictions(pred_df, "game_id")
        bs_hash = logical_hash_block_state(bs_df)

        # Verification summary (sanity only, not training inputs)
        scored = [r for r in all_prediction_rows
                  if r["binary_score_eligible"] and r["prediction_probability"] is not None]
        import numpy as np
        probs = np.array([r["prediction_probability"] for r in scored])
        targs = np.array([int(r["target"]) for r in scored])
        eps = 1e-15
        p_clip = np.clip(probs, eps, 1 - eps)
        brier = float(np.mean((probs - targs) ** 2))
        logloss = float(-np.mean(targs * np.log(p_clip) + (1 - targs) * np.log(1 - p_clip)))
        acc = float(np.mean((probs >= 0.5).astype(int) == targs))
        # ROC-AUC (average-rank tie handling)
        auc = None
        n_pos = int(targs.sum())
        n_neg = len(targs) - n_pos
        if n_pos > 0 and n_neg > 0:
            order = np.argsort(probs, kind="stable")
            sp = probs[order]
            ranks = np.empty(len(probs))
            i = 0
            n = len(sp)
            while i < n:
                j = i
                while j + 1 < n and sp[j + 1] == sp[i]:
                    j += 1
                ranks[i:j + 1] = (i + j) / 2.0 + 1.0
                i = j + 1
            rank_by_orig = np.empty(n)
            rank_by_orig[order] = ranks
            auc = float((np.sum(rank_by_orig[targs == 1]) - n_pos * (n_pos + 1) / 2.0)
                        / (n_pos * n_neg))

        manifest = {
            "model": "XGBOOST_V1",
            "selected_candidate": selected,
            "selected_parameter_hash": SELECTED_PARAM_HASH,
            "engine_candidate_parameter_hash": cand.parameter_hash,
            "original_config_sha256": CANONICAL_CONFIG_SHA,
            "selected_lock_sha256": SELECTED_LOCK_SHA,
            "feature_contract_sha256": FEATURE_CONTRACT_SHA,
            "feature_order_hash": FEATURE_ORDER_HASH,
            "extraction_sha256": EXTRACTION_SHA,
            "extraction_logical_hash": EXTRACTION_LOGICAL_HASH,
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "xgboost_version": __import__("xgboost").__version__,
            "seed": 42,
            "nthread": 1,
            "total_rows": pred_df.height,
            "scored_rows": len(scored),
            "warmup_rows": int(pred_df.filter(pl.col("warmup")).height),
            "prediction_logical_hash": pred_hash,
            "block_state_logical_hash": bs_hash,
            "verification_metrics": {
                "brier": round(brier, 6),
                "logloss": round(logloss, 6),
                "accuracy": round(acc, 6),
                "roc_auc": round(auc, 6) if auc is not None else None,
            },
            "run_status": "COMPLETE",
            "2025_HOLDOUT_ACCESSED": False,
            "MARKET_DATA_USED": False,
            "POST_RESULT_RETUNING_OCCURRED": False,
            "production_deployed": False,
            "canonical_runner_purpose": (
                "Deterministic canonical reproduction of accepted XGBoost V1 "
                "conservative development output from frozen inputs."
            ),
        }
        manifest_out.write_text(json.dumps(manifest, indent=2) + "\n")

        return {
            "selected": selected,
            "prediction_artifact": str(pred_out),
            "block_state_artifact": str(bs_out),
            "manifest": str(manifest_out),
            "prediction_logical_hash": pred_hash,
            "block_state_logical_hash": bs_hash,
            "total_rows": pred_df.height,
            "scored_rows": len(scored),
            "warmup_rows": int(pred_df.filter(pl.col("warmup")).height),
            "best_iteration_seq": [s["best_iteration"] for s in all_block_states
                                   if s.get("best_iteration") is not None],
            "final_refit_seq": [s["final_refit_rounds"] for s in all_block_states
                                if s.get("final_refit_rounds") is not None],
            "run_manifest": manifest,
        }


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Canonical XGBoost V1 runner")
    parser.add_argument("--output-dir", required=True, help="Output directory for canonical artifacts")
    parser.add_argument("--workspace-root", default=None, help="Worktree root override")
    args = parser.parse_args(argv)

    runner = XgboostV1CanonicalRunner(
        workspace_root=Path(args.workspace_root) if args.workspace_root else None
    )
    result = runner.run(Path(args.output_dir), silent=True)
    print(json.dumps(
        {k: v for k, v in result.items() if k != "run_manifest"},
        indent=2, default=str,
    ))


if __name__ == "__main__":
    main()
