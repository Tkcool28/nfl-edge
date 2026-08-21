#!/usr/bin/env python3
"""Task 05E ML-reversal forensic diagnostic (deterministic, read-only).

Dissects the corrected repo-native scorer ledgers (reports/task05e_remediated)
for the locked ML candidates:
  * DOG_AVG    : ML_DOG_VALUE_ZONE  / AVG   / ZONE   (primary)
  * DOG_CORROB : ML_DOG_VALUE_ZONE  / CORROB / ZONE  (primary)
  * AVG_0_2    : ML_AVG_DISAGREEMENT / AVG  / 0-2    (primary)
Discovery 2020-2022 vs Confirmation 2023-2024, per season.

All values are recomputed deterministically from frozen artifacts using the
repo-native scoring primitives (src/nfl_edge/market_edge/scoring). The frozen
experiment is preserved — no retune, no threshold change, 2025 stays SEALED.

Writes (no commit / no push; read-only on artifacts):
  reports/task05e_remediated/ml_reversal_forensic_v1.json
  reports/task05e_remediated/ml_reversal_forensic_v1.md
  reports/task05e_remediated/ml_reversal_forensic_*.csv
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

from nfl_edge.market_edge import scoring

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports/task05e_remediated"
LEDGER_D = OUT_DIR / "market_edge_discovery_corrected_ledger_v1.parquet"
LEDGER_C = OUT_DIR / "market_edge_confirmation_corrected_ledger_v1.parquet"
CENSUS = ROOT / "data/modeling/development_v1/market_edge_census_v1.parquet"
GAMES = ROOT / "data/frozen/games/games_2018_2025.parquet"
XGB = ROOT / "data/modeling/development_v1/chronology_corrected/xgboost_candidate_predictions_2018_2024.parquet"
QB = ROOT / "data/modeling/development_v1/qb_elo_predictions_2018_2024.parquet"

SE = [2020, 2021, 2022, 2023, 2024]
DISC = [2020, 2021, 2022]
CONF = [2023, 2024]
SAMPLE = 25

PBANDS = [("111-125", 111, 125), ("126-150", 126, 150),
          ("151-175", 151, 175), ("176-200", 176, 200)]
PB_SPLIT = [(0.40, 0.45, "40-45"), (0.45, 0.50, "45-50")]
EDGE_SPLIT = [("0-5", 0, 5), ("5-8", 5, 8), ("8+", 8, 999)]

PRIMARY = {
    "DOG_AVG": ("ML_DOG_VALUE_ZONE", "AVG", "ZONE"),
    "DOG_CORROB": ("ML_DOG_VALUE_ZONE", "CORROB", "ZONE"),
    "AVG_0_2": ("ML_AVG_DISAGREEMENT", "AVG", "0-2"),
}


def wl_stats(df: pl.DataFrame) -> dict:
    n = df.height
    if n == 0:
        return {"N": 0}
    wins = int((df["w"] == 1).sum())
    pushes = int((df["p_push"] == 1).sum())
    profit = float(df["profit"].sum())
    return {
        "N": n, "wins": wins, "pushes": pushes,
        "hit_rate": round(wins / n, 4),
        "profit": round(profit, 4), "roi": round(profit / n, 4),
        "avg_breakeven": round(float(df["breakeven"].mean()), 4),
        "hr_minus_be": round(wins / n - float(df["breakeven"].mean()), 4),
        "avg_p_model": round(float(df["p_model"].mean()), 4) if df["p_model"].is_not_null().any() else None,
        "avg_price": round(float(df["price_american"].mean()), 2),
        "avg_edge_pp": round(float(df["edge_pp"].mean()), 4) if df["edge_pp"].is_not_null().any() else None,
        "brier": round(float(((df["p_model"] - df["w"]).pow(2)).mean()), 4) if df["p_model"].is_not_null().any() else None,
    }


def qr(x: list) -> list:
    if not x:
        return [None] * 3
    s = sorted(x)
    n = len(s)

    def qq(p):
        if n == 1:
            return round(s[0], 4)
        idx = (n - 1) * p
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        return round(s[lo] + (s[hi] - s[lo]) * (idx - lo), 4)

    return [qq(0.25), qq(0.5), qq(0.75)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # -------------------- inputs (sealed-holdout firewall first) --------------------
    # Mirror the corrected main scorer: reject any season-2025 row in every raw
    # graded/model frame BEFORE any filtering/materialization.
    ld = pl.read_parquet(LEDGER_D)
    lc = pl.read_parquet(LEDGER_C)
    ledger_raw = pl.concat([ld, lc])
    census_raw = pl.read_parquet(CENSUS)
    xgb_raw = pl.read_parquet(XGB)
    qb_raw = pl.read_parquet(QB)
    for name, raw in [("corrected-ledger", ledger_raw), ("census", census_raw),
                      ("xgb", xgb_raw), ("qb", qb_raw)]:
        bad25 = raw.filter(pl.col("season") == 2025).height
        if bad25:
            raise RuntimeError(
                f"{name} carries {bad25} season-2025 row(s); 2025 SEALED — refusing to continue.")
    games_raw = pl.read_parquet(GAMES)  # frozen source legitimately extends through 2025;
    frozen_2025_games = int(games_raw.filter(pl.col("season") == 2025).height)
    if frozen_2025_games == 0:
        raise RuntimeError("No 2025 games found in frozen games source — unexpectedly empty; refusing.")
    if games_raw.filter(pl.col("season").is_in(SE)).height == 0:
        raise RuntimeError("No development-season (2020-2024) games present — refusing.")

    ledger = ledger_raw.filter(pl.col("season").is_in(SE))
    games = games_raw.filter(pl.col("season").is_in(SE))
    census = census_raw
    pe = census.filter(pl.col("census_family") == "POSITIVE_EDGE_CANDIDATE")
    ts = census.filter(pl.col("census_family") == "TWO_SIDED_ABSOLUTE_DIAGNOSTIC")

    xgb = (xgb_raw.filter(pl.col("candidate_id") == "conservative")
           .filter(pl.col("season").is_in(SE))
           .with_columns(pl.when(pl.col("warmup")).then(None)
                         .otherwise(pl.col("prediction_probability"))
                         .alias("xgb_p_home")))
    qb = qb_raw.filter(pl.col("season").is_in(SE)) \
        .rename({"predicted_home_win_probability": "qb_p_home"})

    cand = {}
    for k, (f, m, b) in PRIMARY.items():
        cand[k] = ledger.filter((pl.col("family") == f) &
                                (pl.col("model") == m) &
                                (pl.col("bucket") == b))
    gmap = {g["game_id"]: g for g in games.to_dicts()}
    # Every graded candidate row must live entirely inside 2020-2024; a 2025
    # game_id here would have already hard-failed the firewall above, so this
    # catch is belt-and-suspenders: none of the candidate frames may be 2025.
    n2025_graded = 0
    for _k, _df in cand.items():
        n2025_graded += int((_df["season"] == 2025).sum())
    if n2025_graded:
        raise RuntimeError(f"{n2025_graded} graded 2025 row(s) in candidate frames — SEALED; refusing.")

    out: dict = {}
    out["sealed_2025"] = {
        "touched": False,
        "firewall": "2025 hard-rejected on every raw graded/model frame before filtering "
                    "(mirrors corrected main scorer; no 2025 outcome/model row read into results).",
        "frozen_2025_games_excluded": frozen_2025_games,
        "development_seasons_graded": SE,
    }
    out["candidate_N"] = {k: wl_stats(v) for k, v in cand.items()}
    out["per_season_primary"] = {
        k: {int(s): wl_stats(v.filter(pl.col("season") == s))
            for s in sorted(v["season"].unique().to_list())}
        for k, v in cand.items()
    }

    # ============================== D1: side, per season ==============
    d1 = {}
    for k, df in cand.items():
        recs = []
        for season in sorted(df["season"].unique().to_list()):
            s = df.filter(pl.col("season") == season)
            for side in ("home", "away"):
                sub = s.filter(pl.col("selected_side") == side)
                if sub.height:
                    recs.append({"candidate": k, "season": season, "side": side,
                                 **wl_stats(sub)})
        for side in ("home", "away"):
            sub = df.filter(pl.col("selected_side") == side)
            if sub.height:
                recs.append({"candidate": k, "season": "POOL", "side": side,
                             **wl_stats(sub)})
        d1[k] = recs
        pl.DataFrame(recs).write_csv(out_dir / f"ml_reversal_forensic_d1_side_{k.lower()}.csv")
    out["d1_home_away"] = d1

    # ============================== D2: market identity ================
    ts_h = ts.filter((pl.col("side") == "home") & (pl.col("model") == "AVG")).select(["game_id", "pinnacle_american"]).rename({"pinnacle_american": "pin_home_am"}).unique(subset=["game_id"])
    ts_a = ts.filter((pl.col("side") == "away") & (pl.col("model") == "AVG")).select(["game_id", "pinnacle_american"]).rename({"pinnacle_american": "pin_away_am"}).unique(subset=["game_id"])
    novig = ts.filter(pl.col("model") == "AVG").select(["game_id", "pinnacle_novig_home", "pinnacle_novig_away"]).unique(subset=["game_id"])

    d2 = {}
    for k in ("DOG_AVG", "DOG_CORROB"):
        df = (cand[k]
              .join(ts_a, on=["game_id"], how="left")
              .join(ts_h, on=["game_id"], how="left")
              .join(novig, on="game_id", how="left"))
        recs = []
        for r in df.to_dicts():
            side = r["selected_side"]
            nv_side = r["pinnacle_novig_home"] if side == "home" else r["pinnacle_novig_away"]
            pin_side = r["pin_home_am"] if side == "home" else r["pin_away_am"]
            pin_opp = r["pin_away_am"] if side == "home" else r["pin_home_am"]
            price = r["price_american"] if r["price_american"] is not None else 0
            recs.append({
                "game_id": r["game_id"], "season": r["season"],
                "selected_side": side, "p_model": r["p_model"],
                "price_american": r["price_american"],
                "pin_no_vig_side": nv_side, "pin_am_side": pin_side,
                "pin_am_opp": pin_opp,
                "plus_money_on_selected": bool(price > 100),
                "underdog_by_novig": bool(nv_side is not None and nv_side < 0.5),
                "underdog_by_offered": bool(pin_side is not None and pin_side > 100),
                "favorite_by_novig": bool(nv_side is not None and nv_side >= 0.5),
                "price_is_opponent_price": bool(pin_opp is not None and abs(price - pin_opp) <= 1),
            })
        tab = pl.DataFrame(recs)
        tab.write_csv(out_dir / f"ml_reversal_forensic_d2_identity_{k.lower()}.csv")
        inv = [r["game_id"] for r in recs
               if r["favorite_by_novig"] or r["price_is_opponent_price"]]
        d2[k] = {
            "rows": tab.height,
            "not_plus_money_on_selected": int((tab["plus_money_on_selected"] == False).sum()),
            "selected_is_favorite_by_novig": int(tab["favorite_by_novig"].sum()),
            "price_attached_opponent": int(tab["price_is_opponent_price"].sum()),
            "underdog_by_novig_count": int(tab["underdog_by_novig"].sum()),
            "underdog_by_offered_count": int(tab["underdog_by_offered"].sum()),
            "inversion_or_attachment_game_ids": inv,
        }
    out["d2_market_identity"] = d2

    # ============================== D3: exact recompute ================
    d3 = {}
    for k, is_avg in (("DOG_AVG", True), ("DOG_CORROB", False)):
        df = cand[k].sort(["season", "game_id", "selected_side"])
        if is_avg:
            rows = pl.concat([
                df.filter(pl.col("season").is_in(DISC)).head(SAMPLE),
                df.filter(pl.col("season").is_in(CONF)).head(SAMPLE),
            ])
        else:
            rows = df
        rec, mismatch = [], []
        for r_ in rows.to_dicts():
            g = gmap.get(r_["game_id"])
            if not g:
                continue
            dec = scoring.american_to_decimal(r_["price_american"])
            if dec is None:
                continue
            w, push, profit = scoring.moneyline_grading(
                r_["selected_side"], g["home_score"], g["away_score"], dec)
            ok = (r_["w"] == w and r_["p_push"] == push
                  and abs(r_["profit"] - profit) < 1e-6)
            rec.append({
                "game_id": r_["game_id"], "season": r_["season"],
                "selected_side": r_["selected_side"],
                "p_model": r_["p_model"], "edge_pp": r_["edge_pp"],
                "price_american": r_["price_american"],
                "home_team": g["home_team"], "away_team": g["away_team"],
                "home_score": g["home_score"], "away_score": g["away_score"],
                "ledger_w": r_["w"], "recomputed_w": w,
                "ledger_profit": r_["profit"], "recomputed_profit": profit,
                "match": bool(ok),
            })
            if not ok:
                mismatch.append(r_["game_id"])
        tab = pl.DataFrame(rec)
        tab.write_csv(out_dir / f"ml_reversal_forensic_d3_recompute_{k.lower()}.csv")
        d3[k] = {"rows_checked": tab.height, "mismatch_count": len(mismatch),
                 "mismatch_game_ids": mismatch}
    out["d3_row_recomputation"] = d3

    # ============================== D4: calibration (DOG_AVG) ========
    pex = pe.filter(pl.col("model") == "XGB").select(["game_id", "season", "side", "p_model"]).rename({"p_model": "xgb_p_side", "side": "selected_side"})
    peq = pe.filter(pl.col("model") == "QB_ELO").select(["game_id", "season", "side", "p_model"]).rename({"p_model": "qb_p_side", "side": "selected_side"})
    dfa = (cand["DOG_AVG"]
           .join(pex, on=["game_id", "season", "selected_side"], how="left")
           .join(peq, on=["game_id", "season", "selected_side"], how="left"))
    d4 = {}
    for season in sorted(dfa["season"].unique().to_list()):
        s = dfa.filter(pl.col("season") == season)
        if s.height == 0:
            continue
        entry = {}
        for nm, colp in (("AVG", "p_model"), ("QB", "qb_p_side"), ("XGB", "xgb_p_side")):
            sub = s.filter(pl.col(colp).is_not_null())
            if sub.height == 0:
                entry[nm] = None
                continue
            n = sub.height
            obs = float((sub["w"] == 1).sum()) / n
            mean_p = float(sub[colp].mean())
            brier = float(((sub[colp] - sub["w"]).pow(2)).mean())
            entry[nm] = {
                "N": n, "observed_win": round(obs, 4), "mean_pred_p": round(mean_p, 4),
                "calibration_gap_pp": round((mean_p - obs) * 100, 2),
                "brier": round(brier, 4),
            }
        d4[str(season)] = entry
    out["d4_calibration_season"] = d4

    pband = {}
    for season in sorted(dfa["season"].unique().to_list()):
        s = dfa.filter(pl.col("season") == season)
        for lo, hi, lbl in PB_SPLIT:
            b = s.filter((pl.col("p_model") >= lo) & (pl.col("p_model") < hi))
            if b.height:
                pband[f"{season}_{lbl}"] = wl_stats(b)
    out["d4b_pband"] = pband

    # ============================== D5: interaction (DOG_AVG) ========
    dfx = cand["DOG_AVG"]
    d5 = []
    for season in sorted(dfx["season"].unique().to_list()):
        s = dfx.filter(pl.col("season") == season)
        for side in ("home", "away"):
            sub = s.filter(pl.col("selected_side") == side)
            for lo, hi, lbl in PB_SPLIT:
                band = sub.filter((pl.col("p_model") >= lo) & (pl.col("p_model") < hi))
                if band.height:
                    d5.append({"season": season, "side": side, "band": lbl,
                               **wl_stats(band)})
    for elbl, elo, ehi in EDGE_SPLIT:
        for season in sorted(dfx["season"].unique().to_list()):
            s = dfx.filter((pl.col("season") == season) &
                           (pl.col("edge_pp") >= elo) &
                           (pl.col("edge_pp") < ehi))
            for side in ("home", "away"):
                sub = s.filter(pl.col("selected_side") == side)
                if sub.height:
                    d5.append({"season": season, "side": side, "edgeband": elbl,
                               **wl_stats(sub)})
    out["d5_interaction"] = d5
    pl.DataFrame(d5).write_csv(out_dir / "ml_reversal_forensic_d5_interaction.csv")

    # ============================== D6: book mix + price bands =======
    peb = pe.select(["game_id", "model", "side", "actionable_book"])
    d6 = {}
    for k, df in cand.items():
        # CORROB rows price from the AVG source model when both constituents exist;
        # census PE only carries QB_ELO/XGB/AVG, so map CORROB -> AVG by game+side.
        if k == "DOG_CORROB":
            pebk = (peb.filter(pl.col("model") == "AVG")
                    .select(["game_id", "side", "actionable_book"]))
            dfm = df.join(pebk, left_on=["game_id", "selected_side"],
                          right_on=["game_id", "side"], how="left")
        else:
            dfm = df.join(peb, left_on=["game_id", "model", "selected_side"],
                          right_on=["game_id", "model", "side"], how="left")
        mix = []
        for season in [None] + sorted(dfm["season"].unique().to_list()):
            s = dfm if season is None else dfm.filter(pl.col("season") == season)
            if s.height == 0:
                continue
            grp = s.group_by("actionable_book").agg(pl.len().alias("N"),
                                                    pl.col("profit").sum().alias("profit"))
            mix.append({"season": season or "ALL", "mix": {
                r["actionable_book"]: {"N": int(r["N"]), "profit": round(float(r["profit"]), 3)}
                for r in grp.to_dicts()}})
        price_bands = []
        for season in [None] + sorted(dfm["season"].unique().to_list()):
            s = dfm if season is None else dfm.filter(pl.col("season") == season)
            if s.height == 0:
                continue
            for lbl, plo, phi in PBANDS:
                b = s.filter((pl.col("price_american") >= plo) & (pl.col("price_american") <= phi))
                if b.height:
                    price_bands.append({"season": season or "ALL", "band": lbl,
                                        **wl_stats(b)})
        d6[k] = {"book_mix": mix, "price_bands": price_bands}
        pl.DataFrame(price_bands).write_csv(out_dir / f"ml_reversal_forensic_d6_pricebands_{k.lower()}.csv")
    out["d6_book_mix"] = d6

    # ==============================D7: Pinnacle distributions ========
    dfm7 = cand["DOG_AVG"].join(novig, on="game_id", how="left")
    d7 = {}
    for season in [None] + sorted(dfm7["season"].unique().to_list()):
        s = dfm7 if season is None else dfm7.filter(pl.col("season") == season)
        if s.height == 0:
            continue
        fair, edge = [], []
        for r in s.to_dicts():
            nv = (r["pinnacle_novig_home"] if r["selected_side"] == "home"
                  else r["pinnacle_novig_away"])
            if nv is not None:
                fair.append(nv)
                if r["p_model"] is not None:
                    edge.append((r["p_model"] - nv) * 100)
        d7[season or "ALL"] = {
            "fair_prob": {"mean": round(sum(fair) / len(fair), 4) if fair else None,
                          "quartiles": qr(fair)},
            "model_edge_pp": {"mean": round(sum(edge) / len(edge), 4) if edge else None,
                              "quartiles": qr(edge)},
        }
    out["d7_distributions"] = d7

    # ============================== D8: team concentration ===========
    gsel = games.select(["game_id", "home_team", "away_team"])
    d8 = {}

    def _team_conc(sub: pl.DataFrame, tag: str) -> dict:
        """Fork concentration statistics for a team-profit slice (scope = ALL /
        DISCOVERY / CONFIRMATION / season_N). Not a single descending-profit
        sort: reports the true largest ABSOLUTE contributor, the max-row-count
        team, the bottom (worst) loss teams, and loss concentration vs the
        total absolute loss across losing teams."""
        if sub.height == 0:
            return {"scope": tag, "rows": 0}
        bt = (sub.group_by("team").agg(pl.len().alias("N"),
                                       pl.col("profit").sum().alias("profit"))
              .with_columns(pl.col("profit").abs().alias("abs_profit")))
        tot_abs_loss = float(bt.filter(pl.col("profit") < 0)["profit"].abs().sum())
        largest_abs = bt.sort(["abs_profit", "team"], descending=[True, True]).head(1).to_dicts()[0]
        max_cnt = bt.sort(["N", "team"], descending=[True, True]).head(1).to_dicts()[0]
        loss_teams = bt.filter(pl.col("profit") < 0).sort("profit").to_dicts()  # ascending => worst first
        biggest_loss = loss_teams[0] if loss_teams else None
        biggest_loss_abs = -biggest_loss["profit"] if biggest_loss else 0.0
        top3_loss_abs = sum((-t["profit"]) for t in loss_teams[:3])
        return {
            "scope": tag, "rows": sub.height,
            "total_abs_loss": round(tot_abs_loss, 3),
            "largest_abs_contributor": {
                "team": largest_abs["team"], "profit": round(largest_abs["profit"], 3),
                "abs_profit": round(largest_abs["abs_profit"], 3),
                "N": int(largest_abs["N"])},
            "max_candidate_count_team": {"team": max_cnt["team"], "N": int(max_cnt["N"])},
            "bottom_loss_teams": [{"team": t["team"], "profit": round(t["profit"], 3),
                                   "N": int(t["N"])} for t in loss_teams[:5]],
            "largest_loss_share": (round(biggest_loss_abs / tot_abs_loss, 4) if tot_abs_loss > 0 else None),
            "largest_loss_share_pct": (round(100 * biggest_loss_abs / tot_abs_loss, 1) if tot_abs_loss > 0 else None),
            "top3_loss_concentration": (round(top3_loss_abs / tot_abs_loss, 4) if tot_abs_loss > 0 else None),
            "top3_loss_concentration_pct": (round(100 * top3_loss_abs / tot_abs_loss, 1) if tot_abs_loss > 0 else None),
        }

    for k in ("DOG_AVG", "DOG_CORROB"):
        dfm = cand[k].join(gsel, on="game_id", how="left")
        recs = []
        for r in dfm.to_dicts():
            team = r["home_team"] if r["selected_side"] == "home" else r["away_team"]
            recs.append({"season": r["season"],
                         "period": "DISCOVERY" if r["season"] in DISC else "CONFIRMATION",
                         "team": team, "profit": r["profit"], "w": r["w"],
                         "price": r["price_american"], "game_id": r["game_id"]})
        td = pl.DataFrame(recs)
        by_team = (td.group_by("team").agg(pl.len().alias("N"),
                                           pl.col("profit").sum().alias("profit"),
                                           pl.col("w").sum().alias("wins"))
                   .with_columns(pl.col("profit").abs().alias("abs_profit"))
                   .sort("abs_profit", descending=True))
        ping = []
        if td.height:
            for tag, sel in [("ALL", td),
                             ("DISCOVERY", td.filter(pl.col("period") == "DISCOVERY")),
                             ("CONFIRMATION", td.filter(pl.col("period") == "CONFIRMATION"))]:
                if sel.height:
                    ping.append(_team_conc(sel, tag))
            for s in sorted(td["season"].unique().to_list()):
                ping.append(_team_conc(td.filter(pl.col("season") == s), f"season_{s}"))
        d8[k] = {"total_rows": td.height, "by_team": by_team.to_dicts(), "concentration": ping}
        by_team.write_csv(out_dir / f"ml_reversal_forensic_d8_teams_{k.lower()}.csv")
    out["d8_team_concentration"] = d8

    # ============================== D9: chronology ===================
    df9 = cand["DOG_AVG"].filter(pl.col("season_week").is_not_null())
    df9 = df9.with_columns(pl.col("season_week").cast(pl.Utf8).str.zfill(3).alias("_wk"))
    df9 = df9.sort(["season", "_wk", "game_id"])
    weekly = []
    for season in sorted(df9["season"].unique().to_list()):
        s = df9.filter(pl.col("season") == season)
        cum, wins, n = 0.0, 0, 0
        for r in s.to_dicts():
            n += 1
            cum += r["profit"]
            wins += 1 if r["w"] == 1 else 0
            weekly.append({"season": season, "week": r["_wk"],
                           "cum_profit": round(cum, 3), "cum_wins": wins,
                           "cum_roi": round(cum / n, 4), "n": n})
    out["d9_chronology"] = {"by_week": weekly}
    pl.DataFrame(weekly).write_csv(out_dir / "ml_reversal_forensic_d9_cumulative.csv")

    # ============================== D10: disagreement ================
    dfa10 = dfa.filter(pl.col("qb_p_side").is_not_null() &
                       pl.col("xgb_p_side").is_not_null())
    dfa10 = dfa10.with_columns((pl.col("qb_p_side") - pl.col("xgb_p_side")).abs().alias("qb_xgb_spread"))
    d10 = {}
    for season in [None] + sorted(dfa10["season"].unique().to_list()):
        sub = dfa10 if season is None else dfa10.filter(pl.col("season") == season)
        if sub.height == 0:
            continue
        n_qb = int((sub["qb_p_side"] > sub["xgb_p_side"]).sum())
        d10[season or "ALL"] = {
            "N": sub.height,
            "mean_abs_spread_pp": round(float(sub["qb_xgb_spread"].mean() * 100), 3),
            "std_spread_pp": round(float(sub["qb_xgb_spread"].std() * 100), 3)
            if sub.height > 1 else None,
            "n_qb_higher": n_qb,
            "n_xgb_higher": sub.height - n_qb,
        }
    out["d10_constituent_disagreement"] = d10

    # ============================== D11: orientation =================
    dfa11 = (cand["DOG_AVG"]
             .join(games.select(["game_id", "home_team", "away_team", "season"]),
                   on=["game_id"], how="left")
             .join(xgb.select(["game_id", "xgb_p_home"]), on="game_id", how="left")
             .join(qb.select(["game_id", "qb_p_home"]), on="game_id", how="left"))
    checks = []
    for r in dfa11.to_dicts():
        xh, qh_p = r["xgb_p_home"], r["qb_p_home"]
        side = r["selected_side"]
        xside = (1 - xh) if side == "away" else xh
        qside = (1 - qh_p) if side == "away" else qh_p
        both = qside is not None and xside is not None
        avg = (qside + xside) / 2 if both else (qside if qside is not None else xside)
        match = avg is not None and abs(avg - r["p_model"]) < 1e-9
        checks.append({
            "game_id": r["game_id"], "season": r["season"],
            "selected_side": r["selected_side"],
            "census_p_model": r["p_model"], "avg_from_side": avg,
            "qb_side_p": qside, "xgb_side_p": xside, "match": bool(match),
        })
    cd = pl.DataFrame(checks)
    out["d11_orientation_join"] = {
        "rows_checked": cd.height,
        "orientation_mismatch_count": int((cd["match"] == False).sum()),
        "mismatch_rows": cd.filter(pl.col("match") == False)
                           .select(["game_id", "season", "selected_side",
                                    "census_p_model", "avg_from_side"])
                           .to_dicts(),
    }

    # ============================== D12: global calibration (one row per game) ====
    # A legitimate global comparison: ONE row per game (home side only), built
    # from the frozen SOURCE home-win probabilities (QB-Elo p_home; XGB p_home;
    # AVG = mean of the two only where BOTH constituents exist) and the ACTUAL
    # home outcome. Sportsbook/census rows never define these global rows (the
    # mirrored/two-sided census rows are NOT used here).
    glob = games.select(["game_id", "season", "home_score", "away_score"])
    glob = glob.join(xgb.select(["game_id", "xgb_p_home"]), on="game_id", how="left")
    glob = glob.join(qb.select(["game_id", "qb_p_home"]), on="game_id", how="left")
    glob = glob.with_columns(
        pl.when(pl.col("home_score") > pl.col("away_score")).then(1.0)
        .when(pl.col("home_score") == pl.col("away_score")).then(None)
        .otherwise(0.0).alias("home_win"))
    glob = glob.with_columns(((pl.col("qb_p_home") + pl.col("xgb_p_home")) / 2.0).alias("avg_p_home"))
    d12 = {}
    for season in SE:
        s = glob.filter(pl.col("season") == season)
        entry = {}
        for nm, col in (("QUARTERBACK_ELO", "qb_p_home"), ("XGBOOST", "xgb_p_home"),
                        ("AVG_BOTH_CONSTITUENTS", "avg_p_home")):
            sub = s.filter(pl.col(col).is_not_null() & pl.col("home_win").is_not_null())
            if sub.height == 0:
                entry[nm] = None
                continue
            n = sub.height
            obs = float(sub["home_win"].mean())
            mp = float(sub[col].mean())
            brier = float(((sub[col] - sub["home_win"]).pow(2)).mean())
            acc = float(((sub[col] >= 0.5) == (sub["home_win"] == 1)).mean())
            entry[nm] = {
                "N_games": n, "observed_home_win_rate": round(obs, 4),
                "mean_p_home": round(mp, 4), "calibration_gap_pp": round((mp - obs) * 100, 2),
                "brier": round(brier, 4), "accuracy": round(acc, 4),
            }
        entry["dog_slice_AVG"] = out["d4_calibration_season"].get(str(season), {}).get("AVG")
        d12[str(season)] = entry
    d12_flat = []
    for season in SE:
        e = d12[str(season)]
        avgb = e.get("AVG_BOTH_CONSTITUENTS")
        d12_flat.append({
            "season": season,
            "AVG_global_N": avgb["N_games"] if avgb else None,
            "AVG_global_gap_pp": avgb["calibration_gap_pp"] if avgb else None,
            "AVG_global_brier": avgb["brier"] if avgb else None,
            "AVG_global_accuracy": avgb["accuracy"] if avgb else None,
            "QB_global_gap_pp": (e.get("QUARTERBACK_ELO") or {}).get("calibration_gap_pp"),
            "XGB_global_gap_pp": (e.get("XGBOOST") or {}).get("calibration_gap_pp"),
            "dog_slice_AVG_gap_pp": (e.get("dog_slice_AVG") or {}).get("calibration_gap_pp"),
        })
    pl.DataFrame(d12_flat).write_csv(out_dir / "ml_reversal_forensic_d12_global_calibration.csv")
    out["d12_global_calibration"] = d12

    # ============================== D13: statistics & block bootstrap ====
    # (a) two-proportion z-test of discovery-vs-confirmation HIT RATE (corrected
    # math: pooled-proportion standard error, both plain and continuity-corrected);
    # (b) dependence-aware season-week BLOCK bootstrap of the disc-vs-conf
    # difference in BOTH hit rate and ROI, resampling the frozen (season,
    # season_week) blocks within each period, fixed seed, B>=5000.
    import math as _math
    import random as _random
    import numpy as _np
    from math import erf as _erf
    _SQRT2 = _math.sqrt(2.0)

    def _two_prop(n1, w1, n0, w0):
        p1 = w1 / n1; p0 = w0 / n0
        pbar = (w1 + w0) / (n1 + n0)
        if pbar in (0.0, 1.0) or n1 == 0 or n0 == 0:
            return None
        se = _math.sqrt(pbar * (1 - pbar) * (1 / n1 + 1 / n0))
        z = (p1 - p0) / se
        cc = abs(p1 - p0) - 0.5 * (1 / n1 + 1 / n0)
        zc = cc / se if cc > 0 else 0.0
        return {
            "n_disc": n1, "n_conf": n0, "wins_disc": w1, "wins_conf": w0,
            "hr_disc": round(p1, 4), "hr_conf": round(p0, 4), "pooled_hr": round(pbar, 4),
            "diff_hr_disc_minus_conf": round(p1 - p0, 4),
            "z": round(z, 3), "p_two_tail": round(1 - _erf(abs(z) / _SQRT2), 4),
            "z_continuity_corrected": round(zc, 3),
            "p_two_tail_continuity_corrected": round(1 - _erf(abs(zc) / _SQRT2), 4),
        }

    def _block_prep(df: pl.DataFrame):
        """Return (unique blocks, block->row idx, profit np array, win np array)."""
        blk, profs, ws = [], [], []
        for r in df.select(["season", "season_week", "profit", "w"]).to_dicts():
            blk.append((r["season"], r["season_week"]))
            profs.append(r["profit"]); ws.append(r["w"])
        ub = sorted(set(blk))
        idx = {b: [i for i, bk in enumerate(blk) if bk == b] for b in ub}
        return ub, idx, _np.array(profs, dtype=float), _np.array(ws, dtype=float)

    def _blk_roi_hr(prof_arr, win_arr, sel):
        p = prof_arr[sel]; w = win_arr[sel]
        return (float(p.sum()) / len(p), float(w.sum()) / len(w))

    d13 = {}
    for k in ("DOG_AVG", "DOG_CORROB"):
        df = cand[k]
        disc = df.filter(pl.col("season").is_in(DISC))
        conf = df.filter(pl.col("season").is_in(CONF))
        n_d, w_d = disc.height, int((disc["w"] == 1).sum())
        n_c, w_c = conf.height, int((conf["w"] == 1).sum())
        tp = _two_prop(n_d, w_d, n_c, w_c)
        roi_disc = float(disc["profit"].sum()) / n_d if n_d else 0.0
        roi_conf = float(conf["profit"].sum()) / n_c if n_c else 0.0
        obs_diff_hr = w_d / n_d - w_c / n_c
        obs_diff_roi = roi_disc - roi_conf
        ub_d, idx_d, p_d, ww_d = _block_prep(disc)
        ub_c, idx_c, p_c, ww_c = _block_prep(conf)
        B = max(10000, 5000)
        SEED = 42
        rng = _random.Random(SEED)
        hr_diffs, roi_diffs = [], []
        for _ in range(B):
            dd = rng.choices(ub_d, k=len(ub_d))  # block resample within discovery
            cc = rng.choices(ub_c, k=len(ub_c))  # block resample within confirmation
            sel_d = _np.concatenate([_np.asarray(idx_d[b]) for b in dd]) if dd else _np.array([], dtype=int)
            sel_c = _np.concatenate([_np.asarray(idx_c[b]) for b in cc]) if cc else _np.array([], dtype=int)
            rd_d, hd_d = _blk_roi_hr(p_d, ww_d, sel_d)  # returns (ROI, HR)
            rc_c, hc_c = _blk_roi_hr(p_c, ww_c, sel_c)
            hr_diffs.append(hd_d - hc_c); roi_diffs.append(rd_d - rc_c)
        hd = _np.asarray(hr_diffs); rd = _np.asarray(roi_diffs)

        def _boot_summary(x, obs):
            return {
                "resamples": int(len(x)), "seed": SEED,
                "observed_diff": round(obs, 4),
                "boot_mean": round(float(x.mean()), 4),
                "boot_se": round(float(x.std(ddof=1)), 4),
                "ci_2_5": round(float(_np.percentile(x, 2.5)), 4),
                "ci_97_5": round(float(_np.percentile(x, 97.5)), 4),
                "frac_diff_positive": round(float((x > 0).mean()), 4),
            }

        d13[k] = {
            "two_proportion_hit_rate": tp,
            "roi_disc": round(roi_disc, 4), "roi_conf": round(roi_conf, 4),
            "roi_diff_disc_minus_conf": round(obs_diff_roi, 4),
            "block_bootstrap": {
                "metric_units": "difference DISCOVERY minus CONFIRMATION (positive = reversal)",
                "blocks_are": "frozen (season, season_week) blocks per period",
                "n_blocks_disc": len(ub_d), "n_blocks_conf": len(ub_c),
                "B": B, "seed": SEED,
                "diff_hit_rate": _boot_summary(hd, obs_diff_hr),
                "diff_roi": _boot_summary(rd, obs_diff_roi),
            },
        }
    out["d13_statistical_reversal"] = d13

    (out_dir / "ml_reversal_forensic_v1.json").write_text(json.dumps(out, indent=2, default=str))
    print(f"wrote {out_dir / 'ml_reversal_forensic_v1.json'}")


if __name__ == "__main__":
    main()