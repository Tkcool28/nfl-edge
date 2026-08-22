"""Account-aware Task05F product presentation helpers.

Core evaluated candidates stay account-independent. These helpers apply the
user's one global staking profile to candidates and Selector V3 primary cards
without changing any market/evaluator/selector field.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from nfl_edge.user.staking_profile import UserStakingProfile
from nfl_edge.value.candidate_table import OUTCOME_FIELDS
from nfl_edge.value.selectors import PRIMARY_CARDS
from nfl_edge.value.selectors_v3 import select_primary_cards_v3
from nfl_edge.value.staking import recommend_stake


PRODUCT_VIEW_VERSION = "task05f_product_view_v1"


def _clean_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(candidate)
    leaked = OUTCOME_FIELDS.intersection(row)
    if leaked:
        raise RuntimeError(
            f"product candidate contains forbidden historical outcome fields: {sorted(leaked)}"
        )
    return row


def user_candidate_view(
    candidate: Mapping[str, Any],
    profile: UserStakingProfile,
) -> dict[str, Any]:
    """Attach one account-specific stake recommendation to one core candidate."""
    core = _clean_candidate(candidate)
    stake = recommend_stake(core, profile).to_dict()
    return {
        "product_view_version": PRODUCT_VIEW_VERSION,
        "candidate": core,
        "staking": stake,
    }


def build_primary_card_views(
    candidate_rows: Iterable[Mapping[str, Any]],
    profile: UserStakingProfile,
) -> dict[str, dict[str, Any] | None]:
    """Select V3 primary cards, then apply the user's global staking strategy."""
    rows = [_clean_candidate(row) for row in candidate_rows]
    picks = select_primary_cards_v3(rows)
    return {
        card: None if picks[card] is None else user_candidate_view(picks[card], profile)
        for card in PRIMARY_CARDS
    }


def build_explorer_views(
    candidate_rows: Iterable[Mapping[str, Any]],
    profile: UserStakingProfile,
) -> list[dict[str, Any]]:
    """Return deterministic account-aware views for every game-explorer wager."""
    rows = [_clean_candidate(row) for row in candidate_rows]
    rows.sort(key=lambda row: str(row.get("candidate_id", "")))
    return [user_candidate_view(row, profile) for row in rows]
