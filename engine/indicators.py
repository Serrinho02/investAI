"""
Technical Indicators — InvestAI
Calcola tutti gli indicatori tecnici necessari al motore di scoring.
Usa pandas_ta dove disponibile, con fallback manuali per robustezza.
"""
from __future__ import annotations

import logging
import warnings
from typing import Optional

import numpy as np
import pandas as pd

try:
    import pandas_ta as ta
    _HAS_TA = True
except ImportError:
    _HAS_TA = False
    warnings.warn("pandas_ta non disponibile — uso implementazioni manuali.")

logger = logging.getLogger(__name__)

# Righe minime per calcolare tutti gli indicatori significativi
MIN_ROWS = 220


# ---------------------------------------------------------------------------
# Implementazioni manuali di fallback
# ---------------------------------------------------------------------------

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def _rsi_manual(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr_manual(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _macd_manual(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast   = _ema(close, fast)
    ema_slow   = _ema(close, slow)
    macd_line  = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    histogram  = macd_line - signal_line
    return macd_line, signal_line, histogram


def _bbands_manual(close: pd.Series, period: int = 20, std: float = 2.0):
    mid  = close.rolling(period).mean()
    std_ = close.rolling(period).std()
    upper = mid + std * std_
    lower = mid - std * std_
    return lower, mid, upper


def _stoch_rsi_manual(rsi: pd.Series, period: int = 14) -> tuple[pd.Series, pd.Series]:
    rsi_min = rsi.rolling(period).min()
    rsi_max = rsi.rolling(period).max()
    stoch_k = (rsi - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan) * 100
    stoch_d = stoch_k.rolling(3).mean()
    return stoch_k, stoch_d


def _obv_manual(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff())
    return (direction * volume).fillna(0).cumsum()


def _mfi_manual(high: pd.Series, low: pd.Series, close: pd.Series,
                volume: pd.Series, period: int = 14) -> pd.Series:
    tp = (high + low + close) / 3
    rmf = tp * volume
    pos_flow = rmf.where(tp > tp.shift(1), 0)
    neg_flow = rmf.where(tp < tp.shift(1), 0)
    mfr = pos_flow.rolling(period).sum() / neg_flow.rolling(period).sum().replace(0, np.nan)
    return 100 - (100 / (1 + mfr))


def _roc_manual(close: pd.Series, period: int = 10) -> pd.Series:
    return (close / close.shift(period) - 1) * 100


def _adx_manual(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()

    up_move   = high - high.shift()
    down_move = low.shift() - low

    pos_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    neg_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    smooth_pos = pos_dm.ewm(span=period, adjust=False).mean()
    smooth_neg = neg_dm.ewm(span=period, adjust=False).mean()

    pdi = 100 * smooth_pos / atr.replace(0, np.nan)
    ndi = 100 * smooth_neg / atr.replace(0, np.nan)
    dx  = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    return dx.ewm(span=period, adjust=False).mean()


# ---------------------------------------------------------------------------
# Funzione principale
# ---------------------------------------------------------------------------

def compute_indicators(df_raw: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    Aggiunge tutti gli indicatori tecnici al DataFrame OHLCV.

    Parameters
    ----------
    df_raw : pd.DataFrame
        DataFrame con colonne: Open, High, Low, Close, Volume.
        Index: DatetimeIndex.

    Returns
    -------
    pd.DataFrame con indicatori aggiunti, oppure None se i dati sono
    insufficienti o completamente corrotti.
    """
    required_cols = {"Open", "High", "Low", "Close", "Volume"}
    if not required_cols.issubset(df_raw.columns):
        logger.debug(f"[indicators] Colonne mancanti: {required_cols - set(df_raw.columns)}")
        return None

    df = df_raw.copy()
    df = df.dropna(subset=["Close", "High", "Low"])

    if len(df) < MIN_ROWS:
        return None

    close  = df["Close"]
    high   = df["High"]
    low    = df["Low"]
    volume = df["Volume"].fillna(0)

    try:
        # --- Trend (medie mobili) ---
        if _HAS_TA:
            df["SMA_200"] = ta.sma(close, length=200)
            df["SMA_50"]  = ta.sma(close, length=50)
            df["EMA_21"]  = ta.ema(close, length=21)
            df["EMA_9"]   = ta.ema(close, length=9)
        else:
            df["SMA_200"] = _sma(close, 200)
            df["SMA_50"]  = _sma(close, 50)
            df["EMA_21"]  = _ema(close, 21)
            df["EMA_9"]   = _ema(close, 9)

        # --- Volatilità ---
        if _HAS_TA:
            df["ATR"] = ta.atr(high, low, close, length=14)
            bb = ta.bbands(close, length=20, std=2)
            if bb is not None and not bb.empty:
                df["BBL"] = bb.iloc[:, 0]
                df["BBM"] = bb.iloc[:, 1]
                df["BBU"] = bb.iloc[:, 2]
            else:
                df["BBL"], df["BBM"], df["BBU"] = _bbands_manual(close)
        else:
            df["ATR"] = _atr_manual(high, low, close, 14)
            df["BBL"], df["BBM"], df["BBU"] = _bbands_manual(close)

        # Volatilità storica annualizzata (20 giorni)
        df["HIST_VOL"] = close.pct_change().rolling(20).std() * np.sqrt(252) * 100

        # --- Momentum ---
        if _HAS_TA:
            df["RSI"] = ta.rsi(close, length=14)
            macd_res  = ta.macd(close)
            if macd_res is not None and not macd_res.empty:
                df["MACD"]        = macd_res.iloc[:, 0]
                df["MACD_SIGNAL"] = macd_res.iloc[:, 2]
                df["MACD_HIST"]   = macd_res.iloc[:, 1]
            else:
                df["MACD"], df["MACD_SIGNAL"], df["MACD_HIST"] = _macd_manual(close)
        else:
            df["RSI"] = _rsi_manual(close)
            df["MACD"], df["MACD_SIGNAL"], df["MACD_HIST"] = _macd_manual(close)

        # Stochastic RSI
        k, d = _stoch_rsi_manual(df["RSI"])
        df["STOCH_K"] = k
        df["STOCH_D"] = d

        # Rate of Change
        df["ROC_10"] = _roc_manual(close, 10)
        df["ROC_20"] = _roc_manual(close, 20)

        # --- Forza relativa / Volume ---
        if _HAS_TA:
            df["OBV"] = ta.obv(close, volume)
            df["MFI"] = ta.mfi(high, low, close, volume, length=14)
        else:
            df["OBV"] = _obv_manual(close, volume)
            df["MFI"] = _mfi_manual(high, low, close, volume, 14)

        # VWAP (rolling 20 giorni — il vero VWAP intraday non è calcolabile con dati daily)
        typical_price = (high + low + close) / 3
        df["VWAP_20"] = (typical_price * volume).rolling(20).sum() / volume.rolling(20).sum()

        # --- Trend Strength ---
        df["ADX"] = _adx_manual(high, low, close, 14)

        # --- Supporti / Resistenze dinamiche ---
        df["PIVOT"] = (high + low + close) / 3
        df["SUPPORT_20"]    = low.rolling(20).min()
        df["RESISTANCE_20"] = high.rolling(20).max()
        df["SUPPORT_50"]    = low.rolling(50).min()
        df["RESISTANCE_50"] = high.rolling(50).max()

        # --- Massimi/minimi rolling ---
        df["HIGH_52W"] = high.rolling(252).max()
        df["LOW_52W"]  = low.rolling(252).min()

        # --- OBV trend (slope 20g) ---
        obv = df["OBV"]
        df["OBV_TREND"] = obv - obv.shift(20)

        # Rimuovi righe con troppi NaN (tipicamente le prime ~200)
        df_clean = df.dropna(subset=["SMA_200", "RSI", "MACD", "ATR", "BBL"])
        if df_clean.empty:
            return None

        return df_clean

    except Exception as e:
        logger.error(f"[indicators] Errore nel calcolo: {e}", exc_info=True)
        return None
