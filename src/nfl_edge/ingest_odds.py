"""The Odds API v4 client.

Pulls NFL odds from DraftKings, FanDuel, and Pinnacle.
Free tier: 500 credits/month. NFL at 6 credits/call (us,eu × 3 markets).
"""
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
import requests

ODDS_API = "https://api.the-odds-api.com/v4"
CACHE_DIR = Path("data/odds")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def fetch_nfl_odds(
    markets: str = "h2h,spreads,totals",
    bookmakers: str = "draftkings,fanduel,pinnacle",
    regions: str = "us,eu",
    api_key: Optional[str] = None,
    cache: bool = True,
) -> list:
    """Single API call. ~6 credits. Returns raw API response list."""
    if api_key is None:
        api_key = os.environ.get("ODDS_API_KEY", "")
    if not api_key:
        raise ValueError("ODDS_API_KEY not set. Put it in .env or pass api_key=.")
    url = f"{ODDS_API}/sports/americanfootball_nfl/odds/"
    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": markets,
        "bookmakers": bookmakers,
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if cache:
        ts = datetime.utcnow().strftime("%Y-%m-%d_%H%M")
        out = CACHE_DIR / f"{ts}.json"
        out.write_text(json.dumps(payload, indent=2))
    return payload


def american_to_decimal(american: int) -> float:
    """Convert American odds to decimal odds."""
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(american)


def american_to_implied(american: int) -> float:
    """Convert American odds to implied probability (with vig)."""
    if american > 0:
        return 100.0 / (american + 100)
    return abs(american) / (abs(american) + 100)


def remove_vig_proportional(home_odds: int, away_odds: int) -> tuple[float, float]:
    """Pinnacle-style proportional vig removal. Returns (true_p_home, true_p_away)."""
    p_h = american_to_implied(home_odds)
    p_a = american_to_implied(away_odds)
    total = p_h + p_a
    return p_h / total, p_a / total
