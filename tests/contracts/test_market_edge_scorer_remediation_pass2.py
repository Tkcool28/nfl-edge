"""Task 05E pass-2 remediation contract tests (deterministic scorer fixes).

Proves the specific audit findings from remediation pass 2:

 1. SPREAD ACTIONABLE SHOPPING: spread is graded from the canonical book_market
    reconstructed offers via the frozen selected-side best-NUMBER-first rule
    (shopping.shop_spread) — NOT from stale census act_line/act_price. Number-first
    beats price-first in realistic reconstruction paths; negatives handle favorite
    sides; same-line picks the better price; identical offers resolve via the
    deterministic DK-before-FD tie-break; and the scorer output does NOT echo the
    stale census line/price/book when reconstructed offers differ.
 2. 2025 FIREWALL: a 2025 row in the outcome table raises hard (fail-closed)
    BEFORE any filtering/materialization.
 3. Fail-closed reconstruction: a spread row whose DK+FD offers cannot both be
    reconstructed is NOT graded.
 4. Pinnacle is never used as an actionable book.

Does not retune, change candidates, add thresholds, or open 2025 outcomes.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from nfl_edge.market_edge import candidates, offers, scoring, shopping
from nfl_edge.market_edge import config as cfgmod

ROOT = Path(__file__).resolve().parents[2]
CENSUS = ROOT / "data/modeling/development_v1/market_edge_census_v1.parquet"
GAMES = ROOT / "data/frozen/games/games_2018_2025.parquet"
XGB = ROOT / "data/modeling/development_v1/xgboost_candidate_predictions_2018_2024.parquet"
CFG = ROOT / "config/market_edge_validation_v1.yaml"
LOCK = ROOT / "reports/task_05e_d5_candidate_lock.json"
CANONICAL_BM = ROOT / "data/market_data/canonical/canonical_book_market.parquet"


# ---------------------------------------------------------------------------
#  fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def spread_index() -> dict:
    cfgmod.load_pinned_config(CFG)
    bm = pl.read_parquet(CANONICAL_BM)
    return offers.build_spread_offer_index(bm)


def _ledger(split: str, games: pl.DataFrame | None = None) -> pl.DataFrame:
    if games is None:
        games = pl.read_parquet(GAMES).filter(pl.col("season").is_in([2020, 2021, 2022, 2023, 2024]))
    census = pl.read_parquet(CENSUS)
    xgb_ids = set(pl.read_parquet(XGB).filter(pl.col("prediction_probability").is_not_null())
                  ["game_id"].unique().to_list())
    return candidates.build_ledger(census, games, xgb_ids, split)


# ---------------------------------------------------------------------------
# 1. SPREAD shopping: number-first beats price-first (real reconstruction)
# ---------------------------------------------------------------------------

def test_spread_number_first_picks_greatest_selected_line() -> None:
    # +3.5 must beat +3 even when +3 has a better price
    offers3 = [
        shopping.Offer("draftkings", 3.5, -115),
        shopping.Offer("fanduel", 3.0, -105),
    ]
    picked = shopping.shop_spread(offers3)
    assert picked.line == 3.5 and picked.price_american == -115 and picked.book == "draftkings"


def test_spread_number_first_negative_favorite() -> None:
    # selected side is a favorite given negative points (home -X). Best number
    # for the selected side is the numerically GREATEST (e.g. -2.5 > -3), so even
    # with worse juice the better line wins.
    fav = [
        shopping.Offer("fanduel", -3.0, -105),
        shopping.Offer("draftkings", -2.5, -120),
    ]
    picked = shopping.shop_spread(fav)
    assert picked.line == -2.5 and picked.book == "draftkings"


def test_spread_same_line_picks_better_price() -> None:
    offers3 = [
        shopping.Offer("draftkings", 6.5, -115),
        shopping.Offer("fanduel", 6.5, -105),
    ]
    picked = shopping.shop_spread(offers3)
    assert picked.line == 6.5 and picked.price_american == -105 and picked.book == "fanduel"


def test_spread_deterministic_tie_dk_before_fd() -> None:
    # identical line AND price -> deterministic fixed order, DK before FD
    offers3 = [
        shopping.Offer("fanduel", 3.0, -110),
        shopping.Offer("draftkings", 3.0, -110),
    ]
    picked = shopping.shop_spread(offers3)
    assert picked.book == "draftkings"


def test_spread_reconstructed_grade_not_census_echo() -> None:
    """Scorer output for spread must NOT echo stale census act_line/act_price.

    In the real census, `2020_01_GB_MIN` (away) recorded act_line=1.5/@-105/FD
    (price-first). Number-first reconstruction from canonical offers yields the
    greater selected line 2.5/@-115/DK. Prove the ledger carries the reconstructed
    (line,price,book), never the census values.
    """
    led = _ledger("DISCOVERY")
    sp = led.filter(pl.col("family") == "SPREAD_DISAGREEMENT")
    row = sp.filter(pl.col("game_id") == "2020_01_GB_MIN").to_dicts()[0]
    census_row = pl.read_parquet(CENSUS).filter(
        (pl.col("census_family") == "SPREAD") & (pl.col("game_id") == "2020_01_GB_MIN")
    ).to_dicts()[0]
    # stale census would have graded at 1.5/-105/FD; the reconstructed/ledgered values
    # differ and the ledger price/ROI uses the reconstructed ones
    assert census_row["act_line"] == 1.5
    assert row["reconstructed_line"] == 2.5
    assert row["price_american"] == -115
    assert row["reconstructed_book"] == "draftkings"
    # the graded outcome is computed from the reconstructed line + price
    g = pl.read_parquet(GAMES).filter(pl.col("game_id") == "2020_01_GB_MIN").head(1).to_dicts()[0]
    w, p, pr = scoring.spread_grading("away", g["home_score"], g["away_score"], 2.5, scoring.american_to_decimal(-115))
    assert row["w"] == w and row["profit"] == pytest.approx(pr)


def test_spread_index_reconstruction_complete_dk_fd() -> None:
    """Every graded spread row has both a DK and FD reconstructed offer."""
    idx = pl.read_parquet(CANONICAL_BM)
    index = offers.build_spread_offer_index(idx)
    led = _ledger("DISCOVERY")
    sp = led.filter(pl.col("family") == "SPREAD_DISAGREEMENT")
    for r in sp.to_dicts():
        offers_list = index.get((r["game_id"], r["selected_side"]), [])
        books = {o.book for o in offers_list}
        assert {"draftkings", "fanduel"} <= books, f"{r['game_id']} missing book"


def test_pinnacle_never_actionable_for_spread() -> None:
    bm = pl.read_parquet(CANONICAL_BM).filter(pl.col("market_key") == "spreads")
    pin = bm.filter(pl.col("bookmaker_key") == "pinnacle")
    assert pin.height > 0  # pinnacle exists as benchmark
    # build the index and assert no pinnacle offer is in the index
    index = offers.build_spread_offer_index(bm)
    for offers_list in index.values():
        for o in offers_list:
            assert o.book != "pinnacle"


# ---------------------------------------------------------------------------
# 2. 2025 FIREWALL
# ---------------------------------------------------------------------------

def test_2025_row_hard_rejected_before_filtering() -> None:
    """A 2025 row in the outcome table raises fail-closed BEFORE filtering."""
    games = pl.read_parquet(GAMES)  # includes 2025 rows (285)
    assert (games["season"] == 2025).any()  # control: 2025 truly present
    census = pl.read_parquet(CENSUS)
    xgb_ids = set(pl.read_parquet(XGB).filter(pl.col("prediction_probability").is_not_null())
                  ["game_id"].unique().to_list())
    with pytest.raises(RuntimeError):
        candidates.build_ledger(census, games, xgb_ids, "DISCOVERY")


def test_2025_clean_output_when_scoped() -> None:
    for split in ("DISCOVERY", "CONFIRMATION"):
        led = _ledger(split)
        assert (led["season"] == 2025).any() is False


# ---------------------------------------------------------------------------
# 3. Row-level integrity spot re-grade
# ---------------------------------------------------------------------------

def test_row_level_integrity_20_rows_per_period() -> None:
    """Independently recompute selected-side result/profit from final score and
    the actionable price/line and assert the ledger matches, including pushes and
    home+away selections."""
    # deterministic sample (fixed stride, no RNG) of spread rows per period
    for split in ("DISCOVERY", "CONFIRMATION"):
        led = _ledger(split)
        fam = "SPREAD_DISAGREEMENT"
        sub = led.filter(pl.col("family") == fam)
        # deterministic stride sample of up to 20 spread rows + 20 ML rows
        check = []
        if sub.height > 0:
            stride = max(1, sub.height // 20)
            check += list(sub.select("game_id").to_series().to_list()[::stride][:20])
        ml = led.filter(pl.col("family").str.contains("ML_"))
        if ml.height > 0:
            stride2 = max(1, ml.height // 20)
            check += list(ml.select("game_id").to_series().to_list()[::stride2][:20])
        check = list(dict.fromkeys(check))
        games = pl.read_parquet(GAMES).filter(pl.col("season").is_in([2020, 2021, 2022, 2023, 2024]))
        gmap = {r["game_id"]: r for r in games.to_dicts()}
        n = 0
        for r in led.filter(pl.col("game_id").is_in(check)).to_dicts():
            g = gmap[r["game_id"]]
            if r["family"] == "SPREAD_DISAGREEMENT":
                w, push, profit = scoring.spread_grading(
                    r["selected_side"], g["home_score"], g["away_score"],
                    r["reconstructed_line"], r["price_decimal"])
            elif "ML_" in r["family"] and r["model"] != "CORROB":
                w, push, profit = scoring.moneyline_grading(
                    r["selected_side"], g["home_score"], g["away_score"], r["price_decimal"])
            else:
                continue
            assert r["w"] == w and r["p_push"] == push and r["profit"] == pytest.approx(profit, abs=1e-4), r
            n += 1
        # assert at least 20 rows independently verified per period across families
        print(f"[{split}] independently verified {n} rows")
        assert n >= 20