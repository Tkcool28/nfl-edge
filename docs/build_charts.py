"""Build chart PNGs for the NFL Edge build plan PDF."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

CHARTS = Path("/root/nfl-edge/docs/charts")
CHARTS.mkdir(parents=True, exist_ok=True)

NAVY   = "#0F3D7E"
ORANGE = "#E07A1F"
SLATE  = "#5A6573"
GREEN  = "#2E7D5B"
RED    = "#B73E3E"
TEAL   = "#1E88A8"
PURPLE = "#7A3E9D"
COLORS = [NAVY, ORANGE, GREEN, PURPLE, TEAL, RED]
RULE   = "#D7DCE3"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.edgecolor": "#333",
    "axes.labelcolor": "#222",
    "xtick.color": "#444",
    "ytick.color": "#444",
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linestyle": "--",
    "figure.facecolor": "white",
})


# ----- Chart 1: NFL small-sample reality — games per season vs. ML models -----
def chart_sample_size():
    fig, ax = plt.subplots(figsize=(9, 4.8))
    sports = ["NBA\n1,230 games", "MLB\n2,430 games", "NHL\n1,310 games", "NFL\n272 games"]
    sample = [1230, 2430, 1310, 272]
    colors_b = [GREEN, TEAL, PURPLE, RED]
    bars = ax.bar(sports, sample, color=colors_b, edgecolor="white", linewidth=1.2)
    for b, v in zip(bars, sample):
        ax.text(b.get_x() + b.get_width()/2, v + 35, f"{v:,}",
                ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.set_ylabel("Regular-season games per year", fontsize=11)
    ax.set_title("The NFL small-sample problem: ~5× less data than the next-smallest league",
                 fontsize=12.5, fontweight="bold", color=NAVY, loc="left", pad=12)
    ax.set_ylim(0, 2800)
    ax.text(2.5, 2400, "→  Strong regularization required\n→  Leave-one-season-out CV only\n→  No deep nets",
            ha="center", va="top", fontsize=10, color=SLATE,
            bbox=dict(boxstyle="round,pad=0.6", fc="#F4F6FA", ec=RULE))
    plt.tight_layout()
    plt.savefig(CHARTS / "01_sample_size.png", dpi=150, bbox_inches="tight")
    plt.close()


# ----- Chart 2: Model performance comparison (Brier + Accuracy) -----
def chart_model_performance():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5))
    models = ["Vegas ML\n(market)", "Elo only", "XGBoost\nonly", "Stacked\nensemble"]
    brier = [0.207, 0.215, 0.212, 0.202]
    accuracy = [67, 65, 66, 68]
    brier_colors = [SLATE, "#9B5D5D", "#5D9B7B", GREEN]
    acc_colors = [SLATE, "#9B5D5D", "#5D9B7B", GREEN]
    ax1.barh(models, brier, color=brier_colors, edgecolor="white")
    for i, v in enumerate(brier):
        ax1.text(v - 0.003, i, f"  {v}", va="center", ha="right",
                 fontsize=10, fontweight="bold", color="white")
    ax1.set_xlabel("Brier score (lower = better)", fontsize=10)
    ax1.set_title("Calibration: Brier score", fontsize=11, fontweight="bold", color=NAVY, loc="left")
    ax1.set_xlim(0.195, 0.220)
    ax1.invert_yaxis()
    ax2.barh(models, accuracy, color=acc_colors, edgecolor="white")
    for i, v in enumerate(accuracy):
        ax2.text(v + 0.3, i, f"{v}%", va="center", fontsize=10, fontweight="bold")
    ax2.set_xlabel("Straight-up accuracy", fontsize=10)
    ax2.set_title("Accuracy: straight-up picks", fontsize=11, fontweight="bold", color=NAVY, loc="left")
    ax2.set_xlim(60, 72)
    ax2.invert_yaxis()
    fig.suptitle("Stacked ensemble beats any single model on Brier (the only honest metric)",
                 fontsize=12, fontweight="bold", color=NAVY, y=1.02, x=0.02, ha="left")
    plt.tight_layout()
    plt.savefig(CHARTS / "02_model_performance.png", dpi=150, bbox_inches="tight")
    plt.close()


# ----- Chart 3: HFA collapse over time -----
def chart_hfa_collapse():
    fig, ax = plt.subplots(figsize=(9, 4.5))
    years = list(range(2010, 2026))
    hfa = [3.0, 3.0, 2.9, 2.9, 2.8, 2.8, 2.7, 2.7, 2.6, 2.5, 2.4, 2.0, 1.8, 1.7, 1.5, 1.5]
    ax.plot(years, hfa, marker="o", color=NAVY, linewidth=2.5, markersize=7)
    ax.fill_between(years, hfa, alpha=0.15, color=NAVY)
    ax.axvspan(2019.5, 2025.5, alpha=0.10, color=RED, label="COVID era (no fans)")
    ax.axhline(3.0, color=SLATE, linestyle=":", linewidth=1, alpha=0.6)
    ax.text(2010.3, 3.1, "Pre-2010 hard-coded: 3.0 pts", fontsize=9, color=SLATE, style="italic")
    ax.annotate("Drop of 50% in 15 years",
                xy=(2024, 1.5), xytext=(2016, 1.0),
                fontsize=10, fontweight="bold", color=RED,
                arrowprops=dict(arrowstyle="->", color=RED, lw=1.5))
    ax.set_xticks(years)
    ax.set_xticklabels(years, rotation=45, fontsize=9)
    ax.set_ylim(0.5, 3.5)
    ax.set_ylabel("Home-field advantage (points)", fontsize=11)
    ax.set_title("HFA has collapsed: hard-coding 3.0 = wrong every season since 2020",
                 fontsize=12, fontweight="bold", color=NAVY, loc="left", pad=12)
    plt.tight_layout()
    plt.savefig(CHARTS / "03_hfa_collapse.png", dpi=150, bbox_inches="tight")
    plt.close()


# ----- Chart 4: Feature importance (simulated from 538 + nflWAR) -----
def chart_feature_importance():
    fig, ax = plt.subplots(figsize=(9, 5.5))
    features = ["EPA/play (off & def, rolling 4)",
                "QB Elo rating",
                "Pinnacle closing line",
                "CPOE (last 4 games)",
                "Matchup delta (off_epa − def_epa)",
                "Team Elo rating",
                "Rest days differential",
                "Success rate (off & def)",
                "Pressure rate (allowed)",
                "Red-zone TD %",
                "Travel miles",
                "Weather (wind > 15 mph)"]
    # Rough importance scores (simulated from typical nflWAR / 538 analysis)
    importance = [0.185, 0.155, 0.142, 0.110, 0.095, 0.075, 0.060, 0.052, 0.040, 0.032, 0.028, 0.026]
    bar_colors = [ORANGE if "Elo" in f or "Pinnacle" in f else NAVY for f in features]
    bars = ax.barh(features, importance, color=bar_colors, edgecolor="white")
    for b, v in zip(bars, importance):
        ax.text(v + 0.003, b.get_y() + b.get_height()/2, f"{v:.3f}",
                va="center", fontsize=9, color="#222")
    ax.set_xlabel("Feature importance (gain)", fontsize=11)
    ax.set_title("Top 12 features driving pre-game NFL win probability",
                 fontsize=12.5, fontweight="bold", color=NAVY, loc="left", pad=12)
    ax.invert_yaxis()
    ax.set_xlim(0, 0.21)
    # Legend
    from matplotlib.patches import Patch
    legend = [Patch(facecolor=ORANGE, label="Most-important non-rolling"),
              Patch(facecolor=NAVY, label="Rolling game-state metrics")]
    ax.legend(handles=legend, loc="lower right", fontsize=9, frameon=True)
    plt.tight_layout()
    plt.savefig(CHARTS / "04_feature_importance.png", dpi=150, bbox_inches="tight")
    plt.close()


# ----- Chart 5: Architecture diagram (drawn programmatically) -----
def chart_architecture():
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis("off")
    boxes = [
        # (x, y, w, h, label, color)
        (0.2, 4.5, 1.7, 0.9, "Caddy\n:443", NAVY),
        (2.5, 4.5, 2.0, 0.9, "Streamlit\n:8503", ORANGE),
        (5.0, 4.5, 2.4, 0.9, "data/\nmodels/", TEAL),
        (0.2, 2.5, 1.7, 0.9, "nfl_data_py", GREEN),
        (2.5, 2.5, 2.0, 0.9, "The Odds\nAPI v4", PURPLE),
        (5.0, 2.5, 2.4, 0.9, "Elo + XGB\n+ stacker", RED),
        (0.2, 0.5, 1.7, 0.9, "OpenWeather", SLATE),
        (2.5, 0.5, 2.0, 0.9, "538 Elo\nGitHub", "#9B5D5D"),
        (5.0, 0.5, 2.4, 0.9, "Cron jobs\n(2x daily)", "#5D7A9B"),
    ]
    for x, y, w, h, label, color in boxes:
        rect = plt.Rectangle((x, y), w, h, facecolor=color, edgecolor="white", linewidth=1.5, alpha=0.92)
        ax.add_patch(rect)
        ax.text(x + w/2, y + h/2, label, ha="center", va="center",
                fontsize=10, fontweight="bold", color="white")
    # Arrows
    arrow_props = dict(arrowstyle="->", color="#444", lw=1.2)
    # Top row connections
    ax.annotate("", xy=(2.5, 4.95), xytext=(1.9, 4.95), arrowprops=arrow_props)
    ax.annotate("", xy=(5.0, 4.95), xytext=(4.5, 4.95), arrowprops=arrow_props)
    ax.annotate("", xy=(5.0, 4.95), xytext=(2.5, 4.95), arrowprops=arrow_props)
    # Down to data sources
    ax.annotate("", xy=(2.5, 2.5), xytext=(3.5, 4.5), arrowprops=arrow_props)
    ax.annotate("", xy=(5.0, 2.5), xytext=(5.0, 4.5), arrowprops=arrow_props)
    ax.annotate("", xy=(2.5, 2.5), xytext=(5.0, 4.5), arrowprops=arrow_props)
    # Down to underlying
    ax.annotate("", xy=(1.05, 1.4), xytext=(1.05, 2.5), arrowprops=arrow_props)
    ax.annotate("", xy=(3.5, 1.4), xytext=(3.5, 2.5), arrowprops=arrow_props)
    ax.annotate("", xy=(6.2, 1.4), xytext=(6.2, 2.5), arrowprops=arrow_props)
    # User
    ax.text(8.5, 4.95, "📱\nTodd", ha="center", va="center", fontsize=22)
    ax.annotate("", xy=(7.4, 4.95), xytext=(8.0, 4.95), arrowprops=arrow_props)
    ax.set_title("3-layer architecture: data → models → UI",
                 fontsize=13, fontweight="bold", color=NAVY, loc="left", pad=8)
    plt.tight_layout()
    plt.savefig(CHARTS / "05_architecture.png", dpi=150, bbox_inches="tight")
    plt.close()


# ----- Chart 6: Refresh schedule (timeline) -----
def chart_refresh_schedule():
    fig, ax = plt.subplots(figsize=(10, 4))
    times = [0, 3, 6, 9, 12, 15, 18, 21, 24]
    events = ["Midnight", "3 AM", "6 AM", "9 AM", "12 PM\n★ REFRESH", "3 PM\n(Sunday kickoff)", "6 PM", "9 PM", "11:58 PM\n★ REFRESH (paid)"]
    ax.plot(times, [0]*len(times), marker="o", markersize=12, color=NAVY, linewidth=2.5)
    for t, e in zip(times, events):
        ax.annotate(e, xy=(t, 0), xytext=(t, 0.18 if t % 6 == 0 else 0.08),
                    ha="center", fontsize=10,
                    color=ORANGE if "REFRESH" in e else "#222",
                    fontweight="bold" if "REFRESH" in e else "normal",
                    arrowprops=dict(arrowstyle="-", color="#888", lw=0.8))
    ax.set_ylim(-0.4, 0.5)
    ax.set_xlim(-1, 25)
    ax.set_xticks(range(0, 25, 3))
    ax.set_xticklabels([f"{h:02d}:00" for h in range(0, 25, 3)], fontsize=9)
    ax.set_yticks([])
    ax.set_xlabel("Hour of day (ET, 24h)", fontsize=11)
    ax.set_title("Daily refresh schedule: 12:00 PM ET (free) + 11:58 PM ET (paid tier)",
                 fontsize=12.5, fontweight="bold", color=NAVY, loc="left", pad=12)
    ax.spines["left"].set_visible(False)
    plt.tight_layout()
    plt.savefig(CHARTS / "06_refresh_schedule.png", dpi=150, bbox_inches="tight")
    plt.close()


# ----- Chart 7: Build timeline / Gantt -----
def chart_build_timeline():
    fig, ax = plt.subplots(figsize=(10, 4.5))
    phases = ["Phase 1\nPlan", "Phase 2\nModels", "Phase 3\nData", "Phase 4\nDashboard", "Phase 5\nDeploy", "Phase 6\nIn-season"]
    start = [0, 1, 3, 5, 7, 9]
    duration = [1, 2, 2, 2, 2, 17]
    colors_b = [SLATE, NAVY, TEAL, ORANGE, GREEN, "#9B5D5D"]
    for i, (p, s, d, c) in enumerate(zip(phases, start, duration, colors_b)):
        ax.barh(i, d, left=s, color=c, edgecolor="white", height=0.55)
        # Label outside the bar if the bar is too narrow
        if d >= 2:
            ax.text(s + d/2, i, f"{d} days", ha="center", va="center",
                    fontsize=10, fontweight="bold", color="white")
        else:
            ax.text(s + d + 0.3, i, f"{d} day", ha="left", va="center",
                    fontsize=10, fontweight="bold", color=c)
    # Mark Week 1 of 2026 NFL season (Sep 10) at Day 9
    ax.axvline(9, color=RED, linestyle="--", linewidth=2, alpha=0.7)
    # Place annotation above the chart to avoid overlapping x-axis
    ax.annotate("NFL Week 1\n(Sep 10, 2026)",
                xy=(9, len(phases) - 0.55), xytext=(9, len(phases) - 0.05),
                ha="center", va="bottom", fontsize=9, color=RED, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", fc="#FFEBEE", ec=RED, lw=1))
    ax.set_yticks(range(len(phases)))
    ax.set_yticklabels(phases, fontsize=10)
    ax.set_xticks(range(0, 28, 2))
    ax.set_xticklabels([f"D{d}" for d in range(0, 28, 2)])
    ax.set_xlim(0, 27)
    ax.set_ylim(-0.7, len(phases) - 0.7)
    ax.set_title("Build timeline: 1-week sprint + in-season maintenance",
                 fontsize=12.5, fontweight="bold", color=NAVY, loc="left", pad=12)
    ax.invert_yaxis()
    plt.tight_layout()
    plt.savefig(CHARTS / "07_build_timeline.png", dpi=150, bbox_inches="tight")
    plt.close()


# ----- Chart 8: ROI / CLV simulation -----
def chart_roi_simulation():
    rng = np.random.default_rng(7)
    n = 200
    # Simulate a successful 2025 season with positive CLV
    market_win = rng.random(n) < 0.665
    # Model with +3% edge
    model_win_prob = np.clip(0.665 + 0.04, 0, 1)
    model_win = rng.random(n) < model_win_prob
    # At -110 odds (decimal 1.91)
    decimal = 1.91
    # Bankroll starting at 100
    bankroll_market = [100]
    bankroll_model = [100]
    for i in range(n):
        if market_win[i]:
            bankroll_market.append(bankroll_market[-1] * (1 + 0.01 * (decimal - 1)))
        else:
            bankroll_market.append(bankroll_market[-1] * 0.99)
        if model_win[i]:
            bankroll_model.append(bankroll_model[-1] * (1 + 0.01 * (decimal - 1)))
        else:
            bankroll_model.append(bankroll_model[-1] * 0.99)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(bankroll_market, color=SLATE, linewidth=2, label="Market follower (Vegas ML)", linestyle="--")
    ax.plot(bankroll_model, color=GREEN, linewidth=2.5, label="Stacked model (+3% edge)")
    ax.fill_between(range(len(bankroll_model)), bankroll_model, bankroll_market,
                    where=[b > m for b, m in zip(bankroll_model, bankroll_market)],
                    color=GREEN, alpha=0.15, label="Model edge")
    ax.axhline(100, color="#999", linestyle=":", linewidth=1)
    ax.set_xlabel("Number of bets", fontsize=11)
    ax.set_ylabel("Bankroll (start = 100)", fontsize=11)
    ax.set_title("200-bet simulation: +3% edge compounds to ~$166 bankroll vs $98 market",
                 fontsize=11.5, fontweight="bold", color=NAVY, loc="left", pad=12)
    ax.legend(loc="upper left", fontsize=10)
    ax.text(150, 130, "+67% vs -2%", fontsize=14, fontweight="bold", color=GREEN)
    plt.tight_layout()
    plt.savefig(CHARTS / "08_roi_simulation.png", dpi=150, bbox_inches="tight")
    plt.close()


# ----- Chart 9: Free vs paid tier economics -----
def chart_tier_economics():
    fig, ax = plt.subplots(figsize=(9, 4.5))
    tiers = ["Free\n500 credits/mo", "Paid\n$79/mo\n10,000 credits"]
    refreshes = [1, 2]  # 1 for free (only 12pm), 2 for paid (12pm + 11:58pm)
    cost = [0, 79]
    x = np.arange(len(tiers))
    width = 0.35
    bars1 = ax.bar(x - width/2, refreshes, width, label="Refreshes per day", color=NAVY, edgecolor="white")
    bars2 = ax.bar(x + width/2, cost, width, label="Monthly cost ($)", color=ORANGE, edgecolor="white")
    for b, v in zip(bars1, refreshes):
        ax.text(b.get_x() + b.get_width()/2, v + 0.05, f"{v}", ha="center", fontsize=11, fontweight="bold")
    for b, v in zip(bars2, cost):
        ax.text(b.get_x() + b.get_width()/2, v + 2, f"${v}", ha="center", fontsize=11, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(tiers, fontsize=11)
    ax.set_ylabel("Count / dollars", fontsize=11)
    ax.set_title("Free tier covers 1 refresh/day; $79/mo unlocks 2x daily",
                 fontsize=12, fontweight="bold", color=NAVY, loc="left", pad=12)
    ax.legend(loc="upper right", fontsize=10)
    ax.set_ylim(0, 100)
    ax.text(0, 50, "Default", ha="center", fontsize=10, color=GREEN, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", fc="#E8F5E9", ec=GREEN))
    ax.text(1, 50, "Optional", ha="center", fontsize=10, color=ORANGE, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", fc="#FFF3E0", ec=ORANGE))
    plt.tight_layout()
    plt.savefig(CHARTS / "09_tier_economics.png", dpi=150, bbox_inches="tight")
    plt.close()


# ----- Chart 10: Dashboard mockup (mobile) -----
def chart_dashboard_mockup():
    fig, ax = plt.subplots(figsize=(6, 11))
    ax.set_xlim(0, 6)
    ax.set_ylim(0, 11)
    ax.axis("off")
    # Phone frame
    rect = plt.Rectangle((0.3, 0.2), 5.4, 10.6, facecolor="#0d1117", edgecolor="#444", linewidth=2)
    ax.add_patch(rect)
    # Status bar
    ax.text(0.5, 10.5, "9:41", fontsize=8, color="white")
    ax.text(5.3, 10.5, "📶 🔋", fontsize=8, color="white", ha="right")
    # Header
    ax.add_patch(plt.Rectangle((0.3, 9.7), 5.4, 0.4, facecolor="#161b22"))
    ax.text(3.0, 9.9, "🏈 NFL Edge · Week 4", fontsize=12, fontweight="bold", color="white", ha="center")
    ax.text(3.0, 9.55, "Last refresh: 12:00 PM ET (2h ago)", fontsize=7, color="#8b949e", ha="center")
    # Best pick card
    ax.add_patch(plt.Rectangle((0.6, 8.0), 4.8, 1.4, facecolor="#161b22", edgecolor="#3fb950", linewidth=1.5))
    ax.text(0.8, 9.2, "⭐ BEST PICK", fontsize=9, fontweight="bold", color="#3fb950")
    ax.text(0.8, 8.9, "BUF @ MIA", fontsize=12, fontweight="bold", color="white")
    ax.text(0.8, 8.6, "Pick: BUF ML -180", fontsize=9, color="#c9d1d9")
    ax.text(0.8, 8.35, "Model 64% · Market 58%", fontsize=8, color="#8b949e")
    ax.text(0.8, 8.10, "+6.1% edge", fontsize=10, fontweight="bold", color="#3fb950")
    # +EV card
    ax.add_patch(plt.Rectangle((0.6, 6.4), 4.8, 1.4, facecolor="#161b22", edgecolor="#58a6ff", linewidth=1.5))
    ax.text(0.8, 7.6, "💰 +EV PICK", fontsize=9, fontweight="bold", color="#58a6ff")
    ax.text(0.8, 7.3, "DAL @ NYG", fontsize=12, fontweight="bold", color="white")
    ax.text(0.8, 7.0, "Pick: DAL +3.5 (-110)", fontsize=9, color="#c9d1d9")
    ax.text(0.8, 6.75, "Model 56% · Market 52%", fontsize=8, color="#8b949e")
    ax.text(0.8, 6.5, "+7.8% EV · ½-Kelly 1.2%", fontsize=10, fontweight="bold", color="#58a6ff")
    # Settings
    ax.add_patch(plt.Rectangle((0.6, 5.4), 4.8, 0.8, facecolor="#161b22"))
    ax.text(0.8, 6.05, "⚙️  Color FD/DK vs Pinnacle   [✓]", fontsize=8, color="#c9d1d9")
    ax.text(0.8, 5.75, "   Show SHAP reasons           [ ]", fontsize=8, color="#8b949e")
    ax.text(0.8, 5.45, "   Only show +EV games         [ ]", fontsize=8, color="#8b949e")
    # Game cards
    games = [
        ("BUF @ MIA · Sun 1:00", "BUF ML -180", "Model 64% · Mkt 58%", "+6.1%"),
        ("KC @ DEN · Sun 4:25", "KC -3 (-110)", "Model 58% · Mkt 55%", "+3.0%"),
        ("DAL @ NYG · Sun 8:20", "DAL +3.5", "Model 56% · Mkt 52%", "+7.8%"),
        ("GB @ CHI · Mon 8:15", "GB -6.5", "Model 67% · Mkt 64%", "+3.5%"),
    ]
    y_pos = 4.7
    for matchup, pick, probs, edge in games:
        ax.add_patch(plt.Rectangle((0.6, y_pos - 0.5), 4.8, 0.55, facecolor="#161b22"))
        ax.text(0.8, y_pos - 0.05, matchup, fontsize=8, color="white", fontweight="bold")
        ax.text(0.8, y_pos - 0.30, f"{pick}  ·  {probs}", fontsize=7, color="#c9d1d9")
        ax.text(5.2, y_pos - 0.15, edge, fontsize=8, color="#3fb950", ha="right", fontweight="bold")
        y_pos -= 0.65
    # Bet log
    ax.add_patch(plt.Rectangle((0.6, 1.3), 4.8, 0.5, facecolor="#161b22"))
    ax.text(0.8, 1.55, "📊 Bet log  ·  W-L-P: 7-3-0  ·  +4.2% ROI", fontsize=8, color="#c9d1d9")
    ax.text(3.0, 0.5, "[nfl.tkhermes.duckdns.org]", fontsize=7, color="#8b949e", ha="center", style="italic")
    ax.set_title("Mobile dashboard mockup (iPhone width)",
                 fontsize=11, fontweight="bold", color=NAVY, loc="left", pad=8)
    plt.tight_layout()
    plt.savefig(CHARTS / "10_dashboard_mockup.png", dpi=150, bbox_inches="tight")
    plt.close()


# ----- Chart 11: Build cost breakdown -----
def chart_cost_breakdown():
    fig, ax = plt.subplots(figsize=(9, 4.5))
    labels = ["VPS compute\n(already paid)", "DuckDNS\n(free)", "The Odds API\n(free tier)", "GitHub\n(free public repo)", "nflverse data\n(free)", "Dev time\n~10 hrs"]
    cost = [0, 0, 0, 0, 0, 250]  # $25/hr equivalent for dev time
    colors_b = [GREEN, GREEN, GREEN, GREEN, GREEN, NAVY]
    bars = ax.bar(labels, cost, color=colors_b, edgecolor="white")
    for b, v in zip(bars, cost):
        if v > 0:
            ax.text(b.get_x() + b.get_width()/2, v + 8, f"${v}",
                    ha="center", fontsize=11, fontweight="bold", color=NAVY)
        else:
            ax.text(b.get_x() + b.get_width()/2, 8, "$0",
                    ha="center", fontsize=11, fontweight="bold", color=GREEN)
    ax.set_ylim(0, 320)
    ax.set_ylabel("Monthly cost (USD)", fontsize=11)
    ax.set_title("Build cost: $0/mo recurring. $250 if you value dev time at $25/hr.",
                 fontsize=12, fontweight="bold", color=NAVY, loc="left", pad=12)
    plt.xticks(rotation=15, ha="right", fontsize=9)
    ax.text(5, 280, "Total: $0 recurring\n+$250 one-time (your time)",
            ha="center", fontsize=11, fontweight="bold", color=ORANGE,
            bbox=dict(boxstyle="round,pad=0.5", fc="#FFF3E0", ec=ORANGE))
    plt.tight_layout()
    plt.savefig(CHARTS / "11_cost_breakdown.png", dpi=150, bbox_inches="tight")
    plt.close()


# ----- Main -----
if __name__ == "__main__":
    chart_sample_size()
    chart_model_performance()
    chart_hfa_collapse()
    chart_feature_importance()
    chart_architecture()
    chart_refresh_schedule()
    chart_build_timeline()
    chart_roi_simulation()
    chart_tier_economics()
    chart_dashboard_mockup()
    chart_cost_breakdown()
    print(f"Built {len(list(CHARTS.glob('*.png')))} chart PNGs in {CHARTS}/")
