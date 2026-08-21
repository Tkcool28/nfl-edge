import pytest
from nfl_edge.value.contracts import CANDIDATE_COLUMNS,EvaluatorState,GameState,NormalizedOffer,candidate_row
from nfl_edge.value.evaluators import evaluate_offer,exact_avg
from nfl_edge.value.market_math import proportional_no_vig,shop_spread,shop_total,offer_vs_benchmark
from nfl_edge.value.reliability import ReliabilityEvidence,tier

def state(mt,fam,**p):return EvaluatorState(mt,fam,"v1",512,p,uncertainty=.01)
def test_exact_avg_requires_both():
 g=GameState("g",2024,"1",None,.6,None);assert exact_avg(g,"home") is None
 g=GameState("g",2024,"1",None,.6,.4);assert exact_avg(g,"home")==pytest.approx(.5)
def test_no_vig_math():
 a,b=proportional_no_vig(-110,-110);assert a==pytest.approx(.5) and b==pytest.approx(.5)
def test_ml_orientation_and_two_probs():
 g=GameState("g",2024,"1",None,.6,.58);o=NormalizedOffer("moneyline","away","manual",120,source="manual")
 r=evaluate_offer(g,o,state("moneyline","global_shrinkage",**{"lambda":.5}),pinnacle_no_vig_selected=.45)
 assert .4<r.actionable_probability<.5 and r.staking_probability is not None
def test_spread_sign_semantics():
 g=GameState("g",2024,"1",None,expected_home_margin=6);home=NormalizedOffer("spread","home","manual",-110,-3)
 away=NormalizedOffer("spread","away","manual",-110,3)
 assert evaluate_offer(g,home,state("spread","normal_cdf",sigma=10)).actionable_probability>.5
 assert evaluate_offer(g,away,state("spread","normal_cdf",sigma=10)).actionable_probability<.5
def test_total_sign_semantics():
 g=GameState("g",2024,"1",None,predicted_total_r4=48)
 assert evaluate_offer(g,NormalizedOffer("total","over","manual",-110,45),state("total","normal_cdf",sigma=10)).actionable_probability>.5
 assert evaluate_offer(g,NormalizedOffer("total","under","manual",-110,45),state("total","normal_cdf",sigma=10)).actionable_probability<.5
def test_shopping_rules():
 xs=[NormalizedOffer("spread","home","draftkings",-115,3.5),NormalizedOffer("spread","home","fanduel",-105,3)]
 assert shop_spread(xs).book=="draftkings"
 ovs=[NormalizedOffer("total","over","draftkings",-115,45),NormalizedOffer("total","over","fanduel",-105,45.5)]
 assert shop_total("over",ovs).book=="draftkings"
def test_reliability_fail_closed():assert tier(ReliabilityEvidence(10,.01))=="UNSUPPORTED"
def test_2025_hard_rejection():
 with pytest.raises(RuntimeError):evaluate_offer(GameState("g",2025,"1",None,.5,.5),NormalizedOffer("moneyline","home","manual",100),state("moneyline","global_shrinkage",**{"lambda":.2}),pinnacle_no_vig_selected=.5)
def test_arbitrary_manual_offer_compatible():
 o=NormalizedOffer("spread","home","user_input",-105,-2.5,source="manual");assert o.source=="manual"
def test_color_support():
 o=NormalizedOffer("spread","home","draftkings",-110,3.5);p=NormalizedOffer("spread","home","pinnacle",-115,3)
 flags=offer_vs_benchmark(o,p);assert flags["better_number_and_price"]
def test_candidate_schema_exact():
 vals={c:None for c in CANDIDATE_COLUMNS};vals.update(game_id="g",season=2024,week="1",market_type="moneyline",selected_side="home")
 assert tuple(candidate_row(**vals))==CANDIDATE_COLUMNS
