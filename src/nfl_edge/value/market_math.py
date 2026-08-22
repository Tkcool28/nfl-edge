"""Price, shopping, and no-vig primitives for Task05F."""
from __future__ import annotations

import math
from .contracts import NormalizedOffer

BOOK_ORDER = ("draftkings", "fanduel")


def american_to_decimal(a: int | float) -> float:
    if float(a) == 0.0:
        raise ValueError("American odds cannot be zero")
    return 1.0 + (float(a) / 100.0 if a > 0 else 100.0 / abs(float(a)))


def decimal_to_american(d: float) -> int:
    if d <= 1.0:
        raise ValueError("decimal odds must be > 1")
    return int(round((d - 1.0) * 100.0 if d >= 2.0 else -100.0 / (d - 1.0)))


def break_even_probability(a: int | float) -> float:
    return 1.0 / american_to_decimal(a)


def proportional_no_vig(price_a: int, price_b: int) -> tuple[float, float]:
    qa = break_even_probability(price_a)
    qb = break_even_probability(price_b)
    den = qa + qb
    if den <= 0:
        raise ValueError("invalid paired prices")
    return qa / den, qb / den


def normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(float(z) / math.sqrt(2.0)))


def clip_probability(p: float, lo: float = 0.01, hi: float = 0.99) -> float:
    return min(float(hi), max(float(lo), float(p)))


def _book_rank(book: str) -> int:
    try:
        return BOOK_ORDER.index(book)
    except ValueError:
        return len(BOOK_ORDER)


def shop_moneyline(offers: list[NormalizedOffer]) -> NormalizedOffer | None:
    return max(offers, key=lambda o: (o.price_american, -_book_rank(o.book)), default=None)


def shop_spread(offers: list[NormalizedOffer]) -> NormalizedOffer | None:
    if not offers:
        return None
    best_line = max(float(o.line) for o in offers if o.line is not None)
    same = [o for o in offers if o.line is not None and float(o.line) == best_line]
    return max(same, key=lambda o: (o.price_american, -_book_rank(o.book)))


def shop_total(side: str, offers: list[NormalizedOffer]) -> NormalizedOffer | None:
    if not offers:
        return None
    lines = [float(o.line) for o in offers if o.line is not None]
    best_line = min(lines) if side.lower() == "over" else max(lines)
    same = [o for o in offers if o.line is not None and float(o.line) == best_line]
    return max(same, key=lambda o: (o.price_american, -_book_rank(o.book)))


def offer_vs_benchmark(offer: NormalizedOffer, benchmark: NormalizedOffer | None) -> dict[str, bool | None]:
    if benchmark is None:
        return {
            "better_number": None,
            "same_number_better_price": None,
            "better_number_and_price": None,
            "worse_or_equal": None,
        }
    price_better = int(offer.price_american) > int(benchmark.price_american)
    if offer.market_type == "moneyline":
        number_better = False
        same_number = True
    elif offer.market_type == "spread":
        number_better = float(offer.line) > float(benchmark.line)
        same_number = float(offer.line) == float(benchmark.line)
    elif offer.side.lower() == "over":
        number_better = float(offer.line) < float(benchmark.line)
        same_number = float(offer.line) == float(benchmark.line)
    else:
        number_better = float(offer.line) > float(benchmark.line)
        same_number = float(offer.line) == float(benchmark.line)
    return {
        "better_number": number_better,
        "same_number_better_price": same_number and price_better,
        "better_number_and_price": number_better and price_better,
        "worse_or_equal": not (number_better or (same_number and price_better)),
    }
