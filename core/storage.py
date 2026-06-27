"""
Storage Layer — InvestAI
Persistenza locale JSON completamente offline.
Tutte le scritture sono atomiche (write-then-rename).
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Cartella dati: rispetto alla root del progetto
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Chiavi dei file JSON
_FILE_TRANSACTIONS = DATA_DIR / "transactions.json"
_FILE_WATCHLIST    = DATA_DIR / "watchlist.json"
_FILE_SETTINGS     = DATA_DIR / "settings.json"

# Lock per evitare scritture concorrenti (Streamlit può avere thread multipli)
_locks: dict[Path, threading.Lock] = {
    _FILE_TRANSACTIONS: threading.Lock(),
    _FILE_WATCHLIST:    threading.Lock(),
    _FILE_SETTINGS:     threading.Lock(),
}


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read(path: Path, default: Any) -> Any:
    """Legge un file JSON; ritorna `default` se mancante o corrotto."""
    _ensure_data_dir()
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"[storage] Lettura fallita per {path.name}: {e} — uso default.")
        return default


def _write(path: Path, data: Any) -> None:
    """Scrittura atomica: scrive su file temporaneo, poi rinomina."""
    _ensure_data_dir()
    lock = _locks[path]
    with lock:
        try:
            fd, tmp_path = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            except Exception:
                os.unlink(tmp_path)
                raise
            # Rinomina atomica (su POSIX è atomica, su Windows è best-effort)
            shutil.move(tmp_path, str(path))
        except OSError as e:
            logger.error(f"[storage] Scrittura fallita per {path.name}: {e}")
            raise


# ---------------------------------------------------------------------------
# TRANSACTIONS
# ---------------------------------------------------------------------------

def load_transactions() -> list[dict]:
    """Ritorna lista di transazioni, già ordinate per data desc."""
    raw = _read(_FILE_TRANSACTIONS, [])
    if not isinstance(raw, list):
        return []
    return raw


def save_transactions(txs: list[dict]) -> None:
    _write(_FILE_TRANSACTIONS, txs)


def add_transaction(tx: dict) -> None:
    """Aggiunge una transazione e incrementa l'ID auto."""
    txs = load_transactions()
    tx["id"] = max((t.get("id", 0) for t in txs), default=0) + 1
    txs.append(tx)
    save_transactions(txs)


def update_transaction(tx_id: int, updated: dict) -> bool:
    txs = load_transactions()
    for i, t in enumerate(txs):
        if t.get("id") == tx_id:
            txs[i] = {**t, **updated, "id": tx_id}
            save_transactions(txs)
            return True
    return False


def delete_transaction(tx_id: int) -> bool:
    txs = load_transactions()
    new_txs = [t for t in txs if t.get("id") != tx_id]
    if len(new_txs) == len(txs):
        return False
    save_transactions(new_txs)
    return True


# ---------------------------------------------------------------------------
# WATCHLIST
# ---------------------------------------------------------------------------

def load_watchlist() -> dict[str, str]:
    """Ritorna {Nome: Ticker}."""
    raw = _read(_FILE_WATCHLIST, {})
    if not isinstance(raw, dict):
        return {}
    return raw


def save_watchlist(watchlist: dict[str, str]) -> None:
    _write(_FILE_WATCHLIST, watchlist)


def add_to_watchlist(name: str, ticker: str) -> None:
    wl = load_watchlist()
    wl[name] = ticker.upper()
    save_watchlist(wl)


def remove_from_watchlist(ticker: str) -> bool:
    wl = load_watchlist()
    to_remove = [k for k, v in wl.items() if v == ticker.upper()]
    if not to_remove:
        return False
    for k in to_remove:
        del wl[k]
    save_watchlist(wl)
    return True


# ---------------------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------------------

def load_settings() -> dict:
    raw = _read(_FILE_SETTINGS, {})
    if not isinstance(raw, dict):
        return {}
    return raw


def save_settings(settings: dict) -> None:
    _write(_FILE_SETTINGS, settings)


def get_setting(key: str, default: Any = None) -> Any:
    return load_settings().get(key, default)


def set_setting(key: str, value: Any) -> None:
    s = load_settings()
    s[key] = value
    save_settings(s)
