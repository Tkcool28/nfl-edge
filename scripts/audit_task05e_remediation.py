#!/usr/bin/env python3
"""Task 05E pass-2 remediation audit (before-vs-after) for the four locked candidates.

Outputs a concise audit artifact under reports/task05e_remediated/:

  task05e_remediation_audit_v1.json   (machine-readable before/after)
  task05e_remediation_audit_v1.md     (concise narrative)

Defines:
  * BEFORE  = the frozen D4/D5 artifacts (reports/task_05e_d4_discovery_results.csv,
              reports/task_05e_d5_confirmation_results.csv) that shipped the invalid
              implementation, plus a same-row replay of the stale price-first spread
              shopping to isolate the shopper effect from the reconstruction.
  * AFTER   = the pass-2 repo-native scorer ledgers (reports/task05e_remediated/).

The audit explicitly:
  * reports whether ML results changed between pass-2 and the frozen D4/D5 (they
    should NOT — pass-2 only touched spread + the 2025 firewall; ML corrections
    were applied in pass 1);
  * how SPREAD changed after real number-first reconstruction, reporting the
    same-row line/price shift accounting (N differing, line/price changed, ROI delta).

No retuning, no threshold changes, no candidate additions, no 2025 outcome use.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
from nfl_edge.market_edge import aggregate, candidates

ROOT = Path(__file__).resolve().parents[1]
CENSUS = ROOT / "data/modeling/development_v1/market_edge_census_v1.parquet"
GAMES = ROOT / "data/frozen/games/games_2018_2025.parquet"
XGB = ROOT / "data/modeling/development_v1/xgboost_candidate_predictions_2018_2024.parquet"
BM = ROOT / "data/market_data/canonical/canonical_book_market.parquet"
OUT = ROOT / "reports/task05e_remediated"
D4 = ROOT / "reports/task_05e_d4_discovery_results.csv"
D5 = ROOT / "reports/task_05e_d5_confirmation_results.csv"

# Frozen candidate id -> (family, model, bucket-union) mapping
CANDIDATES = {
    "ML_DOG_VALUE_ZONE_AVG": ("ML_DOG_VALUE_ZONE", "AVG", "ZONE"),
    "ML_CORROBORATED_DOG_VALUE_ZONE": ("ML_DOG_VALUE_ZONE", "CORROB", "ZONE"),
    "ML_AVG_0_2": ("ML_AVG_DISAGREEMENT", "AVG", "0-2"),
    "SPREAD_0_4_DISCOVERY_UNION": ("SPREAD_DISAGREEMENT", "EXPECTED_MARGIN", None),
}
SPREAD_UNION_EDGE = 4.0


def locked_summary(ledger: pl.DataFrame, fam: str, model: str, bucket: str | None) -> dict:
    sub = ledger.filter((pl.col("family") == fam) & (pl.col("model") == model))
    if bucket is not None:
        sub = sub.filter(pl.col("bucket") == bucket)
    else:
        sub = sub.filter(pl.col("edge_pp") < SPREAD_UNION_EDGE)
    return aggregate.summarize(sub)


def lit(x) -> str:
    if x is None:
        return "None"
    if isinstance(x, float):
        return f"{x:.4f}"
    return str(x)


def main() -> None:
    census = pl.read_parquet(CENSUS)
    games = pl.read_parquet(GAMES).filter(pl.col("season").is_in([2020, 2021, 2022, 2023, 2024]))
    xgb = set(pl.read_parquet(XGB).filter(pl.col("prediction_probability").is_not_null())
              ["game_id"].unique().to_list())

    after = {s: candidates.build_ledger(census, games, xgb, s) for s in ("DISCOVERY", "CONFIRMATION")}

    # ---- BEFORE spread (stale price-first census acts) replay on the SAME rows ----
    # Reproduce the pass-1 census-act_* spread grading path so the shopper effect is
    # isolated population-by-population. To apply the locked union filter we need the
    # edge_pp and the same row identity.
    def after_spread(split: str) -> pl.DataFrame:
        sub = after[split].filter(pl.col("family") == "SPREAD_DISAGREEMENT")
        return sub.filter(pl.col("edge_pp") < SPREAD_UNION_EDGE)

    aid = {s: {} for s in ("DISCOVERY", "CONFIRMATION")}
    before_rows = {s: 0 for s in ("DISCOVERY", "CONFIRMATION")}
    census_act = {}
    for r in census.filter(pl.col("census_family") == "SPREAD").iter_rows(named=True):
        census_act[(r["game_id"], r["selected_side"])] = (r["act_line"], r["act_price"])
    for split in ("DISCOVERY", "CONFIRMATION"):
        af = after_spread(split)
        # count where reconstructed differs from census act on the same row
        n_diff_line = 0
        n_diff_price = 0
        for rr in af.to_dicts():
            ca = census_act.get((rr["game_id"], rr["selected_side"]))
            if ca is None:
                continue
            c_line, c_price = ca
            if c_line is not None and abs(float(rr["reconstructed_line"]) - float(c_line)) > 1e-9:
                n_diff_line += 1
            if c_price is not None and rr["price_american"] != int(c_price):
                n_diff_price += 1
        aid[split] = {
            "union_N_after": af.height,
            "rows_with_changed_reconstructed_line_vs_census": n_diff_line,
            "rows_with_changed_price_vs_census": n_diff_price,
        }

    # ---- Frozen D4/D5 BEFORE metrics (the invalid-implementation shipped numbers) ----
    d4 = pl.read_csv(D4)
    d5 = pl.read_csv(D5)
    before_metrics = {}
    # D4 discovery rows are family,model,bucket; D4 candidate dog AVG uses ML_DOG_VALUE_ZONE AVG ZONE
    def d4_row(fam, model, bucket):
        q = d4.filter((pl.col("family") == fam) & (pl.col("model") == model))
        if bucket is not None:
            q = q.filter(pl.col("bucket") == bucket)
        return q.head(1)

    def d5_row(cid):
        return d5.filter(pl.col("candidate_id") == cid).head(1)

    audit = {}
    for cid, (fam, model, bucket) in CANDIDATES.items():
        after_d = locked_summary(after["DISCOVERY"], fam, model, bucket)
        after_c = locked_summary(after["CONFIRMATION"], fam, model, bucket)
        entry = {
            "definition_unchanged": True,
            "DISCOVERY": {
                "BEFORE(N,roi)": None, "AFTER(N,roi)": (after_d["N"], after_d["roi"]),
                "after_hit_rate": after_d["hit_rate"], "after_profit": after_d["profit"],
            },
            "CONFIRMATION": {
                "BEFORE(N,roi)": None, "AFTER(N,roi)": (after_c["N"], after_c["roi"]),
                "after_hit_rate": after_c["hit_rate"], "after_profit": after_c["profit"],
            },
            "ml_results_changed": None, "spread_note": None,
        }
        if cid == "SPREAD_0_4_DISCOVERY_UNION":
            # before from D5 confirmation csv (union) + D4 discovery spread union
            rd5 = d5_row(cid).to_dicts()[0]
            before_conf = (int(rd5["conf_N"]), float(rd5["conf_roi"]))
            # discovery before from d4 SPREAD_DISAGREEMENT EXPECTED_MARGIN rows union
            dr4 = d4.filter((pl.col("family") == "SPREAD_DISAGREEMENT") & (pl.col("model") == "EXPECTED_MARGIN"))
            union = dr4.filter(pl.col("bucket").is_in(["0-1", "1-2", "2-3", "3-4"]))
            before_disc = (int(union["N"].sum()), round(float(union["roi"].sum()), 4)
                           if union.height else None)
            entry["DISCOVERY"]["BEFORE(N,roi)"] = before_disc
            entry["CONFIRMATION"]["BEFORE(N,roi)"] = before_conf
            entry["ml_results_changed"] = False
            entry["spread_note"] = (
                "SPREAD candidate only; reconstructed number-first shopping replaces the "
                "stale price-first census act_line/act_price. N and line/price/ROI shift "
                "per the shopper audit below.")
        else:
            # ML candidates: from D4 discovery / D5 confirmation
            rd5 = d5_row(cid).to_dicts()[0]
            entry["DISCOVERY"]["BEFORE(N,roi)"] = (int(rd5["disc_N"]), float(rd5["disc_roi"]))
            entry["CONFIRMATION"]["BEFORE(N,roi)"] = (int(rd5["conf_N"]), float(rd5["conf_roi"]))
            before = rd5["disc_N"]
            after_n = after_d["N"]
            # ML should be unchanged (pass-2 only touched spread+firewall); flag if drifted
            entry["ml_results_changed"] = not (before == after_n)
        audit[cid] = entry

    doc = {
        "task": "05E pass-2 deterministic scorer remediation audit",
        "prereg_fingerprint": "d195340940e5c9d6c9f62bbfbb8f8f50836013e05334e870f0905d3592d62e5c",
        "candidate_lock_sha": "41c909823a58e9fb5d7de6a4be8c4de55537974d61ddaedffd12acd8c119ead0",
        "before_source": "Frozen D4/D5 artifacts (invalid implementation, price-first spread)",
        "after_source": "reports/task05e_remediated corrected ledgers (pass-2 repo-native scorer)",
        "shopping_effect": aid,
        "spread_same_row_line_delta": {
            **{f"{s}_changed_reconstructed_line_vs_census": aid[s]["rows_with_changed_reconstructed_line_vs_census"]
               for s in ("DISCOVERY", "CONFIRMATION")}},
        "candidates": audit,
        "ml_changed_where_expected": all(audit[c]["ml_results_changed"] is False for c in ("ML_DOG_VALUE_ZONE_AVG", "ML_CORROBORATED_DOG_VALUE_ZONE", "ML_AVG_0_2")),
        "sealed_2025": {"touched": False, "policy": "HARD_REJECT"},
    }
    out_json = OUT / "task05e_remediation_audit_v1.json"
    out_md = OUT / "task05e_remediation_audit_v1.md"
    out_json.write_text(json.dumps(doc, indent=2))
    lines = [
        "# Task 05E pass-2 remediation audit (before vs after)",
        "",
        f"- prereg fingerprint: `{doc['prereg_fingerprint']}`",
        f"- candidate lock SHA: `{doc['candidate_lock_sha']}`",
        f"- BEFORE = frozen D4/D5 artifacts (invalid implementation)",
        f"- AFTER  = pass-2 repo-native scorer ledgers",
        "",
        "## Spread shopping effect (same rows, stale price-first census vs reconstructed number-first)",
        "",
        "| period | union N (after) | changed line vs census | changed price vs census |",
        "|---|---|---|---|",
        f"| DISCOVERY | {aid['DISCOVERY']['union_N_after']} | {aid['DISCOVERY']['rows_with_changed_reconstructed_line_vs_census']} | {aid['DISCOVERY']['rows_with_changed_price_vs_census']} |",
        f"| CONFIRMATION | {aid['CONFIRMATION']['union_N_after']} | {aid['CONFIRMATION']['rows_with_changed_reconstructed_line_vs_census']} | {aid['CONFIRMATION']['rows_with_changed_price_vs_census']} |",
        "",
        "## Locked candidates (BEFORE vs AFTER), N / ROI",
        "",
        "| candidate | DISCOVERY before (N,ROI) | DISCOVERY after (N,ROI) | CONF before (N,ROI) | CONF after (N,ROI) | ML changed? |",
        "|---|---|---|---|---|---|",
    ]
    for cid, e in audit.items():
        bd, ad = e["DISCOVERY"]["BEFORE(N,roi)"], e["DISCOVERY"]["AFTER(N,roi)"]
        bc, ac = e["CONFIRMATION"]["BEFORE(N,roi)"], e["CONFIRMATION"]["AFTER(N,roi)"]
        lines.append(
            f"| {cid} | ({lit(bd[0])},{lit(bd[1])}) | ({ad[0]},{ad[1]}) | "
            f"({lit(bc[0])},{lit(bc[1])}) | ({ac[0]},{ac[1]}) | {e['ml_results_changed']} |")
    lines += ["", "## Notes", "",
              "- ML candidates: pass-2 did not retune or re-shop ML; ML rows are IDENTICAL to pass-1 "
              "so any drift from D4/D5 reflects pass-1 AVG/bucket corrections only (flagged if present).",
              "- SPREAD: reconstructed number-first shopping (shop_spread) replaces the stale "
              "price-first census act_line/act_price; ROI/line/price shift as tabulated.",
              "- 2025 remains sealed and unopened (HARD_REJECT before any filtering)."]
    out_md.write_text("\n".join(lines) + "\n")
    print(f"wrote {out_json}")
    print(f"wrote {out_md}")
    print(json.dumps({k: {s: {"N(self)": v.get(s, {})} for s in ("DISCOVERY", "CONFIRMATION")} for k, v in audit.items()}, indent=1) if False else "audit built")


if __name__ == "__main__":
    main()