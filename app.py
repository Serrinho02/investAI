import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date, datetime
import pandas as pd
import threading
import time

# IMPORTIAMO IL CERVELLO CONDIVISO
from logic import DBManager, get_data_raw, evaluate_strategy_full, generate_portfolio_advice, AUTO_SCAN_TICKERS, POPULAR_ASSETS, validate_ticker
from bot import run_scheduler, bot 

# --- 1. CONFIGURAZIONE (DEVE ESSERE LA PRIMA RIGA) ---
st.set_page_config(page_title="InvestAI", layout="wide", page_icon="💎")

# --- 2. AVVIO BOT IN BACKGROUND (SINGLETON PROTETTO) ---
@st.cache_resource
def start_bot_singleton():
    # 1. Thread per lo scheduler
    t_sched = threading.Thread(target=run_scheduler, daemon=True)
    t_sched.start()
    
    # 2. Thread per ascoltare i comandi Telegram
    def start_bot_polling():
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Errore polling bot: {e}")
            pass
            
    t_bot = threading.Thread(target=start_bot_polling, daemon=True)
    t_bot.start()
    print("🤖 Bot Telegram avviato in modalità Singleton!")
    return True

start_bot_singleton()

# --- 3. STILI CSS COMPLETI ---
st.markdown("""
<style>
    /* 1. NASCONDI ELEMENTI STANDARD */
    #MainMenu {visibility: hidden;}
    .stDeployButton {display: none;}
    footer {visibility: hidden;}
    header { background: transparent !important; }

    /* 2. CARD STYLES */
    .suggestion-box { 
        padding: 15px; 
        border-radius: 12px; 
        border-left: 5px solid; 
        margin-bottom: 15px; 
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }

    /* 3. MOBILE OPTIMIZATIONS */
    @media (max-width: 768px) {
        /* Forza le metriche su una riga se ci stanno, o a capo ordinatamente */
        [data-testid="stMetric"] {
            background-color: #f9f9f9;
            padding: 10px;
            border-radius: 8px;
            margin-bottom: 5px;
            text-align: center;
        }
        
        /* Tabelle più leggibili su mobile */
        [data-testid="stDataFrame"] { font-size: 0.8rem; }
        
        /* I grafici prendono tutto lo spazio */
        .js-plotly-plot { width: 100% !important; }
        
        /* Titoli più piccoli su mobile */
        h1 { font-size: 1.8rem !important; }
        h2 { font-size: 1.5rem !important; }
        h3 { font-size: 1.2rem !important; }
    }
</style>
""", unsafe_allow_html=True)

db = DBManager()

# --- NUOVA FUNZIONE: DIALOGO CONFERMA ELIMINAZIONE ---
@st.dialog("⚠️ Conferma Eliminazione")
def confirm_delete_dialog(tx_id):
    st.write("Sei sicuro di voler eliminare questa transazione?")
    st.warning("Questa operazione è irreversibile e i dati verranno persi per sempre.")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Sì, Elimina", type="primary", width="stretch"):
            db.delete_transaction(tx_id)
            st.cache_data.clear()
            st.rerun()
    with col2:
        if st.button("Annulla", width="stretch"):
            st.rerun()

# --- WRAPPER CACHE PER IL SITO (Per velocità) ---
@st.cache_data(ttl=600)
def get_data(tickers):
    return get_data_raw(tickers)

# --- GRAFICI UI (Esclusivi del sito, copia esatta stile all-in-one) ---
def create_modern_chart(df, ticker, trend_label):
    df_plot = df.tail(int(365 * 1.5)).copy()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name='Prezzo', increasing_line_color='#26a69a', decreasing_line_color='#ef5350'), row=1, col=1)
    if 'SMA_200' in df_plot.columns:
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['SMA_200'], marker_color='#FFD700', name='SMA 200', line=dict(width=2)), row=1, col=1)
    
    colors_volume = ['#ef5350' if c < o else '#26a69a' for o, c in zip(df_plot['Open'], df_plot['Close'])]
    fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Volume'], name='Volume', marker_color=colors_volume, opacity=0.5), row=2, col=1)
    
    bg_color = "rgba(0, 50, 0, 0.05)" if "BULLISH" in trend_label else "rgba(50, 0, 0, 0.05)"
    fig.update_layout(title=dict(text=f"Analisi: <b>{ticker}</b>", font=dict(size=20)), template="plotly_dark", height=500, margin=dict(l=20, r=20, t=60, b=20), showlegend=False, plot_bgcolor=bg_color, xaxis_rangeslider_visible=False)
    return fig

# --- HELPER PER NOMI ASSET ---
def get_asset_name(ticker):
    # 1. Cerca nella nostra lista predefinita (Invertiamo il dizionario per cercare per valore)
    # POPULAR_ASSETS è {Nome: Ticker}, noi vogliamo Ticker -> Nome
    reversed_assets = {v: k for k, v in POPULAR_ASSETS.items()}
    if ticker in reversed_assets:
        return reversed_assets[ticker]
    
    # 2. Se non trovato, proviamo a scaricarlo (cache) o ritorniamo il ticker stesso
    # Per semplicità e velocità, ritorniamo il ticker se non è nella lista popolare
    return ticker

# --- MAIN APP ---
def main():
    if 'user' not in st.session_state: st.session_state.user = None
    if 'edit_tx_id' not in st.session_state: st.session_state.edit_tx_id = None
    
    if not st.session_state.user:
        c1, c2, c3 = st.columns([1,2,1])
        with c2:
            st.title("💎 InvestAI")
            tab1, tab2 = st.tabs(["Accedi", "Registrati"])
            with tab1:
                u = st.text_input("Username", key="l_u")
                p = st.text_input("Password", type="password", key="l_p")
                if st.button("Login", type="primary", width="stretch"):
                    if db.login_user(u, p): st.session_state.user = u; st.rerun()
                    else: st.error("Errore credenziali")
            with tab2:
                nu = st.text_input("Nuovo Username", key="r_u")
                np = st.text_input("Nuova Password", type="password", key="r_p")
                if st.button("Crea Account", width="stretch"):
                    if db.register_user(nu, np): st.success("Creato! Accedi."); 
                    else: st.error("Utente esistente")
        return

    user = st.session_state.user
    with st.sidebar:
        # --- 1. PROFILO UTENTE (STILE CARD) ---
        st.markdown(f"""
        <div style="background-color: #f0f2f6; padding: 15px; border-radius: 12px; margin-bottom: 20px; text-align: center; border: 1px solid #e0e0e0;">
            <div style="font-size: 3rem; margin-bottom: 5px;">👤</div>
            <h3 style="margin:0; color:#004d40; font-family: sans-serif;">{user}</h3>
        </div>
        """, unsafe_allow_html=True)
        
        # --- 2. MENU DI NAVIGAZIONE ---
        st.markdown("### 🧭 Navigazione")
        page = st.radio(
            "Vai a:", 
            ["📊 Analisi Mercato", "💼 Portafoglio", "💡 Consigli", "⚙️ Impostazioni"], 
            label_visibility="collapsed"
        )
        
        # Spaziatore elastico (HTML vuoto) per spingere il contenuto in basso
        st.markdown("<div style='height: 30px;'></div>", unsafe_allow_html=True)
        st.divider()
        
        # --- 3. STATO SISTEMA (MINIMAL) ---
        with st.container():
            if db.db_url == "SUPABASE_API_CONNECTION_ACTIVE":
                st.markdown("☁️**Database:** <span style='color:green;'>Connesso</span>", unsafe_allow_html=True)
            else:
                st.markdown("**Database:** <span style='color:red;'>Errore</span>", unsafe_allow_html=True)
        
        st.divider()

        # --- 4. LOGOUT ---
        if st.button("🚪 Esci dal Profilo", type="primary", width="stretch"):
            st.session_state.user = None
            st.rerun()
            
        # Footer piccolo
        st.markdown("<div style='text-align: center; font-size: 0.7rem; color: #888; margin-top: 20px;'>InvestAI • created by Nicola Serra</div>", unsafe_allow_html=True)
        st.markdown("<div style='text-align: center; font-size: 0.7rem; color: #888; margin-top: 20px;'>© 2025  · All rights reserved</div>", unsafe_allow_html=True)

    # --- 1. DASHBOARD ANALISI MERCATO ---
    if page == "📊 Analisi Mercato":
        st.title("Analisi Mercato")

        with st.expander("ℹ️ Legenda Strategica e Segnali Tecnici", expanded=False):
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


        with st.expander("🤖 L'App Consiglia (Segnali Operativi)", expanded=True):
            if st.button("🔎 Scansiona Tutto il Mercato", width="stretch"):
                with st.spinner("L'AI sta analizzando tutti gli asset in cerca di occasioni..."):
                    auto_data = get_data(AUTO_SCAN_TICKERS)
                    opportunities = []
                    golden_found = False
                    
                    for t in AUTO_SCAN_TICKERS:
                        if t in auto_data:
                            # 17 Valori
                            tl, act, col, pr, rsi, dd, reason, tgt, pot, risk_pr, risk_pot, w30, p30, w60, p60, w90, p90, conf = evaluate_strategy_full(auto_data[t])
                            
                            if "ACQUISTA" in act or "VENDI" in act or "RISCHIOSO" in act or "ORO" in act:
                                priority = 0
                                if "ORO" in act: 
                                    priority = 3
                                    golden_found = True
                                elif "ACQUISTA" in act: priority = 2
                                elif "VENDI" in act: priority = 1
                                
                                opportunities.append({
                                    "ticker": t, "trend": tl, "action": act, 
                                    "color": col, "price": pr, "rsi": rsi, 
                                    "drawdown": dd, "reason": reason,
                                    "priority": priority,
                                    "target": tgt,      
                                    "potential": pot,
                                    "risk": risk_pr,
                                    "risk_pot": risk_pot,
                                    "w30": w30, "p30": p30, "w60": w60, "p60": p60, "w90": w90, "p90": p90,
                                    "confidence": conf
                                })
                    
                    if opportunities:
                        opportunities = sorted(opportunities, key=lambda x: x['priority'], reverse=True)

                        if golden_found:
                            st.balloons()
                            st.success("💎 TROVATA UN'OPPORTUNITÀ D'ORO! PRESTARE MASSIMA ATTENZIONE.")

                        cols_rec = st.columns(3)
                        for idx, opp in enumerate(opportunities):
                            border_style = "border: 2px solid #FFD700; box-shadow: 0 0 5px #FFD700;" if "ORO" in opp['action'] else "border: 1px solid #8bc34a;"
                            pot_color = "#006400" if opp['potential'] > 0 else "#8b0000"
                            pot_str = f"+{opp['potential']:.1f}%"
                            
                            # Recupera nome completo
                            asset_name = get_asset_name(opp['ticker'])
                            
                            with cols_rec[idx % 3]: 
                                st.markdown(f"""
                                <div class="suggestion-box" style="background-color:{opp['color']}; {border_style}">
                                    <div style="display:flex; justify-content:space-between;">
                                        <div>
                                            <h4 style="margin:0;">{opp['ticker']}</h4>
                                            <div style="font-size:0.75rem; color:#666; margin-bottom:4px;">{asset_name}</div>
                                        </div>
                                        <span style="font-weight:bold; color:{pot_color};">{pot_str}</span>
                                    </div>
                                    <h3 style="color:#222; margin:5px 0;">{opp['action']} 
                                        <span style="float: right; background-color: #388e3c; color: white; padding: 4px 8px; border-radius: 5px; font-size: 1.1rem;">
                                            🎯 {opp['confidence']}/100
                                        </span>
                                    </h3>
                                    <p style="font-size:0.9rem;">{opp['reason']}</p> 
                                    <div style="margin-top:10px; border-top: 1px dashed rgba(0,0,0,0.3); padding-top:5px; font-size:0.8rem; color:#555;">
                                        <strong style="color:#000; font-size: 0.9rem;">Probabilità Storica (Buy Signal):</strong>
                                        <div style="display:flex; justify-content:space-between; margin-top: 5px;">
                                            <span style="font-weight:bold;">30G: {opp['w30']:.0f}% <span style="color:{'green' if opp['p30']>=0 else 'red'};">({opp['p30']:.1f}%)</span></span>
                                            <span style="font-weight:bold;">60G: {opp['w60']:.0f}% <span style="color:{'green' if opp['p60']>=0 else 'red'};">({opp['p60']:.1f}%)</span></span>
                                            <span style="font-weight:bold;">90G: {opp['w90']:.0f}% <span style="color:{'green' if opp['p90']>=0 else 'red'};">({opp['p90']:.1f}%)</span></span>
                                        </div>
                                        <div style="text-align: right; font-size: 0.7rem; color: #777;">(Win Rate % / PnL Medio %)</div>
                                    </div>
                                    <div style="margin-top:8px; border-top: 1px solid rgba(0,0,0,0.1); padding-top:5px;">
                                        <div style="display:flex; justify-content:space-between; font-size:0.85rem;">
                                            <span>Target: <b>${opp['target']:.2f}</b></span>
                                            <span style="color:#b71c1c;">Risk: <b>{opp['risk_pot']:.1f}%</b></span>
                                        </div>
                                        <div style="text-align:right; font-size:0.8rem; margin-top:4px; color:#555;">
                                            Prezzo: ${opp['price']:.2f} | RSI: {opp['rsi']:.0f}
                                        </div>
                                    </div>
                                </div>
                                """, unsafe_allow_html=True)
                    else:
                        st.info("Al momento il mercato è piatto. Nessun segnale forte rilevato.")

        st.divider()
        st.subheader("🔎 Analisi Approfondita Singolo Asset")
        
        popular_tickers = list(POPULAR_ASSETS.values())
        all_options = sorted(list(set(popular_tickers)))
        all_options.insert(0, "➕ Cerca/Inserisci Ticker Manuale...")

        c_sel, c_input = st.columns([3, 1])
        with c_sel:
            selection = st.selectbox("Seleziona Asset (Popolari o Cerca)", all_options)
        
        selected_ticker = None
        if selection == "➕ Cerca/Inserisci Ticker Manuale...":
            with c_input:
                manual_input = st.text_input("Scrivi Ticker", placeholder="Es. KO, NFLX").upper()
            if manual_input: selected_ticker = manual_input
        else:
            selected_ticker = selection

        if selected_ticker:
            if validate_ticker(selected_ticker):
                single_asset_data = get_data([selected_ticker])
                if selected_ticker in single_asset_data:
                    df = single_asset_data[selected_ticker]
                    
                    tl, act, col, pr, rsi, dd, reason, tgt, pot, risk_pr, risk_pot, w30, p30, w60, p60, w90, p90, conf = evaluate_strategy_full(df)
                    
                    k1, k2, k3, k4 = st.columns(4)
                    k1.metric("Prezzo", f"${pr:,.2f}")
                    k2.metric("Target (Upside)", f"${tgt:,.2f}", delta=f"{pot:.1f}%")
                    k3.metric("Supporto (Rischio)", f"${risk_pr:,.2f}", delta=f"{risk_pot:.1f}%", delta_color="normal")
                    k4.metric("RSI", f"{rsi:.1f}")
                    st.metric("🏆 Confidence Score", f"{conf}/100")
                    
                    st.plotly_chart(create_modern_chart(df, selected_ticker, tl))

                    # Aggiungi un riquadro per i risultati storici
                    st.subheader("Storico del Segnale di Acquisto") # AGGIUNTO
                
                    k_w30, k_p30, k_w60, k_p60, k_w90, k_p90 = st.columns(6) # AGGIUNTO
                    k_w30.metric("Win Rate 30d", f"{w30:.0f}%") # AGGIUNTO
                    k_p30.metric("PnL Medio 30d", f"{p30:.1f}%", delta_color="off") # AGGIUNTO
                    k_w60.metric("Win Rate 60d", f"{w60:.0f}%") # AGGIUNTO
                    k_p60.metric("PnL Medio 60d", f"{p60:.1f}%", delta_color="off") # AGGIUNTO
                    k_w90.metric("Win Rate 90d", f"{w90:.0f}%") # AGGIUNTO
                    k_p90.metric("PnL Medio 90d", f"{p90:.1f}%", delta_color="off") # AGGIUNTO
                    
                    st.markdown(f"""
                    <div class="suggestion-box" style="background-color: {col}; border-left: 6px solid #bbb;">
                        <h2 style="margin:0; color: #222;">💡 {act} 
                            <span style="float: right; background-color: #388e3c; color: white; padding: 4px 8px; border-radius: 5px; font-size: 1.1rem;">
                                Score: {conf}/100
                            </span>
                        </h2>
                        <p style="margin-top:10px; font-size:1.1rem;">{reason}</p>
                        <hr style="border-color: rgba(0,0,0,0.1);">
                        <div style="display:flex; justify-content:space-between; font-size: 0.9rem;">
                            <span style="color: green;">✅ Target: <b>${tgt:.2f} (+{pot:.1f}%)</b></span>
                            <span style="color: #b30000;">🔻 Rischio: <b>${risk_pr:.2f} ({risk_pot:.1f}%)</b></span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                else: st.error(f"Impossibile scaricare i dati per {selected_ticker}.")
            else:
                if selected_ticker != "➕ Cerca/Inserisci Ticker Manuale...": st.warning(f"Ticker '{selected_ticker}' non trovato.")

# --- 2. PORTAFOGLIO ---
    elif page == "💼 Portafoglio":
        # Importa la nuova funzione Excel
        from logic import get_historical_portfolio_value, generate_enhanced_excel_report, evaluate_strategy_full, generate_portfolio_advice
        import numpy as np
        
        c_title, c_btn = st.columns([3, 1])
        with c_title: st.title("Gestione Portafoglio")
        with c_btn:
            # FIX: Il pulsante ora forza la pulizia della cache e mostra uno spinner
            if st.button("🔄 Aggiorna Dati", width="stretch"):
                with st.spinner("Scaricamento nuovi dati di mercato..."):
                    st.cache_data.clear()
                    time.sleep(1) # Piccolo delay per assicurare il reset
                    st.rerun()
        
        # Recupera dati dal DB
        pf, history_list = db.get_portfolio_summary(user)
        raw_tx = db.get_all_transactions(user)
        
        # --- PREPARAZIONE DATI ---
        tickers_current = list(pf.keys())
        tickers_history = list(set([t[1] for t in raw_tx])) if raw_tx else []
        all_tickers = list(set(tickers_current + tickers_history))
        
        market_data = get_data(all_tickers)
        
        tot_val = 0
        tot_cost = 0
        pie_data = []
        
        # Calcolo First Buy Date
        first_buy_dates = {}
        if raw_tx:
            for t in raw_tx:
                sym = t[1]
                try: d = datetime.strptime(str(t[4]), '%Y-%m-%d').date()
                except: d = date.today()
                if t[5] == 'BUY':
                    if sym not in first_buy_dates or d < first_buy_dates[sym]:
                        first_buy_dates[sym] = d

        # Aggiornamento valori live
        for t in tickers_current:
            cur = market_data[t]['Close'].iloc[-1] if t in market_data else pf[t]['avg_price']
            val = pf[t]['qty'] * cur
            
            pf[t]['cur_price'] = cur
            pf[t]['pnl'] = val - pf[t]['total_cost'] 
            pf[t]['pnl_pct'] = (pf[t]['pnl'] / pf[t]['total_cost'] * 100) if pf[t]['total_cost'] > 0 else 0
            
            f_date = first_buy_dates.get(t, date.today())
            pf[t]['days_held'] = (date.today() - f_date).days
            
            tot_val += val
            tot_cost += pf[t]['total_cost']
            pie_data.append({"Label": t, "Value": val})
            
        pnl_tot = tot_val - tot_cost
        pnl_tot_pct = (pnl_tot/tot_cost*100) if tot_cost > 0 else 0

        # --- METRICHE ---
        with st.container():
            st.markdown("""
            <style>
            div[data-testid="metric-container"] {
                background-color: #ffffff; border: 1px solid #e0e0e0; padding: 10px; border-radius: 10px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            }
            </style>""", unsafe_allow_html=True)
            
            m1, m2, m3 = st.columns(3)
            m1.metric("Valore Attuale", f"€{tot_val:,.2f}")
            m2.metric("Utile Netto", f"€{pnl_tot:,.2f}", delta=f"{pnl_tot_pct:.2f}%")
            m3.metric("Capitale Investito", f"€{tot_cost:,.2f}")

        # --- STRATEGIA OPERATIVA ---
        st.divider()
        st.subheader("💡 Strategia Operativa")
        
        valid_pf = [item for item in pf.items() if item[0] in market_data]
        sorted_pf = sorted(valid_pf, key=lambda x: x[1]['pnl_pct'])

        if sorted_pf:
            cols_adv = st.columns(3)
            for i, (sym, dat) in enumerate(sorted_pf):
                asset_name = get_asset_name(sym)
                tit, adv, col = generate_portfolio_advice(market_data[sym], dat['avg_price'], dat['cur_price'])
                _, _, _, _, _, _, _, tgt, pot, risk_pr, risk_pot, w30, p30, w60, p60, w90, p90, conf = evaluate_strategy_full(market_data[sym])
                
                val_attuale_asset = dat['qty'] * dat['cur_price']
                alloc = (val_attuale_asset / tot_val * 100) if tot_val > 0 else 0
                days = dat.get('days_held', 0)
                time_badge = f"📅 {days} gg"

                with cols_adv[i % 3]:
                    st.markdown(f"""
                        <div class="suggestion-box" style="background-color:{col}; border: 1px solid #bbb; min-height: 320px;">
                            <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                                <div><strong>{sym}</strong><div style="font-size:0.7rem; color:#666;">{asset_name}</div></div>
                                <div style="text-align:right;">
                                    <span style="color:{'green' if dat['pnl_pct']>=0 else 'red'}; font-weight:bold;">{dat['pnl_pct']:.1f}%</span>
                                    <div style="font-size:0.7rem; background:#444; color:white; padding:2px 6px; border-radius:4px; margin-top:2px;">{time_badge}</div>
                                </div>
                            </div>
                            <h3 style="color:#222; margin:8px 0; font-size:1.1rem;">{tit}
                                <span style="float: right; background-color: #388e3c; color: white; padding: 2px 6px; border-radius: 5px; font-size: 0.9rem;">🎯 {conf}</span>
                            </h3>
                            <p style="font-size:0.85rem; margin-bottom: 5px; line-height:1.3;">{adv}</p>
                            <hr style="margin: 5px 0; border-color: rgba(0,0,0,0.1);">
                            <div style="display: flex; justify-content: space-between; font-size: 0.75rem; color:#444;">
                                <span>Tgt: <b>${tgt:.0f}</b></span><span>Risk: <b>${risk_pr:.0f}</b></span><span>Alloc: <b>{alloc:.1f}%</b></span>
                            </div>
                        </div>""", unsafe_allow_html=True)
        else:
            st.info("Portafoglio vuoto.")

        st.divider()

        # --- TABS ANALISI ---
        tab_chart, tab_alloc, tab_tx = st.tabs(["📈 Analisi Grafica", "🍰 Allocazione", "📝 Cronologia"])

        with tab_chart:
            if raw_tx:
                with st.spinner("Elaborazione dati finanziari..."):
                    df_hist = get_historical_portfolio_value(raw_tx, market_data)
                
                if not df_hist.empty:
                    # FIX: Tasto Download Excel Ben Visibile Qui
                    # Generiamo l'Excel usando la nuova funzione avanzata
                    excel_data = generate_enhanced_excel_report(df_hist, pf)
                    
                    col_dl_btn, _ = st.columns([1, 3])
                    with col_dl_btn:
                        st.download_button(
                            label="📥 Scarica Report Excel Completo (Grafici+Colori)",
                            data=excel_data,
                            file_name=f"Report_InvestAI_{date.today()}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True
                        )

                    g1, g2, g3, g4 = st.tabs(["Capitale", "Utili", "Asset", "Previsione"])
                    
                    with g1: # CAPITALE
                        fig_hist = go.Figure()
                        fig_hist.add_trace(go.Scatter(x=df_hist.index, y=df_hist['Total Value'], mode='lines', name='Valore Portafoglio', line=dict(color='#004d40', width=2), fill='tozeroy'))
                        fig_hist.add_trace(go.Scatter(x=df_hist.index, y=df_hist['Total Invested'], mode='lines', name='Capitale Investito', line=dict(color='#ef5350', width=2, dash='dash')))
                        fig_hist.update_layout(height=400, hovermode="x unified", title="Valore vs Investito", template="plotly_white")
                        st.plotly_chart(fig_hist, use_container_width=True)

                    with g2: # UTILI
                        df_hist['Net Profit'] = df_hist['Total Value'] - df_hist['Total Invested']
                        fig_pnl = go.Figure()
                        colors = ['#66bb6a' if v >= 0 else '#ef5350' for v in df_hist['Net Profit']]
                        fig_pnl.add_trace(go.Bar(x=df_hist.index, y=df_hist['Net Profit'], name='P&L Giornaliero', marker_color=colors))
                        fig_pnl.update_layout(height=400, title="Guadagno/Perdita Netta (€)", template="plotly_white")
                        st.plotly_chart(fig_pnl, use_container_width=True)

                    with g3: # BREAKDOWN
                        fig_stack = go.Figure()
                        cols_asset = [c for c in df_hist.columns if c not in ['Total Value', 'Total Invested', 'Net Profit']]
                        for c in cols_asset:
                            fig_stack.add_trace(go.Scatter(x=df_hist.index, y=df_hist[c], mode='lines', stackgroup='one', name=c))
                        fig_stack.update_layout(height=400, title="Composizione nel Tempo", template="plotly_white")
                        st.plotly_chart(fig_stack, use_container_width=True)

                    with g4: # PREVISIONE (PULITA)
                        # 1. Calcolo Volatilità Storica del Portafoglio
                        # Usiamo solo il valore totale per non intasare il grafico
                        last_val = df_hist['Total Value'].iloc[-1]
                        
                        # Filtriamo i depositi per trovare la vera volatilità
                        df_rets = df_hist.copy()
                        df_rets['Invested_Change'] = df_rets['Total Invested'].diff()
                        mask_market_only = df_rets['Invested_Change'].abs() < 1.0 
                        if mask_market_only.sum() > 10:
                            daily_vol = df_rets.loc[mask_market_only, 'Total Value'].pct_change().std()
                            daily_drift = df_rets.loc[mask_market_only, 'Total Value'].pct_change().mean()
                        else:
                            daily_vol = 0.015
                            daily_drift = 0.0005

                        # Se il drift è negativo (periodo brutto), usiamo un drift neutro per la proiezione ottimistica
                        if np.isnan(daily_vol): daily_vol = 0.015
                        if np.isnan(daily_drift): daily_drift = 0.0

                        days_proj = 90
                        dates_proj = pd.date_range(start=df_hist.index[-1], periods=days_proj+1)
                        
                        # Simulazione Monte Carlo Semplificata (Cono di confidenza)
                        # Upper: +1 Std Dev, Lower: -1 Std Dev
                        # Usiamo la radice quadrata del tempo per scalare la volatilità
                        
                        forecast_mean = [last_val * (1 + daily_drift)**i for i in range(days_proj+1)]
                        # Volatilità scala con sqrt(t)
                        upper_band = [m * (1 + daily_vol * np.sqrt(i)) for i, m in enumerate(forecast_mean)]
                        lower_band = [m * (1 - daily_vol * np.sqrt(i)) for i, m in enumerate(forecast_mean)]
                        
                        fig_proj = go.Figure()
                        
                        # Storico (Ultimi 60 giorni per contesto)
                        cutoff_hist = df_hist.index[-60:] if len(df_hist) > 60 else df_hist.index
                        fig_proj.add_trace(go.Scatter(x=cutoff_hist, y=df_hist.loc[cutoff_hist, 'Total Value'], 
                                                    mode='lines', name='Storico Recente', line=dict(color='gray', width=2)))

                        # Proiezioni
                        fig_proj.add_trace(go.Scatter(x=dates_proj, y=upper_band, mode='lines', line=dict(width=0), showlegend=False))
                        fig_proj.add_trace(go.Scatter(x=dates_proj, y=lower_band, mode='lines', fill='tonexty', 
                                                    fillcolor='rgba(0, 77, 64, 0.2)', line=dict(width=0), name='Range Probabile (90gg)'))
                        
                        fig_proj.add_trace(go.Scatter(x=dates_proj, y=forecast_mean, mode='lines', 
                                                    line=dict(color='#004d40', dash='dash', width=2), name='Trend Atteso'))

                        fig_proj.update_layout(height=450, title="Previsione Portafoglio Totale (90 Giorni)", template="plotly_white")
                        st.plotly_chart(fig_proj, use_container_width=True)
                        st.info("ℹ️ Il grafico mostra SOLO il valore totale del portafoglio per chiarezza. L'area ombreggiata rappresenta la volatilità attesa.")

                else:
                    st.warning("Dati insufficienti.")
            else:
                st.info("Nessuna transazione.")

        # --- TAB B: ALLOCAZIONE ---
        with tab_alloc:
            if pie_data:
                c_pie, c_list = st.columns([1, 1.5])
                with c_pie:
                    fig_pie = go.Figure(data=[go.Pie(labels=[x['Label'] for x in pie_data], values=[x['Value'] for x in pie_data], hole=.4)])
                    fig_pie.update_layout(margin=dict(t=0,b=0,l=0,r=0), height=300, showlegend=False)
                    st.plotly_chart(fig_pie, use_container_width=True)
                
                with c_list:
                    alloc_data = []
                    for k,v in pf.items():
                        f_date = first_buy_dates.get(k, "N/A")
                        alloc_data.append({
                            "Asset": k,
                            "Valore Attuale": v['qty'] * v['cur_price'],
                            "Costo Totale": v['total_cost'],
                            "P&L %": v['pnl_pct'] / 100, 
                            "Data 1° Acq": f_date
                        })
                    df_alloc = pd.DataFrame(alloc_data).sort_values("Valore Attuale", ascending=False)
                    st.dataframe(df_alloc, hide_index=True, use_container_width=True,
                        column_config={
                            "Valore Attuale": st.column_config.NumberColumn(format="€%.2f"),
                            "Costo Totale": st.column_config.NumberColumn(format="€%.2f"),
                            "P&L %": st.column_config.NumberColumn(format="%.2f%%"),
                            "Data 1° Acq": st.column_config.DateColumn(format="DD/MM/YYYY")
                        }
                    )
            else:
                st.info("Portafoglio vuoto.")

        # --- TAB C: CRONOLOGIA ---
        with tab_tx:
            st.subheader("Gestione Transazioni")
            st.info("💡 Modifica celle e premi Salva. Spunta 'Elimina' per cancellare.")
            
            with st.expander("➕ Aggiungi Nuova Transazione"):
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
                        else: st.error("Ticker invalido")

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
                
                if st.button("💾 Salva Modifiche al Database", type="primary"):
                    rows_to_delete = edited_df[edited_df['Elimina'] == True]
                    for index, row in rows_to_delete.iterrows():
                        db.delete_transaction(row['ID'])
                    rows_to_update = edited_df[edited_df['Elimina'] == False]
                    for index, row in rows_to_update.iterrows():
                        db.update_transaction(row['ID'], row['Ticker'], row['Qta'], row['Prezzo'], str(row['Data']), row['Tipo'], row['Fee'])
                    st.success("Aggiornato!"); st.cache_data.clear(); time.sleep(1); st.rerun()
            else:
                st.info("Nessuna transazione.")
                                
# --- 3. CONSIGLI OPERATIVI ---
    elif page == "💡 Consigli":
        # --- FIX: IMPORTAZIONI NECESSARIE ---
        # Assicurati che queste funzioni siano presenti nel tuo file logic.py o definite globalmente
        from logic import generate_portfolio_advice, evaluate_strategy_full, get_data, AUTO_SCAN_TICKERS, get_asset_name
        
        st.title("L'AI Advisor")
        st.markdown("Analisi completa di tutti gli asset in portafoglio e nuove opportunità.")

        if st.button("🔄 Analizza Situazione", width="stretch"):
            st.cache_data.clear()
            st.rerun()

        with st.spinner("Analisi completa in corso..."):
            pf, _ = db.get_portfolio_summary(user)
            owned_tickers = list(pf.keys())
            
            # Scarica dati per tutti (Portafoglio + Mercato)
            all_potential_tickers = list(set(owned_tickers + AUTO_SCAN_TICKERS))
            market_data = get_data(all_potential_tickers)

            # Liste per categorizzare gli asset
            actions_sell = []      # Urgenze di uscita
            actions_buy_more = []  # Occasioni di accumulo su asset posseduti
            actions_hold = []      # Tutto ciò che è stabile (Hold, Moonbag, Wait)
            actions_new_entry = [] # Nuove opportunità di mercato (non posseduti)
            
            missing_tickers = []

            # 1. ANALISI PORTAFOGLIO (TUTTI GLI ASSET)
            for t in owned_tickers:
                if t in market_data:
                    dat = pf[t]
                    cur_price = market_data[t]['Close'].iloc[-1]
                    
                    # Calcoli finanziari
                    val_pos = dat['qty'] * cur_price
                    pnl_val = val_pos - dat['total_cost']
                    dat['pnl_pct'] = (pnl_val / dat['total_cost'] * 100) if dat['total_cost'] > 0 else 0
                    
                    # Genera il consiglio
                    tit, adv, col = generate_portfolio_advice(market_data[t], dat['avg_price'], cur_price)
                    
                    # Oggetto dati per la visualizzazione
                    item = {
                        "ticker": t, 
                        "title": tit, 
                        "desc": adv, 
                        "color": col, 
                        "pnl": dat['pnl_pct'],
                        "price": cur_price
                    }
                    
                    # --- LOGICA DI SMISTAMENTO ---
                    # 1. Vendita / Protezione / Incasso
                    if any(k in tit for k in ["VENDI", "INCASSA", "PROTEGGI", "VALUTA VENDITA", "STOP"]):
                        actions_sell.append(item)
                    
                    # 2. Acquisto / Mediazione
                    elif any(k in tit for k in ["ACQUISTA", "MEDIA", "ACCUMULO", "PAC"]):
                        actions_buy_more.append(item)
                    
                    # 3. HOLD / MANTENIMENTO (Tutto il resto finisce qui)
                    else:
                        # Personalizziamo i colori per renderli distinti
                        if "MOONBAG" in tit: 
                            item['color'] = "#e8f5e9" # Verde chiarissimo
                            item['border'] = "2px solid #4caf50" # Bordo verde acceso
                        elif "TREND SANO" in tit:
                            item['color'] = "#f1f8e9"
                            item['border'] = "1px solid #8bc34a"
                        else: # Mantieni / Attendi / Attenzione
                            item['color'] = "#f5f5f5" # Grigio chiaro neutro
                            item['border'] = "1px solid #ccc"
                            
                        actions_hold.append(item)
                else:
                    missing_tickers.append(t)

            # 2. ANALISI NUOVE OPPORTUNITÀ (MERCATO)
            for t in AUTO_SCAN_TICKERS:
                if t not in owned_tickers and t in market_data:
                    _, act, col, pr, rsi, dd, res, tgt, pot, r_pr, r_pot, w30, p30, w60, p60, w90, p90, conf = evaluate_strategy_full(market_data[t])
                    
                    if "ACQUISTA" in act or "ORO" in act:
                        actions_new_entry.append({
                            "ticker": t, "title": act, "desc": res, 
                            "color": col, "price": pr, "rsi": rsi,
                            "target": tgt, "potential": pot,
                            "risk": r_pr, "risk_pot": r_pot,
                            "w30": w30, "p30": p30, "w60": w60, "p60": p60, "w90": w90, "p90": p90,
                            "confidence": conf
                        })

            # --- VISUALIZZAZIONE ---
            
            # Metriche riassuntive
            c1, c2, c3 = st.columns(3)
            c1.metric("Azioni Urgenti", len(actions_sell) + len(actions_buy_more))
            c2.metric("In Holding", len(actions_hold))
            c3.metric("Nuove Opportunità", len(actions_new_entry))
            st.divider()

            if missing_tickers:
                st.warning(f"⚠️ Dati mancanti per: {', '.join(missing_tickers)}")

            # SEZIONE 1: URGENZE (Priorità Alta)
            if actions_sell:
                st.subheader("🔴 Richiedono Azione (Vendi/Proteggi)")
                cols = st.columns(3)
                for i, item in enumerate(actions_sell):
                    asset_name = get_asset_name(item['ticker'])
                    if item['ticker'] in market_data:
                        _, _, _, _, _, _, _, tgt, pot, risk_pr, risk_pot, w30, p30, w60, p60, w90, p90, conf = evaluate_strategy_full(market_data[item['ticker']]) 
                    else: # Fallback se i dati sono stati persi
                        tgt, pot, risk_pr, risk_pot = 0, 0, 0, 0
                        w30, p30, w60, p60, w90, p90 = 0, 0, 0, 0, 0, 0
                    
                    with cols[i%3]: 
                        st.markdown(f"""
                        <div class="suggestion-box" style="background-color:{item['color']}; border: 2px solid #d32f2f;">
                            <div style="display:flex; justify-content:space-between;">
                                <div>
                                    <h4 style="margin:0;">{item['ticker']}</h4>
                                    <div style="font-size:0.75rem; color:#666; margin-bottom:4px;">{asset_name}</div>
                                </div>
                                <span style="font-weight:bold; color:#d32f2f;">{item['pnl']:.1f}%</span>
                            </div>
                            <h3 style="color:#b71c1c; margin:5px 0;">{item['title']}</h3>
                            <p style="font-size:0.9rem;">{item['desc']}</p>
                        </div>""", unsafe_allow_html=True)
                st.divider()

            # SEZIONE 2: ACCUMULO
            if actions_buy_more:
                st.subheader("🟢 Occasioni di Accumulo (Portafoglio)")
                cols = st.columns(3)
                for i, item in enumerate(actions_buy_more):
                    asset_name = get_asset_name(item['ticker']) 
                    if item['ticker'] in market_data:
                        _, _, _, _, _, _, _, tgt, pot, risk_pr, risk_pot, w30, p30, w60, p60, w90, p90, conf = evaluate_strategy_full(market_data[item['ticker']]) 
                    else:
                        tgt, pot, risk_pr, risk_pot = 0, 0, 0, 0
                        w30, p30, w60, p60, w90, p90 = 0, 0, 0, 0, 0, 0
            
                    with cols[i%3]: 
                        st.markdown(f"""
                        <div class="suggestion-box" style="background-color:{item['color']}; border: 2px solid #2e7d32;">
                            <div style="display:flex; justify-content:space-between;">
                                <div>
                                    <h4 style="margin:0;">{item['ticker']}</h4>
                                    <div style="font-size:0.75rem; color:#666; margin-bottom:4px;">{asset_name}</div>
                                </div>
                                <span style="font-weight:bold; color:#2e7d32;">{item['pnl']:.1f}%</span>
                            </div>
                            <h3 style="color:#1b5e20; margin:5px 0;">{item['title']}</h3>
                            <p style="font-size:0.9rem;">{item['desc']}</p>
                        </div>""", unsafe_allow_html=True)
                st.divider()

            # SEZIONE 3: HOLDING
            if actions_hold:
                st.subheader("🔵 Mantenimento & Monitoraggio")
                st.caption("Asset stabili che non richiedono azioni immediate. Lascia correre i profitti o attendi sviluppi.")
                
                cols = st.columns(3)
                for i, item in enumerate(actions_hold):
                    asset_name = get_asset_name(item['ticker']) 
            
                    if item['ticker'] in market_data:
                        _, _, _, _, _, _, _, tgt, pot, risk_pr, risk_pot, w30, p30, w60, p60, w90, p90, conf = evaluate_strategy_full(market_data[item['ticker']]) 
                    else:
                        tgt, pot, risk_pr, risk_pot = 0, 0, 0, 0
                        w30, p30, w60, p60, w90, p90 = 0, 0, 0, 0, 0, 0

                    # Colore testo dinamico
                    text_color = "#333"
                    if "MOONBAG" in item['title']: text_color = "#2e7d32"
                    elif "ATTENZIONE" in item['title']: text_color = "#f57f17"
                    
                    pnl_color = "green" if item['pnl'] >= 0 else "red"

                    with cols[i%3]: 
                        st.markdown(f"""
                        <div class="suggestion-box" style="background-color:{item['color']}; border: {item['border']};">
                            <div style="display:flex; justify-content:space-between;">
                                <div>
                                    <h4 style="margin:0;">{item['ticker']}</h4>
                                    <div style="font-size:0.75rem; color:#666; margin-bottom:4px;">{asset_name}</div>
                                </div>
                                <span style="font-weight:bold; color:{pnl_color};">{item['pnl']:.1f}%</span>
                            </div>
                            <h3 style="color:{text_color}; margin:5px 0; font-size:1.1rem;">{item['title']}</h3>
                            <p style="font-size:0.85rem; color:#555;">{item['desc']}</p>
                            <div style="text-align:right; font-size:0.8rem; margin-top:5px;">Prezzo: ${item['price']:.2f}</div>
                        </div>""", unsafe_allow_html=True)
                st.divider()

            # SEZIONE 4: OPPORTUNITÀ DI MERCATO
            if actions_new_entry:
                st.subheader("🚀 Nuove Opportunità (Mercato)")
                cols = st.columns(3)
                for i, item in enumerate(actions_new_entry):
                    asset_name = get_asset_name(item['ticker'])
                    border_style = "border: 2px solid #FFD700; box-shadow: 0 0 5px #FFD700;" if "ORO" in item['title'] else "border: 1px solid #8bc34a;"
                    
                    with cols[i%3]: 
                        st.markdown(f"""
                            <div class="suggestion-box" style="background-color:{item['color']}; {border_style}">
                                <div style="display:flex; justify-content:space-between;">
                                    <div>
                                        <h4 style="margin:0;">{item['ticker']}</h4>
                                        <div style="font-size:0.75rem; color:#666; margin-bottom:4px;">{asset_name}</div>
                                    </div>
                                    <span style="font-weight:bold; color:#006400;">+{item['potential']:.1f}%</span>
                                </div>
                                <h3 style="color:#004d40; margin:5px 0;">{item['title']}
                                    <span style="float: right; background-color: #388e3c; color: white; padding: 4px 8px; border-radius: 5px; font-size: 1.1rem;">
                                        🎯 {item['confidence']}/100
                                    </span>
                                </h3>
                                <p style="font-size:0.9rem;">{item['desc']}</p> 
                                <div style="margin-top:8px; border-top: 1px dashed rgba(0,0,0,0.3); padding-top:5px; font-size:0.8rem; color:#555;">
                                    <div style="display:flex; justify-content:space-between; font-weight:bold;">
                                        <span>30G: {item['w30']:.0f}% ({item['p30']:.1f}%)</span>
                                        <span>60G: {item['w60']:.0f}% ({item['p60']:.1f}%)</span>
                                        <span>90G: {item['w90']:.0f}% ({item['p90']:.1f}%)</span>
                                    </div>
                                    <div style="text-align: center; margin-top: 5px; font-size: 0.75rem; color: #777;">
                                        (Win Rate % / PnL Medio %)
                                    </div>
                                </div>
                                <div style="margin-top:8px; border-top: 1px solid rgba(0,0,0,0.1); padding-top:5px;">
                                    <div style="display:flex; justify-content:space-between; font-size:0.85rem;">
                                        <span>Target: <b>${item['target']:.1f}</b></span>
                                        <span style="color:#b71c1c;">Risk: <b>{item['risk_pot']:.1f}%</b></span>
                                    </div>
                                    <div style="text-align:right; font-size:0.8rem; margin-top:4px; color:#555;">
                                        Prezzo: ${item['price']:.2f} | RSI: {item['rsi']:.0f}
                                    </div>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)

            if not (actions_sell or actions_buy_more or actions_hold or actions_new_entry):
                st.info("Nessun dato disponibile per generare consigli.")

# --- 4. IMPOSTAZIONI ---
    elif page == "⚙️ Impostazioni":
        st.title("Impostazioni")
        
        tab_tg, tab_sec = st.tabs(["🔔 Notifiche", "🔒 Sicurezza"])
        
        # --- TAB 1: TELEGRAM ---
        with tab_tg:
            st.info("Per ricevere consigli automatici ogni mattina su Telegram, devi inserire il tuo Chat ID.")
            with st.container(border=True):
                st.subheader("Configurazione Telegram")
                current_id = db.get_user_chat_id(user)
                chat_id_input = st.text_input("Inserisci il tuo Telegram Chat ID", value=current_id, help="Cerca @userinfobot su Telegram per scoprire il tuo ID")
                if st.button("💾 Salva ID Telegram", type="primary"):
                    if chat_id_input:
                        if db.save_chat_id(user, chat_id_input): st.success("Chat ID salvato con successo! Il bot ti invierà aggiornamenti.");
                        else: st.error("Errore nel salvataggio.")
                    else: st.warning("Inserisci un ID valido.")
                st.markdown("""
                **Come ottenere il tuo Chat ID:**
                1. Apri Telegram.
                2. Cerca **@userinfobot** e avvialo.
                3. Copia il numero sotto la voce 'Id'.
                4. **IMPORTANTE:** Cerca il nostro bot **InvestAI Bot** e premi AVVIA, altrimenti non potrà scriverti!
                """)

        # --- TAB 2: SICUREZZA (CAMBIO PASSWORD) ---
        with tab_sec:
            st.warning("Qui puoi modificare la password di accesso a questo sito.")
            with st.container(border=True):
                st.subheader("Cambio Password")
                with st.form("change_pass_form"):
                    p1 = st.text_input("Nuova Password", type="password")
                    p2 = st.text_input("Conferma Password", type="password")
                    if st.form_submit_button("Aggiorna Password"):
                        if p1 and p2:
                            if p1 == p2:
                                if db.change_password(user, p1):
                                    st.success("Password aggiornata con successo! Effettua il login.")
                                    time.sleep(2)
                                    st.session_state.user = None
                                    st.rerun()
                                else:
                                    st.error("Errore durante l'aggiornamento. Riprova.")
                            else:
                                st.error("Le password non coincidono.")
                        else:
                            st.warning("Inserisci la nuova password.")

if __name__ == "__main__":
    main()











