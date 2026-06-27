"""
InvestAI — Assistente Finanziario Personale
Versione 2.0 | Single-User | Storage Locale JSON | No Database

⚠️ DISCLAIMER: InvestAI è uno strumento informativo e non costituisce consulenza
finanziaria. Le analisi si basano su indicatori tecnici storici. I rendimenti
passati non garantiscono risultati futuri. Investi sempre consapevolmente.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# --- Moduli interni ---
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

# ---------------------------------------------------------------------------
# Configurazione pagina
# ---------------------------------------------------------------------------
st.set_page_config(page_title="InvestAI", layout="wide", page_icon="💎")

# ---------------------------------------------------------------------------
# Avvio Bot Telegram (singleton, opzionale)
# ---------------------------------------------------------------------------
@st.cache_resource
def _start_telegram():
    try:
        # Token: prima da st.secrets, poi da variabile d'ambiente
        import os
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

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    #MainMenu { visibility: hidden; }
    .stDeployButton { display: none; }
    footer { visibility: hidden; }
    header { background: transparent !important; }

    .card {
        padding: 16px;
        border-radius: 12px;
        border-left: 5px solid #aaa;
        margin-bottom: 14px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.06);
    }
    .disclaimer {
        background: #fff8e1;
        border-left: 4px solid #f9a825;
        padding: 10px 14px;
        border-radius: 6px;
        font-size: 0.82rem;
        color: #555;
        margin-bottom: 12px;
    }
    .score-badge {
        background: #388e3c;
        color: white;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 0.85rem;
        font-weight: bold;
    }
    .storage-badge {
        background: #e8f5e9;
        border: 1px solid #a5d6a7;
        border-radius: 8px;
        padding: 6px 12px;
        font-size: 0.78rem;
        color: #2e7d32;
    }
</style>
""", unsafe_allow_html=True)

_DISCLAIMER = (
    "⚠️ <b>Disclaimer:</b> InvestAI è uno strumento informativo e <b>non costituisce "
    "consulenza finanziaria</b>. Le analisi si basano su indicatori tecnici storici. "
    "I rendimenti passati non garantiscono risultati futuri."
)

# ---------------------------------------------------------------------------
# Cache dati mercato (10 min TTL, Streamlit-level)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def _get_market_data(tickers: tuple[str, ...]) -> dict:
    return get_data_raw(list(tickers))


def get_market_data(tickers: list[str]) -> dict:
    return _get_market_data(tuple(sorted(set(tickers))))


@st.cache_data(ttl=600, show_spinner=False)
def _get_indicators(ticker: str, data_hash: int):
    """Cache degli indicatori per ticker. data_hash funge da chiave di invalidazione."""
    # Recupera dal market_data non cachato per non duplicare
    raw = get_data_raw([ticker])
    if ticker not in raw:
        return None
    return compute_indicators(raw[ticker])


# ---------------------------------------------------------------------------
# Helper UI
# ---------------------------------------------------------------------------

def _disclaimer_box():
    st.markdown(f'<div class="disclaimer">{_DISCLAIMER}</div>', unsafe_allow_html=True)


def _score_badge(score: int, label: str = "") -> str:
    return f'<span class="score-badge">{label or "Score"}: {score}/100</span>'


def _render_analysis_card(res: AnalysisResult, show_backtest: bool = True) -> None:
    """Renderizza una card di analisi tecnica (uso in Analisi Mercato e Consigli)."""
    border = "3px solid #FFD700" if res.signal == "BUY_STRONG" else "1px solid #aaa"
    
    reasons_html = ""
    if res.reasons:
        reasons_html = "<ul style='font-size:0.8rem;margin:4px 0;padding-left:16px;'>"
        for r in res.reasons[:4]:
            reasons_html += f"<li>{r}</li>"
        reasons_html += "</ul>"
    
    warnings_html = ""
    if res.warnings:
        warnings_html = "<ul style='font-size:0.8rem;margin:4px 0;padding-left:16px;color:#b71c1c;'>"
        for w in res.warnings[:3]:
            warnings_html += f"<li>{w}</li>"
        warnings_html += "</ul>"

    backtest_html = ""
    if show_backtest and (res.backtest_win30 or res.backtest_win90):
        col30 = "green" if res.backtest_pnl30 >= 0 else "red"
        col90 = "green" if res.backtest_pnl90 >= 0 else "red"
        backtest_html = f"""
        <div style='font-size:0.78rem;border-top:1px dashed #ccc;padding-top:4px;margin-top:4px;'>
          <b>Storico segnale:</b>
          <span style='margin-left:8px;'>30g: {res.backtest_win30:.0f}% win
            <span style='color:{col30};'>({res.backtest_pnl30:+.1f}%)</span>
          </span>
          <span style='margin-left:8px;'>90g: {res.backtest_win90:.0f}% win
            <span style='color:{col90};'>({res.backtest_pnl90:+.1f}%)</span>
          </span>
        </div>"""

    st.markdown(f"""
    <div class="card" style="background-color:{res.color}; border:{border};">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;">
        <div>
          <strong style="font-size:1.05rem;">{res.ticker}</strong>
          <span style="font-size:0.75rem;color:#666;margin-left:6px;">{classify_asset(res.ticker)}</span>
          <div style="font-size:0.72rem;color:#888;">{get_asset_name(res.ticker)}</div>
        </div>
        <div style="text-align:right;">
          {_score_badge(res.confidence_score)}
          <div style="font-size:0.75rem;color:#555;margin-top:2px;">
            RSI {res.rsi:.0f} | ADX {res.adx:.0f}
          </div>
        </div>
      </div>
      <h3 style="margin:8px 0;font-size:1.05rem;color:#222;">{res.action_label}</h3>
      {reasons_html}
      {warnings_html}
      <div style="display:flex;justify-content:space-between;font-size:0.82rem;margin-top:6px;">
        <span>Prezzo: <b>${res.last_price:,.2f}</b></span>
        <span style="color:green;">🎯 Target: ${res.target:.2f} (+{res.upside_pct:.1f}%)</span>
        <span style="color:#b71c1c;">🛑 Supporto: ${res.support:.2f} ({res.downside_pct:.1f}%)</span>
      </div>
      {backtest_html}
    </div>
    """, unsafe_allow_html=True)


def _create_price_chart(df: pd.DataFrame, ticker: str, trend_label: str) -> go.Figure:
    """Grafico candlestick con SMA50, SMA200 e volume."""
    df_plot = df.tail(int(365 * 1.5)).copy()
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.05, row_heights=[0.72, 0.28],
    )
    fig.add_trace(go.Candlestick(
        x=df_plot.index,
        open=df_plot["Open"], high=df_plot["High"],
        low=df_plot["Low"], close=df_plot["Close"],
        name="Prezzo",
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
    ), row=1, col=1)

    if "SMA_200" in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot["SMA_200"],
            name="SMA 200", line=dict(color="#FFD700", width=2),
        ), row=1, col=1)
    if "SMA_50" in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot["SMA_50"],
            name="SMA 50", line=dict(color="#FF6B6B", width=1.5, dash="dot"),
        ), row=1, col=1)
    if "BBU" in df_plot.columns and "BBL" in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot["BBU"],
            name="BB Sup", line=dict(color="rgba(100,100,255,0.4)", width=1),
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot["BBL"],
            name="BB Inf", fill="tonexty",
            fillcolor="rgba(100,100,255,0.05)",
            line=dict(color="rgba(100,100,255,0.4)", width=1),
        ), row=1, col=1)

    colors_vol = [
        "#ef5350" if c < o else "#26a69a"
        for o, c in zip(df_plot["Open"], df_plot["Close"])
    ]
    fig.add_trace(go.Bar(
        x=df_plot.index, y=df_plot["Volume"],
        name="Volume", marker_color=colors_vol, opacity=0.5,
    ), row=2, col=1)

    fig.update_layout(
        title=dict(text=f"<b>{ticker}</b> — {trend_label}", font=dict(size=17)),
        template="plotly_dark",
        height=560,
        margin=dict(l=20, r=20, t=50, b=20),
        showlegend=True,
        legend=dict(x=0, y=1, orientation="h"),
        xaxis_rangeslider_visible=False,
    )
    return fig


# ---------------------------------------------------------------------------
# Pagina: Analisi Mercato
# ---------------------------------------------------------------------------

def page_market():
    st.title("📊 Analisi Mercato")
    _disclaimer_box()

    # Watchlist
    wl = load_watchlist()
    if not wl:
        # Prima volta: popola con i default
        wl = dict(POPULAR_ASSETS)
        save_watchlist(wl)

    wl_tickers  = list(wl.values())
    wl_options  = sorted(list(wl.keys()))

    # --- LEGENDA ---
    with st.expander("ℹ️ Come leggere l'analisi", expanded=False):
        st.markdown("""
**Scores (0–100):**
- **Opportunity Score**: sintesi pesata di trend (35%), momentum (25%), valore (20%), volume (20%)
- **Confidence Score**: solidità del segnale — penalizzato da conflitti tra indicatori, trend ribassista, ADX basso
- **Risk Score**: 0 = basso rischio, 100 = altissimo rischio (basato su ATR, drawdown, volatilità storica)

**Segnali operativi:**
- 💎 OPPORTUNITÀ D'ORO: trend bull + RSI < 30 + prezzo sotto Bollinger inferiore (setup raro)
- 🛒 ACQUISTA (Dip): trend bull + RSI scarico o prezzo vicino a Bollinger inferiore
- 🚀 TREND SOLIDO: trend bull senza estremi — mantieni
- 💰 VENDI PARZIALE: ipercomprato (RSI > 75 o prezzo sopra Bollinger superiore)
- ⚠️ RIMBALZO TECNICO: bear trend + RSI estremo (alto rischio)
- ⛔ STAI ALLA LARGA: bear trend + MACD negativo
- ✋ ATTENDI: segnali conflittuali o confidence < 30

**Backtest storico**: win rate e P&L medio nei 30/60/90 giorni successivi ai segnali simili passati.
Campioni < 15 segnali vengono automaticamente scontati verso il 50% (ridge verso la media).
        """)

    # --- SCANSIONE AUTOMATICA ---
    with st.expander("🤖 Scansione Automatica Watchlist", expanded=True):
        if st.button("🔎 Scansiona ora", use_container_width=True):
            with st.spinner(f"Analisi di {len(wl_tickers)} asset…"):
                mdata = get_market_data(wl_tickers)
                opportunities: list[AnalysisResult] = []

                for t in wl_tickers:
                    if t not in mdata:
                        continue
                    df_ind = compute_indicators(mdata[t])
                    if df_ind is None:
                        continue
                    res = analyze(df_ind, t, classify_asset(t))
                    if res.signal in ("BUY_STRONG", "BUY", "SELL_PARTIAL"):
                        opportunities.append(res)

                if opportunities:
                    # Ordina: BUY_STRONG prima, poi per confidence desc
                    priority = {"BUY_STRONG": 3, "BUY": 2, "SELL_PARTIAL": 1}
                    opportunities.sort(
                        key=lambda r: (priority.get(r.signal, 0), r.confidence_score),
                        reverse=True,
                    )
                    if any(r.signal == "BUY_STRONG" for r in opportunities):
                        st.balloons()
                        st.success("💎 TROVATA UN'OPPORTUNITÀ D'ORO!")

                    cols = st.columns(3)
                    for i, res in enumerate(opportunities):
                        with cols[i % 3]:
                            _render_analysis_card(res)
                else:
                    st.info("Nessun segnale forte rilevato nella watchlist.")

    st.divider()
    st.subheader("🔎 Analisi Singolo Asset")

    all_opts = ["➕ Inserisci Ticker Manuale…"] + wl_options
    c_sel, c_inp = st.columns([3, 1])
    with c_sel:
        selection = st.selectbox("Seleziona Asset", all_opts)

    selected_ticker: str | None = None
    if selection == "➕ Inserisci Ticker Manuale…":
        with c_inp:
            manual = st.text_input("Ticker", placeholder="AAPL").upper().strip()
        if manual:
            selected_ticker = manual
    else:
        selected_ticker = wl.get(selection)

    if selected_ticker:
        with st.spinner(f"Download {selected_ticker}…"):
            mdata = get_market_data([selected_ticker])

        if selected_ticker not in mdata:
            st.error(f"Impossibile scaricare dati per '{selected_ticker}'. Verifica il ticker.")
        else:
            df_ind = compute_indicators(mdata[selected_ticker])
            if df_ind is None:
                st.warning(f"Dati insufficienti per analizzare {selected_ticker} (servono almeno 220 sessioni).")
            else:
                res = analyze(df_ind, selected_ticker, classify_asset(selected_ticker))

                # Metriche
                k1, k2, k3, k4, k5 = st.columns(5)
                k1.metric("Prezzo", f"${res.last_price:,.2f}")
                k2.metric("Target", f"${res.target:,.2f}", delta=f"+{res.upside_pct:.1f}%")
                k3.metric("Supporto", f"${res.support:,.2f}", delta=f"{res.downside_pct:.1f}%")
                k4.metric("RSI", f"{res.rsi:.0f}")
                k5.metric("🏆 Score", f"{res.confidence_score}/100")

                # Grafici extra: scores dettagliati
                sc1, sc2, sc3, sc4 = st.columns(4)
                sc1.metric("Trend", f"{res.trend_score}/100")
                sc2.metric("Momentum", f"{res.momentum_score}/100")
                sc3.metric("Value", f"{res.value_score}/100")
                sc4.metric("Volume", f"{res.volume_score}/100")

                st.plotly_chart(
                    _create_price_chart(df_ind, selected_ticker, res.trend_label),
                    use_container_width=True,
                )

                # Backtest
                st.subheader("📊 Backtest Storico Segnale")
                b1, b2, b3, b4, b5, b6 = st.columns(6)
                b1.metric("Win 30g", f"{res.backtest_win30:.0f}%")
                b2.metric("PnL 30g", f"{res.backtest_pnl30:+.1f}%", delta_color="off")
                b3.metric("Win 60g", f"{res.backtest_win60:.0f}%")
                b4.metric("PnL 60g", f"{res.backtest_pnl60:+.1f}%", delta_color="off")
                b5.metric("Win 90g", f"{res.backtest_win90:.0f}%")
                b6.metric("PnL 90g", f"{res.backtest_pnl90:+.1f}%", delta_color="off")

                # Card segnale
                _render_analysis_card(res, show_backtest=False)

                # Spiegazione dettagliata
                with st.expander("🔬 Ragionamento dettagliato", expanded=False):
                    if res.reasons:
                        st.markdown("**✅ Fattori positivi:**")
                        for r in res.reasons:
                            st.markdown(f"- {r}")
                    if res.warnings:
                        st.markdown("**⚠️ Fattori di attenzione:**")
                        for w in res.warnings:
                            st.markdown(f"- {w}")
                    if res.insufficient_data:
                        st.warning("Dati insufficienti per un'analisi completa.")


# ---------------------------------------------------------------------------
# Pagina: Portafoglio
# ---------------------------------------------------------------------------

def page_portfolio():
    c_title, c_refresh = st.columns([3, 1])
    with c_title:
        st.title("💼 Portafoglio")
    with c_refresh:
        if st.button("🔄 Aggiorna Dati"):
            st.cache_data.clear()
            clear_cache()
            time.sleep(0.5)
            st.rerun()

    _disclaimer_box()

    pf, history_list = get_portfolio_summary()
    raw_tx = load_transactions()

    if not pf:
        st.info("Il portafoglio è vuoto. Aggiungi transazioni nella scheda 'Cronologia'.")
        _render_transaction_tab(raw_tx)
        return

    # Download prezzi
    tickers_owned = list(pf.keys())
    tickers_hist  = list({t["symbol"] for t in raw_tx} if raw_tx else set())
    all_tickers   = list(set(tickers_owned + tickers_hist))

    with st.spinner("Download prezzi di mercato…"):
        mdata = get_market_data(all_tickers)

    # Calcola indicatori e aggiorna portafoglio
    pf_enriched: dict = {}
    tot_val  = 0.0
    tot_cost = 0.0
    pie_data: list[dict] = []

    first_buy = compute_first_buy_dates(raw_tx)

    for sym in tickers_owned:
        pos = pf[sym]
        if sym in mdata and not mdata[sym].empty:
            cur_price = float(mdata[sym]["Close"].iloc[-1])
        else:
            cur_price = pos["avg_price"]

        val = pos["qty"] * cur_price
        cost = pos["total_cost"]
        pnl_abs = val - cost
        pnl_pct = (pnl_abs / cost * 100) if cost > 0 else 0.0
        days_held = (date.today() - first_buy[sym]).days if sym in first_buy else 0

        pf_enriched[sym] = {
            **pos,
            "cur_price": cur_price,
            "val":       val,
            "pnl_abs":   pnl_abs,
            "pnl_pct":   pnl_pct,
            "days_held": days_held,
        }
        tot_val  += val
        tot_cost += cost
        if val > 0:
            pie_data.append({"Label": sym, "Value": val})

    pnl_tot     = tot_val - tot_cost
    pnl_tot_pct = (pnl_tot / tot_cost * 100) if tot_cost > 0 else 0.0

    # Metriche principali
    m1, m2, m3 = st.columns(3)
    m1.metric("Valore Attuale", f"€{tot_val:,.2f}")
    m2.metric("Utile Netto", f"€{pnl_tot:,.2f}", delta=f"{pnl_tot_pct:.2f}%")
    m3.metric("Capitale Investito", f"€{tot_cost:,.2f}")

    st.divider()
    st.subheader("💡 Strategia Operativa")

    # Card per ogni asset
    sorted_pf = sorted(pf_enriched.items(), key=lambda x: x[1]["pnl_pct"])
    valid_pf  = [(sym, dat) for sym, dat in sorted_pf if sym in mdata]

    if valid_pf:
        cols = st.columns(3)
        for i, (sym, dat) in enumerate(valid_pf):
            df_ind = compute_indicators(mdata[sym])
            if df_ind is None:
                continue

            cur_price = dat["cur_price"]
            adv  = portfolio_advice(df_ind, dat["avg_price"], cur_price)
            res  = analyze(df_ind, sym, classify_asset(sym))

            allocazione = (dat["val"] / tot_val * 100) if tot_val > 0 else 0.0
            trend_icon  = "🟢" if res.is_bullish else "🔴"

            # Stima giorni al target
            if res.atr > 0:
                gg = int(abs(res.target - cur_price) / (res.atr * 0.5))
                gg_label = "Questa settimana" if gg < 5 else ("Lungo Termine" if gg > 100 else f"~{gg} gg")
            else:
                gg_label = "N/A"

            dist_target   = ((res.target   - cur_price) / cur_price * 100) if cur_price > 0 else 0.0
            dist_stop     = ((res.support  - cur_price) / cur_price * 100) if cur_price > 0 else 0.0
            dist_trailing = ((adv.trailing_stop - cur_price) / cur_price * 100) if cur_price > 0 else 0.0

            with cols[i % 3]:
                pnl_color = "green" if dat["pnl_pct"] >= 0 else "red"
                st.markdown(f"""
                <div class="card" style="background:{adv.color};min-height:360px;">
                  <div style="display:flex;justify-content:space-between;border-bottom:1px solid rgba(0,0,0,.1);padding-bottom:8px;margin-bottom:8px;">
                    <div>
                      <strong style="font-size:1.05rem;">{sym}</strong>
                      <div style="font-size:0.75rem;color:#555;">{get_asset_name(sym)}</div>
                    </div>
                    <div style="text-align:right;">
                      <span style="font-weight:bold;color:{pnl_color};font-size:1.05rem;">{dat['pnl_pct']:+.1f}%</span>
                      <div style="font-size:0.7rem;background:#444;color:white;padding:2px 6px;border-radius:4px;margin-top:2px;">📅 {dat['days_held']} gg</div>
                    </div>
                  </div>

                  <h3 style="color:#222;margin:4px 0;font-size:1rem;">
                    {adv.title}
                    <span class="score-badge" style="float:right;font-size:0.78rem;">Score {res.confidence_score}</span>
                  </h3>
                  <p style="font-size:0.83rem;margin-bottom:8px;color:#333;line-height:1.35;">{adv.advice}</p>

                  <div style="display:flex;justify-content:space-between;font-size:0.82rem;padding:4px 0;border-top:1px dashed #ccc;border-bottom:1px dashed #ccc;margin-bottom:8px;">
                    <span>Prezzo: <b>${cur_price:.2f}</b></span>
                    <span style="color:#666;">Media: ${dat['avg_price']:.2f}</span>
                  </div>

                  <div style="background:rgba(255,255,255,.6);padding:8px;border-radius:6px;border:1px dashed #777;margin-bottom:10px;">
                    <div style="font-size:0.65rem;text-transform:uppercase;color:#555;font-weight:bold;text-align:center;margin-bottom:4px;">Analisi Posizione</div>
                    <div style="display:flex;justify-content:space-between;font-size:0.8rem;margin-bottom:4px;">
                      <span>Trend: <b>{trend_icon}</b></span>
                      <span>RSI: <b>{res.rsi:.0f}</b></span>
                      <span>ADX: <b>{res.adx:.0f}</b></span>
                    </div>
                    <div style="display:flex;justify-content:space-between;font-size:0.8rem;">
                      <span>Alloc: <b>{allocazione:.1f}%</b></span>
                      <span>Risk: <b>{adv.risk_score}/10</b></span>
                      <span style="color:red;">DD: <b>{res.drawdown_pct:.0f}%</b></span>
                    </div>
                  </div>

                  <div style="font-size:0.75rem;color:#333;">
                    <div style="margin-bottom:4px;font-weight:bold;">
                      🛡️ Trailing Stop: ${adv.trailing_stop:.2f} ({dist_trailing:.1f}%)
                    </div>
                    <div style="display:flex;justify-content:space-between;margin-bottom:2px;">
                      <span style="color:green;">🎯 Target: ${res.target:.0f} (+{dist_target:.1f}%)</span>
                      <span style="background:#e8f5e9;padding:0 4px;border-radius:3px;font-size:0.7rem;color:green;">⏳ {gg_label}</span>
                    </div>
                    <div><span style="color:#b71c1c;">🛑 Supporto: ${res.support:.0f} ({dist_stop:.1f}%)</span></div>
                  </div>
                </div>
                """, unsafe_allow_html=True)

    st.divider()

    # Tabs analisi
    tab_chart, tab_alloc, tab_tx = st.tabs(["📈 Analisi Grafica", "🍰 Allocazione", "📝 Cronologia"])

    with tab_chart:
        if raw_tx:
            with st.spinner("Elaborazione storico…"):
                df_hist = get_historical_portfolio_value(raw_tx, mdata)
            if not df_hist.empty:
                excel_bytes = generate_excel_report(df_hist, pf_enriched, raw_tx)
                st.download_button(
                    "📥 Scarica Report Excel",
                    data=excel_bytes,
                    file_name=f"InvestAI_Report_{date.today()}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                g1, g2, g3, g4 = st.tabs(["Capitale", "Utili", "Asset", "Proiezione"])

                with g1:
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist["Total Value"],
                                             mode="lines", name="Valore",
                                             line=dict(color="#004d40", width=2), fill="tozeroy"))
                    fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist["Total Invested"],
                                             mode="lines", name="Investito",
                                             line=dict(color="#ef5350", width=2, dash="dash")))
                    fig.update_layout(height=400, hovermode="x unified", title="Valore vs Investito", template="plotly_white")
                    st.plotly_chart(fig, use_container_width=True)

                with g2:
                    df_hist["Net P&L"] = df_hist["Total Value"] - df_hist["Total Invested"]
                    colors = ["#66bb6a" if v >= 0 else "#ef5350" for v in df_hist["Net P&L"]]
                    fig = go.Figure(go.Bar(x=df_hist.index, y=df_hist["Net P&L"],
                                           marker_color=colors, name="P&L"))
                    fig.update_layout(height=400, title="Utile/Perdita Netta (€)", template="plotly_white")
                    st.plotly_chart(fig, use_container_width=True)

                with g3:
                    fig = go.Figure()
                    asset_cols = [c for c in df_hist.columns if c not in ["Total Value", "Total Invested", "Net P&L"]]
                    for c in asset_cols:
                        fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist[c],
                                                  mode="lines", stackgroup="one", name=c))
                    fig.update_layout(height=400, title="Composizione nel Tempo", template="plotly_white")
                    st.plotly_chart(fig, use_container_width=True)

                with g4:
                    last_val = df_hist["Total Value"].iloc[-1]
                    df_r = df_hist.copy()
                    df_r["Inv_Delta"] = df_r["Total Invested"].diff().abs()
                    mkt_mask = df_r["Inv_Delta"] < 1.0
                    if mkt_mask.sum() > 10:
                        ret = df_r.loc[mkt_mask, "Total Value"].pct_change().dropna()
                        daily_drift = float(ret.mean()) if not ret.empty else 0.0
                        daily_vol   = float(ret.std())  if not ret.empty else 0.015
                    else:
                        daily_drift, daily_vol = 0.0005, 0.015
                    daily_drift = 0.0 if np.isnan(daily_drift) else daily_drift
                    daily_vol   = 0.015 if np.isnan(daily_vol) or daily_vol <= 0 else daily_vol

                    days_proj = 90
                    dates_proj = pd.date_range(start=df_hist.index[-1], periods=days_proj + 1)
                    mean_path  = [last_val * (1 + daily_drift) ** i for i in range(days_proj + 1)]
                    upper_path = [m * (1 + daily_vol * np.sqrt(i)) for i, m in enumerate(mean_path)]
                    lower_path = [m * (1 - daily_vol * np.sqrt(i)) for i, m in enumerate(mean_path)]

                    fig = go.Figure()
                    cutoff = df_hist.index[-60:] if len(df_hist) > 60 else df_hist.index
                    fig.add_trace(go.Scatter(x=cutoff, y=df_hist.loc[cutoff, "Total Value"],
                                             mode="lines", name="Storico", line=dict(color="gray")))
                    fig.add_trace(go.Scatter(x=dates_proj, y=upper_path, line=dict(width=0), showlegend=False))
                    fig.add_trace(go.Scatter(x=dates_proj, y=lower_path, fill="tonexty",
                                             fillcolor="rgba(0,77,64,0.15)", line=dict(width=0),
                                             name="Range probabile (90gg)"))
                    fig.add_trace(go.Scatter(x=dates_proj, y=mean_path,
                                             line=dict(color="#004d40", dash="dash"), name="Trend atteso"))
                    fig.update_layout(height=450, title="Proiezione (Monte Carlo semplificato — solo illustrativo)",
                                      template="plotly_white")
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("Dati storici non sufficienti.")
        else:
            st.info("Nessuna transazione registrata.")

    with tab_alloc:
        if pf_enriched:
            c_pie, c_list = st.columns([1, 1.5])
            with c_pie:
                if pie_data:
                    fig = go.Figure(go.Pie(
                        labels=[d["Label"] for d in pie_data],
                        values=[d["Value"] for d in pie_data],
                        hole=0.4,
                    ))
                    fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=300, showlegend=False)
                    st.plotly_chart(fig, use_container_width=True)
            with c_list:
                alloc_rows = []
                for sym, dat in pf_enriched.items():
                    alloc_rows.append({
                        "Asset": sym,
                        "Valore Attuale": dat["val"],
                        "Costo Totale":   dat["total_cost"],
                        "P&L %":          dat["pnl_pct"] / 100,
                        "Data 1° Acq":    first_buy.get(sym),
                    })
                df_alloc = pd.DataFrame(alloc_rows).sort_values("Valore Attuale", ascending=False)
                st.dataframe(df_alloc, hide_index=True, use_container_width=True,
                    column_config={
                        "Valore Attuale": st.column_config.NumberColumn(format="€%.2f"),
                        "Costo Totale":   st.column_config.NumberColumn(format="€%.2f"),
                        "P&L %":          st.column_config.NumberColumn(format="%.2f%%"),
                        "Data 1° Acq":    st.column_config.DateColumn(format="DD/MM/YYYY"),
                    })
        else:
            st.info("Portafoglio vuoto.")

    with tab_tx:
        _render_transaction_tab(raw_tx)


def _render_transaction_tab(raw_tx: list[dict]) -> None:
    """Scheda di gestione transazioni."""
    st.subheader("Gestione Transazioni")
    _disclaimer_box()

    with st.expander("➕ Aggiungi Nuova Transazione"):
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        n_sym  = c1.text_input("Ticker", placeholder="AAPL", key="tx_sym").upper().strip()
        n_qty  = c2.number_input("Quantità", min_value=0.0001, format="%.4f", key="tx_qty")
        n_prc  = c3.number_input("Prezzo (€/$)", min_value=0.0001, key="tx_prc")
        n_date = c4.date_input("Data", date.today(), key="tx_date")
        n_type = c5.selectbox("Tipo", ["BUY", "SELL"], key="tx_type")
        n_fee  = c6.number_input("Commissione", min_value=0.0, value=0.0, key="tx_fee")

        if st.button("Aggiungi Transazione", type="primary", use_container_width=True):
            if not n_sym:
                st.error("Inserisci il ticker.")
            elif n_qty <= 0 or n_prc <= 0:
                st.error("Quantità e prezzo devono essere > 0.")
            else:
                add_transaction({
                    "symbol":   n_sym,
                    "quantity": n_qty,
                    "price":    n_prc,
                    "date":     str(n_date),
                    "type":     n_type,
                    "fee":      n_fee,
                })
                st.success(f"Transazione {n_type} {n_sym} aggiunta.")
                st.cache_data.clear()
                time.sleep(0.5)
                st.rerun()

    if raw_tx:
        st.info("💡 Modifica le righe e clicca 'Salva Modifiche'. Spunta 'Elimina' per rimuovere.")
        df_editor = pd.DataFrame(raw_tx)
        # Normalizza colonne per l'editor
        rename = {"symbol": "Ticker", "quantity": "Qta", "price": "Prezzo",
                  "date": "Data", "type": "Tipo", "fee": "Fee", "id": "ID"}
        df_editor = df_editor.rename(columns=rename)
        for col in ["ID", "Ticker", "Qta", "Prezzo", "Data", "Tipo", "Fee"]:
            if col not in df_editor.columns:
                df_editor[col] = None
        df_editor["Data"] = pd.to_datetime(df_editor["Data"], errors="coerce").dt.date
        df_editor["Elimina"] = False

        edited = st.data_editor(
            df_editor,
            column_config={
                "ID":      st.column_config.NumberColumn(disabled=True),
                "Elimina": st.column_config.CheckboxColumn(default=False),
                "Data":    st.column_config.DateColumn(format="DD/MM/YYYY"),
                "Prezzo":  st.column_config.NumberColumn(format="€%.2f"),
                "Fee":     st.column_config.NumberColumn(format="€%.2f"),
                "Tipo":    st.column_config.SelectboxColumn(options=["BUY", "SELL"]),
            },
            hide_index=True,
            use_container_width=True,
        )

        if st.button("💾 Salva Modifiche", type="primary"):
            to_delete = edited[edited["Elimina"] == True]
            for _, row in to_delete.iterrows():
                delete_transaction(int(row["ID"]))

            to_update = edited[edited["Elimina"] == False]
            for _, row in to_update.iterrows():
                update_transaction(int(row["ID"]), {
                    "symbol":   str(row["Ticker"]).upper(),
                    "quantity": float(row["Qta"]),
                    "price":    float(row["Prezzo"]),
                    "date":     str(row["Data"]),
                    "type":     str(row["Tipo"]).upper(),
                    "fee":      float(row["Fee"]) if row["Fee"] else 0.0,
                })
            st.success("Modifiche salvate.")
            st.cache_data.clear()
            time.sleep(0.5)
            st.rerun()
    else:
        st.info("Nessuna transazione registrata.")


# ---------------------------------------------------------------------------
# Pagina: Consigli AI
# ---------------------------------------------------------------------------

def page_advice():
    st.title("💡 AI Advisor")
    _disclaimer_box()
    st.markdown("Analisi completa del portafoglio e nuove opportunità di mercato.")

    if st.button("🔄 Aggiorna Analisi", use_container_width=True):
        st.cache_data.clear()
        clear_cache()
        st.rerun()

    with st.spinner("Analisi in corso…"):
        pf, _ = get_portfolio_summary()
        owned = list(pf.keys())
        all_tickers = list(set(owned + AUTO_SCAN_TICKERS))
        mdata = get_market_data(all_tickers)

        sell_items: list[dict]  = []
        buy_more:   list[dict]  = []
        hold_items: list[dict]  = []
        new_entry:  list[dict]  = []

        # Portafoglio
        for ticker, pos in pf.items():
            if ticker not in mdata:
                continue
            df_ind = compute_indicators(mdata[ticker])
            if df_ind is None:
                continue
            cur_price = float(df_ind["Close"].iloc[-1])
            adv = portfolio_advice(df_ind, pos["avg_price"], cur_price)
            res = analyze(df_ind, ticker, classify_asset(ticker))
            pnl = adv.pnl_pct

            item = {
                "ticker":  ticker,
                "title":   adv.title,
                "advice":  adv.advice,
                "color":   adv.color,
                "pnl":     pnl,
                "res":     res,
            }

            urg_kw = ["PERICOLO", "INCASSA", "PROTEGGI", "TAKE PROFIT"]
            buy_kw = ["ACCUMULO", "ACCUMULA", "LASCIA CORRERE"]

            if any(k in adv.title for k in urg_kw):
                sell_items.append(item)
            elif any(k in adv.title for k in buy_kw):
                buy_more.append(item)
            else:
                hold_items.append(item)

        # Nuove opportunità
        for ticker in AUTO_SCAN_TICKERS:
            if ticker in owned or ticker not in mdata:
                continue
            df_ind = compute_indicators(mdata[ticker])
            if df_ind is None:
                continue
            res = analyze(df_ind, ticker, classify_asset(ticker))
            if res.signal in ("BUY_STRONG", "BUY"):
                new_entry.append({"ticker": ticker, "res": res})

        new_entry.sort(key=lambda x: x["res"].confidence_score, reverse=True)

    # Contatori
    c1, c2, c3 = st.columns(3)
    c1.metric("Azioni Urgenti", len(sell_items) + len(buy_more))
    c2.metric("In Holding", len(hold_items))
    c3.metric("Nuove Opportunità", len(new_entry))
    st.divider()

    def _simple_card(item: dict, border_color: str = "#aaa") -> None:
        res: AnalysisResult = item["res"]
        pnl_color = "green" if item["pnl"] >= 0 else "red"
        st.markdown(f"""
        <div class="card" style="background:{item['color']};border:2px solid {border_color};">
          <div style="display:flex;justify-content:space-between;">
            <div>
              <strong>{item['ticker']}</strong>
              <div style="font-size:0.73rem;color:#666;">{get_asset_name(item['ticker'])}</div>
            </div>
            <span style="font-weight:bold;color:{pnl_color};">{item['pnl']:+.1f}%</span>
          </div>
          <h3 style="margin:6px 0;font-size:1rem;color:#222;">
            {item['title']}
            {_score_badge(res.confidence_score)}
          </h3>
          <p style="font-size:0.83rem;margin-bottom:4px;">{item['advice']}</p>
          <div style="font-size:0.75rem;color:#555;">
            Target: <b>${res.target:.2f}</b> ({res.upside_pct:+.1f}%) |
            Supporto: <b>${res.support:.2f}</b> ({res.downside_pct:.1f}%)
          </div>
        </div>
        """, unsafe_allow_html=True)

    if sell_items:
        st.subheader("🔴 Richiedono Azione")
        cols = st.columns(3)
        for i, item in enumerate(sell_items):
            with cols[i % 3]:
                _simple_card(item, "#d32f2f")
        st.divider()

    if buy_more:
        st.subheader("🟢 Occasioni di Accumulo (Posizioni Esistenti)")
        cols = st.columns(3)
        for i, item in enumerate(buy_more):
            with cols[i % 3]:
                _simple_card(item, "#2e7d32")
        st.divider()

    if hold_items:
        st.subheader("🔵 Mantenimento e Monitoraggio")
        cols = st.columns(3)
        for i, item in enumerate(hold_items):
            with cols[i % 3]:
                _simple_card(item, "#78909c")
        st.divider()

    if new_entry:
        st.subheader("🚀 Nuove Opportunità (Non in Portafoglio)")
        cols = st.columns(3)
        for i, ne in enumerate(new_entry[:12]):
            with cols[i % 3]:
                _render_analysis_card(ne["res"])

    if not (sell_items or buy_more or hold_items or new_entry):
        st.info("Nessun dato disponibile. Aggiungi transazioni al portafoglio o verifica la connessione.")


# ---------------------------------------------------------------------------
# Pagina: Impostazioni
# ---------------------------------------------------------------------------

def page_settings():
    st.title("⚙️ Impostazioni")

    tab_tg, tab_wl = st.tabs(["🔔 Telegram", "📋 Watchlist"])

    with tab_tg:
        st.info("Configura Telegram per ricevere report automatici ogni mattina alle 08:00 UTC.")

        current_id = get_setting("telegram_chat_id", "")
        chat_id_input = st.text_input("Telegram Chat ID", value=current_id,
                                       help="Cerca @userinfobot su Telegram e copia il numero 'Id'")

        # Controlla se il token è configurato (da secrets o env)
        try:
            token_configured = bool(st.secrets.get("telegram", {}).get("token", ""))
        except Exception:
            token_configured = bool(os.environ.get("TELEGRAM_TOKEN", ""))

        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 Salva Chat ID", type="primary", use_container_width=True):
                if chat_id_input.strip():
                    set_setting("telegram_chat_id", chat_id_input.strip())
                    st.success("Chat ID salvato. Il bot ti invierà gli aggiornamenti.")
                else:
                    st.warning("Inserisci un Chat ID valido.")
        with col2:
            if st.button("🔕 Disattiva Notifiche", use_container_width=True):
                set_setting("telegram_chat_id", "")
                st.success("Notifiche disattivate.")

        st.markdown("""
**Come configurare Telegram:**
1. Apri Telegram e cerca **@userinfobot** → premi START → copia il numero sotto 'Id'
2. Incollalo qui sopra e clicca 'Salva'
3. Cerca il tuo **InvestAI Bot** e premi START
4. Imposta il `token` in **Streamlit Cloud → App Settings → Secrets** (sezione `[telegram]`)
        """)

        if not token_configured:
            st.warning("⚠️ Token Telegram non configurato nelle Secrets. Il bot è disabilitato.")

    with tab_wl:
        st.info("Gestisci gli asset analizzati nella sezione 'Analisi Mercato'.")

        wl = load_watchlist()

        with st.expander("➕ Aggiungi Asset", expanded=False):
            c_tk, c_nm, c_bt = st.columns([2, 2, 1])
            new_t = c_tk.text_input("Ticker (es. NVDA)", key="wl_t").upper().strip()
            new_n = c_nm.text_input("Nome visualizzato", key="wl_n").strip()
            if c_bt.button("Aggiungi", type="primary", use_container_width=True):
                if not new_t:
                    st.warning("Inserisci il ticker.")
                else:
                    with st.spinner("Verifica ticker su Yahoo Finance…"):
                        ok = validate_ticker(new_t)
                    if ok:
                        display = new_n or new_t
                        add_to_watchlist(display, new_t)
                        st.success(f"✅ {display} ({new_t}) aggiunto.")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error(f"❌ Ticker '{new_t}' non trovato su Yahoo Finance.")

        st.divider()
        st.subheader(f"La tua lista ({len(wl)} asset)")

        if wl:
            for name, sym in sorted(wl.items()):
                c1, c2, c3 = st.columns([3, 2, 1])
                c1.markdown(f"**{name}**")
                c2.code(sym)
                if c3.button("🗑️", key=f"del_{sym}"):
                    remove_from_watchlist(sym)
                    st.success(f"{sym} rimosso.")
                    time.sleep(0.3)
                    st.rerun()
        else:
            st.info("La watchlist è vuota.")
            if st.button("🔄 Carica Asset Predefiniti"):
                save_watchlist(dict(POPULAR_ASSETS))
                st.rerun()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

import os  # noqa: E402


def main():
    # -----------------------------------------------------------------------
    # Gate di autenticazione — tutto il resto dell'app è protetto
    # -----------------------------------------------------------------------
    if not is_authenticated():
        render_login_page()
        st.stop()
        return

    # -----------------------------------------------------------------------
    # Sidebar (solo utente autenticato)
    # -----------------------------------------------------------------------
    with st.sidebar:
        st.markdown("""
        <div style="text-align:center;padding:20px 10px 10px;">
          <div style="font-size:2.5rem;">💎</div>
          <h2 style="margin:4px 0;color:#004d40;">InvestAI</h2>
          <div style="font-size:0.75rem;color:#888;">Assistente Finanziario Personale</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown('<div class="storage-badge">🗄️ Storage Locale Attivo</div>', unsafe_allow_html=True)
        st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

        page = st.radio(
            "Navigazione",
            ["📊 Analisi Mercato", "💼 Portafoglio", "💡 Consigli AI", "⚙️ Impostazioni"],
            label_visibility="collapsed",
        )
        st.divider()

        if st.button("🚪 Esci", use_container_width=True):
            logout()

        st.markdown("""
        <div style="font-size:0.68rem;color:#999;text-align:center;margin-top:8px;">
          InvestAI v2.0 · Nicola Serra<br>
          ⚠️ Solo informativo — non è consulenza finanziaria
        </div>
        """, unsafe_allow_html=True)

    # -----------------------------------------------------------------------
    # Routing pagine
    # -----------------------------------------------------------------------
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

