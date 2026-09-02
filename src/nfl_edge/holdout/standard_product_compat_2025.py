"""Standard-evaluation compatibility layer for the frozen 2025 product path.

This module changes no model, evaluator, confidence, selector, staking, Play
Through, or Task05E candidate-region methodology. It exists only because the
standard 2025 runtime persists the newer canonical Task05G row names while
several already-frozen downstream consumers still read their historical aliases.

All legacy aliases created here are temporary. Persisted 2025 product rows stay
canonical.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Iterable, Mapping

from nfl_edge.market_edge import candidates as task05e_candidates
from nfl_edge.recommendation.remediation_provenance_v1 import REGION_SPECS
from nfl_edge.value.contracts import NormalizedOffer


CURRENT_ALIASES: tuple[tuple[str, str], ...] = (
    ("selected_side", "selection"),
    ("line", "actionable_line"),
    ("american_odds", "actionable_price_american"),
    ("sportsbook", "actionable_book"),
    ("raw_model_output", "raw_football_output"),
)
TEMPORARY_LEGACY_KEYS = frozenset(legacy for legacy, _ in CURRENT_ALIASES)


class StandardProductCompatibilityError(RuntimeError):
    """Raised when the canonical/frozen product interface cannot be reconciled."""


def legacy_current_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return temporary legacy-key copies of canonical current/settled rows."""
    out: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        for legacy, canonical in CURRENT_ALIASES:
            has_legacy = legacy in row
            has_canonical = canonical in row
            legacy_value = row.get(legacy)
            canonical_value = row.get(canonical)
            if not has_legacy and has_canonical:
                row[legacy] = canonical_value
            elif has_legacy and has_canonical:
                if legacy_value is None and canonical_value is not None:
                    row[legacy] = canonical_value
                elif (
                    legacy_value is not None
                    and canonical_value is not None
                    and legacy_value != canonical_value
                ):
                    raise StandardProductCompatibilityError(
                        "current row alias conflict: "
                        f"game_id={row.get('game_id')} {legacy}={legacy_value!r} "
                        f"{canonical}={canonical_value!r}"
                    )
        if row.get("selected_side") is None:
            raise StandardProductCompatibilityError(
                f"current row lacks wager side: game_id={row.get('game_id')}"
            )
        if row.get("sportsbook") is None:
            raise StandardProductCompatibilityError(
                f"current row lacks actionable book: game_id={row.get('game_id')}"
            )
        if row.get("american_odds") is None:
            raise StandardProductCompatibilityError(
                f"current row lacks actionable price: game_id={row.get('game_id')}"
            )
        market = str(row.get("market_type") or "").lower()
        if market in {"moneyline", "spread"} and row.get("raw_model_output") is None:
            raise StandardProductCompatibilityError(
                f"current {market} row lacks frozen model output: game_id={row.get('game_id')}"
            )
        out.append(row)
    return out


def _region_name(family: str, model: str, bucket: str) -> str | None:
    for name, expected_family, expected_model, buckets in REGION_SPECS:
        if family == expected_family and model == expected_model and bucket in buckets:
            return name
    return None


def _positive_edge_side(model_home: float, benchmark_home: float) -> tuple[str, float, float] | None:
    delta = float(model_home) - float(benchmark_home)
    if abs(delta) <= 1e-12:
        return None
    if delta > 0.0:
        return "home", float(model_home), abs(delta) * 100.0
    return "away", 1.0 - float(model_home), abs(delta) * 100.0


def build_current_candidate_registry(
    *,
    task05f: Any,
    current_games: Mapping[str, Mapping[str, Any]],
    market_index: Mapping[Any, Any],
) -> dict[tuple[str, str, str], tuple[str, ...]]:
    """Recreate the frozen Task05E candidate identities outcome-blind for 2025.

    This is the direct 2025 continuation of the locked Task05E census/ledger
    predicates. It uses only current pre-result model outputs and the current
    frozen market snapshot. No score, settlement, profit, or realized edge is
    consulted.
    """
    tags: dict[tuple[str, str, str], set[str]] = defaultdict(set)

    for gid, source in sorted(current_games.items()):
        game = dict(source)
        if int(game.get("season", -1)) != 2025:
            raise StandardProductCompatibilityError(
                f"candidate-registry current game is not 2025: {gid}"
            )
        for outcome_key in (
            "home_score",
            "away_score",
            "target_margin",
            "target_home_win",
            "target_total_points",
        ):
            if game.get(outcome_key) is not None:
                raise StandardProductCompatibilityError(
                    f"candidate-registry outcome leakage: {gid}:{outcome_key}"
                )
        if bool(game.get("target_available", False)):
            raise StandardProductCompatibilityError(
                f"candidate-registry target available before freeze: {gid}"
            )

        # Moneyline candidate regions. Task05E AVG and corroborated definitions
        # require both frozen constituent probabilities.
        qh = game.get("qbelo_home")
        xh = game.get("xgb_home")
        ml_anchor = task05f._moneyline_anchor(market_index, str(gid))
        if qh is not None and xh is not None and ml_anchor is not None:
            qh = float(qh)
            xh = float(xh)
            ah = (qh + xh) / 2.0
            benchmark_home = float(ml_anchor.home_no_vig_probability)
            q_side = _positive_edge_side(qh, benchmark_home)
            x_side = _positive_edge_side(xh, benchmark_home)
            avg_side = _positive_edge_side(ah, benchmark_home)

            if avg_side is not None:
                side, p_selected, edge_pp = avg_side
                offer = task05f._best(market_index, str(gid), "moneyline", side)
                if offer is not None:
                    bucket = task05e_candidates._ml_bucket(float(edge_pp))
                    if bucket is not None:
                        name = _region_name("ML_AVG_DISAGREEMENT", "AVG", bucket)
                        if name is not None:
                            tags[(str(gid), "moneyline", side)].add(name)
                    if task05e_candidates._in_dog_zone(
                        float(p_selected), int(offer.price_american)
                    ):
                        name = _region_name("ML_DOG_VALUE_ZONE", "AVG", "ZONE")
                        if name is not None:
                            tags[(str(gid), "moneyline", side)].add(name)
                        if (
                            q_side is not None
                            and x_side is not None
                            and q_side[0] == x_side[0] == side
                        ):
                            name = _region_name("ML_DOG_VALUE_ZONE", "CORROB", "ZONE")
                            if name is not None:
                                tags[(str(gid), "moneyline", side)].add(name)

        # Spread candidate region. The frozen Task05E definition compares the
        # Expected Margin model to the Pinnacle threshold, then fails closed
        # unless both DK and FD selected-side offers are reconstructable.
        expected_margin = game.get("expected_home_margin")
        spread_anchor = task05f._spread_anchor(market_index, str(gid))
        if expected_margin is not None and spread_anchor is not None:
            signed = float(expected_margin) - float(spread_anchor.threshold)
            if abs(signed) > 1e-9:
                side = "home" if signed > 0.0 else "away"
                disagreement = abs(signed)
                dk = list(market_index.get((str(gid), "spread", side, "draftkings"), []))
                fd = list(market_index.get((str(gid), "spread", side, "fanduel"), []))
                if dk and fd:
                    bucket = task05e_candidates._st_bucket(float(disagreement))
                    if bucket is not None:
                        name = _region_name(
                            "SPREAD_DISAGREEMENT", "EXPECTED_MARGIN", bucket
                        )
                        if name is not None:
                            tags[(str(gid), "spread", side)].add(name)

    return {key: tuple(sorted(value)) for key, value in sorted(tags.items())}


def attach_current_candidate_regions(
    rows: Iterable[Mapping[str, Any]],
    registry: Mapping[tuple[str, str, str], tuple[str, ...]],
) -> list[dict[str, Any]]:
    """Attach frozen Task05E identity tags to current temporary board rows."""
    out: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        key = (
            str(row.get("game_id") or ""),
            str(row.get("market_type") or "").lower(),
            str(row.get("selected_side") or row.get("selection") or "").lower(),
        )
        regions = tuple(registry.get(key, ()))
        row["model_candidate"] = bool(regions)
        row["model_candidate_regions"] = ";".join(regions)
        out.append(row)
    return out


def _strip_row(row: Mapping[str, Any]) -> dict[str, Any]:
    clean = dict(row)
    for legacy in TEMPORARY_LEGACY_KEYS:
        clean.pop(legacy, None)
    return clean


def strip_product_aliases(product: Mapping[str, Any]) -> dict[str, Any]:
    """Remove temporary legacy aliases from every persisted current-row surface."""
    out = dict(product)
    for key in ("board_rows", "headlines", "unique_exposure"):
        if key in out:
            out[key] = [_strip_row(row) for row in out[key]]
    return out


def _assert_confidence_live(board_rows: Iterable[Mapping[str, Any]]) -> None:
    rows = list(board_rows)
    for market in ("moneyline", "spread"):
        material = [
            row
            for row in rows
            if str(row.get("market_type") or "").lower() == market
            and bool(row.get("supported"))
        ]
        if material and not any(bool(row.get("model_confidence_supported")) for row in material):
            raise StandardProductCompatibilityError(
                f"frozen {market} confidence produced zero supported current rows; "
                "canonical/frozen input contract is not live"
            )


def build_product_with_compat(
    frozen_builder: Callable[..., dict[str, Any]],
    *,
    prior_board_rows_adapter: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    **kwargs: Any,
) -> dict[str, Any]:
    """Call the frozen product builder through temporary standard-only views."""
    material = dict(kwargs)
    material["prior_board_rows"] = prior_board_rows_adapter(
        [dict(row) for row in material["prior_board_rows"]]
    )

    # Unit tests may supply a tiny stand-in builder. Production's frozen builder
    # has these internal globals; bypass current-row wrapping for simple stubs.
    namespace = getattr(frozen_builder, "__globals__", {})
    if "_apply_v2" not in namespace or "_apply_v3" not in namespace:
        return frozen_builder(**material)

    task05f = namespace["_load"](
        "standard_2025_candidate_regions_task05f",
        kwargs["root"] / "scripts/task05f_evaluator_final_runner.py",
    )
    registry = build_current_candidate_registry(
        task05f=task05f,
        current_games=kwargs["current_games"],
        market_index=kwargs["market_index"],
    )

    frozen_v2 = namespace["_apply_v2"]
    frozen_v3 = namespace["_apply_v3"]

    def adapted_v2(*, root, candidates, prior_games):
        return frozen_v2(
            root=root,
            candidates=legacy_current_rows(candidates),
            prior_games=prior_games,
        )

    def adapted_v3(*, root, rows, prior_board_rows, prior_games):
        board = frozen_v3(
            root=root,
            rows=legacy_current_rows(rows),
            prior_board_rows=prior_board_rows,
            prior_games=prior_games,
        )
        return attach_current_candidate_regions(board, registry)

    namespace["_apply_v2"] = adapted_v2
    namespace["_apply_v3"] = adapted_v3
    try:
        product = frozen_builder(**material)
    finally:
        namespace["_apply_v2"] = frozen_v2
        namespace["_apply_v3"] = frozen_v3

    clean = strip_product_aliases(product)
    board = list(clean.get("board_rows") or [])
    _assert_confidence_live(board)
    for key in ("board_rows", "headlines", "unique_exposure"):
        for row in clean.get(key, []):
            leaked = TEMPORARY_LEGACY_KEYS.intersection(row)
            if leaked:
                raise StandardProductCompatibilityError(
                    f"temporary legacy aliases leaked to persisted {key}: {sorted(leaked)}"
                )
    return clean


def advance_value_state_with_compat(
    frozen_advance: Callable[..., Any], state: Any, settled_block_rows: Iterable[Mapping[str, Any]]
) -> Any:
    """Advance frozen causal Value trust through a temporary legacy settled view."""
    return frozen_advance(state, legacy_current_rows(settled_block_rows))


def synthetic_current_contract_smoke(task05f: Any) -> None:
    """Prove aliases and frozen Task05E region predicates without 2025 results."""
    gid = "SYNTHETIC_CURRENT"
    idx: dict[tuple[str, str, str, str], list[NormalizedOffer]] = {}

    def add(market: str, side: str, book: str, price: int, line: float | None = None):
        idx.setdefault((gid, market, side, book), []).append(
            NormalizedOffer(
                market_type=market,
                side=side,
                book=book,
                price_american=price,
                line=line,
                snapshot_utc="2025-09-01T00:00:00Z",
            )
        )

    # Symmetric Pinnacle ML around ~55.95/44.05; AVG=.55 selects away with
    # <2pp positive edge. +150 actionable away is inside the frozen dog zone.
    add("moneyline", "home", "pinnacle", -127)
    add("moneyline", "away", "pinnacle", 127)
    add("moneyline", "home", "draftkings", -145)
    add("moneyline", "home", "fanduel", -140)
    add("moneyline", "away", "draftkings", 150)
    add("moneyline", "away", "fanduel", 145)

    # Mirrored Pinnacle spread; Expected Margin 2.5 vs threshold 1.0 gives a
    # 1.5-point home disagreement. Both frozen actionable books are present.
    add("spread", "home", "pinnacle", -110, -1.0)
    add("spread", "away", "pinnacle", -110, 1.0)
    add("spread", "home", "draftkings", -110, -1.0)
    add("spread", "home", "fanduel", -108, -0.5)
    add("spread", "away", "draftkings", -110, 1.0)
    add("spread", "away", "fanduel", -112, 0.5)

    current = {
        gid: {
            "game_id": gid,
            "season": 2025,
            "week": 1,
            "qbelo_home": 0.55,
            "xgb_home": 0.55,
            "expected_home_margin": 2.5,
            "predicted_total": 44.0,
            "home_score": None,
            "away_score": None,
            "target_margin": None,
            "target_home_win": None,
            "target_total_points": None,
            "target_available": False,
        }
    }
    registry = build_current_candidate_registry(
        task05f=task05f, current_games=current, market_index=idx
    )
    ml_tags = set(registry.get((gid, "moneyline", "away"), ()))
    expected_ml = {
        "ML_DOG_VALUE_ZONE_AVG",
        "ML_DOG_VALUE_ZONE_CORROB",
        "ML_AVG_DISAGREEMENT_AVG_0_2",
    }
    if ml_tags != expected_ml:
        raise StandardProductCompatibilityError(
            f"synthetic Task05E ML provenance mismatch: {sorted(ml_tags)}"
        )
    spread_tags = set(registry.get((gid, "spread", "home"), ()))
    if spread_tags != {"SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4"}:
        raise StandardProductCompatibilityError(
            f"synthetic Task05E spread provenance mismatch: {sorted(spread_tags)}"
        )

    canonical = {
        "game_id": gid,
        "market_type": "moneyline",
        "selection": "away",
        "actionable_book": "draftkings",
        "actionable_line": None,
        "actionable_price_american": 150,
        "raw_football_output": 0.45,
    }
    adapted = legacy_current_rows([canonical])[0]
    expected_aliases = {
        "selected_side": "away",
        "sportsbook": "draftkings",
        "line": None,
        "american_odds": 150,
        "raw_model_output": 0.45,
    }
    for key, value in expected_aliases.items():
        if adapted.get(key) != value:
            raise StandardProductCompatibilityError(
                f"synthetic current alias mismatch: {key}={adapted.get(key)!r} expected={value!r}"
            )
    if TEMPORARY_LEGACY_KEYS.intersection(canonical):
        raise StandardProductCompatibilityError("synthetic current adapter mutated canonical source")
