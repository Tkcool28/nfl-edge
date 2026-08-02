"""Streamlit dashboard for NFL Edge.

Mobile-first, dark theme, single column. Reads cached data from data/.

Run: streamlit run app/streamlit_app.py --server.port 8503
"""
import os
from pathlib import Path
import streamlit as st
import pandas as pd

st.set_page_config(page_title="NFL Edge", page_icon="🏈", layout="centered")

st.markdown("""
<style>
  .stApp { background: #0d1117; color: #c9d1d9; }
  .card { background: #161b22; border-radius: 8px; padding: 16px; margin: 8px 0; }
  .edge-green { color: #3fb950; font-weight: 600; }
  .edge-yellow { color: #d29922; }
  .edge-red { color: #f85149; }
  h1, h2, h3 { color: #c9d1d9; }
  .stToggle { color: #c9d1d9; }
</style>
""", unsafe_allow_html=True)

st.title("🏈 NFL Edge")
st.caption("Last refresh: 12:00 PM ET (2h ago) · Refresh schedule: 12 PM / 11:58 PM ET")

# Load cached picks (written by score_week.py)
picks_path = Path("data/processed/picks_current.parquet")
if picks_path.exists():
    picks = pd.read_parquet(picks_path)
else:
    st.warning("Preseason — no live games yet. Data layer goes live Sep 10, 2026 (NFL Week 1).")
    st.stop()

# Best Pick + +EV Pick hero cards
if "model_prob" in picks.columns and len(picks) > 0:
    col1, col2 = st.columns(2)
    with col1:
        best = picks.loc[picks["model_prob"].idxmax()]
        st.markdown(f"""
        <div class="card" style="border: 1.5px solid #3fb950;">
          <h3 style="color: #3fb950;">⭐ Best Pick</h3>
          <h2>{best['matchup']}</h2>
          <p><b>{best.get('pick', '—')}</b> at {best.get('odds', '—')}</p>
          <p>Model <b>{best['model_prob']:.0%}</b> · Market {best.get('market_prob', 0):.0%}</p>
          <p class="edge-green">+{best.get('edge_pts', 0):.1f} pts edge</p>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        if "ev_pct" in picks.columns and picks["ev_pct"].max() > 0:
            ev = picks.loc[picks["ev_pct"].idxmax()]
            st.markdown(f"""
            <div class="card" style="border: 1.5px solid #58a6ff;">
              <h3 style="color: #58a6ff;">💰 +EV Pick</h3>
              <h2>{ev['matchup']}</h2>
              <p><b>{ev.get('pick', '—')}</b> at {ev.get('odds', '—')}</p>
              <p>Model <b>{ev['model_prob']:.0%}</b> · EV <b class="edge-green">+{ev['ev_pct']:.1f}%</b></p>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class="card">
              <h3 style="color: #8b949e;">💰 +EV Pick</h3>
              <p>No +EV games this week.</p>
            </div>
            """, unsafe_allow_html=True)

# Settings
with st.expander("⚙️ Settings"):
    color_pinnacle = st.toggle("Color FD/DK when better than Pinnacle", value=True)
    show_shap = st.toggle("Show SHAP reasons", value=False)
    only_ev = st.toggle("Only show +EV games", value=False)
    st.caption("Refresh: 12:00 PM ET daily (free tier). Add 11:58 PM with paid tier.")

# Game cards
st.subheader(f"All games this week ({len(picks)})")
for _, g in picks.iterrows():
    with st.container():
        st.markdown(f"""
        <div class="card">
          <h3>{g['matchup']} · {g.get('kickoff', '')}</h3>
          <p>Pick: <b>{g.get('pick', '—')}</b> at {g.get('odds', '—')}</p>
          <p>Model {g['model_prob']:.0%} · Market {g.get('market_prob', 0):.0%}</p>
        </div>
        """, unsafe_allow_html=True)
        if color_pinnacle and "odds_dk" in g.index:
            cols = st.columns(3)
            for i, book in enumerate(["dk", "fd", "pinnacle"]):
                with cols[i]:
                    o = g.get(f"odds_{book}")
                    if pd.notna(o):
                        st.markdown(f"<p><b>{book.upper()}</b>: {int(o):+d}</p>",
                                    unsafe_allow_html=True)
        with st.expander("Manual odds"):
            c1, c2, c3 = st.columns(3)
            dk = c1.text_input("DK", value="", key=f"dk_{g.get('game_id', _)}")
            fd = c2.text_input("FD", value="", key=f"fd_{g.get('game_id', _)}")
            pin = c3.text_input("Pin", value="", key=f"pin_{g.get('game_id', _)}")
            if dk or fd or pin:
                st.caption("Manual odds override (session-only)")
