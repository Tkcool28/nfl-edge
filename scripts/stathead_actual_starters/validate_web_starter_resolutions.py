#!/usr/bin/env python3
"""Validate web-researched starter resolutions and deterministically generate v1 + v2 ledgers.

v1 = general resolution of all 99 researched exception game-sides.
v2 = v1 with the single Kendall Hinton semantic special-case applied
     (SPECIAL_CASE_KENDALL_HINTON_IDENTITY_RESOLVED), regenerated deterministically.

Identity mapping uses the repository-contained nflverse crosswalk subset.
"""
import csv
import hashlib
import json
import re
from pathlib import Path

import pandas as pd

R = Path(__file__).resolve().parents[2]
OUT = R / "data/derived/stathead_actual_starters_v1" / "manual_starter_review"
X = R / "data/derived/stathead_actual_starters_v1" / "identity_crosswalk" / "task04a_player_crosswalk_v1.csv"
SUBSET_SHA = "d554c7c2ab5114bc70d0f04a46feba0ef46ab53c717769f8c04f88b98e976742"
SUBSET_ROWS = 138

# Committed Kendall Hinton special-case evidence (fixes BOTH pfr/gsis and status).
KENDALL_HINTON = {
    "game_id": "2020_12_NO_DEN",
    "team_side": "home",
    "canonical_team": "DEN",
    "actual_starting_qb_name": "Kendall Hinton",
    "actual_starting_qb_pfr_id": "HintKe00",
    "actual_starting_qb_gsis_id": "00-0035864",
    "original_exception_type": "ZERO_CANDIDATE",
    "starter_evidence_class": "POSTGAME_ACTUAL_STARTER",
    "historical_model_usage": "ORACLE_STARTER_IDENTITY_ONLY",
    "identity_mapping_status": "SPECIAL_CASE_KENDALL_HINTON_IDENTITY_RESOLVED",
    "source_locator_note": (
        "Denver Broncos official postgame recap, Under extreme circumstances, "
        "Vic Fangio proud of Broncos fight in loss to Saints (2020-11-29); "
        "NFL.com QB Index noting no official QB start; PFR /players/H/HintKe00.htm"
    ),
    "notes": ("Denver opened with direct-snap Wildcat plays and official recordkeepers "
              "did not credit a QB start. Kendall Hinton served as Denver emergency/"
              "makeshift quarterback for the game. Identity assigned for canonical "
              "historical QB-role coverage; not represented as an official statistical "
              "QB start."),
}


def sh(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).split()


def same(a, b):
    return norm(a) == norm(b) or norm(a) == list(reversed(norm(b)))


def _count(rows, pred):
    return sum(1 for x in rows if pred(x))


def main(R_=R):
    out_dir = R_ / "data/derived/stathead_actual_starters_v1" / "manual_starter_review"
    xw = (R_ / "data/derived/stathead_actual_starters_v1" / "identity_crosswalk"
          / "task04a_player_crosswalk_v1.csv")
    rs = list(csv.DictReader(open(out_dir / "web_researched_starter_name_map_v1.csv")))
    es = list(csv.DictReader(open(out_dir / "exception_game_sides.csv")))
    rk = {(x["game_id"], x["team_side"]): x for x in rs}
    ek = {(x["game_id"], x["team_side"]): x for x in es}
    assert len(rs) == len(rk) == 99 and set(rk) == set(ek)

    d = pd.read_csv(xw, dtype=str)
    assert len(d) == SUBSET_ROWS and sh(xw) == SUBSET_SHA, "crosswalk subset mismatch"

    audit = []
    out = []
    for k, r in rk.items():
        e = ek[k]
        name = r["researched_actual_starting_qb_name"]
        pfr = gsis = ""
        status = "IDENTITY_UNRESOLVED"
        etype = e["exception_type"]
        if etype == "MULTIPLE_CANDIDATES":
            cand = list(zip(e["candidate_names"].split("|"), e["candidate_pfr_ids"].split("|")))
            exact = [z for z in cand if z[0] == name]
            form = []
            for cn, cp in cand:
                h = d[d.pfr_id == cp]
                cw = h.display_name.iloc[0] if len(h) == 1 else ""
                if not exact and len(h) == 1 and same(name, cw) and same(cn, cw):
                    form.append((cn, cp, cw))
            pick = exact[0] if len(exact) == 1 else (form[0][:2] if len(form) == 1 else None)
            for cn, cp in cand:
                h = d[d.pfr_id == cp]
                cw = h.display_name.iloc[0] if len(h) == 1 else ""
                if cn == name:
                    cs = "EXACT_NAME_MATCH"
                elif any(cp == z[1] for z in form):
                    cs = "NAME_FORM_MISMATCH_WITH_UNIQUE_PFR_ID"
                else:
                    cs = "TRUE_IDENTITY_MISMATCH"
                if cs == "EXACT_NAME_MATCH":
                    basis = "EXACT_STRING"
                elif cs.startswith("NAME_FORM"):
                    basis = "PFR_ID_CONFIRMED_LAST_FIRST_INVERSION"
                else:
                    basis = "UNRESOLVED"
                audit.append({
                    "game_id": k[0], "team_side": k[1], "canonical_team": r["canonical_team"],
                    "researched_name": name, "raw_candidate_name": cn, "candidate_pfr_id": cp,
                    "crosswalk_name": cw, "comparison_status": cs,
                    "resolution_basis": basis, "notes": r["notes"],
                })
            if pick:
                pfr = pick[1]
                h = d[d.pfr_id == pfr]
                gsis = h.gsis_id.iloc[0] if len(h) == 1 else ""
                if exact:
                    status = "EXISTING_STATHEAD_PFR_AND_GSIS_RESOLVED"
                else:
                    status = "PFR_CONFIRMED_NAME_FORM_VARIANT_AND_GSIS_RESOLVED"
        else:
            h = d[(d.display_name == name) & (d.position == "QB")][["pfr_id", "gsis_id"]].drop_duplicates()
            if len(h) == 1 and pd.notna(h.pfr_id.iloc[0]):
                pfr = h.pfr_id.iloc[0]
                gsis = h.gsis_id.iloc[0]
                status = "NFLVERSE_EXACT_NAME_PFR_AND_GSIS_RESOLVED"
        out.append({
            "game_id": k[0], "team_side": k[1], "canonical_team": r["canonical_team"],
            "actual_starting_qb_name": name, "actual_starting_qb_pfr_id": pfr,
            "actual_starting_qb_gsis_id": gsis, "original_exception_type": etype,
            "starter_evidence_class": "POSTGAME_ACTUAL_STARTER",
            "historical_model_usage": "ORACLE_STARTER_IDENTITY_ONLY",
            "identity_mapping_status": status, "source_locator_note": r["source_locator_note"],
            "notes": r["notes"],
        })

    def wr(n, rows, lineterminator="\r\n"):
        with (out_dir / n).open("w", newline="") as f:
            writer = csv.DictWriter(f, rows[0], lineterminator=lineterminator)
            writer.writeheader()
            writer.writerows(rows)

    wr("multi_candidate_name_form_audit_v1.csv", audit)
    wr("web_researched_starter_resolutions_v1.csv", out)

    multi = _count(out, lambda x: x["original_exception_type"] == "MULTIPLE_CANDIDATES")
    zero = _count(out, lambda x: x["original_exception_type"] == "ZERO_CANDIDATE")
    multi_unres = _count(
        out,
        lambda x: x["original_exception_type"] == "MULTIPLE_CANDIDATES" and not x["actual_starting_qb_pfr_id"],
    )
    zero_unres = _count(
        out,
        lambda x: x["original_exception_type"] == "ZERO_CANDIDATE" and not x["actual_starting_qb_pfr_id"],
    )
    pfr_res = _count(out, lambda x: bool(x["actual_starting_qb_pfr_id"]))
    gsis_res = _count(out, lambda x: bool(x["actual_starting_qb_gsis_id"]))
    rep = {
        "research_rows": 99,
        "exception_keys_matched": 99,
        "multi_candidate_rows": multi,
        "multi_exact_name_matches": _count(audit, lambda x: x["comparison_status"] == "EXACT_NAME_MATCH"),
        "multi_name_form_mismatches": _count(audit, lambda x: x["comparison_status"].startswith("NAME_FORM")),
        "multi_name_form_resolved": _count(
            out, lambda x: x["identity_mapping_status"].startswith("PFR_CONFIRMED")
        ),
        "multi_true_identity_mismatches": _count(
            audit, lambda x: x["comparison_status"] == "TRUE_IDENTITY_MISMATCH"
        ),
        "multi_unresolved": multi_unres,
        "zero_candidate_rows": zero,
        "zero_exact_name_resolved": _count(
            out,
            lambda x: x["original_exception_type"] == "ZERO_CANDIDATE" and bool(x["actual_starting_qb_pfr_id"]),
        ),
        "zero_name_form_resolved": 0,
        "zero_unresolved": zero_unres,
        "pfr_resolved": pfr_res,
        "pfr_unresolved": 99 - pfr_res,
        "gsis_resolved": gsis_res,
        "gsis_unresolved": 99 - gsis_res,
        "exact_unresolved_game_side_keys": [
            f"{x['game_id']}:{x['team_side']}" for x in out if not x["actual_starting_qb_pfr_id"]
        ],
        "crosswalk_sha256": sh(xw),
        "output_sha256": {
            "audit": sh(out_dir / "multi_candidate_name_form_audit_v1.csv"),
            "ledger": sh(out_dir / "web_researched_starter_resolutions_v1.csv"),
        },
    }
    (out_dir / "web_researched_starter_resolution_report.json").write_text(
        json.dumps(rep, indent=2) + "\n"
    )

    # ---- v2 = v1 with Kendall Hinton special-case (LF to match committed artifact) ----
    out2 = []
    for row in out:
        if row["game_id"] == "2020_12_NO_DEN" and row["team_side"] == "home":
            row2 = dict(row)
            row2.update({k: v for k, v in KENDALL_HINTON.items() if k in row})
            out2.append(row2)
        else:
            out2.append(row)
    assert len(out2) == 99
    wr("web_researched_starter_resolutions_v2.csv", out2, lineterminator="\n")

    special = [x for x in out2 if x["identity_mapping_status"].startswith("SPECIAL")]
    rep2 = {
        "research_rows": 99,
        "resolved_pfr": _count(out2, lambda x: bool(x["actual_starting_qb_pfr_id"])),
        "unresolved_pfr": _count(out2, lambda x: not x["actual_starting_qb_pfr_id"]),
        "resolved_gsis": _count(out2, lambda x: bool(x["actual_starting_qb_gsis_id"])),
        "unresolved_gsis": _count(out2, lambda x: not x["actual_starting_qb_gsis_id"]),
        "special_semantic_exceptions": len(special),
        "special_semantic_exception_keys": [
            f"{x['game_id']}:{x['team_side']}" for x in special
        ],
        "kendall_hinton": {
            "pfr_id": "HintKe00", "gsis_id": "00-0035864",
            "official_statistical_qb_start_credit": "NONE",
            "source_notes": KENDALL_HINTON["source_locator_note"],
        },
        "output_sha256": {
            "web_researched_starter_resolutions_v2.csv": sh(
                out_dir / "web_researched_starter_resolutions_v2.csv"
            )
        },
    }
    (out_dir / "web_researched_starter_resolution_report_v2.json").write_text(
        json.dumps(rep2, indent=2) + "\n"
    )

    # fail-closed: v2 hash must match the frozen committed value
    assert sh(out_dir / "web_researched_starter_resolutions_v2.csv") == (
        "333a399288bda0405e6e8c10ac391740b681cf2de9b55ecc87afe60222df022d"
    ), "v2 ledger hash mismatch"


if __name__ == "__main__":
    main()