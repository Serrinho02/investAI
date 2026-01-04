import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date, datetime
import pandas as pd
import threading
import time

from logic import (
    DBManager, get_data_raw, evaluate_strategy_full, generate_portfolio_advice, 
    AUTO_SCAN_TICKERS, POPULAR_ASSETS, validate_ticker,
    get_historical_portfolio_value, generate_enhanced_excel_report
)
from bot import run_scheduler, bot 

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="InvestAI", layout="wide", page_icon="💎")

# --- AVVIO BOT ---
@st.cache_resource
def start_bot_singleton():
    t_sched = threading.Thread(target=run_scheduler, daemon=True)
    t_sched.start()
    
    def start_bot_polling():
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Errore polling bot: {e}")
            
    t_bot = threading.Thread(target=start_bot_polling, daemon=True)
    t_bot.start()
    print("🤖 Bot Telegram avviato!")
    return True

start_bot_singleton()

# --- CSS ---
st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    .stDeployButton {display: none;}
    footer {visibility: hidden;}
    header { background: transparent !important; }

    .suggestion-box { 
        padding: 15px; 
        border-radius: 12px; 
        border-left: 5px solid; 
        margin-bottom: 15px; 
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }

    @media (max-width: 768px) {
        [data-testid="stMetric"] {
            background-color: #f9f9f9;
            padding: 10px;
            border-radius: 8px;
            margin-bottom: 5px;
            text-align: center;
        }
        [data-testid="stDataFrame"] { font-size: 0.8rem; }
        .js-plotly-plot { width: 100% !important; }
        h1 { font-size: 1.8rem !important; }
        h2 { font-size: 1.5rem !important; }
        h3 { font-size: 1.2rem !important; }
    }
</style>
""", unsafe_allow_html=True)

db = DBManager()

# --- CACHE OTTIMIZZATA ---
@st.cache_data(ttl=600, show_spinner=False)
def get_data(tickers):
    return get_data_raw(tickers)

# --- HELPER UI ---
def get_asset_name(ticker):
    reversed_assets = {v: k for k, v in POPULAR_ASSETS.items()}
    return reversed_assets.get(ticker, ticker)

def create_modern_chart(df, ticker, trend_label):
    """Grafico migliorato con più dettagli."""
    df_plot = df.tail(int(365 * 1.5)).copy()
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, 
        vertical_spacing=0.05, row_heights=[0.7, 0.3],
        subplot_titles=('', '')
    )
    
    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df_plot.index, 
        open=df_plot['Open'], 
        high=df_plot['High'], 
        low=df_plot['Low'], 
        close=df_plot['Close'], 
        name='Prezzo',
        increasing_line_color='#26a69a', 
        decreasing_line_color='#ef5350'
    ), row=1, col=1)
    
    # SMA 200
    if 'SMA_200' in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot['SMA_200'], 
            marker_color='#FFD700', name='SMA 200', 
            line=dict(width=2)
        ), row=1, col=1)
    
    # SMA 50
    if 'SMA_50' in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot['SMA_50'], 
            marker_color='#FF6B6B', name='SMA 50', 
            line=dict(width=1.5, dash='dot')
        ), row=1, col=1)
    
    # Volume
    colors_volume = ['#ef5350' if c < o else '#26a69a' 
                     for o, c in zip(df_plot['Open'], df_plot['Close'])]
    fig.add_trace(go.Bar(
        x=df_plot.index, y=df_plot['Volume'], 
        name='Volume', marker_color=colors_volume, 
        opacity=0.5
    ), row=2, col=1)
    
    bg_color = "rgba(0, 50, 0, 0.05)" if "BULLISH" in trend_label else "rgba(50, 0, 0, 0.05)"
    fig.update_layout(
        title=dict(text=f"<b>{ticker}</b> - {trend_label}", font=dict(size=18)),
        template="plotly_dark", 
        height=550, 
        margin=dict(l=20, r=20, t=60, b=20),
        showlegend=True,
        legend=dict(x=0, y=1, orientation='h'),
        plot_bgcolor=bg_color, 
        xaxis_rangeslider_visible=False
    )
    return fig

# --- MAIN APP ---
def main():
    if 'user' not in st.session_state: 
        st.session_state.user = None
    
    # LOGIN/REGISTER
    if not st.session_state.user:
        c1, c2, c3 = st.columns([1,2,1])
        with c2:
            st.title("💎 InvestAI")
            st.markdown("**Gestione Portafoglio Intelligente**")
            tab1, tab2 = st.tabs(["Accedi", "Registrati"])
            
            with tab1:
                u = st.text_input("Username", key="l_u")
                p = st.text_input("Password", type="password", key="l_p")
                if st.button("Login", type="primary", use_container_width=True):
                    if db.login_user(u, p): 
                        st.session_state.user = u
                        st.rerun()
                    else: 
                        st.error("Credenziali errate")
            
            with tab2:
                nu = st.text_input("Nuovo Username", key="r_u")
                np = st.text_input("Nuova Password", type="password", key="r_p")
                if st.button("Crea Account", use_container_width=True):
                    if db.register_user(nu, np): 
                        st.success("Account creato! Accedi ora.")
                    else: 
                        st.error("Username già esistente")
        return

    # LOGGED IN
    user = st.session_state.user
    
    # SIDEBAR
    with st.sidebar:
        st.markdown(f"""
        <div style="background-color: #f0f2f6; padding: 15px; border-radius: 12px; margin-bottom: 20px; text-align: center; border: 1px solid #e0e0e0;">
            <div style="font-size: 3rem; margin-bottom: 5px;">👤</div>
            <h3 style="margin:0; color:#004d40; font-family: sans-serif;">{user}</h3>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("### 🧭 Navigazione")
        page = st.radio(
            "Vai a:", 
            ["📊 Analisi Mercato", "💼 Portafoglio", "💡 Consigli", "⚙️ Impostazioni"], 
            label_visibility="collapsed"
        )
        
        st.markdown("<div style='height: 30px;'></div>", unsafe_allow_html=True)
        st.divider()
        
        if db.db_url == "SUPABASE_API_CONNECTION_ACTIVE":
            st.markdown("☁️**Database:** <span style='color:green;'>Connesso</span>", unsafe_allow_html=True)
        else:
            st.markdown("**Database:** <span style='color:red;'>Errore</span>", unsafe_allow_html=True)
        
        st.divider()
        
        if st.button("🚪 Esci dal Profilo", type="primary", use_container_width=True):
            st.session_state.user = None
            st.rerun()
            
        st.markdown("<div style='text-align: center; font-size: 0.7rem; color: #888; margin-top: 20px;'>InvestAI • Nicola Serra</div>", unsafe_allow_html=True)
        st.markdown("<div style='text-align: center; font-size: 0.7rem; color: #888;'>© 2025</div>", unsafe_allow_html=True)

    # === PAGINE ===
    
    # ANALISI MERCATO
    if page == "📊 Analisi Mercato":
        st.title("📊 Analisi Mercato")

        with st.expander("ℹ️ Legenda Strategica", expanded=False):
            st.markdown("""
                <div style="font-size: 0.9rem; color: #333; line-height: 1.5;">
                    L'algoritmo combina <b>Trend Following</b> (SMA 200) e <b>Mean Reversion</b> (RSI + Bollinger) filtrati dal <b>Momentum</b> (MACD).
                    <h4 style="margin-top: 15px; color: #004d40;">🏆 Confidence Score (0-100)</h4>
                    <p style="margin-top: 5px;">
                        Questo punteggio misura la <b>solidità totale</b> del segnale (Acquista/Golden) basandosi su una media ponderata di 4 fattori: 
                        Forza del Trend, Qualità del Setup (RSI/Bollinger), Rapporto Rischio/Rendimento attuale e <b>Affidabilità Storica del Backtest</b>.
                        Più è alto, più il segnale è robusto.
                    </p>
                    <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
                        <tr>
                            <td style="border: 1px solid #ddd; padding: 6px; background-color: #e6f4ea;"><b>> 65 / 100 (ALTO)</b></td>
                            <td style="border: 1px solid #ddd; padding: 6px;">Opportunità eccellente. Storia e Trend allineati.</td>
                        </tr>
                        <tr>
                            <td style="border: 1px solid #ddd; padding: 6px; background-color: #fff4cc;"><b>40–65 / 100 (MEDIO)</b></td>
                            <td style="border: 1px solid #ddd; padding: 6px;">Segnale valido, ma con potenziale debole nel medio termine o rischio elevato. Richiede cautela.</td>
                        </tr>
                        <tr>
                            <td style="border: 1px solid #ddd; padding: 6px; background-color: #fcfcfc;"><b>< 40 / 100 (BASSO)</b></td>
                            <td style="border: 1px solid #ddd; padding: 6px;">Segnale tecnico debole o statisticamente inaffidabile. Evita l'ingresso.</td>
                        </tr>
                    </table>
                    <h4 style="margin-top: 15px; color: #004d40;">📊 Analisi Storica e Timeframe (Win Rate / PnL Medio)</h4>
                    <p>
                        Il Backtest ti dice <b>cosa è successo in passato</b> dopo un segnale di acquisto simile. 
                        Usa questi dati per decidere il tuo orizzonte temporale:
                    </p>
                    <ul style="margin-top: 10px; padding-left: 20px;">
                        <li style="margin-bottom: 8px;">
                            <b>Breve Termine (30G/60G):</b> Se il Win Rate è alto (> 60%) e il PnL Medio è positivo, è un buon candidato per il <b>Trading Veloce (Swing)</b>.
                        </li>
                        <li style="margin-bottom: 8px;">
                            <b>Lungo Termine (90G):</b> Se il Win Rate e il PnL Medio a 90 Giorni sono positivi, il segnale è robusto per l'<b>Accumulo e l'Investimento (Buy & Hold)</b>.
                        </li>
                        <li style="margin-bottom: 8px; color: #b71c1c;">
                            <b>⚠️ Attenzione:</b> Se il Win Rate a 90 giorni è <b>0%</b>, il segnale è buono solo per il rimbalzo e <b>non deve essere mantenuto a lungo</b>.
                        </li>
                    </ul>
                    <h4 style="margin-top: 20px; color: #222;">🔬 I 7 Scenari Tecnici</h4>
                    <ul style="margin-top: 10px; padding-left: 20px;">
                        <li style="margin-bottom: 8px;">
                            💎 <b>OPPORTUNITÀ D'ORO (Golden Entry)</b><br>
                            <i>Setup:</i> Trend Rialzista + Crollo Anomalo (RSI < 30 + Sotto Bollinger).<br>
                            <i>Logica:</i> Il "Santo Graal" statistico. Un asset fondamentalmente forte (sopra SMA200) è crollato a livelli di ipervenduto estremo.
                        </li>
                        <li style="margin-bottom: 8px;">
                            🛒 <b>ACQUISTA ORA (Buy the Dip)</b><br>
                            <i>Setup:</i> Trend Rialzista (Prezzo > SMA200) + Ipervenduto.<br>
                            <i>Logica:</i> Il prezzo è in un trend positivo di fondo ma ha subito un ritracciamento fisiologico.
                        </li>
                        <li style="margin-bottom: 8px;">
                            💰 <b>VENDI PARZIALE (Take Profit)</b><br>
                            <i>Setup:</i> Trend Rialzista + Estensione Eccessiva.<br>
                            <i>Logica:</i> Il prezzo è "tirato". L'RSI è in zona critica (> 75).
                        </li>    
                        <li style="margin-bottom: 8px;">
                            🚀 <b>TREND SOLIDO (Hold)</b><br>
                            <i>Setup:</i> Trend Rialzista + Volatilità Contenuta.<br>
                            <i>Logica:</i> Il prezzo viaggia sopra la SMA200 senza toccare estremi di volatilità.
                        </li>
                        <li style="margin-bottom: 8px;">
                            ⚠️ <b>TENTATIVO RISCHIOSO (Reversal Trading)</b><br>
                            <i>Setup:</i> Trend Ribassista + Ipervenduto Estremo.<br>
                            <i>Logica:</i> Operazione contro-trend ad alto rischio (Dead Cat Bounce).
                        </li>
                        <li style="margin-bottom: 8px;">
                            ⛔ <b>STAI ALLA LARGA (Strong Bearish)</b><br>
                            <i>Setup:</i> Trend Ribassista + Momentum Negativo.<br>
                            <i>Logica:</i> Il prezzo è sotto la media a 200 periodi e il MACD conferma che i venditori hanno il controllo.
                        </li>
                        <li style="margin-bottom: 8px;">
                            ✋ <b>ATTENDI (Neutral/Chop)</b><br>
                            <i>Setup:</i> Segnali Conflittuali.<br>
                            <i>Logica:</i> Il mercato non ha una direzionalità chiara.
                        </li>
                    </ul>
                </div>
                """, unsafe_allow_html=True)

        with st.expander("🤖 Scansione Automatica", expanded=True):
            if st.button("🔎 Scansiona Mercato", use_container_width=True):
                with st.spinner("Analisi in corso..."):
                    auto_data = get_data(AUTO_SCAN_TICKERS)
                    opportunities = []
                    
                    for t in AUTO_SCAN_TICKERS:
                        if t in auto_data:
                            tl, act, col, pr, rsi, dd, reason, tgt, pot, risk_pr, risk_pot, w30, p30, w60, p60, w90, p90, conf = evaluate_strategy_full(auto_data[t])
                            
                            if any(x in act for x in ["ACQUISTA", "ORO", "VENDI", "RISCHIOSO"]):
                                priority = 3 if "ORO" in act else (2 if "ACQUISTA" in act else 1)
                                
                                opportunities.append({
                                    "ticker": t, "trend": tl, "action": act, 
                                    "color": col, "price": pr, "rsi": rsi, 
                                    "drawdown": dd, "reason": reason,
                                    "priority": priority, "target": tgt,      
                                    "potential": pot, "risk": risk_pr,
                                    "risk_pot": risk_pot,
                                    "w30": w30, "p30": p30, "w60": w60, 
                                    "p60": p60, "w90": w90, "p90": p90,
                                    "confidence": conf
                                })
                    
                    if opportunities:
                        opportunities = sorted(opportunities, key=lambda x: (x['priority'], x['confidence']), reverse=True)
                        
                        if any("ORO" in o['action'] for o in opportunities):
                            st.balloons()
                            st.success("💎 TROVATA UN'OPPORTUNITÀ D'ORO!")

                        cols_rec = st.columns(3)
                        for idx, opp in enumerate(opportunities):
                            border = "3px solid #FFD700" if "ORO" in opp['action'] else "1px solid #8bc34a"
                            asset_name = get_asset_name(opp['ticker'])
                            
                            with cols_rec[idx % 3]: 
                                st.markdown(f"""
                                <div class="suggestion-box" style="background-color:{opp['color']}; border: {border};">
                                    <div style="display:flex; justify-content:space-between;">
                                        <div>
                                            <h4 style="margin:0;">{opp['ticker']}</h4>
                                            <div style="font-size:0.75rem; color:#666;">{asset_name}</div>
                                        </div>
                                        <span style="font-weight:bold; color:{'green' if opp['potential']>0 else 'red'};">
                                            {'+' if opp['potential']>0 else ''}{opp['potential']:.1f}%
                                        </span>
                                    </div>
                                    <h3 style="color:#222; margin:8px 0; font-size:1.1rem;">
                                        {opp['action']}
                                        <span style="float:right; background:#388e3c; color:white; padding:4px 8px; border-radius:5px; font-size:0.9rem;">
                                            🎯 {opp['confidence']}
                                        </span>
                                    </h3>
                                    <p style="font-size:0.9rem; margin:8px 0;">{opp['reason']}</p>
                                    <hr style="margin:8px 0; opacity:0.3;">
                                    <div style="font-size:0.8rem;">
                                        <strong>Storico:</strong>
                                        <div style="display:flex; justify-content:space-between; margin-top:4px;">
                                            <span>30G: {opp['w30']:.0f}% <span style="color:{'green' if opp['p30']>=0 else 'red'};">({opp['p30']:.1f}%)</span></span>
                                            <span>60G: {opp['w60']:.0f}% <span style="color:{'green' if opp['p60']>=0 else 'red'};">({opp['p60']:.1f}%)</span></span>
                                            <span>90G: {opp['w90']:.0f}% <span style="color:{'green' if opp['p90']>=0 else 'red'};">({opp['p90']:.1f}%)</span></span>
                                        </div>
                                    </div>
                                    <hr style="margin:8px 0; opacity:0.3;">
                                    <div style="display:flex; justify-content:space-between; font-size:0.85rem;">
                                        <span>Target: <b>${opp['target']:.2f}</b></span>
                                        <span style="color:#b71c1c;">Risk: <b>{opp['risk_pot']:.1f}%</b></span>
                                    </div>
                                    <div style="text-align:right; font-size:0.8rem; margin-top:4px; color:#555;">
                                        Prezzo: ${opp['price']:.2f} | RSI: {opp['rsi']:.0f}
                                    </div>
                                </div>
                                """, unsafe_allow_html=True)
                    else:
                        st.info("Nessun segnale forte rilevato")

        st.divider()
        st.subheader("🔎 Analisi Singolo Asset")
        
        all_options = ["➕ Inserisci Ticker Manuale..."] + sorted(list(POPULAR_ASSETS.values()))
        
        c_sel, c_input = st.columns([3, 1])
        with c_sel:
            selection = st.selectbox("Seleziona Asset", all_options)
        
        selected_ticker = None
        if selection == "➕ Inserisci Ticker Manuale...":
            with c_input:
                manual_input = st.text_input("Ticker", placeholder="AAPL").upper()
            if manual_input: 
                selected_ticker = manual_input
        else:
            selected_ticker = selection

        if selected_ticker and selected_ticker != "➕ Inserisci Ticker Manuale...":
            if validate_ticker(selected_ticker):
                single_data = get_data([selected_ticker])
                if selected_ticker in single_data:
                    df = single_data[selected_ticker]
                    
                    tl, act, col, pr, rsi, dd, reason, tgt, pot, risk_pr, risk_pot, w30, p30, w60, p60, w90, p90, conf = evaluate_strategy_full(df)
                    
                    k1, k2, k3, k4, k5 = st.columns(5)
                    k1.metric("Prezzo", f"${pr:,.2f}")
                    k2.metric("Target", f"${tgt:,.2f}", delta=f"{pot:.1f}%")
                    k3.metric("Supporto", f"${risk_pr:,.2f}", delta=f"{risk_pot:.1f}%")
                    k4.metric("RSI", f"{rsi:.1f}")
                    k5.metric("🏆 Score", f"{conf}/100")
                    
                    st.plotly_chart(create_modern_chart(df, selected_ticker, tl), use_container_width=True)
                    
                    st.subheader("📊 Backtest Storico")
                    k_w30, k_p30, k_w60, k_p60, k_w90, k_p90 = st.columns(6)
                    k_w30.metric("Win 30G", f"{w30:.0f}%")
                    k_p30.metric("PnL 30G", f"{p30:.1f}%", delta_color="off")
                    k_w60.metric("Win 60G", f"{w60:.0f}%")
                    k_p60.metric("PnL 60G", f"{p60:.1f}%", delta_color="off")
                    k_w90.metric("Win 90G", f"{w90:.0f}%")
                    k_p90.metric("PnL 90G", f"{p90:.1f}%", delta_color="off")
                    
                    st.markdown(f"""
                    <div class="suggestion-box" style="background-color: {col}; border-left: 6px solid #888;">
                        <h2 style="margin:0; color: #222;">💡 {act}
                            <span style="float:right; background:#388e3c; color:white; padding:6px 12px; border-radius:5px;">
                                Score: {conf}/100
                            </span>
                        </h2>
                        <p style="margin-top:10px; font-size:1.1rem;">{reason}</p>
                        <hr style="border-color: rgba(0,0,0,0.1); margin:10px 0;">
                        <div style="display:flex; justify-content:space-between; font-size: 0.95rem;">
                            <span style="color: green;">✅ Target: <b>${tgt:.2f} (+{pot:.1f}%)</b></span>
                            <span style="color: #b30000;">🔻 Rischio: <b>${risk_pr:.2f} ({risk_pot:.1f}%)</b></span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                else: 
                    st.error(f"Impossibile scaricare {selected_ticker}")
            else:
                st.warning(f"Ticker '{selected_ticker}' non valido")


    #  PORTAFOGLIO
    elif page == "💼 Portafoglio":
        c_title, c_btn = st.columns([3, 1])
        with c_title: 
            st.title("💼 Portafoglio")
        with c_btn:
            if st.button("🔄 Aggiorna", use_container_width=True):
                st.cache_data.clear()
                st.rerun()
        
        pf, history_list = db.get_portfolio_summary(user)
        raw_tx = db.get_all_transactions(user)
        
        tickers_current = list(pf.keys())
        tickers_history = list(set([t[1] for t in raw_tx])) if raw_tx else []
        all_tickers = list(set(tickers_current + tickers_history))
        
        with st.spinner("Caricamento dati mercato..."):
            market_data = get_data(all_tickers)
        
        tot_val = 0
        tot_cost = 0
        
        # First buy dates
        first_buy_dates = {}
        if raw_tx:
            for t in raw_tx:
                sym = t[1]
                try: 
                    d = datetime.strptime(str(t[4]), '%Y-%m-%d').date()
                except: 
                    d = date.today()
                if t[5] == 'BUY':
                    if sym not in first_buy_dates or d < first_buy_dates[sym]:
                        first_buy_dates[sym] = d

        # Aggiorna valori live
        for t in tickers_current:
            if t in market_data:
                cur = market_data[t]['Close'].iloc[-1]
                val = pf[t]['qty'] * cur
                
                pf[t]['cur_price'] = cur
                pf[t]['pnl'] = val - pf[t]['total_cost'] 
                pf[t]['pnl_pct'] = (pf[t]['pnl'] / pf[t]['total_cost'] * 100) if pf[t]['total_cost'] > 0 else 0
                
                f_date = first_buy_dates.get(t, date.today())
                pf[t]['days_held'] = (date.today() - f_date).days
                
                tot_val += val
                tot_cost += pf[t]['total_cost']
            
        pnl_tot = tot_val - tot_cost
        pnl_tot_pct = (pnl_tot/tot_cost*100) if tot_cost > 0 else 0

        # METRICHE
        st.markdown("""
        <style>
        div[data-testid="metric-container"] {
            background-color: #ffffff; 
            border: 1px solid #e0e0e0; 
            padding: 12px; 
            border-radius: 10px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }
        </style>""", unsafe_allow_html=True)
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Valore Attuale", f"€{tot_val:,.2f}")
        m2.metric("Utile Netto", f"€{pnl_tot:,.2f}", delta=f"{pnl_tot_pct:.2f}%")
        m3.metric("Capitale Investito", f"€{tot_cost:,.2f}")

        # STRATEGIA OPERATIVA
        st.divider()
        st.subheader("💡 Strategia Operativa")
        
        valid_pf = [(k, v) for k, v in pf.items() if k in market_data]
        sorted_pf = sorted(valid_pf, key=lambda x: x[1]['pnl_pct'])

        if sorted_pf:
            cols_adv = st.columns(3)
            for i, (sym, dat) in enumerate(sorted_pf):
                asset_name = get_asset_name(sym)
                
                # 1. Calcolo Dati Finanziari Personali
                val_attuale = dat['qty'] * dat['cur_price']
                prezzo_carico = dat['avg_price']
                pnl_percent = dat['pnl_pct']
                allocazione = (val_attuale / tot_val * 100) if tot_val > 0 else 0
                days = dat.get('days_held', 0)
                
                # 2. Analisi Tecnica dell'AI
                tit, adv, col_bg = generate_portfolio_advice(market_data[sym], prezzo_carico, dat['cur_price'])
                
                # Recuperiamo i dati tecnici puri
                # tl = Trend Label, pr = Price, dd = Drawdown
                tl, _, _, pr, rsi, dd, _, tgt, pot, risk_pr, risk_pot, _, _, _, _, _, _, conf = evaluate_strategy_full(market_data[sym])
                
                # 3. Calcoli per la Gestione (Management)
                # Calcoliamo quanto dista il prezzo attuale dal supporto tecnico (Stop Loss suggerito)
                distanza_stop = ((risk_pr - pr) / pr) * 100 
                
                # Definiamo lo stato del Trend per chi lo possiede
                trend_icon = "🟢" if "BULLISH" in tl else "🔴"
                trend_text = "Rialzista" if "BULLISH" in tl else "Ribassista"
                
                # Badge Giorni
                time_badge = f"📅 {days} gg"

                with cols_adv[i % 3]:
                    st.markdown(f"""
                        <div class="suggestion-box" style="background-color:{col_bg}; border: 1px solid #bbb; min-height: 350px;">
                            <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom: 10px; border-bottom: 1px solid rgba(0,0,0,0.1); padding-bottom:8px;">
                                <div>
                                    <strong style="font-size:1.1rem;">{sym}</strong>
                                    <div style="font-size:0.75rem; color:#555;">{asset_name}</div> 
                                </div>
                                <div style="text-align:right;">
                                    <span style="color:{'green' if pnl_percent >=0 else 'red'}; font-weight:bold; font-size:1.1rem;">
                                        {pnl_percent:+.2f}%
                                    </span>
                                    <div style="font-size:0.7rem; background:#444; color:white; padding:2px 6px; border-radius:4px; margin-top:2px;">{time_badge}</div>
                                </div>
                            </div>
                            <h3 style="color:#222; margin:5px 0; font-size:1.1rem;">{tit}
                                <span style="float: right; background-color: #388e3c; color: white; padding: 2px 6px; border-radius: 5px; font-size: 0.8rem;">
                                    Score: {conf}
                                </span>
                            </h3>
                            <p style="font-size:0.85rem; margin-bottom: 10px; line-height:1.3; min-height: 40px; color:#333;">{adv}</p>
                            <div style="background-color: rgba(255,255,255,0.6); padding: 8px; border-radius: 6px; border: 1px dashed #777; margin-bottom: 10px;">
                                <div style="font-size: 0.65rem; text-transform: uppercase; color: #555; font-weight: bold; margin-bottom: 4px; text-align:center;">Analisi Tecnica Posizione</div>
                                <div style="display: flex; justify-content: space-between; font-size: 0.8rem; margin-bottom: 4px;">
                                    <span>Trend: <b>{trend_icon} {trend_text}</b></span>
                                    <span>RSI: <b>{rsi:.0f}</b></span>
                                </div>
                                <div style="display: flex; justify-content: space-between; font-size: 0.8rem;">
                                    <span>Dai Massimi: <b style="color:red">{dd:.1f}%</b></span>
                                    <span>Allocazione: <b>{allocazione:.1f}%</b></span>
                                </div>
                            </div>
                            <div style="font-size: 0.75rem; color:#333; padding-top: 5px; border-top: 1px solid rgba(0,0,0,0.1);">
                                <div style="display:flex; justify-content:space-between; margin-bottom: 2px;">
                                    <span>Prezzo Carico: <b>€{prezzo_carico:.2f}</b></span>
                                    <span>Prezzo Attuale: <b>€{dat['cur_price']:.2f}</b></span>
                                </div>
                                <div style="display:flex; justify-content:space-between; font-weight:bold;">
                                    <span style="color: green;">🎯 Target: ${tgt:.0f}</span>
                                    <span style="color: #b71c1c;">🛑 Stop Tecnico: ${risk_pr:.0f} ({distanza_stop:.1f}%)</span>
                                </div>
                            </div>
                        </div>""", unsafe_allow_html=True)
        else:
            st.info("Portafoglio vuoto")

        st.divider()

        # TABS ANALISI
        tab_chart, tab_alloc, tab_tx = st.tabs(["📈 Grafici", "🍰 Allocazione", "📝 Transazioni"])

        with tab_chart:
            if raw_tx:
                with st.spinner("Elaborazione storico..."):
                    df_hist = get_historical_portfolio_value(raw_tx, market_data)
                
                if not df_hist.empty:
                    # Download Excel
                    excel_data = generate_enhanced_excel_report(df_hist, pf, raw_tx)
                    
                    col_dl, _ = st.columns([1, 3])
                    with col_dl:
                        st.download_button(
                            label="📥 Scarica Report Excel",
                            data=excel_data,
                            file_name=f"InvestAI_Report_{date.today()}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True
                        )

                    g1, g2, g3 = st.tabs(["Capitale", "Utili", "Asset"])
                    
                    with g1:
                        fig_hist = go.Figure()
                        fig_hist.add_trace(go.Scatter(
                            x=df_hist.index, y=df_hist['Total Value'], 
                            mode='lines', name='Valore', 
                            line=dict(color='#004d40', width=2), 
                            fill='tozeroy', fillcolor='rgba(0,77,64,0.1)'
                        ))
                        fig_hist.add_trace(go.Scatter(
                            x=df_hist.index, y=df_hist['Total Invested'], 
                            mode='lines', name='Investito', 
                            line=dict(color='#ef5350', width=2, dash='dash')
                        ))
                        fig_hist.update_layout(
                            height=400, hovermode="x unified", 
                            title="Valore vs Investito", template="plotly_white"
                        )
                        st.plotly_chart(fig_hist, use_container_width=True)

                    with g2:
                        df_hist['Net Profit'] = df_hist['Total Value'] - df_hist['Total Invested']
                        colors = ['#66bb6a' if v >= 0 else '#ef5350' for v in df_hist['Net Profit']]
                        fig_pnl = go.Figure()
                        fig_pnl.add_trace(go.Bar(
                            x=df_hist.index, y=df_hist['Net Profit'], 
                            marker_color=colors, name='P&L'
                        ))
                        fig_pnl.update_layout(
                            height=400, title="Guadagno/Perdita Netta (€)", 
                            template="plotly_white", showlegend=False
                        )
                        st.plotly_chart(fig_pnl, use_container_width=True)

                    with g3:
                        fig_stack = go.Figure()
                        cols_asset = [c for c in df_hist.columns if c not in ['Total Value', 'Total Invested', 'Net Profit']]
                        for c in cols_asset:
                            fig_stack.add_trace(go.Scatter(
                                x=df_hist.index, y=df_hist[c], 
                                mode='lines', stackgroup='one', name=c
                            ))
                        fig_stack.update_layout(
                            height=400, title="Composizione nel Tempo", 
                            template="plotly_white"
                        )
                        st.plotly_chart(fig_stack, use_container_width=True)
                else:
                    st.warning("Dati insufficienti")
            else:
                st.info("Nessuna transazione")

        # --- TAB B: ALLOCAZIONE ---
        with tab_alloc:
            if pf:
                c_pie, c_list = st.columns([1, 1.5])
                with c_pie:
                    # FIX: Usiamo .get() per evitare il crash se manca il prezzo
                    pie_data = []
                    for k, v in pf.items():
                        # Se manca cur_price usa avg_price come fallback
                        p = v.get('cur_price', v.get('avg_price', 0.0))
                        val = v['qty'] * p
                        if val > 0:
                            pie_data.append({"Label": k, "Value": val})

                    if pie_data:
                        fig_pie = go.Figure(data=[go.Pie(
                            labels=[x['Label'] for x in pie_data], 
                            values=[x['Value'] for x in pie_data], 
                            hole=.4
                        )])
                        fig_pie.update_layout(margin=dict(t=0,b=0,l=0,r=0), height=300, showlegend=False)
                        st.plotly_chart(fig_pie, use_container_width=True)
                
                with c_list:
                    alloc_data = []
                    for k,v in pf.items():
                        f_date = first_buy_dates.get(k, "N/A")
                        # FIX: Anche qui usiamo .get()
                        p = v.get('cur_price', v.get('avg_price', 0.0))
                        
                        alloc_data.append({
                            "Asset": k,
                            "Valore": v['qty'] * p,
                            "Costo": v['total_cost'],
                            "P&L %": v.get('pnl_pct', 0.0) / 100, 
                            "Data 1° Acq": f_date
                        })
                    
                    df_alloc = pd.DataFrame(alloc_data).sort_values("Valore", ascending=False)
                    st.dataframe(df_alloc, hide_index=True, use_container_width=True,
                        column_config={
                            "Valore": st.column_config.NumberColumn(format="€%.2f"),
                            "Costo": st.column_config.NumberColumn(format="€%.2f"),
                            "P&L %": st.column_config.NumberColumn(format="%.2f%%"),
                            "Data 1° Acq": st.column_config.DateColumn(format="DD/MM/YYYY")
                        }
                    )
            else:
                st.info("Portafoglio vuoto")

        with tab_tx:
            st.subheader("Gestione Transazioni")
            st.info("💡 Modifica celle e premi Salva. Spunta 'Elimina' per cancellare.")
            
            with st.expander("➕ Aggiungi Transazione"):
                with st.form("add_tx_form"):
                    c1, c2, c3, c4, c5 = st.columns(5)
                    n_sym = c1.text_input("Ticker", placeholder="AAPL").upper()
                    n_qty = c2.number_input("Qta", min_value=0.0001, format="%.4f")
                    n_prc = c3.number_input("Prezzo", min_value=0.01)
                    n_date = c4.date_input("Data", date.today())
                    n_type = c5.selectbox("Tipo", ["BUY", "SELL"])
                    if st.form_submit_button("Aggiungi", type="primary"):
                        if validate_ticker(n_sym): 
                            db.add_transaction(user, n_sym, n_qty, n_prc, str(n_date), n_type, 0.0)
                            st.cache_data.clear()
                            st.rerun()
                        else: 
                            st.error("Ticker invalido")

            if raw_tx:
                df_editor = pd.DataFrame(raw_tx, columns=['ID', 'Ticker', 'Qta', 'Prezzo', 'Data', 'Tipo', 'Fee'])
                df_editor['Data'] = pd.to_datetime(df_editor['Data']).dt.date
                df_editor['Elimina'] = False 
                
                edited_df = st.data_editor(
                    df_editor,
                    column_config={
                        "ID": st.column_config.NumberColumn(disabled=True),
                        "Elimina": st.column_config.CheckboxColumn(default=False),
                        "Data": st.column_config.DateColumn(format="DD/MM/YYYY"),
                        "Prezzo": st.column_config.NumberColumn(format="€%.2f"),
                        "Fee": st.column_config.NumberColumn(format="€%.2f"),
                        "Tipo": st.column_config.SelectboxColumn(options=["BUY", "SELL"])
                    },
                    hide_index=True,
                    use_container_width=True,
                    num_rows="fixed" 
                )
                
                if st.button("💾 Salva Modifiche", type="primary"):
                    rows_to_delete = edited_df[edited_df['Elimina'] == True]
                    for index, row in rows_to_delete.iterrows():
                        db.delete_transaction(row['ID'])
                    
                    rows_to_update = edited_df[edited_df['Elimina'] == False]
                    for index, row in rows_to_update.iterrows():
                        db.update_transaction(
                            row['ID'], row['Ticker'], row['Qta'], 
                            row['Prezzo'], str(row['Data']), row['Tipo'], row['Fee']
                        )
                    
                    st.success("Salvato!")
                    st.cache_data.clear()
                    time.sleep(1)
                    st.rerun()
            else:
                st.info("Nessuna transazione")

    # CONSIGLI
    elif page == "💡 Consigli":
        st.title("💡 AI Advisor")
        st.markdown("Analisi completa portafoglio e nuove opportunità.")

        if st.button("🔄 Analizza", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        with st.spinner("Analisi in corso..."):
            pf, _ = db.get_portfolio_summary(user)
            owned_tickers = list(pf.keys())
            
            all_tickers = list(set(owned_tickers + AUTO_SCAN_TICKERS))
            market_data = get_data(all_tickers)

            actions_sell = []
            actions_buy_more = []
            actions_hold = []
            actions_new_entry = []
            missing_tickers = []

            # ANALISI PORTAFOGLIO
            for t in owned_tickers:
                if t in market_data:
                    dat = pf[t]
                    cur_price = market_data[t]['Close'].iloc[-1]
                    
                    val_pos = dat['qty'] * cur_price
                    pnl_val = val_pos - dat['total_cost']
                    dat['pnl_pct'] = (pnl_val / dat['total_cost'] * 100) if dat['total_cost'] > 0 else 0
                    
                    tit, adv, col = generate_portfolio_advice(market_data[t], dat['avg_price'], cur_price)
                    
                    # FIX: Recupera TUTTI i dati tecnici
                    _, _, _, _, _, _, _, tgt, pot, risk_pr, risk_pot, w30, p30, w60, p60, w90, p90, conf = evaluate_strategy_full(market_data[t])
                    
                    item = {
                        "ticker": t, "title": tit, "desc": adv, "color": col, 
                        "pnl": dat['pnl_pct'], "price": cur_price,
                        "target": tgt, "potential": pot, "risk": risk_pr, "risk_pot": risk_pot,
                        "w30": w30, "p30": p30, "w60": w60, "p60": p60, "w90": w90, "p90": p90,
                        "confidence": conf
                    }
                    
                    if any(k in tit for k in ["VENDI", "INCASSA", "PROTEGGI", "VALUTA VENDITA", "STOP"]):
                        actions_sell.append(item)
                    elif any(k in tit for k in ["ACQUISTA", "MEDIA", "ACCUMULO", "PAC"]):
                        actions_buy_more.append(item)
                    else:
                        if "MOONBAG" in tit: 
                            item['color'] = "#e8f5e9"
                            item['border'] = "2px solid #4caf50"
                        elif "TREND SANO" in tit:
                            item['color'] = "#f1f8e9"
                            item['border'] = "1px solid #8bc34a"
                        else:
                            item['color'] = "#f5f5f5"
                            item['border'] = "1px solid #ccc"
                        actions_hold.append(item)
                else:
                    missing_tickers.append(t)

            # NUOVE OPPORTUNITÀ
            for t in AUTO_SCAN_TICKERS:
                if t not in owned_tickers and t in market_data:
                    _, act, col, pr, rsi, dd, res, tgt, pot, r_pr, r_pot, w30, p30, w60, p60, w90, p90, conf = evaluate_strategy_full(market_data[t])
                    
                    if "ACQUISTA" in act or "ORO" in act:
                        actions_new_entry.append({
                            "ticker": t, "title": act, "desc": res, 
                            "color": col, "price": pr, "rsi": rsi,
                            "target": tgt, "potential": pot,
                            "risk": r_pr, "risk_pot": r_pot,
                            "w30": w30, "p30": p30, "w60": w60, 
                            "p60": p60, "w90": w90, "p90": p90,
                            "confidence": conf
                        })

            # VISUALIZZAZIONE
            c1, c2, c3 = st.columns(3)
            c1.metric("Azioni Urgenti", len(actions_sell) + len(actions_buy_more))
            c2.metric("In Holding", len(actions_hold))
            c3.metric("Nuove Opportunità", len(actions_new_entry))
            st.divider()

            if missing_tickers:
                st.warning(f"⚠️ Dati mancanti: {', '.join(missing_tickers)}")

            # URGENZE
            if actions_sell:
                st.subheader("🔴 Richiedono Azione")
                cols = st.columns(3)
                for i, item in enumerate(actions_sell):
                    asset_name = get_asset_name(item['ticker'])
                    with cols[i%3]: 
                        st.markdown(f"""
                        <div class="suggestion-box" style="background-color:{item['color']}; border: 2px solid #d32f2f;">
                            <div style="display:flex; justify-content:space-between;">
                                <div>
                                    <h4 style="margin:0;">{item['ticker']}</h4>
                                    <div style="font-size:0.75rem; color:#666;">{asset_name}</div>
                                </div>
                                <span style="font-weight:bold; color:#d32f2f;">{item['pnl']:.1f}%</span>
                            </div>
                            <h3 style="color:#b71c1c; margin:8px 0; font-size:1rem;">
                                {item['title']}
                                <span style="float:right; background:#d32f2f; color:white; padding:3px 7px; border-radius:5px; font-size:0.85rem;">
                                    🎯 {item['confidence']}
                                </span>
                            </h3>
                            <p style="font-size:0.85rem; margin-bottom:6px;">{item['desc']}</p>
                            <hr style="margin:6px 0; opacity:0.3;">
                            <div style="font-size:0.75rem;">
                                <div style="display:flex; justify-content:space-between;">
                                    <span>Target: <b>${item['target']:.2f}</b></span>
                                    <span>Risk: <b>{item['risk_pot']:.1f}%</b></span>
                                </div>
                            </div>
                        </div>""", unsafe_allow_html=True)
                st.divider()

            # ACCUMULO
            if actions_buy_more:
                st.subheader("🟢 Occasioni di Accumulo")
                cols = st.columns(3)
                for i, item in enumerate(actions_buy_more):
                    asset_name = get_asset_name(item['ticker'])
                    with cols[i%3]: 
                        st.markdown(f"""
                        <div class="suggestion-box" style="background-color:{item['color']}; border: 2px solid #2e7d32;">
                            <div style="display:flex; justify-content:space-between;">
                                <div>
                                    <h4 style="margin:0;">{item['ticker']}</h4>
                                    <div style="font-size:0.75rem; color:#666;">{asset_name}</div>
                                </div>
                                <span style="font-weight:bold; color:#2e7d32;">{item['pnl']:.1f}%</span>
                            </div>
                            <h3 style="color:#1b5e20; margin:8px 0; font-size:1rem;">
                                {item['title']}
                                <span style="float:right; background:#2e7d32; color:white; padding:3px 7px; border-radius:5px; font-size:0.85rem;">
                                    🎯 {item['confidence']}
                                </span>
                            </h3>
                            <p style="font-size:0.85rem; margin-bottom:6px;">{item['desc']}</p>
                            <hr style="margin:6px 0; opacity:0.3;">
                            <div style="font-size:0.75rem;">
                                <div style="display:flex; justify-content:space-between;">
                                    <span>Target: <b>${item['target']:.2f}</b></span>
                                    <span style="color:green;">Pot: <b>+{item['potential']:.1f}%</b></span>
                                </div>
                            </div>
                        </div>""", unsafe_allow_html=True)
                st.divider()

            # HOLDING
            if actions_hold:
                st.subheader("🔵 Mantenimento & Monitoraggio")
                cols = st.columns(3)
                for i, item in enumerate(actions_hold):
                    asset_name = get_asset_name(item['ticker'])
                    text_color = "#2e7d32" if "MOONBAG" in item['title'] else ("#f57f17" if "ATTENZIONE" in item['title'] else "#333")
                    pnl_color = "green" if item['pnl'] >= 0 else "red"

                    with cols[i%3]: 
                        st.markdown(f"""
                        <div class="suggestion-box" style="background-color:{item['color']}; border: {item.get('border', '1px solid #ccc')};">
                            <div style="display:flex; justify-content:space-between;">
                                <div>
                                    <h4 style="margin:0;">{item['ticker']}</h4>
                                    <div style="font-size:0.75rem; color:#666;">{asset_name}</div>
                                </div>
                                <span style="font-weight:bold; color:{pnl_color};">{item['pnl']:.1f}%</span>
                            </div>
                            <h3 style="color:{text_color}; margin:8px 0; font-size:1rem;">
                                {item['title']}
                                <span style="float:right; background:#757575; color:white; padding:3px 7px; border-radius:5px; font-size:0.85rem;">
                                    🎯 {item['confidence']}
                                </span>
                            </h3>
                            <p style="font-size:0.85rem; color:#555; margin-bottom:6px;">{item['desc']}</p>
                            <div style="text-align:right; font-size:0.75rem; margin-top:6px;">
                                Prezzo: ${item['price']:.2f}
                            </div>
                        </div>""", unsafe_allow_html=True)
                st.divider()

            # NUOVE OPPORTUNITÀ
            if actions_new_entry:
                st.subheader("🚀 Nuove Opportunità")
                cols = st.columns(3)
                for i, item in enumerate(actions_new_entry):
                    asset_name = get_asset_name(item['ticker'])
                    border = "3px solid #FFD700" if "ORO" in item['title'] else "1px solid #8bc34a"
                    
                    with cols[i%3]: 
                        st.markdown(f"""
                        <div class="suggestion-box" style="background-color:{item['color']}; border: {border};">
                            <div style="display:flex; justify-content:space-between;">
                                <div>
                                    <h4 style="margin:0;">{item['ticker']}</h4>
                                    <div style="font-size:0.75rem; color:#666;">{asset_name}</div>
                                </div>
                                <span style="font-weight:bold; color:#006400;">+{item['potential']:.1f}%</span>
                            </div>
                            <h3 style="color:#004d40; margin:8px 0; font-size:1rem;">
                                {item['title']}
                                <span style="float:right; background:#388e3c; color:white; padding:3px 7px; border-radius:5px; font-size:0.85rem;">
                                    🎯 {item['confidence']}
                                </span>
                            </h3>
                            <p style="font-size:0.85rem; margin-bottom:6px;">{item['desc']}</p>
                            <hr style="margin:6px 0; opacity:0.3;">
                            <div style="font-size:0.75rem;">
                                <strong>Storico:</strong>
                                <div style="display:flex; justify-content:space-between; margin-top:3px;">
                                    <span>30G: {item['w30']:.0f}% <span style="color:{'green' if item['p30']>=0 else 'red'};">({item['p30']:.1f}%)</span></span>
                                    <span>90G: {item['w90']:.0f}% <span style="color:{'green' if item['p90']>=0 else 'red'};">({item['p90']:.1f}%)</span></span>
                                </div>
                            </div>
                            <hr style="margin:6px 0; opacity:0.3;">
                            <div style="display:flex; justify-content:space-between; font-size:0.75rem;">
                                <span>Target: <b>${item['target']:.2f}</b></span>
                                <span style="color:#b71c1c;">Risk: <b>{item['risk_pot']:.1f}%</b></span>
                            </div>
                        </div>""", unsafe_allow_html=True)

            if not (actions_sell or actions_buy_more or actions_hold or actions_new_entry):
                st.info("Nessun dato disponibile")

    # IMPOSTAZIONI
    elif page == "⚙️ Impostazioni":
        st.title("⚙️ Impostazioni")
        
        tab_tg, tab_sec = st.tabs(["🔔 Notifiche", "🔒 Sicurezza"])
        
        with tab_tg:
            st.info("Configura Telegram per ricevere consigli automatici ogni mattina.")
            with st.container(border=True):
                st.subheader("Configurazione Telegram")
                current_id = db.get_user_chat_id(user)
                chat_id_input = st.text_input(
                    "Telegram Chat ID", 
                    value=current_id, 
                    help="Cerca @userinfobot su Telegram"
                )
                if st.button("💾 Salva ID", type="primary"):
                    if chat_id_input:
                        if db.save_chat_id(user, chat_id_input): 
                            st.success("Salvato! Il bot ti invierà aggiornamenti.")
                        else: 
                            st.error("Errore nel salvataggio")
                    else: 
                        st.warning("Inserisci un ID valido")
                
                st.markdown("""
                **Come ottenere il tuo Chat ID:**
                1. Apri Telegram
                2. Cerca **@userinfobot** e avvialo
                3. Copia il numero sotto 'Id'
                4. **IMPORTANTE:** Cerca **InvestAI Bot** e premi AVVIA
                """)

        with tab_sec:
            st.warning("Modifica la password di accesso.")
            with st.container(border=True):
                st.subheader("Cambio Password")
                with st.form("change_pass_form"):
                    p1 = st.text_input("Nuova Password", type="password")
                    p2 = st.text_input("Conferma Password", type="password")
                    if st.form_submit_button("Aggiorna Password"):
                        if p1 and p2:
                            if p1 == p2:
                                if db.change_password(user, p1):
                                    st.success("Password aggiornata! Effettua il login.")
                                    time.sleep(2)
                                    st.session_state.user = None
                                    st.rerun()
                                else:
                                    st.error("Errore durante l'aggiornamento")
                            else:
                                st.error("Le password non coincidono")
                        else:
                            st.warning("Inserisci la nuova password")

if __name__ == "__main__":
    main()







