"""
Market Data Layer — InvestAI
Download dati da Yahoo Finance con:
 - cache in-process (TTL 10 min)
 - retry esponenziale
 - timeout
 - gestione ticker delistati / mercati chiusi / simboli errati
 - nessun download doppio per lo stesso ticker
"""
from __future__ import annotations

import logging
import time
import threading
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache in-process
# ---------------------------------------------------------------------------
_cache_lock = threading.Lock()
_cache: dict[str, tuple[pd.DataFrame, datetime]] = {}   # ticker -> (df, timestamp)
_CACHE_TTL_SECONDS = 600   # 10 minuti


def _get_cached(ticker: str) -> Optional[pd.DataFrame]:
    with _cache_lock:
        entry = _cache.get(ticker)
        if entry is None:
            return None
        df, ts = entry
        if datetime.utcnow() - ts > timedelta(seconds=_CACHE_TTL_SECONDS):
            del _cache[ticker]
            return None
        return df


def _set_cached(ticker: str, df: pd.DataFrame) -> None:
    with _cache_lock:
        _cache[ticker] = (df, datetime.utcnow())


def clear_cache() -> None:
    """Svuota la cache manualmente (es. dopo un refresh forzato)."""
    with _cache_lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

_PERIOD = "2y"
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF  = 2.0   # secondi, raddoppia ad ogni tentativo


def _download_single(ticker: str) -> Optional[pd.DataFrame]:
    """
    Scarica 2 anni di dati per un singolo ticker.
    Ritorna None se il ticker non esiste o i dati sono insufficienti.
    """
    cached = _get_cached(ticker)
    if cached is not None:
        return cached

    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            raw = yf.download(
                ticker,
                period=_PERIOD,
                progress=False,
                auto_adjust=False,
                timeout=15,
            )

            # yfinance può ritornare MultiIndex anche per singolo ticker
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)

            if raw.empty or "Close" not in raw.columns:
                logger.debug(f"[market] {ticker}: nessun dato restituito.")
                return None

            raw = raw.dropna(subset=["Close"])

            if len(raw) < 30:
                logger.debug(f"[market] {ticker}: dati insufficienti ({len(raw)} righe).")
                return None

            _set_cached(ticker, raw)
            return raw

        except Exception as e:
            wait = _RETRY_BACKOFF ** attempt
            logger.warning(f"[market] {ticker} tentativo {attempt}/{_RETRY_ATTEMPTS}: {e}. Attendo {wait:.1f}s")
            if attempt < _RETRY_ATTEMPTS:
                time.sleep(wait)

    return None


def get_data_raw(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """
    Scarica i dati per una lista di ticker.
    Ritorna { ticker: DataFrame } per i ticker scaricati con successo.
    I ticker già in cache non vengono riscaricati.
    """
    if not tickers:
        return {}

    unique = list(dict.fromkeys(t.strip().upper() for t in tickers if t))

    # Separa ticker già in cache da quelli da scaricare
    result: dict[str, pd.DataFrame] = {}
    to_download: list[str] = []

    for t in unique:
        cached = _get_cached(t)
        if cached is not None:
            result[t] = cached
        else:
            to_download.append(t)

    if not to_download:
        return result

    # Batch download per ridurre le chiamate HTTP
    # yfinance è più efficiente con batch, ma il parsing MultiIndex è delicato;
    # usiamo un approccio ibrido: batch per gruppi, fallback singolo se parsing fallisce.
    BATCH_SIZE = 30
    for i in range(0, len(to_download), BATCH_SIZE):
        batch = to_download[i : i + BATCH_SIZE]
        _download_batch(batch, result)

    return result


def _download_batch(tickers: list[str], result: dict) -> None:
    """Scarica un batch di ticker. Fallback singolo in caso di errore."""
    if len(tickers) == 1:
        df = _download_single(tickers[0])
        if df is not None:
            result[tickers[0]] = df
        return

    try:
        raw = yf.download(
            tickers,
            period=_PERIOD,
            group_by="ticker",
            progress=False,
            auto_adjust=False,
            timeout=30,
        )

        if raw.empty:
            raise ValueError("DataFrame vuoto")

        for t in tickers:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    if t in raw.columns.get_level_values(0):
                        df = raw[t].copy()
                    else:
                        raise KeyError(t)
                else:
                    # Un solo ticker restituisce colonne flat
                    df = raw.copy()

                df = df.dropna(subset=["Close"])
                if len(df) >= 30:
                    _set_cached(t, df)
                    result[t] = df
                else:
                    logger.debug(f"[market] {t}: solo {len(df)} righe dopo il batch.")
            except (KeyError, Exception) as e:
                logger.debug(f"[market] {t}: estrazione dal batch fallita ({e}), retry singolo.")
                single = _download_single(t)
                if single is not None:
                    result[t] = single

    except Exception as e:
        logger.warning(f"[market] Batch download fallito: {e}. Fallback a singoli.")
        for t in tickers:
            single = _download_single(t)
            if single is not None:
                result[t] = single


def validate_ticker(ticker: str) -> bool:
    """Verifica che un ticker esista su Yahoo Finance."""
    if not ticker:
        return False
    try:
        df = yf.download(ticker, period="5d", progress=False, timeout=10)
        return not df.empty
    except Exception:
        return False
