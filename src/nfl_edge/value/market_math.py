from __future__ import annotations
import math
from .contracts import NormalizedOffer
BOOK_ORDER = ("draftkings", "fanduel")

def american_to_decimal(a: int | float) -> float:
    if a == 0: raise ValueError("American odds cannot be zero")
    return 1.0 + (float(a)/100.0 if a > 0 else 100.0/abs(float(a)))

def decimal_to_american(d: float) -> int:
    if not 1.0 < d: raise ValueError("decimal odds must be >1")
    return int(round((d-1.0)*100.0 if d >= 2.0 else -100.0/(d-1.0)))

def probability_to_fair_american(p: float) -> int:
    if not 0 < p < 1: raise ValueError("probability must be in (0,1)")
    return decimal_to_american(1.0/p)

def break_even_probability(a: int | float) -> float: return 1.0/american_to_decimal(a)
def expected_value_per_unit(p: float, a: int | float) -> float: return p*american_to_decimal(a)-1.0

def proportional_no_vig(price_a: int, price_b: int) -> tuple[float,float]:
    qa,qb=break_even_probability(price_a),break_even_probability(price_b); s=qa+qb
    return qa/s,qb/s

def normal_cdf(z: float) -> float: return 0.5*(1.0+math.erf(z/math.sqrt(2.0)))
def clip_probability(p: float, lo: float=.01, hi: float=.99) -> float: return min(hi,max(lo,p))

def _book_rank(book: str) -> int:
    try: return BOOK_ORDER.index(book)
    except ValueError: return len(BOOK_ORDER)

def shop_moneyline(offers: list[NormalizedOffer]) -> NormalizedOffer | None:
    return max(offers, key=lambda o:(o.price_american,-_book_rank(o.book)), default=None)
def shop_spread(offers: list[NormalizedOffer]) -> NormalizedOffer | None:
    if not offers: return None
    best=max(o.line for o in offers); xs=[o for o in offers if o.line==best]
    return max(xs,key=lambda o:(o.price_american,-_book_rank(o.book)))
def shop_total(side: str, offers: list[NormalizedOffer]) -> NormalizedOffer | None:
    if not offers:return None
    best=(min if side.lower()=="over" else max)(o.line for o in offers)
    xs=[o for o in offers if o.line==best]
    return max(xs,key=lambda o:(o.price_american,-_book_rank(o.book)))

def offer_vs_benchmark(offer: NormalizedOffer, benchmark: NormalizedOffer | None) -> dict[str,bool|None]:
    if benchmark is None:return {"better_number":None,"same_number_better_price":None,"better_number_and_price":None,"worse_or_equal":None}
    price_better=offer.price_american>benchmark.price_american
    if offer.market_type=="moneyline": number_better=False
    elif offer.market_type=="spread": number_better=float(offer.line)>float(benchmark.line)
    elif offer.side.lower()=="over": number_better=float(offer.line)<float(benchmark.line)
    else: number_better=float(offer.line)>float(benchmark.line)
    same=offer.line==benchmark.line
    return {"better_number":number_better,"same_number_better_price":same and price_better,"better_number_and_price":number_better and price_better,"worse_or_equal":not(number_better or (same and price_better))}
