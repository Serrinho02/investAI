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
        # Importiamo le funzioni helper necessarie
        # Assicurati che get_historical_portfolio_value e generate_excel_report siano in logic.py
        from logic import get_historical_portfolio_value, generate_excel_report, evaluate_strategy_full, generate_portfolio_advice
        
        if 'tx_page' not in st.session_state: st.session_state.tx_page = 0
        
        c_title, c_btn = st.columns([3, 1])
        with c_title: st.title("Gestione Portafoglio")
        with c_btn:
            if st.button("🔄 Aggiorna Dati", width="stretch"):
                st.cache_data.clear()
                st.rerun()
        
        # Recupera dati dal DB
        pf, history = db.get_portfolio_summary(user)
        raw_tx = db.get_all_transactions(user) # Serve per il grafico storico
        
        # --- CALCOLO TOTALE E DATI MERCATO ---
        # 1. Identifichiamo tutti i ticker mai toccati (per lo storico) + quelli attuali
        tickers_current = list(pf.keys())
        tickers_history = list(set([t[1] for t in raw_tx])) if raw_tx else []
        all_tickers = list(set(tickers_current + tickers_history))
        
        market_data = get_data(all_tickers)
        
        tot_val = 0 # Valore totale attuale
        tot_cost = 0 # Costo totale attuale
        pie_data = [] # Dati per grafico a torta
        
        # Aggiorniamo i dati del portafoglio attuale con i prezzi live
        for t in tickers_current:
            cur = market_data[t]['Close'].iloc[-1] if t in market_data else pf[t]['avg_price']
            val = pf[t]['qty'] * cur
            
            pf[t]['cur_price'] = cur
            pf[t]['pnl'] = val - pf[t]['total_cost'] 
            pf[t]['pnl_pct'] = (pf[t]['pnl'] / pf[t]['total_cost'] * 100) if pf[t]['total_cost'] > 0 else 0
            
            tot_val += val
            tot_cost += pf[t]['total_cost']
            pie_data.append({"Label": t, "Value": val})
            
        pnl_tot = tot_val - tot_cost
        pnl_tot_pct = (pnl_tot/tot_cost*100) if tot_cost > 0 else 0

        # --- SEZIONE 1: METRICHE PRINCIPALI (Responsive) ---
        with st.container():
            # Stile personalizzato per card metriche
            st.markdown("""
            <style>
            div[data-testid="metric-container"] {
                background-color: #ffffff;
                border: 1px solid #e0e0e0;
                padding: 10px;
                border-radius: 10px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            }
            </style>
            """, unsafe_allow_html=True)
            
            m1, m2, m3 = st.columns(3)
            m1.metric("Valore Attuale", f"€{tot_val:,.2f}")
            m2.metric("P&L Totale", f"€{pnl_tot:,.2f}", delta=f"{pnl_tot_pct:.2f}%")
            m3.metric("Liquidità Investita", f"€{tot_cost:,.2f}")

        # --- SEZIONE 2: STRATEGIA OPERATIVA (RESTORED) ---
        st.divider()
        st.subheader("💡 Strategia Operativa")
        
        with st.expander("ℹ️ Legenda Comandi", expanded=False):
            st.markdown("""
            <div style="font-size: 0.85rem; line-height: 1.4; color: #333;">
                L'Advisor analizza ogni posizione in base alla volatilità dell'asset (ATR) e al Trend di fondo.
                <ul style="padding-left: 20px; margin-bottom: 10px;">
                    <li>🚀 <b>MOONBAG / TREND SANO:</b> Profitto solido, trend rialzista. Lascia correre.</li>
                    <li>💰 <b>TAKE PROFIT:</b> RSI estremo o trend incerto. Metti al sicuro parte dei profitti.</li>
                    <li>🚨 <b>PROTEGGI / INCASSA:</b> Trend cambiato in negativo. Uscire.</li>
                    <li>🛒 <b>MEDIA (Accumulo):</b> Prezzo a sconto in trend rialzista. Occasione.</li>
                    <li>⚠️ <b>CUT LOSS:</b> Perdita e trend negativo. Tagliare prima che peggiori.</li>
                </ul>
            </div>
            """, unsafe_allow_html=True)

        # Generazione Card Consigli
        valid_pf = [item for item in pf.items() if item[0] in market_data]
        sorted_pf = sorted(valid_pf, key=lambda x: x[1]['pnl_pct']) # Ordina per P&L

        if sorted_pf:
            cols_adv = st.columns(3)
            for i, (sym, dat) in enumerate(sorted_pf):
                asset_name = get_asset_name(sym)
                # Genera il consiglio finanziario
                tit, adv, col = generate_portfolio_advice(market_data[sym], dat['avg_price'], dat['cur_price'])
                # Ottieni i dati tecnici e score per la card
                _, _, _, _, _, _, _, tgt, pot, risk_pr, risk_pot, w30, p30, w60, p60, w90, p90, conf = evaluate_strategy_full(market_data[sym])
                
                val_attuale_asset = dat['qty'] * dat['cur_price']
                percentuale_allocazione = (val_attuale_asset / tot_val * 100) if tot_val > 0 else 0
                
                with cols_adv[i % 3]:
                    st.markdown(f"""
                        <div class="suggestion-box" style="background-color:{col}; border: 1px solid #bbb; min-height: 280px;">
                            <div style="display:flex; justify-content:space-between;">
                                <div>
                                    <strong>{sym}</strong>
                                    <div style="font-size:0.7rem; color:#666; margin-top:-2px;">{asset_name}</div> 
                                </div>
                                <span style="color:{'green' if dat['pnl_pct']>=0 else 'red'}; font-weight:bold;">{dat['pnl_pct']:.1f}%</span>
                            </div>
                            <h3 style="color:#222; margin:5px 0;">{tit}
                                <span style="float: right; background-color: #388e3c; color: white; padding: 4px 8px; border-radius: 5px; font-size: 1.1rem;">
                                    🎯 {conf}/100
                                </span>
                            </h3>
                            <p style="font-size:0.9rem; margin-bottom: 5px;">{adv}</p>
                            <hr style="margin: 5px 0; border-color: rgba(0,0,0,0.1);">
                            <div style="font-size: 0.8rem; display: flex; justify-content: space-between; margin-bottom: 5px;">
                                <span>Prezzo: €{dat['cur_price']:.2f}</span>
                                <span>Tot: <b>€{val_attuale_asset:,.0f}</b></span>
                            </div>
                            <div style="font-size: 0.8rem; text-align: right; margin-bottom: 10px;">Allocazione: <b>{percentuale_allocazione:.1f}%</b></div>
                            <div style="padding: 8px; background-color: rgba(255,255,255,0.8); border-radius: 6px; border: 1px dashed #666; margin-bottom: 8px;">
                                <div style="font-size: 0.7rem; text-transform: uppercase; color: #555; font-weight: bold; margin-bottom: 4px; text-align:center;">Probabilità Storica (Buy Signal)</div>
                                <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.85rem;">
                                    <span style="font-weight:bold;">30G: {w30:.0f}% <span style="color:{'green' if p30>=0 else 'red'};">({p30:.1f}%)</span></span>
                                    <span style="font-weight:bold;">90G: {w90:.0f}% <span style="color:{'green' if p90>=0 else 'red'};">({p90:.1f}%)</span></span>
                                </div>
                            </div>
                            <div style="padding: 8px; background-color: rgba(255,255,255,0.6); border-radius: 6px; border: 1px dashed #666;">
                                <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.85rem;">
                                    <span style="color: #006400;">✅ Tgt: <b>${tgt:.0f}</b></span>
                                    <span style="color: #b30000;">🔻 Risk: <b>${risk_pr:.0f}</b></span>
                                </div>
                            </div>
                        </div>""", unsafe_allow_html=True)
        else:
            st.info("Aggiungi asset al portafoglio per ricevere i consigli dell'AI.")

        st.divider()

        # --- SEZIONE 3: TABELLA DI MARCIA (TABS) ---
        # Organizziamo in Tab per non avere una pagina infinita su mobile
        tab_chart, tab_alloc, tab_tx = st.tabs(["📈 Andamento Storico", "🍰 Allocazione", "📝 Transazioni"])

        # --- TAB A: GRAFICO STORICO ---
        with tab_chart:
            if raw_tx:
                with st.spinner("Ricostruzione storico del portafoglio..."):
                    df_hist = get_historical_portfolio_value(raw_tx, market_data)
                
                if not df_hist.empty:
                    # Grafico Area
                    fig_hist = go.Figure()
                    fig_hist.add_trace(go.Scatter(
                        x=df_hist.index, y=df_hist['Total Value'],
                        mode='lines', name='Valore Portafoglio',
                        line=dict(color='#004d40', width=2),
                        fill='tozeroy', fillcolor='rgba(0, 77, 64, 0.1)'
                    ))
                    fig_hist.update_layout(
                        title="Evoluzione del Capitale",
                        template="plotly_white",
                        height=350,
                        margin=dict(l=10, r=10, t=40, b=10),
                        hovermode="x unified"
                    )
                    st.plotly_chart(fig_hist, use_container_width=True)
                    
                    # Bottone Export Excel
                    excel_data = generate_excel_report(df_hist, pf)
                    st.download_button(
                        label="📥 Scarica Report Excel Completo",
                        data=excel_data,
                        file_name=f"InvestAI_Report_{date.today()}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
                else:
                    st.warning("Non ci sono abbastanza dati storici per generare il grafico.")
            else:
                st.info("Aggiungi la tua prima transazione per vedere il grafico storico.")

        # --- TAB B: ALLOCAZIONE & DETTAGLI ---
        with tab_alloc:
            if pie_data:
                c_pie, c_list = st.columns([1, 1])
                with c_pie:
                    fig_pie = go.Figure(data=[go.Pie(
                        labels=[x['Label'] for x in pie_data], 
                        values=[x['Value'] for x in pie_data], 
                        hole=.5,
                        textinfo='label+percent',
                        marker=dict(colors=['#004d40', '#00695c', '#00796b', '#00897b', '#26a69a', '#4db6ac'])
                    )])
                    fig_pie.update_layout(margin=dict(t=0,b=0,l=0,r=0), height=300, showlegend=False)
                    st.plotly_chart(fig_pie, use_container_width=True)
                
                with c_list:
                    # Tabella riassuntiva pulita
                    summary_df = pd.DataFrame([
                        {"Asset": k, "Valore": v['cur_price']*v['qty'], "P&L": v['pnl_pct']} 
                        for k,v in pf.items()
                    ]).sort_values("Valore", ascending=False)
                    
                    st.dataframe(
                        summary_df, 
                        hide_index=True,
                        column_config={
                            "Valore": st.column_config.NumberColumn(format="€%.2f"),
                            "P&L": st.column_config.NumberColumn(format="%.2f%%")
                        },
                        use_container_width=True
                    )
            else:
                st.info("Portafoglio vuoto.")

        # --- TAB C: GESTIONE TRANSAZIONI (Il tuo codice originale integrato) ---
        with tab_tx:
            # --- MODIFICA TRANSAZIONE (Form a scomparsa) ---
            if st.session_state.edit_tx_id:
                tx = db.get_transaction_by_id(st.session_state.edit_tx_id)
                if tx:
                    with st.container(border=True):
                        st.subheader(f"✏️ Modifica: {tx[1]}")
                        with st.form("edit"):
                            c1,c2,c3,c4 = st.columns(4)
                            nq = c1.number_input("Qta", value=float(tx[2]))
                            np = c2.number_input("Prezzo", value=float(tx[3]))
                            current_fee = float(tx[6]) if len(tx) > 6 and tx[6] is not None else 0.0
                            nf = c3.number_input("Comm. (€)", value=current_fee, step=0.5)
                            nd = c4.date_input("Data", datetime.strptime(tx[4], '%Y-%m-%d').date())
                            
                            c_s1, c_s2 = st.columns(2)
                            if c_s1.form_submit_button("💾 Salva", type="primary", use_container_width=True): 
                                db.update_transaction(tx[0], tx[1], nq, np, str(nd), tx[5], nf) 
                                st.session_state.edit_tx_id=None; st.cache_data.clear(); st.rerun()
                            if c_s2.form_submit_button("Annulla", use_container_width=True): 
                                st.session_state.edit_tx_id=None; st.rerun()

            c_l, c_a = st.columns([2, 1])
            
            # LISTA TRANSAZIONI
            with c_l:
                st.subheader("Cronologia")
                if raw_tx:
                    search_query = st.text_input("🔍 Cerca...", placeholder="Ticker o Data").upper()
                    filtered_tx = [r for r in raw_tx if search_query in r[1] or search_query in str(r[4])] if search_query else raw_tx
                    
                    # Paginazione
                    ITEMS_PER_PAGE = 8
                    total_tx = len(filtered_tx)
                    start_idx = st.session_state.tx_page * ITEMS_PER_PAGE
                    end_idx = start_idx + ITEMS_PER_PAGE
                    
                    # Header Tabella (Custom HTML per layout mobile migliore)
                    st.markdown("""
                    <div style="display: flex; font-weight: bold; padding: 5px 0; border-bottom: 2px solid #ddd; font-size: 0.85rem;">
                        <div style="flex: 2;">Data</div>
                        <div style="flex: 2;">Asset</div>
                        <div style="flex: 2;">Prezzo</div>
                        <div style="flex: 1; text-align: right;">Azioni</div>
                    </div>
                    """, unsafe_allow_html=True)

                    view_tx = filtered_tx[start_idx:end_idx]
                    for r in view_tx:
                        color_type = "green" if r[5]=='BUY' else "red"
                        # Riga Tabella
                        st.markdown(f"""
                        <div style="display: flex; align-items: center; padding: 8px 0; border-bottom: 1px solid #eee; font-size: 0.85rem;">
                            <div style="flex: 2;">{r[4]}</div>
                            <div style="flex: 2; color: {color_type}; font-weight: bold;">{r[5]} {r[1]}<br><span style="color:#666; font-weight:normal; font-size:0.75rem;">x{r[2]:.4f}</span></div>
                            <div style="flex: 2;">€{r[3]:.2f}<br><span style="color:#999; font-size:0.7rem;">Fee: €{r[6]:.1f}</span></div>
                            <div style="flex: 1; text-align: right;">
                                </div>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        # Bottoni Azione (invisibili nell'HTML sopra, posizionati qui)
                        c_b1, c_b2 = st.columns([0.85, 0.15])
                        with c_b2:
                            pop_col1, pop_col2 = st.columns(2)
                            if pop_col1.button("✏️", key=f"e{r[0]}"): st.session_state.edit_tx_id=r[0]; st.rerun()
                            if pop_col2.button("❌", key=f"d{r[0]}"): confirm_delete_dialog(r[0])
                    
                    # Controlli Paginazione
                    st.markdown("<br>", unsafe_allow_html=True)
                    cp, cn = st.columns(2)
                    if st.session_state.tx_page > 0:
                        if cp.button("⬅️ Precedenti"): st.session_state.tx_page -= 1; st.rerun()
                    if end_idx < total_tx:
                        if cn.button("Successivi ➡️"): st.session_state.tx_page += 1; st.rerun()
                else:
                    st.write("Nessuna transazione.")

            # AGGIUNTA TRANSAZIONE
            with c_a:
                with st.expander("➕ Aggiungi Nuova", expanded=False):
                    with st.container(border=True):
                        n_sym = st.selectbox("Asset", ["BTC-USD", "ETH-USD", "AAPL", "NVDA", "ALTRO"], key="ns")
                        if n_sym == "ALTRO": n_sym = st.text_input("Ticker", key="ncs").upper()
                        n_qty = st.number_input("Qta", min_value=0.0001, format="%.4f", key="nq")
                        n_prc = st.number_input("Prezzo (€)", min_value=0.01, key="np")
                        n_fee = st.number_input("Fee (€)", min_value=0.0, step=0.5, key="nf") 
                        n_date = st.date_input("Data", date.today(), key="nd")
                        n_type = st.selectbox("Tipo", ["BUY", "SELL"], key="nt")
                        
                        if st.button("Salva", type="primary", width="stretch"):
                            if validate_ticker(n_sym): 
                                db.add_transaction(user, n_sym, n_qty, n_prc, str(n_date), n_type, n_fee)
                                st.cache_data.clear()
                                st.success("Fatto!"); st.rerun()
                            else: st.error("Ticker invalido")

    # --- 3. CONSIGLI OPERATIVI ---
    elif page == "💡 Consigli":
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
                            # AGGIUNTA DEI DATI DI BACKTESTING
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
                    asset_name = get_asset_name(item['ticker']) # AGGIUNTO
                    # CHIAMATA COMPLETA PER DATI TECNICI (Per mostrare il nome e il P&L storico)
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

            # SEZIONE 3: HOLDING (QUELLE CHE MANCAVANO!)
            # Questa sezione viene mostrata SEMPRE se ci sono asset in hold
            if actions_hold:
                st.subheader("🔵 Mantenimento & Monitoraggio")
                st.caption("Asset stabili che non richiedono azioni immediate. Lascia correre i profitti o attendi sviluppi.")
                
                cols = st.columns(3)
                for i, item in enumerate(actions_hold):
                    asset_name = get_asset_name(item['ticker']) # AGGIUNTO
            
                    # CHIAMATA COMPLETA PER DATI TECNICI (Per mostrare il nome e il P&L storico)
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
                    # Bordo speciale per "ORO", altrimenti bordo standard grigio/verde
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
                                        <span>30 Giorni: {item['w30']:.0f}% ({item['p30']:.1f}%)</span>
                                        <span>60 Giorni: {item['w60']:.0f}% ({item['p60']:.1f}%)</span>
                                        <span>90 Giorni: {item['w90']:.0f}% ({item['p90']:.1f}%)</span>
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






