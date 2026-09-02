"""Standard-only 2025 compatibility wrapper around the merged PR #87 base.

The merged compatibility implementation is preserved byte-for-byte in
``standard_product_compat_2025_base``. This wrapper changes only how the frozen
Model Confidence V2 / Spread Confidence V3 current inputs are materialized:
those historical runners sourced game-level model predictions, not Task05F's
candidate ``raw_model_output`` field.

The standard-only contract check validates that those inputs reached the frozen
confidence code. It must not promote a legitimate frozen ``supported=False``
state into a fatal error: Spread Confidence V3 intentionally fails closed when
its causal logistic state is unsupported (including a non-positive slope).
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

from . import standard_product_compat_2025_base as _base

CURRENT_ALIASES = _base.CURRENT_ALIASES
TEMPORARY_LEGACY_KEYS = _base.TEMPORARY_LEGACY_KEYS
StandardProductCompatibilityError = _base.StandardProductCompatibilityError
build_current_candidate_registry = _base.build_current_candidate_registry
attach_current_candidate_regions = _base.attach_current_candidate_regions
strip_product_aliases = _base.strip_product_aliases
# Retained as the old PR #87 diagnostic helper for historical tests only.  The
# standard execution path no longer treats zero support as proof of bad wiring.
_assert_confidence_live = _base._assert_confidence_live


def legacy_current_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return temporary legacy-key copies without requiring candidate raw output.

    ``raw_model_output`` is still copied from canonical ``raw_football_output``
    when present, preserving the PR #87 behavior. Unlike the PR #87 base, a null
    candidate-level raw output is not treated as a contract failure because the
    finalized V2/V3 confidence runners did not source their current inputs there.
    """
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
        out.append(row)
    return out


def confidence_current_rows(
    rows: Iterable[Mapping[str, Any]],
    current_games: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Restore the exact frozen game-level current-input contract for V2/V3.

    Moneyline V2 used the 50/50 QB-Elo/XGBoost home probability average and
    flipped it to the selected side. Spread V2/V3 used stable Expected Margin's
    home prediction. The values below come only from already-frozen current-game
    predictions; no 2025 result fields are consulted.
    """
    out = legacy_current_rows(rows)
    for row in out:
        gid = str(row.get("game_id") or "")
        game = current_games.get(gid)
        if game is None:
            raise StandardProductCompatibilityError(
                f"current confidence row has no game-level model inputs: {gid}"
            )
        market = str(row.get("market_type") or "").lower()
        side = str(row.get("selected_side") or "").lower()

        expected: float | None = None
        if market == "moneyline":
            qbelo_home = game.get("qbelo_home")
            xgb_home = game.get("xgb_home")
            if qbelo_home is not None and xgb_home is not None:
                avg_home = (float(qbelo_home) + float(xgb_home)) / 2.0
                if side == "home":
                    expected = avg_home
                elif side == "away":
                    expected = 1.0 - avg_home
                else:
                    raise StandardProductCompatibilityError(
                        f"unexpected moneyline side for confidence input: {gid}:{side}"
                    )
        elif market == "spread":
            margin = game.get("expected_home_margin")
            if margin is not None:
                expected = float(margin)

        if market in {"moneyline", "spread"}:
            row["raw_model_output"] = expected
    return out


def _assert_confidence_contract(
    board_rows: Iterable[Mapping[str, Any]],
    current_games: Mapping[str, Mapping[str, Any]],
) -> None:
    """Validate confidence wiring without overriding frozen support semantics.

    The former standard-only liveness check required every material market to
    produce at least one supported confidence row. That was too strong: frozen
    Spread Confidence V3 deliberately returns ``supported=False`` when its
    causal logistic calibration is not usable (for example, non-positive
    slope). Such a state is a valid model decision and must flow to selectors as
    no confidence, not abort the season.

    Structural checks remain fail-closed:
    * when both frozen ML constituents are live, at least one supported Task05F
      moneyline row must receive supported ML confidence;
    * every supported spread row with an Expected Margin input and actionable
      line must show that it actually traversed the frozen V3 conversion, even
      when V3 itself returns unsupported.
    """
    rows = [dict(row) for row in board_rows]

    live_ml_rows: list[dict[str, Any]] = []
    spread_wiring_failures: list[str] = []
    for row in rows:
        gid = str(row.get("game_id") or "")
        game = current_games.get(gid)
        if game is None:
            raise StandardProductCompatibilityError(
                f"persisted confidence row has no current game: {gid}"
            )
        market = str(row.get("market_type") or "").lower()
        if not bool(row.get("supported")):
            continue

        if market == "moneyline":
            if game.get("qbelo_home") is not None and game.get("xgb_home") is not None:
                live_ml_rows.append(row)
            continue

        if market != "spread":
            continue
        line = row.get("actionable_line")
        if line is None:
            line = row.get("line")
        if game.get("expected_home_margin") is None or line is None:
            continue
        if str(row.get("model_confidence_source") or "") != "EXPECTED_MARGIN_DIRECT_LOGISTIC_V3":
            spread_wiring_failures.append(f"{gid}:source")
            continue
        if row.get("model_cover_margin_v3") is None:
            spread_wiring_failures.append(f"{gid}:cover_margin")

    if live_ml_rows and not any(bool(row.get("model_confidence_supported")) for row in live_ml_rows):
        raise StandardProductCompatibilityError(
            "frozen moneyline confidence inputs are live but produced zero supported current rows"
        )
    if spread_wiring_failures:
        raise StandardProductCompatibilityError(
            "frozen spread confidence wiring incomplete: "
            + ", ".join(spread_wiring_failures[:8])
        )


def build_product_with_compat(
    frozen_builder: Callable[..., dict[str, Any]],
    *,
    prior_board_rows_adapter: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    **kwargs: Any,
) -> dict[str, Any]:
    """Call the frozen product through PR #87 compatibility + exact V2/V3 inputs."""
    material = dict(kwargs)
    material["prior_board_rows"] = prior_board_rows_adapter(
        [dict(row) for row in material["prior_board_rows"]]
    )

    namespace = getattr(frozen_builder, "__globals__", {})
    if "_apply_v2" not in namespace or "_apply_v3" not in namespace:
        return frozen_builder(**material)

    current_games = kwargs["current_games"]
    task05f = namespace["_load"](
        "standard_2025_candidate_regions_task05f",
        kwargs["root"] / "scripts/task05f_evaluator_final_runner.py",
    )
    registry = build_current_candidate_registry(
        task05f=task05f,
        current_games=current_games,
        market_index=kwargs["market_index"],
    )

    frozen_v2 = namespace["_apply_v2"]
    frozen_v3 = namespace["_apply_v3"]

    def adapted_v2(*, root, candidates, prior_games):
        return frozen_v2(
            root=root,
            candidates=confidence_current_rows(candidates, current_games),
            prior_games=prior_games,
        )

    def adapted_v3(*, root, rows, prior_board_rows, prior_games):
        board = frozen_v3(
            root=root,
            rows=confidence_current_rows(rows, current_games),
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
    _assert_confidence_contract(board, current_games)
    for key in ("board_rows", "headlines", "unique_exposure"):
        for row in clean.get(key, []):
            leaked = TEMPORARY_LEGACY_KEYS.intersection(row)
            if leaked:
                raise StandardProductCompatibilityError(
                    f"temporary legacy aliases leaked to persisted {key}: {sorted(leaked)}"
                )
    return clean


def advance_value_state_with_compat(
    frozen_advance: Callable[..., Any],
    state: Any,
    settled_block_rows: Iterable[Mapping[str, Any]],
) -> Any:
    """Advance frozen Value trust through the same temporary legacy settled view."""
    return frozen_advance(state, legacy_current_rows(settled_block_rows))


def synthetic_current_contract_smoke(task05f: Any) -> None:
    """Retain prior smokes and cover legitimate frozen unsupported confidence."""
    _base.synthetic_current_contract_smoke(task05f)

    gid = "SYNTHETIC_CONFIDENCE_SOURCE"
    current = {
        gid: {
            "game_id": gid,
            "season": 2025,
            "week": 1,
            "qbelo_home": 0.55,
            "xgb_home": 0.55,
            "expected_home_margin": 2.5,
            "home_score": None,
            "away_score": None,
            "target_margin": None,
            "target_home_win": None,
            "target_total_points": None,
            "target_available": False,
        }
    }
    canonical_ml = {
        "game_id": gid,
        "market_type": "moneyline",
        "selection": "away",
        "actionable_book": "draftkings",
        "actionable_line": None,
        "actionable_price_american": 150,
        "raw_football_output": None,
    }
    legacy_ml = legacy_current_rows([canonical_ml])[0]
    if legacy_ml.get("raw_model_output") is not None:
        raise StandardProductCompatibilityError(
            "legacy alias invented a model-confidence input"
        )
    confidence_ml = confidence_current_rows([canonical_ml], current)[0]
    if abs(float(confidence_ml["raw_model_output"]) - 0.45) > 1e-12:
        raise StandardProductCompatibilityError(
            "ML confidence source did not reproduce selected-side QB-Elo/XGB AVG"
        )

    canonical_spread = {
        "game_id": gid,
        "market_type": "spread",
        "selection": "home",
        "actionable_book": "draftkings",
        "actionable_line": -1.0,
        "actionable_price_american": -110,
        "raw_football_output": None,
    }
    confidence_spread = confidence_current_rows([canonical_spread], current)[0]
    if abs(float(confidence_spread["raw_model_output"]) - 2.5) > 1e-12:
        raise StandardProductCompatibilityError(
            "spread confidence source did not reproduce Expected Margin"
        )

    # Frozen Spread V3 may intentionally be unsupported.  The compatibility
    # layer must accept that model decision as long as the V3 path was actually
    # traversed and the current model-cover margin was materialized.
    unsupported_spread = {
        **canonical_spread,
        "supported": True,
        "model_confidence_supported": False,
        "model_confidence_source": "EXPECTED_MARGIN_DIRECT_LOGISTIC_V3",
        "model_cover_margin_v3": 1.5,
    }
    _assert_confidence_contract([unsupported_spread], current)

    # XGBoost warmup likewise makes ML confidence legitimately unavailable.
    cold_current = {gid: {**current[gid], "xgb_home": None}}
    cold_ml = {
        **canonical_ml,
        "supported": True,
        "model_confidence_supported": False,
        "model_confidence_source": None,
    }
    _assert_confidence_contract([cold_ml], cold_current)

    # Once both ML constituents are live, silent all-unsupported confidence is
    # still a real integration failure and remains fail-closed.
    try:
        _assert_confidence_contract([cold_ml], current)
    except StandardProductCompatibilityError:
        pass
    else:
        raise StandardProductCompatibilityError(
            "live ML confidence wiring smoke did not fail closed"
        )

    # A spread row with a current Expected Margin input must show evidence that
    # it traversed V3 even if V3 itself declines support.
    broken_spread = {
        **unsupported_spread,
        "model_confidence_source": None,
        "model_cover_margin_v3": None,
    }
    try:
        _assert_confidence_contract([broken_spread], current)
    except StandardProductCompatibilityError:
        pass
    else:
        raise StandardProductCompatibilityError(
            "spread confidence wiring smoke did not fail closed"
        )

    for source in (canonical_ml, canonical_spread):
        if TEMPORARY_LEGACY_KEYS.intersection(source):
            raise StandardProductCompatibilityError(
                "confidence adapter mutated canonical source"
            )
