"""Task 04D focused tests: bounded team-Elo season-regression harness.

Covers the formula grid (0/25/33.3/40/60%), the canonical-engine reuse
of ``apply_season_carryover``, season-transition triggers, 2018
initialization, same-block chronology, frozen oracle-QB isolation, the
development universe / 2025 exclusion, and the 33.3% Task04C identity gate.
"""

from __future__ import annotations

import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from nfl_edge.backtest.task04c_paired_evaluation import OracleQBAdjustments
from nfl_edge.backtest.task04d_season_regression_evaluation import (
    AUDIT_LEDGER_COLUMNS,
    CANDIDATE_FRACTIONS,
    CANDIDATE_LABELS,
    REGRESSION_CENTER,
    TASK04C_REFERENCE_FRACTION,
    build_candidate_config,
    build_season_boundary_audit,
    load_canonical_config,
    metrics_for,
    regression_expected,
    week1_4_metrics_for,
)
from nfl_edge.backtest.walk_forward import run_development_walk_forward
from nfl_edge.common.errors import SealedHoldoutAccessError

REPO_ROOT = Path(__file__).resolve().parents[2]
ORACLE_PATH = (
    REPO_ROOT
    / "data/derived/oracle_qb_entering_state_v2"
    / "oracle_qb_pregame_adjustments_by_game_2018_2024_v2.parquet"
)
GAMES_PATH = REPO_ROOT / "data/derived/features_v1/game_features_2018_2025.parquet"
TEAM_PATH = REPO_ROOT / "data/derived/features_v1/team_pregame_features_2018_2025.parquet"
TASK04C_ORACLE_PREDS = (
    REPO_ROOT
    / "data/derived/qb_elo_oracle_comparison_v1"
    / "qb_elo_oracle_predictions_2018_2024.parquet"
)
AS_OF = datetime(2018, 9, 6, 17, 0, 0, tzinfo=timezone.utc)

_TOL = 1e-6


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _row(
    game_id: str,
    home: str,
    away: str,
    *,
    season: int = 2018,
    st: str = "REG",
    week: int = 1,
    margin: int = 7,
    tie: bool = False,
    neutral: bool = False,
    as_of: datetime | None = None,
) -> dict:
    return {
        "game_id": game_id,
        "season": season,
        "season_type": st,
        "week": week,
        "home_team": home,
        "away_team": away,
        "neutral_site": neutral,
        "target_margin": None if tie else margin,
        "target_home_win": None if tie else (margin > 0),
        "target_tie": tie,
        "target_available": not tie,
        "prediction_as_of_utc": as_of or AS_OF,
    }


def _games(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows)


def _write_games(rows: list[dict], tmp_path: Path) -> Path:
    path = tmp_path / "fixture_games.parquet"
    _games(rows).write_parquet(path)
    return path


def _run_fixture(
    rows: list[dict],
    tmp_path: Path,
    *,
    fraction: float,
    resolver=None,
    out_dir: Path | None = None,
):
    games_path = _write_games(rows, tmp_path)
    out = out_dir or (tmp_path / "out")
    run_development_walk_forward(
        games_path=games_path,
        team_features_path=TEAM_PATH,
        output_dir=out,
        config=build_candidate_config(load_canonical_config(REPO_ROOT), fraction),
        created_at=datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
        project_root=REPO_ROOT,
        qb_adjustment_resolver=resolver,
    )
    preds = pl.read_parquet(out / "qb_elo_predictions_2018_2024.parquet")
    state = pl.read_parquet(out / "qb_elo_state_transitions_2018_2024.parquet")
    return preds, state


# ---------------------------------------------------------------------------
# 1. Candidate grid / config structure
# ---------------------------------------------------------------------------


def test_candidate_grid_labels_and_fractions():
    assert CANDIDATE_LABELS == (
        "regression_000",
        "regression_025",
        "regression_040",
        "regression_060",
        "task04c_reference_0333",
    )
    assert CANDIDATE_FRACTIONS == {
        "regression_000": 0.00,
        "regression_025": 0.25,
        "regression_040": 0.40,
        "regression_060": 0.60,
        "task04c_reference_0333": 0.333,
    }
    assert TASK04C_REFERENCE_FRACTION == 0.333
    assert REGRESSION_CENTER == 1500.0


def test_build_candidate_config_changes_only_the_fraction():
    base = load_canonical_config(REPO_ROOT)
    assert base["season_mean_reversion_fraction"] == pytest.approx(0.333)
    for label, frac in CANDIDATE_FRACTIONS.items():
        cfg = build_candidate_config(base, frac)
        assert cfg["season_mean_reversion_fraction"] == pytest.approx(frac)
        # Every other key identical.
        for k, v in base.items():
            if k == "season_mean_reversion_fraction":
                continue
            assert cfg[k] == v, f"candidate config mutated non-fraction key {k}"
        assert set(cfg.keys()) == set(base.keys())


# ---------------------------------------------------------------------------
# 2. Formula grid (using the canonical regression_expected helper)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fraction,retain",
    [
        (0.00, 1.00),
        (0.25, 0.75),
        (0.40, 0.60),
        (0.60, 0.40),
    ],
)
def test_regression_formula_required_grid(fraction: float, retain: float):
    for R in (1350.0, 1500.0, 1650.0):  # low / exactly-center / high
        expected = 1500.0 + retain * (R - 1500.0)
        assert regression_expected(R, fraction) == pytest.approx(expected, abs=_TOL)


def test_regression_formula_task04c_reference_uses_exact_0333():
    # Repository value is 0.333, NOT mathematical one-third.
    assert TASK04C_REFERENCE_FRACTION == 0.333
    retain = 1.0 - 0.333  # 0.667
    for R in (1350.0, 1500.0, 1650.0):
        expected = 1500.0 + retain * (R - 1500.0)
        assert regression_expected(R, TASK04C_REFERENCE_FRACTION) == pytest.approx(
            expected, abs=_TOL
        )


def test_regression_at_exact_center_is_1500_for_every_fraction():
    for fraction in CANDIDATE_FRACTIONS.values():
        assert regression_expected(1500.0, fraction) == pytest.approx(1500.0, abs=_TOL)


def test_zero_percent_returns_prior_unchanged():
    for R in (1200.0, 1500.0, 1800.0):
        assert regression_expected(R, 0.00) == pytest.approx(R, abs=_TOL)


def test_canonical_apply_season_carryover_matches_helper():
    """Prove the harness reuses the canonical engine math (no 2nd impl)."""
    from nfl_edge.models.qb_elo import EloConfig, EloState, TeamState, apply_season_carryover

    state = EloState(
        teams={
            t: TeamState(team=t, rating=r, last_season=2018)
            for t, r in {
                "AAA": 1180.0,
                "BBB": 1500.0,
                "CCC": 1700.0,
                "DDD": 1610.25,
            }.items()
        },
        mean=1500.0,
        current_season=2018,
    )
    for fraction in CANDIDATE_FRACTIONS.values():
        cfg = EloConfig(season_mean_reversion_fraction=fraction)
        new_state = apply_season_carryover(state, new_season=2019, config=cfg)
        for team, prior in {
            "AAA": 1180.0,
            "BBB": 1500.0,
            "CCC": 1700.0,
            "DDD": 1610.25,
        }.items():
            assert new_state.rating(team) == pytest.approx(
                regression_expected(prior, fraction), abs=_TOL
            )
        assert new_state.current_season == 2019
        assert all(ts.last_season == 2019 for ts in new_state.teams.values())


# ---------------------------------------------------------------------------
# 3. Transition semantics (engine-level, baseline resolver)
# ---------------------------------------------------------------------------


def _two_season_rows() -> list[dict]:
    # 2018 REG W1 (2 games), 2018 WC W1 (1 game), 2019 REG W1 (2 games).
    return [
        _row("2018_01_AAA_BBB", "AAA", "BBB", season=2018, week=1, margin=7),
        _row("2018_01_CCC_DDD", "CCC", "DDD", season=2018, week=1, margin=-3),
        _row("2018_18_AAA_CCC", "AAA", "CCC", season=2018, st="WC", week=18, margin=10),
        _row("2019_01_DDD_AAA", "DDD", "AAA", season=2019, week=1, margin=1),
        _row("2019_01_BBB_CCC", "BBB", "CCC", season=2019, week=1, margin=-7),
    ]


def test_exactly_one_regression_at_2018_to_2019(tmp_path):
    preds, state = _run_fixture(_two_season_rows(), tmp_path, fraction=0.25)
    audit = build_season_boundary_audit(preds, state, 0.25, candidate_label="regression_025")
    assert audit["new_season"].to_list() == [2019] * audit.height
    # Exactly one regression row per team that played in 2018 and appears in 2019.
    teams_2018 = {"AAA", "BBB", "CCC", "DDD"}
    assert set(audit["team"].to_list()) == teams_2018
    assert audit.height == len(teams_2018)
    # Only one transition (2018->2019); no duplicate application.
    assert audit.select(pl.col("previous_season"), pl.col("new_season")).unique().height == 1
    assert (audit["status"] == "PASS").all()


def test_no_regression_within_single_season_or_between_reg_and_wc(tmp_path):
    # 2018 REG W1, REG W2, and WC - same integer season -> zero transitions.
    rows = [
        _row("2018_01_AAA_BBB", "AAA", "BBB", season=2018, week=1, margin=7),
        _row("2018_02_CCC_DDD", "CCC", "DDD", season=2018, week=2, margin=-3),
        _row("2018_18_AAA_CCC", "AAA", "CCC", season=2018, st="WC", week=18, margin=10),
        _row("2018_19_BBB_DDD", "BBB", "DDD", season=2018, st="DIV", week=19, margin=1),
        _row("2018_20_AAA_DDD", "AAA", "DDD", season=2018, st="CON", week=20, margin=4),
        _row("2018_21_CCC_BBB", "CCC", "BBB", season=2018, st="SB", week=21, margin=6),
    ]
    preds, state = _run_fixture(rows, tmp_path, fraction=0.40)
    audit = build_season_boundary_audit(preds, state, 0.40, candidate_label="regression_040")
    assert audit.height == 0  # no season bump -> no regression


def test_no_calendar_rollover_and_season_integer_governs(tmp_path):
    # Same integer season 2018 spanning Sep(REG)-Jan(WC)-Feb(SB) dates.
    rows = [
        _row(
            "2018_01_AAA_BBB", "AAA", "BBB", season=2018, week=1, margin=7,
            as_of=datetime(2018, 9, 6, 17, 0, 0, tzinfo=timezone.utc),
        ),
        _row(
            "2018_18_CCC_DDD", "CCC", "DDD", season=2018, st="WC", week=18, margin=10,
            as_of=datetime(2019, 1, 5, 17, 0, 0, tzinfo=timezone.utc),
        ),
        _row(
            "2018_21_AAA_DDD", "AAA", "DDD", season=2018, st="SB", week=21, margin=4,
            as_of=datetime(2019, 2, 3, 18, 0, 0, tzinfo=timezone.utc),
        ),
        # New integer season 2019 (Sep) -> one bump.
        _row(
            "2019_01_AAA_BBB", "AAA", "BBB", season=2019, week=1, margin=7,
            as_of=datetime(2019, 9, 5, 17, 0, 0, tzinfo=timezone.utc),
        ),
    ]
    preds, state = _run_fixture(rows, tmp_path, fraction=0.60)
    audit = build_season_boundary_audit(preds, state, 0.60, candidate_label="regression_060")
    # The only regression is at the 2018->2019 integer-season bump; the
    # January/February dates inside 2018 never trigger it.
    assert set(audit["previous_season"].to_list()) == {2018}
    assert set(audit["new_season"].to_list()) == {2019}
    # Only teams that appear in the new season (2019 -> AAA, BBB) are audited.
    assert set(audit["team"].to_list()) == {"AAA", "BBB"}


def test_no_arbitrary_week_number_reset_trigger(tmp_path):
    # Same-season week numbers are arbitrary; a large week does not reset.
    rows = [
        _row("2018_01_AAA_BBB", "AAA", "BBB", season=2018, week=1, margin=7),
        _row("2018_99_CCC_DDD", "CCC", "DDD", season=2018, week=99, margin=-3),
    ]
    preds, state = _run_fixture(rows, tmp_path, fraction=0.25)
    audit = build_season_boundary_audit(preds, state, 0.25)
    assert audit.height == 0


def test_subsequent_transition_and_single_application(tmp_path):
    # 2018, 2019, 2020 -> exactly two transitions; each prior team once each.
    rows = [
        _row("2018_01_AAA_BBB", "AAA", "BBB", season=2018, week=1, margin=7),
        _row("2019_01_AAA_CCC", "AAA", "CCC", season=2019, week=1, margin=-9),
        _row("2019_02_BBB_DDD", "BBB", "DDD", season=2019, week=2, margin=3),
        _row("2020_01_AAA_BBB", "AAA", "BBB", season=2020, week=1, margin=5),
        _row("2020_01_CCC_DDD", "CCC", "DDD", season=2020, week=1, margin=-7),
    ]
    preds, state = _run_fixture(rows, tmp_path, fraction=0.25)
    audit = build_season_boundary_audit(preds, state, 0.25)
    assert sorted(audit["new_season"].unique().to_list()) == [2019, 2020]
    # per (prev,new,team) exactly one row -> no duplicate application.
    key = audit.select("previous_season", "new_season", "team")
    assert not key.is_duplicated().any()
    # CCC/DDD first appear in 2019 (no 2018 state) -> NO_PRIOR_STATE for the
    # 2018->2019 transition; they gain a 2019 rating and are regressed 2019->2020.
    np = audit.filter(pl.col("status") == "NO_PRIOR_STATE")
    assert np.height == 2
    assert set(np["team"].to_list()) == {"CCC", "DDD"}
    assert set(np["previous_season"].to_list()) == {2018}
    assert (np["prior_team_state_exists"] == False).all()  # noqa: E712
    # Every team WITH a prior-season rating is PASS (regression applied).
    pend = audit.filter(pl.col("prior_team_state_exists") == True)  # noqa: E712
    assert (pend["status"] == "PASS").all()
    assert pend.height == (audit.height - np.height)


# ---------------------------------------------------------------------------
# 4. 2018 initialization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fraction", [0.00, 0.333, 0.60])
def test_2018_initialization_identical_and_no_pre2018_regression(tmp_path, fraction):
    rows = [
        _row("2018_01_AAA_BBB", "AAA", "BBB", season=2018, week=1, margin=7),
        _row("2019_01_AAA_BBB", "AAA", "BBB", season=2019, week=1, margin=7),
    ]
    preds, state = _run_fixture(rows, tmp_path, fraction=fraction)
    w1 = preds.filter(pl.col("season") == 2018)
    for v in w1["home_elo_before"].to_list() + w1["away_elo_before"].to_list():
        assert v == pytest.approx(1500.0, abs=_TOL)
    audit = build_season_boundary_audit(preds, state, fraction)
    # No transition row references 2018 as a NEW season (no pre-2018 carryover).
    assert 2018 not in set(audit["new_season"].to_list())
    # The regression EVENT still fired once for 2018->2019 (structure proven,
    # not merely ratings - which are invisible at exactly 1500 start).
    tr = audit.filter(pl.col("new_season") == 2019)
    assert tr.height == 2  # AAA, BBB
    assert (tr["previous_season"] == 2018).all()
    assert (tr["status"] == "PASS").all()


# ---------------------------------------------------------------------------
# 5. Same-block chronology
# ---------------------------------------------------------------------------


def test_candidate_regression_active_before_new_season_predictions(tmp_path):
    # 2018 game ends AAA/BBB at non-1500; 2019 W1 block has AAA and BBB games.
    rows = [
        _row("2018_01_AAA_CCC", "AAA", "CCC", season=2018, week=1, margin=14),
        _row("2018_01_BBB_DDD", "BBB", "DDD", season=2018, week=1, margin=-10),
        # New season block: two independent games, same block.
        _row("2019_01_AAA_BBB", "AAA", "BBB", season=2019, week=1, margin=3),
        _row("2019_01_CCC_DDD", "CCC", "DDD", season=2019, week=1, margin=-7),
    ]
    preds, state = _run_fixture(rows, tmp_path, fraction=0.25)
    w19 = preds.filter(pl.col("season") == 2019).sort("game_id")
    assert w19.height == 2
    g_aaa = w19.filter(pl.col("game_id") == "2019_01_AAA_BBB")[0]
    g_ccc = w19.filter(pl.col("game_id") == "2019_01_CCC_DDD")[0]
    # AAA's 2019 W1 elo_before reflects the 0.25 regression from its 2018
    # rating (not its raw 2018 ending) -> regression active before predict.
    aaa_2018_end = state.filter(
        (pl.col("team") == "AAA") & (pl.col("season") == 2018)
    )["elo_after"].item()
    assert g_aaa["home_elo_before"].item() == pytest.approx(
        regression_expected(aaa_2018_end, 0.25), abs=_TOL
    )
    # Frozen block: the two 2019 W1 predictions do not influence each other.
    ccc_2018_end = state.filter(
        (pl.col("team") == "CCC") & (pl.col("season") == 2018)
    )["elo_after"].item()
    assert g_ccc["home_elo_before"].item() == pytest.approx(
        regression_expected(ccc_2018_end, 0.25), abs=_TOL
    )
    assert g_ccc["away_elo_before"].item() == pytest.approx(
        regression_expected(
            state.filter((pl.col("team") == "DDD") & (pl.col("season") == 2018))[
                "elo_after"
            ].item(),
            0.25,
        ),
        abs=_TOL,
    )
    # Regression already applied for every team before any 2019 prediction:
    # the season-boundary audit must map each team's first new-season rating
    # onto regression_expected(prior, 0.25) with PASS.
    audit = build_season_boundary_audit(preds, state, 0.25)
    assert set(audit["team"].to_list()) == {"AAA", "BBB", "CCC", "DDD"}
    assert (audit["status"] == "PASS").all()
    for r in audit.iter_rows(named=True):
        assert r["actual_new_elo"] == pytest.approx(
            regression_expected(r["prior_season_ending_elo"], 0.25), abs=_TOL
        )


def test_candidate_config_does_not_alter_block_ordering(tmp_path):
    rows = _two_season_rows()
    preds_lo, _ = _run_fixture(rows, tmp_path, fraction=0.00, out_dir=tmp_path / "lo")
    preds_hi, _ = _run_fixture(rows, tmp_path, fraction=0.60, out_dir=tmp_path / "hi")
    assert preds_lo["game_id"].to_list() == preds_hi["game_id"].to_list()
    # Season/type/week labels identical across candidates.
    for col in ("season", "season_type", "week", "home_team", "away_team"):
        assert preds_lo[col].to_list() == preds_hi[col].to_list()


# ---------------------------------------------------------------------------
# 6. Frozen oracle-QB isolation (0% vs 0.333 over the full universe)
# ---------------------------------------------------------------------------


def test_frozen_oracle_qb_identical_across_candidates():
    """Run 0% once and compare against the committed 0.333 oracle parquet.

    QB adjustments are prediction-only and fraction-independent: they must be
    byte-identical for every game. Only team Elo differs after a transition.
    """
    with tempfile.TemporaryDirectory(prefix="task04d_frozenqb_") as td:
        run_development_walk_forward(
            games_path=GAMES_PATH,
            team_features_path=TEAM_PATH,
            output_dir=Path(td),
            config=build_candidate_config(
                load_canonical_config(REPO_ROOT), CANDIDATE_FRACTIONS["regression_000"]
            ),
            created_at=datetime(2026, 8, 10, 13, 0, 0, tzinfo=timezone.utc),
            project_root=REPO_ROOT,
            qb_adjustment_resolver=OracleQBAdjustments(ORACLE_PATH),
        )
        p0 = pl.read_parquet(Path(td) / "qb_elo_predictions_2018_2024.parquet")
    p033 = pl.read_parquet(TASK04C_ORACLE_PREDS)

    m0 = p0.sort("game_id")
    m3 = p033.sort("game_id")
    assert m0["game_id"].to_list() == m3["game_id"].to_list()
    assert m0.height == m3.height == 1942
    # QB adjustments identical for EVERY game (fraction-independent, frozen).
    assert m0["home_qb_adjustment"].to_list() == m3["home_qb_adjustment"].to_list()
    assert m0["away_qb_adjustment"].to_list() == m3["away_qb_adjustment"].to_list()
    # QB adjustment equals the frozen oracle parquet (not scaled by fraction).
    oracle = OracleQBAdjustments(ORACLE_PATH)
    for r in m0.iter_rows(named=True):
        hb, ab = oracle(r["game_id"])
        assert r["home_qb_adjustment"] == pytest.approx(hb, abs=_TOL)
        assert r["away_qb_adjustment"] == pytest.approx(ab, abs=_TOL)
    # Some 2019+ game must differ in team Elo while QB adjustments stay equal
    # -> proves only team Elo changes after a transition.
    post2018 = m0.filter(pl.col("season") >= 2019)
    h0 = post2018["home_elo_before"].to_list()
    h3 = m3.filter(pl.col("season") >= 2019)["home_elo_before"].to_list()
    assert any(x != y for x, y in zip(h0, h3))


# ---------------------------------------------------------------------------
# 7. Development universe / 2025 exclusion
# ---------------------------------------------------------------------------


def test_development_universe_counts():
    games = pl.read_parquet(GAMES_PATH)
    dev = games.filter(pl.col("season") <= 2024)
    assert dev.height == 1942
    assert int(dev["season"].min()) == 2018
    assert int(dev["season"].max()) == 2024
    assert int(games.filter(pl.col("season") == 2017).height) == 0
    assert int(games.filter(pl.col("season") == 2025).height) == 285
    counts = {int(r["season"]): int(r["len"]) for r in dev.group_by("season").len().to_dicts()}
    assert counts == {
        2018: 267, 2019: 267, 2020: 269, 2021: 285, 2022: 284, 2023: 285, 2024: 285,
    }
    st = {r["season_type"]: int(r["len"]) for r in dev.group_by("season_type").len().to_dicts()}
    assert st["WC"] + st["DIV"] + st["CON"] + st["SB"] == 87
    assert st["REG"] == 1855


def test_2025_rows_excluded_from_development_schedule():
    from nfl_edge.backtest.blocks import (
        assert_development_seasons_only,
        build_development_blocks,
    )

    bad = _games([_row("2025_01_AAA_BBB", "AAA", "BBB", season=2025, week=1)])
    with pytest.raises(SealedHoldoutAccessError):
        assert_development_seasons_only(bad)
    assert build_development_blocks(bad) == []


def test_canonical_blocks_fraction_independent_and_oracle_coverage():
    from nfl_edge.backtest.blocks import build_development_blocks

    games = pl.read_parquet(GAMES_PATH).filter(pl.col("season") <= 2024)
    blocks = build_development_blocks(games)
    # One block per (season, season_type, week); all 1942 game_ids present.
    block_gids = {gid for b in blocks for gid in b.game_ids}
    assert len(block_gids) == 1942
    assert all(b.season <= 2024 for b in blocks)
    # The oracle covers exactly the canonical universe (no extras, no missing).
    oracle = OracleQBAdjustments(ORACLE_PATH)
    oracle.assert_coverage(block_gids, where="task04d.universe")
    assert oracle.n_rows == 1942
    # Blocks are config-independent -> identical schedule for any candidate.
    # (Rebuild shows determinism; engine schedule does not depend on fraction.)
    blocks2 = build_development_blocks(games)
    assert [b.block_id for b in blocks] == [b.block_id for b in blocks2]


# ---------------------------------------------------------------------------
# 8. Audit ledger shape / center
# ---------------------------------------------------------------------------


def test_audit_ledger_columns_and_center():
    assert AUDIT_LEDGER_COLUMNS == (
        "candidate_label",
        "regression_fraction",
        "team",
        "previous_season",
        "new_season",
        "prior_season_ending_elo",
        "canonical_mean",
        "expected_new_elo",
        "actual_new_elo",
        "difference",
        "transition_block_id",
        "first_prediction_block_id",
        "first_prediction_game_id",
        "prior_team_state_exists",
        "status",
    )
    rows = _two_season_rows()
    preds, state = _run_fixture(
        rows, Path(tempfile.mkdtemp(prefix="task04d_aud_")), fraction=0.00
    )
    audit = build_season_boundary_audit(
        preds, state, 0.00, candidate_label="regression_000"
    )
    assert (audit["canonical_mean"] == 1500.0).all()
    # 0% -> expected == prior-season ending.
    for r in audit.iter_rows(named=True):
        assert r["expected_new_elo"] == pytest.approx(r["prior_season_ending_elo"])

    # 60% -> expected equals 1500 + 0.40*(prior - 1500) and matches actual.
    preds6, state6 = _run_fixture(
        rows, Path(tempfile.mkdtemp(prefix="task04d_aud6_")), fraction=0.60
    )
    audit6 = build_season_boundary_audit(
        preds6, state6, 0.60, candidate_label="regression_060"
    )
    assert (audit6["status"] == "PASS").all()
    for r in audit6.iter_rows(named=True):
        assert r["expected_new_elo"] == pytest.approx(
            1500.0 + 0.40 * (r["prior_season_ending_elo"] - 1500.0), abs=_TOL
        )
        assert r["actual_new_elo"] == pytest.approx(r["expected_new_elo"], abs=_TOL)


# ---------------------------------------------------------------------------
# 9. Metrics helper reproduces Task04C convention
# ---------------------------------------------------------------------------


def test_metrics_convention_matches_task04c():
    p033 = pl.read_parquet(TASK04C_ORACLE_PREDS)
    y = p033["target_outcome"].to_list()
    p = p033["predicted_home_win_probability"].to_list()
    n = len(y)
    brier = sum((py - yn) ** 2 for py, yn in zip(p, y)) / n
    ll = sum(
        -(yn * math.log(py) + (1 - yn) * math.log(1 - py)) for py, yn in zip(p, y)
    ) / n
    acc = sum(1 for py, yn in zip(p, y) if (py > 0.5) == bool(yn)) / n
    assert brier == pytest.approx(0.221918210006, abs=_TOL)
    assert ll == pytest.approx(0.635506991355, abs=_TOL)
    assert acc == pytest.approx(0.647785787848, abs=_TOL)


# ---------------------------------------------------------------------------
# 10. Task04C identity gate (33.3% reference reproduces Task04C)
# ---------------------------------------------------------------------------


def test_task04c_reference_0333_identity_gate(tmp_path):
    """The 33.3% reference must reproduce the validated Task04C oracle model."""
    out = tmp_path / "id33"
    run_development_walk_forward(
        games_path=GAMES_PATH,
        team_features_path=TEAM_PATH,
        output_dir=out,
        config=build_candidate_config(
            load_canonical_config(REPO_ROOT), TASK04C_REFERENCE_FRACTION
        ),
        created_at=datetime(2026, 8, 10, 14, 0, 0, tzinfo=timezone.utc),
        project_root=REPO_ROOT,
        qb_adjustment_resolver=OracleQBAdjustments(ORACLE_PATH),
    )
    mine = pl.read_parquet(out / "qb_elo_predictions_2018_2024.parquet").sort("game_id")
    theirs = pl.read_parquet(TASK04C_ORACLE_PREDS).sort("game_id")
    assert mine.height == theirs.height == 1942
    assert mine["game_id"].to_list() == theirs["game_id"].to_list()
    for col in (
        "home_elo_before",
        "away_elo_before",
        "home_qb_adjustment",
        "away_qb_adjustment",
        "predicted_home_win_probability",
    ):
        a = mine[col].to_list()
        b = theirs[col].to_list()
        assert max(abs(x - y) for x, y in zip(a, b)) <= _TOL, f"diverged on {col}"
    m = metrics_for(mine)
    assert m["brier"] == pytest.approx(0.221918210006, abs=_TOL)
    assert m["log_loss"] == pytest.approx(0.635506991355, abs=_TOL)
    assert m["accuracy"] == pytest.approx(0.647785787848, abs=_TOL)


# ---------------------------------------------------------------------------
# 11. Week 1-4 metrics helper smoke
# ---------------------------------------------------------------------------


def test_week1_4_metrics_helper_on_full_run(tmp_path):
    out = tmp_path / "w14"
    run_development_walk_forward(
        games_path=GAMES_PATH,
        team_features_path=TEAM_PATH,
        output_dir=out,
        config=build_candidate_config(
            load_canonical_config(REPO_ROOT), TASK04C_REFERENCE_FRACTION
        ),
        created_at=datetime(2026, 8, 10, 15, 0, 0, tzinfo=timezone.utc),
        project_root=REPO_ROOT,
        qb_adjustment_resolver=OracleQBAdjustments(ORACLE_PATH),
    )
    preds = pl.read_parquet(out / "qb_elo_predictions_2018_2024.parquet")
    m = metrics_for(preds)
    w14 = week1_4_metrics_for(preds)
    assert m["brier"] == pytest.approx(0.221918210006, abs=_TOL)
    # Week 1-4 sub-segment runs and returns finite metrics.
    assert w14["n_scored"] > 0
    assert 0.0 < w14["brier"] < 1.0
    assert 0.0 < w14["log_loss"] < 1.0
    # Week<=4 REG rows < total scored rows.
    w14_rows = preds.filter(
        (pl.col("week") <= 4) & (pl.col("season_type") == "REG")
    ).height
    assert w14["n_scored"] == float(w14_rows)


# ---------------------------------------------------------------------------
# Phase 5B-1: fail-closed workflow enforcement
# ---------------------------------------------------------------------------
def _load_script(rel: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(Path(rel).stem, REPO_ROOT / rel)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_OFFICIAL = _load_script("scripts/official_qb_elo_season_regression.py")
_FINALIZE = _load_script("scripts/finalize_qb_elo_season_regression.py")


def _fixture_root(root: Path) -> Path:
    import shutil as _sh
    dst = root / "fixture"
    (dst / "data/derived").mkdir(parents=True, exist_ok=True)
    _sh.copytree(
        REPO_ROOT / "data/derived/qb_elo_season_regression_v1",
        dst / "data/derived/qb_elo_season_regression_v1",
    )
    (dst / "config").mkdir(parents=True, exist_ok=True)
    _sh.copy2(REPO_ROOT / "config/qb_elo_v1.yaml", dst / "config/qb_elo_v1.yaml")
    return dst


def _official_metrics_fake() -> dict:
    base = {
        "week1_4": {"n_scored": 445.0, "brier": 0.23, "log_loss": 0.66, "accuracy": 0.60},
        "weeks5plus": {"n_scored": 1410.0, "brier": 0.22, "log_loss": 0.63, "accuracy": 0.65},
        "reg": {"n_scored": 1855.0, "brier": 0.22, "log_loss": 0.63, "accuracy": 0.64},
        "postseason": {"n_scored": 87.0, "brier": 0.22, "log_loss": 0.64, "accuracy": 0.62},
        "full": {"n_scored": 1942.0, "brier": 0.22, "log_loss": 0.63, "accuracy": 0.64},
        "season_week1_4": {str(y): {"n_scored": 63.0, "brier": 0.24, "log_loss": 0.67, "accuracy": 0.59}
                           for y in [2018, 2019, 2020, 2021, 2022, 2023, 2024]},
    }
    out = {}
    for label in ("regression_000", "regression_025", "regression_040",
                  "regression_060", "task04c_reference_0333"):
        m = dict(base)
        m["label"] = label
        m["fraction"] = _OFFICIAL.CANDIDATE_FRACTIONS[label]
        m["role"] = _OFFICIAL.ROLE[label]
        out[label] = m
    return out


def _patch_official(monkeypatch, *, identity=True, pair=True, sanity=True,
                    audit_pass=True, replay=True) -> dict:
    metrics = _official_metrics_fake()

    def fake_run_candidate(root, out_root, label, oracle, base_config):
        audit = pl.DataFrame({"status": ["PASS"] if audit_pass else ["FAIL"]})
        return {
            "label": label, "fraction": _OFFICIAL.CANDIDATE_FRACTIONS[label],
            "role": _OFFICIAL.ROLE[label],
            "preds": pl.DataFrame({"game_id": ["G"]}),
            "state": pl.DataFrame({"game_id": ["G"]}),
            "artifact": pl.DataFrame({"game_id": ["G"]}),
            "audit": audit, "run_dir": str(out_root / "runs" / label),
        }

    monkeypatch.setattr(_OFFICIAL, "run_candidate", fake_run_candidate)
    monkeypatch.setattr(_OFFICIAL, "collect_metrics", lambda res: metrics[res["label"]])
    monkeypatch.setattr(_OFFICIAL, "verify_identity",
                        lambda res, committed: {"identity_passed": identity})
    monkeypatch.setattr(_OFFICIAL, "pairability",
                        lambda results: {"pairable": pair, "matrix": {}})
    monkeypatch.setattr(_OFFICIAL, "pre_boundary_sanity",
                        lambda results: {"passed": sanity, "checks": {}})
    monkeypatch.setattr(
        _OFFICIAL, "replay_check",
        lambda results, root, out_root, oracle, base_config, labels: {
            lb: {"game_id_order_identical": replay, "max_prob_diff": 0.0,
                 "metrics_equal": replay} for lb in labels
        },
    )
    return metrics


@pytest.mark.parametrize("kwargs,expect_fail", [
    ({"identity": False}, True),
    ({"pair": False}, True),
    ({"sanity": False}, True),
    ({"audit_pass": False}, True),
    ({"replay": False}, True),
    ({"identity": True, "pair": True, "sanity": True, "audit_pass": True, "replay": True}, False),
])
def test_official_workflow_gate_nonzero_on_failure(tmp_path, monkeypatch, kwargs, expect_fail):
    _patch_official(monkeypatch, **kwargs)
    out = tmp_path / "official_out"
    rc = _OFFICIAL.main(["--project-root", str(REPO_ROOT), "--out", str(out)])
    if expect_fail:
        assert rc != 0
    else:
        assert rc == 0
    assert (out / "summary.json").exists()


def test_finalize_reconciliation_false_returns_nonzero(tmp_path, monkeypatch):
    root = _fixture_root(tmp_path)
    out = root / "data/derived/qb_elo_season_regression_v1"
    bad = pl.DataFrame([{
        "mean_brier_delta": 0.5, "aggregate_brier_equiv": -0.5,
        "candidate": "x", "reference": "y", "segment": "full",
    }])
    bad.write_parquet(out / "paired_comparisons.parquet")
    assert _FINALIZE.main(["--project-root", str(root)]) != 0


def test_finalize_reproducibility_false_returns_nonzero(tmp_path, monkeypatch):
    root = _fixture_root(tmp_path)
    out = root / "data/derived/qb_elo_season_regression_v1"
    stored = pl.read_parquet(out / "predictions_regression_000.parquet")
    stored.head(100).write_parquet(out / "predictions_regression_000.parquet")
    assert _FINALIZE.main(["--project-root", str(root)]) != 0


def test_finalize_transition_audit_false_returns_nonzero(tmp_path, monkeypatch):
    root = _fixture_root(tmp_path)
    out = root / "data/derived/qb_elo_season_regression_v1"
    audit = pl.read_parquet(out / "season_boundary_audit_all.parquet")
    audit.with_columns(pl.lit("FAIL").alias("status")).write_parquet(
        out / "season_boundary_audit_all.parquet")
    assert _FINALIZE.main(["--project-root", str(root)]) != 0


def test_finalize_seal_2025_false_returns_nonzero(tmp_path, monkeypatch):
    root = _fixture_root(tmp_path)
    out = root / "data/derived/qb_elo_season_regression_v1"
    stored = pl.read_parquet(out / "predictions_regression_000.parquet")
    dt = stored["season"].dtype
    first = stored.head(1).with_columns(pl.lit(2025, dtype=dt).alias("season"))
    rest = stored.tail(stored.height - 1)
    pl.concat([first, rest], how="vertical").write_parquet(
        out / "predictions_regression_000.parquet")
    assert _FINALIZE.main(["--project-root", str(root)]) != 0


def test_finalize_config_mismatch_returns_nonzero(tmp_path, monkeypatch):
    root = _fixture_root(tmp_path)
    monkeypatch.setattr(
        _FINALIZE, "load_canonical_config",
        lambda root_dir: {"season_mean_reversion_fraction": 0.25},
    )
    assert _FINALIZE.main(["--project-root", str(root)]) != 0


def test_finalize_all_pass_returns_zero(tmp_path):
    root = _fixture_root(tmp_path)
    assert _FINALIZE.main(["--project-root", str(root)]) == 0
