import yfinance as yf
import pandas as pd
import pandas_ta as ta
import sqlite3
import hashlib
from datetime import date
import requests
import os
import psycopg2
from urllib.parse import urlparse

# --- CONFIGURAZIONE TELEGRAM (Hardcoded) ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")

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

# --- DATABASE MANAGER (Versione Robusta Anti-Crash) ---
class DBManager:
    def __init__(self):
        self.db_url = os.environ.get("DATABASE_URL")
        self.conn = self.connect()
        
        # FIX CRITICO: Creiamo le tabelle SOLO se la connessione c'è
        if self.conn is not None:
            self.create_tables()
        else:
            print("⚠️ ERRORE CRITICO: Impossibile connettersi al Database. L'app è in modalità limitata.")

    def connect(self):
        if self.db_url:
            try:
                # Tentativo connessione Cloud
                return psycopg2.connect(self.db_url, sslmode='require', connect_timeout=10)
            except Exception as e:
                print(f"❌ Errore connessione DB Cloud: {e}")
                return None
        else:
            # Fallback locale
            return sqlite3.connect("investai_v10.db", check_same_thread=False)

    def get_cursor(self):
        # Se la connessione è morta, proviamo a rianimarla
        if self.conn is None or (self.db_url and self.conn.closed != 0):
            self.conn = self.connect()
        
        if self.conn is not None:
            try:
                return self.conn.cursor()
            except:
                return None
        return None

    def execute_query(self, query, params=()):
        c = self.get_cursor()
        if c is None: return False # Se non c'è DB, esce senza crashare
        
        try:
            if self.db_url: query = query.replace('?',('%s'))
            c.execute(query, params)
            if query.strip().upper().startswith("SELECT"):
                return c.fetchall()
            else:
                self.conn.commit()
                return True
        except Exception as e:
            print(f"Errore query: {e}")
            if self.conn: self.conn.rollback()
            return False

    def execute_fetchone(self, query, params=()):
        c = self.get_cursor()
        if c is None: return None
        
        if self.db_url: query = query.replace('?',('%s'))
        try:
            c.execute(query, params)
            return c.fetchone()
        except: return None

    # --- METODI CREAZIONE TABELLE (Spostati qui per usare execute_query) ---
    def create_tables(self):
        # Usiamo query separate per sicurezza
        q_users = '''CREATE TABLE IF NOT EXISTS users (
                     username TEXT PRIMARY KEY, 
                     password TEXT, 
                     tg_chat_id TEXT)'''
                     
        q_tx = '''CREATE TABLE IF NOT EXISTS transactions (
                     id SERIAL PRIMARY KEY, 
                     username TEXT, 
                     symbol TEXT, 
                     quantity REAL, 
                     price REAL, 
                     date TEXT, 
                     type TEXT, 
                     fee REAL DEFAULT 0.0)'''
        
        # Adattamento per SQLite locale
        if not self.db_url:
            q_tx = q_tx.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")

        self.execute_query(q_users)
        self.execute_query(q_tx)

    # --- METODI UTENTE ---
    
    def register_user(self, u, p):
        h = hashlib.sha256(p.encode()).hexdigest()
        return self.execute_query("INSERT INTO users (username, password) VALUES (?, ?)", (u, h))

    def login_user(self, u, p):
        h = hashlib.sha256(p.encode()).hexdigest()
        res = self.execute_fetchone("SELECT * FROM users WHERE username=? AND password=?", (u, h))
        return res is not None

    def save_chat_id(self, user, chat_id):
        exists = self.execute_fetchone("SELECT username FROM users WHERE username=?", (user,))
        if exists:
            return self.execute_query("UPDATE users SET tg_chat_id=? WHERE username=?", (chat_id, user))
        return False

    def get_user_chat_id(self, user):
        res = self.execute_fetchone("SELECT tg_chat_id FROM users WHERE username=?", (user,))
        return res[0] if res else ""

    def get_users_with_telegram(self):
        return self.execute_query("SELECT username, tg_chat_id FROM users WHERE tg_chat_id IS NOT NULL AND tg_chat_id != ''") or []

    # --- METODI TRANSAZIONI ---

    def add_transaction(self, user, symbol, qty, price, date_str, type="BUY", fee=0.0):
        return self.execute_query(
            "INSERT INTO transactions (username, symbol, quantity, price, date, type, fee) VALUES (?, ?, ?, ?, ?, ?, ?)", 
            (user, symbol.upper(), qty, price, date_str, type, fee))

    def update_transaction(self, t_id, symbol, qty, price, date_str, type, fee=0.0):
        return self.execute_query(
            "UPDATE transactions SET symbol=?, quantity=?, price=?, date=?, type=?, fee=? WHERE id=?", 
            (symbol.upper(), qty, price, date_str, type, fee, t_id))

    def delete_transaction(self, t_id):
        return self.execute_query("DELETE FROM transactions WHERE id=?", (t_id,))

    def get_all_transactions(self, user):
        res = self.execute_query("SELECT id, symbol, quantity, price, date, type, fee FROM transactions WHERE username=? ORDER BY date DESC", (user,))
        return res if res else []

    def get_transaction_by_id(self, t_id):
        return self.execute_fetchone("SELECT id, symbol, quantity, price, date, type, fee FROM transactions WHERE id=?", (t_id,))

    def get_portfolio_summary(self, user):
        rows = self.get_all_transactions(user)
        portfolio = {}
        history = [] 
        
        if rows:
            for row in rows:
                t_id, sym, qty, price, dt, type_tx = row[0], row[1], row[2], row[3], row[4], row[5]
                fee = float(row[6]) if len(row) > 6 and row[6] is not None else 0.0
                qty = float(qty)
                price = float(price)

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
        hist = t.history(period="1d")
        return not hist.empty
    except: return False

def get_data_raw(tickers):
    if not tickers: return {}
    data = {}
    
    if len(tickers) == 1:
        t = tickers[0]
        try:
            df = yf.download(t, period="2y", progress=False, auto_adjust=False)
            if df.empty: return {}
            if isinstance(df.columns, pd.MultiIndex):
                try: df.columns = df.columns.get_level_values(0)
                except: pass
            process_df(df, data, t)
        except: pass
        return data

    try:
        df = yf.download(" ".join(tickers), period="2y", group_by='ticker', progress=False, auto_adjust=False)
        for t in tickers:
            try:
                if t in df:
                    asset_df = df[t].copy()
                    process_df(asset_df, data, t)
            except: pass
        return data
    except: return {}

def process_df(df, data, t):
    # Controllo lunghezza minima per la SMA 200
    if len(df) < 205: 
        return 
    
    df = df.dropna(how='all')
    
    try:
        # Indicatori Base
        df['RSI'] = ta.rsi(df['Close'], length=14)
        df['SMA_200'] = ta.sma(df['Close'], length=200)
        df['SMA_50'] = ta.sma(df['Close'], length=50)
        
        # --- NUOVO: Calcolo ATR (Volatilità Dinamica) ---
        # ATR misura la volatilità media (in dollari)
        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)

        # --- FIX ROBUSTEZZA PER MACD e BOLLINGER ---
        # Usiamo iloc (posizione) invece dei nomi delle colonne per evitare KeyErrors
        
        # MACD (Ritorna: MACD Line, Histogram, Signal Line)
        macd = ta.macd(df['Close'])
        if macd is not None and not macd.empty:
            # Colonna 0: MACD Line, Colonna 2: Signal Line
            df['MACD'] = macd.iloc[:, 0]
            df['MACD_SIGNAL'] = macd.iloc[:, 2]
        else:
            return 
            
        # Bollinger Bands (Ritorna: Lower, Mid, Upper, Bandwidth, Percent)
        bb = ta.bbands(df['Close'], length=20, std=2)
        if bb is not None and not bb.empty:
            # Colonna 0: Lower Band (BBL), Colonna 2: Upper Band (BBU)
            df['BBL'] = bb.iloc[:, 0]
            df['BBU'] = bb.iloc[:, 2]
        else:
            return
            
        # Pulizia NaN iniziali
        df_clean = df.dropna()
        
        if not df_clean.empty:
            data[t] = df_clean
            
    except Exception as e:
        print(f"Errore calcolo indicatori per {t}: {e}")
        pass

# --- STRATEGIA DI SCANSIONE (MERCATO) ---
def evaluate_strategy_full(df):
    # Verifica esistenza colonne (incluso ATR)
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
        
        # --- CALCOLO TARGET & RISCHIO CON VOLATILITÀ (ATR) ---
        # Il target tecnico è flessibile: Banda alta oppure 2 volte l'ATR sopra il prezzo
        technical_target = max(last_bbu, last_close + (2 * last_atr))
        potential_upside = ((technical_target - last_close) / last_close) * 100

        # Il rischio è la Banda bassa oppure 2 volte l'ATR sotto il prezzo
        technical_risk = min(last_bbl, last_close - (2 * last_atr))
        potential_downside = ((technical_risk - last_close) / last_close) * 100
        
        # --- LOGICA STRATEGICA ---
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
                 technical_risk = last_sma200 # Se si vende, il rischio è tornare alla media
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
                 potential_upside = 0 # Nessun upside in trend bear forte
                 
        return trend_label, action, color, last_close, last_rsi, drawdown, reason, technical_target, potential_upside, technical_risk, potential_downside
        
    except Exception as e:
        return "ERR", "Errore", "#eee", 0, 0, 0, str(e), 0, 0, 0, 0

# --- STRATEGIA DI PORTAFOGLIO (CON ATR DINAMICO) ---
def generate_portfolio_advice(df, avg_price, current_price):
    if 'RSI' not in df.columns or 'SMA_200' not in df.columns or 'ATR' not in df.columns:
        return "✋ DATI MANCANTI", "Impossibile calcolare strategia.", "#eee"

    rsi = df['RSI'].iloc[-1]
    sma = df['SMA_200'].iloc[-1]
    atr = df['ATR'].iloc[-1]
    
    trend = "BULL" if current_price > sma else "BEAR"
    pnl_pct = ((current_price - avg_price) / avg_price) * 100
    
    # --- CALCOLO SOGLIE DINAMICHE ---
    # Convertiamo l'ATR in percentuale rispetto al prezzo attuale
    atr_pct = (atr / current_price) * 100
    
    # Definiamo le fasce basandoci sulla volatilità intrinseca dell'asset
    # Un asset volatile (ATR 5%) avrà fasce larghe. Un asset stabile (ATR 0.5%) fasce strette.
    
    # Fascia 1: Protezione Guadagni (Stop in profit) -> circa 2-6 volte l'ATR
    threshold_low = max(5.0, 2 * atr_pct) 
    
    # Fascia 2: Target Profitto (Take Profit) -> circa 6-12 volte l'ATR
    threshold_mid = max(15.0, 6 * atr_pct)
    
    # Fascia 3: Moonbag (Super Trend) -> oltre 12 volte l'ATR
    threshold_high = max(40.0, 12 * atr_pct)

    title, advice, color = "✋ MANTIENI", "Situazione stabile.", "#fcfcfc"
    
    # --- LOGICA A GRADINI DINAMICA ---
    
    # FASCIA 3: SUPER GUADAGNO (> High Threshold)
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

    # FASCIA 2: OTTIMO GUADAGNO (tra Mid e High)
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

    # FASCIA 1: GUADAGNO INIZIALE (tra Low e Mid)
    elif threshold_low < pnl_pct <= threshold_mid:
        if trend == "BEAR":
            title = "⚠️ ATTENZIONE (Break Even)"
            advice = f"Sei in utile (+{pnl_pct:.1f}%) ma il trend è brutto. Alza lo Stop Loss al prezzo di ingresso per non perdere soldi."
            color = "#ffffcc"

    # FASCIA 0: PERDITA O PARITÀ (< Low Threshold)
    elif pnl_pct < -threshold_low: # Usiamo l'ATR anche per lo stop loss dinamico!
        if trend == "BULL" and rsi < 40:
            title = "🛒 MEDIA IL PREZZO (Accumulo)"
            advice = f"Sei sotto del {pnl_pct:.1f}%, ma il trend di fondo è rialzista e siamo a sconto. Occasione per abbassare il prezzo medio."
            color = "#ccffcc"
        elif trend == "BEAR":
            title = "⚠️ VALUTA VENDITA (Cut Loss)"
            advice = f"Perdita importante ({pnl_pct:.1f}%) e trend negativo. La statistica suggerisce di tagliare le perdite."
            color = "#ffe6e6"
            

    return title, advice, color


