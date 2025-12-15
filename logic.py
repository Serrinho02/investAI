import streamlit as st
from st_supabase_connection import SupabaseConnection
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import hashlib
import os

# --- CONFIGURAZIONE TELEGRAM ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

# --- ASSET LIST COMPLETA ---
POPULAR_ASSETS = {
    "S&P 500 (USA)": "SPY", "Nasdaq 100 (Tech)": "QQQ", 
    "Russell 2000 (Small Cap)": "IWM", "All-World": "VWCE.DE",
    "Emerging Markets": "EEM", "Europe Stoxx 50": "FEZ", "Nikkei 225": "EWJ",
    "Gold": "GLD", "Silver": "SLV", "Oil": "USO", "Real Estate": "VNQ",
    "Bitcoin": "BTC-USD", "Ethereum": "ETH-USD", "Solana": "SOL-USD",
    "Semiconductors": "SMH", "Healthcare": "XLV", "Financials": "XLF", "Clean Energy": "ICLN",
    "US Treasury 20Y+": "TLT", "US Treasury 1-3Y": "SHY",
    "Nvidia": "NVDA", "Apple": "AAPL", "Microsoft": "MSFT", "Tesla": "TSLA", 
    "Amazon": "AMZN", "Meta": "META", "Google": "GOOGL",
    "Ferrari": "RACE.MI", "Intesa": "ISP.MI", "Enel": "ENEL.MI", 
    "Eni": "ENI.MI", "Stellantis": "STLAM.MI", "Leonardo": "LDO.MI", "UniCredit": "UCG.MI"
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
        h = hashlib.sha256(p.encode()).hexdigest()
        try:
            res = self.client.table("users").insert({"username": u, "password": h}).execute()
            return len(res.data) > 0
        except: return False

    def login_user(self, u, p):
        h = hashlib.sha256(p.encode()).hexdigest()
        try:
            res = self.client.table("users").select("*").eq("username", u).eq("password", h).execute()
            return len(res.data) > 0
        except: return False

    def change_password(self, username, new_password):
        """Aggiorna la password dell'utente"""
        h = hashlib.sha256(new_password.encode()).hexdigest()
        try:
            res = self.client.table("users").update({"password": h}).eq("username", username).execute()
            return len(res.data) > 0
        except Exception as e:
            print(f"Errore cambio password: {e}")
            return False
    
    def save_chat_id(self, user, chat_id):
        try:
            res = self.client.table("users").update({"tg_chat_id": str(chat_id)}).eq("username", user).execute()
            return len(res.data) > 0
        except: return False

    def get_user_chat_id(self, user):
        try:
            res = self.client.table("users").select("tg_chat_id").eq("username", user).execute()
            if res.data and len(res.data) > 0:
                raw_id = res.data[0].get("tg_chat_id", "")
                # Pulisce l'ID per mostrarlo nel sito
                return raw_id.replace("STOP_", "")
            return ""
        except: return ""

    def get_users_with_telegram(self):
        try:
            res = self.client.table("users").select("username, tg_chat_id").neq("tg_chat_id", "").execute()
            # Filtra ed esclude chi inizia con STOP_
            return [(r['username'], r['tg_chat_id']) for r in res.data if not r['tg_chat_id'].startswith("STOP_")]
        except: return []

    def get_user_by_chat_id(self, chat_id):
        try:
            # Cerca se l'utente ha l'ID normale OPPURE l'ID con STOP_
            possible_ids = [str(chat_id), f"STOP_{chat_id}"]
            res = self.client.table("users").select("username").in_("tg_chat_id", possible_ids).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]['username']
            return None
        except: return None

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
        except: return False

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
        except: return False

    def delete_transaction(self, t_id):
        try:
            self.client.table("transactions").delete().eq("id", t_id).execute()
            return True
        except: return False

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
        except: return None

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

# --- HELPER FUNCTIONS ---
def validate_ticker(ticker):
    if not ticker: return False
    try:
        t = yf.Ticker(ticker)
        # Fast check: history(period="1d") è molto più veloce e affidabile
        return len(t.history(period="1d")) > 0
    except: return False

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
        pass

# --- STRATEGIA DI SCANSIONE ---
def evaluate_strategy_full(df):
    required_cols = ['SMA_200', 'MACD', 'MACD_SIGNAL', 'BBL', 'BBU', 'RSI', 'ATR']
    for col in required_cols:
        if col not in df.columns:
            return "N/A", "Dati insufficienti", "#eee", 0, 50, 0, "Mancano indicatori", 0, 0, 0, 0

    if df.empty: 
        return "N/A", "Dati insufficienti", "#eee", 0, 50, 0, "", 0, 0, 0, 0
    
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
                 
        return trend_label, action, color, last_close, last_rsi, drawdown, reason, technical_target, potential_upside, technical_risk, potential_downside
        
    except Exception as e:
        return "ERR", "Errore", "#eee", 0, 0, 0, str(e), 0, 0, 0, 0

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





