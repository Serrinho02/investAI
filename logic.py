import streamlit as st
from st_supabase_connection import SupabaseConnection
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import hashlib
import os
import logging
from passlib.context import CryptContext

# --- CONFIGURAZIONE LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- CONFIGURAZIONE HASHING ---
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"], 
    deprecated="auto",
    # Impostiamo il fattore di lavoro per una sicurezza moderna (aumenta le iterazioni)
    pbkdf2_sha256__default_rounds=300000 
)

# --- CONFIGURAZIONE TELEGRAM ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

# --- ASSET LIST COMPLETA ---
POPULAR_ASSETS = {
    # --- INDICI GLOBALI ---
    "S&P 500 (USA)": "SPY", "Nasdaq 100 (Tech)": "QQQ", 
    "Russell 2000 (Small Cap)": "IWM", "Dow Jones": "DIA",
    "All-World": "VWCE.DE", "Emerging Markets": "EEM", "Europe Stoxx 50": "FEZ",
    "China (Large Cap)": "FXI", "China (Internet)": "KWEB", "India": "INDA",
    "Brazil": "EWZ", "Japan": "EWJ", "UK (FTSE 100)": "EWU", "Germany (DAX)": "EWG",
    # --- MATERIE PRIME & METALLI ---
    "Gold": "GLD", "Silver": "SLV", "Oil (WTI)": "USO", 
    "Natural Gas": "UNG", "Copper (Miners)": "COPX", 
    "Uranium": "URA", "Agriculture": "DBA",
    # --- IMMOBILIARE & OBBLIGAZIONI ---
    "Real Estate (US)": "VNQ", "US Treasury 20Y+": "TLT", 
    "US Treasury 1-3Y": "SHY", "Corporate Bonds": "LQD",
    # --- SETTORI USA & MEGATREND ---
    "Semiconductors": "SMH", "Technology": "XLK", "Healthcare": "XLV", 
    "Financials": "XLF", "Energy": "XLE", "Materials": "XLB", 
    "Industrials": "XLI", "Consumer Disc. (Amazon/Tesla)": "XLY", 
    "Consumer Staples (Coca/Pepsi)": "XLP", "Utilities": "XLU",
    "Clean Energy": "ICLN", "Cybersecurity": "CIBR", "Robotics & AI": "BOTZ",
    "Defense & Aerospace": "ITA", "Biotech": "XBI",
    # --- CRYPTO ---
    "Bitcoin": "BTC-USD", "Ethereum": "ETH-USD", "Solana": "SOL-USD",
    "Ripple": "XRP-USD", "Binance Coin": "BNB-USD", "Cardano": "ADA-USD",
    "Dogecoin": "DOGE-USD", "Chainlink": "LINK-USD", "Polkadot": "DOT-USD",
    # --- BIG TECH (USA) ---
    "Nvidia": "NVDA", "Apple": "AAPL", "Microsoft": "MSFT", "Tesla": "TSLA", 
    "Amazon": "AMZN", "Meta": "META", "Google": "GOOGL", 
    "Netflix": "NFLX", "AMD": "AMD", "Palantir": "PLTR", "Coinbase": "COIN",
    # --- BIG EUROPE (GRANOLAS) ---
    "ASML (Chip)": "ASML", "LVMH (Luxury)": "MC.PA", 
    "Novo Nordisk (Pharma)": "NVO", "SAP (Software)": "SAP",
    # --- ITALIA (FTSE MIB) ---
    "Ferrari": "RACE.MI", "Intesa Sanpaolo": "ISP.MI", "UniCredit": "UCG.MI", 
    "Enel": "ENEL.MI", "Eni": "ENI.MI", "Stellantis": "STLAM.MI", 
    "Leonardo": "LDO.MI", "Generali": "G.MI", "Moncler": "MONC.MI", 
    "Poste Italiane": "PST.MI", "Terna": "TRN.MI", "Snam": "SRG.MI", 
    "Mediobanca": "MB.MI", "Tenaris": "TEN.MI", "Prysmian": "PRY.MI"
}

AUTO_SCAN_TICKERS = [v for k, v in POPULAR_ASSETS.items() if v is not None]

# --- DATABASE MANAGER (Supabase API Version - Compatibility Mode) ---
class DBManager:
    def __init__(self):
        # Placeholder per evitare crash del debug in app.py
        self.db_url = "SUPABASE_API_CONNECTION_ACTIVE"
        
        try:
            # Inizializza la connessione usando i secrets [connections.supabase]
            self.conn = st.connection("supabase", type=SupabaseConnection)
            # Accesso diretto al client Supabase
            self.client = self.conn.client 
        except Exception as e:
            st.error(f"❌ Errore connessione Supabase: {e}")
            st.stop()

    # --- METODI UTENTE ---
    
    def register_user(self, u, p):
        h = hash_password(p)
        try:
            res = self.client.table("users").insert({"username": u, "password": h}).execute()
            return len(res.data) > 0
        except Exception as e: # MODIFICATO
            logger.error(f"Errore registrazione utente {u}: {e}") # AGGIUNTO
            return False

    def login_user(self, u, p):
        try:
            res = self.client.table("users").select("password").eq("username", u).execute()
            if res.data and len(res.data) > 0:
                hashed_password = res.data[0]['password']
                return verify_password(p, hashed_password) # MODIFICATO: Usa verify_password
            return False
        except Exception as e:
            logger.error(f"Errore login utente {u}: {e}")
            return False

    def change_password(self, username, new_password):
        """Aggiorna la password dell'utente"""
        h = hash_password(new_password) # MODIFICATO: Usa la funzione hash_password
        try:
            res = self.client.table("users").update({"password": h}).eq("username", username).execute()
            return len(res.data) > 0
        except Exception as e:
            print(f"Errore cambio password: {e}")
            return False
    
    def save_chat_id(self, user, chat_id):
        try:
            # Salva l'ID pulito (rimuove eventuali STOP_ se presenti nel DB per errore)
            res = self.client.table("users").update({"tg_chat_id": str(chat_id)}).eq("username", user).execute()
            return len(res.data) > 0
        except Exception as e:
            print(f"❌ ERRORE save_chat_id: {e}")
            return False

    def disable_notifications(self, user, chat_id):
        try:
            stop_id = f"STOP_{chat_id}"
            res = self.client.table("users").update({"tg_chat_id": stop_id}).eq("username", user).execute()
            return len(res.data) > 0
        except Exception as e:
            print(f"❌ ERRORE disable_notifications: {e}")
            return False  

    def get_user_chat_id(self, user):
        try:
            res = self.client.table("users").select("tg_chat_id").eq("username", user).execute()
            if res.data and len(res.data) > 0:
                raw_id = res.data[0].get("tg_chat_id", "")
                # Pulisce l'ID per mostrarlo nel sito
                return raw_id.replace("STOP_", "")
            return ""
        except Exception as e: # MODIFICATO
            logger.error(f"Errore get_user_chat_id per {user}: {e}") # AGGIUNTO
            return ""

    def get_users_with_telegram(self):
        """Ritorna solo gli utenti che NON hanno STOP_ nel loro ID"""
        try:
            res = self.client.table("users").select("username, tg_chat_id").neq("tg_chat_id", "").execute()
            # Filtro Python: escludi chi inizia con STOP_
            return [(r['username'], r['tg_chat_id']) for r in res.data if not r['tg_chat_id'].startswith("STOP_")]
        except Exception as e:
            print(f"❌ ERRORE get_users_with_telegram: {e}")
            return []

    def get_user_by_chat_id(self, chat_id):
        """Trova l'utente sia se attivo (ID pulito) sia se stoppato (STOP_ID)"""
        try:
            # 1. Cerca l'ID normale
            res = self.client.table("users").select("username").eq("tg_chat_id", str(chat_id)).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]['username']
            # 2. Se non lo trova, cerca l'ID con prefisso STOP_
            stop_id = f"STOP_{chat_id}"
            res = self.client.table("users").select("username").eq("tg_chat_id", stop_id).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]['username']
            return None
        except Exception as e:
            print(f"❌ ERRORE get_user_by_chat_id: {e}")
            return None

    # --- METODI TRANSAZIONI ---
    
    def add_transaction(self, user, symbol, qty, price, date_str, type="BUY", fee=0.0):
        data = {
            "username": user,
            "symbol": symbol.upper(),
            "quantity": float(qty),
            "price": float(price),
            "date": date_str,
            "type": type,
            "fee": float(fee)
        }
        try:
            self.client.table("transactions").insert(data).execute()
            return True
        except Exception as e: # MODIFICATO
            logger.error(f"Errore aggiunta transazione per {user} ({symbol}): {e}") # AGGIUNTO
            return False

    def update_transaction(self, t_id, symbol, qty, price, date_str, type, fee=0.0):
        data = {
            "symbol": symbol.upper(),
            "quantity": float(qty),
            "price": float(price),
            "date": date_str,
            "type": type,
            "fee": float(fee)
        }
        try:
            self.client.table("transactions").update(data).eq("id", t_id).execute()
            return True
        except Exception as e: # MODIFICATO
            logger.error(f"Errore aggiornamento transazione ID {t_id}: {e}") # AGGIUNTO
            return False

    def delete_transaction(self, t_id):
        try:
            self.client.table("transactions").delete().eq("id", t_id).execute()
            return True
        except Exception as e: # MODIFICATO
            logger.error(f"Errore eliminazione transazione ID {t_id}: {e}") # AGGIUNTO
            return False

    def get_all_transactions(self, user):
        try:
            # API: Ottiene i dati come dizionario
            res = self.client.table("transactions").select("*").eq("username", user).order("date", desc=True).execute()
            
            # --- FIX FONDAMENTALE PER APP.PY ---
            # Convertiamo i Dizionari in Tuple nell'ordine esatto che app.py si aspetta:
            # (id, symbol, quantity, price, date, type, fee)
            # Indici: 0=id, 1=sym, 2=qty, 3=price, 4=date, 5=type, 6=fee
            
            clean_rows = []
            for r in res.data:
                clean_rows.append((
                    r['id'], 
                    r['symbol'], 
                    float(r['quantity']), 
                    float(r['price']), 
                    r['date'], 
                    r['type'], 
                    float(r.get('fee', 0.0))
                ))
            return clean_rows
        except Exception as e:
            print(f"Errore fetch tx: {e}")
            return []

    def get_transaction_by_id(self, t_id):
        try:
            res = self.client.table("transactions").select("*").eq("id", t_id).execute()
            if res.data:
                r = res.data[0]
                # Anche qui, restituiamo una Tupla per il form di modifica
                return (r['id'], r['symbol'], r['quantity'], r['price'], r['date'], r['type'], r.get('fee', 0.0))
            return None
        except Exception as e: # MODIFICATO
            logger.error(f"Errore get_transaction_by_id per ID {t_id}: {e}") # AGGIUNTO
            return None

    def get_portfolio_summary(self, user):
        # Ora get_all_transactions restituisce TUPLE, quindi usiamo gli indici numerici
        rows = self.get_all_transactions(user)
        portfolio = {}
        history = [] 
        
        for row in rows:
            # Usa INDICI NUMERICI (Tupla)
            sym = row[1]
            qty = float(row[2])
            price = float(row[3])
            dt = row[4]
            type_tx = row[5]
            fee = float(row[6])

            if sym not in portfolio: portfolio[sym] = {"qty": 0.0, "total_cost": 0.0, "avg_price": 0.0}
            
            if type_tx == "BUY":
                portfolio[sym]["qty"] += qty
                portfolio[sym]["total_cost"] += (qty * price) + fee
            elif type_tx == "SELL":
                portfolio[sym]["qty"] -= qty
                portfolio[sym]["total_cost"] -= (qty * price)
            
            if portfolio[sym]["qty"] > 0.000001:
                portfolio[sym]["avg_price"] = portfolio[sym]["total_cost"] / portfolio[sym]["qty"]
            else:
                portfolio[sym]["avg_price"] = 0
                portfolio[sym]["total_cost"] = 0
                
            history.append({"symbol": sym, "date": dt, "price": price, "type": type_tx, "fee": fee})

        return {k: v for k, v in portfolio.items() if v["qty"] > 0.0001}, history

# --- HELPER HASHING ---
def hash_password(password) -> str:
    """Genera l'hash della password usando PBKDF2 (Python puro)."""
    p_str = str(password) if password else "" 
    # RIMOZIONE LOGICA DI TRONCAMENTO E FALLBACK
    if not p_str:
        # Se la password è vuota, blocchiamo l'azione o usiamo una stringa placeholder nota (come fatto prima).
        # Poiché il tuo sito gestisce già le stringhe vuote come errore di input,
        # qui assumiamo che la password non sia vuota, o usiamo un hash per una stringa vuota.
        p_str = "" # Useremo un hash per la stringa vuota se l'input non viene validato prima.
    return pwd_context.hash(p_str) # L'hashing PBKDF2 può accettare stringhe lunghe

def verify_password(plain_password, hashed_password: str) -> bool:
    """Verifica la password in chiaro contro l'hash memorizzato."""
    p_str = str(plain_password) if plain_password else ""
    # RIMOZIONE LOGICA DI TRONCAMENTO
    return pwd_context.verify(p_str, hashed_password)

# --- HELPER FUNCTIONS ---
def validate_ticker(ticker):
    if not ticker: return False
    try:
        t = yf.Ticker(ticker)
        # Fast check: history(period="1d") è molto più veloce e affidabile
        return len(t.history(period="1d")) > 0
    except Exception as e: # MODIFICATO
        logger.debug(f"Validazione fallita per {ticker}: {e}") # AGGIUNTO
        return False

def get_data_raw(tickers):
    """
    Funzione Universale per scaricare dati. 
    Gestisce il download sia di singoli ticker che di liste, 
    risolvendo i problemi di MultiIndex di yfinance.
    """
    if not tickers: return {}
    data = {}
    
    # Pulizia e Unicità
    unique_tickers = list(set([t.strip().upper() for t in tickers if t]))
    if not unique_tickers: return {}

    try:
        # 1. Scarichiamo sempre con group_by='ticker' per avere una struttura coerente
        df = yf.download(unique_tickers, period="2y", group_by='ticker', progress=False, auto_adjust=False)
        
        if df.empty:
            return {}

        # 2. Iteriamo su ogni ticker richiesto e cerchiamo di estrarlo
        for t in unique_tickers:
            asset_df = pd.DataFrame()
            
            try:
                # CASO A: Il ticker è nel livello superiore delle colonne (MultiIndex tipico)
                if isinstance(df.columns, pd.MultiIndex) and t in df.columns.get_level_values(0):
                    asset_df = df[t].copy()
                
                # CASO B: Un solo ticker richiesto, yfinance a volte non mette il livello ticker
                elif len(unique_tickers) == 1:
                    # Se le colonne sono semplici (es. 'Close', 'Open'), usiamo tutto il df
                    if 'Close' in df.columns:
                        asset_df = df.copy()
                    # Se sono MultiIndex ma non abbiamo trovato il ticker prima, proviamo a spianare
                    elif isinstance(df.columns, pd.MultiIndex):
                        asset_df = df.copy()
                        asset_df.columns = asset_df.columns.get_level_values(0)
            
                # 3. Processiamo solo se abbiamo dati validi
                if not asset_df.empty and 'Close' in asset_df.columns:
                    # Rimuoviamo righe con NaN critici
                    asset_df.dropna(subset=['Close'], inplace=True)
                    # Chiamiamo la tua funzione process_df esistente
                    process_df(asset_df, data, t)
                    
            except Exception as e:
                # print(f"Errore estrazione dati per {t}: {e}") # Debug opzionale
                continue
                
        return data

    except Exception as e:
        print(f"Errore download generale: {e}")
        return {}

def process_df(df, data, t):
    if len(df) < 205: 
        return 
    df = df.dropna(how='all')
    try:
        df['RSI'] = ta.rsi(df['Close'], length=14)
        df['SMA_200'] = ta.sma(df['Close'], length=200)
        df['SMA_50'] = ta.sma(df['Close'], length=50)
        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        macd = ta.macd(df['Close'])
        if macd is not None and not macd.empty:
            df['MACD'] = macd.iloc[:, 0]
            df['MACD_SIGNAL'] = macd.iloc[:, 2]
        else:
            return   
        bb = ta.bbands(df['Close'], length=20, std=2)
        if bb is not None and not bb.empty:
            df['BBL'] = bb.iloc[:, 0]
            df['BBU'] = bb.iloc[:, 2]
        else:
            return    
        df_clean = df.dropna()
        if not df_clean.empty:
            data[t] = df_clean     
    except Exception as e:
        logger.warning(f"Errore calcolo indicatori per {t}: {e}")


# --- NUOVA FUNZIONE: BACKTESTING E PROBABILITÀ ---
def run_backtest(df, days_list=[30, 60, 90]):
    """
    Esegue un backtest storico sulla strategia d'acquisto 'Dip' e 'Golden'.
    Ritorna: Win Rate per [30, 60, 90] giorni e PnL medio per [30, 60, 90] giorni.
    """
    df_copy = df.copy()
    # 1. Identifica i segnali di acquisto ('Buy the Dip' o 'Golden Entry')
    # Questi sono segnali in cui: Trend è rialzista (Close > SMA200) E (RSI < 40 OPPURE Prezzo vicino a BBL)
    df_copy['Signal'] = ((df_copy['Close'] > df_copy['SMA_200']) & 
                         ((df_copy['RSI'] < 40) | (df_copy['Close'] <= df_copy['BBL'] * 1.01)))
    entry_dates = df_copy[df_copy['Signal']].index.tolist()
    if not entry_dates:
        return 0, 0, 0, 0, 0, 0
    total_signals = len(entry_dates)
    results = {days: {"wins": 0, "pnl_sum": 0.0} for days in days_list}
    for entry_date in entry_dates:
        entry_price = df_copy.loc[entry_date, 'Close']
        for days in days_list:
            # Trova la data di uscita (uscita = n giorni lavorativi dopo)
            # Uso shift(days) per trovare il prezzo n giorni "dopo"
            exit_idx = df_copy.index.get_loc(entry_date) + days
            if exit_idx < len(df_copy):
                exit_price = df_copy.iloc[exit_idx]['Close']
                pnl = (exit_price - entry_price) / entry_price
                results[days]["pnl_sum"] += pnl
                if pnl > 0:
                    results[days]["wins"] += 1
    # Calcola le metriche finali
    win_rates = [0.0] * len(days_list)
    avg_pnls = [0.0] * len(days_list)
    for i, days in enumerate(days_list):
        if total_signals > 0:
            win_rates[i] = (results[days]["wins"] / total_signals) * 100
            avg_pnls[i] = (results[days]["pnl_sum"] / total_signals) * 100
    # Ritorna: Win_30, PnL_30, Win_60, PnL_60, Win_90, PnL_90
    return win_rates[0], avg_pnls[0], win_rates[1], avg_pnls[1], win_rates[2], avg_pnls[2]

# --- NUOVA FUNZIONE: CALCOLO CONFIDENCE SCORE (0-100) ---
def calculate_confidence(df, is_bullish, action, potential_upside, potential_downside, w30, p30, w60, p60, w90, p90):
    """
    Calcola un punteggio di fiducia da 0 a 100 per il segnale BUY/SELL.
    Pesatura Concettuale: Trend (30%) + Setup (25%) + Rischio (15%) + Backtest (30%)
    """
    if df.empty or action not in ["🛒 ACQUISTA ORA! (Dip)", "💎 OPPORTUNITÀ D'ORO"]:
        # Il Confidence Score è calcolato solo per i segnali di acquisto più forti.
        return 0

    last_close = df['Close'].iloc[-1]
    last_sma50 = df['SMA_50'].iloc[-1]
    last_sma200 = df['SMA_200'].iloc[-1]
    last_rsi = df['RSI'].iloc[-1]
    
    # 1. Trend Strength (30%): Distanza dalla SMA 200 (Normalizzata 0-30 punti)
    # Più siamo lontani dalla SMA200 (ma sopra), più il trend è solido.
    # Usiamo SMA50 come proxy per momentum a breve termine.
    trend_score = 0
    if is_bullish:
        # 1a. Se Close > SMA200 (Trend primario)
        trend_factor = min(1.0, (last_close - last_sma200) / last_sma200 * 10) # 10% sopra SMA200 = 1.0
        
        # 1b. Se anche SMA50 > SMA200 (Trend secondario/momentum)
        if last_sma50 > last_sma200:
             trend_factor *= 1.2 # Bonus per momentum
        
        trend_score = min(30, trend_factor * 30) # Max 30 punti

    # 2. Setup Quality (25%): Profondità del Dip (RSI) e Estremità (Golden vs Dip)
    setup_score = 0
    if "ORO" in action:
        setup_score = 25 # Golden Entry ottiene il massimo
    else: # ACQUISTA ORA! (Dip)
        # Più il prezzo è ipervenduto (RSI basso), migliore è il punto di entrata.
        # RSI 40 -> 0 punti, RSI 20 -> 25 punti
        setup_factor = max(0, 40 - last_rsi) / 20 
        setup_score = min(25, setup_factor * 25)

    # 3. Volatility / Risk (15%): Rapporto Rischio/Rendimento Immediato
    risk_score = 0
    if potential_upside > 0 and potential_downside < 0:
        # Rapporto R:R (espresso in percentuale)
        risk_reward_ratio = potential_upside / abs(potential_downside) 
        # R:R di 2:1 (RR=2) è ottimo. R:R di 0.5:1 (RR=0.5) è basso.
        # Normalizziamo RR in modo che 2.0 dia circa 15 punti.
        risk_score = min(15, risk_reward_ratio / 0.15) # 15/0.15 = 100 max, ma la normalizzazione è più complessa in pratica
        # Una R:R di 2.0 (ossia 2/0.15) è 13.33 punti, ottimo.
        risk_score = min(15, risk_score)

    # 4. Backtest Reliability (30%): Win Rate (30G) e PnL Medio (90G)
    # Bilanciamo la performance a breve termine (Win30) con il risultato a lungo termine (PnL90)
    backtest_score = 0
    if w30 > 0:
        # Ponderazione 1: Successo a breve termine (Win Rate 30G)
        win_rate_weight = (w30 / 100) * 15 # Max 15 punti (se 100% Win Rate)
        
        # Ponderazione 2: Forza a lungo termine (PnL Medio 90G)
        # Se PnL90 è positivo, è un segnale più robusto nel tempo.
        pnl_90_weight = max(0, p90) / 5 # Ogni 1% di PnL90 positivo = 3 punti
        pnl_90_weight = min(15, pnl_90_weight) # Max 15 punti
        
        backtest_score = win_rate_weight + pnl_90_weight # Max 30 punti

    # CONFIDENCE SCORE FINALE (Arrotondato)
    confidence = trend_score + setup_score + risk_score + backtest_score
    return round(min(100, confidence)) # Assicuriamo un massimo di 100

# --- STRATEGIA DI SCANSIONE ---
def evaluate_strategy_full(df):
    required_cols = ['SMA_200', 'MACD', 'MACD_SIGNAL', 'BBL', 'BBU', 'RSI', 'ATR']
    for col in required_cols:
        if col not in df.columns:
            # Inseriamo 6 zeri per backtest + 1 zero per Confidence Score
            return "N/A", "Dati insufficienti", "#eee", 0, 50, 0, "Mancano indicatori", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 # MODIFICATO (18 VALORI)

    if df.empty: 
        # Inseriamo 6 zeri per backtest + 1 zero per Confidence Score
        return "N/A", "Dati insufficienti", "#eee", 0, 50, 0, "", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 # MODIFICATO (18 VALORI)
    
    try:
        last_close = df['Close'].iloc[-1]
        last_sma200 = df['SMA_200'].iloc[-1]
        last_rsi = df['RSI'].iloc[-1]
        last_macd = df['MACD'].iloc[-1]
        last_macd_signal = df['MACD_SIGNAL'].iloc[-1]
        last_bbl = df['BBL'].iloc[-1]
        last_bbu = df['BBU'].iloc[-1]
        last_atr = df['ATR'].iloc[-1]
        
        max_price = df['Close'].max()
        drawdown = ((last_close - max_price) / max_price) * 100
        
        is_bullish = last_close > last_sma200
        trend_label = "BULLISH (Rialzista)" if is_bullish else "BEARISH (Ribassista)"
        
        action = "✋ ATTENDI"
        color = "#fcfcfc"
        reason = "Nessun segnale operativo chiaro."
        
        technical_target = max(last_bbu, last_close + (2 * last_atr))
        potential_upside = ((technical_target - last_close) / last_close) * 100

        technical_risk = min(last_bbl, last_close - (2 * last_atr))
        potential_downside = ((technical_risk - last_close) / last_close) * 100

        try:
            # Ritorna: Win30, PnL30, Win60, PnL60, Win90, PnL90
            w30, p30, w60, p60, w90, p90 = run_backtest(df) 
        except Exception as e:
            logger.error(f"Errore calcolo backtest: {e}")
            w30, p30, w60, p60, w90, p90 = 0, 0, 0, 0, 0, 0
        # --- CALCOLO NUOVO: CONFIDENCE SCORE --- # AGGIUNTO
        confidence_score = calculate_confidence(
            df, is_bullish, action, potential_upside, potential_downside, w30, p30, w60, p60, w90, p90
        )

        if is_bullish:
            if last_rsi < 30 and last_close <= last_bbl:
                action = "💎 OPPORTUNITÀ D'ORO"
                color = "#FFD700"
                reason = "RARITÀ: Asset in trend rialzista crollato a livelli estremi."
            elif last_rsi < 40 or last_close <= last_bbl * 1.01: 
                action = "🛒 ACQUISTA ORA! (Dip)"
                color = "#ccffcc"
                reason = "Trend rialzista + Prezzo a sconto."
            elif last_rsi > 75 or (last_close >= last_bbu and last_macd < last_macd_signal):
                 action = "💰 VENDI PARZIALE"
                 color = "#ffdddd"
                 reason = "Prezzo esteso. Rischio ritracciamento."
                 technical_risk = last_sma200 
                 potential_downside = ((technical_risk - last_close) / last_close) * 100
            else:
                 action = "🚀 TREND SOLIDO"
                 color = "#e6f4ea"
                 reason = "Il trend è sano. Lascia correre."

        else: # BEARISH
            if last_rsi < 30 and last_close < last_bbl:
                 action = "⚠️ TENTATIVO RISCHIOSO"
                 color = "#fff4cc"
                 reason = "Rimbalzo tecnico (Dead Cat Bounce)."
            elif last_macd < last_macd_signal:
                 action = "⛔ STAI ALLA LARGA"
                 color = "#fcfcfc"
                 reason = "Trend ribassista. Momentum negativo."
                 potential_upside = 0 
                 
        return trend_label, action, color, last_close, last_rsi, drawdown, reason, technical_target, potential_upside, technical_risk, potential_downside, w30, p30, w60, p60, w90, p90, confidence_score # MODIFICATO (18 VALORI)

    except Exception as e:
        logger.error(f"Errore generale in evaluate_strategy_full: {e}") 
        return "ERR", "Errore", "#eee", 0, 0, 0, str(e), 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 # MODIFICATO (18 VALORI)

# --- STRATEGIA DI PORTAFOGLIO ---
def generate_portfolio_advice(df, avg_price, current_price):
    if 'RSI' not in df.columns or 'SMA_200' not in df.columns or 'ATR' not in df.columns:
        return "✋ DATI MANCANTI", "Impossibile calcolare strategia.", "#eee"

    rsi = df['RSI'].iloc[-1]
    sma = df['SMA_200'].iloc[-1]
    atr = df['ATR'].iloc[-1]
    
    trend = "BULL" if current_price > sma else "BEAR"
    pnl_pct = ((current_price - avg_price) / avg_price) * 100
    
    atr_pct = (atr / current_price) * 100
    
    threshold_low = max(5.0, 2 * atr_pct) 
    threshold_mid = max(15.0, 6 * atr_pct)
    threshold_high = max(40.0, 12 * atr_pct)

    title, advice, color = "✋ MANTIENI", "Situazione stabile.", "#fcfcfc"
    
    if pnl_pct > threshold_high:
        if trend == "BEAR":
            title = "🚨 INCASSA TUTTO (Super Profit)"
            advice = f"Guadagno eccezionale (+{pnl_pct:.1f}%) ma il trend è crollato. Porta a casa questi soldi subito!"
            color = "#ffcccb"
        elif rsi > 80:
            title = "💰 VENDI META' POSIZIONE"
            advice = f"Sei a +{pnl_pct:.1f}% e l'RSI è estremo ({rsi:.0f}). Il mercato è euforico, metti al sicuro metà del profitto."
            color = "#ffdddd"
        else:
            title = "🚀 MOONBAG (Trailing Stop)"
            advice = f"Performance stellare (+{pnl_pct:.1f}%). Il trend regge. Imposta uno Stop Loss mentale a +{pnl_pct-10:.0f}% e lascia correre."
            color = "#e6f4ea"

    elif threshold_mid < pnl_pct <= threshold_high:
        if trend == "BEAR":
            title = "💰 PROTEGGI IL BOTTINO"
            advice = f"Il trend è cambiato in negativo. Non lasciare che questo +{pnl_pct:.1f}% svanisca. Valuta l'uscita."
            color = "#fff4cc"
        elif rsi > 70:
            title = "💰 TAKE PROFIT PARZIALE"
            advice = f"Buon guadagno (+{pnl_pct:.1f}%) e indicatori saturi. Ottimo momento per alleggerire."
            color = "#ffdddd"
        else:
            title = "📈 TREND SANO"
            advice = f"Il guadagno è solido (+{pnl_pct:.1f}%) e c'è ancora spazio per salire. Mantieni."
            color = "#f0f8ff"

    elif threshold_low < pnl_pct <= threshold_mid:
        if trend == "BEAR":
            title = "⚠️ ATTENZIONE (Break Even)"
            advice = f"Sei in utile (+{pnl_pct:.1f}%) ma il trend è brutto. Alza lo Stop Loss al prezzo di ingresso per non perdere soldi."
            color = "#ffffcc"

    elif pnl_pct < -threshold_low: 
        if trend == "BULL" and rsi < 40:
            title = "🛒 MEDIA IL PREZZO (Accumulo)"
            advice = f"Sei sotto del {pnl_pct:.1f}%, ma il trend di fondo è rialzista e siamo a sconto. Occasione per abbassare il prezzo medio."
            color = "#ccffcc"
        elif trend == "BEAR":
            title = "⚠️ VALUTA VENDITA (Cut Loss)"
            advice = f"Perdita importante ({pnl_pct:.1f}%) e trend negativo. La statistica suggerisce di tagliare le perdite."
            color = "#ffe6e6"
            
    return title, advice, color















