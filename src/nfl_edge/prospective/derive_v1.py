"""Derived episodes and per-game official pre-kick records from immutable publications."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from nfl_edge.prospective.common_v1 import (
    BUILDER_VERSION,
    EPISODES_SCHEMA_VERSION,
    LANE_ORDER,
    LANE_RANK,
    OFFICIAL_SCHEMA_VERSION,
    ProspectiveCardError,
    assert_same_week,
    exact_offer_tuple,
    parse_utc,
    stable_id,
)


def _ordered(publications: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    rows = list(publications)
    assert_same_week(rows)
    for row in rows:
        parse_utc(str(row["published_at_utc"]))
    return sorted(rows, key=lambda row: (str(row["published_at_utc"]), str(row["publication_id"])))


def _best_worst_line(
    market: str | None,
    side: str | None,
    values: list[float],
) -> tuple[float | None, float | None]:
    if not values or market is None:
        return None, None
    market_key = str(market).upper()
    if market_key == "SPREAD":
        # Production shop_spread semantics: larger selected-side line is better.
        return max(values), min(values)
    if market_key == "TOTAL":
        # Production shop_total semantics: Over wants lower; Under wants higher.
        if str(side).lower() == "over":
            return min(values), max(values)
        if str(side).lower() == "under":
            return max(values), min(values)
    return None, None


def derive_episodes(publications: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Group consecutive appearances of one logical lane recommendation."""
    ordered = _ordered(publications)
    season, week = assert_same_week(list(ordered))
    episodes: list[dict[str, Any]] = []
    active: dict[str, dict[str, Any] | None] = {lane: None for lane in LANE_ORDER}
    previously_seen: dict[str, set[str]] = {lane: set() for lane in LANE_ORDER}

    def close(lane_key: str, reason: str) -> None:
        episode = active[lane_key]
        if episode is None:
            return
        observations = episode.pop("_observations")
        prices = [int(item["american_odds"]) for item in observations if item.get("american_odds") is not None]
        lines = [float(item["line"]) for item in observations if item.get("line") is not None]
        best_line, worst_line = _best_worst_line(
            episode.get("market"),
            episode.get("normalized_side"),
            lines,
        )
        episode.update(
            first_seen_at_utc=observations[0]["published_at_utc"],
            last_seen_at_utc=observations[-1]["published_at_utc"],
            first_publication_id=observations[0]["publication_id"],
            last_publication_id=observations[-1]["publication_id"],
            publication_count=len(observations),
            first_price=prices[0] if prices else None,
            last_price=prices[-1] if prices else None,
            best_price=max(prices) if prices else None,
            worst_price=min(prices) if prices else None,
            first_line=lines[0] if lines else None,
            last_line=lines[-1] if lines else None,
            best_line=best_line,
            worst_line=worst_line,
            terminal_reason=reason,
            observations=observations,
        )
        episodes.append(episode)
        active[lane_key] = None

    for publication in ordered:
        for lane_key in LANE_ORDER:
            row = dict(publication["lanes"][lane_key])
            logical_id = row.get("logical_recommendation_id")
            if logical_id is None:
                close(lane_key, "DISAPPEARED")
                continue

            current = active[lane_key]
            if current is not None and current["logical_recommendation_id"] != logical_id:
                close(lane_key, "REPLACED")
                current = None

            if current is None:
                returned = str(logical_id) in previously_seen[lane_key]
                previously_seen[lane_key].add(str(logical_id))
                current = {
                    "episode_id": stable_id(
                        "episode",
                        lane_key,
                        logical_id,
                        publication["publication_id"],
                    ),
                    "lane_key": lane_key,
                    "lane": row["lane"],
                    "logical_recommendation_id": logical_id,
                    "game_id": row["game_id"],
                    "market": row["market"],
                    "selection": row["selection"],
                    "normalized_selection": row["normalized_selection"],
                    "normalized_side": row["normalized_side"],
                    "returned_after_gap": returned,
                    "_observations": [],
                }
                active[lane_key] = current

            current["_observations"].append(
                {
                    "publication_id": publication["publication_id"],
                    "source_product_sha256": publication["source_product_sha256"],
                    "published_at_utc": publication["published_at_utc"],
                    "state": row["state"],
                    "book": row["book"],
                    "line": row["line"],
                    "american_odds": row["american_odds"],
                    "recommended_units": row["recommended_units"],
                    "play_through": deepcopy(row["play_through"]),
                    "value_at": deepcopy(row["value_at"]),
                    "wager_identity_id": row["wager_identity_id"],
                    "exact_offer_identity_id": row["exact_offer_identity_id"],
                }
            )

    for lane_key in LANE_ORDER:
        close(lane_key, "WEEK_HISTORY_END")

    episodes.sort(
        key=lambda row: (
            row["first_seen_at_utc"],
            LANE_RANK[row["lane_key"]],
            row["episode_id"],
        )
    )
    return {
        "schema_version": EPISODES_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "season": season,
        "week": week,
        "source_publication_ids": [row["publication_id"] for row in ordered],
        "episodes": episodes,
    }


def resolve_official(publications: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Resolve the final eligible lane state strictly before each referenced game kickoff."""
    ordered = _ordered(publications)
    season, week = assert_same_week(list(ordered))

    candidate_games: dict[tuple[str, str], str] = {}
    for publication in ordered:
        for lane_key in LANE_ORDER:
            lane = publication["lanes"][lane_key]
            game_id = lane.get("game_id")
            if game_id is None:
                continue
            key = (lane_key, str(game_id))
            kickoff = str(lane["kickoff_at_utc"])
            existing = candidate_games.setdefault(key, kickoff)
            if existing != kickoff:
                raise ProspectiveCardError(f"kickoff drift for {key}: {existing} != {kickoff}")

    resolutions: list[dict[str, Any]] = []
    candidates = sorted(
        candidate_games.items(),
        key=lambda item: (
            parse_utc(item[1]),
            LANE_RANK[item[0][0]],
            item[0][1],
        ),
    )
    for (lane_key, game_id), kickoff in candidates:
        kickoff_dt = parse_utc(kickoff)
        eligible = [
            publication
            for publication in ordered
            if parse_utc(str(publication["published_at_utc"])) < kickoff_dt
        ]
        if not eligible:
            resolutions.append(
                {
                    "lane_key": lane_key,
                    "lane": lane_key.upper(),
                    "game_id": game_id,
                    "kickoff_at_utc": kickoff,
                    "resolution_state": "NO_ELIGIBLE_PREKICK_PUBLICATION",
                    "source_publication_id": None,
                    "source_product_sha256": None,
                    "final_lane_state": None,
                    "official_wager": None,
                    "first_appearance": None,
                }
            )
            continue

        final_publication = eligible[-1]
        final_lane = dict(final_publication["lanes"][lane_key])
        same_game = final_lane.get("game_id") == game_id
        official_wager = (
            deepcopy(final_lane)
            if same_game and final_lane.get("state") == "BET"
            else None
        )

        first_appearance = None
        if official_wager is not None:
            logical_id = official_wager.get("logical_recommendation_id")
            first = next(
                (
                    publication
                    for publication in ordered
                    if publication["lanes"][lane_key].get("logical_recommendation_id") == logical_id
                    and parse_utc(str(publication["published_at_utc"])) < kickoff_dt
                ),
                None,
            )
            if first is not None:
                first_lane = first["lanes"][lane_key]
                first_appearance = {
                    "publication_id": first["publication_id"],
                    "source_product_sha256": first["source_product_sha256"],
                    "published_at_utc": first["published_at_utc"],
                    "line": first_lane.get("line"),
                    "american_odds": first_lane.get("american_odds"),
                }
            resolution_state = "OFFICIAL_BET"
        elif same_game:
            resolution_state = f"OFFICIAL_{str(final_lane.get('state') or 'NO_PLAY')}"
        else:
            resolution_state = "OFFICIAL_NO_PLAY_OR_REPLACED"

        resolutions.append(
            {
                "lane_key": lane_key,
                "lane": str(final_lane["lane"]),
                "game_id": game_id,
                "kickoff_at_utc": kickoff,
                "resolution_state": resolution_state,
                "source_publication_id": final_publication["publication_id"],
                "source_product_sha256": final_publication["source_product_sha256"],
                "final_lane_state": deepcopy(final_lane),
                "official_wager": official_wager,
                "first_appearance": first_appearance,
            }
        )

    official_wagers = [row for row in resolutions if row["official_wager"] is not None]

    # Mirror current backend exact-offer duplicate identity:
    # game_id, market, selection, book, line, american_odds.
    portfolio_by_offer: dict[tuple[Any, ...], dict[str, Any]] = {}
    ordered_wagers = sorted(
        official_wagers,
        key=lambda row: (
            parse_utc(row["kickoff_at_utc"]),
            LANE_RANK[row["lane_key"]],
            row["game_id"],
        ),
    )
    for resolution in ordered_wagers:
        wager = resolution["official_wager"]
        exact = exact_offer_tuple(wager)
        if exact is None:
            raise ProspectiveCardError("official BET lacks exact offer identity")
        entry = portfolio_by_offer.get(exact)
        if entry is None:
            entry = {
                "portfolio_entry_id": stable_id("portfolio", *exact),
                "primary_lane_key": resolution["lane_key"],
                "lane_keys": [resolution["lane_key"]],
                "game_id": wager["game_id"],
                "market": wager["market"],
                "selection": wager["selection"],
                "book": wager["book"],
                "line": wager["line"],
                "american_odds": wager["american_odds"],
                "recommended_units": wager["recommended_units"],
                "kickoff_at_utc": resolution["kickoff_at_utc"],
                "source_publication_id": resolution["source_publication_id"],
                "source_product_sha256": resolution["source_product_sha256"],
            }
            portfolio_by_offer[exact] = entry
        elif resolution["lane_key"] not in entry["lane_keys"]:
            entry["lane_keys"].append(resolution["lane_key"])

    portfolio_entries = list(portfolio_by_offer.values())
    portfolio_entries.sort(
        key=lambda row: (
            parse_utc(row["kickoff_at_utc"]),
            LANE_RANK[row["primary_lane_key"]],
            row["portfolio_entry_id"],
        )
    )
    return {
        "schema_version": OFFICIAL_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "season": season,
        "week": week,
        "official_definition": "FINAL_VALID_PUBLISHED_LANE_STATE_STRICTLY_BEFORE_GAME_KICKOFF",
        "source_publication_ids": [row["publication_id"] for row in ordered],
        "resolutions": resolutions,
        "official_wagers": official_wagers,
        "portfolio_entries": portfolio_entries,
        "overlap_count": len(official_wagers) - len(portfolio_entries),
    }
