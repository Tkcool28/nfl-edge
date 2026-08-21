"""Deterministic actionable line/price shopping for Task 05E.

Implements the frozen `actionable_price` rule from the preregistration config:

* SPREAD : normalize to the selected side; choose the NUMERICALLY GREATEST
           selected-side spread first (e.g. +3.5 > +3 ; -2.5 > -3); if the
           line is identical choose the BETTER price; if still identical use a
           deterministic fixed book tie-break.
* TOTAL OVER  : take the LOWEST total line first; if identical choose the
                better price.
* TOTAL UNDER : take the HIGHEST total line first; if identical choose the
                better price.

Shopping NEVER consults outcomes (frozen pre-outcome), and Pinnacle is NEVER
substituted as an actionable book.

The authoritative census already encodes the result of this rule in
``act_line`` / ``act_price`` / ``act_book``. These functions provide the
canonical implementation of the rule (and its unit tests) so the ordering is
documented, deterministic, and reproducible from raw per-book offers.
"""

from __future__ import annotations

from dataclasses import dataclass

# Deterministic fixed book tie-break order (frozen).
FIXED_BOOK_ORDER = ("draftkings", "fanduel")


@dataclass(frozen=True)
class Offer:
    book: str
    line: float
    price_american: int


def _best_price(offers: list[Offer]) -> Offer | None:
    """Better American price = larger payoff. Deterministic book tie-break."""
    if not offers:
        return None
    best = offers[0]
    for off in offers[1:]:
        if off.price_american > best.price_american:
            best = off
        elif off.price_american == best.price_american:
            if FIXED_BOOK_ORDER.index(off.book) < FIXED_BOOK_ORDER.index(best.book):
                best = off
    return best


def shop_spread(offers: list[Offer]) -> Offer | None:
    """Selected-side spread shopping: best number first, then better price."""
    if not offers:
        return None
    best_number = max(off.line for off in offers)
    views = [off for off in offers if off.line == best_number]
    return _best_price(views)


def shop_total(selected_side: str, offers: list[Offer]) -> Offer | None:
    """Total shopping. OVER takes the LOWEST line first; UNDER the HIGHEST."""
    if not offers:
        return None
    if selected_side == "over":
        line = min(off.line for off in offers)
    else:  # under
        line = max(off.line for off in offers)
    views = [off for off in offers if off.line == line]
    return _best_price(views)