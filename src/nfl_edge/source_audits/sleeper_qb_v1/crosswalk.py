"""Sleeper-to-nflverse identity crosswalk for active QBs.

The crosswalk prefers stable IDs and **never** treats a name-plus-team
match as authoritative. The match priority is:

1. exact GSIS id;
2. exact ESPN id;
3. another exact stable provider id (sportradar / yahoo /
   fantasy_data / rotowire);
4. normalized name plus team as a flagged fallback only.

The 2025 sealed holdout is never consulted. The crosswalk is intended
to run against the project's frozen nflverse reference table, which
covers 2018-2024 plus the in-season 2025 free-agent edge cases. The
audit's "is_matched" flag is the only output; any "review_required"
case must be inspected by a human before the row is used downstream.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping

import polars as pl

CROSSWALK_SCHEMA_VERSION = "qb-identity-crosswalk-v1"

CROSSWALK_FIELDS: tuple[str, ...] = (
    "snapshot_id",
    "sleeper_player_id",
    "sleeper_name",
    "sleeper_team",
    "gsis_id",
    "espn_id",
    "nflverse_player_id",
    "match_method",
    "match_confidence",
    "conflict_reason",
    "is_matched",
    "review_required",
)

CROSSWALK_DTYPES: dict[str, pl.DataType] = {
    "snapshot_id": pl.Utf8,
    "sleeper_player_id": pl.Utf8,
    "sleeper_name": pl.Utf8,
    "sleeper_team": pl.Utf8,
    "gsis_id": pl.Utf8,
    "espn_id": pl.Utf8,
    "nflverse_player_id": pl.Utf8,
    "match_method": pl.Utf8,
    "match_confidence": pl.Float64,
    "conflict_reason": pl.Utf8,
    "is_matched": pl.Boolean,
    "review_required": pl.Boolean,
}

# Sleeper's own player id is the most authoritative crosswalk key: when
# the nflverse reference table contains a row whose ``sleeper_id`` (or
# legacy ``sleeper_player_id``) matches the Sleeper-side id exactly,
# the audit can match with the highest confidence. GSIS, ESPN, and
# the other provider ids are fallbacks when the Sleeper id is not
# present in the reference.
MATCH_METHOD_SLEEPER = "exact_sleeper_id"
MATCH_METHOD_GSIS = "exact_gsis"
MATCH_METHOD_ESPN = "exact_espn"
MATCH_METHOD_OTHER_STABLE = "exact_other_stable"
MATCH_METHOD_NAME_TEAM_FALLBACK = "name_team_fallback"
MATCH_METHOD_NONE = "none"

NAME_STRIP_RE = re.compile(r"[^a-z0-9]+")


def _normalize_name(value: str | None) -> str:
    if not value:
        return ""
    nfkd = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return NAME_STRIP_RE.sub("", ascii_only.lower())


def _normalize_team(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().upper()


def _row_for_sleeper(
    *,
    snapshot_id: str,
    sleeper_record: Mapping[str, Any],
    gsis_to_nflverse: dict[str, set[str]],
    espn_to_nflverse: dict[str, set[str]],
    other_stable_to_nflverse: dict[str, set[str]],
    name_team_to_nflverse: dict[tuple[str, str], set[str]],
    sleeper_to_nflverse: dict[str, set[str]],
) -> dict[str, Any]:
    sleeper_player_id = str(sleeper_record.get("sleeper_player_id", ""))
    sleeper_name = (
        sleeper_record.get("full_name")
        or f"{sleeper_record.get('first_name', '')} {sleeper_record.get('last_name', '')}".strip()
    )
    sleeper_team = sleeper_record.get("team") or ""
    gsis_id = sleeper_record.get("gsis_id")
    espn_id = sleeper_record.get("espn_id")
    sportradar_id = sleeper_record.get("sportradar_id")
    yahoo_id = sleeper_record.get("yahoo_id")
    fantasy_data_id = sleeper_record.get("fantasy_data_id")
    rotowire_id = sleeper_record.get("rotowire_id")

    conflict_reasons: list[str] = []
    review_required = False
    is_matched = False
    nflverse_id: str | None = None
    match_method = MATCH_METHOD_NONE
    match_confidence = 0.0
    # Rereview contract (Rereview 4851615980): once a
    # higher-priority exact identifier produces a multi-match
    # conflict, the row is TERMINAL. The crosswalk must NOT fall
    # through to lower-priority identifiers or to name+team
    # fallback. The conflict token is preserved exactly as the
    # spec requires, ``is_matched`` stays False,
    # ``nflverse_player_id`` stays None, and ``review_required``
    # stays True.
    conflict_terminal = False

    def _pick_unique(
        candidates: set[str] | None,
        *,
        method_label: str,
        confidence: float,
    ) -> tuple[str | None, str | None, bool]:
        """Return ``(nflverse_id, conflict_reason, terminal)``.

        Empty set -> ``(None, None, False)``.
        Singleton -> ``(the_id, None, False)``.
        Multi-element -> ``(None, "multiple_nflverse_for_<method_label>", True)``.

        The terminal flag short-circuits all lower-priority
        identifiers; the crosswalk never silently selects the first
        element of a multi-match.
        """
        if not candidates:
            return None, None, False
        if len(candidates) == 1:
            return next(iter(candidates)), None, False
        return None, f"multiple_nflverse_for_{method_label}", True

    # Priority 0: exact Sleeper id.
    if not conflict_terminal:
        picked, conflict, terminal = _pick_unique(
            sleeper_to_nflverse.get(sleeper_player_id) if sleeper_player_id else None,
            method_label=MATCH_METHOD_SLEEPER,
            confidence=1.0,
        )
        if conflict:
            conflict_reasons.append(conflict)
            review_required = True
            conflict_terminal = True
        if picked is not None:
            nflverse_id = picked
            match_method = MATCH_METHOD_SLEEPER
            match_confidence = 1.0
            is_matched = True
    # Priority 1: exact GSIS id.
    if not conflict_terminal and not is_matched and gsis_id:
        picked, conflict, terminal = _pick_unique(
            gsis_to_nflverse.get(str(gsis_id)),
            method_label=MATCH_METHOD_GSIS,
            confidence=0.98,
        )
        if conflict:
            conflict_reasons.append(conflict)
            review_required = True
            conflict_terminal = True
        if picked is not None:
            nflverse_id = picked
            match_method = MATCH_METHOD_GSIS
            match_confidence = 0.98
            is_matched = True
    # Priority 2: exact ESPN id.
    if not conflict_terminal and not is_matched and espn_id:
        picked, conflict, terminal = _pick_unique(
            espn_to_nflverse.get(str(espn_id)),
            method_label=MATCH_METHOD_ESPN,
            confidence=0.95,
        )
        if conflict:
            conflict_reasons.append(conflict)
            review_required = True
            conflict_terminal = True
        if picked is not None:
            nflverse_id = picked
            match_method = MATCH_METHOD_ESPN
            match_confidence = 0.95
            is_matched = True
    # Priority 3: another exact stable provider id.
    if not conflict_terminal and not is_matched:
        for stable_id, label in (
            (sportradar_id, "sportradar"),
            (yahoo_id, "yahoo"),
            (fantasy_data_id, "fantasy_data"),
            (rotowire_id, "rotowire"),
        ):
            if not stable_id:
                continue
            picked, conflict, terminal = _pick_unique(
                other_stable_to_nflverse.get(str(stable_id)),
                method_label=f"{MATCH_METHOD_OTHER_STABLE}_{label}",
                confidence=0.9,
            )
            if conflict:
                conflict_reasons.append(conflict)
                review_required = True
                conflict_terminal = True
                break
            if picked is not None:
                nflverse_id = picked
                match_method = MATCH_METHOD_OTHER_STABLE
                match_confidence = 0.9
                is_matched = True
                break
    # Priority 4: name+team fallback. Flagged as review_required.
    # The rereview contract also forbids evaluating this fallback
    # when a higher-priority exact ID produced a conflict.
    if not conflict_terminal and not is_matched:
        team_norm = _normalize_team(sleeper_team)
        first = sleeper_record.get("first_name")
        last = sleeper_record.get("last_name")
        first_norm = _normalize_name(first) if isinstance(first, str) else ""
        last_norm = _normalize_name(last) if isinstance(last, str) else ""
        composite_norm = (first_norm + last_norm) if first_norm and last_norm else ""
        name_candidates: list[str] = []
        if isinstance(sleeper_name, str) and sleeper_name.strip():
            name_candidates.append(_normalize_name(sleeper_name))
        if composite_norm:
            name_candidates.append(composite_norm)
        for norm_name in name_candidates:
            if not norm_name or not team_norm:
                continue
            candidates = name_team_to_nflverse.get((norm_name, team_norm), set())
            if len(candidates) == 1:
                nflverse_id = next(iter(candidates))
                match_method = MATCH_METHOD_NAME_TEAM_FALLBACK
                match_confidence = 0.6
                is_matched = True
                review_required = True
                break
            if len(candidates) > 1:
                conflict_reasons.append("multiple_nflverse_for_name_team")
                review_required = True
                conflict_terminal = True
                break
    # Rereview contract: when a higher-priority exact ID produced a
    # conflict, the row is terminal. ``is_matched`` stays False,
    # ``nflverse_player_id`` is explicitly null (overriding any
    # value picked before the conflict), ``match_method`` stays at
    # the conflict label (not whatever lower-priority method would
    # have evaluated), and ``match_confidence`` stays at 0.0.
    if conflict_terminal:
        is_matched = False
        nflverse_id = None
        if match_method == MATCH_METHOD_NONE:
            match_confidence = 0.0
        # The fallback name+team case would have set
        # ``review_required = True`` even on a singleton; this
        # branch never executes for that case because the conflict
        # would have happened in priority 0..3.
    if not gsis_id and not espn_id and not sleeper_team:
        conflict_reasons.append("missing_all_stable_ids_and_team")
        review_required = True

    return {
        "snapshot_id": snapshot_id,
        "sleeper_player_id": sleeper_player_id,
        "sleeper_name": sleeper_name,
        "sleeper_team": sleeper_team,
        "gsis_id": gsis_id,
        "espn_id": espn_id,
        "nflverse_player_id": nflverse_id,
        "match_method": match_method,
        "match_confidence": match_confidence,
        "conflict_reason": ";".join(conflict_reasons) if conflict_reasons else None,
        "is_matched": is_matched,
        "review_required": review_required,
    }


def build_nflverse_indexes(
    nflverse_qbs: pl.DataFrame,
) -> tuple[
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
    dict[tuple[str, str], set[str]],
    dict[str, set[str]],
]:
    """Build the four (now five) lookup tables used by the crosswalk.

    Every exact-ID index is a ``dict[token, set[nflverse_id]]``. When
    two nflverse rows share the same Sleeper / GSIS / ESPN /
    sportradar / yahoo / fantasy_data / rotowire id, both rows
    appear in the set; the crosswalk treats that as a conflict and
    refuses to pick the first row silently.

    The expected nflverse input has columns:
    ``player_id, gsis_id, espn_id, sportradar_id, yahoo_id,
    fantasy_data_id, rotowire_id, full_name, team, position, season``,
    plus the optional ``sleeper_id`` / ``sleeper_id_str`` /
    ``sleeper_player_id`` columns the orchestrator's
    ``_read_nflverse_qbs`` synthesizes.

    Only rows where ``position == "QB"`` are considered. The 2025
    sealed holdout is excluded by an explicit filter so a 2025 row
    can never accidentally contribute to a crosswalk entry.
    """
    qbs = nflverse_qbs
    if "position" in qbs.columns:
        qbs = qbs.filter(pl.col("position") == "QB")
    if "db_season" in qbs.columns:
        qbs = qbs.filter(pl.col("db_season") != 2025)
    if "season" in qbs.columns:
        try:
            seasons = qbs.select(pl.col("season").cast(pl.Int64)).to_series().to_list()
        except Exception:
            seasons = []
        if any(s == 2025 for s in seasons):
            qbs = qbs.filter(pl.col("season") != 2025)

    gsis_index: dict[str, set[str]] = {}
    espn_index: dict[str, set[str]] = {}
    other_index: dict[str, set[str]] = {}
    name_team_index: dict[tuple[str, str], set[str]] = {}
    sleeper_index: dict[str, set[str]] = {}

    def _add(index: dict[str, set[str]], token: str, nflverse_id: str) -> None:
        if not token or not nflverse_id:
            return
        index.setdefault(token, set()).add(nflverse_id)

    for row in qbs.to_dicts():
        nflverse_id = row.get("player_id")
        if not nflverse_id:
            continue
        for col, index in (
            ("gsis_id", gsis_index),
            ("espn_id", espn_index),
        ):
            value = row.get(col)
            if value:
                _add(index, str(value).strip(), str(nflverse_id))
        for col in ("sportradar_id", "yahoo_id", "fantasy_data_id", "rotowire_id"):
            value = row.get(col)
            if value:
                _add(other_index, str(value).strip(), str(nflverse_id))
        for sleeper_col in ("sleeper_id_str", "sleeper_id", "sleeper_player_id"):
            value = row.get(sleeper_col)
            if value:
                _add(sleeper_index, str(value).strip(), str(nflverse_id))
        full_name = _normalize_name(row.get("full_name") or "")
        first = _normalize_name(row.get("first_name") or "")
        last = _normalize_name(row.get("last_name") or "")
        first_last = (first + last) if first and last else ""
        team = _normalize_team(row.get("team") or "")
        for name_key in (full_name, first_last):
            if name_key and team:
                name_team_index.setdefault((name_key, team), set()).add(str(nflverse_id))
    return gsis_index, espn_index, other_index, name_team_index, sleeper_index


def build_crosswalk(
    *,
    snapshot_id: str,
    active_qb_frame: pl.DataFrame,
    nflverse_qbs: pl.DataFrame,
) -> pl.DataFrame:
    """Run the crosswalk over the active QB frame.

    Returns a polars frame with the canonical schema. Rows that cannot
    be matched still appear with ``is_matched = False`` so the audit
    can report an exact unmatched count.
    """
    indexes = build_nflverse_indexes(nflverse_qbs)
    rows = active_qb_frame.to_dicts()
    crosswalk_rows = [
        _row_for_sleeper(
            snapshot_id=snapshot_id,
            sleeper_record=row,
            gsis_to_nflverse=indexes[0],
            espn_to_nflverse=indexes[1],
            other_stable_to_nflverse=indexes[2],
            name_team_to_nflverse=indexes[3],
            sleeper_to_nflverse=indexes[4],
        )
        for row in rows
    ]
    if not crosswalk_rows:
        return pl.DataFrame(
            {
                field: pl.Series(name=field, values=[], dtype=dt)
                for field, dt in CROSSWALK_DTYPES.items()
            }
        )
    frame = pl.DataFrame(crosswalk_rows, infer_schema_length=len(crosswalk_rows))
    frame = frame.select(
        [
            pl.col(field).cast(dt, strict=False).alias(field)
            for field, dt in CROSSWALK_DTYPES.items()
        ]
    )
    return frame.sort(["sleeper_team", "sleeper_name", "sleeper_player_id"], nulls_last=True)
