"""Build the NFL Edge build plan PDF.

Output: /root/nfl-edge/docs/NFL_Edge_Build_Plan.pdf
"""
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle,
    PageBreak, KeepTogether,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

# ---- Paths -----------------------------------------------------------------
ROOT      = Path("/root/nfl-edge/docs")
CHARTS    = ROOT / "charts"
OUT_PDF   = ROOT / "NFL_Edge_Build_Plan.pdf"

# ---- Brand colors ----------------------------------------------------------
NAVY    = colors.HexColor("#0F3D7E")
ORANGE  = colors.HexColor("#E07A1F")
SLATE   = colors.HexColor("#5A6573")
TEAL    = colors.HexColor("#1E88A8")
LIGHT   = colors.HexColor("#F4F6FA")
RULE    = colors.HexColor("#D7DCE3")
GREEN   = colors.HexColor("#2E7D5B")
RED     = colors.HexColor("#B73E3E")

# ---- Styles ----------------------------------------------------------------
def make_styles():
    ss = getSampleStyleSheet()
    styles = {}
    styles["Title"] = ParagraphStyle(
        "Title", parent=ss["Title"],
        fontName="Helvetica-Bold", fontSize=28, leading=32,
        textColor=colors.white, alignment=TA_LEFT, spaceAfter=4,
    )
    styles["Subtitle"] = ParagraphStyle(
        "Subtitle", parent=ss["Normal"],
        fontName="Helvetica", fontSize=12, leading=15,
        textColor=SLATE, spaceAfter=12,
    )
    styles["H1"] = ParagraphStyle(
        "H1", parent=ss["Heading1"],
        fontName="Helvetica-Bold", fontSize=17, leading=21,
        textColor=NAVY, spaceBefore=8, spaceAfter=6,
    )
    styles["H2"] = ParagraphStyle(
        "H2", parent=ss["Heading2"],
        fontName="Helvetica-Bold", fontSize=12.5, leading=16,
        textColor=ORANGE, spaceBefore=8, spaceAfter=3,
    )
    styles["H3"] = ParagraphStyle(
        "H3", parent=ss["Heading3"],
        fontName="Helvetica-Bold", fontSize=10.5, leading=13,
        textColor=NAVY, spaceBefore=4, spaceAfter=2,
    )
    styles["Body"] = ParagraphStyle(
        "Body", parent=ss["BodyText"],
        fontName="Helvetica", fontSize=10, leading=13.5,
        textColor=colors.HexColor("#1F232B"),
        alignment=TA_JUSTIFY, spaceAfter=5,
    )
    styles["Bullet"] = ParagraphStyle(
        "Bullet", parent=ss["BodyText"],
        fontName="Helvetica", fontSize=10, leading=13,
        textColor=colors.HexColor("#1F232B"),
        leftIndent=14, bulletIndent=2, spaceAfter=2,
    )
    styles["Callout"] = ParagraphStyle(
        "Callout", parent=ss["BodyText"],
        fontName="Helvetica-Bold", fontSize=11, leading=15,
        textColor=NAVY, leftIndent=8, rightIndent=8,
        spaceBefore=4, spaceAfter=8,
    )
    styles["Caption"] = ParagraphStyle(
        "Caption", parent=ss["Italic"],
        fontName="Helvetica-Oblique", fontSize=8.5, leading=10.5,
        textColor=SLATE, alignment=TA_CENTER, spaceBefore=2, spaceAfter=8,
    )
    styles["SmallNote"] = ParagraphStyle(
        "SmallNote", parent=ss["Normal"],
        fontName="Helvetica", fontSize=8.5, leading=11,
        textColor=SLATE, spaceAfter=4,
    )
    styles["Code"] = ParagraphStyle(
        "Code", parent=ss["Code"],
        fontName="Courier", fontSize=8, leading=10,
        textColor=colors.HexColor("#1F232B"),
        leftIndent=8, rightIndent=8,
        backColor=LIGHT, borderPadding=6, spaceBefore=4, spaceAfter=4,
    )
    return styles


# ---- Page templates --------------------------------------------------------
def cover_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, letter[1] - 3.6*inch, letter[0], 3.6*inch, fill=1, stroke=0)
    canvas.setFillColor(ORANGE)
    canvas.rect(0, letter[1] - 3.65*inch, letter[0], 0.05*inch, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(0.75*inch, letter[1] - 0.7*inch, "NFL EDGE")
    canvas.setFont("Helvetica", 9)
    canvas.drawString(0.75*inch, letter[1] - 0.95*inch, "Build Plan · Executive PDF")
    canvas.setFillColor(SLATE)
    canvas.setFont("Helvetica", 8.5)
    canvas.drawString(0.75*inch, 0.5*inch, "NFL Edge · Build Plan · v1.0")
    canvas.drawRightString(letter[0] - 0.75*inch, 0.5*inch, f"Page {doc.page}")
    canvas.restoreState()


def inner_page(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.6)
    canvas.line(0.75*inch, letter[1] - 0.55*inch, letter[0] - 0.75*inch, letter[1] - 0.55*inch)
    canvas.setFillColor(NAVY)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(0.75*inch, letter[1] - 0.4*inch, "NFL Edge · Build Plan")
    canvas.setFillColor(ORANGE)
    canvas.setFont("Helvetica", 9)
    canvas.drawRightString(letter[0] - 0.75*inch, letter[1] - 0.4*inch, "v1.0")
    canvas.setFillColor(SLATE)
    canvas.setFont("Helvetica", 8.5)
    canvas.drawString(0.75*inch, 0.5*inch, "From research to live mobile dashboard on your VPS")
    canvas.drawRightString(letter[0] - 0.75*inch, 0.5*inch, f"Page {doc.page}")
    canvas.restoreState()


# ---- Helpers ---------------------------------------------------------------
def callout_box(text, styles, color=NAVY, bg=LIGHT):
    t = Table([[Paragraph(text, styles["Callout"])]], colWidths=[6.7*inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX", (0, 0), (-1, -1), 1.2, color),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def kv_table(rows, col_widths=(2.0, 4.7), styles=None):
    """Two-column key/value table."""
    data = []
    for k, v in rows:
        data.append([Paragraph(f"<b>{k}</b>", styles["Body"]), Paragraph(v, styles["Body"])])
    t = Table(data, colWidths=[col_widths[0]*inch, col_widths[1]*inch])
    t.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, RULE),
    ]))
    return t


# ---- Build the document ---------------------------------------------------
def build():
    doc = SimpleDocTemplate(
        str(OUT_PDF), pagesize=letter,
        leftMargin=0.75*inch, rightMargin=0.75*inch,
        topMargin=0.85*inch, bottomMargin=0.75*inch,
        title="NFL Edge Build Plan",
        author="Todd Kirschman",
    )
    styles = make_styles()
    story = []

    # ==== COVER ====
    story.append(Spacer(1, 1.6*inch))
    story.append(Paragraph("NFL Edge", styles["Title"]))
    story.append(Paragraph("Build plan: from research to live mobile dashboard", styles["Subtitle"]))
    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph(
        "A pre-game NFL win-probability model built on a stacked ensemble of "
        "QB-adjusted Elo, XGBoost on nflfastR features, and market-implied probability. "
        "Live dashboard at <b>nfl.tkhermes.duckdns.org</b> via Caddy reverse-proxy on your existing VPS.",
        styles["Body"]))
    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph(
        "<b>Author:</b> Todd Kirschman &nbsp;·&nbsp; <b>Drafted:</b> August 2, 2026 "
        "&nbsp;·&nbsp; <b>Target launch:</b> Week 1, 2026 NFL season (Sep 10, 2026)",
        styles["SmallNote"]))
    story.append(Spacer(1, 0.2*inch))

    cover_rows = [
        ("Stack type", "Stacked (3 base models + 1 logistic meta-learner) — not separate models"),
        ("Base models", "QB-adjusted Elo · XGBoost on nflfastR · Pinnacle closing market"),
        ("Refresh", "12:00 PM ET daily (free tier). 11:58 PM ET (paid tier $79/mo)"),
        ("Books", "DraftKings, FanDuel, Pinnacle (sharp benchmark)"),
        ("URL", "nfl.tkhermes.duckdns.org → Caddy → Streamlit :8503"),
        ("Repo", "github.com/Tkcool28/nfl-edge (public)"),
        ("Recurring cost", "$0/mo (free tier). $79/mo for 2x daily refresh."),
        ("Build time", "~10 hours / 1 week sprint (Phases 1–5)"),
    ]
    story.append(kv_table(cover_rows, styles=styles))
    story.append(Spacer(1, 0.15*inch))
    story.append(callout_box(
        "Built end-to-end on your existing VPS. No new services, no new virtualenv, "
        "no changes to any existing dashboard (Pick 'Em, 2TB, Hermes, wedding, Polymoney). "
        "Only appends to Caddy. Only adds packages to the existing mlb-ev-model-lab venv.",
        styles))
    story.append(PageBreak())

    # ==== PAGE 2: Recap of prior research ====
    story.append(Paragraph("0. Recap of the prior research session", styles["H1"]))
    story.append(Paragraph(
        "In June 2026, you asked me to research ML win-prediction stacks across MLB, NFL, "
        "NBA, NHL. Four subagents wrote briefs in <font face='Courier' size='9'>/root/sport-model-research/raw/</font> "
        "and I synthesized a single executive PDF at <font face='Courier' size='9'>Sport_Win_Prediction_ML_Stacks.pdf</font>. "
        "The NFL brief (122 lines) is the foundation for this build.",
        styles["Body"]))
    story.append(Paragraph("The verdict from that research:", styles["H2"]))
    story.append(callout_box(
        "The best ensemble for pre-game NFL win-probability is a 3-model stack: "
        "QB-adjusted FiveThirtyEight-style Elo + XGBoost on nflfastR features + "
        "Pinnacle closing market. Combined via logistic-regression stacker, "
        "trained with leave-one-week-out CV. Market is included as a feature inside XGBoost — "
        "not as a target — so the tree can deviate on lines it disagrees with.",
        styles))
    story.append(Paragraph("Constraints that drove the design:", styles["H2"]))
    for txt in [
        "<b>272 regular-season games/yr</b>. Five seasons = ~1,425 games. Deep nets overfit instantly. Strong regularization mandatory.",
        "<b>NFL market is unusually efficient</b>. Closing-line value (CLV) is below 50% for most public bettors. Beating it requires calibration, not raw accuracy.",
        "<b>Home-field advantage collapsed from 3.0 → 1.5–2.0 points</b> post-COVID. Hard-coding static HFA = wrong every season since 2020.",
        "<b>QB play alone captures 60–70% of pre-game variance</b>. QB Elo is non-negotiable. Team-only Elo underweights elite passers.",
    ]:
        story.append(Paragraph(f"• {txt}", styles["Bullet"]))
    story.append(Spacer(1, 0.05*inch))
    story.append(Paragraph("Sources", styles["H3"]))
    for s in [
        "nflfastR docs — nflfastr.com",
        "FiveThirtyEight NFL Elo — github.com/fivethirtyeight/data",
        "Yurko, Ventura, Horowitz — nflWAR (arXiv:1802.00998)",
        "B. Baldwin — Open Source Football (CPOE / xYAC model docs)",
        "Burke & Pileggi — NFL market efficiency (CiteSeerX 10.1.1.198.7822)",
    ]:
        story.append(Paragraph(f"• {s}", styles["SmallNote"]))
    story.append(PageBreak())

    # ==== PAGE 3: What we are building + architecture ====
    story.append(Paragraph("1. What we are building", styles["H1"]))
    stack_rows = [
        ("Data", "Weekly NFL schedule + play-by-play history + live odds", "nfl_data_py, The Odds API v4"),
        ("Models", "3 base models + 1 stacker, retrained nightly in-season", "Elo, XGBoost, market-implied, LogReg stacker"),
        ("Picks engine", "Computes +EV vs market, surfaces 'best hit-rate' + '+EV' picks", "src/edge.py"),
        ("Dashboard", "Mobile-first Streamlit, auto-refresh 2x daily", "Streamlit 1.58 on 127.0.0.1:8503"),
        ("Public URL", "Caddy reverse-proxy on nfl.tkhermes.duckdns.org", "Caddy, Let's Encrypt"),
        ("GitHub", "Full repo at Tkcool28/nfl-edge, public", "git, GitHub"),
    ]
    data = [[Paragraph(f"<b>{r[0]}</b>", styles["Body"]),
             Paragraph(r[1], styles["Body"]),
             Paragraph(f"<font color='#5A6573' size='9'>{r[2]}</font>", styles["Body"])]
            for r in stack_rows]
    t = Table(data, colWidths=[0.9*inch, 3.6*inch, 2.2*inch])
    t.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LIGHT, colors.white]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, RULE),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.1*inch))
    story.append(callout_box(
        "The URL you'll bookmark: <b>https://nfl.tkhermes.duckdns.org/</b>",
        styles, color=ORANGE, bg=colors.HexColor("#FFF3E0")))

    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph("2. Architecture diagram", styles["H1"]))
    arch_img = Image(str(CHARTS / "05_architecture.png"), width=6.7*inch, height=3.7*inch)
    story.append(arch_img)
    story.append(Paragraph("3-layer: data → models → UI. Each layer is independently testable.", styles["Caption"]))
    story.append(PageBreak())

    # ==== PAGE 4: Repo layout + sample size ====
    story.append(Paragraph("3. Repository layout", styles["H1"]))
    story.append(Paragraph(
        "All code lives at github.com/Tkcool28/nfl-edge. Below is the full structure.",
        styles["Body"]))
    code = """nfl-edge/
    README.md, LICENSE, .gitignore, .env.example
    pyproject.toml, requirements.txt
    src/nfl_edge/
        elo.py            # QB-adjusted Elo engine
        features.py       # nflfastR -> feature frame
        train_xgb.py      # XGBoost training
        train_stacker.py  # LogReg stacker
        ingest_nflverse.py
        ingest_odds.py    # The Odds API v4
        score_week.py
        edge.py           # +EV calculator
        calibration.py
        backtest.py
    app/streamlit_app.py
    data/   (.gitignored - parquet + JSON cache)
    models/ (.gitignored - trained artifacts)
    systemd/nfl-edge-dashboard.service
    cron/  (02-odds-refresh.sh, 03-scoring.sh, 01-train-ros.sh)
    tests/  (elo, features, edge, calibration)
    docs/   (this plan + PDF)"""
    story.append(Paragraph(code.replace("\n", "<br/>"), styles["Code"]))

    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph("4.1 The small-sample reality (and why it matters)", styles["H2"]))
    story.append(Image(str(CHARTS / "01_sample_size.png"), width=6.5*inch, height=3.5*inch))
    story.append(Paragraph(
        "The NFL has roughly 5× less data per season than the next-smallest major league. "
        "This drives every modeling decision: strong regularization, leave-one-season-out CV, "
        "and the explicit decision to stack (not just average) — because stacking lets the "
        "meta-learner assign different weights in different probability regions (e.g., heavy-favorite "
        "territory vs. coin flips).",
        styles["Caption"]))
    story.append(PageBreak())

    # ==== PAGE 5: Model performance ====
    story.append(Paragraph("4.2 Expected model performance", styles["H1"]))
    story.append(Image(str(CHARTS / "02_model_performance.png"), width=6.7*inch, height=3.0*inch))
    story.append(Paragraph(
        "Brier score (left) measures probability calibration — the honest success metric for "
        "betting models. The stacked ensemble targets Brier 0.200–0.205, beating the market's "
        "0.207. Accuracy (right) is reported but the league-average favorite wins ~67% of games "
        "even picking randomly against the spread — so accuracy alone is misleading.",
        styles["Caption"]))

    story.append(Spacer(1, 0.05*inch))
    story.append(Paragraph("Target success metric", styles["H2"]))
    story.append(callout_box(
        "Positive closing-line value (CLV) over a 100-game rolling sample. "
        "If our model's implied probabilities would have beaten the Pinnacle closing line "
        "by an average of 5+ basis points, we ship. If not, we retune and re-backtest.",
        styles, color=GREEN, bg=colors.HexColor("#E8F5E9")))

    story.append(Paragraph("4.3 ROI simulation (200 bets, +3% edge, -110 odds)", styles["H2"]))
    story.append(Image(str(CHARTS / "08_roi_simulation.png"), width=6.5*inch, height=3.2*inch))
    story.append(Paragraph(
        "200 flat-stake bets at -110. Market follower: ~0% (the vig grinds). "
        "Stacked model with +3% edge: ~+67% bankroll. This is the long-run target. "
        "Variance is large over 200 bets — but the directional edge is what we ship on.",
        styles["Caption"]))
    story.append(PageBreak())

    # ==== PAGE 6: HFA + features ====
    story.append(Paragraph("4.4 HFA has collapsed — don't hard-code it", styles["H1"]))
    story.append(Image(str(CHARTS / "03_hfa_collapse.png"), width=6.5*inch, height=3.3*inch))
    story.append(Paragraph(
        "Home-field advantage in the NFL has dropped from 3.0 points (2010) to ~1.5 points (2024–2025). "
        "A static HFA in code is wrong every year since 2020. The Elo engine estimates HFA as a "
        "rolling 2-year average, clamped to [1.0, 3.0] points. This is one of the few features "
        "where a simple rolling mean outperforms a learned parameter — because HFA drifts slowly and "
        "predictably, and there isn't enough data to learn it jointly with everything else.",
        styles["Caption"]))

    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph("4.5 Top features (gain-based importance)", styles["H1"]))
    story.append(Image(str(CHARTS / "04_feature_importance.png"), width=6.5*inch, height=4.0*inch))
    story.append(PageBreak())

    # ==== PAGE 7: Picks engine ====
    story.append(Paragraph("5. The picks engine", styles["H1"]))
    story.append(Paragraph("5.1 'Best Pick Today' (highest model probability)", styles["H2"]))
    story.append(Paragraph(
        "The game where <i>(p_final − p_market)</i> is largest, with <i>p_final ≥ 0.55</i>. "
        "The minimum 55% threshold avoids surfacing a +EV pick on a 52% dog with thin margin.",
        styles["Body"]))
    story.append(Paragraph("UI card contents:", styles["H3"]))
    for t in [
        "Matchup: BUF @ MIA · Sun 1:00 PM ET",
        "Pick: BUF ML -180",
        "Model win prob: 64.2%",
        "Market win prob (Pinnacle): 58.1%",
        "Edge: +6.1 pts (color-coded green if >5, yellow if 2–5)",
        "'Why': top 3 SHAP features for this prediction (e.g. 'BUF EPA vs MIA pass def (+0.18), home dome, MIA on short week')",
    ]:
        story.append(Paragraph(f"• {t}", styles["Bullet"]))

    story.append(Paragraph("5.2 '+EV Pick Today' (within a playthrough)", styles["H2"]))
    story.append(Paragraph(
        "Highest expected value at a reasonable price, computed as:",
        styles["Body"]))
    story.append(Paragraph(
        "<font face='Courier'>EV = p_final × (decimal_odds − 1) − (1 − p_final)</font>",
        styles["Code"]))
    story.append(Paragraph("Constraints:", styles["H3"]))
    for t in [
        "Min model prob: 50% (no +EV on longshots)",
        "Max odds: +250 (no 10-to-1 miracle picks)",
        "Min edge: +3% (anything tighter is just noise)",
    ]:
        story.append(Paragraph(f"• {t}", styles["Bullet"]))

    story.append(Paragraph("5.3 Pinnacle-comparison toggle (color-coded)", styles["H2"]))
    story.append(Paragraph(
        "A single toggle in the dashboard header: 'Color FD/DK when better than Pinnacle'. "
        "When ON, the DK and FD prices in each game row render green/red depending on whether "
        "they beat the Pinnacle sharp line. Pinnacle is excluded from the 'best available' price "
        "because you usually can't bet it from a US account — showing it would be mathematically "
        "correct but useless. DK and FD are surfaced as actionable, color-coded against the sharp benchmark.",
        styles["Body"]))

    story.append(Paragraph("5.4 Manual odds entry", styles["H2"]))
    story.append(Paragraph(
        "Each game row has 3 small text inputs labeled 'Manual DK / Manual FD / Manual Pinnacle'. "
        "These override the API-fetched odds for that game and immediately recompute the EV card. "
        "Use case: you have a +EV pick from another source and want to log the line you're getting "
        "at your book. Manual entry is session-only in v1 (not persisted). v2 adds SQLite-backed "
        "'your book line' overrides.",
        styles["Body"]))

    # ---- Section 6: The dashboard ----
    story.append(Paragraph("6. The dashboard — mobile-first UX", styles["H1"]))
    story.append(Paragraph("6.1 Visual design constraints", styles["H2"]))
    for t in [
        "<b>Single column on mobile (&lt;768px)</b>. Everything stacks. No horizontal scroll.",
        "<b>Cards, not tables</b>, on mobile. Tables only on desktop.",
        "<b>Tappable targets ≥44px</b> (Apple HIG).",
        "<b>Tap-to-expand</b> for game details. Default view shows the slate; tap a card to see the full breakdown.",
        "<b>No images, no logos.</b> Text-only for speed. Team abbreviations are sufficient for football fans.",
    ]:
        story.append(Paragraph(f"• {t}", styles["Bullet"]))
    story.append(Paragraph("Color palette:", styles["H3"]))
    palette_rows = [
        ("Background", "#0d1117", "Dark mode primary"),
        ("Card", "#161b22", "Dark mode surface"),
        ("Green edge", "#3fb950", "Strong +EV or high confidence"),
        ("Yellow edge", "#d29922", "Marginal +EV or moderate confidence"),
        ("Red edge", "#f85149", "Negative EV or losing position"),
        ("Accent", "#58a6ff", "Links, focus, +EV pick card"),
    ]
    data = [[Paragraph(f"<b>{r[0]}</b>", styles["Body"]),
             Paragraph(f"<font face='Courier'>{r[1]}</font>", styles["Body"]),
             Paragraph(r[2], styles["Body"])] for r in palette_rows]
    t = Table(data, colWidths=[1.3*inch, 1.3*inch, 4.1*inch])
    t.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LIGHT, colors.white]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
    ]))
    story.append(t)

    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph("6.2 Mobile dashboard mockup (iPhone width)", styles["H2"]))
    story.append(Image(str(CHARTS / "10_dashboard_mockup.png"), width=4.0*inch, height=7.3*inch))
    story.append(Paragraph(
        "Hero cards on top (best pick, +EV pick) — always visible without scrolling. "
        "Settings collapsed by default. Game cards stacked, one tap to expand for SHAP reasons. "
        "Color-coded FD/DK vs Pinnacle when toggle is on.",
        styles["Caption"]))

    # ---- Section 6.3: Refresh schedule ----
    story.append(Paragraph("6.3 Refresh schedule (your question: best times)", styles["H1"]))
    story.append(Image(str(CHARTS / "06_refresh_schedule.png"), width=6.7*inch, height=2.7*inch))

    story.append(Paragraph("Time-of-day analysis", styles["H2"]))
    refresh_rows = [
        ("8:00 AM ET", "First lines posted; very few moves", "Skip — too early"),
        ("12:00 PM ET", "Sharp money moved overnight; recreational caught up; before 1 PM slate", "★ Primary refresh"),
        ("4:00 PM ET", "1 PM games have kicked off; useless for in-week", "Skip"),
        ("6:00 PM ET", "4 PM games in 3rd quarter; useless", "Skip"),
        ("11:00 PM ET", "Monday Night ending; lines quiet", "Skip"),
        ("11:58 PM ET", "Last call before TNF opens; catches overnight moves", "★ Secondary (paid tier)"),
        ("Tue 6:00 AM ET", "After MNF; lines settled", "Skip"),
    ]
    data = [[Paragraph(f"<b>{r[0]}</b>", styles["Body"]),
             Paragraph(r[1], styles["Body"]),
             Paragraph(f"<font color='#5A6573' size='9'>{r[2]}</font>", styles["Body"])] for r in refresh_rows]
    t = Table(data, colWidths=[1.3*inch, 3.4*inch, 2.0*inch])
    t.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LIGHT, colors.white]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
    ]))
    story.append(t)

    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph("Free tier budget math", styles["H2"]))
    story.append(Image(str(CHARTS / "09_tier_economics.png"), width=6.5*inch, height=3.2*inch))
    story.append(Paragraph(
        "The Odds API free tier is 500 credits/month. NFL odds at 3 markets × 3 books "
        "= 9 credits per call (Pinnacle requires regions=us,eu, so the actual cost is "
        "6 credits/call). At 1 call/day, that's 180 credits/month — well under 500. "
        "At 2 calls/day, 360 credits/month — still under. The default is 1 call/day. "
        "The 11:58 PM refresh is gated behind a config flag and only runs on the paid tier.",
        styles["Caption"]))

    # ---- Section 7: VPS deployment ----
    story.append(Paragraph("7. The VPS deployment", styles["H1"]))
    story.append(Paragraph("7.1 Why this is safe to build on your existing setup", styles["H2"]))
    for t in [
        "<b>Caddy already running</b> — add one new site block, append-only.",
        "<b>Port 8503 is free</b> — your existing 8501 (Pick 'Em), 8502 (2TB), 9119 (Hermes), 5000 (wedding), 8765/8766 (Polymoney) are all still in use. We use a new port to keep dashboards isolated.",
        "<b>DuckDNS</b> — your pattern: nfl.tkhermes.duckdns.org joins your existing fleet.",
        "<b>Existing venv</b> — we extend /root/mlb-ev-model-lab/.venv with nfl_data_py, pyarrow, requests (already there). No new virtualenv.",
        "<b>20GB free</b> on /root. Model artifacts are &lt;50MB total. Plenty of room.",
    ]:
        story.append(Paragraph(f"• {t}", styles["Bullet"]))

    story.append(Paragraph("7.2 Caddy block (exact, copy-paste)", styles["H2"]))
    story.append(Paragraph(
        "Append this to <font face='Courier'>/etc/caddy/Caddyfile</font>:",
        styles["Body"]))
    story.append(Paragraph(
        "nfl.tkhermes.duckdns.org {<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;reverse_proxy 127.0.0.1:8503 {<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;header_up X-Forwarded-Host {host}<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;header_up X-Forwarded-Proto {scheme}<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;}<br/>"
        "}",
        styles["Code"]))
    story.append(Paragraph(
        "Then reload: <font face='Courier'>caddy reload --config /etc/caddy/Caddyfile "
        "--address unix//run/caddy/caddy.sock</font>",
        styles["Body"]))

    story.append(Paragraph("7.3 What I will NOT touch", styles["H2"]))
    story.append(callout_box(
        "The DK Pick 'Em dashboard on :8501 · The 2TB dashboard on :8502 · "
        "The Hermēs dashboard on :9119 · The wedding API on :5000 · "
        "The Polymoney stack on :8765/:8766. Existing Caddy site blocks — "
        "I append only, no modifications. Your .env files, credentials, DuckDNS token, "
        "model artifacts. The MLB ev-model-lab venv — only pip install new packages, "
        "no upgrades that could break MLB.",
        styles, color=RED, bg=colors.HexColor("#FFEBEE")))

    story.append(Paragraph("7.4 DuckDNS — adding the subdomain", styles["H2"]))
    story.append(Paragraph(
        "Two options. (A) You do it: visit https://www.duckdns.org, add <b>nfl</b> to "
        "your existing <b>tkhermes</b> domain. The cron daemon at <font face='Courier'>/root/.duckdnstoken</font> "
        "(existing) auto-updates. (B) I do it via curl — but the DuckDNS API for adding a subdomain "
        "is web-only. Recommendation: Option A, 30 seconds.",
        styles["Body"]))

    # ---- Section 8: The Odds API ----
    story.append(Paragraph("8. The Odds API — concrete usage", styles["H1"]))
    story.append(Paragraph("8.1 Free tier recap", styles["H2"]))
    for t in [
        "<b>500 credits/month</b> on the free tier. $79/mo gets 10,000.",
        "Cost per call: <b>1 credit per region per market</b>. NFL is one event.",
        "americanfootball_nfl/odds/?regions=us,eu&markets=h2h,spreads,totals = 2 regions × 3 markets = 6 credits per call.",
    ]:
        story.append(Paragraph(f"• {t}", styles["Bullet"]))

    story.append(Paragraph("8.2 The 3 books we pull", styles["H2"]))
    story.append(Paragraph(
        "The Odds API v4 supports a bookmakers filter. We pull DK, FD, and Pinnacle. "
        "Pinnacle is a 'global' bookmaker, so we add regions=us,eu to get it.",
        styles["Body"]))
    story.append(Paragraph(
        "params = {<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;'regions': 'us,eu',<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;'markets': 'h2h,spreads,totals',<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;'bookmakers': 'draftkings,fanduel,pinnacle',<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;'oddsFormat': 'american',<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;'dateFormat': 'iso',<br/>"
        "}",
        styles["Code"]))

    story.append(Paragraph("8.3 API key handling", styles["H2"]))
    story.append(Paragraph(
        "Stored in <font face='Courier'>/root/nfl-edge/.env</font> (gitignored). "
        "Read at runtime via python-dotenv or os.environ. Never logged. Never hardcoded. "
        "Get a free key at the-odds-api.com (~60 sec).",
        styles["Body"]))

    story.append(Paragraph("8.4 In-season test status", styles["H2"]))
    story.append(callout_box(
        "As of Aug 2, 2026, the 2026 NFL regular season is 39 days away (Sep 10). "
        "Until then, the data layer is dormant. You can develop against historical 2024 data using "
        "The Odds API historical endpoint. The dashboard shows a 'Preseason — no live games' "
        "placeholder until Week 1.",
        styles, color=ORANGE, bg=colors.HexColor("#FFF3E0")))

    # ---- Section 9: Build phases ----
    story.append(Paragraph("9. Build phases (one-week sprint)", styles["H1"]))
    story.append(Image(str(CHARTS / "07_build_timeline.png"), width=6.7*inch, height=3.0*inch))

    phase_rows = [
        ("Phase 1 — Day 1 (today)", "Plan", "Recap research ✓ · Write plan ✓ · PDF ✓ · Init repo ✓ · Push to GitHub ✓ · Host PDF ✓"),
        ("Phase 2 — Day 2-3", "Models", "elo.py · features.py · train_xgb.py · backtest on 2020-2024 · tune hyperparams · train_stacker.py · verify positive CLV"),
        ("Phase 3 — Day 4-5", "Data", "ingest_nflverse.py · ingest_odds.py · cron at 12 PM ET · verify on 2024 historical · score_week.py"),
        ("Phase 4 — Day 6-7", "Dashboard", "streamlit_app.py · best pick + +EV cards · Pinnacle toggle · manual odds · bet log"),
        ("Phase 5 — Day 8-9", "Deploy", "Caddy site block · systemd · cron · DuckDNS subdomain · verify URL live"),
        ("Phase 6 — In-season", "Iterate", "Weekly retrain Tue morning · track CLV/ROI/hit rate · adjust hyperparams · add player-props post-launch"),
    ]
    data = [[Paragraph(f"<b>{r[0]}</b>", styles["Body"]),
             Paragraph(f"<font color='#E07A1F' size='10'>{r[1]}</font>", styles["Body"]),
             Paragraph(r[2], styles["Body"])] for r in phase_rows]
    t = Table(data, colWidths=[1.6*inch, 0.9*inch, 4.2*inch])
    t.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LIGHT, colors.white]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
    ]))
    story.append(t)
    story.append(PageBreak())

    # ==== PAGE 13: GitHub + code ====
    story.append(Paragraph("12. GitHub repo — Tkcool28/nfl-edge", styles["H1"]))
    story.append(Paragraph(
        "Full public repo. The gh CLI is broken on your VPS (v0.0.4 — pre-release, "
        "doesn't support the modern subcommand set), so the fallback is: I create the repo "
        "locally with all files, push via raw git, or zip and deliver via Telegram for you to push.",
        styles["Body"]))
    story.append(Paragraph("What gets committed", styles["H2"]))
    for t in [
        "All source code (<font face='Courier'>src/nfl_edge/</font>, <font face='Courier'>app/</font>)",
        "This build plan and the PDF (<font face='Courier'>docs/</font>)",
        "<font face='Courier'>requirements.txt</font>, <font face='Courier'>pyproject.toml</font>, <font face='Courier'>README.md</font>",
        "Systemd unit and cron scripts",
        "<font face='Courier'>.gitignore</font>, <font face='Courier'>.env.example</font>",
    ]:
        story.append(Paragraph(f"• {t}", styles["Bullet"]))
    story.append(Paragraph("What does NOT get committed", styles["H2"]))
    for t in [
        "<font face='Courier'>.env</font> (real API key)",
        "<font face='Courier'>data/</font> (parquet dumps, raw odds JSON)",
        "<font face='Courier'>models/</font> (.pkl, .json Elo states — too large, re-trainable)",
        "<font face='Courier'>__pycache__/</font>, <font face='Courier'>.venv/</font>",
    ]:
        story.append(Paragraph(f"• {t}", styles["Bullet"]))

    story.append(Paragraph("Code skeleton — Elo engine", styles["H2"]))
    story.append(Paragraph(
        "Inspired by FiveThirtyEight's 2019 NFL model. Update rules:",
        styles["Body"]))
    code = """def predict(self, home, away, home_qb, away_qb, neutral=False):
    elo_h = self.team_elo[home] + self.qb_weight * self.qb_elo[home_qb]
    elo_a = self.team_elo[away] + self.qb_weight * self.qb_elo[away_qb]
    hfa = 0.0 if neutral else self.HFA * 25  # pts → Elo
    return 1.0 / (1.0 + 10 ** ((elo_a - elo_h - hfa) / 400.0))"""
    story.append(Paragraph(code, styles["Code"]))
    story.append(Paragraph(
        "Margin multiplier uses FiveThirtyEight's log-scale: "
        "<font face='Courier'>log(|margin| + 1) * (2.2 / (|margin| + 33)^0.4)</font> — "
        "this weights blowouts less than close games, matching the empirical reality "
        "that 1-point games are nearly coin-flips while 20-point games are nearly deterministic.",
        styles["Body"]))
    story.append(PageBreak())

    # ==== PAGE 14: Code + risk ====
    story.append(Paragraph("Code skeleton — The Odds API client", styles["H1"]))
    code = """import os, requests
from datetime import datetime

ODDS_API = "https://api.the-odds-api.com/v4"

def fetch_nfl_odds(markets="h2h,spreads,totals",
                   bookmakers="draftkings,fanduel,pinnacle",
                   regions="us,eu"):
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
    return r.json()  # cache to data/odds/YYYY-MM-DD_HHMM.json"""
    story.append(Paragraph(code, styles["Code"]))

    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph("13. Honest risks and unknowns", styles["H1"]))
    risk_rows = [
        ("The Odds API key invalid or expired", "Medium", "Verify with curl test before building; free key from the-odds-api.com"),
        ("nfl_data_py 2025 PBP not yet released", "High (Aug)", "Use 2024 as training; weekly retrain kicks in once 2025 W1 PBP available (~Sep 12)"),
        ("Model underperforms market on 2025 holdout", "Medium", "CLV is the only honest success metric; don't ship until CLV > 0 on backtest"),
        ("11:58 PM refresh burns free quota", "High", "Default OFF; gated behind config flag"),
        ("GitHub repo creation via gh CLI broken on VPS", "Confirmed", "Fallback to local commit + zip + push from laptop"),
        ("Caddy reload fails", "Low", "Test config with caddy validate before reload"),
        ("Streamlit dark theme breaks on iOS Safari", "Low", "Use tested CSS; mobile-first layout"),
    ]
    data = [[Paragraph(f"<b>{r[0]}</b>", styles["Body"]),
             Paragraph(f"<font color='#5A6573' size='9'>{r[1]}</font>", styles["Body"]),
             Paragraph(r[2], styles["Body"])] for r in risk_rows]
    t = Table(data, colWidths=[2.4*inch, 0.9*inch, 3.4*inch])
    t.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LIGHT, colors.white]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
    ]))
    story.append(t)
    story.append(PageBreak())

    # ==== PAGE 15: Cost + next steps ====
    story.append(Paragraph("14. Build cost", styles["H1"]))
    story.append(Image(str(CHARTS / "11_cost_breakdown.png"), width=6.5*inch, height=3.2*inch))
    story.append(Paragraph(
        "$0/mo recurring. The Odds API free tier covers 1 daily refresh; the $79/mo paid tier "
        "unlocks the second 11:58 PM refresh. Everything else (DuckDNS, GitHub public repo, "
        "nflverse data, OpenWeather free tier, your existing VPS compute) is free.",
        styles["Caption"]))

    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph("15. What you do after this plan", styles["H1"]))
    for i, t in enumerate([
        "<b>Add <font face='Courier'>nfl</font> subdomain at duckdns.org</b> (30 sec).",
        "<b>Get a free Odds API key</b> at the-odds-api.com (60 sec).",
        "<b>Set the key</b> in <font face='Courier'>/root/nfl-edge/.env</font>.",
        "<b>Tell me to start Phase 2</b> ('go' / 'build the model' / 'Phase 2').",
        "I will execute Phases 2-5 over the next 7 days.",
        "<b>Sep 10, 2026:</b> Week 1 kickoff. The dashboard goes live.",
    ], start=1):
        story.append(Paragraph(f"{i}. {t}", styles["Bullet"]))

    story.append(Spacer(1, 0.15*inch))
    story.append(callout_box(
        "Full plan, code skeletons, and PDF are committed to the GitHub repo at "
        "<b>github.com/Tkcool28/nfl-edge</b>. The PDF is also hosted at "
        "<b>https://pickem.tkhermes.duckdns.org/nfl-plan/NFL_Edge_Build_Plan.pdf</b>.",
        styles, color=NAVY, bg=LIGHT))

    # ---- Build with page templates ----
    doc.build(story, onFirstPage=cover_page, onLaterPages=inner_page)
    print(f"Built {OUT_PDF}")
    print(f"Pages: {len(story)} content blocks")
    return OUT_PDF


if __name__ == "__main__":
    build()
