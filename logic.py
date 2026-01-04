import streamlit as st
from st_supabase_connection import SupabaseConnection
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import os
import logging
from passlib.context import CryptContext
import numpy as np
from datetime import datetime, timedelta

# --- CONFIGURAZIONE LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- CONFIGURAZIONE HASHING ---
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"], 
    deprecated="auto",
    pbkdf2_sha256__default_rounds=300000 
)

# --- CONFIGURAZIONE TELEGRAM ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

# --- ASSET LIST COMPLETA (Ottimizzata e ordinata) ---
POPULAR_ASSETS = {
    # --- INDICI GLOBALI ---
    "S&P 500 (USA)": "SPY", "Nasdaq 100 (Tech)": "QQQ", 
    "Russell 2000 (Small Cap)": "IWM", "Dow Jones": "DIA",
    "All-World": "VWCE.DE", "Emerging Markets": "EEM", "Europe Stoxx 50": "FEZ",
    "China (Large Cap)": "FXI", "China (Internet)": "KWEB", "India": "INDA",
    "Brazil": "4BRZ.DE", "Japan": "EWJ", "UK (FTSE 100)": "EWU", "Germany (DAX)": "EWG",
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
    "Clean Energy": "ICLN", "Cybersecurity": "CIBR.MI", "Robotics & AI": "BOTZ",
    "Defense & Aerospace": "ITA", "Biotech": "XBI", "Tonies SE": "TNIE.F", "DroneShield": "DRH.F",
    "Redcare Pharmacy": "0RJT.IL",
    # --- CRYPTO ---
    "Bitcoin": "BTC-USD", "Ethereum": "ETH-USD", "Solana": "SOL-USD",
    "Ripple": "XRP-USD", "Binance Coin": "BNB-USD", "Cardano": "ADA-USD",
    "Dogecoin": "DOGE-USD", "Chainlink": "LINK-USD", "Polkadot": "DOT-USD",
    # --- BIG TECH (USA) ---
    "Nvidia": "NVDA", "Apple": "AAPL", "Microsoft": "MSFT", "Tesla": "TSLA", 
    "Amazon": "AMZN", "Meta": "META", "Google": "GOOGL", "Oracle": "ORCL",
    "Netflix": "NFLX", "AMD": "AMD.F", "Palantir": "PLTR", "Coinbase": "COIN",
    "monday.com": "MNDY", "Arista Networks": "ANET", "Duolingo": "DUOL", 
    "The Trade Desk": "TTD", "Axon Enterprise": "AXON", "BigBear.ai": "BBAI",
    "Installed Building Products": "IBP",
    # --- BIG EUROPE (GRANOLAS) ---
    "ASML (Chip)": "ASML", "LVMH (Luxury)": "MC.PA", 
    "Novo Nordisk (Pharma)": "NVO", "SAP (Software)": "SAP", "Easyjet": "EJT1.F",
    # --- ITALIA (FTSE MIB) ---
    "Ferrari": "RACE.MI", "Intesa Sanpaolo": "ISP.MI", "UniCredit": "UCG.MI", 
    "Enel": "ENEL.MI", "Eni": "ENI.MI", "Stellantis": "STLAM.MI", 
    "Leonardo": "LDO.MI", "Generali": "G.MI", "Moncler": "MONC.MI", 
    "Poste Italiane": "PST.MI", "Terna": "TRN.MI", "Snam": "SRG.MI", 
    "Mediobanca": "MB.MI", "Tenaris": "TEN.MI", "Prysmian": "PRY.MI",
    "Fincantieri": "FCT.MI", "Juventus": "JUV.F", "Banca Monte dei Paschi di Siena": "BMPSM.XD",
    "Banca Popolare di Sondrio": "BPSOM.XD"
} 
AUTO_SCAN_TICKERS = [v for k, v in POPULAR_ASSETS.items() if v is not None]

# --- DATABASE MANAGER (Supabase) ---
class DBManager:
    def __init__(self):
        self.db_url = "SUPABASE_API_CONNECTION_ACTIVE"
        
        try:
            self.conn = st.connection("supabase", type=SupabaseConnection)
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
        except Exception as e:
            logger.error(f"Errore registrazione utente {u}: {e}")
            return False

    def login_user(self, u, p):
        try:
            res = self.client.table("users").select("password").eq("username", u).execute()
            if res.data and len(res.data) > 0:
                hashed_password = res.data[0]['password']
                return verify_password(p, hashed_password)
            return False
        except Exception as e:
            logger.error(f"Errore login utente {u}: {e}")
            return False

    def change_password(self, username, new_password):
        h = hash_password(new_password)
        try:
            res = self.client.table("users").update({"password": h}).eq("username", username).execute()
            return len(res.data) > 0
        except Exception as e:
            logger.error(f"Errore cambio password: {e}")
            return False
    
    def save_chat_id(self, user, chat_id):
        try:
            res = self.client.table("users").update({"tg_chat_id": str(chat_id)}).eq("username", user).execute()
            return len(res.data) > 0
        except Exception as e:
            logger.error(f"Errore save_chat_id: {e}")
            return False

    def disable_notifications(self, user, chat_id):
        try:
            stop_id = f"STOP_{chat_id}"
            res = self.client.table("users").update({"tg_chat_id": stop_id}).eq("username", user).execute()
            return len(res.data) > 0
        except Exception as e:
            logger.error(f"Errore disable_notifications: {e}")
            return False  

    def get_user_chat_id(self, user):
        try:
            res = self.client.table("users").select("tg_chat_id").eq("username", user).execute()
            if res.data and len(res.data) > 0:
                raw_id = res.data[0].get("tg_chat_id", "")
                return raw_id.replace("STOP_", "")
            return ""
        except Exception as e:
            logger.error(f"Errore get_user_chat_id per {user}: {e}")
            return ""

    def get_users_with_telegram(self):
        try:
            res = self.client.table("users").select("username, tg_chat_id").neq("tg_chat_id", "").execute()
            return [(r['username'], r['tg_chat_id']) for r in res.data if not r['tg_chat_id'].startswith("STOP_")]
        except Exception as e:
            logger.error(f"Errore get_users_with_telegram: {e}")
            return []

    def get_user_by_chat_id(self, chat_id):
        try:
            res = self.client.table("users").select("username").eq("tg_chat_id", str(chat_id)).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]['username']
            stop_id = f"STOP_{chat_id}"
            res = self.client.table("users").select("username").eq("tg_chat_id", stop_id).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]['username']
            return None
        except Exception as e:
            logger.error(f"Errore get_user_by_chat_id: {e}")
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
        except Exception as e:
            logger.error(f"Errore aggiunta transazione per {user} ({symbol}): {e}")
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
        except Exception as e:
            logger.error(f"Errore aggiornamento transazione ID {t_id}: {e}")
            return False

    def delete_transaction(self, t_id):
        try:
            self.client.table("transactions").delete().eq("id", t_id).execute()
            return True
        except Exception as e:
            logger.error(f"Errore eliminazione transazione ID {t_id}: {e}")
            return False

    def get_all_transactions(self, user):
        try:
            res = self.client.table("transactions").select("*").eq("username", user).order("date", desc=True).execute()
            
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
            logger.error(f"Errore fetch tx: {e}")
            return []

    def get_transaction_by_id(self, t_id):
        try:
            res = self.client.table("transactions").select("*").eq("id", t_id).execute()
            if res.data:
                r = res.data[0]
                return (r['id'], r['symbol'], r['quantity'], r['price'], r['date'], r['type'], r.get('fee', 0.0))
            return None
        except Exception as e:
            logger.error(f"Errore get_transaction_by_id per ID {t_id}: {e}")
            return None

    def get_portfolio_summary(self, user):
        rows = self.get_all_transactions(user)
        portfolio = {}
        history = [] 
        
        for row in rows:
            sym = row[1]
            qty = float(row[2])
            price = float(row[3])
            dt = row[4]
            type_tx = row[5]
            fee = float(row[6])

            if sym not in portfolio: 
                portfolio[sym] = {"qty": 0.0, "total_cost": 0.0, "avg_price": 0.0}
            
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
    p_str = str(password) if password else ""
    if not p_str:
        p_str = ""
    return pwd_context.hash(p_str)

def verify_password(plain_password, hashed_password: str) -> bool:
    p_str = str(plain_password) if plain_password else ""
    return pwd_context.verify(p_str, hashed_password)

# --- HELPER FUNCTIONS ---
def validate_ticker(ticker):
    if not ticker: return False
    try:
        t = yf.Ticker(ticker)
        return len(t.history(period="1d")) > 0
    except Exception as e:
        logger.debug(f"Validazione fallita per {ticker}: {e}")
        return False

def get_data_raw(tickers):
    """
    Download universale con gestione MultiIndex migliorata.
    """
    if not tickers: return {}
    data = {}
    
    unique_tickers = list(set([t.strip().upper() for t in tickers if t]))
    if not unique_tickers: return {}

    try:
        df = yf.download(unique_tickers, period="2y", group_by='ticker', progress=False, auto_adjust=False)
        
        if df.empty:
            return {}

        for t in unique_tickers:
            asset_df = pd.DataFrame()
            
            try:
                if isinstance(df.columns, pd.MultiIndex) and t in df.columns.get_level_values(0):
                    asset_df = df[t].copy()
                elif len(unique_tickers) == 1:
                    if 'Close' in df.columns:
                        asset_df = df.copy()
                    elif isinstance(df.columns, pd.MultiIndex):
                        asset_df = df.copy()
                        asset_df.columns = asset_df.columns.get_level_values(0)
            
                if not asset_df.empty and 'Close' in asset_df.columns:
                    asset_df.dropna(subset=['Close'], inplace=True)
                    process_df(asset_df, data, t)
                    
            except Exception as e:
                logger.debug(f"Errore estrazione {t}: {e}")
                continue
                
        return data

    except Exception as e:
        logger.error(f"Errore download generale: {e}")
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

# --- BACKTESTING E PROBABILITÀ ---
def run_backtest(df, days_list=[30, 60, 90]):
    """
    Backtest migliorato con gestione errori.
    """
    df_copy = df.copy()
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
            exit_idx = df_copy.index.get_loc(entry_date) + days
            if exit_idx < len(df_copy):
                exit_price = df_copy.iloc[exit_idx]['Close']
                pnl = (exit_price - entry_price) / entry_price
                results[days]["pnl_sum"] += pnl
                if pnl > 0:
                    results[days]["wins"] += 1
    
    win_rates = [0.0] * len(days_list)
    avg_pnls = [0.0] * len(days_list)
    
    for i, days in enumerate(days_list):
        if total_signals > 0:
            win_rates[i] = (results[days]["wins"] / total_signals) * 100
            avg_pnls[i] = (results[days]["pnl_sum"] / total_signals) * 100
    
    return win_rates[0], avg_pnls[0], win_rates[1], avg_pnls[1], win_rates[2], avg_pnls[2]

# --- CONFIDENCE SCORE MIGLIORATO ---
def calculate_confidence(df, is_bullish, action, potential_upside, potential_downside, w30, p30, w60, p60, w90, p90):
    """
    Score 0-100 con pesatura ottimizzata.
    """
    last_close = df['Close'].iloc[-1]
    last_sma50 = df['SMA_50'].iloc[-1]
    last_sma200 = df['SMA_200'].iloc[-1]
    last_rsi = df['RSI'].iloc[-1]
    
    # 1. Trend Strength (30%)
    trend_score = 0
    if is_bullish:
        trend_factor = min(1.0, (last_close - last_sma200) / last_sma200 * 10)
        if last_sma50 > last_sma200:
             trend_factor *= 1.2
        trend_score = min(30, trend_factor * 30)

    # 2. Setup Quality (25%)
    setup_score = 0
    if "ORO" in action:
        setup_score = 25
    else:
        setup_factor = max(0, 40 - last_rsi) / 20 
        setup_score = min(25, setup_factor * 25)

    # 3. Risk/Reward (15%)
    risk_score = 0
    if potential_upside > 0 and potential_downside < 0:
        risk_reward_ratio = potential_upside / abs(potential_downside) 
        risk_score = min(15, (risk_reward_ratio / 2) * 15)

    # 4. Backtest (30%)
    backtest_score = 0
    if w30 > 0:
        win_rate_weight = (w30 / 100) * 15
        pnl_90_weight = max(0, min(15, p90 / 3))
        backtest_score = win_rate_weight + pnl_90_weight

    confidence = trend_score + setup_score + risk_score + backtest_score
    return round(min(100, max(0, confidence)))

# --- STRATEGIA MIGLIORATA ---
def evaluate_strategy_full(df):
    """
    Strategia con gestione errori potenziata.
    """
    required_cols = ['SMA_200', 'MACD', 'MACD_SIGNAL', 'BBL', 'BBU', 'RSI', 'ATR']
    for col in required_cols:
        if col not in df.columns:
            return "N/A", "Dati insufficienti", "#eee", 0, 50, 0, "Mancano indicatori", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0

    if df.empty: 
        return "N/A", "Dati insufficienti", "#eee", 0, 50, 0, "", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    
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
            w30, p30, w60, p60, w90, p90 = run_backtest(df) 
        except Exception as e:
            logger.error(f"Errore backtest: {e}")
            w30, p30, w60, p60, w90, p90 = 0, 0, 0, 0, 0, 0

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
        else:
            if last_rsi < 30 and last_close < last_bbl:
                 action = "⚠️ TENTATIVO RISCHIOSO"
                 color = "#fff4cc"
                 reason = "Rimbalzo tecnico (Dead Cat Bounce)."
            elif last_macd < last_macd_signal:
                 action = "⛔ STAI ALLA LARGA"
                 color = "#fcfcfc"
                 reason = "Trend ribassista. Momentum negativo."
                 potential_upside = 0

        confidence_score = calculate_confidence(
            df, is_bullish, action, potential_upside, potential_downside, 
            w30, p30, w60, p60, w90, p90
        )
                 
        return trend_label, action, color, last_close, last_rsi, drawdown, reason, technical_target, potential_upside, technical_risk, potential_downside, w30, p30, w60, p60, w90, p90, confidence_score

    except Exception as e:
        logger.error(f"Errore generale in evaluate_strategy_full: {e}") 
        return "ERR", "Errore", "#eee", 0, 0, 0, str(e), 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0

# --- STRATEGIA PORTAFOGLIO ---
def generate_portfolio_advice(df, avg_price, current_price):
    """
    Consiglio personalizzato migliorato.
    """
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
            advice = f"Il guadagno è solido (+{pnl_pct:.1f}%) e c'è ancora spazio. Mantieni."
            color = "#f0f8ff"

    elif threshold_low < pnl_pct <= threshold_mid:
        if trend == "BEAR":
            title = "⚠️ ATTENZIONE (Break Even)"
            advice = f"Sei in utile (+{pnl_pct:.1f}%) ma il trend è brutto. Alza lo Stop Loss al prezzo di ingresso."
            color = "#ffffcc"

    elif pnl_pct < -threshold_low: 
        if trend == "BULL" and rsi < 40:
            title = "🛒 MEDIA IL PREZZO (Accumulo)"
            advice = f"Sei sotto del {pnl_pct:.1f}%, ma il trend è rialzista e siamo a sconto. Occasione per abbassare il prezzo medio."
            color = "#ccffcc"
        elif trend == "BEAR":
            title = "⚠️ VALUTA VENDITA (Cut Loss)"
            advice = f"Perdita importante ({pnl_pct:.1f}%) e trend negativo. Considera di tagliare le perdite."
            color = "#ffe6e6"
            
    return title, advice, color

# --- STORICO PORTAFOGLIO MIGLIORATO ---
def get_historical_portfolio_value(transactions, market_data_history):
    """
    Ricostruzione storico con gestione vendite completa.
    """
    if not transactions:
        return pd.DataFrame()

    df_tx = pd.DataFrame(transactions, columns=['id', 'symbol', 'qty', 'price', 'date', 'type', 'fee'])
    df_tx['date'] = pd.to_datetime(df_tx['date'])
    df_tx = df_tx.sort_values('date')

    start_date = df_tx['date'].min()
    end_date = pd.Timestamp.today().normalize()
    date_range = pd.date_range(start=start_date, end=end_date, freq='D')

    unique_tickers = df_tx['symbol'].unique()
    
    portfolio_state = {t: {'qty': 0.0, 'total_cost_basis': 0.0} for t in unique_tickers}
    history_records = []

    tx_grouped = df_tx.groupby('date')

    # Scarica prezzi
    price_history = pd.DataFrame(index=date_range)
    for t in unique_tickers:
        if t in market_data_history:
            price_history[t] = market_data_history[t]['Close'].reindex(date_range).ffill().bfill()
        else:
            price_history[t] = 0.0

    # Loop giornaliero
    for current_date in date_range:
        # Applica transazioni
        if current_date in tx_grouped.groups:
            daily_txs = tx_grouped.get_group(current_date)
            for _, tx in daily_txs.iterrows():
                sym = tx['symbol']
                q = tx['qty']
                p = tx['price']
                f = tx['fee']
                
                curr_qty = portfolio_state[sym]['qty']
                curr_cost = portfolio_state[sym]['total_cost_basis']

                if tx['type'] == 'BUY':
                    portfolio_state[sym]['qty'] += q
                    portfolio_state[sym]['total_cost_basis'] += (q * p) + f
                
                elif tx['type'] == 'SELL':
                    if curr_qty > 0:
                        avg_cost = curr_cost / curr_qty
                        cost_removed = avg_cost * q
                        portfolio_state[sym]['qty'] = max(0, curr_qty - q)
                        portfolio_state[sym]['total_cost_basis'] = max(0, curr_cost - cost_removed)

        # Calcola valori
        daily_total_value = 0.0
        daily_total_invested = 0.0
        asset_values = {}

        for sym in unique_tickers:
            qty = portfolio_state[sym]['qty']
            cost_basis = portfolio_state[sym]['total_cost_basis']
            market_price = price_history.at[current_date, sym]
            
            curr_val = qty * market_price
            
            daily_total_value += curr_val
            daily_total_invested += cost_basis
            asset_values[sym] = curr_val

        record = {
            'Total Value': daily_total_value,
            'Total Invested': daily_total_invested,
            **asset_values
        }
        history_records.append(record)

    df_history = pd.DataFrame(history_records, index=date_range)
    return df_history

def generate_enhanced_excel_report(df_hist, current_portfolio):
    """
    Genera un Excel professionale con:
    1. Foglio 'Dati Storici': Tabella completa con valori, investito, utile e % giornaliera.
    2. Foglio 'Portafoglio': Situazione attuale asset per asset.
    3. Foglio 'Dashboard Grafici': Solo grafici riassuntivi.
    """
    from io import BytesIO
    import pandas as pd
    
    output = BytesIO()
    
    # Pre-calcoli sui dati storici per arricchire la tabella
    # Assicuriamoci di avere le colonne calcolate
    if 'Total Invested' not in df_hist.columns:
        df_hist['Total Invested'] = 0.0 # Fallback se manca
    
    df_hist['Utile Netto (€)'] = df_hist['Total Value'] - df_hist['Total Invested']
    df_hist['Performance %'] = df_hist['Total Value'].pct_change().fillna(0)
    
    # Riorganizziamo le colonne: Prima i totali, poi i singoli asset
    cols_main = ['Total Value', 'Total Invested', 'Utile Netto (€)', 'Performance %']
    cols_assets = [c for c in df_hist.columns if c not in cols_main]
    df_final_hist = df_hist[cols_main + cols_assets]

    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        
        # --- DEFINIZIONE FORMATI ---
        fmt_header = workbook.add_format({
            'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#D7E4BC', 'border': 1})
        fmt_currency = workbook.add_format({'num_format': '€ #,##0.00'})
        fmt_pct = workbook.add_format({'num_format': '0.00%'})
        
        # Formattazione condizionale (Verde/Rosso per testo e sfondo chiaro)
        fmt_green = workbook.add_format({'bg_color': '#C6EFCE', 'font_color': '#006100', 'num_format': '0.00%'})
        fmt_red = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006', 'num_format': '0.00%'})
        
        fmt_curr_green = workbook.add_format({'bg_color': '#C6EFCE', 'font_color': '#006100', 'num_format': '€ #,##0.00'})
        fmt_curr_red = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006', 'num_format': '€ #,##0.00'})

        # ==========================================
        # FOGLIO 1: DATI STORICI
        # ==========================================
        sheet_hist_name = 'Dati Storici'
        df_final_hist.to_excel(writer, sheet_name=sheet_hist_name, index=True)
        ws_hist = writer.sheets[sheet_hist_name]
        
        last_row = len(df_final_hist) + 1
        
        # Larghezza colonne (Data + Totali larghe, Asset normali)
        ws_hist.set_column(0, 0, 15) # Data
        ws_hist.set_column(1, 3, 20, fmt_currency) # Valore, Investito, Utile
        ws_hist.set_column(4, 4, 15, fmt_pct) # Performance %
        ws_hist.set_column(5, len(df_final_hist.columns), 15, fmt_currency) # Asset singoli
        
        # Formattazione Condizionale su "Performance %" (Colonna E -> Indice 4)
        ws_hist.conditional_format(1, 4, last_row, 4, {'type': 'cell', 'criteria': '>', 'value': 0, 'format': fmt_green})
        ws_hist.conditional_format(1, 4, last_row, 4, {'type': 'cell', 'criteria': '<', 'value': 0, 'format': fmt_red})

        # Formattazione Condizionale su "Utile Netto" (Colonna D -> Indice 3)
        ws_hist.conditional_format(1, 3, last_row, 3, {'type': 'cell', 'criteria': '>', 'value': 0, 'format': fmt_curr_green})
        ws_hist.conditional_format(1, 3, last_row, 3, {'type': 'cell', 'criteria': '<', 'value': 0, 'format': fmt_curr_red})

        # ==========================================
        # FOGLIO 2: PORTAFOGLIO ATTUALE
        # ==========================================
        sheet_pf_name = 'Portafoglio'
        data_pf = []
        for k, v in current_portfolio.items():
            data_pf.append({
                "Asset": k,
                "Quantità": v['qty'],
                "Prezzo Medio": v['avg_price'],
                "Prezzo Attuale": v['cur_price'],
                "Valore Totale": v['qty'] * v['cur_price'],
                "P&L %": v['pnl_pct'] / 100
            })
        
        if data_pf:
            df_pf = pd.DataFrame(data_pf)
            df_pf.to_excel(writer, sheet_name=sheet_pf_name, index=False)
            ws_pf = writer.sheets[sheet_pf_name]
            
            # Larghezza colonne
            ws_pf.set_column('A:A', 15) # Asset
            ws_pf.set_column('B:B', 12) # Qty
            ws_pf.set_column('C:E', 18, fmt_currency) # Prezzi
            ws_pf.set_column('F:F', 12, fmt_pct) # P&L
            
            # Condizionale su P&L %
            ws_pf.conditional_format(1, 5, len(df_pf), 5, {'type': 'cell', 'criteria': '>', 'value': 0, 'format': fmt_green})
            ws_pf.conditional_format(1, 5, len(df_pf), 5, {'type': 'cell', 'criteria': '<', 'value': 0, 'format': fmt_red})

        # ==========================================
        # FOGLIO 3: DASHBOARD GRAFICI
        # ==========================================
        sheet_dash_name = 'Dashboard Grafici'
        ws_dash = workbook.add_worksheet(sheet_dash_name)
        ws_dash.hide_gridlines(2) # Nascondi griglia per estetica
        
        # TITOLO DASHBOARD
        ws_dash.write('B2', "Report Finanziario - InvestAI", workbook.add_format({'bold': True, 'font_size': 18, 'font_color': '#004d40'}))

        # --- GRAFICO 1: EVOLUZIONE CAPITALE (Valore vs Investito) ---
        if len(df_final_hist) > 0:
            chart_evo = workbook.add_chart({'type': 'area'})
            
            # Serie 1: Valore Totale (Area Verde)
            chart_evo.add_series({
                'name':       'Valore Portafoglio',
                'categories': f"='{sheet_hist_name}'!$A$2:$A${last_row}",
                'values':     f"='{sheet_hist_name}'!$B$2:$B${last_row}",
                'fill':       {'color': '#b2dfdb', 'transparency': 50},
                'line':       {'color': '#004d40'}
            })
            
            # Serie 2: Investito (Linea Rossa) - Aggiunta come asse secondario o linea sovrapposta
            # Nota: In Excel base via Python, combinare area+linea è complesso. 
            # Usiamo 'area' per il valore, e aggiungiamo l'investito come seconda serie (apparirà come area sovrapposta).
            # Per farlo "Linea", dovremmo usare 'type': 'line' per tutto o 'stock'. 
            # Facciamo un grafico a LINEE per chiarezza massima.
            chart_evo = workbook.add_chart({'type': 'line'})
            chart_evo.add_series({
                'name':       'Valore Portafoglio',
                'categories': f"='{sheet_hist_name}'!$A$2:$A${last_row}",
                'values':     f"='{sheet_hist_name}'!$B$2:$B${last_row}",
                'line':       {'color': '#004d40', 'width': 2.5}
            })
            chart_evo.add_series({
                'name':       'Capitale Investito',
                'categories': f"='{sheet_hist_name}'!$A$2:$A${last_row}",
                'values':     f"='{sheet_hist_name}'!$C$2:$C${last_row}",
                'line':       {'color': '#ef5350', 'width': 1.5, 'dash_type': 'dash'}
            })
            
            chart_evo.set_title({'name': 'Crescita del Capitale'})
            chart_evo.set_y_axis({'major_gridlines': {'visible': True, 'line': {'color': '#f0f0f0'}}})
            chart_evo.set_size({'width': 800, 'height': 400})
            ws_dash.insert_chart('B4', chart_evo)

            # --- GRAFICO 2: UTILE NETTO (Colonne) ---
            chart_pnl = workbook.add_chart({'type': 'column'})
            chart_pnl.add_series({
                'name':       'Utile Netto',
                'categories': f"='{sheet_hist_name}'!$A$2:$A${last_row}",
                'values':     f"='{sheet_hist_name}'!$D$2:$D${last_row}",
                'fill':       {'color': '#66bb6a'}, # Verde base, non possiamo fare conditional color nativo facile qui
                'gap':        50
            })
            chart_pnl.set_title({'name': 'Andamento Utile Netto (€)'})
            chart_pnl.set_size({'width': 800, 'height': 350})
            ws_dash.insert_chart('B26', chart_pnl)

        # --- GRAFICO 3: ALLOCAZIONE (Torta) ---
        if data_pf:
            chart_pie = workbook.add_chart({'type': 'doughnut'})
            chart_pie.add_series({
                'name': 'Allocazione',
                'categories': f"='{sheet_pf_name}'!$A$2:$A${len(df_pf)+1}",
                'values':     f"='{sheet_pf_name}'!$E$2:$E${len(df_pf)+1}",
                'data_labels': {'percentage': True, 'position': 'outside'}
            })
            chart_pie.set_title({'name': 'Allocazione Asset'})
            chart_pie.set_style(10)
            chart_pie.set_size({'width': 400, 'height': 350})
            # Lo posizioniamo a destra del grafico PnL o sotto
            ws_dash.insert_chart('O4', chart_pie)

    return output.getvalue()

