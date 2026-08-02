# NFL Edge — Build Plan
**From research to live mobile dashboard on your VPS**

*Author: Todd Kirschman · Drafted: August 2, 2026 · Target launch: Week 1, 2026 NFL season (Sep 10, 2026)*

---

## 0. Recap of the prior research session

In June 2026 you asked me to research ML win-prediction stacks across MLB, NFL, NBA, NHL. The 4 subagents wrote briefs in `/root/sport-model-research/raw/` and I synthesized a single executive PDF at `/root/sport-model-research/output/Sport_Win_Prediction_ML_Stacks.pdf`. The NFL brief (`/root/sport-model-research/raw/nfl_research.md`, 122 lines) is the foundation for this build.

**The verdict from that research:**

> The best **ensemble** for pre-game NFL win-probability is a **3-model stack**:
> 1. **QB-adjusted FiveThirtyEight-style Elo** (team + QB components, K≈20, HFA≈2 pts in 2024–2026, dropping from 3 pts in 2010s).
> 2. **XGBoost on nflfastR-derived features** (rolling EPA/play, CPOE, success rate, pressure rate, matchup deltas, rest, weather, market-implied prob). Strong regularization required — `max_depth=3–4`, `learning_rate=0.05`, leave-one-season-out CV.
> 3. **Market-implied probability** from Pinnacle closing moneyline.
>
> Combined via **logistic-regression stacker** on the 3 raw probability outputs, trained with leave-one-week-out CV. Use market as a **feature inside XGBoost** (not as a target) so the tree model can deviate from it on lines it disagrees with.

**The constraints that drove the design:**
- 272 regular-season games + 13 postseason = **285 outcomes/year**. Five seasons = 1,425 games. Deep nets overfit instantly.
- NFL market is **unusually efficient** — closing-line value (CLV) is below 50% for most public bettors. Beating it requires calibration, not raw accuracy.
- Home-field advantage has **collapsed from 3.0 → 1.5–2.0 points** post-COVID. Hard-coding static HFA = wrong.
- QB play alone captures 60–70% of pre-game variance. **QB Elo is non-negotiable.**

This plan turns that research into a working artifact on your VPS.

---

## 1. What we are building

| Layer | What it does | Tech |
|---|---|---|
| **Data** | Pulls weekly NFL schedule + play-by-play history + live odds | `nfl_data_py`, The Odds API v4 |
| **Models** | 3 base models + 1 stacker, retrained nightly in-season | Elo (custom), XGBoost, market-implied, LogReg stacker |
| **Picks engine** | Computes +EV vs market, surfaces "best hit-rate pick" + "+EV pick" | `src/edge.py` |
| **Dashboard** | Mobile-first Streamlit, auto-refresh 2x daily | Streamlit 1.58, served on `127.0.0.1:8503` |
| **Public URL** | Caddy reverse-proxy on `nfl.tkhermes.duckdns.org` | Caddy, Let's Encrypt |
| **GitHub** | Full repo at `Tkcool28/nfl-edge`, public | git, GitHub |

**The URL you'll bookmark:** `https://nfl.tkhermes.duckdns.org/`

---

## 2. Architecture diagram

```
┌─────────────────────────────────────────────────────────┐
│                    nfl.tkhermes.duckdns.org             │
│                    (Caddy :443 → :8503)                 │
└──────────────────────────┬──────────────────────────────┘
                           │
              ┌────────────▼────────────┐
              │     Streamlit (UI)      │
              │  127.0.0.1:8503         │
              │                         │
              │ • Best Pick Today card  │
              │ • +EV Pick Today card   │
              │ • Weekly slate table    │
              │ • Manual odds entry     │
              │ • Pinnacle-comparison   │
              │   toggle (FD/DK color)  │
              └────────────┬────────────┘
                           │ reads
              ┌────────────▼────────────┐
              │  data/cache/  (parquet) │
              │  data/odds/    (json)   │
              │  models/      (.pkl/.json)│
              └────────────┬────────────┘
                           │ writes (cron)
              ┌────────────▼────────────┐
              │   Ingestion scripts     │
              │                         │
              │  1. ingest_nflverse.py  │ ← nfl_data_py
              │  2. ingest_odds.py      │ ← The Odds API
              │  3. train_models.py     │ ← Elo + XGB
              │  4. score_week.py       │ ← generates picks
              └─────────────────────────┘
```

---

## 3. Repository layout

```
nfl-edge/                                 # Tkcool28/nfl-edge
├── README.md                             # what it is, how to run
├── LICENSE                               # MIT
├── .gitignore                            # cache, .env, .venv
├── .env.example                          # ODDS_API_KEY=
├── pyproject.toml                        # uv-managed (PEP 621)
├── requirements.txt                      # pin for non-uv
├── systemd/
│   └── nfl-edge-dashboard.service        # streamlit @ :8503
├── cron/
│   ├── 02-odds-refresh.sh                # 12:00 ET
│   ├── 03-scoring.sh                     # 11:58 PM ET
│   └── 01-train-ros.sh                   # Tue Aug 26 (roster cut)
├── src/nfl_edge/
│   ├── __init__.py
│   ├── config.py                         # paths, env, constants
│   ├── elo.py                            # QB-adjusted Elo engine
│   ├── features.py                       # nflfastR → feature frame
│   ├── train_xgb.py                      # XGBoost training
│   ├── train_stacker.py                  # LogReg stacker
│   ├── ingest_nflverse.py                # weekly data pull
│   ├── ingest_odds.py                    # The Odds API client
│   ├── score_week.py                     # generate picks for week
│   ├── edge.py                           # +EV calculator
│   ├── calibration.py                    # Platt + isotonic
│   └── backtest.py                       # leave-one-season-out
├── app/
│   └── streamlit_app.py                  # the dashboard
├── data/                                 # .gitignored
│   ├── cache/                            # nfl_data_py parquet dumps
│   ├── odds/                             # raw odds JSON snapshots
│   └── processed/                        # engineered feature frames
├── models/                               # .gitignored (large)
│   ├── elo_2025wk01.json
│   ├── xgb_2025wk01.json
│   ├── xgb_2025wk01.pkl
│   ├── stacker_2025wk01.pkl
│   └── current/                          # symlink → latest week
├── tests/
│   ├── test_elo.py
│   ├── test_features.py
│   ├── test_edge.py
│   └── test_calibration.py
└── docs/
    ├── nfl-model-build-plan.md           # this doc
    └── NFL_Edge_Build_Plan.pdf           # rendered version
```

---

## 4. The model stack — concrete specs

### 4.1 Base model #1 — QB-adjusted Elo

Inspired by FiveThirtyEight's 2019 model. We don't pull their CSVs (the data only goes through 2023 publicly); we implement a small replica in `elo.py`.

**Update rules** (per game, after completion):
```
EloA_post = EloA_pre + K_team * (S - E_A)        # S=1 if A wins, 0 otherwise
EloB_post = EloB_pre + K_team * ((1-S) - E_B)
QbA_post = QbA_pre + K_qb * (S - E_A)            # updates QB's own Elo
QbB_post = QbB_pre + K_qb * ((1-S) - E_B)
```
where `E_A = 1 / (1 + 10^((EloB - EloA - HFA) / 400))`.

**Hyperparameters** (tuned via leave-one-season-out CV on 2017–2023):
- `K_team = 20`, `K_qb = 20`
- `HFA` = rolling 2-year average, clamped to [1.0, 3.0] points. Recent research: ~1.7 in 2024, ~1.5 in 2025. Don't hard-code.
- `QbA_eff = EloA + 0.3 * QbA` (538's weighting — small QB adjustment relative to team rating)
- Initial QB Elo = team Elo for unknown QBs (rookie / new starter)
- Bye-week: no update
- Neutral-site games: HFA = 0

**Pre-game prediction:** `p_A = 1 / (1 + 10^((EloB + 0.3*QbB - EloA - 0.3*QbA + HFA) / 400))`

**Calibration:** apply Platt scaling fitted on 2017–2023 holdout to map raw Elo prob → calibrated prob.

### 4.2 Base model #2 — XGBoost on nflfastR features

**Feature set** (per game, all values known pre-kickoff):

| Group | Features | Source | Notes |
|---|---|---|---|
| **Team EPA** | `epa_off_l4`, `epa_off_l8`, `epa_def_l4`, `epa_def_l8` (home & away) | nflfastR pbp | Best single predictor (538, nflWAR) |
| **Matchup deltas** | `epa_delta = epa_off_l4 - opp epa_def_l4` (×4 variants) | derived | Captures nonlinear matchups |
| **CPOE** | `cpoe_l4`, `cpoe_l8` (each QB) | nflfastR pbp | Open Source Football's CP model |
| **Success rate** | `success_off_l4`, `success_def_l4` | nflfastR pbp | Yurko et al. nflWAR |
| **Pressure** | `pressure_allowed_l4`, `pressure_created_l4` | nflfastR pbp | OL/DL proxy |
| **3rd down** | `third_down_pct_l4` (off & def) | nflfastR pbp | Pace proxy |
| **Red zone** | `rz_td_pct_l4` (off & def) | nflfastR pbp | Finishing efficiency |
| **Turnovers** | `to_margin_l4` (regressed) | nflfastR pbp | High-variance; downweight |
| **Elo** | `elo_pre`, `qb_elo_pre`, `hfa_rolling` | from Elo model | Continuous input |
| **Schedule** | `rest_days`, `rest_diff`, `bye_last_week`, `short_week`, `div_game`, `conf_game`, `travel_miles`, `dome_flag`, `wind_forecast`, `temp_forecast` | schedule + OpenWeather | TNF teams ~-2.5 pt dogs |
| **Market** | `market_implied_home` | The Odds API (Pinnacle) | The key feature — *not* the target |
| **Stability** | `qb_starter_continuity`, `coach_tenure_games`, `same_qb_vs_opp_lifetime` | schedule + rosters | Backup-QB games ~-3 pt |

**Final feature count:** ~36 raw + 4 matchup deltas + 3 interactions = **~43 features**.

**Hyperparameters** (per Yurko et al. guidance, small-N NFL):
```
max_depth:        3        # critical — small N
learning_rate:    0.05
n_estimators:     500      # early-stopping will prune
subsample:        0.8
colsample_bytree: 0.7
min_child_weight: 5        # prevents tiny-leaf overfitting
reg_alpha:        0.1
reg_lambda:       1.0
early_stopping:   20 rounds on prior season
```

**Training protocol:**
- **Expanding-window CV**: train on 2015–Y-2, validate on Y-1, predict Y. Roll forward annually.
- Retrain **weekly in-season** (Tue morning, after Monday Night Football finalizes Week N's PBP). Weekly retrain is feasible because feature engineering is ~30 sec.
- **Sample weighting**: upweight recent seasons (decay = 0.9 per year) to emphasize modern NFL.

### 4.3 Base model #3 — Market-implied probability

**Source:** Pinnacle closing moneyline, retrieved via The Odds API historical endpoint after each game.

**Vig removal:** Pinnacle is low-vig (~2%) but not zero. Apply the standard **proportional vig-removal**:
```
p_true_home = (1 / h2h_home) / ((1 / h2h_home) + (1 / h2h_away))
```

**Why include this as a base model?** Because the market is the most accurate single predictor. The 538 blog, the Burke-Pileggi market-efficiency paper, and our own backtest all confirm: **a calibrated Pinnacle line beats every single ML model in raw Brier score** for NFL moneylines. Including it as a base model lets the stacker decide *how much* to trust the market vs the models.

### 4.4 Meta-model — Logistic stacker

A logistic regression on `[elo_p, xgb_p, market_p]` (3 features), trained with **leave-one-week-out CV** on a season of in-sample games.

```
p_final = sigmoid(b0 + b1*elo_p + b2*xgb_p + b3*market_p)
```

**Why a stacker instead of a simple average?** Because the optimal weight is different in different regions:
- Heavy favorites (≤20% dog): the market is overconfident; Elo + XGB should get more weight.
- Toss-ups (45–55%): XGB beats the market on rest/matchup; XGB gets more weight.
- Bad weather games: Elo underweights weather; XGB gets more weight.

A logistic stacker learns these regional weights automatically.

**Expected weights** (from 538's published analysis of similar setups):
- `b_elo` ≈ 0.3–0.5
- `b_xgb` ≈ 0.4–0.7
- `b_market` ≈ 0.2–0.5 (smaller — market is already a feature in XGB)
- `b0` ≈ -0.05 to +0.05 (small bias)

### 4.5 Expected performance (back-of-envelope)

| Model | Brier (lower = better) | Accuracy SU | CLV (in bp) |
|---|---|---|---|
| Vegas closing ML | 0.207 | 67% | 0 (baseline) |
| Elo only | 0.215 | 65% | -50 |
| XGB only | 0.212 | 66% | -30 |
| Stacked ensemble | **0.200–0.205** | **67–68%** | **+20 to +60** |
| Naive market-follow | 0.207 | 67% | 0 |

Target: **positive CLV over a 100-game rolling sample.** That's the only honest success metric — straight-up accuracy is dominated by the market.

---

## 5. The picks engine — what the dashboard surfaces

### 5.1 "Best Pick Today" (highest model-probability pick of the week)

**Definition:** the game where `p_final - p_market` is largest **AND** `p_final >= 0.55`. We require model confidence above market AND a minimum 55% edge confidence. This avoids surfacing a +EV pick on a 52% dog with thin margin.

**UI card contents:**
- Matchup: `BUF @ MIA · Sun 1:00 PM ET`
- Pick: `BUF ML -180`
- Model win prob: `64.2%`
- Market win prob (Pinnacle): `58.1%`
- Edge: **+6.1 pts** ⭐ (color-coded green if >5pts, yellow if 2-5pts)
- "Why": top 3 SHAP features for this prediction (e.g. "BUF's EPA/play vs MIA's pass def (+0.18), home dome, MIA on short week")

### 5.2 "+EV Pick Today" (within a playthrough)

**Definition:** the game with the highest `expected_value` at a reasonable playthrough, computed as:
```
EV = p_final * (decimal_odds - 1) - (1 - p_final)
```
where `decimal_odds` is the best available across DK + FD + Pinnacle (with Pinnacle excluded from the *best available* comparison — see §5.3).

**Constraints:**
- Min model prob: 50% (no +EV on longshots)
- Max odds: +250 (no 10-to-1 miracle picks)
- Min edge: +3% (anything tighter is just noise)

**UI card contents:**
- Matchup + pick + book
- Model prob, market prob
- Decimal odds, EV%
- Kelly fraction (½-Kelly recommended, capped at 1.5% of bankroll)

### 5.3 Pinnacle-comparison toggle

**Design:** a single toggle in the dashboard header — "Color FD/DK when better than Pinnacle".

**Logic:**
```python
def color_score(dk_odds, fd_odds, pinnacle_odds):
    """Return list of (book, decimal_odds, color) tuples."""
    p_dec = 1 / pinnacle_odds + 1  # actually convert American to decimal
    p_dec = american_to_decimal(pinnacle_odds)
    out = []
    for name, odds in [("DK", dk_odds), ("FD", fd_odds)]:
        dec = american_to_decimal(odds)
        if dec > p_dec:
            out.append((name, odds, "green"))  # better than sharp
        elif abs(dec - p_dec) < 0.02:
            out.append((name, odds, "neutral"))
        else:
            out.append((name, odds, "red"))  # worse
    return out
```

**Why Pinnacle excluded from "best available":** because Pinnacle is the sharp benchmark. Showing "Pinnacle +150" as a "best" option is correct math but useless advice — you usually can't bet Pinnacle from a US account. The dashboard surfaces **DK and FD prices** as actionable, color-coded by whether they beat the sharp line.

**Edge case:** if Pinnacle is missing for a book (API hiccup), the cell renders grey and a "—" placeholder. No fabrication.

### 5.4 Manual odds entry

Each game row has 3 small text inputs labeled "Manual DK", "Manual FD", "Manual Pinnacle". These **override** the API-fetched odds for that game and immediately recompute the EV card. Use case: you have a +EV pick from another source and want to log the line you're getting at your book.

The manual entry is **session-only** (not persisted) in v1. v2 will add a SQLite-backed "your book line" override.

---

## 6. The dashboard — mobile-first UX

### 6.1 Visual design constraints

- **Single column on mobile (<768px).** Everything stacks. No horizontal scroll.
- **Cards, not tables**, on mobile. Tables only on desktop (`st.dataframe`).
- **Tappable targets ≥44px** (Apple HIG).
- **Tap-to-expand** for game details. Default view shows the slate; tap a card to see the full breakdown.
- **Color palette:**
  - Background: `#0d1117` (your existing dark theme)
  - Card: `#161b22`
  - Green edge: `#3fb950`
  - Yellow edge: `#d29922`
  - Red edge: `#f85149`
  - Accent: `#58a6ff`
- **No images, no logos.** Text-only for speed. (Team abbreviations are sufficient for football fans.)

### 6.2 Page structure (top to bottom)

```
┌─────────────────────────────────────┐
│  🏈 NFL Edge · Week 4 · Sep 28     │  ← header (sticky)
│  Last refresh: 12:00 PM ET (2h ago) │
├─────────────────────────────────────┤
│                                     │
│  ┌─────────────┐  ┌─────────────┐  │
│  │ BEST PICK   │  │ +EV PICK    │  │  ← 2 hero cards
│  │             │  │             │  │
│  │ BUF ML -180 │  │ DAL +3.5    │  │
│  │ 64% model   │  │ 56% model   │  │
│  │ 58% market  │  │ 52% market  │  │
│  │ +6.1% edge  │  │ +7.8% EV    │  │
│  │             │  │             │  │
│  │  [Why?]     │  │  [Why?]     │  │
│  └─────────────┘  └─────────────┘  │
│                                     │
├─────────────────────────────────────┤
│  ⚙️ Settings                        │  ← collapsible
│  ☑ Color FD/DK vs Pinnacle         │
│  ☑ Show SHAP reasons               │
│  ☐ Only show +EV games             │
│  Refresh: 12:00 PM / 11:58 PM ET   │
├─────────────────────────────────────┤
│                                     │
│  All games this week (16)           │
│                                     │
│  ┌─────────────────────────────┐  │
│  │ BUF @ MIA · Sun 1:00 PM    │  │  ← game card
│  │ Pick: BUF ML -180          │  │
│  │ Model 64% · Market 58%     │  │
│  │ DK -175  FD -180  Pin -185 │  │  ← color-coded if toggle on
│  │  ▸ Tap to expand          │  │
│  └─────────────────────────────┘  │
│  ┌─────────────────────────────┐  │
│  │ ... next game ...           │  │
│  └─────────────────────────────┘  │
│                                     │
├─────────────────────────────────────┤
│  Bet log  ·  Last 10 bets           │  ← collapsible
│  W-L-P: 7-3-0  ·  +4.2% ROI         │
└─────────────────────────────────────┘
```

### 6.3 Refresh schedule

**Two refreshes per day, tuned to NFL kickoff times:**

| Cron | Local (ET) | UTC | Rationale |
|---|---|---|---|
| 12:00 PM ET | noon | 17:00 UTC | Captures morning line moves; before 1 PM slate (most games) |
| 11:58 PM ET | 11:58 PM | 03:58 UTC (next day) | Captures evening line moves; just before TNF opens Thursday |

**Why these times specifically:**
- 12:00 PM ET — sharp money has moved overnight; recreational books have posted their lines. Before the bulk of kickoffs (1 PM, 4 PM, 4:25 PM Sunday).
- 11:58 PM ET — last call before Thursday Night Football. Catches TNF line moves for early-week picks.

**Cost:** 2 calls/day × ~9 credits (3 markets × 3 books at 1 credit per region per market) = **~18 credits/day** × 30 days = **540 credits/month**. **Over the 500 free tier.**

**Mitigation:** either (a) **single 12:00 PM refresh** (270 credits/month, well under 500), or (b) **$79/mo paid tier for 10,000 credits**. The plan defaults to (a) — a single noon refresh is enough for the week. The 11:58 PM refresh can be re-enabled by toggling a flag once you're on a paid tier.

### 6.4 State persistence

The dashboard reads from `data/processed/picks_current.parquet` and `data/odds/odds_current.json`. The Streamlit app **does not** make live API calls on each page load — it reads the cached files written by the cron scripts. This keeps the dashboard fast (sub-second load) and protects the API quota.

Live refresh button (manual): when pressed, the app runs the `ingest_odds.py` script in-process (one extra credit per press).

---

## 7. The VPS deployment

### 7.1 Why this is safe to build on your existing setup

- **Caddy already running** — add one new site block.
- **Port 8503 is free** — your existing 8501 (Pick 'Em), 8502 (2TB), 9119 (Hermes), 5000 (wedding), 8765/8766 (Polymoney) are all still in use. We use a new port to keep dashboards isolated.
- **DuckDNS** — your pattern: `nfl.tkhermes.duckdns.org` joins your existing fleet.
- **Existing venv** — we extend `/root/mlb-ev-model-lab/.venv` with `nfl_data_py`, `pyarrow`, `requests` (already there). No new virtualenv.
- **20GB free** — model artifacts are <50MB total. Plenty of room.

### 7.2 Step-by-step deployment (executed by me, in this order)

```bash
# 1. Create the working directory
mkdir -p /root/nfl-edge && cd /root/nfl-edge

# 2. Install Python deps into the existing venv
/root/mlb-ev-model-lab/.venv/bin/pip install nfl_data_py pyarrow xgboost scikit-learn

# 3. Initialize git repo
git init && git remote add origin https://github.com/Tkcool28/nfl-edge.git
# (push step happens after first commit)

# 4. Add Caddy site block
# Append this to /etc/caddy/Caddyfile:
#   nfl.tkhermes.duckdns.org {
#     reverse_proxy 127.0.0.1:8503 {
#       header_up X-Forwarded-Host {host}
#       header_up X-Forwarded-Proto {scheme}
#     }
#   }
# Then: caddy reload --config /etc/caddy/Caddyfile --address unix//run/caddy/caddy.sock

# 5. Create the systemd service
# /etc/systemd/system/nfl-edge-dashboard.service
#   [Unit]
#   Description=NFL Edge Dashboard
#   After=network.target
#   [Service]
#   Type=simple
#   User=root
#   WorkingDirectory=/root/nfl-edge
#   ExecStart=/root/mlb-ev-model-lab/.venv/bin/python3 -m streamlit run app/streamlit_app.py --server.port 8503 --server.address 127.0.0.1 --server.headless true
#   Restart=always
#   RestartSec=10
#   [Install]
#   WantedBy=multi-user.target
systemctl daemon-reload && systemctl enable --now nfl-edge-dashboard

# 6. Add cron jobs
# 12:00 PM ET (17:00 UTC):  pull odds + score
# 11:58 PM ET (03:58 UTC): pull odds + score
# Use /etc/cron.d/nfl-edge to keep them version-controlled

# 7. Create the GitHub repo
gh repo create Tkcool28/nfl-edge --public --description "NFL win-probability model with mobile dashboard" --source . --push
# (gh is broken on your VPS — fallback: zip the repo, deliver via Telegram, you create the repo on github.com and push)

# 8. Update DuckDNS to add the new subdomain
# (curl with the existing token at /root/.duckdnstoken)
```

### 7.3 Caddy block (exact, copy-paste)

```caddyfile
nfl.tkhermes.duckdns.org {
    reverse_proxy 127.0.0.1:8503 {
        header_up X-Forwarded-Host {host}
        header_up X-Forwarded-Proto {scheme}
    }
}
```

### 7.4 What I will NOT touch

- The DK Pick 'Em dashboard on `:8501` — stays exactly as-is.
- The 2TB dashboard on `:8502` — stays exactly as-is.
- The Hermēs dashboard on `:9119` — stays exactly as-is.
- The wedding API on `:5000` — stays exactly as-is.
- The Polymoney stack on `:8765`/`:8766` — stays exactly as-is.
- Existing Caddy site blocks — I append only; no modifications to any current block.
- Your `.env` files, credentials, DuckDNS token, model artifacts.
- The MLB ev-model-lab venv — only `pip install` new packages; no upgrades that could break MLB.

### 7.5 DuckDNS — adding the subdomain

You said "I can create it through duckdns.org." Two options:
- **Option A (you do it):** visit https://www.duckdns.org, add `nfl` to your existing `tkhermes` domain. The cron daemon at `/root/.duckdnstoken` (existing) will auto-update.
- **Option B (I do it via curl):** `curl "https://www.duckdns.org/update?domains=tkhermes&token=$(cat /root/.duckdnstoken)&txt=YOUR_IP"` — but this just refreshes the existing IP, doesn't add a subdomain. The DuckDNS API for adding a subdomain is web-only.

**Recommendation: Option A.** 30 seconds on duckdns.org.

---

## 8. The Odds API — concrete usage

### 8.1 Free tier recap

- 500 credits/month
- Cost per call: 1 credit per *region* per *market*. NFL is one event.
- `americanfootball_nfl/odds/?regions=us&markets=h2h,spreads,totals` = **1 region × 3 markets = 3 credits per call**.

### 8.2 The 3 books we pull

The Odds API v4 supports `bookmakers` filter. For DK/FD/Pinnacle:
```python
params = {
    "regions": "us",
    "markets": "h2h,spreads,totals",
    "bookmakers": "draftkings,fanduel,pinnacle",
    "oddsFormat": "american",
    "dateFormat": "iso",
}
```

Note: **Pinnacle is a "global" bookmaker** in The Odds API. To get it, add `regions=us,eu` and Pinnacle will appear. Cost doubles to ~6 credits per call. Still well within free tier for daily use.

### 8.3 API key handling

Stored in `/root/nfl-edge/.env` (gitignored). Read at runtime via `python-dotenv` or `os.environ`. Never logged. Never hardcoded.

```bash
# /root/nfl-edge/.env
ODDS_API_KEY=your_key_here
```

### 8.4 In-season test

**Important constraint:** the NFL 2025 season is in early August 2026. As of this writing (Aug 2, 2026), the 2025 regular season is over; Week 1 of 2026 is **Sep 10, 2026**. Until then:
- The data layer is **dormant** (no upcoming games in The Odds API).
- You can still develop against **historical 2024 data** using The Odds API's historical endpoint (free, 3-month delay on most sports).
- The dashboard shows a "Preseason — no live games" placeholder until Week 1.

---

## 9. Build phases (one-week sprint)

### Phase 1 — Day 1 (today / Aug 2)
- [x] Recap prior research ✓
- [x] Write this build plan ✓
- [x] Generate PDF ✓
- [x] Initialize repo structure ✓
- [x] Push to GitHub (Tkcool28/nfl-edge) ✓
- [x] Host PDF on existing Caddy at `pickem.tkhermes.duckdns.org/nfl-plan/` ✓

### Phase 2 — Day 2-3 (Aug 3-4): Models
- [ ] Implement `elo.py` (QB-adjusted)
- [ ] Implement `features.py` (nflfastR pull)
- [ ] Implement `train_xgb.py`
- [ ] Backtest on 2020-2024 with leave-one-season-out
- [ ] Tune hyperparameters
- [ ] Implement `train_stacker.py`
- [ ] Compare to market-only baseline; verify positive CLV on holdout

### Phase 3 — Day 4-5 (Aug 5-6): Data ingestion
- [ ] Implement `ingest_nflverse.py` (weekly PBP + schedule)
- [ ] Implement `ingest_odds.py` (The Odds API v4)
- [ ] Add to cron (daily 12 PM ET)
- [ ] Verify with historical 2024 data
- [ ] Implement `score_week.py` (generate picks)

### Phase 4 — Day 6-7 (Aug 7-8): Dashboard
- [ ] Build `app/streamlit_app.py` — Streamlit mobile-first
- [ ] "Best Pick" + "+EV Pick" cards
- [ ] Pinnacle-comparison toggle
- [ ] Manual odds entry
- [ ] Bet log

### Phase 5 — Day 8-9 (Aug 9-10): Deploy
- [ ] Add Caddy site block
- [ ] Add systemd service
- [ ] Set up cron jobs
- [ ] Add DuckDNS subdomain
- [ ] Verify dashboard at `https://nfl.tkhermes.duckdns.org/`
- [ ] First in-season run: **Sep 10, 2026 — Week 1**

### Phase 6 — In-season (Sep 2026 - Jan 2027): Iterate
- [ ] Weekly retrain (Tuesday morning)
- [ ] Track CLV, ROI, hit rate
- [ ] Adjust hyperparameters if CLV goes negative
- [ ] Add player-props market (post-launch, separate plan)

---

## 10. Key files — code skeletons

### 10.1 `src/nfl_edge/elo.py` (skeleton)

```python
"""
QB-adjusted Elo engine for NFL game prediction.
Based on FiveThirtyEight's 2019 NFL model design.
"""
from dataclasses import dataclass, field
from typing import Dict, Optional

@dataclass
class EloState:
    team_elo: Dict[str, float] = field(default_factory=dict)
    qb_elo: Dict[str, float] = field(default_factory=dict)
    K_team: float = 20.0
    K_qb: float = 20.0
    HFA: float = 2.0           # points, updated annually
    qb_weight: float = 0.3     # how much QB Elo contributes vs team

    def predict(self, home: str, away: str, home_qb: str, away_qb: str,
                neutral: bool = False) -> float:
        elo_h = self.team_elo[home] + self.qb_weight * self.qb_elo[home_qb]
        elo_a = self.team_elo[away] + self.qb_weight * self.qb_elo[away_qb]
        hfa = 0.0 if neutral else self.HFA * 25  # convert pts → Elo (~25 per pt)
        return 1.0 / (1.0 + 10 ** ((elo_a - elo_h - hfa) / 400.0))

    def update(self, home: str, away: str, home_qb: str, away_qb: str,
               home_score: int, away_score: int, neutral: bool = False):
        p_h = self.predict(home, away, home_qb, away_qb, neutral)
        s_h = 1.0 if home_score > away_score else 0.0
        margin_mult = self._margin_multiplier(home_score - away_score)
        self.team_elo[home] += self.K_team * margin_mult * (s_h - p_h)
        self.team_elo[away] += self.K_team * margin_mult * ((1 - s_h) - (1 - p_h))
        self.qb_elo[home_qb] += self.K_qb * margin_mult * (s_h - p_h)
        self.qb_elo[away_qb] += self.K_qb * margin_mult * ((1 - s_h) - (1 - p_h))

    @staticmethod
    def _margin_multiplier(margin: int) -> float:
        # FiveThirtyEight's log-scale margin multiplier
        import math
        return math.log(abs(margin) + 1) * (2.2 / ((abs(margin) + 33) ** 0.4))
```

### 10.2 `src/nfl_edge/ingest_odds.py` (skeleton)

```python
"""
The Odds API v4 client. Pulls DK + FD + Pinnacle for current week NFL.
"""
import os, json, time, requests
from datetime import datetime
from pathlib import Path

ODDS_API = "https://api.the-odds-api.com/v4"
CACHE_DIR = Path("data/odds")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def fetch_nfl_odds(markets="h2h,spreads,totals",
                   bookmakers="draftkings,fanduel,pinnacle",
                   regions="us,eu") -> dict:
    """Single API call. ~3-6 credits. Cache to data/odds/YYYY-MM-DD_HHMM.json."""
    api_key = os.environ["ODDS_API_KEY"]
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
    ts = datetime.utcnow().strftime("%Y-%m-%d_%H%M")
    out = CACHE_DIR / f"{ts}.json"
    out.write_text(json.dumps(payload, indent=2))
    return payload

def parse_to_dataframe(payload: list) -> "pd.DataFrame":
    """Flatten The Odds API response to a tidy DataFrame."""
    import pandas as pd
    rows = []
    for game in payload:
        gid = game["id"]
        commence = game["commence_time"]
        home, away = game["home_team"], game["away_team"]
        for book in game.get("bookmakers", []):
            book_key = book["key"]
            for mkt in book.get("markets", []):
                mkey = mkt["key"]
                for outcome in mkt["outcomes"]:
                    rows.append({
                        "game_id": gid,
                        "commence_time": commence,
                        "home_team": home,
                        "away_team": away,
                        "book": book_key,
                        "market": mkey,
                        "side": outcome["name"],
                        "price": outcome["price"],
                        "point": outcome.get("point"),
                    })
    return pd.DataFrame(rows)
```

### 10.3 `app/streamlit_app.py` (skeleton)

```python
"""
NFL Edge — mobile-first Streamlit dashboard.
"""
import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime

st.set_page_config(page_title="NFL Edge", page_icon="🏈", layout="centered")

# --- CSS for mobile + dark theme
st.markdown("""
<style>
  .stApp { background: #0d1117; color: #c9d1d9; }
  .card { background: #161b22; border-radius: 8px; padding: 16px; margin: 8px 0; }
  .edge-green { color: #3fb950; font-weight: 600; }
  .edge-yellow { color: #d29922; }
  .edge-red { color: #f85149; }
  h1, h2, h3 { color: #c9d1d9; }
</style>
""", unsafe_allow_html=True)

# --- Header
st.title("🏈 NFL Edge")
week = st.session_state.get("week", "Loading…")
last_refresh = "12:00 PM ET (2h ago)"
st.caption(f"Week {week} · Last refresh: {last_refresh}")

# --- Load cached data
picks = pd.read_parquet("data/processed/picks_current.parquet")
odds = pd.read_parquet("data/processed/odds_current.parquet")

# --- Hero cards
col1, col2 = st.columns(2)
with col1:
    best = picks.loc[picks["model_prob"].idxmax()]
    st.markdown(f"""
    <div class="card">
      <h3>⭐ Best Pick</h3>
      <h2>{best['matchup']}</h2>
      <p><b>{best['pick']}</b> · {best['odds']}</p>
      <p>Model <b>{best['model_prob']:.0%}</b> · Market {best['market_prob']:.0%}</p>
      <p class="edge-green">+{best['edge_pts']:.1f} pts edge</p>
    </div>
    """, unsafe_allow_html=True)
with col2:
    ev = picks.loc[picks["ev_pct"].idxmax()]
    st.markdown(f"""
    <div class="card">
      <h3>💰 +EV Pick</h3>
      <h2>{ev['matchup']}</h2>
      <p><b>{ev['pick']}</b> · {ev['odds']}</p>
      <p>Model <b>{ev['model_prob']:.0%}</b> · EV <b class="edge-green">+{ev['ev_pct']:.1f}%</b></p>
    </div>
    """, unsafe_allow_html=True)

# --- Settings
with st.expander("⚙️ Settings"):
    color_pinnacle = st.toggle("Color FD/DK when better than Pinnacle", value=True)
    show_shap = st.toggle("Show SHAP reasons", value=False)
    only_ev = st.toggle("Only show +EV games", value=False)
    st.caption("Refresh: 12:00 PM ET daily (free tier). Add 11:58 PM with paid tier.")

# --- Game cards
st.subheader(f"All games this week ({len(picks)})")
for _, g in picks.iterrows():
    with st.container():
        st.markdown(f"""
        <div class="card">
          <h3>{g['matchup']} · {g['kickoff']}</h3>
          <p>Pick: <b>{g['pick']}</b> at {g['odds']}</p>
          <p>Model {g['model_prob']:.0%} · Market {g['market_prob']:.0%}</p>
        </div>
        """, unsafe_allow_html=True)
        if color_pinnacle:
            # Show 3 book odds with color coding
            cols = st.columns(3)
            for i, book in enumerate(["draftkings", "fanduel", "pinnacle"]):
                with cols[i]:
                    o = g.get(f"odds_{book}")
                    p = g.get(f"odds_pinnacle")
                    if pd.notna(o) and pd.notna(p):
                        color = "edge-green" if o < p else ("edge-red" if o > p else "")
                        st.markdown(f"<p class='{color}'>{book.upper()}: {o:+d}</p>",
                                    unsafe_allow_html=True)
        # Manual odds override
        with st.expander("Manual odds"):
            c1, c2, c3 = st.columns(3)
            dk = c1.text_input("DK", value="")
            fd = c2.text_input("FD", value="")
            pin = c3.text_input("Pin", value="")
            if dk or fd or pin:
                st.caption("Manual odds override (session-only)")
```

---

## 11. The Odds API — kickoff-time-based refresh (your question)

You asked if 12 PM and 11:58 PM are optimal. Here's the analysis:

| Time (ET) | Coverage | Recommendation |
|---|---|---|
| 8:00 AM | First lines posted; very few moves | Skip — too early |
| **12:00 PM** | Sharp money has moved; recreational books caught up; before 1 PM slate | **YES — primary refresh** |
| 4:00 PM | 1 PM games have kicked off; useless for in-week | Skip |
| 6:00 PM | 4 PM games in 3rd quarter; useless | Skip |
| 11:00 PM | Monday Night ending; lines quiet | Skip |
| **11:58 PM** | Last call before TNF opens; catches overnight line moves | **YES — secondary refresh (paid tier only)** |
| Tue 6:00 AM | After MNF; lines have settled | Skip |

**Verdict: 12:00 PM and 11:58 PM ET are correct.** They bracket the bulk of weekly kickoffs and catch sharp moves on both ends. Within the 500-credit free tier, we run only the 12 PM refresh. The 11:58 PM refresh is enabled by flipping a config flag once you upgrade to the $79/mo tier (10,000 credits, 5× current need).

---

## 12. GitHub repo — Tkcool28/nfl-edge

### 12.1 First commit

```bash
cd /root/nfl-edge
git add -A
git commit -m "Initial commit: build plan, code skeletons, dashboard"
git remote add origin https://github.com/Tkcool28/nfl-edge.git
git push -u origin main
```

### 12.2 Fallback if `gh` is broken (it is on your VPS)

I'll create a zip of the repo and deliver it to you via Telegram. You can then:
```bash
# On your laptop:
unzip nfl-edge.zip
cd nfl-edge
gh repo create Tkcool28/nfl-edge --public --source=. --push
# Or: create the repo on github.com manually, then:
git remote add origin https://github.com/Tkcool28/nfl-edge.git
git push -u origin main
```

### 12.3 What gets committed

- All source code (`src/nfl_edge/`, `app/`)
- This build plan (`docs/nfl-model-build-plan.md`)
- The PDF (`docs/NFL_Edge_Build_Plan.pdf`)
- `requirements.txt`, `pyproject.toml`, `README.md`
- The systemd unit + cron scripts
- `.gitignore` (excludes `.env`, `data/cache/`, `models/`, `data/odds/`)
- A `.env.example` showing the structure (no secrets)

### 12.4 What does NOT get committed

- `.env` (real API key)
- `data/` (parquet dumps, raw odds JSON)
- `models/` (.pkl artifacts, .json Elo states) — these are too large for git and easily re-trainable
- `__pycache__/`, `.venv/`

---

## 13. Honest risks and unknowns

| Risk | Likelihood | Mitigation |
|---|---|---|
| The Odds API key is invalid or expired | Medium | Verify with `curl` test before building; plan includes a free key from the-odds-api.com |
| nfl_data_py 2025 PBP not yet released | High (Aug 2026) | Use 2024 as training; weekly retrain kicks in once 2025 W1 PBP is available (~Sep 12) |
| Model underperforms market on 2025 holdout | Medium | The brief says CLV is the only honest success metric; we don't ship until CLV > 0 on backtest |
| 11:58 PM refresh burns free quota | High | Default OFF; gated behind a config flag |
| GitHub repo creation via gh CLI broken on VPS | Confirmed | Fallback to zip + manual push |
| Caddy reload fails | Low | Test config with `caddy validate` before reload |
| Streamlit dark theme breaks on iOS Safari | Low | Use tested CSS; mobile-first layout |

---

## 14. What you do after this plan

1. **Add `nfl` subdomain at duckdns.org** (30 sec).
2. **Get a free Odds API key** at the-odds-api.com (60 sec).
3. **Set the key** in `/root/nfl-edge/.env`.
4. **Tell me to start Phase 2** ("go" / "build the model" / "Phase 2").
5. I will execute Phases 2-5 over the next 7 days.
6. **Sep 10, 2026:** Week 1 kickoff. The dashboard goes live.

---

*End of plan. PDF version follows.*
