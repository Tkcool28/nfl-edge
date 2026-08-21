#!/usr/bin/env python3
"""Task05F redesign v2 candidate harness (prereg /tmp/task05f-redesign-v2-prereg.json).

Full-board 2020-2024 chronological expanding OOS, prior season-week blocks only.
No 2018-2019 evaluator rows; 2025 is sealed and hard-fails if ever requested.

Families evaluated:
  moneyline: global_shrinkage (incumbent, committed evaluator path),
             partial_shrinkage_floor (v1 prior benchmark, same tier gating as v2),
             reliability_aware_shrinkage_v2 (NEW preregistered candidate)
  spread:    calibrated_normal (incumbent, committed evaluator path),
             empirical_residual_cdf (v1 prior global ECDF benchmark),
             conditional_band_ecdf (NEW banded conditional residual CDF),
             standardized_conditional_ecdf (NEW standardized conditional CDF)
  total:     calibrated_normal (incumbent, committed evaluator path),
             canonical_over_ecdf (NEW canonical-over empirical CDF)

Push handling: spread/total training rows whose wager pushed keep their residual
in the ECDF pools but carry NO y (never encoded 0/1); binary fits and
Brier/logloss use y-present rows only; realized ROI treats pushes as 0-unit
return. Exact push counts are reported.

Determinism: fixed iteration orders, fixed bootstrap seed (committed module
default), no clocks, no randomness. Run twice and compare byte hashes.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path("/root/workspaces/nfl-edge-task05f-validation").resolve()
OUTD = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/task05f-redesign-v2")
sys.path.insert(0, str(ROOT / "src"))

from nfl_edge.market_data.matching import _NAME_TO_ABBR  # noqa: E402
from nfl_edge.value.contracts import GameState, NormalizedOffer  # noqa: E402
from nfl_edge.value.evaluators import evaluate_offer  # noqa: E402
from nfl_edge.value.fitting import (  # noqa: E402
    _lr, _ml_state, _ml_support_features, _point_state, fit_global_lambda)
from nfl_edge.value.market_math import (  # noqa: E402
    american_to_decimal, break_even_probability, clip_probability,
    normal_cdf, proportional_no_vig, shop_moneyline, shop_spread, shop_total)
from nfl_edge.value.reliability import (  # noqa: E402
    ReliabilityEvidence, overall_support_distance, staking_probability,
    tier as rel_tier)
from nfl_edge.value.redesign import (  # noqa: E402
    ML_LAMBDA_FLOOR, _mad_sigma, canonical_over_probability,
    conditional_band_probability, ml_v2_actionable_probability,
    smooth_ecdf_from_sorted, spread_band, standardized_conditional_probability)
from nfl_edge.value.uncertainty import (  # noqa: E402
    block_bootstrap_calibration_radius, stability_from_radius)

DEV = [2020, 2021, 2022, 2023, 2024]
SEALED = {2025}
VERSION = "market_evaluator_v1"
BOOKS = ("draftkings", "fanduel")
ML_FAMS = ("global_shrinkage", "partial_shrinkage_floor", "reliability_aware_shrinkage_v2")
SP_FAMS = ("normal_cdf", "calibrated_normal", "empirical_residual_cdf",
           "conditional_band_ecdf", "standardized_conditional_ecdf")
TO_FAMS = ("calibrated_normal", "canonical_over_ecdf")


def cfg_sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_scan(path, cols):
    return pl.scan_parquet(path).select(cols).filter(pl.col("season").is_in(DEV))


def _grade_ml(side, hs, as_):
    return int((hs > as_) if side == "home" else (as_ > hs))


def _grade_sp(side, line, hs, as_):
    m = (hs - as_) if side == "home" else (as_ - hs)
    v = m + line
    return None if abs(v) < 1e-9 else int(v > 0)


def _grade_total(side, line, hs, as_):
    v = (hs + as_ - line) if side == "over" else (line - hs - as_)
    return None if abs(v) < 1e-9 else int(v > 0)


def _block_key(season, week):
    return f"{int(season):04d}-{str(week).zfill(2)}"


def assert_not_sealed_seasons(seasons):
    bad = SEALED.intersection({int(s) for s in seasons})
    if bad:
        raise RuntimeError(f"SEALED season requested before materialization: {sorted(bad)}")


def build_inputs():
    qe = _safe_scan(ROOT / "data/modeling/development_v1/qb_elo_predictions_2018_2024.parquet",
                    ["game_id", "season", "week", "predicted_home_win_probability"]).rename(
        {"predicted_home_win_probability": "qbelo_home"})
    xb = _safe_scan(ROOT / "data/modeling/development_v1/chronology_corrected/xgboost_candidate_predictions_2018_2024.parquet",
                    ["candidate_id", "game_id", "season", "week", "warmup", "prediction_probability"]).filter(
        pl.col("candidate_id") == "conservative").with_columns(
        pl.when(pl.col("warmup")).then(None).otherwise(pl.col("prediction_probability")).alias("xgb_home")).select(
        ["game_id", "xgb_home"])
    em = _safe_scan(ROOT / "data/modeling/development_v1/expected_margin_predictions_2018_2024.parquet",
                    ["candidate_id", "game_id", "season", "week", "expected_home_margin"]).filter(
        pl.col("candidate_id") == "stable").select(["game_id", "expected_home_margin"])
    r4 = pl.scan_parquet(ROOT / "reports/task05d/task05d_ridge_predictions.parquet").select(
        ["candidate_id", "game_id", "season", "week", "predicted_total"]).filter(
        (pl.col("candidate_id") == "R4") & pl.col("season").is_in(DEV)).select(["game_id", "predicted_total"])
    out = _safe_scan(ROOT / "data/frozen/games/games_2018_2025.parquet", ["game_id", "season", "home_score", "away_score"])
    df = (qe.join(xb, on="game_id", how="left").join(em, on="game_id", how="left")
          .join(r4, on="game_id", how="left").join(out, on=["game_id", "season"], how="inner").collect())
    assert_not_sealed_seasons(df["season"].unique().to_list())
    return {r["game_id"]: r for r in df.to_dicts()}


def build_market(games):
    cg = pl.read_parquet(ROOT / "data/market_data/canonical/canonical_games.parquet").filter(
        pl.col("game_id").is_in(list(games))).select(["game_id", "home_abbr", "away_abbr"])
    sides = {r["game_id"]: (r["home_abbr"], r["away_abbr"]) for r in cg.to_dicts()}
    bm = pl.read_parquet(ROOT / "data/market_data/canonical/canonical_book_market.parquet").filter(
        pl.col("game_id").is_in(list(games)))
    idx = {}
    for r in bm.to_dicts():
        book, mk, gid = r.get("bookmaker_key"), r.get("market_key"), r.get("game_id")
        if book not in {"draftkings", "fanduel", "pinnacle"} or mk not in {"h2h", "spreads", "totals"}:
            continue
        if mk == "totals":
            side = str(r.get("outcome_name", "")).strip().lower()
        else:
            ab = _NAME_TO_ABBR.get(str(r.get("outcome_name", "")).strip())
            h, a = sides.get(gid, (None, None))
            side = "home" if ab == h else "away" if ab == a else None
        if side is None:
            continue
        mt = {"h2h": "moneyline", "spreads": "spread", "totals": "total"}[mk]
        try:
            o = NormalizedOffer(mt, side, book, int(r["american_price"]),
                                None if mt == "moneyline" else float(r["point"]),
                                str(r.get("actual_snapshot_timestamp_utc") or ""))
        except Exception:
            continue
        idx.setdefault((gid, mt, side, book), []).append(o)
    return idx


def _best(idx, gid, mt, side):
    xs = [o for b in BOOKS for o in idx.get((gid, mt, side, b), [])]
    return shop_moneyline(xs) if mt == "moneyline" else shop_spread(xs) if mt == "spread" else shop_total(side, xs)


def _pin(idx, gid, mt, side):
    xs = idx.get((gid, mt, side, "pinnacle"), [])
    if not xs:
        return None
    return shop_moneyline(xs) if mt == "moneyline" else shop_spread(xs) if mt == "spread" else shop_total(side, xs)


def materialize_training(games, idx, prior_gids):
    """Prior-scope training rows. Spread/total pushes keep their residual with NO y."""
    ml, spr, tot = [], [], []
    for gid in prior_gids:
        g = games[gid]
        block = _block_key(g["season"], g["week"])
        hs, as_ = g["home_score"], g["away_score"]
        ph, pa = _pin(idx, gid, "moneyline", "home"), _pin(idx, gid, "moneyline", "away")
        if ph and pa and g["qbelo_home"] is not None and g["xgb_home"] is not None:
            p_home, _ = proportional_no_vig(ph.price_american, pa.price_american)
            ml.append({"block": block, "qb": float(g["qbelo_home"]), "xgb": float(g["xgb_home"]),
                       "pin": p_home, "y": _grade_ml("home", hs, as_)})
        o = _best(idx, gid, "spread", "home")
        if o and g["expected_home_margin"] is not None:
            y = _grade_sp("home", float(o.line), hs, as_)
            row = {"block": block, "residual": hs - as_ - float(g["expected_home_margin"]),
                   "delta": float(g["expected_home_margin"]) + float(o.line),
                   "market_level": abs(float(o.line))}
            if y is not None:
                row["y"] = y
            spr.append(row)
        if g["predicted_total"] is not None:
            o = _best(idx, gid, "total", "over")
            if o:
                y = _grade_total("over", float(o.line), hs, as_)
                row = {"block": block, "residual": (hs + as_) - float(g["predicted_total"]),
                       "delta": float(g["predicted_total"]) - float(o.line),
                       "market_level": float(o.line)}
                if y is not None:
                    row["y"] = y
                tot.append(row)
    return ml, spr, tot


def _calibrated_normal_params(rows):
    """Committed calibrated_normal composition: sigma = std of residuals (ddof=1);
    logistic (C=0.05) of y on delta/sigma over y-present rows only."""
    sig = float(np.std([float(r["residual"]) for r in rows], ddof=1)) if len(rows) > 1 else 14.0
    sig = max(sig, 1e-6)
    cov = [r for r in rows if "y" in r]
    if len(cov) < 128:
        return None
    z = [float(r["delta"]) / sig for r in cov]
    y = [int(r["y"]) for r in cov]
    it, co = _lr([[v] for v in z], y)
    return {"sigma": sig, "intercept": it, "slope": co[0]}


class SpreadCandidateFitter:
    """Precomputed sorted residual pools for the three ECDF spread candidates."""

    def __init__(self, spr_tr):
        self.rows = spr_tr
        res = np.sort(np.asarray([float(r["residual"]) for r in spr_tr], dtype=float))
        self.res_all = res
        self.res_band = {}
        for b in (0, 1, 2):
            self.res_band[b] = np.sort(np.asarray(
                [float(r["residual"]) for r in spr_tr
                 if r.get("market_level") is not None and spread_band(abs(float(r["market_level"]))) == b],
                dtype=float))
        allv = [float(r["residual"]) for r in spr_tr]
        self.sig_all = _mad_sigma(allv)
        self.sig_band = {b: _mad_sigma([float(x) for x in self.res_band[b]]) if len(self.res_band[b]) >= 2
                         else self.sig_all for b in (0, 1, 2)}
        # pooled standardized z arrays: each prior residual scaled by its OWN band sigma
        zs = []
        for r in spr_tr:
            rb = spread_band(abs(float(r["market_level"]))) if r.get("market_level") is not None else 1
            zs.append(float(r["residual"]) / self.sig_band[rb])
        self.z_all = np.sort(np.asarray(zs, dtype=float))

    def prob(self, fam, delta, market_level):
        if fam == "empirical_residual_cdf":
            return smooth_ecdf_from_sorted(self.res_all, -float(delta))
        if fam == "conditional_band_ecdf":
            p, _ = conditional_band_probability(self.rows, float(delta), float(market_level))
            return p
        if fam == "standardized_conditional_ecdf":
            b = spread_band(abs(float(market_level)))
            sig = self.sig_band[b] if len(self.res_band[b]) >= 2 else self.sig_all
            z = float(delta) / sig
            return smooth_ecdf_from_sorted(self.z_all, -z)
        raise ValueError(fam)


def run():
    t0 = time.time()
    cfg_sha = cfg_sha_of(ROOT / "config/market_evaluator_v1.yaml")
    games = build_inputs()
    idx = build_market(games)
    blocks = sorted({(_block_key(g["season"], g["week"]), gid) for gid, g in games.items()})
    ordered = sorted({b for b, _ in blocks})
    rows_out = []
    push_counts = {"spread_push_rows_no_y_in_prior_pools": 0,
                   "total_push_rows_no_y_in_prior_pools": 0,
                   "spread_push_rows_current_board": 0,
                   "total_push_rows_current_board": 0}
    for block in ordered:
        current = [gid for b, gid in blocks if b == block]
        prior = [gid for b, gid in blocks if b < block]
        ml_tr, spr_tr, tot_tr = materialize_training(games, idx, prior)
        push_counts["spread_push_rows_no_y_in_prior_pools"] += sum(1 for r in spr_tr if "y" not in r)
        push_counts["total_push_rows_no_y_in_prior_pools"] += sum(1 for t in tot_tr if "y" not in t)

        # ---- incumbent ML state (committed composition, global_shrinkage only) ----
        usable = [r for r in ml_tr if r.get("qb") is not None and r.get("xgb") is not None and r.get("pin") is not None]
        lam = fit_global_lambda([(r["qb"] + r["xgb"]) / 2.0 for r in usable],
                                [r["pin"] for r in usable], [r["y"] for r in usable]) if usable else 0.0
        st_gs = _ml_state("global_shrinkage", {"lambda": lam}, usable, VERSION, cfg_sha)

        # ---- incumbent point states (committed composition, calibrated_normal only) ----
        spr_fit = [r for r in spr_tr if "y" in r]
        tot_fit = [r for r in tot_tr if "y" in r]
        cn_spread = _calibrated_normal_params(spr_fit)
        st_cn_spr = (_point_state("calibrated_normal", cn_spread, spr_fit, "spread", VERSION, cfg_sha,
                                  cn_spread["sigma"]) if cn_spread else None)
        cn_total = _calibrated_normal_params(tot_fit)
        st_cn_tot = (_point_state("calibrated_normal", cn_total, tot_fit, "total", VERSION, cfg_sha,
                                  cn_total["sigma"]) if cn_total else None)

        # ---- v2 ML reliability inputs (exact-avg signal basis, committed modules) ----
        triples = [(r["block"], (r["qb"] + r["xgb"]) / 2.0, r["y"]) for r in usable]
        ml_unc = block_bootstrap_calibration_radius(triples) if triples else None
        ml_stable = stability_from_radius(triples, ml_unc if ml_unc is not None else 1.0) if triples else False
        ml_feats = _ml_support_features(usable)
        ml_support_n = len(usable)

        sp_fit = SpreadCandidateFitter(spr_tr)
        tot_res = np.sort(np.asarray([float(r["residual"]) for r in tot_tr], dtype=float))
        # committed sigma basis for the raw normal_cdf baseline (y-present prior residuals,
        # identical convention to fitting.fit_point_states)
        sig_spr = float(np.std([float(r["residual"]) for r in spr_fit], ddof=1)) if len(spr_fit) > 1 else 14.0
        sig_spr = max(sig_spr, 1e-6)

        for gid in current:
            g = games[gid]
            hs, as_ = g["home_score"], g["away_score"]
            gs = GameState(gid, int(g["season"]), str(g["week"]), None, g["qbelo_home"], g["xgb_home"],
                           g["expected_home_margin"], g["predicted_total"])
            base = {"block": block, "game_id": gid, "season": int(g["season"])}

            # ---------------- moneyline ----------------
            ph, pa = _pin(idx, gid, "moneyline", "home"), _pin(idx, gid, "moneyline", "away")
            if ph and pa and g["qbelo_home"] is not None and g["xgb_home"] is not None:
                pinh, pina = proportional_no_vig(ph.price_american, pa.price_american)
                for side in ("home", "away"):
                    o = _best(idx, gid, "moneyline", side)
                    if o is None:
                        continue
                    q = g["qbelo_home"] if side == "home" else 1.0 - g["qbelo_home"]
                    x = g["xgb_home"] if side == "home" else 1.0 - g["xgb_home"]
                    avg = (q + x) / 2.0
                    pin_sel = pinh if side == "home" else pina
                    resid = avg - pin_sel
                    disag = abs(q - x)
                    be = break_even_probability(o.price_american)
                    dec = american_to_decimal(o.price_american)
                    y = _grade_ml(side, hs, as_)
                    # shared experimental tier (exact-avg basis, committed modules)
                    svals = [pin_sel, avg - pin_sel, disag]
                    sup_d = overall_support_distance(svals, list(ml_feats))
                    rel = rel_tier(ReliabilityEvidence(ml_support_n, ml_unc, sup_d, disag, ml_stable))
                    # incumbent via committed evaluator path
                    rr = evaluate_offer(gs, o, st_gs, pinnacle_no_vig_selected=pin_sel)
                    p_gs = rr.actionable_probability
                    rows_out.append({**base, "market_type": "moneyline", "family": "global_shrinkage",
                                     "side": side, "price_american": int(o.price_american), "break_even": be,
                                     "decimal": dec, "p": p_gs, "staking_p": rr.staking_probability,
                                     "ev_unit": rr.expected_value, "y": y, "residual": resid, "p_model": avg,
                                     "p_market": pin_sel, "disag": disag, "uncertainty": rr.uncertainty,
                                     "support_n": ml_support_n, "reliability": rr.reliability,
                                     "lambda": lam})
                    # v1 prior benchmark: global shrinkage with preregistered floor, same tier gating as v2
                    p_floor = None if rel == "UNSUPPORTED" else clip_probability(
                        pin_sel + max(lam, ML_LAMBDA_FLOOR) * resid)
                    rows_out.append({**base, "market_type": "moneyline", "family": "partial_shrinkage_floor",
                                     "side": side, "price_american": int(o.price_american), "break_even": be,
                                     "decimal": dec, "p": p_floor, "staking_p": None,
                                     "ev_unit": None if p_floor is None else p_floor * dec - 1.0,
                                     "y": y, "residual": resid,
                                     "p_model": avg, "p_market": pin_sel, "disag": disag, "uncertainty": ml_unc,
                                     "support_n": ml_support_n, "reliability": rel, "lambda": lam})
                    # NEW preregistered candidate (fail-closed entry point)
                    p_v2, v2d = ml_v2_actionable_probability(q, x, pin_sel, rel, ml_unc)
                    sp_v2 = (None if p_v2 is None
                             else clip_probability(staking_probability(p_v2, be, rel, ml_unc)))
                    ev_v2 = (None if p_v2 is None else p_v2 * dec - 1.0)
                    rows_out.append({**base, "market_type": "moneyline",
                                     "family": "reliability_aware_shrinkage_v2", "side": side,
                                     "price_american": int(o.price_american), "break_even": be, "decimal": dec,
                                     "p": p_v2, "staking_p": sp_v2, "ev_unit": ev_v2, "y": y,
                                     "residual": resid, "p_model": avg, "p_market": pin_sel, "disag": disag,
                                     "uncertainty": ml_unc, "support_n": ml_support_n, "reliability": rel,
                                     "lambda": lam,
                                     "base_weight": v2d.get("base_weight"),
                                     "unc_damping": v2d.get("uncertainty_damping"),
                                     "final_weight": v2d.get("final_weight")})

            # ---------------- spread ----------------
            # Canonical HOME orientation (prereg): the probability map is evaluated
            # ONCE on the home-side delta; the away side is its exact complement
            # (p_away = 1 - p_home). Empirical residual CDFs are not symmetric,
            # so evaluating the map per-side would break complement coherence.
            if g["expected_home_margin"] is not None:
                o_anchor = _best(idx, gid, "spread", "home")
                if o_anchor is not None:
                    em = float(g["expected_home_margin"])
                    delta_home = em + float(o_anchor.line)
                    mlev = abs(float(o_anchor.line))
                    p_canon = {}
                    if sig_spr is not None:
                        p_canon["normal_cdf"] = normal_cdf(delta_home / sig_spr)
                    for fam in ("empirical_residual_cdf", "conditional_band_ecdf",
                                "standardized_conditional_ecdf"):
                        p_canon[fam] = sp_fit.prob(fam, delta_home, mlev)
                    if st_cn_spr is not None:
                        rr = evaluate_offer(gs, o_anchor, st_cn_spr)
                        p_canon["calibrated_normal"] = rr.actionable_probability
                        cn_stak = rr.staking_probability
                    else:
                        cn_stak = None
                    for side in ("home", "away"):
                        o = o_anchor if side == "home" else _best(idx, gid, "spread", "away")
                        if o is None:
                            continue
                        y = _grade_sp(side, float(o.line), hs, as_)
                        if y is None:
                            push_counts["spread_push_rows_current_board"] += 1
                        be = break_even_probability(o.price_american)
                        dec = american_to_decimal(o.price_american)
                        for fam in SP_FAMS:
                            pc = p_canon.get(fam)
                            if pc is None:
                                continue
                            p = clip_probability(pc if side == "home" else 1.0 - pc)
                            rows_out.append({**base, "market_type": "spread", "family": fam, "side": side,
                                             "line": float(o.line), "price_american": int(o.price_american),
                                             "break_even": be, "decimal": dec, "p": p,
                                             "staking_p": cn_stak if fam == "calibrated_normal" else None,
                                             "ev_unit": None if p is None else p * dec - 1.0, "y": y,
                                             "delta": delta_home, "market_level": mlev})

            # ---------------- total (canonical over) ----------------
            if g["predicted_total"] is not None:
                o_over = _best(idx, gid, "total", "over")
                if o_over is not None:
                    over_delta = float(g["predicted_total"]) - float(o_over.line)
                    p_over_cand = {}
                    p_over_cand["canonical_over_ecdf"] = smooth_ecdf_from_sorted(tot_res, -over_delta)
                    if st_cn_tot is not None:
                        for side in ("over", "under"):
                            o = o_over if side == "over" else _best(idx, gid, "total", "under")
                            if o is None:
                                continue
                            rr = evaluate_offer(gs, o, st_cn_tot)
                            y = _grade_total(side, float(o.line), hs, as_)
                            if y is None:
                                push_counts["total_push_rows_current_board"] += 1
                            be = break_even_probability(o.price_american)
                            dec = american_to_decimal(o.price_american)
                            p = rr.actionable_probability
                            rows_out.append({**base, "market_type": "total", "family": "calibrated_normal",
                                             "side": side, "line": float(o.line),
                                             "price_american": int(o.price_american), "break_even": be,
                                             "decimal": dec, "p": p, "staking_p": rr.staking_probability,
                                             "ev_unit": None if p is None else p * dec - 1.0, "y": y,
                                             "delta": over_delta if side == "over" else -over_delta,
                                             "market_level": float(o.line)})
                    for side in ("over", "under"):
                        o = o_over if side == "over" else _best(idx, gid, "total", "under")
                        if o is None:
                            continue
                        y = _grade_total(side, float(o.line), hs, as_)
                        if y is None:
                            push_counts["total_push_rows_current_board"] += 1
                        be = break_even_probability(o.price_american)
                        dec = american_to_decimal(o.price_american)
                        po = p_over_cand["canonical_over_ecdf"]
                        p = clip_probability(po if side == "over" else 1.0 - po)
                        rows_out.append({**base, "market_type": "total", "family": "canonical_over_ecdf",
                                         "side": side, "line": float(o.line),
                                         "price_american": int(o.price_american), "break_even": be,
                                         "decimal": dec, "p": p, "staking_p": None,
                                         "ev_unit": p * dec - 1.0, "y": y,
                                         "delta": over_delta if side == "over" else -over_delta,
                                         "market_level": float(o.line)})
        print(f"{block} rows={len(rows_out)} {time.time()-t0:.0f}s", flush=True)

    OUTD.mkdir(parents=True, exist_ok=True)
    df = pl.DataFrame(rows_out, infer_schema_length=len(rows_out))
    df.write_parquet(OUTD / "candidate_full_board.parquet")
    (OUTD / "_push_counts.json").write_text(json.dumps(push_counts, indent=2, sort_keys=True))
    prov = {
        "harness": "candidate_v2_run.py",
        "code_file_sha256": {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in [
            "candidate_v2_run.py", "src/nfl_edge/value/redesign.py", "src/nfl_edge/value/fitting.py",
            "src/nfl_edge/value/evaluators.py", "src/nfl_edge/value/reliability.py",
            "src/nfl_edge/value/uncertainty.py", "src/nfl_edge/value/market_math.py"]},
        "config_sha256": cfg_sha,
        "preregistration_sha256": hashlib.sha256(
            Path("/tmp/task05f-redesign-v2-prereg.json").read_bytes()).hexdigest(),
        "development_seasons": DEV,
        "sealed_seasons": sorted(SEALED),
        "chronology": "expanding prior season-week blocks only; no 2018-2019 evaluator rows",
        "rows": df.height,
        "push_counts": push_counts,
        "ml_families": list(ML_FAMS),
        "spread_families": list(SP_FAMS),
        "total_families": list(TO_FAMS),
    }
    (OUTD / "candidate_provenance.json").write_text(json.dumps(prov, indent=2, sort_keys=True))
    print(json.dumps({"rows": df.height, **push_counts}, sort_keys=True))


if __name__ == "__main__":
    run()
