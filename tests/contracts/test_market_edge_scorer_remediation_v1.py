"""Contract/unit tests for the Task 05E corrective scorer (SCORER_REMEDIATION).

Covers the ten required gates:

  1. AVG is null/missing when either constituent (QB-Elo or XGBoost) is missing
  2. row-level side/winner grading
  3. home/away inversion
  4. ML profit math (win=decimal-1, loss=-1, push=0)
  5. spread best-number-first shopping, then better price, then tie-break
  6. push zero profit (spread/total)
  7. exact dog zone 0.40 <= p < 0.50 AND +111 <= price <= +200
  8. AVG 0-2 exact raw bucket
  9. 2025 absent (sealed)
 10. the SAME scorer function builds both the discovery and confirmation ledgers

Also verifies the prereg fingerprint and candidate-lock hash before any grading.
"""
from __future__ import annotations

from pathlib import Path
import json

import polars as pl
import pytest

from nfl_edge.market_edge import scoring, shopping, candidates
from nfl_edge.market_edge import config as cfgmod
from nfl_edge.market_edge import provenance as provmod

ROOT = Path(__file__).resolve().parents[2]
CENSUS = ROOT / "data/modeling/development_v1/market_edge_census_v1.parquet"
GAMES = ROOT / "data/frozen/games/games_2018_2025.parquet"
XGB = ROOT / "data/modeling/development_v1/xgboost_candidate_predictions_2018_2024.parquet"
CFG = ROOT / "config/market_edge_validation_v1.yaml"
LOCK = ROOT / "reports/task_05e_d5_candidate_lock.json"

# --------------------------------------------------------------------------
# Gate 0: fingerprint + lock verified before grading
# --------------------------------------------------------------------------

def test_prereq_fingerprint_pinned() -> None:
    cfgmod.load_pinned_config(CFG)  # raises if fingerprint mismatch


def test_candidate_lock_hash_pinned() -> None:
    provmod.verify_lock_hash(LOCK)  # raises if canonical lock hash mismatch


# --------------------------------------------------------------------------
# Gates 2-4, 6: pure grading function behavior
# --------------------------------------------------------------------------

def test_amer_to_decimal() -> None:
    assert scoring.american_to_decimal(150) == 2.5
    assert scoring.american_to_decimal(-110) == pytest.approx(1.9090909)
    assert scoring.american_to_decimal(None) is None
    assert scoring.american_to_decimal(0) is None


def test_moneyline_win_loss_push() -> None:
    assert scoring.moneyline_grading("home", 24, 20, 2.4) == (1, 0, 1.4)
    assert scoring.moneyline_grading("away", 20, 24, 2.2) == (1, 0, 1.2)
    assert scoring.moneyline_grading("home", 20, 24, 2.2) == (0, 0, -1.0)
    assert scoring.moneyline_grading("away", 24, 20, 2.2) == (0, 0, -1.0)
    assert scoring.moneyline_grading("home", 21, 21, 2.5) == (0, 1, 0.0)  # tie -> push


def test_home_away_inversion() -> None:
    # identical margin flips winner by side
    assert scoring.moneyline_grading("home", 30, 27, 2.0)[0] == 1
    assert scoring.moneyline_grading("away", 30, 27, 2.0)[0] == 0
    h = scoring.moneyline_grading("home", 27, 30, 2.0)
    a = scoring.moneyline_grading("away", 30, 27, 2.0)
    assert h == a  # same outcome when the favored side is flipped identically


def test_ml_profit_math() -> None:
    w, p, pr = scoring.moneyline_grading("home", 28, 20, 3.5)
    assert w == 1 and p == 0 and pr == pytest.approx(2.5)  # decimal - 1
    w, p, pr = scoring.moneyline_grading("home", 20, 28, 2.5)
    assert w == 0 and p == 0 and pr == -1.0
    w, p, pr = scoring.moneyline_grading("home", 28, 28, 2.5)
    assert w == 0 and p == 1 and pr == 0.0  # push -> zero profit


def test_spread_grading_and_push_zero() -> None:
    # home -3.5 covers when home wins by 4+
    assert scoring.spread_grading("home", 27, 20, -3.5, 1.952381) == (1, 0, pytest.approx(0.952381))
    assert scoring.spread_grading("home", 23, 20, -3.5, 1.952381) == (0, 0, -1.0)
    # push exactly
    assert scoring.spread_grading("home", 23, 20, -3.0, 1.952381) == (0, 1, 0.0)
    # away +3.5 covers when away loses by <= 3.5 (e.g. loses by 3: home 24, away 21)
    assert scoring.spread_grading("away", 24, 21, 3.5, 1.952381) == (1, 0, pytest.approx(0.952381))
    # away loses by 4 -> +3.5 does NOT cover
    assert scoring.spread_grading("away", 24, 20, 3.5, 1.952381) == (0, 0, -1.0)


def test_total_grading_and_push_zero() -> None:
    assert scoring.total_grading("over", 24, 20, 40.0, 1.91) == (1, 0, pytest.approx(0.91))
    assert scoring.total_grading("under", 24, 20, 40.0, 1.91) == (0, 0, -1.0)
    # over 44 with total exactly 44 -> PUSH (zero profit)
    assert scoring.total_grading("over", 24, 20, 44.0, 1.91) == (0, 1, 0.0)
    # under 44 with total 44 -> PUSH
    assert scoring.total_grading("under", 24, 20, 44.0, 1.91) == (0, 1, 0.0)
    # over 44 with total below 44 -> loss
    assert scoring.total_grading("over", 24, 19, 44.0, 1.91) == (0, 0, -1.0)
    # push -> zero profit
    assert scoring.total_grading("over", 22, 22, 44.0, 2.0) == (0, 1, 0.0)


# --------------------------------------------------------------------------
# Gate 5: spread shopping ordering
# --------------------------------------------------------------------------

def test_spread_shopping_best_number_first() -> None:
    offers = [shopping.Offer("draftkings", -3.5, -115),
              shopping.Offer("fanduel", -3.0, -120)]  # -3 is better (numerically greater)
    picked = shopping.shop_spread(offers)
    # best number is -3.0; only fanduel offers -3.0 -> fanduel
    assert picked is not None and picked.line == -3.0 and picked.book == "fanduel"


def test_spread_shopping_better_price_after_number() -> None:
    offers = [shopping.Offer("draftkings", -3.0, -120),
              shopping.Offer("fanduel", -3.0, -110)]  # same number, better price on FD
    picked = shopping.shop_spread(offers)
    assert picked.price_american == -110 and picked.book == "fanduel"


def test_spread_shopping_deterministic_tie_break() -> None:
    offers = [shopping.Offer("fanduel", -3.0, -110),
              shopping.Offer("draftkings", -3.0, -110)]  # identical -> fixed book order
    picked = shopping.shop_spread(offers)
    assert picked.book == "draftkings"  # draftkings before fanduel in fixed order


# --------------------------------------------------------------------------
# Gates 1,7,8,9,10: integration over the real frozen census (outcome-blind input)
# --------------------------------------------------------------------------

def _ledger(split: str) -> pl.DataFrame:
    census = pl.read_parquet(CENSUS)
    games = pl.read_parquet(GAMES).filter(pl.col("season").is_in([2020, 2021, 2022, 2023, 2024]))
    xgb_ids = set(pl.read_parquet(XGB).filter(pl.col("prediction_probability").is_not_null())
                  ["game_id"].unique().to_list())
    return candidates.build_ledger(census, games, xgb_ids, split)


def test_2025_absent() -> None:
    for split in ("DISCOVERY", "CONFIRMATION"):
        led = _ledger(split)
        assert (led["season"] == 2025).any() is False


def test_same_scorer_used_for_both_periods() -> None:
    # Both periods are produced by the identical build_ledger code path with the
    # same module object (no period-specific scoring). Their column schemas match.
    d = _ledger("DISCOVERY")
    c = _ledger("CONFIRMATION")
    assert d.columns == c.columns
    assert set(d["season"].unique().to_list()) == {2020, 2021, 2022}
    assert set(c["season"].unique().to_list()) == {2023, 2024}


def test_avg_0_2_exact_raw_bucket() -> None:
    d = _ledger("DISCOVERY")
    avg02 = d.filter((pl.col("family") == "ML_AVG_DISAGREEMENT") & (pl.col("bucket") == "0-2"))
    # exact raw boundary: edge_pp in [0, 2), never a rounded value at 2.0
    assert avg02["edge_pp"].min() >= 0
    assert avg02["edge_pp"].max() < 2
    assert avg02.height == 126  # validated corrected N (both constituents gate)


def test_dog_value_zone_exact() -> None:
    d = _ledger("DISCOVERY")
    dz = d.filter((pl.col("family") == "ML_DOG_VALUE_ZONE") & (pl.col("model") == "AVG"))
    assert dz.height == 131  # validated corrected N
    from nfl_edge.market_edge.scoring import american_to_decimal
    # all rows satisfy 0.40 <= p < 0.50 and +111 <= price <= +200
    assert dz["p_model"].min() >= 0.40
    assert dz["p_model"].max() < 0.50
    assert dz["price_american"].min() >= 111
    assert dz["price_american"].max() <= 200


def test_avg_null_when_either_constituent_missing() -> None:
    """AVG rows exist only for games with BOTH a QB-Elo and an XGBoost pred."""
    census = pl.read_parquet(CENSUS)
    games = pl.read_parquet(GAMES).filter(pl.col("season").is_in([2020, 2021, 2022, 2023, 2024]))
    xgb_ids = set(pl.read_parquet(XGB).filter(pl.col("prediction_probability").is_not_null())
                  ["game_id"].unique().to_list())
    led = candidates.build_ledger(census, games, xgb_ids, "DISCOVERY")
    avg = led.filter((pl.col("family") == "ML_AVG_DISAGREEMENT"))
    # every graded AVG game has an XGBoost prediction present in the input set
    assert set(avg["game_id"].unique().to_list()) <= xgb_ids
    # and a QB-Elo prediction exists for every AVG game (census QB_ELO row present)
    qb_games = set(census.filter((pl.col("census_family") == "POSITIVE_EDGE_CANDIDATE")
                                 & (pl.col("model") == "QB_ELO"))["game_id"].to_list())
    assert set(avg["game_id"].unique().to_list()) <= qb_games


def test_spread_ledger_uses_actual_actionable_price() -> None:
    d = _ledger("DISCOVERY")
    sp = d.filter(pl.col("family") == "SPREAD_DISAGREEMENT")
    assert sp["price_american"].is_not_null().all()
    # one correctly-reconstructed spread row per fully-reconstructable discovery game
    assert sp.height == 829


def test_corroborated_never_emitted_via_qb_fallback_when_avg_missing() -> None:
    """Regression gate for the removed corroborated ML fail-open fallback.

    Two synthetic games have QB-ELO and XGB both positive on the SAME dog-zone
    side, so the frozen corroboration predicate (QB and XGB agree on side) holds.
    The first game has NO AVG row / constituent prediction (xgb absent from the
    input id set), so the exact AVG cannot be constructed. Corrected scorer MUST
    NOT emit a corroborated row scored from the QB-ELO value alone — it skips the
    game (fail closed). The second game has the AVG row and both constituents, so
    it MUST be emitted and scored from the AVG value (positive control).
    """
    games = pl.DataFrame({
        "game_id": ["G_MISSING_AVG", "G_WITH_AVG"],
        "season": [2020, 2020],
        "season_week": [1, 2],
        "home_team": ["H1", "H2"], "away_team": ["A1", "A2"],
        "home_score": [17, 14], "away_score": [10, 17],
    })

    def pe_row(game: str, model: str, side: str, price: int, p: float, edge: float) -> dict:
        return {
            "game_id": game, "season": 2020,
            "season_week": 1 if game == "G_MISSING_AVG" else 2,
            "census_family": "POSITIVE_EDGE_CANDIDATE", "model": model,
            "side": side, "actionable_american": price, "p_model": p,
            "edge_pp": edge, "model_implied_ev": None, "actionable_book": "draftkings",
            "split_label": "DISCOVERY",
        }

    rows = [
        pe_row("G_MISSING_AVG", "QB_ELO", "home", 140, 0.45, 3.0),
        pe_row("G_MISSING_AVG", "XGB", "home", 150, 0.47, 4.0),
        # no AVG census row and no XGB prediction present -> exact AVG unconstructable
        pe_row("G_WITH_AVG", "QB_ELO", "away", 140, 0.46, 4.0),
        pe_row("G_WITH_AVG", "XGB", "away", 130, 0.48, 5.0),
        pe_row("G_WITH_AVG", "AVG", "away", 135, 0.47, 4.5),
    ]
    census = pl.DataFrame(rows)
    xgb_ids = {"G_WITH_AVG"}  # G_MISSING_AVG has no XGBoost constituent prediction

    led = candidates.build_ledger(census, games, xgb_ids, "DISCOVERY")

    corr = led.filter(pl.col("family") == "ML_CORROBORATED_DISAGREEMENT")
    dog_corr = led.filter((pl.col("family") == "ML_DOG_VALUE_ZONE") & (pl.col("model") == "CORROB"))
    # corroborated is never scored from QB-ELO alone; the missing-AVG game is skipped
    assert set(corr["game_id"].to_list()) == {"G_WITH_AVG"}
    assert set(dog_corr["game_id"].to_list()) == {"G_WITH_AVG"}
    # positive control: the corroborated row is valued from the AVG, not QB/XGB
    cr = corr.filter(pl.col("game_id") == "G_WITH_AVG").to_dicts()[0]
    assert cr["model"] == "CORROB" and cr["price_american"] == 135
    assert abs(cr["p_model"] - 0.47) < 1e-9
    # the standalone single-model QB row for the missing-AVG game is still graded
    qb_rows = led.filter(pl.col("model") == "QB_ELO")
    assert "G_MISSING_AVG" in set(qb_rows["game_id"].to_list())