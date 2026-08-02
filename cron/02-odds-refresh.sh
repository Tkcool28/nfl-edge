#!/bin/bash
# NFL Edge - 12:00 PM ET daily refresh
# Fetches odds from The Odds API, scores the week, refreshes picks.
set -e
cd /root/nfl-edge
source .env 2>/dev/null || true
/root/mlb-ev-model-lab/.venv/bin/python3 -m nfl_edge.ingest_odds
/root/mlb-ev-model-lab/.venv/bin/python3 -m nfl_edge.score_week
echo "[$(date)] NFL Edge refresh complete" >> /var/log/nfl-edge.log
