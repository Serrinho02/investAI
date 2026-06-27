"""
InvestAI — Assistente Finanziario Personale v2.1
Single-User | Storage Locale JSON | No Database

⚠️ DISCLAIMER: InvestAI è uno strumento informativo e non costituisce consulenza
finanziaria. Le analisi si basano su indicatori tecnici storici. I rendimenti
passati non garantiscono risultati futuri. Investi sempre consapevolmente.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from core.assets import POPULAR_ASSETS, AUTO_SCAN_TICKERS, get_asset_name, classify_asset
from core.market_data import get_data_raw, validate_ticker, clear_cache
from core.portfolio import get_portfolio_summary, get_historical_portfolio_value, compute_first_buy_dates
from core.storage import (
    load_transactions, add_transaction, update_transaction, delete_transaction,
    load_watchlist, save_watchlist, add_to_watchlist, remove_from_watchlist,
    load_settings, set_setting, get_setting,
)
from core.excel_report import generate_excel_report
from core.auth import is_authenticated, render_login_page, logout
from engine.indicators import compute_indicators
from engine.scoring import analyze, portfolio_advice, AnalysisResult

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configurazione pagina
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="InvestAI", layout="wide", page_icon="💎",
                   initial_sidebar_state="expanded")


# ─────────────────────────────────────────────────────────────────────────────
# Telegram (singleton opzionale)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_resource
def _start_telegram():
    try:
        token = ""
        try:
            token = st.secrets.get("telegram", {}).get("token", "")
        except Exception:
            pass
        if not token:
            token = os.environ.get("TELEGRAM_TOKEN", "")
        if token:
            os.environ["TELEGRAM_TOKEN"] = token
        from telegram.bot import start_bot_threads
        start_bot_threads()
    except Exception as e:
        logger.info(f"Bot Telegram non avviato: {e}")

_start_telegram()

# ─────────────────────────────────────────────────────────────────────────────
# CSS moderno
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Layout ── */
#MainMenu, .stDeployButton, footer { display: none !important; }
header { background: transparent !important; }
[data-testid="stSidebar"] { background: #0f1117 !important; }
[data-testid="stSidebar"] * { color: #e0e0e0 !important; }
[data-testid="stSidebar"] hr { border-color: #2a2a3a !important; }

/* ── Card opportunità ── */
.opp-card {
    background: white;
    border-radius: 14px;
    padding: 18px;
    margin-bottom: 16px;
    border: 1px solid #e8e8f0;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    transition: box-shadow .2s;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.opp-card:hover { box-shadow: 0 6px 20px rgba(0,0,0,0.10); }
.opp-card.gold  { border: 2px solid #f59e0b; background: #fffbeb; }
.opp-card.buy   { border-left: 4px solid #22c55e; }
.opp-card.sell  { border-left: 4px solid #ef4444; }
.opp-card.hold  { border-left: 4px solid #6366f1; }
.opp-card.avoid { border-left: 4px solid #9ca3af; }

/* ── Badge score ── */
.badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: .3px;
}
.badge-green  { background:#dcfce7; color:#16a34a; }
.badge-yellow { background:#fef9c3; color:#b45309; }
.badge-red    { background:#fee2e2; color:#dc2626; }
.badge-gray   { background:#f3f4f6; color:#6b7280; }
.badge-gold   { background:#fef3c7; color:#d97706; border:1px solid #f59e0b; }
.badge-blue   { background:#eff6ff; color:#2563eb; }

/* ── Tag tipo asset ── */
.asset-tag {
    font-size: 0.68rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .5px;
    padding: 2px 7px;
    border-radius: 10px;
    background: #f3f4f6;
    color: #6b7280;
    margin-left: 6px;
}

/* ── Mini stat row ── */
.stat-row {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    margin: 8px 0 4px;
}
.stat-item {
    font-size: 0.78rem;
    color: #6b7280;
}
.stat-item b { color: #1f2937; }

/* ── Reason pills ── */
.pill-green {
    display: inline-block;
    font-size: 0.73rem;
    background: #f0fdf4;
    color: #15803d;
    border: 1px solid #bbf7d0;
    border-radius: 20px;
    padding: 2px 9px;
    margin: 2px 2px;
}
.pill-red {
    display: inline-block;
    font-size: 0.73rem;
    background: #fef2f2;
    color: #b91c1c;
    border: 1px solid #fecaca;
    border-radius: 20px;
    padding: 2px 9px;
    margin: 2px 2px;
}

/* ── Divider sottile ── */
.thin-div { border: none; border-top: 1px solid #f1f1f5; margin: 10px 0; }

/* ── Disclaimer ── */
.disclaimer {
    background: #fffbeb;
    border-left: 3px solid #f59e0b;
    padding: 8px 14px;
    border-radius: 6px;
    font-size: 0.8rem;
    color: #78350f;
    margin-bottom: 14px;
}

/* ── Metriche portafoglio ── */
[data-testid="metric-container"] {
    background: white;
    border: 1px solid #e8e8f0;
    border-radius: 12px;
    padding: 12px 16px !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}

/* ── Bottoni primari ── */
.stButton button[kind="primary"] {
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    border: none;
    border-radius: 8px;
    font-weight: 600;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Cache
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def _get_market_data(tickers: tuple[str, ...]) -> dict:
    return get_data_raw(list(tickers))

def get_market_data(tickers: list[str]) -> dict:
    return _get_market_data(tuple(sorted(set(tickers))))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers UI
# ─────────────────────────────────────────────────────────────────────────────

def _disclaimer():
    st.markdown(
        '<div class="disclaimer">⚠️ <b>Disclaimer:</b> InvestAI è uno strumento informativo '
        'e <b>non costituisce consulenza finanziaria</b>. I rendimenti passati non garantiscono '
        'risultati futuri.</div>',
        unsafe_allow_html=True,
    )


def _score_badge_html(score: int) -> str:
    if score >= 65:
        cls = "badge-green"
    elif score >= 40:
        cls = "badge-yellow"
    else:
        cls = "badge-red"
    return f'<span class="badge {cls}">Score {score}/100</span>'


def _signal_badge_html(signal: str, label: str) -> str:
    mapping = {
        "BUY_STRONG": ("badge-gold",   "💎 " + label),
        "BUY":        ("badge-green",  "🛒 " + label),
        "SELL_PARTIAL":("badge-red",   "💰 " + label),
        "HOLD":       ("badge-blue",   "🚀 " + label),
        "AVOID":      ("badge-gray",   "⛔ " + label),
    }
    cls, text = mapping.get(signal, ("badge-gray", label))
    return f'<span class="badge {cls}" style="font-size:0.85rem;padding:5px 12px;">{text}</span>'


def _type_tag(asset_type: str) -> str:
    colors = {
        "Crypto": "#fdf4ff:#9333ea",
        "ETF":    "#eff6ff:#2563eb",
        "Bond":   "#f0fdf4:#16a34a",
        "REIT":   "#fff7ed:#ea580c",
        "Azione": "#f9fafb:#4b5563",
        "?":      "#f9fafb:#9ca3af",
    }
    bg, fg = colors.get(asset_type, "#f9fafb:#6b7280").split(":")
    return (f'<span style="font-size:0.65rem;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:.5px;padding:2px 7px;border-radius:10px;'
            f'background:{bg};color:{fg};margin-left:6px;">{asset_type}</span>')


def _card_css_class(signal: str) -> str:
    return {"BUY_STRONG": "gold", "BUY": "buy", "SELL_PARTIAL": "sell",
            "AVOID": "avoid"}.get(signal, "hold")


def render_opportunity_card(res: AnalysisResult) -> None:
    """Card opportunità: moderna, senza HTML grezzo nel backtest."""
    css = _card_css_class(res.signal)
    name = get_asset_name(res.ticker)
    atype = classify_asset(res.ticker)

    # Pills fattori positivi (max 4)
    pos_pills = "".join(
        f'<span class="pill-green">✓ {r[:55]}</span>'
        for r in res.reasons[:4]
    )
    # Pills fattori negativi (max 2)
    neg_pills = "".join(
        f'<span class="pill-red">⚠ {w[:55]}</span>'
        for w in res.warnings[:2]
    )

    # Backtest row — costruiamo HTML inline, nessun tag annidato problematico
    bt_html = ""
    if res.backtest_win30 or res.backtest_win90:
        def _bt(win, pnl):
            col = "#16a34a" if pnl >= 0 else "#dc2626"
            sign = "+" if pnl >= 0 else ""
            return f'<b>{win:.0f}%</b> win <span style="color:{col};">({sign}{pnl:.1f}%)</span>'

        bt_html = (
            f'<div style="font-size:0.75rem;color:#6b7280;margin-top:8px;padding-top:8px;'
            f'border-top:1px solid #f1f1f5;">'
            f'📊 <b>Backtest:</b>&nbsp;&nbsp;'
            f'30g: {_bt(res.backtest_win30, res.backtest_pnl30)}'
            f'&nbsp;&nbsp;|&nbsp;&nbsp;'
            f'60g: {_bt(res.backtest_win60, res.backtest_pnl60)}'
            f'&nbsp;&nbsp;|&nbsp;&nbsp;'
            f'90g: {_bt(res.backtest_win90, res.backtest_pnl90)}'
            f'</div>'
        )

    upside_col = "#16a34a" if res.upside_pct > 0 else "#dc2626"
    down_col   = "#dc2626"

    html = f"""
<div class="opp-card {css}">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
    <div>
      <span style="font-size:1.05rem;font-weight:700;color:#111;">{res.ticker}</span>
      {_type_tag(atype)}
      <div style="font-size:0.75rem;color:#9ca3af;margin-top:2px;">{name}</div>
    </div>
    <div style="text-align:right;flex-shrink:0;">
      {_score_badge_html(res.confidence_score)}
      <div style="font-size:0.72rem;color:#9ca3af;margin-top:3px;">RSI {res.rsi:.0f} · ADX {res.adx:.0f}</div>
    </div>
  </div>

  <div style="margin:10px 0 6px;">
    {_signal_badge_html(res.signal, res.action_label)}
  </div>

  <div style="font-size:0.78rem;line-height:1.4;margin-bottom:6px;">
    {pos_pills}{neg_pills}
  </div>

  <hr class="thin-div">

  <div class="stat-row">
    <div class="stat-item">Prezzo <b>${res.last_price:,.2f}</b></div>
    <div class="stat-item">🎯 Target <b style="color:{upside_col};">${res.target:,.2f} ({res.upside_pct:+.1f}%)</b></div>
    <div class="stat-item">🛑 Supporto <b style="color:{down_col};">${res.support:,.2f} ({res.downside_pct:.1f}%)</b></div>
  </div>

  {bt_html}
</div>
"""
    st.markdown(html, unsafe_allow_html=True)


def render_portfolio_card(sym: str, dat: dict, res: AnalysisResult,
                          adv, tot_val: float) -> None:
    """Card posizione in portafoglio."""
    pnl_pct   = dat["pnl_pct"]
    pnl_col   = "#16a34a" if pnl_pct >= 0 else "#dc2626"
    pnl_sign  = "+" if pnl_pct >= 0 else ""
    alloc     = (dat["val"] / tot_val * 100) if tot_val > 0 else 0
    trend_ico = "🟢" if res.is_bullish else "🔴"
    days      = dat.get("days_held", 0)
    name      = get_asset_name(sym)
    atype     = classify_asset(sym)

    # Stima tempo al target
    gg_label = "N/A"
    if res.atr > 0 and res.last_price > 0:
        gg = int(abs(res.target - res.last_price) / (res.atr * 0.5))
        gg_label = ("Questa settimana" if gg < 5
                    else "Lungo termine" if gg > 100
                    else f"~{gg} gg")

    dist_trailing = ((adv.trailing_stop - res.last_price) / res.last_price * 100) if res.last_price > 0 else 0
    dist_target   = ((res.target - res.last_price) / res.last_price * 100) if res.last_price > 0 else 0
    dist_support  = ((res.support - res.last_price) / res.last_price * 100) if res.last_price > 0 else 0

    # Colore sfondo card basato sull'advice
    bg_map = {
        "🔪": "#fef2f2", "🚨": "#fef2f2", "🛡️": "#fffbeb",
        "💰": "#fff7ed", "🚀": "#f0fdf4", "💎": "#f0fdf4",
        "🛒": "#f0fdf4", "🧊": "#eff6ff", "⚠️": "#fffbeb",
    }
    card_bg = next((v for k, v in bg_map.items() if adv.title.startswith(k)), "#ffffff")

    html = f"""
<div class="opp-card" style="background:{card_bg};">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
    <div>
      <span style="font-size:1.05rem;font-weight:700;color:#111;">{sym}</span>
      {_type_tag(atype)}
      <div style="font-size:0.73rem;color:#9ca3af;">{name}</div>
    </div>
    <div style="text-align:right;flex-shrink:0;">
      <span style="font-size:1.15rem;font-weight:700;color:{pnl_col};">{pnl_sign}{pnl_pct:.1f}%</span>
      <div style="font-size:0.7rem;background:#1f2937;color:white;padding:2px 7px;border-radius:10px;margin-top:3px;">📅 {days}g</div>
    </div>
  </div>

  <div style="margin:10px 0 4px;">
    <span style="font-size:0.95rem;font-weight:600;color:#1f2937;">{adv.title}</span>
    &nbsp;{_score_badge_html(res.confidence_score)}
  </div>
  <p style="font-size:0.82rem;color:#374151;margin:0 0 8px;line-height:1.4;">{adv.advice}</p>

  <hr class="thin-div">

  <div class="stat-row">
    <div class="stat-item">Prezzo <b>${res.last_price:.2f}</b></div>
    <div class="stat-item">Media <b>${dat['avg_price']:.2f}</b></div>
    <div class="stat-item">Alloc. <b>{alloc:.1f}%</b></div>
    <div class="stat-item">Trend {trend_ico}</div>
    <div class="stat-item">RSI <b>{res.rsi:.0f}</b></div>
    <div class="stat-item">Risk <b>{adv.risk_score}/10</b></div>
  </div>

  <hr class="thin-div">

  <div style="font-size:0.78rem;color:#374151;">
    <div style="margin-bottom:4px;">
      🛡️ <b>Trailing Stop</b> ${adv.trailing_stop:.2f}
      <span style="color:#dc2626;">({dist_trailing:.1f}%)</span>
    </div>
    <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:4px;">
      <span>🎯 Target <b style="color:#16a34a;">${res.target:.2f} ({dist_target:+.1f}%)</b>
        <span style="font-size:0.7rem;background:#dcfce7;color:#15803d;padding:1px 6px;border-radius:8px;">⏳ {gg_label}</span>
      </span>
      <span>🛑 Supporto <b style="color:#dc2626;">${res.support:.2f} ({dist_support:.1f}%)</b></span>
    </div>
  </div>
</div>
"""
    st.markdown(html, unsafe_allow_html=True)


def _create_price_chart(df: pd.DataFrame, ticker: str, trend_label: str) -> go.Figure:
    df_plot = df.tail(int(365 * 1.5)).copy()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.04, row_heights=[0.72, 0.28])

    fig.add_trace(go.Candlestick(
        x=df_plot.index,
        open=df_plot["Open"], high=df_plot["High"],
        low=df_plot["Low"],   close=df_plot["Close"],
        name="Prezzo",
        increasing_line_color="#22c55e",
        decreasing_line_color="#ef4444",
    ), row=1, col=1)

    for col, name, color, dash in [
        ("SMA_200", "SMA 200", "#f59e0b", "solid"),
        ("SMA_50",  "SMA 50",  "#8b5cf6", "dot"),
        ("EMA_21",  "EMA 21",  "#06b6d4", "dash"),
    ]:
        if col in df_plot.columns:
            fig.add_trace(go.Scatter(
                x=df_plot.index, y=df_plot[col], name=name,
                line=dict(color=color, width=1.5, dash=dash), opacity=0.85,
            ), row=1, col=1)

    if "BBU" in df_plot.columns and "BBL" in df_plot.columns:
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["BBU"],
                                 name="BB Sup", line=dict(color="rgba(99,102,241,0.35)", width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["BBL"],
                                 name="BB Inf", fill="tonexty",
                                 fillcolor="rgba(99,102,241,0.05)",
                                 line=dict(color="rgba(99,102,241,0.35)", width=1)), row=1, col=1)

    colors_vol = ["#ef4444" if c < o else "#22c55e"
                  for o, c in zip(df_plot["Open"], df_plot["Close"])]
    fig.add_trace(go.Bar(x=df_plot.index, y=df_plot["Volume"],
                         name="Volume", marker_color=colors_vol, opacity=0.45), row=2, col=1)

    fig.update_layout(
        title=dict(text=f"<b>{ticker}</b>  ·  {trend_label}", font=dict(size=16, color="#1f2937")),
        template="plotly_white",
        height=540,
        margin=dict(l=10, r=10, t=50, b=10),
        showlegend=True,
        legend=dict(x=0, y=1.02, orientation="h", font=dict(size=11)),
        xaxis_rangeslider_visible=False,
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    fig.update_xaxes(showgrid=True, gridcolor="#f3f4f6")
    fig.update_yaxes(showgrid=True, gridcolor="#f3f4f6")
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Pagina: Analisi Mercato
# ─────────────────────────────────────────────────────────────────────────────
def page_market():
    st.title("📊 Analisi Mercato")
    _disclaimer()

    wl = load_watchlist()
    if not wl:
        wl = dict(POPULAR_ASSETS)
        save_watchlist(wl)

    wl_tickers = list(wl.values())
    wl_options = sorted(list(wl.keys()))

    # ── Scansione automatica ──────────────────────────────────────────────
    with st.expander("🤖 Scansione Automatica Watchlist", expanded=True):
        n_assets = len(wl_tickers)
        st.caption(f"Watchlist attiva: **{n_assets} asset** — cerca automaticamente segnali BUY e SELL")

        col_btn, col_filter = st.columns([2, 3])
        with col_btn:
            scan_btn = st.button("🔎 Scansiona ora", type="primary", use_container_width=True)
        with col_filter:
            only_strong = st.toggle("Solo segnali forti (Score ≥ 55)", value=False)

        if scan_btn:
            prog = st.progress(0, text="Download dati in corso…")
            with st.spinner(""):
                mdata = get_market_data(wl_tickers)
            prog.progress(40, text="Calcolo indicatori…")

            opportunities: list[AnalysisResult] = []
            for i, t in enumerate(wl_tickers):
                if t not in mdata:
                    continue
                df_ind = compute_indicators(mdata[t])
                if df_ind is None:
                    continue
                res = analyze(df_ind, t, classify_asset(t))
                if res.signal in ("BUY_STRONG", "BUY", "SELL_PARTIAL"):
                    if only_strong and res.confidence_score < 55:
                        continue
                    opportunities.append(res)
                prog.progress(40 + int(55 * (i + 1) / max(len(wl_tickers), 1)))

            prog.progress(100, text="Analisi completata!")
            time.sleep(0.3)
            prog.empty()

            if opportunities:
                prio = {"BUY_STRONG": 3, "BUY": 2, "SELL_PARTIAL": 1}
                opportunities.sort(
                    key=lambda r: (prio.get(r.signal, 0), r.confidence_score),
                    reverse=True,
                )
                if any(r.signal == "BUY_STRONG" for r in opportunities):
                    st.balloons()
                    st.success("💎 TROVATA UN'OPPORTUNITÀ D'ORO!")

                # Riepilogo contatori
                n_gold = sum(1 for r in opportunities if r.signal == "BUY_STRONG")
                n_buy  = sum(1 for r in opportunities if r.signal == "BUY")
                n_sell = sum(1 for r in opportunities if r.signal == "SELL_PARTIAL")
                ca, cb, cc, cd = st.columns(4)
                ca.metric("💎 Golden",   n_gold)
                cb.metric("🛒 Acquisto", n_buy)
                cc.metric("💰 Sell",     n_sell)
                cd.metric("📊 Analizzati", len([t for t in wl_tickers if t in mdata]))

                st.divider()
                cols = st.columns(3)
                for i, res in enumerate(opportunities):
                    with cols[i % 3]:
                        render_opportunity_card(res)
            else:
                st.info("Nessun segnale forte rilevato nella watchlist in questo momento.")

    st.divider()

    # ── Analisi singolo asset ─────────────────────────────────────────────
    st.subheader("🔎 Analisi Singolo Asset")
    all_opts = ["➕ Ticker manuale…"] + wl_options
    c_sel, c_inp = st.columns([3, 1])
    with c_sel:
        selection = st.selectbox("Seleziona dalla watchlist", all_opts, label_visibility="collapsed")
    selected_ticker: str | None = None
    if selection == "➕ Ticker manuale…":
        with c_inp:
            manual = st.text_input("Ticker", placeholder="AAPL", label_visibility="collapsed").upper().strip()
        if manual:
            selected_ticker = manual
    else:
        selected_ticker = wl.get(selection)

    if selected_ticker:
        with st.spinner(f"Scarico dati {selected_ticker}…"):
            mdata = get_market_data([selected_ticker])

        if selected_ticker not in mdata:
            st.error(f"Ticker '{selected_ticker}' non trovato o dati insufficienti.")
        else:
            df_ind = compute_indicators(mdata[selected_ticker])
            if df_ind is None:
                st.warning(f"Dati insufficienti per {selected_ticker} (servono ≥ 220 sessioni).")
            else:
                res = analyze(df_ind, selected_ticker, classify_asset(selected_ticker))

                # Metriche principali
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Prezzo", f"${res.last_price:,.2f}")
                k2.metric("🎯 Target", f"${res.target:,.2f}", delta=f"{res.upside_pct:+.1f}%")
                k3.metric("🛑 Supporto", f"${res.support:,.2f}", delta=f"{res.downside_pct:.1f}%")
                k4.metric("🏆 Score", f"{res.confidence_score}/100")

                # Score dettagliati
                s1, s2, s3, s4, s5 = st.columns(5)
                s1.metric("Trend", f"{res.trend_score}/100")
                s2.metric("Momentum", f"{res.momentum_score}/100")
                s3.metric("Value", f"{res.value_score}/100")
                s4.metric("Volume", f"{res.volume_score}/100")
                s5.metric("Risk", f"{res.risk_score}/100", delta_color="inverse")

                st.plotly_chart(_create_price_chart(df_ind, selected_ticker, res.trend_label),
                                use_container_width=True)

                c_card, c_bt = st.columns([1, 1])
                with c_card:
                    render_opportunity_card(res)
                with c_bt:
                    st.markdown("**📊 Backtest storico segnale**")
                    b1, b2, b3 = st.columns(3)
                    b1.metric("30g Win", f"{res.backtest_win30:.0f}%")
                    b1.metric("30g PnL", f"{res.backtest_pnl30:+.1f}%", delta_color="off")
                    b2.metric("60g Win", f"{res.backtest_win60:.0f}%")
                    b2.metric("60g PnL", f"{res.backtest_pnl60:+.1f}%", delta_color="off")
                    b3.metric("90g Win", f"{res.backtest_win90:.0f}%")
                    b3.metric("90g PnL", f"{res.backtest_pnl90:+.1f}%", delta_color="off")

                    with st.expander("🔬 Ragionamento completo"):
                        if res.reasons:
                            st.markdown("**✅ Fattori positivi**")
                            for r in res.reasons:
                                st.markdown(f"- {r}")
                        if res.warnings:
                            st.markdown("**⚠️ Fattori di attenzione**")
                            for w in res.warnings:
                                st.markdown(f"- {w}")


# ─────────────────────────────────────────────────────────────────────────────
# Pagina: Portafoglio
# ─────────────────────────────────────────────────────────────────────────────
def page_portfolio():
    c_title, c_refresh = st.columns([4, 1])
    with c_title:
        st.title("💼 Portafoglio")
    with c_refresh:
        if st.button("🔄 Aggiorna", use_container_width=True):
            st.cache_data.clear(); clear_cache(); time.sleep(0.3); st.rerun()

    _disclaimer()

    pf, _ = get_portfolio_summary()
    raw_tx = load_transactions()

    if not pf:
        st.info("Portafoglio vuoto. Aggiungi transazioni qui sotto.")
        _render_transaction_tab(raw_tx)
        return

    tickers_owned = list(pf.keys())
    tickers_hist  = list({t["symbol"] for t in raw_tx} if raw_tx else set())
    all_tickers   = list(set(tickers_owned + tickers_hist))

    with st.spinner("Download prezzi…"):
        mdata = get_market_data(all_tickers)

    first_buy = compute_first_buy_dates(raw_tx)
    pf_enriched: dict = {}
    tot_val = tot_cost = 0.0
    pie_data: list[dict] = []

    for sym in tickers_owned:
        pos = pf[sym]
        cur = float(mdata[sym]["Close"].iloc[-1]) if sym in mdata and not mdata[sym].empty else pos["avg_price"]
        val  = pos["qty"] * cur
        cost = pos["total_cost"]
        pnl_abs = val - cost
        pnl_pct = (pnl_abs / cost * 100) if cost > 0 else 0.0
        days = (date.today() - first_buy[sym]).days if sym in first_buy else 0
        pf_enriched[sym] = {**pos, "cur_price": cur, "val": val,
                             "pnl_abs": pnl_abs, "pnl_pct": pnl_pct, "days_held": days}
        tot_val  += val
        tot_cost += cost
        if val > 0:
            pie_data.append({"Label": sym, "Value": val})

    pnl_tot     = tot_val - tot_cost
    pnl_tot_pct = (pnl_tot / tot_cost * 100) if tot_cost > 0 else 0.0

    # Metriche
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("💼 Valore Attuale", f"€{tot_val:,.2f}")
    m2.metric("📈 Utile Netto", f"€{pnl_tot:,.2f}", delta=f"{pnl_tot_pct:.2f}%")
    m3.metric("💰 Investito", f"€{tot_cost:,.2f}")
    m4.metric("📊 Asset", len(pf_enriched))

    st.divider()
    st.subheader("💡 Strategia Operativa")

    valid_pf = [(s, d) for s, d in sorted(pf_enriched.items(), key=lambda x: x[1]["pnl_pct"])
                if s in mdata]
    cols = st.columns(3)
    for i, (sym, dat) in enumerate(valid_pf):
        df_ind = compute_indicators(mdata[sym])
        if df_ind is None:
            continue
        adv = portfolio_advice(df_ind, dat["avg_price"], dat["cur_price"])
        res = analyze(df_ind, sym, classify_asset(sym))
        with cols[i % 3]:
            render_portfolio_card(sym, dat, res, adv, tot_val)

    st.divider()
    tab_chart, tab_alloc, tab_tx = st.tabs(["📈 Grafici", "🍰 Allocazione", "📝 Transazioni"])

    with tab_chart:
        if raw_tx:
            with st.spinner("Elaborazione storico…"):
                df_hist = get_historical_portfolio_value(raw_tx, mdata)
            if not df_hist.empty:
                excel_bytes = generate_excel_report(df_hist, pf_enriched, raw_tx)
                st.download_button("📥 Scarica Report Excel", data=excel_bytes,
                                   file_name=f"InvestAI_{date.today()}.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

                g1, g2, g3 = st.tabs(["Capitale", "Utili", "Composizione"])
                with g1:
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist["Total Value"],
                                             name="Valore", line=dict(color="#6366f1", width=2.5), fill="tozeroy",
                                             fillcolor="rgba(99,102,241,0.08)"))
                    fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist["Total Invested"],
                                             name="Investito", line=dict(color="#ef4444", width=1.5, dash="dash")))
                    fig.update_layout(height=380, hovermode="x unified", template="plotly_white",
                                      title="Valore vs Capitale Investito")
                    st.plotly_chart(fig, use_container_width=True)
                with g2:
                    df_hist["Net"] = df_hist["Total Value"] - df_hist["Total Invested"]
                    colors = ["#22c55e" if v >= 0 else "#ef4444" for v in df_hist["Net"]]
                    fig = go.Figure(go.Bar(x=df_hist.index, y=df_hist["Net"], marker_color=colors))
                    fig.update_layout(height=380, template="plotly_white", title="Utile Netto (€)")
                    st.plotly_chart(fig, use_container_width=True)
                with g3:
                    fig = go.Figure()
                    asset_cols = [c for c in df_hist.columns if c not in ["Total Value","Total Invested","Net"]]
                    for c in asset_cols:
                        fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist[c],
                                                 mode="lines", stackgroup="one", name=c))
                    fig.update_layout(height=380, template="plotly_white", title="Composizione nel Tempo")
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("Dati storici non sufficienti.")
        else:
            st.info("Nessuna transazione.")

    with tab_alloc:
        if pf_enriched:
            c_pie, c_tbl = st.columns([1, 1.5])
            with c_pie:
                if pie_data:
                    fig = go.Figure(go.Pie(labels=[d["Label"] for d in pie_data],
                                           values=[d["Value"] for d in pie_data], hole=0.45))
                    fig.update_layout(margin=dict(t=0,b=0,l=0,r=0), height=280, showlegend=False)
                    st.plotly_chart(fig, use_container_width=True)
            with c_tbl:
                rows = [{"Asset": s, "Valore €": d["val"], "Costo €": d["total_cost"],
                          "P&L %": d["pnl_pct"]/100, "Data 1°": first_buy.get(s)}
                        for s, d in pf_enriched.items()]
                df_a = pd.DataFrame(rows).sort_values("Valore €", ascending=False)
                st.dataframe(df_a, hide_index=True, use_container_width=True,
                    column_config={
                        "Valore €": st.column_config.NumberColumn(format="€%.2f"),
                        "Costo €":  st.column_config.NumberColumn(format="€%.2f"),
                        "P&L %":    st.column_config.NumberColumn(format="%.2f%%"),
                        "Data 1°":  st.column_config.DateColumn(format="DD/MM/YYYY"),
                    })
        else:
            st.info("Portafoglio vuoto.")

    with tab_tx:
        _render_transaction_tab(raw_tx)


def _render_transaction_tab(raw_tx: list[dict]) -> None:
    st.subheader("Gestione Transazioni")

    with st.expander("➕ Nuova Transazione", expanded=not raw_tx):
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        n_sym  = c1.text_input("Ticker", placeholder="AAPL", key="tx_sym").upper().strip()
        n_qty  = c2.number_input("Quantità", min_value=0.0001, format="%.4f", key="tx_qty")
        n_prc  = c3.number_input("Prezzo", min_value=0.0001, key="tx_prc")
        n_date = c4.date_input("Data", date.today(), key="tx_date")
        n_type = c5.selectbox("Tipo", ["BUY", "SELL"], key="tx_type")
        n_fee  = c6.number_input("Commissione", min_value=0.0, value=0.0, key="tx_fee")
        if st.button("➕ Aggiungi", type="primary", use_container_width=True):
            if not n_sym:
                st.error("Inserisci il ticker.")
            elif n_qty <= 0 or n_prc <= 0:
                st.error("Quantità e prezzo devono essere > 0.")
            else:
                add_transaction({"symbol": n_sym, "quantity": n_qty, "price": n_prc,
                                  "date": str(n_date), "type": n_type, "fee": n_fee})
                st.success(f"✅ {n_type} {n_sym} aggiunto.")
                st.cache_data.clear(); time.sleep(0.3); st.rerun()

    if raw_tx:
        st.caption("💡 Modifica le righe e clicca 'Salva'. Spunta 'Elimina' per rimuovere una riga.")
        df_ed = pd.DataFrame(raw_tx).rename(columns={
            "symbol":"Ticker","quantity":"Qta","price":"Prezzo",
            "date":"Data","type":"Tipo","fee":"Fee","id":"ID"})
        for col in ["ID","Ticker","Qta","Prezzo","Data","Tipo","Fee"]:
            if col not in df_ed.columns: df_ed[col] = None
        df_ed["Data"] = pd.to_datetime(df_ed["Data"], errors="coerce").dt.date
        df_ed["Elimina"] = False

        edited = st.data_editor(df_ed,
            column_config={
                "ID":      st.column_config.NumberColumn(disabled=True),
                "Elimina": st.column_config.CheckboxColumn(default=False),
                "Data":    st.column_config.DateColumn(format="DD/MM/YYYY"),
                "Prezzo":  st.column_config.NumberColumn(format="€%.2f"),
                "Fee":     st.column_config.NumberColumn(format="€%.2f"),
                "Tipo":    st.column_config.SelectboxColumn(options=["BUY","SELL"]),
            }, hide_index=True, use_container_width=True)

        if st.button("💾 Salva Modifiche", type="primary"):
            for _, row in edited[edited["Elimina"]].iterrows():
                delete_transaction(int(row["ID"]))
            for _, row in edited[~edited["Elimina"]].iterrows():
                update_transaction(int(row["ID"]), {
                    "symbol":   str(row["Ticker"]).upper(),
                    "quantity": float(row["Qta"]),
                    "price":    float(row["Prezzo"]),
                    "date":     str(row["Data"]),
                    "type":     str(row["Tipo"]).upper(),
                    "fee":      float(row["Fee"]) if row["Fee"] else 0.0,
                })
            st.success("✅ Salvato."); st.cache_data.clear(); time.sleep(0.3); st.rerun()
    else:
        st.info("Nessuna transazione registrata.")


# ─────────────────────────────────────────────────────────────────────────────
# Pagina: Consigli AI
# ─────────────────────────────────────────────────────────────────────────────
def page_advice():
    st.title("💡 AI Advisor")
    _disclaimer()

    if st.button("🔄 Aggiorna Analisi", type="primary", use_container_width=True):
        st.cache_data.clear(); clear_cache(); st.rerun()

    with st.spinner("Analisi portafoglio e mercato in corso…"):
        pf, _ = get_portfolio_summary()
        owned = list(pf.keys())
        all_t = list(set(owned + AUTO_SCAN_TICKERS))
        mdata = get_market_data(all_t)

        sell_items: list[dict] = []
        buy_more:   list[dict] = []
        hold_items: list[dict] = []
        new_entry:  list[AnalysisResult] = []

        for ticker, pos in pf.items():
            if ticker not in mdata: continue
            df_ind = compute_indicators(mdata[ticker])
            if df_ind is None: continue
            cur = float(df_ind["Close"].iloc[-1])
            adv = portfolio_advice(df_ind, pos["avg_price"], cur)
            res = analyze(df_ind, ticker, classify_asset(ticker))
            item = {"ticker": ticker, "title": adv.title, "advice": adv.advice,
                    "color": adv.color, "pnl": adv.pnl_pct, "res": res, "adv": adv}

            urg = ["PERICOLO","INCASSA","PROTEGGI","TAKE PROFIT"]
            acc = ["ACCUMULO","LASCIA CORRERE","ACCUMULA"]
            if any(k in adv.title for k in urg):
                sell_items.append(item)
            elif any(k in adv.title for k in acc):
                buy_more.append(item)
            else:
                hold_items.append(item)

        for ticker in AUTO_SCAN_TICKERS:
            if ticker in owned or ticker not in mdata: continue
            df_ind = compute_indicators(mdata[ticker])
            if df_ind is None: continue
            res = analyze(df_ind, ticker, classify_asset(ticker))
            if res.signal in ("BUY_STRONG","BUY"):
                new_entry.append(res)

        new_entry.sort(key=lambda r: r.confidence_score, reverse=True)

    # Riepilogo
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔴 Azioni Urgenti", len(sell_items) + len(buy_more))
    c2.metric("🔵 In Holding",     len(hold_items))
    c3.metric("🚀 Nuove Opp.",     len(new_entry))
    c4.metric("📊 Analizzati",     len([t for t in owned if t in mdata]))
    st.divider()

    def _simple_card(item: dict, border_color: str) -> None:
        res: AnalysisResult = item["res"]
        pnl_col = "#16a34a" if item["pnl"] >= 0 else "#dc2626"
        sign = "+" if item["pnl"] >= 0 else ""
        html = f"""
<div class="opp-card" style="border-left:4px solid {border_color};">
  <div style="display:flex;justify-content:space-between;align-items:center;">
    <div>
      <span style="font-weight:700;font-size:1rem;">{item['ticker']}</span>
      {_type_tag(classify_asset(item['ticker']))}
      <div style="font-size:0.72rem;color:#9ca3af;">{get_asset_name(item['ticker'])}</div>
    </div>
    <div style="text-align:right;">
      <span style="font-weight:700;color:{pnl_col};">{sign}{item['pnl']:.1f}%</span><br>
      {_score_badge_html(res.confidence_score)}
    </div>
  </div>
  <div style="margin:8px 0 4px;font-weight:600;font-size:0.95rem;">{item['title']}</div>
  <p style="font-size:0.82rem;color:#374151;margin:0 0 8px;">{item['advice']}</p>
  <div class="stat-row">
    <div class="stat-item">🎯 Target <b>${res.target:.2f}</b> ({res.upside_pct:+.1f}%)</div>
    <div class="stat-item">🛑 Supp. <b>${res.support:.2f}</b></div>
  </div>
</div>"""
        st.markdown(html, unsafe_allow_html=True)

    if sell_items:
        st.subheader("🔴 Richiedono Azione")
        cols = st.columns(3)
        for i, item in enumerate(sell_items):
            with cols[i%3]: _simple_card(item, "#ef4444")
        st.divider()

    if buy_more:
        st.subheader("🟢 Occasioni Accumulo (posizioni esistenti)")
        cols = st.columns(3)
        for i, item in enumerate(buy_more):
            with cols[i%3]: _simple_card(item, "#22c55e")
        st.divider()

    if hold_items:
        st.subheader("🔵 Monitoraggio")
        cols = st.columns(3)
        for i, item in enumerate(hold_items):
            with cols[i%3]: _simple_card(item, "#6366f1")
        st.divider()

    if new_entry:
        st.subheader("🚀 Nuove Opportunità")
        cols = st.columns(3)
        for i, res in enumerate(new_entry[:12]):
            with cols[i%3]: render_opportunity_card(res)

    if not (sell_items or buy_more or hold_items or new_entry):
        st.info("Nessun dato. Aggiungi transazioni al portafoglio o verifica la connessione.")


# ─────────────────────────────────────────────────────────────────────────────
# Pagina: Impostazioni
# ─────────────────────────────────────────────────────────────────────────────
def page_settings():
    st.title("⚙️ Impostazioni")
    tab_tg, tab_wl = st.tabs(["🔔 Telegram", "📋 Watchlist"])

    with tab_tg:
        st.info("Configura Telegram per ricevere report automatici ogni mattina alle 08:00 UTC.")
        current_id = get_setting("telegram_chat_id", "")
        chat_id_input = st.text_input("Telegram Chat ID", value=current_id,
                                       help="Ottienilo da @userinfobot su Telegram")
        try:
            token_ok = bool(st.secrets.get("telegram", {}).get("token", ""))
        except Exception:
            token_ok = bool(os.environ.get("TELEGRAM_TOKEN", ""))

        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 Salva Chat ID", type="primary", use_container_width=True):
                if chat_id_input.strip():
                    set_setting("telegram_chat_id", chat_id_input.strip())
                    st.success("Salvato!")
                else:
                    st.warning("ID non valido.")
        with col2:
            if st.button("🔕 Disattiva", use_container_width=True):
                set_setting("telegram_chat_id", "")
                st.success("Notifiche disattivate.")

        st.markdown("""
**Setup Telegram:**
1. Cerca **@userinfobot** → START → copia il numero 'Id'
2. Incollalo qui sopra → Salva
3. Cerca il tuo **InvestAI Bot** → START
4. Imposta il `token` in Streamlit Cloud → Secrets
        """)
        if not token_ok:
            st.warning("⚠️ Token Telegram non configurato nelle Secrets.")

    with tab_wl:
        st.info(f"Gestisci i **{len(load_watchlist())} asset** analizzati nella scansione automatica.")
        wl = load_watchlist()

        with st.expander("➕ Aggiungi Asset"):
            c_tk, c_nm, c_bt = st.columns([2, 2, 1])
            new_t = c_tk.text_input("Ticker", key="wl_t").upper().strip()
            new_n = c_nm.text_input("Nome", key="wl_n").strip()
            if c_bt.button("Aggiungi", type="primary", use_container_width=True):
                if not new_t:
                    st.warning("Inserisci il ticker.")
                else:
                    with st.spinner("Verifica su Yahoo Finance…"):
                        ok = validate_ticker(new_t)
                    if ok:
                        add_to_watchlist(new_n or new_t, new_t)
                        st.success(f"✅ {new_t} aggiunto.")
                        time.sleep(0.3); st.rerun()
                    else:
                        st.error(f"❌ '{new_t}' non trovato.")

        st.markdown(f"**Lista attuale ({len(wl)} asset)**")
        if wl:
            # Mostra in tre colonne
            items = sorted(wl.items())
            chunk = max(1, len(items)//3)
            c1, c2, c3 = st.columns(3)
            for col, chunk_items in zip([c1, c2, c3],
                                        [items[:chunk], items[chunk:2*chunk], items[2*chunk:]]):
                with col:
                    for name, sym in chunk_items:
                        ca, cb, cc = st.columns([3, 2, 1])
                        ca.markdown(f"**{name}**")
                        cb.code(sym, language=None)
                        if cc.button("🗑️", key=f"del_{sym}", help="Rimuovi"):
                            remove_from_watchlist(sym); st.rerun()
        else:
            st.info("Lista vuota.")
            if st.button("🔄 Carica asset predefiniti"):
                save_watchlist(dict(POPULAR_ASSETS)); st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    if not is_authenticated():
        render_login_page()
        st.stop()
        return

    with st.sidebar:
        st.markdown("""
        <div style="text-align:center;padding:24px 10px 16px;">
          <div style="font-size:3rem;">💎</div>
          <h2 style="margin:6px 0 2px;font-size:1.4rem;color:white;">InvestAI</h2>
          <div style="font-size:0.72rem;color:#9ca3af;">Assistente Finanziario Personale</div>
        </div>
        """, unsafe_allow_html=True)

        page = st.radio("nav", [
            "📊 Analisi Mercato",
            "💼 Portafoglio",
            "💡 Consigli AI",
            "⚙️ Impostazioni",
        ], label_visibility="collapsed")

        st.divider()

        wl_count = len(load_watchlist())
        st.markdown(f"""
        <div style="font-size:0.78rem;color:#9ca3af;padding:0 4px;">
          🗄️ Storage locale attivo<br>
          📋 Watchlist: <b style="color:white;">{wl_count} asset</b>
        </div>
        """, unsafe_allow_html=True)

        st.divider()

        if st.button("🚪 Esci", use_container_width=True):
            logout()

        st.markdown("""
        <div style="font-size:0.65rem;color:#4b5563;text-align:center;margin-top:12px;">
          InvestAI v2.1 · Nicola Serra<br>
          ⚠️ Solo informativo
        </div>
        """, unsafe_allow_html=True)

    if page == "📊 Analisi Mercato":
        page_market()
    elif page == "💼 Portafoglio":
        page_portfolio()
    elif page == "💡 Consigli AI":
        page_advice()
    elif page == "⚙️ Impostazioni":
        page_settings()


if __name__ == "__main__":
    main()
