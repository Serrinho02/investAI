"""
Telegram Bot — InvestAI (Single-User)
- Chat ID salvato in settings.json
- Il bot è completamente opzionale
- Non rompe l'app se TELEGRAM_TOKEN è mancante
- /start salva il chat_id, /stop lo cancella
"""
from __future__ import annotations

import logging
import os
import time
import threading
from datetime import datetime

import schedule

from core.storage import get_setting, set_setting, load_settings
from core.market_data import get_data_raw
from core.portfolio import get_portfolio_summary
from core.assets import AUTO_SCAN_TICKERS
from engine.indicators import compute_indicators
from engine.scoring import analyze, portfolio_advice

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_TOKEN", "")

# Bot globale — None se il token non è disponibile
bot = None
_bot_initialized = False


def _init_bot():
    """Inizializza telebot solo se il token è disponibile."""
    global bot, _bot_initialized
    if _bot_initialized:
        return bot
    _bot_initialized = True

    if not TELEGRAM_BOT_TOKEN:
        logger.info("[telegram] TELEGRAM_TOKEN non configurato. Bot disabilitato.")
        return None

    try:
        import telebot
        bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, parse_mode="HTML")
        _register_handlers(bot)
        logger.info("[telegram] Bot inizializzato con successo.")
    except ImportError:
        logger.warning("[telegram] pyTelegramBotAPI non installato.")
        bot = None
    except Exception as e:
        logger.warning(f"[telegram] Inizializzazione fallita: {e}")
        bot = None

    return bot


def _get_chat_id() -> str:
    return str(get_setting("telegram_chat_id", ""))


def _register_handlers(b):
    """Registra i comandi sul bot Telegram."""

    @b.message_handler(commands=["start"])
    def cmd_start(message):
        chat_id = str(message.chat.id)
        set_setting("telegram_chat_id", chat_id)
        b.reply_to(
            message,
            f"✅ <b>InvestAI Bot attivo!</b>\n\n"
            f"Chat ID <code>{chat_id}</code> salvato.\n"
            f"Riceverai il report automatico ogni mattina.\n\n"
            f"<b>Comandi:</b>\n"
            f"/portafoglio — Analisi del portafoglio\n"
            f"/mercato — Scansione opportunità\n"
            f"/stop — Disattiva notifiche",
        )

    @b.message_handler(commands=["stop"])
    def cmd_stop(message):
        set_setting("telegram_chat_id", "")
        b.reply_to(
            message,
            "🔕 Notifiche disattivate.\n"
            "Puoi sempre usare /portafoglio e /mercato manualmente.\n"
            "Digita /start per riabilitarle.",
        )

    @b.message_handler(commands=["portafoglio"])
    def cmd_portfolio(message):
        chat_id = str(message.chat.id)
        b.send_message(chat_id, "⏳ Analisi portafoglio in corso...")

        pf, _ = get_portfolio_summary()
        if not pf:
            b.send_message(chat_id, "Il portafoglio è vuoto.")
            return

        all_tickers = list(pf.keys())
        market_data = get_data_raw(all_tickers)

        msgs: list[str] = []
        for ticker, pos in pf.items():
            if ticker not in market_data:
                continue
            df_ind = compute_indicators(market_data[ticker])
            if df_ind is None:
                continue

            cur_price = float(df_ind["Close"].iloc[-1])
            adv  = portfolio_advice(df_ind, pos["avg_price"], cur_price)
            res  = analyze(df_ind, ticker)
            pnl  = adv.pnl_pct
            emoji = "🟢" if pnl > 0 else "🔴"

            msgs.append(
                f"{emoji} <b>{ticker}</b>: {pnl:+.1f}%\n"
                f"📢 <b>{adv.title}</b>\n"
                f"🛡️ Trailing Stop: <b>${adv.trailing_stop:.2f}</b>\n"
                f"🎯 Target: ${res.target:.2f} (+{res.upside_pct:.1f}%)\n"
                f"🏆 Score: <b>{res.confidence_score}/100</b>\n"
                f"<i>{adv.advice}</i>"
            )

        if msgs:
            b.send_message(chat_id, "💼 <b>PORTAFOGLIO</b>\n\n" + "\n\n".join(msgs))
        else:
            b.send_message(chat_id, "Impossibile scaricare i dati.")

    @b.message_handler(commands=["mercato"])
    def cmd_market(message):
        chat_id = str(message.chat.id)
        b.send_message(chat_id, "🔎 Scansione mercato in corso...")

        market_data = get_data_raw(AUTO_SCAN_TICKERS)
        opportunities: list[tuple[int, str]] = []

        for ticker in AUTO_SCAN_TICKERS:
            if ticker not in market_data:
                continue
            df_ind = compute_indicators(market_data[ticker])
            if df_ind is None:
                continue
            res = analyze(df_ind, ticker)
            if res.signal in ("BUY_STRONG", "BUY") and res.confidence_score >= 40:
                icon = "💎" if res.signal == "BUY_STRONG" else "🟢"
                msg  = (
                    f"{icon} <b>{ticker}</b>: {res.action_label}\n"
                    f"🏆 Score: <b>{res.confidence_score}/100</b>\n"
                    f"Prezzo: ${res.last_price:.2f} | RSI: {res.rsi:.0f}\n"
                    f"🎯 Upside: +{res.upside_pct:.1f}%\n"
                    f"<i>{res.reasons[0] if res.reasons else ''}</i>"
                )
                opportunities.append((res.confidence_score, msg))

        if opportunities:
            opportunities.sort(reverse=True)
            text = "🚀 <b>TOP OPPORTUNITÀ</b>\n\n" + "\n\n".join(m for _, m in opportunities[:10])
            b.send_message(chat_id, text)
        else:
            b.send_message(chat_id, "Nessuna occasione rilevata al momento.")

    @b.message_handler(commands=["help"])
    def cmd_help(message):
        b.send_message(
            message.chat.id,
            "📱 <b>COMANDI</b>\n\n"
            "/start — Attiva notifiche automatiche\n"
            "/portafoglio — Analisi del tuo portafoglio\n"
            "/mercato — Scansiona nuove opportunità\n"
            "/stop — Disattiva il report giornaliero\n"
            "/help — Questo messaggio\n\n"
            "<i>⚠️ InvestAI è uno strumento informativo. Non costituisce consulenza finanziaria.</i>",
        )


# ---------------------------------------------------------------------------
# Report giornaliero
# ---------------------------------------------------------------------------

def _send_daily_report():
    """Invia il report automatico mattutino (se configurato)."""
    if bot is None:
        return

    chat_id = _get_chat_id()
    if not chat_id:
        logger.info("[telegram] Nessun chat_id configurato, skip report.")
        return

    logger.info(f"[telegram] Report giornaliero: {datetime.now()}")

    pf, _ = get_portfolio_summary()
    owned_tickers = list(pf.keys())
    all_tickers   = list(set(owned_tickers + AUTO_SCAN_TICKERS))
    market_data   = get_data_raw(all_tickers)

    messages: list[str] = []

    # Portafoglio: solo alert urgenti
    for ticker, pos in pf.items():
        if ticker not in market_data:
            continue
        df_ind = compute_indicators(market_data[ticker])
        if df_ind is None:
            continue
        cur_price = float(df_ind["Close"].iloc[-1])
        adv = portfolio_advice(df_ind, pos["avg_price"], cur_price)
        if any(k in adv.title for k in ["PERICOLO", "INCASSA", "PROTEGGI", "LASCIA CORRERE"]):
            pnl = adv.pnl_pct
            messages.append(f"🚨 <b>{ticker}</b> ({pnl:+.1f}%): {adv.title}")

    # Mercato: Golden + alta confidence
    for ticker in AUTO_SCAN_TICKERS:
        if ticker in owned_tickers or ticker not in market_data:
            continue
        df_ind = compute_indicators(market_data[ticker])
        if df_ind is None:
            continue
        res = analyze(df_ind, ticker)
        if res.signal == "BUY_STRONG":
            messages.append(f"💎 <b>{ticker} – GOLDEN!</b> (+{res.upside_pct:.1f}%) [Score: {res.confidence_score}]")
        elif res.signal == "BUY" and res.confidence_score >= 60:
            messages.append(f"🟢 <b>{ticker} – BUY</b> (+{res.upside_pct:.1f}%) [Score: {res.confidence_score}]")

    if messages:
        text = f"🌅 <b>Buongiorno! Report InvestAI</b>\n\n" + "\n\n".join(messages[:8])
        try:
            bot.send_message(chat_id, text)
            logger.info("[telegram] Report inviato.")
        except Exception as e:
            logger.error(f"[telegram] Errore invio report: {e}")
    else:
        logger.info("[telegram] Nessuna novità rilevante, report non inviato.")


# ---------------------------------------------------------------------------
# Scheduler e avvio
# ---------------------------------------------------------------------------

def run_scheduler():
    """Loop dello scheduler giornaliero (eseguito in thread daemon)."""
    schedule.every().day.at("08:00").do(_send_daily_report)
    logger.info("[telegram] Scheduler attivo (08:00 UTC).")
    while True:
        try:
            schedule.run_pending()
            time.sleep(60)
        except Exception as e:
            logger.error(f"[telegram] Scheduler error: {e}")
            time.sleep(60)


def start_bot_threads():
    """
    Avvia il bot e lo scheduler in thread daemon.
    Chiamare una sola volta all'avvio dell'app (con @st.cache_resource).
    """
    b = _init_bot()
    if b is None:
        return

    def _polling():
        try:
            b.remove_webhook()
            time.sleep(1)
            b.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"[telegram] Polling error: {e}")

    t_bot   = threading.Thread(target=_polling,       daemon=True, name="tg-polling")
    t_sched = threading.Thread(target=run_scheduler,  daemon=True, name="tg-scheduler")
    t_bot.start()
    t_sched.start()
    logger.info("[telegram] Thread polling e scheduler avviati.")
