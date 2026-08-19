"""Deterministic, outcome-blind game identity resolution for the historical
market acquisition (Task 05E-D2, Phase B).

The Odds API ``event_id`` is an opaque hash unrelated to the frozen nflverse
``game_id``. Identity is therefore resolved ONLY from outcome-blind
identifiers:

* home / away team spellings (via a canonical alias map)
* season
* event ``commence_time`` against the frozen schedule kickoff (UTC)

No scores, results, or odds-derived outcomes are ever consulted. The alias map
was derived ONLY from team-name spellings observed in the raw acquisition
payloads (2020--2024).
"""

from __future__ import annotations

from dataclasses import dataclass

# Canonical nflverse abbreviation -> provider spellings observed in the raw
# acquisition payloads. Keyed by the abbreviation used in frozen ``game_id``.
# ``WAS`` carries two historical spellings (2020 "Football Team", later
# "Commanders"); all other teams use one spelling across 2020--2024.
TEAM_ALIASES: dict[str, tuple[str, ...]] = {
    "ARI": ("Arizona Cardinals",),
    "ATL": ("Atlanta Falcons",),
    "BAL": ("Baltimore Ravens",),
    "BUF": ("Buffalo Bills",),
    "CAR": ("Carolina Panthers",),
    "CHI": ("Chicago Bears",),
    "CIN": ("Cincinnati Bengals",),
    "CLE": ("Cleveland Browns",),
    "DAL": ("Dallas Cowboys",),
    "DEN": ("Denver Broncos",),
    "DET": ("Detroit Lions",),
    "GB": ("Green Bay Packers",),
    "HOU": ("Houston Texans",),
    "IND": ("Indianapolis Colts",),
    "JAX": ("Jacksonville Jaguars",),
    "KC": ("Kansas City Chiefs",),
    "LV": ("Las Vegas Raiders",),
    "LAC": ("Los Angeles Chargers",),
    "LA": ("Los Angeles Rams",),
    "MIA": ("Miami Dolphins",),
    "MIN": ("Minnesota Vikings",),
    "NE": ("New England Patriots",),
    "NO": ("New Orleans Saints",),
    "NYG": ("New York Giants",),
    "NYJ": ("New York Jets",),
    "PHI": ("Philadelphia Eagles",),
    "PIT": ("Pittsburgh Steelers",),
    "SF": ("San Francisco 49ers",),
    "SEA": ("Seattle Seahawks",),
    "TB": ("Tampa Bay Buccaneers",),
    "TEN": ("Tennessee Titans",),
    "WAS": ("Washington Commanders", "Washington Football Team"),
}

_NAME_TO_ABBR: dict[str, str] = {}
for _abbr, names in TEAM_ALIASES.items():
    for nm in names:
        _NAME_TO_ABBR[nm] = _abbr


class MatchError(RuntimeError):
    """Raised when game identity cannot be resolved unambiguously."""


@dataclass(frozen=True)
class MatchIdentity:
    """Canonical team identity resolved from an event or target game."""

    home_abbr: str | None
    away_abbr: str | None
    matched_exact: bool = True


def canonicalize_name(name: str | None) -> str | None:
    """Return the canonical abbreviation for a provider team name, else None."""
    if name is None:
        return None
    return _NAME_TO_ABBR.get(str(name).strip())


def resolve_event_identity(home_name: str | None, away_name: str | None) -> MatchIdentity:
    """Resolve a provider event's home/away full names to canonical abbrs.

    If either side is unrecognized the event cannot be deterministically
    matched; ``matched_exact`` is False so the caller must not force identity.
    """
    ha = canonicalize_name(home_name)
    aa = canonicalize_name(away_name)
    return MatchIdentity(home_abbr=ha, away_abbr=aa, matched_exact=ha is not None and aa is not None)


def event_abbr_pair(event: dict) -> frozenset[str] | None:
    """Resolve an Odds API event to an unordered canonical team-pair abbr set."""
    ident = resolve_event_identity(event.get("home_team"), event.get("away_team"))
    if not ident.matched_exact:
        return None
    return frozenset((ident.home_abbr, ident.away_abbr))


def _parse_game_id(game_id: str) -> tuple[str, str]:
    """Split a frozen nflverse ``game_id`` like ``2024_01_BAL_KC`` into
    ``(away_abbr, home_abbr)`` (format: ``<season>_<week>_<away>_<home>``)."""
    parts = str(game_id).split("_")
    if len(parts) != 4:
        raise MatchError(f"unparseable game_id {game_id!r}")
    return parts[2], parts[3]


def game_id_abbr_pair(game_id: str) -> frozenset[str]:
    """Return the unordered canonical team-pair abbr set for a frozen game_id."""
    away, home = _parse_game_id(game_id)
    return frozenset((away, home))