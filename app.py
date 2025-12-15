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
st.set_page_config(page_title="InvestAI Ultimate", layout="wide", page_icon="💎")

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
    /* 1. NASCONDI ELEMENTI SPECIFICI, MA NON TUTTO L'HEADER */
    
    /* Nasconde il menu hamburger (i 3 puntini a destra) */
    #MainMenu {visibility: hidden;}
    
    /* Nasconde il pulsante Deploy */
    .stDeployButton {display: none;}
    
    /* Nasconde il footer in basso */
    footer {visibility: hidden;}
    
    /* Nasconde la barra colorata decorativa in alto */
    [data-testid="stDecoration"] {display: none;}
    
    /* Nasconde widget di stato in basso a destra */
    .stStatusWidget {display: none;}

    /* 2. GESTIONE HEADER (LA CORREZIONE È QUI) */
    /* Non usiamo più 'visibility: hidden' su tutto l'header.
       Invece, lo rendiamo trasparente per mantenere cliccabile 
       la freccetta in alto a sinistra per aprire la sidebar. */
    header {
        background: transparent !important;
    }

    /* 3. STILI PERSONALIZZATI APP */
    [data-testid="stMetricValue"] { font-size: 1.8rem; }
    div[data-testid="stExpander"] div[role="button"] p { font-size: 1.1rem; font-weight: 600; }
    .suggestion-box { padding: 15px; border-radius: 10px; border-left: 5px solid; margin-bottom: 10px; }
    .tx-row { padding: 10px; border-bottom: 1px solid #333; }
    .stButton button { width: 100%; }
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
        if st.button("Sì, Elimina", type="primary", use_container_width=True):
            db.delete_transaction(tx_id)
            st.cache_data.clear()
            st.rerun()
    with col2:
        if st.button("Annulla", use_container_width=True):
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

# --- MAIN APP ---
def main():
    if 'user' not in st.session_state: st.session_state.user = None
    if 'edit_tx_id' not in st.session_state: st.session_state.edit_tx_id = None
    
    if not st.session_state.user:
        c1, c2, c3 = st.columns([1,2,1])
        with c2:
            st.title("💎 InvestAI Ultimate")
            tab1, tab2 = st.tabs(["Accedi", "Registrati"])
            with tab1:
                u = st.text_input("Username", key="l_u")
                p = st.text_input("Password", type="password", key="l_p")
                if st.button("Login", type="primary", use_container_width=True):
                    if db.login_user(u, p): st.session_state.user = u; st.rerun()
                    else: st.error("Errore credenziali")
            with tab2:
                nu = st.text_input("Nuovo Username", key="r_u")
                np = st.text_input("Nuova Password", type="password", key="r_p")
                if st.button("Crea Account", use_container_width=True):
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
            c_text = st.columns([1, 4])
            with c_text:
                if db.db_url == "SUPABASE_API_CONNECTION_ACTIVE":
                    st.markdown("☁️**Database:** <span style='color:green;'>Connesso</span>", unsafe_allow_html=True)
                    st.caption("Supabase Cloud API")
                else:
                    st.markdown("**Database:** <span style='color:red;'>Errore</span>", unsafe_allow_html=True)
        
        st.divider()

        # --- 4. LOGOUT ---
        if st.button("🚪 Esci dal Profilo", type="primary", use_container_width=True):
            st.session_state.user = None
            st.rerun()
            
        # Footer piccolo
        st.markdown("<div style='text-align: center; font-size: 0.7rem; color: #888; margin-top: 20px;'>InvestAI v2.0 • 2025</div>", unsafe_allow_html=True)

    # --- 1. DASHBOARD ANALISI MERCATO ---
    if page == "📊 Analisi Mercato":
        st.title("Analisi Mercato")

        with st.expander("ℹ️ Legenda Strategica e Segnali Tecnici", expanded=False):
                    st.markdown("""
                <div style="font-size: 0.9rem; color: #333; line-height: 1.5;">
                    L'algoritmo combina <b>Trend Following</b> (SMA 200) e <b>Mean Reversion</b> (RSI + Bollinger) filtrati dal <b>Momentum</b> (MACD).<br>
                    Ecco i 7 scenari tecnici identificati dal codice:
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
            if st.button("🔎 Scansiona Tutto il Mercato", use_container_width=True):
                with st.spinner("L'AI sta analizzando tutti gli asset in cerca di occasioni..."):
                    auto_data = get_data(AUTO_SCAN_TICKERS)
                    opportunities = []
                    golden_found = False
                    
                    for t in AUTO_SCAN_TICKERS:
                        if t in auto_data:
                            # 11 Valori
                            tl, act, col, pr, rsi, dd, reason, tgt, pot, risk_pr, risk_pot = evaluate_strategy_full(auto_data[t])
                            
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
                                    "risk_pot": risk_pot
                                })
                    
                    if opportunities:
                        opportunities = sorted(opportunities, key=lambda x: x['priority'], reverse=True)

                        if golden_found:
                            st.balloons()
                            st.success("💎 TROVATA UN'OPPORTUNITÀ D'ORO! PRESTARE MASSIMA ATTENZIONE.")

                        cols_rec = st.columns(3)
                        for idx, opp in enumerate(opportunities):
                            # Stile bordo: Oro per "Golden", standard verde/grigio per altri
                            border_style = "border: 2px solid #FFD700; box-shadow: 0 0 5px #FFD700;" if "ORO" in opp['action'] else "border: 1px solid #8bc34a;"
                            # Colore percentuale potenziale
                            pot_color = "#006400" if opp['potential'] > 0 else "#8b0000"
                            pot_str = f"+{opp['potential']:.1f}%"
                            with cols_rec[idx % 3]: 
                                st.markdown(f"""
                                <div class="suggestion-box" style="background-color:{opp['color']}; {border_style}">
                                    <div style="display:flex; justify-content:space-between;">
                                        <h4>{opp['ticker']}</h4>
                                        <span style="font-weight:bold; color:{pot_color};">{pot_str}</span>
                                    </div>
                                    <h3 style="color:#004d40; margin:5px 0;">{opp['action']}</h3>
                                    <p style="font-size:0.9rem;">{opp['reason']}</p>
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
                    
                    tl, act, col, pr, rsi, dd, reason, tgt, pot, risk_pr, risk_pot = evaluate_strategy_full(df)
                    
                    k1, k2, k3, k4 = st.columns(4)
                    k1.metric("Prezzo", f"${pr:,.2f}")
                    k2.metric("Target (Upside)", f"${tgt:,.2f}", delta=f"{pot:.1f}%")
                    k3.metric("Supporto (Rischio)", f"${risk_pr:,.2f}", delta=f"{risk_pot:.1f}%", delta_color="normal")
                    k4.metric("RSI", f"{rsi:.1f}")
                    
                    st.plotly_chart(create_modern_chart(df, selected_ticker, tl), use_container_width=True)
                    
                    st.markdown(f"""
                    <div class="suggestion-box" style="background-color: {col}; border-left: 6px solid #bbb;">
                        <h2 style="margin:0; color: #222;">💡 {act}</h2>
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
        if 'tx_page' not in st.session_state: st.session_state.tx_page = 0
        
        c_title, c_btn = st.columns([3, 1])
        with c_title: st.title("Gestione Portafoglio")
        with c_btn:
            if st.button("🔄 Aggiorna Dati", use_container_width=True):
                st.cache_data.clear()
                st.rerun()
        
        pf, history = db.get_portfolio_summary(user)
        
        # --- CALCOLO TOTALE PORTAFOGLIO ---
        tot_val = 0 # Variabile fondamentale, usata dopo
        if pf:
            tickers = list(pf.keys())
            market_data = get_data(tickers)
            
            pie_data = []
            tot_cost = 0
            
            for t in tickers:
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

            with st.container(border=True):
                m1, m2, m3 = st.columns(3)
                m1.metric("Valore Portafoglio", f"€{tot_val:,.2f}")
                m2.metric("Utile/Perdita Totale", f"€{pnl_tot:,.2f}", delta=f"{pnl_tot_pct:.2f}%")
                m3.metric("Asset Diversi", len(pf))
            
            st.subheader("💡 Strategia Operativa")
            with st.expander("ℹ️ Legenda Comandi (Logica Dinamica)", expanded=False):
                st.markdown("""
                <div style="font-size: 0.85rem; line-height: 1.4; color: #333;">
                    L'Advisor analizza ogni posizione in base alla volatilità dell'asset (ATR) e al Trend di fondo.
                    <h5 style="margin-bottom:5px; margin-top:10px; color: #006400;">🟢 GESTIONE PROFITTI</h5>
                    <ul style="padding-left: 20px; margin-bottom: 10px;">
                        <li>🚀 <b>MOONBAG / TREND SANO:</b> Il profitto è solido e il trend è rialzista. La strategia migliore è non fare nulla e lasciar correre i guadagni.</li>
                        <li>💰 <b>TAKE PROFIT / VENDI METÀ:</b> Il guadagno è ottimo ma l'RSI indica "euforia" o ipercomprato. Il sistema consiglia di incassare una parte per sicurezza.</li>
                        <li>🚨 <b>INCASSA TUTTO / PROTEGGI:</b> Avevi un ottimo guadagno ma il Trend è cambiato in Negativo (Bear). Priorità assoluta: portare a casa i soldi prima che spariscano.</li>
                        <li>⚠️ <b>ATTENZIONE (Break Even):</b> Sei in leggero utile ma il trend è brutto. Alza lo Stop Loss al tuo prezzo di ingresso per non rischiare di andare in rosso.</li>
                        <li>✋ <b>MANTIENI:</b> Situazione stabile o movimento non significativo (rumore di mercato).</li>
                    </ul>
                    <h5 style="margin-bottom:5px; margin-top:10px; color: #8b0000;">🔴 GESTIONE PERDITE</h5>
                    <ul style="padding-left: 20px; margin-bottom: 10px;">
                        <li>🛒 <b>MEDIA IL PREZZO (Accumulo):</b> Sei in perdita, MA il trend di lungo periodo è positivo e il prezzo è a sconto. È un'opportunità matematica per abbassare il tuo prezzo medio.</li>
                        <li>⚠️ <b>VALUTA VENDITA (Cut Loss):</b> Sei in perdita e il trend è negativo. Non ci sono segnali di ripresa. La statistica suggerisce di tagliare la perdita (Stop Loss) per salvare il capitale residuo.</li>
                    </ul>
                </div>
                """, unsafe_allow_html=True)
            
            valid_pf = [item for item in pf.items() if item[0] in market_data]
            sorted_pf = sorted(valid_pf, key=lambda x: x[1]['pnl_pct'])
            
            if sorted_pf:
                cols_adv = st.columns(3)
                for i, (sym, dat) in enumerate(sorted_pf):
                    tit, adv, col = generate_portfolio_advice(market_data[sym], dat['avg_price'], dat['cur_price'])
                    _, _, _, _, _, _, _, tgt, pot, risk_pr, risk_pot = evaluate_strategy_full(market_data[sym])
                    
                    val_attuale_asset = dat['qty'] * dat['cur_price']
                    # FIX: Uso tot_val (calcolato sopra) invece di tot_val_portfolio
                    percentuale_allocazione = (val_attuale_asset / tot_val * 100) if tot_val > 0 else 0
                    
                    with cols_adv[i % 3]:
                        st.markdown(f"""
                        <div class="suggestion-box" style="background-color:{col}; border: 1px solid #bbb; min-height: 280px;">
                            <div style="display:flex; justify-content:space-between;"><strong>{sym}</strong><span style="color:{'green' if dat['pnl_pct']>=0 else 'red'}; font-weight:bold;">{dat['pnl_pct']:.1f}%</span></div>
                            <h3 style="margin:5px 0; color: #222;">{tit}</h3>
                            <p style="font-size:0.9rem; margin-bottom: 5px;">{adv}</p>
                            <hr style="margin: 5px 0; border-color: rgba(0,0,0,0.1);">
                            <div style="font-size: 0.8rem; display: flex; justify-content: space-between; margin-bottom: 5px;">
                                <span>Prezzo: €{dat['cur_price']:.2f}</span>
                                <span>Tot: <b>€{val_attuale_asset:,.0f}</b></span>
                            </div>
                            <div style="font-size: 0.8rem; text-align: right; margin-bottom: 10px;">Allocazione: <b>{percentuale_allocazione:.1f}%</b></div>
                            <div style="padding: 8px; background-color: rgba(255,255,255,0.6); border-radius: 6px; border: 1px dashed #666;">
                                <div style="font-size: 0.7rem; text-transform: uppercase; color: #555; font-weight: bold; margin-bottom: 4px; text-align:center;">Scenari Tecnici</div>
                                <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.85rem;">
                                    <span style="color: #006400;">✅ <b>+{pot:.1f}%</b></span>
                                    <span style="color: #333;">|</span>
                                    <span style="color: #b30000;">🔻 <b>{risk_pot:.1f}%</b></span>
                                </div>
                                <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.75rem; color: #444; margin-top:2px;">
                                    <span>Tgt: ${tgt:.0f}</span>
                                    <span>Risk: ${risk_pr:.0f}</span>
                                </div>
                            </div>
                        </div>""", unsafe_allow_html=True)

            st.divider()
            c_pie, c_det = st.columns([1, 2])
            with c_pie:
                fig = go.Figure(data=[go.Pie(labels=[x['Label'] for x in pie_data], values=[x['Value'] for x in pie_data], hole=.4)])
                fig.update_layout(margin=dict(t=0,b=0,l=0,r=0), height=250, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
            with c_det:
                perf_df = pd.DataFrame([
                    {
                        "Asset": t, 
                        "Costo Totale": pf[t]['total_cost'], 
                        "Prezzo Medio": pf[t]['avg_price'], 
                        "Prezzo Attuale": pf[t]['cur_price'], 
                        "P&L %": pf[t]['pnl_pct'], 
                        "Valore": pf[t]['qty'] * pf[t]['cur_price']
                    } for t in tickers
                ])
                
                st.dataframe(
                    perf_df, 
                    hide_index=True, 
                    use_container_width=True, 
                    column_config={
                        "P&L %": st.column_config.NumberColumn(format="%.2f%%"),
                        "Valore": st.column_config.NumberColumn(format="€%.2f"),
                        "Costo Totale": st.column_config.NumberColumn(format="€%.2f"),
                        "Prezzo Attuale": st.column_config.NumberColumn(format="€%.2f"),
                        "Prezzo Medio": st.column_config.NumberColumn(format="€%.2f")
                    }
                )
        else: st.info("Portafoglio vuoto.")

        st.divider()
        
        # --- MODIFICA TRANSAZIONE ---
        if st.session_state.edit_tx_id:
            tx = db.get_transaction_by_id(st.session_state.edit_tx_id)
            if tx:
                with st.form("edit"):
                    st.write(f"Modifica {tx[1]} ({tx[5]})")
                    c1,c2,c3,c4 = st.columns(4)
                    nq = c1.number_input("Qta", value=float(tx[2]))
                    np = c2.number_input("Prezzo", value=float(tx[3]))
                    current_fee = float(tx[6]) if len(tx) > 6 and tx[6] is not None else 0.0
                    nf = c3.number_input("Commissioni (€)", value=current_fee, step=0.5)
                    nd = c4.date_input("Data", datetime.strptime(tx[4], '%Y-%m-%d').date())
                    
                    if st.form_submit_button("Salva Modifiche"): 
                        db.update_transaction(tx[0], tx[1], nq, np, str(nd), tx[5], nf) 
                        st.session_state.edit_tx_id=None; st.cache_data.clear(); st.rerun()
                    if st.form_submit_button("Annulla"): st.session_state.edit_tx_id=None; st.rerun()

        # --- STORICO TRANSAZIONI ---
        c_l, c_a = st.columns([2, 1])
        with c_l:
            st.subheader("Storico Transazioni")
            raw = db.get_all_transactions(user)
            
            if raw:
                search_query = st.text_input("🔍 Cerca transazione (Ticker o Data)", placeholder="Es. NVDA o 2023-10...").upper()
                filtered_tx = [r for r in raw if search_query in r[1] or search_query in str(r[4])] if search_query else raw
                
                total_tx = len(filtered_tx)
                st.caption(f"Totale transazioni trovate: **{total_tx}**")
                
                ITEMS_PER_PAGE = 10
                start_idx = st.session_state.tx_page * ITEMS_PER_PAGE
                end_idx = start_idx + ITEMS_PER_PAGE
                
                col_prev, col_page, col_next = st.columns([1, 2, 1])
                with col_prev:
                    if st.session_state.tx_page > 0:
                        if st.button("⬅️ Prec"): st.session_state.tx_page -= 1; st.rerun()
                with col_next:
                    if end_idx < total_tx:
                        if st.button("Succ ➡️"): st.session_state.tx_page += 1; st.rerun()
                
                view_tx = filtered_tx[start_idx:end_idx]

                h1, h2, h3, h4, h5, h6 = st.columns([1.2, 1.5, 1, 1, 1, 1])
                h1.markdown("**Data**"); h2.markdown("**Asset**"); h3.markdown("**Qta**"); h4.markdown("**Prezzo**"); h5.markdown("**Comm.**"); h6.markdown("**Azioni**")
                st.divider()
                
                for r in view_tx:
                    with st.container():
                        c1, c2, c3, c4, c5, c6 = st.columns([1.2, 1.5, 1, 1, 1, 1])
                        c1.write(r[4])
                        c2.markdown(f":{'green' if r[5]=='BUY' else 'red'}[{r[5]}] **{r[1]}**")
                        c3.write(f"{r[2]:.4f}")
                        c4.write(f"€{r[3]:.2f}")
                        fee_val = r[6] if len(r) > 6 and r[6] is not None else 0.0
                        c5.write(f"€{fee_val:.2f}")
                        
                        b1, b2 = c6.columns(2)
                        if b1.button("✏️", key=f"e{r[0]}", help="Modifica"): st.session_state.edit_tx_id=r[0]; st.rerun()
                        if b2.button("❌", key=f"d{r[0]}", help="Elimina"): 
                            confirm_delete_dialog(r[0])
                        st.markdown("<hr style='margin:2px 0; border-top:1px solid #333;'>", unsafe_allow_html=True)
            else: st.write("Nessuna transazione registrata.")

        with c_a:
            with st.expander("➕ Aggiungi Transazione", expanded=False):
                with st.container(border=True):
                    n_sym = st.selectbox("Asset", ["BTC-USD", "ETH-USD", "AAPL", "NVDA", "ALTRO"], key="ns")
                    if n_sym == "ALTRO": n_sym = st.text_input("Ticker", key="ncs").upper()
                    n_qty = st.number_input("Qta", min_value=0.0001, format="%.4f", key="nq")
                    n_prc = st.number_input("Prezzo Unitario (€)", min_value=0.01, key="np")
                    n_fee = st.number_input("Commissioni (€)", min_value=0.0, step=0.5, key="nf") 
                    n_date = st.date_input("Data", date.today(), key="nd")
                    n_type = st.selectbox("Tipo", ["BUY", "SELL"], key="nt")
                    
                    if st.button("Salva Transazione", type="primary", use_container_width=True):
                        if validate_ticker(n_sym): 
                            db.add_transaction(user, n_sym, n_qty, n_prc, str(n_date), n_type, n_fee)
                            st.cache_data.clear()
                            st.success("Fatto!"); st.rerun()
                        else: st.error("Ticker invalido")

    # --- 3. CONSIGLI OPERATIVI ---
    elif page == "💡 Consigli":
        st.title("L'AI Advisor")
        st.markdown("Analisi completa di tutti gli asset in portafoglio e nuove opportunità.")

        if st.button("🔄 Analizza Situazione", use_container_width=True):
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
                    _, act, col, pr, rsi, dd, res, tgt, pot, r_pr, r_pot = evaluate_strategy_full(market_data[t])
                    
                    if "ACQUISTA" in act or "ORO" in act:
                        actions_new_entry.append({
                            "ticker": t, "title": act, "desc": res, 
                            "color": col, "price": pr, "rsi": rsi,
                            "target": tgt, "potential": pot,
                            "risk": r_pr, "risk_pot": r_pot
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
                    with cols[i%3]: 
                        st.markdown(f"""
                        <div class="suggestion-box" style="background-color:{item['color']}; border: 2px solid #d32f2f;">
                            <div style="display:flex; justify-content:space-between;">
                                <h4>{item['ticker']}</h4>
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
                    with cols[i%3]: 
                        st.markdown(f"""
                        <div class="suggestion-box" style="background-color:{item['color']}; border: 2px solid #2e7d32;">
                            <div style="display:flex; justify-content:space-between;">
                                <h4>{item['ticker']}</h4>
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
                    # Colore testo dinamico
                    text_color = "#333"
                    if "MOONBAG" in item['title']: text_color = "#2e7d32"
                    elif "ATTENZIONE" in item['title']: text_color = "#f57f17"
                    
                    pnl_color = "green" if item['pnl'] >= 0 else "red"

                    with cols[i%3]: 
                        st.markdown(f"""
                        <div class="suggestion-box" style="background-color:{item['color']}; border: {item['border']};">
                            <div style="display:flex; justify-content:space-between;">
                                <h4>{item['ticker']}</h4>
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
                    # Bordo speciale per "ORO", altrimenti bordo standard grigio/verde
                    border_style = "border: 2px solid #FFD700; box-shadow: 0 0 5px #FFD700;" if "ORO" in item['title'] else "border: 1px solid #8bc34a;"
                    
                    with cols[i%3]: 
                        st.markdown(f"""
                        <div class="suggestion-box" style="background-color:{item['color']}; {border_style}">
                            <div style="display:flex; justify-content:space-between;">
                                <h4>{item['ticker']}</h4>
                                <span style="font-weight:bold; color:#006400;">+{item['potential']:.1f}%</span>
                            </div>
                            <h3 style="color:#004d40; margin:5px 0;">{item['title']}</h3>
                            <p style="font-size:0.9rem;">{item['desc']}</p>
                            <div style="margin-top:8px; border-top: 1px solid rgba(0,0,0,0.1); padding-top:5px;">
                                <div style="display:flex; justify-content:space-between; font-size:0.85rem;">
                                    <span>Target: <b>${item['target']:.1f}</b></span>
                                    <span style="color:#b71c1c;">Risk: <b>{item['risk_pot']:.1f}%</b></span>
                                </div>
                                <div style="text-align:right; font-size:0.8rem; margin-top:4px; color:#555;">
                                    Prezzo: ${item['price']:.2f} | RSI: {item['rsi']:.0f}
                                </div>
                            </div>
                        </div>""", unsafe_allow_html=True)

            if not (actions_sell or actions_buy_more or actions_hold or actions_new_entry):
                st.info("Nessun dato disponibile per generare consigli.")

    # --- 4. IMPOSTAZIONI ---
    elif page == "⚙️ Impostazioni":
        st.title("Impostazioni Notifiche")
        
        st.info("Per ricevere consigli automatici ogni mattina su Telegram, devi inserire il tuo Chat ID.")
        
        with st.container(border=True):
            st.subheader("Configurazione Telegram")
            
            current_id = db.get_user_chat_id(user)
            chat_id_input = st.text_input("Inserisci il tuo Telegram Chat ID", value=current_id, help="Cerca @userinfobot su Telegram per scoprire il tuo ID")
            
            if st.button("💾 Salva ID", type="primary"):
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

if __name__ == "__main__":
    main()











