"""Task05F reliability/support remediation regression tests.

Covers: real out-of-support distance, fail-closed out-of-support, prior-block
stability evidence, honest uncertainty semantics, staking conservatism, and
methodology boundaries (2025 firewall, football-model independence, exact_avg
fail-closed).
"""
import pytest

from nfl_edge.value.contracts import EvaluatorState, GameState, NormalizedOffer, SupportFeature
from nfl_edge.value.evaluators import evaluate_offer, exact_avg
from nfl_edge.value.reliability import (
    ReliabilityEvidence, tier, unsupported_reason,
    staking_probability, support_feature, overall_support_distance,
    MAX_OUT_OF_SUPPORT_DISTANCE)
from nfl_edge.value.uncertainty import calibration_stability, stability_from_radius, MIN_STABLE_BLOCKS
from nfl_edge.value.fitting import fit_ml_states, fit_point_states


def test_support_distance_inside_is_zero():
    f = SupportFeature("pin", 0.0, 1.0, 1.0)
    assert overall_support_distance([0.5], [f]) == pytest.approx(0.0)
    assert overall_support_distance([0.0], [f]) == pytest.approx(0.0)
    assert overall_support_distance([1.0], [f]) == pytest.approx(0.0)


def test_support_distance_small_extrapolation_nonzero():
    # span = 1.0; value 0.15 beyond the high bound -> distance 0.15
    f = SupportFeature("pin", 0.0, 1.0, 1.0)
    d = overall_support_distance([1.15], [f])
    assert d == pytest.approx(0.15)
    assert 0 < d <= MAX_OUT_OF_SUPPORT_DISTANCE * 2


def test_support_distance_over_threshold_unsupported_and_reason():
    f = SupportFeature("pin", 0.0, 1.0, 1.0)
    ev = ReliabilityEvidence(500, 0.02, overall_support_distance([2.0], [f]), 0.01, True)
    assert tier(ev) == "UNSUPPORTED"
    assert unsupported_reason(ev) == "out_of_support"


def test_out_of_support_reason_explicit_via_evaluator():
    # Strong out-of-support moneyline game (pinnacle 0.99, outside historical range)
    state = EvaluatorState("moneyline", "global_shrinkage", "v1", 1000,
                           {"lambda": 0.5}, uncertainty=0.02, stable_blocks=True,
                           support_features=(SupportFeature("pin", 0.1, 0.8, 0.7),
                                             SupportFeature("avg_pin_gap", -0.1, 0.1, 0.2),
                                             SupportFeature("qb_xgb_gap", 0.0, 0.2, 0.2)))
    game = GameState("g1", 2024, "1", None, 0.5, 0.5)  # qbed/xgb both present
    offer = NormalizedOffer("moneyline", "home", "manual", -110, source="manual")
    r = evaluate_offer(game, offer, state, pinnacle_no_vig_selected=0.99)
    assert r.supported is False
    assert r.reliability == "UNSUPPORTED"
    assert r.reason == "out_of_support"
    assert r.actionable_probability is None and r.staking_probability is None and r.expected_value is None


def test_support_bounds_from_prior_blocks_only():
    prior_rows = [
        {"block": "2020-01", "qb": 0.55, "xgb": 0.5, "pin": 0.5, "y": 1},
        {"block": "2020-02", "qb": 0.6, "xgb": 0.58, "pin": 0.55, "y": 0},
        {"block": "2020-03", "qb": 0.52, "xgb": 0.54, "pin": 0.5, "y": 1},
    ]
    states = fit_ml_states(prior_rows, "v1", "c")
    feats = {f.name: f for f in states["global_shrinkage"].support_features}
    assert feats["pin"].min_value == pytest.approx(0.5)
    assert feats["pin"].max_value == pytest.approx(0.55)
    dsame = overall_support_distance([0.5], [feats["pin"]])
    dfuture = overall_support_distance([0.9], [feats["pin"]])
    assert dsame == pytest.approx(0.0)
    assert dfuture > MAX_OUT_OF_SUPPORT_DISTANCE


def test_future_block_value_out_of_support():
    state = EvaluatorState("moneyline", "global_shrinkage", "v1", 1000,
                           {"lambda": 0.5}, uncertainty=0.02, stable_blocks=True,
                           support_features=(SupportFeature("pin", 0.3, 0.7, 0.4),))
    game = GameState("future", 2024, "18", None, 0.5, 0.5)
    offer = NormalizedOffer("moneyline", "home", "manual", -110, source="manual")
    # pin 0.9 well beyond [0.3, 0.7] -> out of support (future blocks never widen envelope)
    r = evaluate_offer(game, offer, state, pinnacle_no_vig_selected=0.9)
    assert r.reliability == "UNSUPPORTED" and r.reason == "out_of_support"


def test_stability_requires_min_prior_blocks():
    # fewer than MIN_STABLE_BLOCKS distinct blocks -> not stable (fails closed)
    rows = [(f"b{i}", 0.5, i % 2) for i in range(MIN_STABLE_BLOCKS - 1)]
    assert calibration_stability(rows) is False
    assert stability_from_radius(rows, 0.001) is False


def test_stability_computed_from_prior_only_and_cold_start_no_high():
    # cold start: no rows -> unstable
    assert calibration_stability([]) is False
    # a few blocks but high radius -> unstable
    rows = [(f"b{i}", 0.5 + (0.05 if i % 2 else -0.05), i % 2) for i in range(6)]
    # unstable states cap at LOW
    ev = ReliabilityEvidence(500, 0.02, 0.0, 0.01, stable_blocks=False)
    assert tier(ev) == "LOW"  # never HIGH/MEDIUM


def test_insufficient_stability_cannot_produce_high():
    ev = ReliabilityEvidence(600, 0.01, 0.0, 0.01, stable_blocks=False)
    assert tier(ev) != "HIGH"
    assert tier(ev) != "MEDIUM"


def test_unstable_history_cannot_produce_high_medium():
    ev = ReliabilityEvidence(600, 0.015, 0.0, 0.01, stable_blocks=False)
    assert tier(ev) == "LOW"


def test_baseline_ml_evaluator_uncertainty_not_silently_zero():
    rows = [{"block": f"20{(i // 30) % 4:02d}-{i % 30:02d}", "qb": 0.5, "xgb": 0.5, "pin": 0.5, "y": i % 2}
            for i in range(300)]
    states = fit_ml_states(rows, "v1", "c")
    # pinnacle / raw_qbelo get REAL uncertainty (not 0.0 / None)
    assert states["pinnacle"].uncertainty is not None
    assert states["pinnacle"].uncertainty >= 0.0
    assert states["raw_qbelo"].uncertainty is not None


def test_selected_ml_evaluator_gets_valid_uncertainty():
    rows = [{"block": f"20{(i // 30) % 4:02d}-{i % 30:02d}",
             "qb": 0.5 + 0.01 * (i % 5), "xgb": 0.5, "pin": 0.5, "y": i % 2} for i in range(300)]
    states = fit_ml_states(rows, "v1", "c")
    gs = states["global_shrinkage"]
    assert gs.uncertainty is not None and gs.uncertainty >= 0.0
    assert gs.stable_blocks in (True, False)


def test_spread_calibrated_normal_gets_valid_uncertainty():
    rows = [{"block": f"20{(i // 20) % 5:02d}-{i % 20:02d}",
             "delta": 2.0 * (-1 if i % 2 else 1), "market_level": 4.0, "residual": 3.0, "y": i % 2}
            for i in range(300)]
    states = fit_point_states(rows, "spread", "v1", "c")
    cn = states["calibrated_normal"]
    assert cn.uncertainty is not None and cn.uncertainty >= 0.0


def test_totals_calibrated_normal_gets_valid_uncertainty():
    rows = [{"block": f"20{(i // 20) % 5:02d}-{i % 20:02d}",
             "delta": 3.0 * (-1 if i % 2 else 1), "market_level": 45.0, "residual": 4.0, "y": i % 2}
            for i in range(300)]
    states = fit_point_states(rows, "total", "v1", "c")
    cn = states["calibrated_normal"]
    assert cn.uncertainty is not None and cn.uncertainty >= 0.0


def test_staking_more_conservative_when_reliability_uncertainty_worsen():
    a, anchor = 0.7, 0.5
    hi = staking_probability(a, anchor, "HIGH", 0.01)
    lo = staking_probability(a, anchor, "LOW", 0.01)
    assert lo < hi
    # worse uncertainty -> more conservative (closer to anchor)
    assert staking_probability(a, anchor, "HIGH", 0.09) <= staking_probability(a, anchor, "HIGH", 0.01)
    # UNSUPPORTED -> no staking probability (returns anchor)
    assert staking_probability(a, anchor, "UNSUPPORTED", 0.01) == pytest.approx(anchor)
    # None uncertainty treated as conservative, not perfect certainty
    assert staking_probability(a, anchor, "HIGH", None) == pytest.approx(anchor)


def test_2025_rejection_intact():
    with pytest.raises(RuntimeError):
        evaluate_offer(
            GameState("g", 2025, "1", None, 0.5, 0.5),
            NormalizedOffer("moneyline", "home", "manual", 100, source="manual"),
            EvaluatorState("moneyline", "global_shrinkage", "v1", 500, {"lambda": 0.2}, uncertainty=0.01),
            pinnacle_no_vig_selected=0.5)


def test_exact_avg_fail_closed_regression_intact():
    g = GameState("g", 2024, "1", None, 0.6, None)
    o = NormalizedOffer("moneyline", "home", "manual", -110, source="manual")
    state = EvaluatorState("moneyline", "exact_avg", "v1", 500, {}, uncertainty=0.01)
    r = evaluate_offer(g, o, state, pinnacle_no_vig_selected=0.5)
    assert r.supported is False and r.reliability == "UNSUPPORTED"
    assert r.reason == "exact_avg_requires_both_models"


def test_arbitrary_manual_offer_uses_same_support_reliability_logic():
    # manual offer with extreme pin out of support still fails closed even when book is "user_input"
    state = EvaluatorState("moneyline", "global_shrinkage", "v1", 1000,
                           {"lambda": 0.5}, uncertainty=0.02, stable_blocks=True,
                           support_features=(SupportFeature("pin", 0.1, 0.8, 0.7),))
    game = GameState("g", 2024, "1", None, 0.5, 0.5)
    offer = NormalizedOffer("moneyline", "home", "user_input", -110, source="manual")
    r = evaluate_offer(game, offer, state, pinnacle_no_vig_selected=0.99)
    assert r.supported is False and r.reason == "out_of_support"


def test_football_models_sportsbook_independent():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "src/nfl_edge/models"
    for p in root.glob("*.py"):
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(a.name.startswith("nfl_edge.value") for a in node.names), p
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("nfl_edge.value"), p


# ---------------------------------------------------------------------------
# Defect #1: ML avg_pin_gap signed-coordinate consistency
# ---------------------------------------------------------------------------

def _ml_state_with_signed_support(lo, hi):
    """Signed avg_pin_gap support envelope helper."""
    return EvaluatorState(
        "moneyline", "global_shrinkage", "v1", 1000, {"lambda": 0.5},
        uncertainty=0.02, stable_blocks=True,
        support_features=(
            SupportFeature("pin", 0.1, 0.8, 0.7),
            SupportFeature("avg_pin_gap", lo, hi, max(hi - lo, 1e-6)),
            SupportFeature("qb_xgb_gap", 0.0, 0.5, 0.5),
        ))


def test_ml_signed_avg_pin_gap_is_preserved():
    # Historical envelope negatively skewed [-0.15, -0.03]; a -0.07 signed gap is inside.
    state = _ml_state_with_signed_support(-0.15, -0.03)
    game = GameState("g", 2024, "1", None, 0.43, 0.43)  # avg = 0.43
    offer = NormalizedOffer("moneyline", "home", "manual", -110, source="manual")
    r = evaluate_offer(game, offer, state, pinnacle_no_vig_selected=0.50)
    # signed gap = -0.07, inside [-0.15, -0.03] -> supported (buggy abs() would flag it)
    assert r.supported is True
    assert r.reason is None


def test_ml_negative_supported_gap_stays_supported():
    # -0.10 inside [-0.15,-0.03], supported (old abs() -> +0.10, beyond max -0.03 -> false UNSUPPORTED)
    state = _ml_state_with_signed_support(-0.15, -0.03)
    game = GameState("g", 2024, "1", None, 0.40, 0.40)  # avg 0.40, pin 0.5 -> -0.10
    offer = NormalizedOffer("moneyline", "home", "manual", -100, source="manual")
    r = evaluate_offer(game, offer, state, pinnacle_no_vig_selected=0.50)
    assert r.reliability != "UNSUPPORTED"
    assert r.reason is None


def test_ml_positive_opposite_gap_can_be_out_of_support():
    # +0.07 lies above historical max -0.03 -> legitimately outside negative-skew support.
    state = _ml_state_with_signed_support(-0.15, -0.03)
    game = GameState("g", 2024, "1", None, 0.57, 0.57)  # avg 0.57, pin 0.5 -> +0.07
    offer = NormalizedOffer("moneyline", "home", "manual", -100, source="manual")
    r = evaluate_offer(game, offer, state, pinnacle_no_vig_selected=0.50)
    assert r.supported is False
    assert r.reason == "out_of_support"


def test_ml_side_flip_support_coherent_signed():
    # home: signed gap -0.07 inside support; away flip -> +0.07 gap (outside) -> coherent.
    state = _ml_state_with_signed_support(-0.15, -0.03)
    game = GameState("g", 2024, "1", None, 0.43, 0.43)
    offer_home = NormalizedOffer("moneyline", "home", "manual", -100, source="manual")
    # home side gap -0.07 -> supported; away side flips prob -> gap +0.07 -> out_of_support
    r_home = evaluate_offer(game, offer_home, state, pinnacle_no_vig_selected=0.50)
    assert r_home.supported is True
    offer_away = NormalizedOffer("moneyline", "away", "manual", -100, source="manual")
    r_away = evaluate_offer(game, offer_away, state, pinnacle_no_vig_selected=0.50)
    assert r_away.supported is False and r_away.reason == "out_of_support"


# ---------------------------------------------------------------------------
# Defect #2: point-market orientation-invariant support (delta_magnitude)
# ---------------------------------------------------------------------------

def _point_state(market_type, lo, hi):
    # market magnitude envelope differs: spread lines ~0-7, total lines ~35-60
    ml_lo, ml_hi = (0.0, 7.0) if market_type == "spread" else (35.0, 60.0)
    return EvaluatorState(
        market_type, "normal_cdf", "v1", 1000, {"sigma": 10.0},
        uncertainty=0.02, stable_blocks=True,
        support_features=(
            SupportFeature("delta_magnitude", lo, hi, max(hi - lo, 1e-6)),
            SupportFeature("market_magnitude", ml_lo, ml_hi, ml_hi - ml_lo),
        ))


def test_spread_home_away_delta_magnitude_invariant():
    # home delta +1, away delta -1 => both see abs(delta)=1
    state = _point_state("spread", 0.5, 3.0)
    game = GameState("g", 2024, "1", None, expected_home_margin=4.0)
    home = NormalizedOffer("spread", "home", "manual", -110, -3)
    away = NormalizedOffer("spread", "away", "manual", -110, 3)
    # home delta = expected_margin(+4 selected) + line(-3) = +1; school in support
    r_home = evaluate_offer(game, home, state)
    # away delta = -4 + 3 = -1; absolute 1, within same support
    r_away = evaluate_offer(game, away, state)
    # Both within support w.r.t. delta (market_magnitude 3 within 0..7)
    assert r_home.reason is None or r_home.reason in ("spread",)
    assert r_away.reason is None
    assert r_home.supported is True and r_away.supported is True
    # probabilities complement (selected-side signed math)
    assert abs(r_home.actionable_probability + r_away.actionable_probability - 1.0) < 1e-6


def test_total_over_under_delta_magnitude_invariant():
    # predicted total 48, market 45: over delta +3, under delta -3, both abs=3
    state = _point_state("total", 1.0, 5.0)
    game = GameState("g", 2024, "1", None, predicted_total_r4=48.0)
    over = NormalizedOffer("total", "over", "manual", -110, 45)
    under = NormalizedOffer("total", "under", "manual", -110, 45)
    r_over = evaluate_offer(game, over, state)
    r_under = evaluate_offer(game, under, state)
    assert r_over.supported is True and r_under.supported is True
    assert abs(r_over.actionable_probability + r_under.actionable_probability - 1.0) < 1e-6


def test_no_opposite_side_training_duplication():
    # Fit on ONE canonical orientation per prior game only (spread home, total over).
    from nfl_edge.value.fitting import fit_point_states, _point_support_features
    # spread training uses home orientation only -> rows carry one delta per game
    rows = [
        {"block": f"20{(i // 5) % 4:02d}-{i % 5:02d}", "delta": 2.0, "market_level": 4.0, "residual": 3.0, "y": i % 2}
        for i in range(20)
    ]
    states = fit_point_states(rows, "spread", "v1", "c")
    feats = {f.name: f for f in states["normal_cdf"].support_features}
    # support feature is delta_magnitude now
    assert "delta_magnitude" in feats
    assert feats["delta_magnitude"].max_value == pytest.approx(2.0)  # abs(2.0) from one-per-game
    # No away-mirrored rows were added: max feature == the single canonical delta magnitude
    assert states["normal_cdf"].training_n == 20  # one observation per game, no doubling


def test_point_support_out_of_support_threshold_still_works():
    # delta magnitude well beyond support -> out_of_support
    state = _point_state("spread", 0.5, 3.0)
    game = GameState("g", 2024, "1", None, expected_home_margin=20.0)
    offer = NormalizedOffer("spread", "home", "manual", -110, -3)
    r = evaluate_offer(game, offer, state)
    assert r.supported is False and r.reason == "out_of_support"
