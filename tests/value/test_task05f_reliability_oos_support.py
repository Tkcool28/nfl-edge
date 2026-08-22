from nfl_edge.value.contracts import ReliabilityState
from nfl_edge.value.reliability import make_evidence, reliability_tier


def test_reliability_cold_start_is_supported_low_not_unsupported():
    state = ReliabilityState(radius=None, support_n=0, block_count=0, stable=False)
    evidence = make_evidence(
        support_n=700,
        support_distance=0.0,
        constituent_disagreement=0.01,
        reliability_state=state,
    )
    assert evidence.support_n == 0
    assert reliability_tier(evidence) == "LOW"


def test_reliability_tier_cannot_outrun_accepted_oos_support():
    state = ReliabilityState(radius=0.02, support_n=128, block_count=10, stable=True)
    evidence = make_evidence(
        support_n=700,
        support_distance=0.0,
        constituent_disagreement=0.01,
        reliability_state=state,
    )
    assert evidence.support_n == 128
    assert reliability_tier(evidence) == "LOW"


def test_reliability_tier_promotes_when_fit_and_oos_support_both_exist():
    state = ReliabilityState(radius=0.02, support_n=600, block_count=50, stable=True)
    evidence = make_evidence(
        support_n=700,
        support_distance=0.0,
        constituent_disagreement=0.01,
        reliability_state=state,
    )
    assert evidence.support_n == 600
    assert reliability_tier(evidence) == "HIGH"
