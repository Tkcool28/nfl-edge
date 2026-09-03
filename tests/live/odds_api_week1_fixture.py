from __future__ import annotations

from typing import Any, Mapping

TEAM_NAMES = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills", "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs", "LAC": "Los Angeles Chargers", "LAR": "Los Angeles Rams",
    "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings",
    "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
    "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks", "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
}

BOOKS = (
    ("draftkings", "DraftKings", 0),
    ("fanduel", "FanDuel", 3),
    ("pinnacle", "Pinnacle", 6),
)


def build_synthetic_week1_response(
    schedule: Mapping[str, Any], *, observed_at_utc: str = "2026-09-03T18:00:00Z"
) -> list[dict[str, Any]]:
    """Committed deterministic synthetic Odds API fixture for all 16 Week 1 games."""
    events: list[dict[str, Any]] = []
    for index, game in enumerate(schedule["games"]):
        home = str(game["home_team"])
        away = str(game["away_team"])
        home_ml = -120 - (index % 5) * 5
        away_ml = 100 + (index % 5) * 5
        home_spread = -2.5 - (index % 3)
        total = 43.5 + (index % 5)
        bookmakers: list[dict[str, Any]] = []
        for key, title, delta in BOOKS:
            bookmakers.append(
                {
                    "key": key,
                    "title": title,
                    "last_update": observed_at_utc,
                    "markets": [
                        {
                            "key": "h2h",
                            "last_update": observed_at_utc,
                            "outcomes": [
                                {"name": TEAM_NAMES[home], "price": home_ml + delta},
                                {"name": TEAM_NAMES[away], "price": away_ml + delta},
                            ],
                        },
                        {
                            "key": "spreads",
                            "last_update": observed_at_utc,
                            "outcomes": [
                                {"name": TEAM_NAMES[home], "price": -110 + delta, "point": home_spread},
                                {"name": TEAM_NAMES[away], "price": -110 - delta, "point": -home_spread},
                            ],
                        },
                        {
                            "key": "totals",
                            "last_update": observed_at_utc,
                            "outcomes": [
                                {"name": "Over", "price": -110 + delta, "point": total},
                                {"name": "Under", "price": -110 - delta, "point": total},
                            ],
                        },
                    ],
                }
            )
        events.append(
            {
                "id": f"synthetic-event-{index + 1:02d}",
                "sport_key": "americanfootball_nfl",
                "sport_title": "NFL",
                "commence_time": str(game["scheduled_start_utc"]),
                "home_team": TEAM_NAMES[home],
                "away_team": TEAM_NAMES[away],
                "bookmakers": bookmakers,
            }
        )
    return events
