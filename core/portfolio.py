"""
Portfolio Engine — InvestAI
Calcolo del portafoglio a partire dalle transazioni locali.
Nessuna dipendenza da database esterno.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import pandas as pd

from core.storage import load_transactions

logger = logging.getLogger(__name__)


def get_portfolio_summary() -> tuple[dict, list[dict]]:
    """
    Calcola lo stato attuale del portafoglio da tutte le transazioni.

    Returns
    -------
    portfolio : dict
        { ticker: { qty, total_cost, avg_price } }
        Contiene solo asset con quantità > 0.
    history : list[dict]
        Lista ordinata (per data) di tutte le transazioni.
    """
    txs = load_transactions()
    if not txs:
        return {}, []

    # Ordina per data (asc) per elaborare in ordine cronologico
    txs_sorted = sorted(txs, key=lambda t: t.get("date", ""))

    portfolio: dict[str, dict] = {}
    history: list[dict] = []

    for tx in txs_sorted:
        sym: str  = str(tx.get("symbol", "")).upper()
        qty: float = float(tx.get("quantity", 0.0))
        price: float = float(tx.get("price", 0.0))
        tx_type: str = str(tx.get("type", "BUY")).upper()
        fee: float = float(tx.get("fee", 0.0))
        tx_date: str = str(tx.get("date", ""))

        if not sym or qty <= 0 or price <= 0:
            continue

        if sym not in portfolio:
            portfolio[sym] = {"qty": 0.0, "total_cost": 0.0, "avg_price": 0.0}

        pos = portfolio[sym]

        if tx_type == "BUY":
            pos["qty"] += qty
            pos["total_cost"] += (qty * price) + fee

        elif tx_type == "SELL":
            # Riduce il costo medio proporzionalmente (FIFO semplificato)
            sold_qty = min(qty, pos["qty"])  # non si può vendere più di quanto si possiede
            if pos["qty"] > 1e-9:
                avg = pos["total_cost"] / pos["qty"]
                pos["total_cost"] = max(0.0, pos["total_cost"] - avg * sold_qty)
            pos["qty"] = max(0.0, pos["qty"] - sold_qty)

        # Ricalcola avg_price
        if pos["qty"] > 1e-9:
            pos["avg_price"] = pos["total_cost"] / pos["qty"]
        else:
            pos["avg_price"] = 0.0
            pos["total_cost"] = 0.0

        history.append({
            "id": tx.get("id"),
            "symbol": sym,
            "quantity": qty,
            "price": price,
            "date": tx_date,
            "type": tx_type,
            "fee": fee,
        })

    # Filtra asset chiusi
    active_portfolio = {k: v for k, v in portfolio.items() if v["qty"] > 1e-6}

    return active_portfolio, history


def get_historical_portfolio_value(
    transactions: list[dict],
    market_data: dict,
) -> pd.DataFrame:
    """
    Ricostruisce il valore storico giornaliero del portafoglio.

    Parameters
    ----------
    transactions : list[dict]
        Lista transazioni (come da load_transactions).
    market_data : dict
        { ticker: DataFrame con colonna 'Close' e index DatetimeIndex }

    Returns
    -------
    pd.DataFrame con colonne:
        - Total Value    : valore di mercato del portafoglio
        - Total Invested : costo totale investito (cost basis)
        - <TICKER>       : valore di mercato per ogni asset
    """
    if not transactions:
        return pd.DataFrame()

    df_tx = pd.DataFrame(transactions)
    df_tx["date"] = pd.to_datetime(df_tx["date"], errors="coerce")
    df_tx = df_tx.dropna(subset=["date"]).sort_values("date")

    if df_tx.empty:
        return pd.DataFrame()

    start_date = df_tx["date"].min().normalize()
    end_date   = pd.Timestamp.today().normalize()
    date_range = pd.date_range(start=start_date, end=end_date, freq="D")

    unique_tickers: list[str] = df_tx["symbol"].unique().tolist()

    # Matrice dei prezzi giornalieri (forward-fill + backward-fill)
    price_matrix = pd.DataFrame(index=date_range)
    for t in unique_tickers:
        if t in market_data and not market_data[t].empty:
            price_matrix[t] = (
                market_data[t]["Close"]
                .reindex(date_range)
                .ffill()
                .bfill()
            )
        else:
            price_matrix[t] = 0.0

    # Stato del portafoglio: simulazione giorno per giorno
    state: dict[str, dict] = {t: {"qty": 0.0, "cost": 0.0} for t in unique_tickers}
    records: list[dict] = []

    tx_by_date = df_tx.groupby(df_tx["date"].dt.normalize())

    for current_date in date_range:
        # Applica le transazioni del giorno
        if current_date in tx_by_date.groups:
            for _, tx in tx_by_date.get_group(current_date).iterrows():
                sym   = str(tx["symbol"]).upper()
                qty   = float(tx.get("quantity", 0.0))
                price = float(tx.get("price", 0.0))
                fee   = float(tx.get("fee", 0.0))
                ttype = str(tx.get("type", "BUY")).upper()

                if sym not in state:
                    state[sym] = {"qty": 0.0, "cost": 0.0}

                pos = state[sym]
                if ttype == "BUY":
                    pos["qty"]  += qty
                    pos["cost"] += (qty * price) + fee
                elif ttype == "SELL":
                    sold = min(qty, pos["qty"])
                    if pos["qty"] > 1e-9:
                        avg = pos["cost"] / pos["qty"]
                        pos["cost"] = max(0.0, pos["cost"] - avg * sold)
                    pos["qty"] = max(0.0, pos["qty"] - sold)

        # Calcola valori del giorno
        day_value    = 0.0
        day_invested = 0.0
        asset_values: dict[str, float] = {}

        for sym in unique_tickers:
            pos          = state[sym]
            mkt_price    = price_matrix.at[current_date, sym] if sym in price_matrix.columns else 0.0
            asset_val    = pos["qty"] * mkt_price
            day_value   += asset_val
            day_invested += pos["cost"]
            asset_values[sym] = asset_val

        records.append({
            "Total Value":    day_value,
            "Total Invested": day_invested,
            **asset_values,
        })

    return pd.DataFrame(records, index=date_range)


def compute_first_buy_dates(transactions: list[dict]) -> dict[str, date]:
    """Ritorna la prima data di acquisto per ciascun ticker."""
    result: dict[str, date] = {}
    for tx in transactions:
        if str(tx.get("type", "")).upper() != "BUY":
            continue
        sym = str(tx.get("symbol", "")).upper()
        try:
            d = datetime.strptime(str(tx["date"]), "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        if sym not in result or d < result[sym]:
            result[sym] = d
    return result
