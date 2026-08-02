# NFL Edge 🏈

A pre-game NFL win-probability model with a mobile-first Streamlit dashboard.
Pulls live odds from The Odds API, scores each week's slate against a stacked
ensemble (QB-adjusted Elo + XGBoost + market-implied), and surfaces picks on a
public URL via Caddy reverse-proxy.

**Live URL:** `https://nfl.tkhermes.duckdns.org/` (live from Week 1, 2026 season)

## Architecture

- **Models:** QB-adjusted Elo (FiveThirtyEight-style) + XGBoost on nflfastR
  features + market-implied probability, combined with a logistic stacker.
- **Data:** [nflverse/nfl_data_py](https://github.com/nflverse/nfl_data_py) for
  play-by-play + schedule; [The Odds API v4](https://the-odds-api.com/) for DK
  + FD + Pinnacle.
- **UI:** Streamlit, dark theme, mobile-first single column.
- **Hosting:** Streamlit on `127.0.0.1:8503`, Caddy reverse-proxy on
  `nfl.tkhermes.duckdns.org`.
- **Refresh:** 12:00 PM ET daily (free tier). 11:58 PM ET available with paid tier.

See [docs/nfl-model-build-plan.md](docs/nfl-model-build-plan.md) for the full
build plan and [docs/NFL_Edge_Build_Plan.pdf](docs/NFL_Edge_Build_Plan.pdf) for
the rendered PDF.

## Repo layout

```
nfl-edge/
├── src/nfl_edge/        # model + ingestion code
├── app/                 # Streamlit dashboard
├── data/                # .gitignored — parquet + JSON cache
├── models/              # .gitignored — trained artifacts
├── systemd/             # systemd unit
├── cron/                # refresh + retrain scripts
├── tests/               # pytest suite
└── docs/                # this plan + PDF
```

## Local setup

```bash
git clone https://github.com/Tkcool28/nfl-edge.git
cd nfl-edge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env to add your ODDS_API_KEY
```

## Running

```bash
# Ingest data (one-time)
python -m nfl_edge.ingest_nflverse --seasons 2020 2021 2022 2023 2024
python -m nfl_edge.ingest_odds

# Train models
python -m nfl_edge.train_xgb
python -m nfl_edge.train_stacker

# Score this week
python -m nfl_edge.score_week

# Launch dashboard
streamlit run app/streamlit_app.py --server.port 8503
```

## Deploy on VPS

See [docs/nfl-model-build-plan.md §7](docs/nfl-model-build-plan.md#7-the-vps-deployment).

## Data sources

- **nflverse/nfl_data_py** — play-by-play, schedules, rosters (free, no auth)
- **FiveThirtyEight NFL Elo** — historical Elo ratings (free, GitHub)
- **The Odds API** — live DK / FD / Pinnacle (free tier: 500 credits/month)
- **OpenWeather** — kickoff-time weather (free tier: 60 calls/min)

## License

MIT
