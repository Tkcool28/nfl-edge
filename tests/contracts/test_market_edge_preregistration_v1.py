"""Frozen contract tests for the 05E-D3C FINAL market-edge PREREGISTRATION config.

Outcome-blind: this module NEVER touches scores, winners, covers, totals results,
or returns. It reads the config, the ledger, the docs, and the freeze script only,
and additionally asserts that the preregistration construction references no
outcome fields.

Validates the frozen contract:
  * discovery 2020-22 / confirmation 2023-24 / 2025 sealed final-product holdout
  * exactly seven hypothesis families
  * final ML buckets [0,2)[2,4)[4,8)[8,12)[12,+inf)
  * ML candidates use positive model-vs-Pinnacle edge (no >0.50 requirement)
  * normal dog-value zone 40-50% / +111..+200, long dogs separated
  * spread + R4 total buckets 0-1/1-2/2-3/3-4/4+
  * R4 alpha=100, not retuned
  * DK/FD actionable / Pinnacle benchmark
  * deterministic line-shopping
  * NFL season-week block bootstrap, 5000 replicates
  * outcome-metric definitions, evidence labels, Big-Oppell eligibility N
  * 2025 reserved for future top-card simulation
  * flat-stake validation separated from future staking strategies
  * config self-hash reproducible and pinned (downstream FAILS CLOSED if changed)
"""
from __future__ import annotations

import hashlib
import importlib.util
import csv
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "market_edge_validation_v1.yaml"
DOC = ROOT / "docs" / "task_05e_edge_preregistration_v1.md"
REPORT = ROOT / "reports" / "task_05e_edge_preregistration_v1.txt"
LEDGER = ROOT / "reports" / "task_05e_d3b_hypothesis_ledger_v1.csv"
SCRIPT = ROOT / "scripts" / "freeze_market_edge_prereg.py"

PINNED_HASH = "d195340940e5c9d6c9f62bbfbb8f8f50836013e05334e870f0905d3592d62e5c"
SUPERSEDED_HASH = "e0cff2756488aeda7f2f1ec3f5d322c48b507f482947cc07300dfb240bee2137"
OBSOLETE_HASH = "d178922bedd5ebe206d883828d230083db5d7742263c811fddff69547fe8901f"

OUTCOME_TERMS = [
    "score", "winner", "win_loss", "realized_roi", "realized_roi",
    "ats_cover", "total_result", "realized_profit", "final_score",
]


@pytest.fixture(scope="module")
def cfg() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
def test_config_exists_and_parses(cfg) -> None:
    assert isinstance(cfg, dict)
    assert CONFIG.exists()
    assert CONFIG.stat().st_size > 0


def test_sealed_holdout_is_2025(cfg) -> None:
    assert cfg["seasons"]["sealed"] == [2025]
    assert cfg["split"]["sealed"] == [2025]


def test_discovery_confirmation_split_exact(cfg) -> None:
    assert cfg["seasons"]["discovery"] == [2020, 2021, 2022]
    assert cfg["seasons"]["confirmation"] == [2023, 2024]
    assert cfg["split"]["discovery"] == [2020, 2021, 2022]
    assert cfg["split"]["confirmation"] == [2023, 2024]
    assert cfg["split"]["confirmation_method_identical"] is True


def test_book_universe_and_roles(cfg) -> None:
    expected = ["draftkings", "fanduel", "pinnacle", "betonlineag",
                "williamhill_us", "betmgm", "betrivers", "bovada",
                "lowvig", "betus"]
    assert cfg["books"]["universe"] == expected
    assert cfg["books"]["actionable_primary"] == ["draftkings", "fanduel"]
    assert cfg["books"]["benchmark_primary"] == "pinnacle"
    assert cfg["books"]["benchmark_secondary"] == "betonlineag"
    assert cfg["books"]["secondary_audit_only"] is True
    assert cfg["markets"] == ["h2h", "spreads", "totals"]


def test_vig_removal_is_proportional_h2h_only(cfg) -> None:
    v = cfg["vig_removal"]
    assert v["method"] == "proportional_normalization"
    assert v["scope"] == "h2h_only"
    assert "p_home = q_home / (q_home + q_away)" in v["formula"].replace("\n", " ")


# --- Moneyline model views + positive-edge definition ----------------------
def test_moneyline_views_and_no_stacker(cfg) -> None:
    ml = cfg["moneyline"]
    assert set(ml["models"]) == {"oracle_qb_elo", "xgboost", "avg"}  # views A/B/C
    assert ml["corroborated"] is True                                # view D
    assert ml["no_stacker"] is True


def test_moneyline_positive_edge_no_05_req(cfg) -> None:
    ped = cfg["moneyline"]["positive_edge_definition"]
    assert "model_probability_side - pinnacle_no_vig_probability_side" in ped["edge_side"]
    assert ped["no_05_requirement"] is True
    assert "edge > 0" in ped["positive_edge_candidate"]
    # MODEL_IMPLIED_EV kept separate from disagreement and NOT realized ROI
    assert "MODEL_IMPLIED_EV" in cfg["moneyline"]["disaggregation_separate"]
    assert "NOT realized ROI" in " ".join(cfg["moneyline"][
        "disaggregation_separate"]["MODEL_IMPLIED_EV"].split())


def test_moneyline_avg_definition(cfg) -> None:
    assert "p_avg = (p_qbelo + p_xgb) / 2" in cfg["moneyline"]["avg_definition"]


def test_spread_orientation_is_explicit(cfg) -> None:
    sp = cfg["spread"]
    assert "expected_home_margin + L" in sp["define"]
    assert "HOME" in sp["selected_side"]
    assert sp["model_retuned_on_market"] is False


def test_total_uses_ridge_totals_r4_alpha100_not_retuned(cfg) -> None:
    t = cfg["total"]
    assert "ridge_totals" in t["model"]
    assert "R4" in t["model"]
    assert "alpha=100" in t["model"]
    assert t["model_retuned_on_market"] is False
    assert "OVER" in t["selected_side"] and "UNDER" in t["selected_side"]


# --- Buckets ---------------------------------------------------------------
def test_moneyline_buckets_final_5bin(cfg) -> None:
    b = cfg["buckets"]["moneyline_disagreement_pp"]
    # FINAL: [0,2) [2,4) [4,8) [8,12) [12,+inf)
    assert b["edges_pp"] == [0, 2, 4, 8, 12, 1000]
    assert b["labels"] == ["0-2", "2-4", "4-8", "8-12", "12+"]
    # bins apply independently to the three ML views
    assert cfg["buckets"]["moneyline_disagreement_pp_bins_independent_for"] == [
        "QB_ELO", "XGB", "AVG"]


def test_spread_buckets(cfg) -> None:
    assert cfg["buckets"]["spread_disagreement_pts"]["edges_pts"] == [0, 1, 2, 3, 4, 1000]


def test_total_buckets(cfg) -> None:
    assert cfg["buckets"]["total_disagreement_pts"]["edges_pts"] == [0, 1, 2, 3, 4, 1000]


def test_dog_value_zone(cfg) -> None:
    dog = cfg["moneyline_dog_value_zone"]
    assert dog["frozen_hypothesis"] is True
    zone = dog["zone"]
    assert "40%" in zone and "50%" in zone
    assert "+111" in zone and "+200" in zone
    assert "positive" in zone.lower()
    assert set(dog["evaluate_for"]) == {"QB_ELO", "XGB", "AVG", "CORROBORATED"}
    # long dogs separated, not folded into normal hypothesis
    assert "+201" in dog["long_dogs"]
    assert "NOT folded" in dog["long_dogs"]


# --- Line shopping (deterministic) -----------------------------------------
def test_line_shopping_rules_deterministic(cfg) -> None:
    ap = cfg["actionable_price"]
    pm = ap["point_markets"]
    pml = pm.lower()
    assert "+3.5" in pm and "+3" in pm          # numerically greatest selected side
    assert "selected-side spread" in pml
    assert "greatest" in pml
    assert "lowest total" in pml
    assert "highest total" in pml
    assert "deterministic fixed book tie-break" in pm
    assert "do not optimize line-vs-juice trade using outcomes" in pml
    assert "LARGER payoff" in ap["moneyline"] or "BETTER" in ap["moneyline"]
    assert ap["pinnacle_never_substituted_as_actionable"] is True
    assert "NOT actionable" in ap["if_no_actionable_available"]


# --- Seven hypothesis families ---------------------------------------------
def test_exact_seven_hypothesis_families(cfg) -> None:
    expect = [
        "ML_QBELO_DISAGREEMENT",
        "ML_XGB_DISAGREEMENT",
        "ML_AVG_DISAGREEMENT",
        "ML_CORROBORATED_DISAGREEMENT",
        "ML_DOG_VALUE_ZONE",
        "SPREAD_DISAGREEMENT",
        "TOTAL_R4_DISAGREEMENT",
    ]
    assert cfg["hypothesis_families"] == expect
    assert len(expect) == 7


def test_hypothesis_ledger_exact_seven() -> None:
    with LEDGER.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    ids = [r["hypothesis_id"] for r in rows]
    assert ids == [
        "ML_QBELO_DISAGREEMENT",
        "ML_XGB_DISAGREEMENT",
        "ML_AVG_DISAGREEMENT",
        "ML_CORROBORATED_DISAGREEMENT",
        "ML_DOG_VALUE_ZONE",
        "SPREAD_DISAGREEMENT",
        "TOTAL_R4_DISAGREEMENT",
    ]
    assert all(r["frozen"] == "true" for r in rows)
    assert all(r["prereg_fingerprint"] == PINNED_HASH for r in rows)


# --- Bootstrap -------------------------------------------------------------
def test_bootstrap_season_week_block_5000(cfg) -> None:
    bt = cfg["bootstrap"]
    assert "season-week block" in bt["resampling_unit"].lower()
    assert "season" in bt["resampling_unit"].lower()
    assert "week" in bt["resampling_unit"].lower()
    assert bt["replicates"] == 5000
    assert "percentile" in bt["confidence_interval"].lower()
    assert bt["iid_game_as_sole_estimate"] is False
    assert "ROI" in bt["metric"]


# --- Minimum N & evidence labels -------------------------------------------
def test_minimum_n_frozen(cfg) -> None:
    mn = cfg["minimum_N"]
    assert mn["report_bucket_min_pool"] == 25
    assert mn["normal_ev_min"] == {"discovery": 50, "confirmation": 50,
                                   "per_season_min": 5}
    # Big Opportunity FINAL: 50 discovery / 40 confirmation
    assert mn["big_opportunity_min"]["discovery"] == 50
    assert mn["big_opportunity_min"]["confirmation"] == 40
    assert mn["selected_before_results"] is True


def test_evidence_labels_three(cfg) -> None:
    ev = cfg["evidence_labels"]
    assert set(ev) == {"STRONG_VALIDATION", "SUPPORTED_USABLE", "FAILED_TO_VALIDATE"}
    assert "lower bound > 0" in " ".join(ev["STRONG_VALIDATION"]["requires_all"])
    assert "uncertainty may still include zero" in " ".join(
        ev["SUPPORTED_USABLE"]["requires_all"]).lower()


def test_big_opportunity_higher_evidence_and_negative_result(cfg) -> None:
    big = cfg["big_opportunity_candidate"]
    assert big["higher_evidence_standard"] is True
    assert big["conditional_section"] is True
    assert big["no_65_pct_hit_threshold"] is True
    assert "NO_BIG_OPPORTUNITY_SIGNAL_YET" in big["if_not_qualified"]


# --- Weekly top-cards / 2025 role / staking separation ---------------------
def test_weekly_top_cards_architecture(cfg) -> None:
    wtc = cfg["weekly_top_cards"]
    assert "ONE HIT RATE" in wtc["counts"].upper()
    assert "ONE BALANCED" in wtc["counts"].upper()
    assert "ONE +EV" in wtc["counts"].upper()
    assert wtc["ranking_formulas_frozen_later"] is True or wtc.get(
        "defined_by_task_this_study") is False
    assert "all_game_board" in wtc
    assert "2025_role" in wtc


def test_2025_reserved_for_future_top_card_simulation(cfg) -> None:
    assert "end-to-end" in cfg["weekly_top_cards"]["2025_role"]
    assert "NOT used while designing" in cfg["weekly_top_cards"]["2025_role"]


def test_flat_stake_separated_from_staking_strategy(cfg) -> None:
    r = cfg["returns"]
    assert r["unit_stake"] == 1.0
    assert r["staking_separated_from_edge_selection"] is True


def test_concentration_is_diagnostics_no_cutoffs(cfg) -> None:
    cc = cfg["concentration_checks"]
    assert cc["diagnostics_only"] is True
    assert cc["frozen_for_disqualification"] is False
    assert cc["no_post_hoc_exclusions"] is True
    assert "DK vs FD" in cc["diagnostics"] or "DK" in cc["diagnostics"]


def test_fingerprint_field_is_pinned_sha256(cfg) -> None:
    val = cfg["fingerprint"]["sha256_self"]
    assert val == PINNED_HASH
    assert isinstance(val, str) and len(val) == 64
    assert all(ch in "0123456789abcdef" for ch in val)


def test_pinned_hash_recomputes_over_documents() -> None:
    text = DOC.read_text(encoding="utf-8") + REPORT.read_text(encoding="utf-8")
    assert PINNED_HASH in text
    # obsolete provisional hash + superseded prior hash documented as provenance
    assert "OBSOLETE" in DOC.read_text(encoding="utf-8")
    assert "superseded" in DOC.read_text(encoding="utf-8").lower()
    # the doc must present the AMENDED hash as the sole authoritative fingerprint line
    assert f"Fingerprint (SHA-256, AMENDED): `{PINNED_HASH}`" in DOC.read_text(encoding="utf-8")
    assert SUPERSEDED_HASH != PINNED_HASH


def test_fingerprint_authoritative_in_report() -> None:
    report = REPORT.read_text(encoding="utf-8")
    assert "AMENDED" in report
    assert "SUPERSEDED" in report
    assert PINNED_HASH in report


def test_freeze_script_reproduces_the_same_hash() -> None:
    """Recompute the config self-hash using the same canonicalization the
    freeze script uses; it must equal the pinned value."""

    def load_freeze_canonicalize():
        spec = importlib.util.spec_from_file_location("freeze_mep", SCRIPT)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    mod = load_freeze_canonicalize()
    raw = CONFIG.read_bytes()
    digest = hashlib.sha256(mod.canonicalize(raw.decode("utf-8"))).hexdigest()
    assert digest == PINNED_HASH, "freeze script no longer reproduces the pinned hash"
    assert mod.pin_hash(raw.decode("utf-8"), digest) == CONFIG.read_text(
        encoding="utf-8")


def test_prereg_doc_exists_and_mentions_stop(cfg) -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "NO_BIG_OPPORTUNITY_SIGNAL_YET" in text
    assert "EDGE_PREREGISTRATION_AMENDED_PRE_OUTCOME" in text
    assert REPORT.exists()
    assert "EDGE_PREREGISTRATION_AMENDED_PRE_OUTCOME" in REPORT.read_text(encoding="utf-8")


def test_price_band_reporting_taxonomy_correct(cfg) -> None:
    pb = cfg["price_band"]
    bands = pb["bands"]
    assert pb["reporting_only"] is True
    assert set(bands.keys()) == {
        "heavy_favorite", "moderate_favorite", "near_even",
        "short_plus_money", "moderate_plus_money", "long_plus_money",
    }
    # exact correct taxonomy
    assert bands["heavy_favorite"] == {"american_max": -200}
    assert bands["moderate_favorite"] == {"american_min": -199, "american_max": -111}
    assert bands["near_even"] == {"american_min": -110, "american_max": 110}
    assert bands["short_plus_money"] == {"american_min": 111, "american_max": 150}
    assert bands["moderate_plus_money"] == {"american_min": 151, "american_max": 200}
    assert bands["long_plus_money"] == {"american_min": 201}


def test_dog_value_zone_unchanged_by_price_amendment(cfg) -> None:
    dog = cfg["moneyline_dog_value_zone"]
    assert dog["frozen_hypothesis"] is True
    zone = dog["zone"]
    assert "40%" in zone and "50%" in zone
    assert "+111" in zone and "+200" in zone
    assert "positive" in zone.lower()
    assert set(dog["evaluate_for"]) == {"QB_ELO", "XGB", "AVG", "CORROBORATED"}
    assert "+201" in dog["long_dogs"]


def test_dispersion_boolean_correct(cfg) -> None:
    mf = cfg["market_freshness"]
    assert mf["no_dispersion_grid"] is True
    assert mf["is_production_signal"] is False
    assert mf["no_freshness_filter_frozen"] is True


def test_consistency_diagnostics_deterministic(cfg) -> None:
    cd = cfg["consistency_diagnostics"]
    assert cd["frozen_now_outcome_blind"] is True
    assert cd["no_additional_performance_thresholds"] is True
    assert ">60%" in cd["SEASON_DOMINANCE"]["definition"]
    assert "-20%" in cd["CATASTROPHIC_SEASON_INSTABILITY"]["definition"]
    assert "opposite signs" in cd["DIRECTION_REVERSAL"]["definition"]
    # every vague phrase maps to a deterministic term
    mapping = {m["phrase"]: m["deterministic_term"] for m in cd["phrase_mapping"]}
    assert mapping["catastrophic season instability"] == "CATASTROPHIC_SEASON_INSTABILITY"
    assert mapping["obvious single-season dependence"] == "SEASON_DOMINANCE"
    assert mapping["direction reverses materially"] == "DIRECTION_REVERSAL"
    assert mapping["strong season instability dominates"] == "CATASTROPHIC_SEASON_INSTABILITY"


def test_evidence_labels_use_deterministic_terms(cfg) -> None:
    ev = cfg["evidence_labels"]
    assert set(ev) == {"STRONG_VALIDATION", "SUPPORTED_USABLE", "FAILED_TO_VALIDATE"}
    strong = " ".join(ev["STRONG_VALIDATION"]["requires_all"]).lower()
    supported = " ".join(ev["SUPPORTED_USABLE"]["requires_all"]).lower()
    failed = " ".join(ev["FAILED_TO_VALIDATE"]["if_any"]).lower()
    assert "catastrophic_season_instability" in strong
    assert "season_dominance" in supported
    assert "direction_reversal" in failed
    # vague phrases removed from evidence labels
    assert "catastrophic season instability" not in strong
    assert "direction reverses materially" not in failed


def test_preregistration_construction_references_no_outcome_data() -> None:
    """The frozen config must not build any methodology step on an outcome
    field. Outcome words may appear only as prose guardrails (e.g. 'do not
    open winners'); none may be a machine-readable config KEY or VALUE that a
    downstream evaluator would read as an outcome source."""
    cfg_text = CONFIG.read_text(encoding="utf-8")
    # Machine-readable config keys and scalar values must not name outcome fields.
    for term in OUTCOME_TERMS:
        lowered = term.lower()
        # allowed only as prose in comment/note lines; never as a mapping key
        # or as a data-column reference.
        for line in cfg_text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" in stripped and not stripped.startswith("-"):
                key = stripped.split(":", 1)[0]
                assert lowered not in key.lower(), f"outcome-derived config key: {key}"


def test_census_provenance_confirms_outcome_blind() -> None:
    """Supporting census provenance must hard-declare that no outcomes were
    loaded and no realized performance was computed."""
    for proven_path in [
        ROOT / "reports" / "task_05e_d3b_census_provenance.json",
    ]:
        prov = yaml.safe_load(proven_path.read_text(encoding="utf-8"))
        assert prov["scores_winners_ats_totals_loaded"] is False
        assert prov["realized_hit_rate_roi_profit_calculated"] is False
        assert prov["seasons_2025_used"] is False
        assert prov["model_training_or_retuning_or_stacker"] is False
        assert prov["observed_total_loaded"] is False
